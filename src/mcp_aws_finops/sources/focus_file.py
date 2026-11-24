"""`CostSource` implementation backed by a FOCUS-format file (or directory
of files), queried with DuckDB.

FOCUS (FinOps Open Cost and Usage Specification) columns used here:
    BilledCost, EffectiveCost, BillingCurrency, ServiceName, ServiceCategory,
    ChargePeriodStart, ChargePeriodEnd, RegionId, SubAccountId,
    SubAccountName, ResourceId, ResourceType, Tags (JSON object as string),
    ChargeCategory, PricingUnit, ConsumedQuantity, UsageAmount.

In addition, the bundled sample data (and any file produced by
`scripts/generate_sample.py`) carries a handful of provider-extension
columns, prefixed `x_` as the FOCUS spec allows, that encode operational
signals real AWS billing/usage exports don't carry on their own but which
are needed for the idle-resource heuristics below:
    x_Attached (bool)              -- EBS volume currently attached to an instance
    x_AssociatedInstanceId (str)   -- Elastic IP's associated EC2 instance, if any
    x_AgeDays (int)                -- age of a snapshot/resource in days
    x_AvgCpuUtilization (float)    -- trailing average CPU%, for EC2/RDS instances

Idle resource heuristics (`idle_resources`), evaluated over the trailing
`lookback_days` window ending on `as_of`:
    1. Unattached EBS volume   -- ResourceType = 'EBS Volume' and x_Attached = false
    2. Idle Elastic IP         -- ResourceType = 'Elastic IP' and no associated instance
    3. Old EBS snapshot        -- ResourceType = 'EBS Snapshot' and x_AgeDays > 90
    4. Low-usage compute       -- ResourceType in ('EC2 Instance', 'RDS Instance')
                                   and x_AvgCpuUtilization < 5.0
Each match reports the resource's actual billed cost over the window,
annualised to a 30-day month (`estimated_monthly_cost`).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import duckdb

from mcp_aws_finops.models import GroupedCost, IdleResource
from mcp_aws_finops.sources.base import CostSource, GroupBy

_TAG_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

_IDLE_RULES: list[tuple[str, str, str]] = [
    (
        "EBS Volume",
        "x_Attached = false",
        "Unattached EBS volume (not attached to any instance)",
    ),
    (
        "Elastic IP",
        "(x_AssociatedInstanceId IS NULL OR x_AssociatedInstanceId = '')",
        "Idle Elastic IP (not associated with a running instance)",
    ),
    (
        "EBS Snapshot",
        "x_AgeDays > 90",
        "Snapshot older than 90 days",
    ),
    (
        "EC2 Instance",
        "x_AvgCpuUtilization < 5.0",
        "Low-usage EC2 instance (avg CPU < 5%)",
    ),
    (
        "RDS Instance",
        "x_AvgCpuUtilization < 5.0",
        "Low-usage RDS instance (avg CPU < 5%)",
    ),
]


def _group_expr(group_by: GroupBy) -> str:
    """Translate a tool-facing `group_by` value into a SQL expression."""
    if group_by == "service":
        return "ServiceName"
    if group_by == "account":
        return "SubAccountName"
    if group_by == "region":
        return "COALESCE(RegionId, 'global')"
    if group_by.startswith("tag:"):
        key = group_by.removeprefix("tag:")
        if not _TAG_KEY_RE.match(key):
            raise ValueError(f"Invalid tag key: {key!r}")
        return f"COALESCE(json_extract_string(Tags, '$.{key}'), 'untagged')"
    raise ValueError(
        f"Invalid group_by: {group_by!r}. Use 'service', 'account', 'region' or 'tag:<key>'."
    )


class FocusFileSource(CostSource):
    """Reads FOCUS-format billing data (CSV or Parquet, file or directory)."""

    def __init__(self, data_path: str | Path) -> None:
        self._path = Path(data_path)
        if not self._path.exists():
            raise FileNotFoundError(f"FOCUS data path not found: {self._path}")
        self._con = duckdb.connect(database=":memory:")
        self._con.execute(f"CREATE VIEW costs AS SELECT * FROM {self._scan_expr()}")
        self._currency = self._load_currency()

    def _scan_expr(self) -> str:
        target = self._path
        if target.is_dir():
            parquet_files = sorted(target.glob("*.parquet"))
            if parquet_files:
                return f"read_parquet('{target}/*.parquet')"
            return f"read_csv_auto('{target}/*.csv*', union_by_name=true)"
        if target.suffix == ".parquet":
            return f"read_parquet('{target}')"
        return f"read_csv_auto('{target}')"

    def _load_currency(self) -> str:
        row = self._con.execute(
            "SELECT BillingCurrency FROM costs WHERE BillingCurrency IS NOT NULL LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else "USD"

    @property
    def currency(self) -> str:
        return self._currency

    def data_bounds(self) -> tuple[date, date]:
        row = self._con.execute(
            "SELECT MIN(CAST(ChargePeriodStart AS DATE)), MAX(CAST(ChargePeriodStart AS DATE)) "
            "FROM costs"
        ).fetchone()
        if row is None or row[0] is None:
            raise ValueError("No data available in the configured FOCUS source")
        return row[0], row[1]

    def total_cost(self, start: date, end: date) -> float:
        row = self._con.execute(
            "SELECT COALESCE(SUM(BilledCost), 0.0) FROM costs "
            "WHERE CAST(ChargePeriodStart AS DATE) >= ? AND CAST(ChargePeriodStart AS DATE) < ?",
            [start, end],
        ).fetchone()
        return float(row[0]) if row else 0.0

    def cost_summary(self, start: date, end: date, group_by: GroupBy) -> list[GroupedCost]:
        expr = _group_expr(group_by)
        total = self.total_cost(start, end)
        rows = self._con.execute(
            f"SELECT {expr} AS k, COALESCE(SUM(BilledCost), 0.0) AS c FROM costs "
            "WHERE CAST(ChargePeriodStart AS DATE) >= ? AND CAST(ChargePeriodStart AS DATE) < ? "
            "GROUP BY k ORDER BY c DESC",
            [start, end],
        ).fetchall()
        return [
            GroupedCost(
                key=str(key),
                cost=float(cost),
                share_pct=(float(cost) / total * 100.0) if total else 0.0,
            )
            for key, cost in rows
        ]

    def daily_cost_series(self, start: date, end: date) -> list[tuple[date, float]]:
        rows = self._con.execute(
            "SELECT CAST(ChargePeriodStart AS DATE) AS d, COALESCE(SUM(BilledCost), 0.0) AS c "
            "FROM costs WHERE CAST(ChargePeriodStart AS DATE) >= ? "
            "AND CAST(ChargePeriodStart AS DATE) < ? GROUP BY d ORDER BY d",
            [start, end],
        ).fetchall()
        by_day = {d: float(c) for d, c in rows}
        days = []
        cur = start
        while cur < end:
            days.append((cur, by_day.get(cur, 0.0)))
            cur += timedelta(days=1)
        return days

    def daily_cost_by_group(
        self, start: date, end: date, group_by: GroupBy
    ) -> dict[date, list[GroupedCost]]:
        expr = _group_expr(group_by)
        rows = self._con.execute(
            f"SELECT CAST(ChargePeriodStart AS DATE) AS d, {expr} AS k, "
            "COALESCE(SUM(BilledCost), 0.0) AS c FROM costs "
            "WHERE CAST(ChargePeriodStart AS DATE) >= ? AND CAST(ChargePeriodStart AS DATE) < ? "
            "GROUP BY d, k ORDER BY d, c DESC",
            [start, end],
        ).fetchall()
        result: dict[date, list[GroupedCost]] = {}
        totals: dict[date, float] = {}
        for d, _k, c in rows:
            totals[d] = totals.get(d, 0.0) + float(c)
        for d, k, c in rows:
            total = totals.get(d, 0.0)
            result.setdefault(d, []).append(
                GroupedCost(
                    key=str(k),
                    cost=float(c),
                    share_pct=(float(c) / total * 100.0) if total else 0.0,
                )
            )
        return result

    def idle_resources(self, as_of: date, lookback_days: int) -> list[IdleResource]:
        start = as_of - timedelta(days=lookback_days)
        resources: list[IdleResource] = []
        for resource_type, condition, reason in _IDLE_RULES:
            rows = self._con.execute(
                f"""
                SELECT ResourceId, AccountKey, RegionId, SUM(BilledCost) AS cost
                FROM (
                    SELECT ResourceId, SubAccountId AS AccountKey, RegionId, BilledCost
                    FROM costs
                    WHERE ResourceType = ?
                      AND CAST(ChargePeriodStart AS DATE) >= ?
                      AND CAST(ChargePeriodStart AS DATE) < ?
                      AND {condition}
                )
                GROUP BY ResourceId, AccountKey, RegionId
                HAVING SUM(BilledCost) > 0
                ORDER BY cost DESC
                """,
                [resource_type, start, as_of],
            ).fetchall()
            for resource_id, account_id, region, cost in rows:
                monthly = (float(cost) / max(lookback_days, 1)) * 30.0
                resources.append(
                    IdleResource(
                        resource_id=str(resource_id),
                        resource_type=resource_type,
                        reason=reason,
                        account_id=str(account_id) if account_id is not None else None,
                        region=str(region) if region is not None else None,
                        estimated_monthly_cost=round(monthly, 2),
                    )
                )
        resources.sort(key=lambda r: r.estimated_monthly_cost, reverse=True)
        return resources

    def close(self) -> None:
        self._con.close()

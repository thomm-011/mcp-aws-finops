"""AWS Cost Explorer / CloudWatch / EC2 backed `CostSource` (M4).

Maps live AWS billing & resource-usage APIs onto the same `CostSource`
contract (and the same pydantic models) that `FocusFileSource` returns,
so every MCP tool works unmodified against either backend.

APIs used (all read-only — see `iam/policy.json` for the exact action list):
    ce:GetCostAndUsage   -- cost_summary / total_cost / daily_cost_series /
                             daily_cost_by_group (GroupBy SERVICE, LINKED_ACCOUNT,
                             REGION, or TAG).
    ce:GetCostForecast   -- not required for data_bounds; a trailing run-rate
                             forecast is computed by the `forecast_month_end`
                             tool itself from `total_cost`, same as the file
                             backend. `get_cost_forecast` is still exposed
                             here as a thin convenience wrapper in case a
                             future tool wants CE's own ML-based forecast.
    ce:GetAnomalies      -- optional hint for `explain_anomaly`; the tool's
                             own trailing-baseline computation always runs
                             too, and remains the source of truth returned
                             to callers (CE anomaly detection needs an
                             Anomaly Monitor to be configured up front, which
                             may not exist in every account).
    ec2:DescribeVolumes / DescribeAddresses / DescribeSnapshots / DescribeInstances
                         -- idle_resources heuristics (unattached EBS volumes,
                            unassociated Elastic IPs, old self-owned snapshots,
                            low-CPU EC2 instances).
    cloudwatch:GetMetricStatistics -- average CPU utilization per EC2 instance
                            over the lookback window, for the low-usage heuristic.

Cost Explorer bills ~US$0.01 per `GetCostAndUsage`/`GetCostForecast` request,
so results are cached in-memory with a short, configurable TTL
(`CostExplorerSource(..., cache_ttl_seconds=...)`).
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from mcp_aws_finops.models import GroupedCost, IdleResource
from mcp_aws_finops.sources.base import CostSource, GroupBy

_GROUP_BY_DIMENSION: dict[str, dict[str, str]] = {
    "service": {"Type": "DIMENSION", "Key": "SERVICE"},
    "account": {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
    "region": {"Type": "DIMENSION", "Key": "REGION"},
}

_IAM_HINT = (
    "Grant the IAM identity used by this server the read-only policy in "
    "iam/policy.json (ce:GetCostAndUsage, ce:GetCostForecast, ce:GetAnomalies, "
    "ec2:Describe*, cloudwatch:GetMetricStatistics/GetMetricData)."
)


class CostExplorerError(RuntimeError):
    """Raised for AWS-side failures, with a friendly, actionable message."""


def _friendly_aws_error(exc: Exception) -> CostExplorerError:
    """Translate common boto3/botocore failures into an actionable message."""
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    name = type(exc).__name__
    if name in ("NoCredentialsError", "PartialCredentialsError") or (
        code is None and "credential" in str(exc).lower()
    ):
        return CostExplorerError(
            f"No AWS credentials found ({exc}). Configure credentials via a profile "
            f"(--profile), environment variables, or an IAM role, then retry. {_IAM_HINT}"
        )
    if code in ("AccessDeniedException", "AccessDenied", "UnauthorizedOperation"):
        return CostExplorerError(f"AWS denied this request ({code}): {exc}. {_IAM_HINT}")
    if code == "DataUnavailableException":
        return CostExplorerError(
            "Cost Explorer has no data for the requested range yet (it can take up "
            "to 24h after account activation, or data may be outside the 14-month "
            f"retention window). Original error: {exc}"
        )
    return CostExplorerError(f"AWS Cost Explorer/EC2/CloudWatch request failed: {exc}")


def _group_by_spec(group_by: GroupBy) -> dict[str, str]:
    if group_by in _GROUP_BY_DIMENSION:
        return _GROUP_BY_DIMENSION[group_by]
    if group_by.startswith("tag:"):
        return {"Type": "TAG", "Key": group_by.removeprefix("tag:")}
    raise ValueError(
        f"Invalid group_by: {group_by!r}. Use 'service', 'account', 'region' or 'tag:<key>'."
    )


class _TTLCache:
    """Tiny in-memory TTL cache keyed by an arbitrary hashable tuple.

    Cost Explorer calls cost real money (~US$0.01 each), so repeated tool
    calls over the same window within `ttl_seconds` are served from memory.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        if self._ttl <= 0:
            return None
        hit = self._store.get(key)
        if hit is None:
            return None
        expires_at, value = hit
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if self._ttl <= 0:
            return
        self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        self._store.clear()


class CostExplorerSource(CostSource):
    """`CostSource` backed by live `ce`/`ec2`/`cloudwatch` AWS APIs.

    Parameters:
        session: an existing `boto3.Session` (useful for tests with a
            Stubber-wrapped client); if omitted, a default session is
            created lazily from `profile`/`region`/env/instance role.
        region: AWS region for `ec2`/`cloudwatch` calls (Cost Explorer
            itself is a global, us-east-1-only service).
        profile: named AWS CLI profile to use when `session` is not given.
        metric: "UnblendedCost" (default, matches the AWS bill) or
            "AmortizedCost" (spreads Reserved Instance / Savings Plan
            up-front costs over time — often preferred for showback/FinOps).
        cache_ttl_seconds: TTL for the in-memory Cost Explorer response
            cache. 0 disables caching.
        idle_cpu_threshold_pct: average CPU% below which an EC2 instance is
            flagged idle by the CloudWatch heuristic.
        old_snapshot_days: snapshot age (days) above which it is flagged.
    """

    def __init__(
        self,
        *,
        session: Any | None = None,
        region: str = "us-east-1",
        profile: str | None = None,
        metric: str = "UnblendedCost",
        cache_ttl_seconds: float = 300.0,
        idle_cpu_threshold_pct: float = 5.0,
        old_snapshot_days: int = 90,
        ce_client: Any | None = None,
        ec2_client: Any | None = None,
        cloudwatch_client: Any | None = None,
    ) -> None:
        if metric not in ("UnblendedCost", "AmortizedCost"):
            raise ValueError(f"metric must be 'UnblendedCost' or 'AmortizedCost', got {metric!r}")
        self._metric = metric
        self._region = region
        self._idle_cpu_threshold_pct = idle_cpu_threshold_pct
        self._old_snapshot_days = old_snapshot_days
        self._cache = _TTLCache(cache_ttl_seconds)
        self._currency_cache: str | None = None

        if ce_client is not None or ec2_client is not None or cloudwatch_client is not None:
            # Test/advanced seam: pre-built (e.g. Stubber-wrapped) clients.
            self._ce = ce_client
            self._ec2 = ec2_client
            self._cloudwatch = cloudwatch_client
            self._session = session
        else:
            self._session = session
            self._ce = None
            self._ec2 = None
            self._cloudwatch = None
            self._profile = profile

    # -- lazy client construction -------------------------------------------------

    def _get_session(self) -> Any:
        if self._session is None:
            import boto3  # lazy import: keep boto3 optional for --demo/--data users

            self._session = boto3.Session(
                profile_name=getattr(self, "_profile", None), region_name=self._region
            )
        return self._session

    def _client(self, name: str, attr: str) -> Any:
        existing = getattr(self, attr)
        if existing is not None:
            return existing
        try:
            client = self._get_session().client(name, region_name=self._region)
        except Exception as exc:  # pragma: no cover - construction rarely fails
            raise _friendly_aws_error(exc) from exc
        setattr(self, attr, client)
        return client

    @property
    def _ce_client(self) -> Any:
        return self._client("ce", "_ce")

    @property
    def _ec2_client(self) -> Any:
        return self._client("ec2", "_ec2")

    @property
    def _cloudwatch_client(self) -> Any:
        return self._client("cloudwatch", "_cloudwatch")

    # -- Cost Explorer helpers ----------------------------------------------------

    def _paginate_cost_and_usage(self, **kwargs: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            call_kwargs = dict(kwargs)
            if next_token:
                call_kwargs["NextPageToken"] = next_token
            try:
                resp = self._ce_client.get_cost_and_usage(**call_kwargs)
            except Exception as exc:
                raise _friendly_aws_error(exc) from exc
            results.extend(resp.get("ResultsByTime", []))
            next_token = resp.get("NextPageToken")
            if not next_token:
                break
        return results

    def _get_cost_and_usage_cached(
        self, start: date, end: date, group_by_specs: list[dict[str, str]] | None
    ) -> list[dict[str, Any]]:
        key = (
            "gcau",
            start,
            end,
            self._metric,
            tuple(sorted((g["Type"], g["Key"]) for g in (group_by_specs or []))),
        )
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        kwargs: dict[str, Any] = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": "DAILY",
            "Metrics": [self._metric],
        }
        if group_by_specs:
            kwargs["GroupBy"] = group_by_specs
        results = self._paginate_cost_and_usage(**kwargs)
        self._cache.set(key, results)
        return results

    def _detect_currency(self, results: list[dict[str, Any]]) -> str:
        for row in results:
            total = row.get("Total", {}).get(self._metric)
            if total and total.get("Unit"):
                return str(total["Unit"])
            for group in row.get("Groups", []):
                metrics = group.get("Metrics", {}).get(self._metric)
                if metrics and metrics.get("Unit"):
                    return str(metrics["Unit"])
        return "USD"

    @property
    def currency(self) -> str:
        if self._currency_cache is not None:
            return self._currency_cache
        today = date.today()
        results = self._get_cost_and_usage_cached(today - timedelta(days=1), today, None)
        self._currency_cache = self._detect_currency(results) if results else "USD"
        return self._currency_cache

    def total_cost(self, start: date, end: date) -> float:
        if end <= start:
            return 0.0
        results = self._get_cost_and_usage_cached(start, end, None)
        total = 0.0
        for row in results:
            amount = row.get("Total", {}).get(self._metric, {}).get("Amount")
            if amount is not None:
                total += float(amount)
        return total

    def cost_summary(self, start: date, end: date, group_by: GroupBy) -> list[GroupedCost]:
        if end <= start:
            return []
        spec = _group_by_spec(group_by)
        results = self._get_cost_and_usage_cached(start, end, [spec])
        totals: dict[str, float] = {}
        for row in results:
            for group in row.get("Groups", []):
                key = "/".join(group.get("Keys", [])) or "untagged"
                if group_by.startswith("tag:"):
                    key = key.split("$", 1)[-1] or "untagged"
                amount = group.get("Metrics", {}).get(self._metric, {}).get("Amount", "0")
                totals[key] = totals.get(key, 0.0) + float(amount)
        grand_total = sum(totals.values())
        grouped = [
            GroupedCost(
                key=k,
                cost=v,
                share_pct=(v / grand_total * 100.0) if grand_total else 0.0,
            )
            for k, v in totals.items()
        ]
        grouped.sort(key=lambda g: g.cost, reverse=True)
        return grouped

    def daily_cost_series(self, start: date, end: date) -> list[tuple[date, float]]:
        if end <= start:
            return []
        results = self._get_cost_and_usage_cached(start, end, None)
        by_day: dict[date, float] = {}
        for row in results:
            d = date.fromisoformat(row["TimePeriod"]["Start"])
            amount = row.get("Total", {}).get(self._metric, {}).get("Amount", "0")
            by_day[d] = by_day.get(d, 0.0) + float(amount)
        days = []
        cur = start
        while cur < end:
            days.append((cur, by_day.get(cur, 0.0)))
            cur += timedelta(days=1)
        return days

    def daily_cost_by_group(
        self, start: date, end: date, group_by: GroupBy
    ) -> dict[date, list[GroupedCost]]:
        if end <= start:
            return {}
        spec = _group_by_spec(group_by)
        results = self._get_cost_and_usage_cached(start, end, [spec])
        by_day: dict[date, dict[str, float]] = {}
        for row in results:
            d = date.fromisoformat(row["TimePeriod"]["Start"])
            day_totals = by_day.setdefault(d, {})
            for group in row.get("Groups", []):
                key = "/".join(group.get("Keys", [])) or "untagged"
                if group_by.startswith("tag:"):
                    key = key.split("$", 1)[-1] or "untagged"
                amount = group.get("Metrics", {}).get(self._metric, {}).get("Amount", "0")
                day_totals[key] = day_totals.get(key, 0.0) + float(amount)
        result: dict[date, list[GroupedCost]] = {}
        for d, totals in by_day.items():
            day_total = sum(totals.values())
            grouped = [
                GroupedCost(key=k, cost=v, share_pct=(v / day_total * 100.0) if day_total else 0.0)
                for k, v in totals.items()
            ]
            grouped.sort(key=lambda g: g.cost, reverse=True)
            result[d] = grouped
        return result

    def get_cost_forecast(self, start: date, end: date) -> float:
        """Convenience wrapper over `ce:GetCostForecast` (CE's own ML forecast).

        Not used by the shipped `forecast_month_end` tool (which keeps the
        same simple run-rate method as `FocusFileSource` for parity across
        backends), but exposed for callers that want CE's own prediction.
        """
        key = ("forecast", start, end, self._metric)
        cached = self._cache.get(key)
        if cached is not None:
            return float(cached)
        try:
            resp = self._ce_client.get_cost_forecast(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Metric=_forecast_metric_name(self._metric),
                Granularity="MONTHLY",
            )
        except Exception as exc:
            raise _friendly_aws_error(exc) from exc
        total = float(resp.get("Total", {}).get("Amount", 0.0))
        self._cache.set(key, total)
        return total

    def get_anomalies(self, monitor_arn: str, start: date, end: date) -> list[dict[str, Any]]:
        """Thin wrapper over `ce:GetAnomalies` for callers with a configured
        Anomaly Monitor. Returns `[]` (not an error) if CE reports none or
        the account has no monitor configured, so `explain_anomaly`'s own
        baseline computation remains the primary, always-available signal.
        """
        try:
            resp = self._ce_client.get_anomalies(
                MonitorArn=monitor_arn,
                DateInterval={"StartDate": start.isoformat(), "EndDate": end.isoformat()},
            )
        except Exception as exc:
            response = getattr(exc, "response", None) or {}
            code = response.get("Error", {}).get("Code", "")
            if code in ("ResourceNotFoundException", "ValidationException"):
                return []
            raise _friendly_aws_error(exc) from exc
        return list(resp.get("Anomalies", []))

    def data_bounds(self) -> tuple[date, date]:
        today = date.today()
        start = today - timedelta(days=14 * 30)  # CE retains ~14 months
        return start, today - timedelta(days=1)

    # -- idle resources (ec2 + cloudwatch) ----------------------------------------

    def _ec2_paginate(self, method_name: str, result_key: str, **kwargs: Any) -> list[Any]:
        items: list[Any] = []
        next_token: str | None = None
        method = getattr(self._ec2_client, method_name)
        while True:
            call_kwargs = dict(kwargs)
            if next_token:
                call_kwargs["NextToken"] = next_token
            try:
                resp = method(**call_kwargs)
            except Exception as exc:
                raise _friendly_aws_error(exc) from exc
            items.extend(resp.get(result_key, []))
            next_token = resp.get("NextToken")
            if not next_token:
                break
        return items

    def _idle_volumes(self) -> list[IdleResource]:
        volumes = self._ec2_paginate(
            "describe_volumes",
            "Volumes",
            Filters=[{"Name": "status", "Values": ["available"]}],
        )
        resources = []
        for vol in volumes:
            size_gb = vol.get("Size", 0)
            # GP3 list price approx $0.08/GB-month; a rough, documented estimate
            # (billing-API-free so we don't burn a CE call per idle volume).
            est_monthly = round(size_gb * 0.08, 2)
            resources.append(
                IdleResource(
                    resource_id=vol["VolumeId"],
                    resource_type="EBS Volume",
                    reason="Unattached EBS volume (status=available)",
                    account_id=None,
                    region=self._region,
                    estimated_monthly_cost=est_monthly,
                )
            )
        return resources

    def _idle_addresses(self) -> list[IdleResource]:
        resp = self._ec2_paginate("describe_addresses", "Addresses")
        resources = []
        for addr in resp:
            if addr.get("AssociationId"):
                continue
            resources.append(
                IdleResource(
                    resource_id=addr.get("AllocationId", addr.get("PublicIp", "unknown")),
                    resource_type="Elastic IP",
                    reason="Unassociated Elastic IP (no AssociationId)",
                    account_id=None,
                    region=self._region,
                    # AWS charges ~$0.005/hr for an idle EIP -> ~$3.6/month.
                    estimated_monthly_cost=3.6,
                )
            )
        return resources

    def _old_snapshots(self, as_of: date) -> list[IdleResource]:
        snapshots = self._ec2_paginate("describe_snapshots", "Snapshots", OwnerIds=["self"])
        resources = []
        for snap in snapshots:
            start_time = snap.get("StartTime")
            if start_time is None:
                continue
            snap_date = start_time.date() if hasattr(start_time, "date") else start_time
            age_days = (as_of - snap_date).days
            if age_days <= self._old_snapshot_days:
                continue
            size_gb = snap.get("VolumeSize", 0)
            est_monthly = round(size_gb * 0.05, 2)  # EBS snapshot storage ~$0.05/GB-month
            resources.append(
                IdleResource(
                    resource_id=snap["SnapshotId"],
                    resource_type="EBS Snapshot",
                    reason=f"Snapshot older than {self._old_snapshot_days} days (age={age_days}d)",
                    account_id=snap.get("OwnerId"),
                    region=self._region,
                    estimated_monthly_cost=est_monthly,
                )
            )
        return resources

    def _instance_avg_cpu(self, instance_id: str, lookback_days: int) -> float | None:
        end = datetime.now(UTC)
        start = end - timedelta(days=lookback_days)
        try:
            resp = self._cloudwatch_client.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "avg_cpu",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/EC2",
                                "MetricName": "CPUUtilization",
                                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                            },
                            "Period": 86400,
                            "Stat": "Average",
                        },
                    }
                ],
                StartTime=start,
                EndTime=end,
            )
        except Exception as exc:
            raise _friendly_aws_error(exc) from exc
        results = resp.get("MetricDataResults", [])
        values = [v for result in results for v in result.get("Values", [])]
        if not values:
            return None
        return float(sum(values) / len(values))

    def _idle_instances(self, lookback_days: int) -> list[IdleResource]:
        reservations = self._ec2_paginate(
            "describe_instances",
            "Reservations",
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}],
        )
        resources = []
        for reservation in reservations:
            for instance in reservation.get("Instances", []):
                instance_id = instance["InstanceId"]
                avg_cpu = self._instance_avg_cpu(instance_id, lookback_days)
                if avg_cpu is None or avg_cpu >= self._idle_cpu_threshold_pct:
                    continue
                instance_type = instance.get("InstanceType", "unknown")
                # Flat placeholder estimate; real cost would need a pricing
                # API lookup per instance type/region, which is a separate
                # (non read-only-billing) API call this server doesn't make.
                est_monthly = _EC2_MONTHLY_ESTIMATE.get(instance_type, 30.0)
                resources.append(
                    IdleResource(
                        resource_id=instance_id,
                        resource_type="EC2 Instance",
                        reason=f"Low-usage EC2 instance (avg CPU {avg_cpu:.1f}% < "
                        f"{self._idle_cpu_threshold_pct}% over {lookback_days}d)",
                        account_id=None,
                        region=self._region,
                        estimated_monthly_cost=est_monthly,
                    )
                )
        return resources

    def idle_resources(self, as_of: date, lookback_days: int) -> list[IdleResource]:
        resources: list[IdleResource] = []
        resources.extend(self._idle_volumes())
        resources.extend(self._idle_addresses())
        resources.extend(self._old_snapshots(as_of))
        resources.extend(self._idle_instances(lookback_days))
        resources.sort(key=lambda r: r.estimated_monthly_cost, reverse=True)
        return resources

    def clear_cache(self) -> None:
        """Expose cache invalidation for long-running server processes."""
        self._cache.clear()


_EC2_MONTHLY_ESTIMATE: dict[str, float] = {
    "t3.micro": 7.5,
    "t3.small": 15.0,
    "t3.medium": 30.0,
    "t3.large": 60.0,
    "m5.large": 70.0,
    "m5.xlarge": 140.0,
}


def _forecast_metric_name(metric: str) -> str:
    return "UNBLENDED_COST" if metric == "UnblendedCost" else "AMORTIZED_COST"

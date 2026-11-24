"""FastMCP server wiring: tools, one resource, one prompt.

All tools are read-only: they only ever query the configured `CostSource`,
never mutate anything (checked by `tests/test_server_integration.py`, which
asserts that no MCP tool is registered as an AWS write / the FocusFileSource
only opens DuckDB in read mode over a local file).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from mcp.server.fastmcp import FastMCP

from mcp_aws_finops.models import (
    AnomalyContributor,
    ComparePeriodsResult,
    CostByTagResult,
    CostSummaryResult,
    ExplainAnomalyResult,
    FindIdleResourcesResult,
    ForecastMonthEndResult,
    GroupedCost,
    PeriodDriver,
    TagGroupCost,
    TopCostDriversResult,
)
from mcp_aws_finops.sources.base import CostSource

_VALID_GROUP_BY = {"service", "account", "region"}


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field}={value!r}: expected an ISO date, e.g. '2025-07-01'."
        ) from exc


def _validate_range(start: date, end: date) -> None:
    if end <= start:
        raise ValueError(f"end ({end}) must be after start ({start}).")


def _validate_group_by(group_by: str) -> None:
    if group_by in _VALID_GROUP_BY or group_by.startswith("tag:"):
        return
    raise ValueError(
        f"Invalid group_by={group_by!r}. Use one of {sorted(_VALID_GROUP_BY)} or 'tag:<key>'."
    )


def create_server(source: CostSource, *, name: str = "aws-finops") -> FastMCP:
    """Build the FastMCP server for the given (already-configured) CostSource."""
    mcp = FastMCP(name)

    @mcp.tool()
    def get_cost_summary(start: str, end: str, group_by: str = "service") -> CostSummaryResult:
        """Summarize AWS cost for a date range, grouped by a dimension.

        Args:
            start: ISO date (inclusive), e.g. "2025-07-01".
            end: ISO date (exclusive), e.g. "2025-08-01".
            group_by: One of "service", "account", "region", or "tag:<key>"
                (e.g. "tag:team") to break the total down by a cost
                allocation tag.

        Returns the total cost for the period and the cost per group,
        sorted descending, each with its share of the total.
        """
        _validate_group_by(group_by)
        s, e = _parse_date(start, "start"), _parse_date(end, "end")
        _validate_range(s, e)
        groups = source.cost_summary(s, e, group_by)
        total = source.total_cost(s, e)
        return CostSummaryResult(
            start=s,
            end=e,
            group_by=group_by,
            currency=source.currency,
            total_cost=round(total, 2),
            groups=groups,
        )

    @mcp.tool()
    def compare_periods(a_start: str, a_end: str, b_start: str, b_end: str) -> ComparePeriodsResult:
        """Compare total AWS cost between two date ranges and rank what changed.

        Args:
            a_start/a_end: ISO dates for the baseline period (e.g. last month).
            b_start/b_end: ISO dates for the comparison period (e.g. this month).

        Returns the totals for both periods, the delta, and the services
        with the largest absolute cost change (increase or decrease),
        largest first — useful to answer "what went up since last month?".
        """
        a_s, a_e = _parse_date(a_start, "a_start"), _parse_date(a_end, "a_end")
        b_s, b_e = _parse_date(b_start, "b_start"), _parse_date(b_end, "b_end")
        _validate_range(a_s, a_e)
        _validate_range(b_s, b_e)
        total_a = source.total_cost(a_s, a_e)
        total_b = source.total_cost(b_s, b_e)
        by_service_a = {g.key: g.cost for g in source.cost_summary(a_s, a_e, "service")}
        by_service_b = {g.key: g.cost for g in source.cost_summary(b_s, b_e, "service")}
        keys = set(by_service_a) | set(by_service_b)
        drivers = []
        for key in keys:
            ca, cb = by_service_a.get(key, 0.0), by_service_b.get(key, 0.0)
            drivers.append(
                PeriodDriver(
                    key=key,
                    cost_a=round(ca, 2),
                    cost_b=round(cb, 2),
                    delta=round(cb - ca, 2),
                    delta_pct=round((cb - ca) / ca * 100.0, 1) if ca else None,
                )
            )
        drivers.sort(key=lambda d: abs(d.delta), reverse=True)
        delta = total_b - total_a
        return ComparePeriodsResult(
            a_start=a_s,
            a_end=a_e,
            b_start=b_s,
            b_end=b_e,
            total_a=round(total_a, 2),
            total_b=round(total_b, 2),
            delta=round(delta, 2),
            delta_pct=round(delta / total_a * 100.0, 1) if total_a else None,
            currency=source.currency,
            top_drivers=drivers[:10],
        )

    @mcp.tool()
    def top_cost_drivers(start: str, end: str, n: int = 10) -> TopCostDriversResult:
        """Rank the top N services by cost over a date range.

        Args:
            start: ISO date (inclusive).
            end: ISO date (exclusive).
            n: How many drivers to return (1-50).
        """
        if not 1 <= n <= 50:
            raise ValueError(f"n must be between 1 and 50, got {n}.")
        s, e = _parse_date(start, "start"), _parse_date(end, "end")
        _validate_range(s, e)
        groups = source.cost_summary(s, e, "service")
        total = source.total_cost(s, e)
        from mcp_aws_finops.models import CostDriver

        drivers = [
            CostDriver(rank=i + 1, key=g.key, cost=g.cost, share_pct=g.share_pct)
            for i, g in enumerate(groups[:n])
        ]
        return TopCostDriversResult(
            start=s, end=e, currency=source.currency, total_cost=round(total, 2), drivers=drivers
        )

    @mcp.tool()
    def cost_by_tag(tag_key: str, start: str, end: str) -> CostByTagResult:
        """Break down cost by the values of one cost-allocation tag (showback).

        Args:
            tag_key: Tag key to group by, e.g. "team" or "project".
            start: ISO date (inclusive).
            end: ISO date (exclusive).

        Also reports the cost and percentage of spend with no value for
        this tag ("untagged"), which is a common FinOps hygiene metric.
        """
        if not tag_key or not tag_key.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Invalid tag_key={tag_key!r}.")
        s, e = _parse_date(start, "start"), _parse_date(end, "end")
        _validate_range(s, e)
        groups = source.cost_summary(s, e, f"tag:{tag_key}")
        total = source.total_cost(s, e)
        untagged = next((g.cost for g in groups if g.key == "untagged"), 0.0)
        tag_groups = [
            TagGroupCost(tag_value=g.key, cost=g.cost, share_pct=g.share_pct)
            for g in groups
            if g.key != "untagged"
        ]
        return CostByTagResult(
            tag_key=tag_key,
            start=s,
            end=e,
            currency=source.currency,
            total_cost=round(total, 2),
            groups=tag_groups,
            untagged_cost=round(untagged, 2),
            untagged_pct=round(untagged / total * 100.0, 1) if total else 0.0,
        )

    @mcp.tool()
    def find_idle_resources(lookback_days: int = 14) -> FindIdleResourcesResult:
        """Find likely-idle/wasteful AWS resources from billing data heuristics.

        Args:
            lookback_days: How many trailing days of billing data to inspect
                (1-90). Defaults to 14.

        Heuristics (see FocusFileSource docstring for full detail):
        unattached EBS volumes, idle Elastic IPs, EBS snapshots older than
        90 days, and EC2/RDS instances with average CPU under 5%. Each
        finding includes an estimated monthly cost of the waste.
        """
        if not 1 <= lookback_days <= 90:
            raise ValueError(f"lookback_days must be between 1 and 90, got {lookback_days}.")
        _, max_date = source.data_bounds()
        resources = source.idle_resources(max_date, lookback_days)
        return FindIdleResourcesResult(
            lookback_days=lookback_days,
            resources=resources,
            total_estimated_monthly_waste=round(
                sum(r.estimated_monthly_cost for r in resources), 2
            ),
        )

    @mcp.tool()
    def forecast_month_end(month: str) -> ForecastMonthEndResult:
        """Forecast the total AWS cost for a calendar month using a run-rate.

        Args:
            month: Target month as "YYYY-MM", e.g. "2025-09".

        Method: linear run-rate. Computes the average daily cost over the
        days of the month already covered by data, then multiplies by the
        number of days in the month. This is intentionally simple (no
        seasonality or trend) — documented so callers know its limits.
        """
        try:
            year, mon = (int(p) for p in month.split("-"))
            month_start = date(year, mon, 1)
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Invalid month={month!r}; expected 'YYYY-MM'.") from exc
        next_month = date(year + (mon // 12), (mon % 12) + 1, 1)
        days_in_month = (next_month - month_start).days
        _, max_date = source.data_bounds()
        covered_end = min(next_month, max_date + timedelta(days=1))
        if covered_end <= month_start:
            raise ValueError(
                f"No data available for {month}; data covers up to {max_date.isoformat()}."
            )
        days_elapsed = (covered_end - month_start).days
        cost_to_date = source.total_cost(month_start, covered_end)
        daily_run_rate = cost_to_date / days_elapsed if days_elapsed else 0.0
        return ForecastMonthEndResult(
            month=month,
            currency=source.currency,
            days_elapsed=days_elapsed,
            days_in_month=days_in_month,
            cost_to_date=round(cost_to_date, 2),
            daily_run_rate=round(daily_run_rate, 2),
            forecast_total=round(daily_run_rate * days_in_month, 2),
            method="linear run-rate: avg(daily cost so far) * days_in_month",
        )

    @mcp.tool()
    def explain_anomaly(
        day: str, baseline_window_days: int = 14, threshold_pct: float = 30.0
    ) -> ExplainAnomalyResult:
        """Explain a cost spike/dip on a given day vs. a trailing baseline.

        Args:
            day: ISO date to explain, e.g. "2025-08-25".
            baseline_window_days: How many days before `day` to average as
                the baseline (1-60). Defaults to 14.
            threshold_pct: Percent deviation from baseline above which the
                day is flagged `is_anomaly=True`. Defaults to 30%.

        Returns the day's actual cost, the baseline average, and the
        services that contributed most to the difference.
        """
        if not 1 <= baseline_window_days <= 60:
            raise ValueError(
                f"baseline_window_days must be between 1 and 60, got {baseline_window_days}."
            )
        d = _parse_date(day, "day")
        baseline_start = d - timedelta(days=baseline_window_days)
        series = source.daily_cost_series(baseline_start, d)
        baseline_avg = sum(c for _, c in series) / len(series) if series else 0.0
        actual = source.total_cost(d, d + timedelta(days=1))
        delta = actual - baseline_avg
        delta_pct = (delta / baseline_avg * 100.0) if baseline_avg else None

        by_group_day = source.daily_cost_by_group(d, d + timedelta(days=1), "service")
        actual_by_service = {g.key: g.cost for g in by_group_day.get(d, [])}
        baseline_by_group = source.daily_cost_by_group(baseline_start, d, "service")
        baseline_by_service: dict[str, float] = {}
        for grouped in baseline_by_group.values():
            for g in grouped:
                baseline_by_service[g.key] = baseline_by_service.get(g.key, 0.0) + g.cost
        n_days = max(len(baseline_by_group), 1)
        baseline_avg_by_service = {k: v / n_days for k, v in baseline_by_service.items()}

        keys = set(actual_by_service) | set(baseline_avg_by_service)
        contributors = [
            AnomalyContributor(
                key=k,
                baseline_cost=round(baseline_avg_by_service.get(k, 0.0), 2),
                actual_cost=round(actual_by_service.get(k, 0.0), 2),
                delta=round(actual_by_service.get(k, 0.0) - baseline_avg_by_service.get(k, 0.0), 2),
            )
            for k in keys
        ]
        contributors.sort(key=lambda c: abs(c.delta), reverse=True)

        return ExplainAnomalyResult(
            date=d,
            currency=source.currency,
            actual_cost=round(actual, 2),
            baseline_cost=round(baseline_avg, 2),
            delta=round(delta, 2),
            delta_pct=round(delta_pct, 1) if delta_pct is not None else None,
            baseline_window_days=baseline_window_days,
            is_anomaly=bool(delta_pct is not None and abs(delta_pct) >= threshold_pct),
            contributors=contributors[:10],
        )

    @mcp.resource("finops://reports/weekly")
    def weekly_report() -> str:
        """Markdown weekly cost report for the most recent 7 days of data."""
        _, max_date = source.data_bounds()
        end = max_date + timedelta(days=1)
        start = end - timedelta(days=7)
        prev_start = start - timedelta(days=7)
        total = source.total_cost(start, end)
        prev_total = source.total_cost(prev_start, start)
        delta_pct = (total - prev_total) / prev_total * 100.0 if prev_total else None
        groups: list[GroupedCost] = source.cost_summary(start, end, "service")
        idle = source.idle_resources(max_date, 14)
        waste = sum(r.estimated_monthly_cost for r in idle)

        period_end = (end - timedelta(days=1)).isoformat()
        lines = [
            f"# Weekly Cost Review — {start.isoformat()} to {period_end}",
            "",
            f"**Total cost:** {total:,.2f} {source.currency}"
            + (f" ({delta_pct:+.1f}% vs. previous week)" if delta_pct is not None else ""),
            "",
            "## Top services",
            "",
            "| Service | Cost | Share |",
            "|---|---|---|",
        ]
        for g in groups[:8]:
            lines.append(f"| {g.key} | {g.cost:,.2f} | {g.share_pct:.1f}% |")
        lines += [
            "",
            "## Idle resources (estimated monthly waste)",
            "",
            f"**{len(idle)} resources flagged, ~{waste:,.2f} {source.currency}/month estimated.**",
            "",
        ]
        for r in idle[:10]:
            lines.append(
                f"- `{r.resource_id}` ({r.resource_type}): {r.reason} — "
                f"~{r.estimated_monthly_cost:,.2f}/mo"
            )
        lines.append(f"\n_Generated {datetime.now().isoformat(timespec='seconds')}._")
        return "\n".join(lines)

    @mcp.prompt(name="weekly_cost_review")
    def weekly_cost_review_prompt() -> str:
        """Prompt template: guide an agent through a weekly FinOps review."""
        return (
            "You are a FinOps analyst. Using the mcp-aws-finops tools, produce a weekly "
            "cost review:\n"
            "1. Call get_cost_summary for the last 7 days, grouped by service.\n"
            "2. Call compare_periods against the previous 7 days to find what changed.\n"
            "3. Call find_idle_resources to list waste to clean up.\n"
            "4. Call forecast_month_end for the current month.\n"
            "5. Summarize in plain language: total spend, top movers, idle waste, "
            "and the month-end forecast, with concrete recommendations."
        )

    return mcp

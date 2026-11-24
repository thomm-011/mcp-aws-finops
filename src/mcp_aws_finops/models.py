"""Pydantic models returned by the MCP tools.

Keeping these as typed models (instead of raw dicts) gives the MCP client
and the LLM calling the tools a predictable, documented schema.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class GroupedCost(BaseModel):
    """Cost aggregated for a single group (service, account, region, tag...)."""

    key: str = Field(description="Group value, e.g. service name or account id")
    cost: float = Field(description="Billed cost in the source currency")
    share_pct: float = Field(description="Share of the period total, in percent")


class CostSummaryResult(BaseModel):
    """Result of `get_cost_summary`."""

    start: date
    end: date
    group_by: str
    currency: str
    total_cost: float
    groups: list[GroupedCost]


class PeriodDriver(BaseModel):
    """A single group's contribution to the change between two periods."""

    key: str
    cost_a: float
    cost_b: float
    delta: float = Field(description="cost_b - cost_a")
    delta_pct: float | None = Field(
        default=None, description="Percent change vs period A; null if cost_a was 0"
    )


class ComparePeriodsResult(BaseModel):
    """Result of `compare_periods`."""

    a_start: date
    a_end: date
    b_start: date
    b_end: date
    total_a: float
    total_b: float
    delta: float
    delta_pct: float | None
    currency: str
    top_drivers: list[PeriodDriver] = Field(
        description="Services ranked by absolute change, largest first"
    )


class CostDriver(BaseModel):
    """A single ranked cost driver for `top_cost_drivers`."""

    rank: int
    key: str
    cost: float
    share_pct: float


class TopCostDriversResult(BaseModel):
    """Result of `top_cost_drivers`."""

    start: date
    end: date
    currency: str
    total_cost: float
    drivers: list[CostDriver]


class TagGroupCost(BaseModel):
    """Cost for one value of a given tag key."""

    tag_value: str
    cost: float
    share_pct: float


class CostByTagResult(BaseModel):
    """Result of `cost_by_tag`."""

    tag_key: str
    start: date
    end: date
    currency: str
    total_cost: float
    groups: list[TagGroupCost]
    untagged_cost: float
    untagged_pct: float


class IdleResource(BaseModel):
    """A resource flagged as idle/wasteful by one of the heuristics."""

    resource_id: str
    resource_type: str
    reason: str = Field(description="Which heuristic matched and why")
    account_id: str | None = None
    region: str | None = None
    estimated_monthly_cost: float = Field(
        description="Cost of this resource over the trailing window, annualised to a month"
    )


class FindIdleResourcesResult(BaseModel):
    """Result of `find_idle_resources`."""

    lookback_days: int
    resources: list[IdleResource]
    total_estimated_monthly_waste: float


class ForecastMonthEndResult(BaseModel):
    """Result of `forecast_month_end`."""

    month: str = Field(description="Target month, format YYYY-MM")
    currency: str
    days_elapsed: int
    days_in_month: int
    cost_to_date: float
    daily_run_rate: float
    forecast_total: float
    method: str = Field(
        description="Forecasting method used, documented for transparency to the caller"
    )


class AnomalyContributor(BaseModel):
    """A service/resource that contributed to an anomalous day."""

    key: str
    baseline_cost: float
    actual_cost: float
    delta: float


class ExplainAnomalyResult(BaseModel):
    """Result of `explain_anomaly`."""

    date: date
    currency: str
    actual_cost: float
    baseline_cost: float
    delta: float
    delta_pct: float | None
    baseline_window_days: int
    is_anomaly: bool = Field(description="True if delta exceeds the anomaly threshold")
    contributors: list[AnomalyContributor]

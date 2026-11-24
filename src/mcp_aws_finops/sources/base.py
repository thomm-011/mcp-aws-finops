"""Backend-agnostic interface for cost data sources.

A `CostSource` knows how to answer the handful of aggregate queries the MCP
tools need, without the tool layer caring whether the data comes from a
local FOCUS file (`FocusFileSource`, implemented) or the AWS Cost Explorer /
CloudWatch APIs (`CostExplorerSource`, interface only — see M4 in the
roadmap).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from mcp_aws_finops.models import GroupedCost, IdleResource

GroupBy = str
"""One of "service", "account", "region" or "tag:<key>" (e.g. "tag:team")."""


class CostSource(ABC):
    """Abstract contract every billing data backend must implement."""

    @property
    @abstractmethod
    def currency(self) -> str:
        """ISO currency code of the underlying data (e.g. "USD")."""

    @abstractmethod
    def cost_summary(self, start: date, end: date, group_by: GroupBy) -> list[GroupedCost]:
        """Return cost aggregated by `group_by` for [start, end) (end exclusive)."""

    @abstractmethod
    def total_cost(self, start: date, end: date) -> float:
        """Return the total cost for [start, end)."""

    @abstractmethod
    def daily_cost_series(self, start: date, end: date) -> list[tuple[date, float]]:
        """Return (day, cost) pairs for every day in [start, end)."""

    @abstractmethod
    def daily_cost_by_group(
        self, start: date, end: date, group_by: GroupBy
    ) -> dict[date, list[GroupedCost]]:
        """Return, for each day in [start, end), cost grouped by `group_by`.

        Used by `explain_anomaly` to find which groups drove a spike on one
        specific day relative to a trailing baseline.
        """

    @abstractmethod
    def idle_resources(self, as_of: date, lookback_days: int) -> list[IdleResource]:
        """Return resources matching the idle/waste heuristics (see FocusFileSource docs)."""

    @abstractmethod
    def data_bounds(self) -> tuple[date, date]:
        """Return (min_date, max_date) available in the underlying dataset."""

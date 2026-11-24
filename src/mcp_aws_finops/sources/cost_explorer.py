"""AWS Cost Explorer / CloudWatch backed `CostSource` — interface only.

This module intentionally does NOT implement `CostSource` yet. It exists so
the rest of the codebase (tools, server wiring) can already type against a
real AWS backend and so the planned shape of M4 is documented in code.

Planned implementation (M4, out of scope for this milestone):
- `cost_summary` / `total_cost` / `daily_cost_series` / `daily_cost_by_group`
  via `ce:GetCostAndUsage` (grouped by SERVICE, LINKED_ACCOUNT, REGION or a
  cost allocation TAG). Each call costs ~US$0.01; results should be cached.
- `idle_resources` via a mix of `ce:GetCostAndUsage` (to find candidate
  resources billed for storage/elastic IP with near-zero usage) and
  `cloudwatch:GetMetricData` (CPUUtilization, NetworkIn/Out) plus, where
  available, `compute-optimizer:GetEC2InstanceRecommendations`.
- `data_bounds` via `ce:GetCostAndUsage` with a wide date range, or a fixed
  "last 14 months" window (Cost Explorer's retention).
- boto3 clients are created with a read-only IAM role (see
  `docs/iam-policy.json` in the README roadmap) — this module must never
  call a mutating API action.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import boto3

from mcp_aws_finops.models import GroupedCost, IdleResource
from mcp_aws_finops.sources.base import CostSource, GroupBy


class CostExplorerSource(CostSource):
    """Not implemented yet — placeholder for the M4 AWS backend.

    Raises `NotImplementedError` on every call. Kept here (rather than
    deleted) so `CostSource` has two concrete shapes to type-check against
    and so M4 has a clear starting point.
    """

    def __init__(self, *, session: Any | None = None, region: str = "us-east-1") -> None:
        self._session = session or boto3.Session()
        self._region = region

    @property
    def currency(self) -> str:
        raise NotImplementedError("CostExplorerSource is not implemented yet (see M4 roadmap)")

    def cost_summary(self, start: date, end: date, group_by: GroupBy) -> list[GroupedCost]:
        raise NotImplementedError("CostExplorerSource is not implemented yet (see M4 roadmap)")

    def total_cost(self, start: date, end: date) -> float:
        raise NotImplementedError("CostExplorerSource is not implemented yet (see M4 roadmap)")

    def daily_cost_series(self, start: date, end: date) -> list[tuple[date, float]]:
        raise NotImplementedError("CostExplorerSource is not implemented yet (see M4 roadmap)")

    def daily_cost_by_group(
        self, start: date, end: date, group_by: GroupBy
    ) -> dict[date, list[GroupedCost]]:
        raise NotImplementedError("CostExplorerSource is not implemented yet (see M4 roadmap)")

    def idle_resources(self, as_of: date, lookback_days: int) -> list[IdleResource]:
        raise NotImplementedError("CostExplorerSource is not implemented yet (see M4 roadmap)")

    def data_bounds(self) -> tuple[date, date]:
        raise NotImplementedError("CostExplorerSource is not implemented yet (see M4 roadmap)")

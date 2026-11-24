"""Tests for FocusFileSource (DuckDB-backed CostSource)."""

from __future__ import annotations

from datetime import date

import pytest

from mcp_aws_finops.sources.focus_file import FocusFileSource, _group_expr


def test_currency(source: FocusFileSource) -> None:
    assert source.currency == "USD"


def test_data_bounds(source: FocusFileSource) -> None:
    start, end = source.data_bounds()
    assert start == date(2025, 7, 1)
    assert end == date(2025, 9, 30)


def test_total_cost_positive(source: FocusFileSource) -> None:
    total = source.total_cost(date(2025, 7, 1), date(2025, 8, 1))
    assert total > 0


def test_cost_summary_by_service_sums_to_total(source: FocusFileSource) -> None:
    start, end = date(2025, 7, 1), date(2025, 8, 1)
    groups = source.cost_summary(start, end, "service")
    total = source.total_cost(start, end)
    assert groups  # non-empty
    assert sum(g.cost for g in groups) == pytest.approx(total, rel=1e-6)
    # sorted descending
    costs = [g.cost for g in groups]
    assert costs == sorted(costs, reverse=True)


def test_cost_summary_by_region(source: FocusFileSource) -> None:
    groups = source.cost_summary(date(2025, 7, 1), date(2025, 7, 8), "region")
    assert {g.key for g in groups} <= {"us-east-1", "us-west-2", "eu-west-1", "global"}


def test_cost_summary_by_tag_includes_untagged(source: FocusFileSource) -> None:
    groups = source.cost_summary(date(2025, 7, 1), date(2025, 8, 1), "tag:team")
    keys = {g.key for g in groups}
    assert "untagged" in keys


def test_cost_summary_invalid_group_by(source: FocusFileSource) -> None:
    with pytest.raises(ValueError, match="Invalid group_by"):
        source.cost_summary(date(2025, 7, 1), date(2025, 7, 2), "bogus")


def test_group_expr_rejects_bad_tag_key() -> None:
    with pytest.raises(ValueError, match="Invalid tag key"):
        _group_expr("tag:bad key; DROP TABLE costs")


def test_daily_cost_series_covers_every_day(source: FocusFileSource) -> None:
    start, end = date(2025, 7, 1), date(2025, 7, 11)
    series = source.daily_cost_series(start, end)
    assert len(series) == 10
    assert all(day < end for day, _ in series)
    assert all(c >= 0 for _, c in series)


def test_daily_cost_series_detects_spike(source: FocusFileSource) -> None:
    series = dict(source.daily_cost_series(date(2025, 8, 20), date(2025, 8, 30)))
    avg_other = sum(c for d, c in series.items() if d != date(2025, 8, 25)) / 9
    assert series[date(2025, 8, 25)] > avg_other * 1.5


def test_daily_cost_by_group(source: FocusFileSource) -> None:
    result = source.daily_cost_by_group(date(2025, 7, 1), date(2025, 7, 3), "service")
    assert date(2025, 7, 1) in result
    for groups in result.values():
        shares = [g.share_pct for g in groups]
        assert sum(shares) == pytest.approx(100.0, rel=1e-3)


def test_idle_resources_finds_known_categories(source: FocusFileSource) -> None:
    resources = source.idle_resources(date(2025, 9, 30), 14)
    types = {r.resource_type for r in resources}
    assert "EBS Volume" in types
    assert "EBS Snapshot" in types
    assert all(r.estimated_monthly_cost >= 0 for r in resources)
    # sorted descending by cost
    costs = [r.estimated_monthly_cost for r in resources]
    assert costs == sorted(costs, reverse=True)


def test_missing_file_raises(tmp_path: object) -> None:
    with pytest.raises(FileNotFoundError):
        FocusFileSource(f"{tmp_path}/does-not-exist.parquet")

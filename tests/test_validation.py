"""Unit tests for the tool-layer validation logic in server.py."""

from __future__ import annotations

import pytest

from mcp_aws_finops.server import _parse_date, _validate_group_by, _validate_range


def test_parse_date_ok() -> None:
    assert _parse_date("2025-07-01", "start").isoformat() == "2025-07-01"


def test_parse_date_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid start"):
        _parse_date("not-a-date", "start")


def test_validate_range_rejects_end_before_start() -> None:
    from datetime import date

    with pytest.raises(ValueError, match="must be after"):
        _validate_range(date(2025, 8, 1), date(2025, 7, 1))


@pytest.mark.parametrize("group_by", ["service", "account", "region", "tag:team"])
def test_validate_group_by_ok(group_by: str) -> None:
    _validate_group_by(group_by)  # should not raise


def test_validate_group_by_rejects_bad_value() -> None:
    with pytest.raises(ValueError, match="Invalid group_by"):
        _validate_group_by("bogus")

"""Tests for the CLI argument parsing and source wiring (no actual stdio run)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp_aws_finops.cli import build_arg_parser, main


def test_arg_parser_demo_flag() -> None:
    args = build_arg_parser().parse_args(["--demo"])
    assert args.demo is True
    assert args.data is None


def test_arg_parser_data_flag() -> None:
    args = build_arg_parser().parse_args(["--data", "/tmp/foo.parquet"])
    assert args.data == "/tmp/foo.parquet"


def test_arg_parser_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--demo", "--data", "/tmp/foo.parquet"])


def test_main_demo_builds_and_runs_server() -> None:
    with patch("mcp_aws_finops.cli.create_server") as create_server_mock:
        main(["--demo"])
    create_server_mock.assert_called_once()
    create_server_mock.return_value.run.assert_called_once_with(transport="stdio")


def test_main_missing_data_path_exits(tmp_path: object) -> None:
    with pytest.raises(SystemExit):
        main([f"--data={tmp_path}/nope.parquet"])


def test_arg_parser_source_aws() -> None:
    args = build_arg_parser().parse_args(
        ["--source", "aws", "--profile", "prod", "--region", "eu-west-1"]
    )
    assert args.source == "aws"
    assert args.profile == "prod"
    assert args.region == "eu-west-1"


def test_arg_parser_source_mutually_exclusive_with_demo() -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--demo", "--source", "aws"])


def test_main_source_aws_builds_cost_explorer_source() -> None:
    with (
        patch("mcp_aws_finops.cli.create_server") as create_server_mock,
        patch("mcp_aws_finops.sources.cost_explorer.CostExplorerSource") as ce_source_mock,
    ):
        main(["--source", "aws", "--region", "eu-west-1"])
    ce_source_mock.assert_called_once()
    _, kwargs = ce_source_mock.call_args
    assert kwargs["region"] == "eu-west-1"
    create_server_mock.assert_called_once_with(ce_source_mock.return_value)
    create_server_mock.return_value.run.assert_called_once_with(transport="stdio")

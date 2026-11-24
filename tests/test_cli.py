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
        main(["--data", f"{tmp_path}/nope.parquet"])

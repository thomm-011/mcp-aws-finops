"""Command-line entry point for `mcp-aws-finops`."""

from __future__ import annotations

import argparse
import sys
from importlib import resources

from mcp_aws_finops.server import create_server
from mcp_aws_finops.sources.focus_file import FocusFileSource


def _sample_data_path() -> str:
    data_file = resources.files("mcp_aws_finops.data").joinpath("sample_focus.parquet")
    return str(data_file)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-aws-finops",
        description=(
            "Read-only MCP server that answers AWS cost/FinOps questions for AI agents, "
            "backed by FOCUS-format billing data."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--demo",
        action="store_true",
        help="Use the bundled synthetic sample dataset (no AWS account needed).",
    )
    group.add_argument(
        "--data",
        metavar="PATH",
        help="Path to a FOCUS-format CSV/Parquet file, or a directory of such files.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    data_path = args.data or _sample_data_path()

    try:
        source = FocusFileSource(data_path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    server = create_server(source)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

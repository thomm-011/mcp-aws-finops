"""Command-line entry point for `mcp-aws-finops`."""

from __future__ import annotations

import argparse
import sys
from importlib import resources

from mcp_aws_finops import __version__
from mcp_aws_finops.server import create_server
from mcp_aws_finops.sources.base import CostSource
from mcp_aws_finops.sources.focus_file import FocusFileSource


def _sample_data_path() -> str:
    data_file = resources.files("mcp_aws_finops.data").joinpath("sample_focus.parquet")
    return str(data_file)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-aws-finops",
        description=(
            "Read-only MCP server that answers AWS cost/FinOps questions for AI agents, "
            "backed by FOCUS-format billing data or live AWS Cost Explorer."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--demo",
        action="store_true",
        help="Use the bundled synthetic sample dataset (no AWS account needed). Default.",
    )
    group.add_argument(
        "--data",
        metavar="PATH",
        help="Path to a FOCUS-format CSV/Parquet file, or a directory of such files.",
    )
    group.add_argument(
        "--source",
        choices=["aws"],
        help="Use a live backend instead of a file. Currently only 'aws' "
        "(AWS Cost Explorer/EC2/CloudWatch) is supported; requires credentials "
        "(see README). Mutually exclusive with --demo/--data.",
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="AWS named profile to use with --source aws (default: default credential chain).",
    )
    parser.add_argument(
        "--region",
        metavar="REGION",
        default="us-east-1",
        help="AWS region for ec2/cloudwatch calls with --source aws (default: us-east-1). "
        "Cost Explorer itself is a global, single-endpoint service.",
    )
    parser.add_argument(
        "--metric",
        choices=["UnblendedCost", "AmortizedCost"],
        default="UnblendedCost",
        help="Cost Explorer cost metric to use with --source aws (default: UnblendedCost).",
    )
    parser.add_argument(
        "--cache-ttl-seconds",
        type=float,
        default=300.0,
        help="TTL for the in-memory Cost Explorer response cache with --source aws "
        "(default: 300; 0 disables caching). Each GetCostAndUsage call costs ~US$0.01.",
    )
    return parser


def _build_aws_source(args: argparse.Namespace) -> CostSource:
    from mcp_aws_finops.sources.cost_explorer import CostExplorerSource

    return CostExplorerSource(
        region=args.region,
        profile=args.profile,
        metric=args.metric,
        cache_ttl_seconds=args.cache_ttl_seconds,
    )


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    source: CostSource
    if args.source == "aws":
        try:
            source = _build_aws_source(args)
        except Exception as exc:  # pragma: no cover - construction rarely fails
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    else:
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

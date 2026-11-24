"""mcp-aws-finops: a read-only MCP server that answers AWS cost questions."""

from __future__ import annotations

__version__ = "0.2.0"

from mcp_aws_finops.cli import main

__all__ = ["__version__", "main"]

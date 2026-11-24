"""In-process integration tests: call every MCP tool/resource/prompt through
the real FastMCP server object (no subprocess, no stdio transport)."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError


async def _call(server: FastMCP, name: str, **kwargs: object) -> dict[str, object]:
    result = await server.call_tool(name, kwargs)
    # FastMCP's call_tool returns a tuple-ish (content_blocks, structured) in
    # some versions, or a dict with structuredContent; normalise both.
    if isinstance(result, tuple):
        _blocks, structured = result
        assert structured is not None
        return dict(structured)
    if isinstance(result, dict):
        return result
    raise AssertionError(f"Unexpected call_tool result shape: {type(result)}")


async def test_list_tools(server: FastMCP) -> None:
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_cost_summary",
        "compare_periods",
        "top_cost_drivers",
        "cost_by_tag",
        "find_idle_resources",
        "forecast_month_end",
        "explain_anomaly",
    }


async def test_get_cost_summary(server: FastMCP) -> None:
    out = await _call(server, "get_cost_summary", start="2025-07-01", end="2025-08-01")
    assert out["total_cost"] > 0
    assert out["group_by"] == "service"
    assert len(out["groups"]) > 0


async def test_get_cost_summary_by_tag(server: FastMCP) -> None:
    out = await _call(
        server, "get_cost_summary", start="2025-07-01", end="2025-08-01", group_by="tag:team"
    )
    assert any(g["key"] == "untagged" for g in out["groups"])


async def test_get_cost_summary_invalid_dates(server: FastMCP) -> None:
    # FastMCP wraps validation ValueErrors raised by the tool into ToolError.
    with pytest.raises(ToolError, match="Invalid start"):
        await server.call_tool("get_cost_summary", {"start": "bad", "end": "2025-08-01"})


async def test_compare_periods(server: FastMCP) -> None:
    out = await _call(
        server,
        "compare_periods",
        a_start="2025-07-01",
        a_end="2025-08-01",
        b_start="2025-08-01",
        b_end="2025-09-01",
    )
    assert "top_drivers" in out
    assert out["top_drivers"]
    assert out["delta"] == pytest.approx(out["total_b"] - out["total_a"], abs=0.05)


async def test_top_cost_drivers(server: FastMCP) -> None:
    out = await _call(server, "top_cost_drivers", start="2025-07-01", end="2025-10-01", n=3)
    assert len(out["drivers"]) == 3
    assert out["drivers"][0]["rank"] == 1


async def test_top_cost_drivers_bad_n(server: FastMCP) -> None:
    with pytest.raises(ToolError, match="between 1 and 50"):
        await server.call_tool(
            "top_cost_drivers", {"start": "2025-07-01", "end": "2025-08-01", "n": 999}
        )


async def test_cost_by_tag(server: FastMCP) -> None:
    out = await _call(server, "cost_by_tag", tag_key="team", start="2025-07-01", end="2025-10-01")
    assert out["untagged_pct"] >= 0
    assert out["groups"]


async def test_find_idle_resources(server: FastMCP) -> None:
    out = await _call(server, "find_idle_resources", lookback_days=14)
    assert out["total_estimated_monthly_waste"] >= 0
    assert any(r["resource_type"] == "EBS Volume" for r in out["resources"])


async def test_forecast_month_end(server: FastMCP) -> None:
    out = await _call(server, "forecast_month_end", month="2025-09")
    assert out["forecast_total"] > 0
    assert out["days_in_month"] == 30


async def test_explain_anomaly_flags_known_spike(server: FastMCP) -> None:
    out = await _call(server, "explain_anomaly", day="2025-08-25")
    assert out["is_anomaly"] is True
    assert out["contributors"]
    assert any(c["key"] == "Amazon EC2" for c in out["contributors"])


async def test_weekly_report_resource(server: FastMCP) -> None:
    contents = list(await server.read_resource("finops://reports/weekly"))
    assert contents
    text = contents[0].content
    assert "Weekly Cost Review" in text
    assert "Idle resources" in text


async def test_weekly_cost_review_prompt(server: FastMCP) -> None:
    result = await server.get_prompt("weekly_cost_review")
    assert result.messages
    combined = " ".join(m.content.text for m in result.messages if hasattr(m.content, "text"))
    assert "find_idle_resources" in combined


async def test_no_write_tools_registered(server: FastMCP) -> None:
    """Guard rail: this server must never expose a mutating AWS action."""
    tools = await server.list_tools()
    forbidden = {"create", "delete", "update", "put", "terminate", "modify", "write"}
    for tool in tools:
        lowered = tool.name.lower()
        assert not any(word in lowered for word in forbidden), tool.name

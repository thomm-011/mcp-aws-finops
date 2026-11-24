"""Manual smoke test: drive the real mcp-aws-finops server over stdio."""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_aws_finops", "--demo"],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print("TOOLS:", [t.name for t in tools.tools])

        resources = await session.list_resources()
        print("RESOURCES:", [str(r.uri) for r in resources.resources])

        prompts = await session.list_prompts()
        print("PROMPTS:", [p.name for p in prompts.prompts])

        calls = [
            ("get_cost_summary", {"start": "2025-07-01", "end": "2025-08-01"}),
            (
                "compare_periods",
                {
                    "a_start": "2025-07-01",
                    "a_end": "2025-08-01",
                    "b_start": "2025-08-01",
                    "b_end": "2025-09-01",
                },
            ),
            ("top_cost_drivers", {"start": "2025-07-01", "end": "2025-10-01", "n": 5}),
            ("cost_by_tag", {"tag_key": "team", "start": "2025-07-01", "end": "2025-10-01"}),
            ("find_idle_resources", {"lookback_days": 14}),
            ("forecast_month_end", {"month": "2025-09"}),
            ("explain_anomaly", {"day": "2025-08-25"}),
        ]
        for name, args in calls:
            result = await session.call_tool(name, args)
            text = result.structuredContent or (result.content[0].text if result.content else None)
            print(f"\n=== {name} ===")
            print(json.dumps(text, indent=2, default=str)[:800])

        report = await session.read_resource("finops://reports/weekly")
        print("\n=== finops://reports/weekly (first 400 chars) ===")
        print(report.contents[0].text[:400])

        prompt = await session.get_prompt("weekly_cost_review")
        print("\n=== prompt weekly_cost_review (first 200 chars) ===")
        print(prompt.messages[0].content.text[:200])


if __name__ == "__main__":
    asyncio.run(main())

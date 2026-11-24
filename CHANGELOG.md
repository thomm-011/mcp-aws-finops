# Changelog

All notable changes to this project are documented here.
The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added — M2: offline mode
- `FocusFileSource`: DuckDB-backed `CostSource` reading FOCUS CSV/Parquet
  (file or directory), with cost summary, daily series, per-day grouping,
  and idle-resource heuristics.
- All 7 MCP tools implemented: `get_cost_summary`, `compare_periods`,
  `top_cost_drivers`, `cost_by_tag`, `find_idle_resources`,
  `forecast_month_end`, `explain_anomaly`.
- MCP resource `finops://reports/weekly` (markdown weekly report) and
  prompt `weekly_cost_review`.
- Deterministic sample data generator (`scripts/generate_sample.py`,
  seeded) producing ~3 months of synthetic AWS FOCUS data, bundled as
  `src/mcp_aws_finops/data/sample_focus.parquet`.
- Test suite (pytest + pytest-asyncio + pytest-cov) covering the source
  layer, tool validation, and an in-process MCP client exercising every
  tool/resource/prompt through the real `FastMCP` server object.
  Coverage ≥ 80% (96% at time of writing).

### Added — M1: skeleton
- Project scaffolding with `uv`, `src/` layout, `pyproject.toml`.
- `CostSource` abstract interface and `CostExplorerSource` placeholder
  (interface only — AWS backend is M4, out of scope here).
- `mcp-aws-finops` console script with `--demo` / `--data PATH` flags,
  stdio transport.
- ruff (lint + format), mypy (strict on `src/`), pre-commit config.
- GitHub Actions CI workflow (`uv`, ruff, mypy, pytest).
- MIT license, README with architecture and quickstart.

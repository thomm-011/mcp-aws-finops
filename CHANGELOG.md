# Changelog

All notable changes to this project are documented here.
The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-11-23

### Added — M5: packaging + release automation
- `pyproject.toml` metadata polish: dynamic version (single source of
  truth in `src/mcp_aws_finops/__init__.py` via `tool.hatch.version`),
  full classifiers (incl. Python 3.12/3.13, `Typing :: Typed`), extra
  keywords, `project.urls.Issues`/`Changelog`, `py.typed` marker shipped
  in the wheel alongside the sample parquet.
- `mcp-aws-finops --version` CLI flag, backed by `__version__`.
- Verified `uv build` output (sdist + wheel) with `uvx twine check
  dist/*` (PASSED) and an end-to-end smoke test installing the built
  wheel into a fresh venv and running `scripts/smoke_test_stdio.py`
  against it (confirms `sample_focus.parquet` is actually packaged and
  all 7 tools/resource/prompt work from the installed wheel, not just
  the source tree).
- Multi-stage `Dockerfile` (`ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
  builder → `python:3.12-slim-bookworm` runtime), non-root `app` user,
  no dev dependencies in the final image, `ENTRYPOINT
  ["mcp-aws-finops"]` / default `CMD ["--demo"]`, OCI image labels.
  `.dockerignore`. Linted clean with `hadolint` (one informational
  DL3066 notice on the non-numeric `app` user, not a failure).
- `.github/workflows/release.yml`: triggered on `v*` tags — build
  sdist/wheel with `uv` and verify the tag matches the package version;
  publish to PyPI via `pypa/gh-action-pypi-publish` using Trusted
  Publishing (`environment: pypi`, `permissions.id-token: write`, no
  stored token); multi-arch (`linux/amd64`/`linux/arm64`) Docker build
  + push to `ghcr.io/thomm-011/mcp-aws-finops` (version + `latest` tags,
  provenance + SBOM, `GITHUB_TOKEN`); GitHub Release with notes sliced
  from this changelog and the dist files attached. The PyPI job is
  `continue-on-error: true` so Docker + the GitHub Release still
  succeed before the PyPI Trusted Publisher is registered (see
  `RELEASING.md`).
- `.github/workflows/ci.yml`: new `docker` job building the image (no
  push) on every PR/push to `main`.
- Both workflow files validated with `actionlint` (clean).
- `RELEASING.md`: one-time PyPI Trusted Publisher setup steps and the
  release-cutting checklist.
- README: badges (CI, PyPI, Python versions, license, GHCR — the PyPI
  badge reads "not found" until the first publish), Docker
  install/run instructions (incl. AWS-mode credential mount), M5 marked
  done in the roadmap. `examples/`: added a Docker variant of the
  Claude Desktop config.

## [Unreleased]

### Added — M4: AWS backend
- `CostExplorerSource`: full `CostSource` implementation over live
  `ce`/`ec2`/`cloudwatch` boto3 clients — `ce:GetCostAndUsage` (with
  pagination via `NextPageToken`, DAILY granularity, SERVICE/
  LINKED_ACCOUNT/REGION/TAG grouping, `UnblendedCost`/`AmortizedCost`
  metric choice, CE end-date exclusivity) for `cost_summary`/`total_cost`/
  `daily_cost_series`/`daily_cost_by_group`; `ec2:DescribeVolumes`
  (status=available), `DescribeAddresses` (no `AssociationId`),
  `DescribeSnapshots` (OwnerIds=self, age > configurable threshold), and
  `DescribeInstances` + `cloudwatch:GetMetricData` (avg CPU) for
  `idle_resources`. Convenience wrappers for `ce:GetCostForecast` and
  `ce:GetAnomalies` (graceful empty-list fallback when no Anomaly Monitor
  is configured).
- In-memory TTL cache (default 300s, configurable, `0` disables) over
  Cost Explorer responses — each `GetCostAndUsage`/`GetCostForecast` call
  costs ~US$0.01.
- `CostExplorerError`: friendly, actionable error messages for missing
  credentials, `AccessDenied`, and `DataUnavailableException`, each
  pointing back at `iam/policy.json`.
- CLI: `--source aws` with `--profile`, `--region`, `--metric`,
  `--cache-ttl-seconds`; boto3 is imported lazily so `--demo`/`--data`
  users never need it installed to run.
- `iam/policy.json`: least-privilege read-only policy (`ce:GetCostAndUsage`,
  `ce:GetCostForecast`, `ce:GetAnomalies`, `ec2:Describe{Volumes,Addresses,
  Snapshots,Instances}`, `cloudwatch:GetMetricData`/`GetMetricStatistics`)
  + `iam/README.md` action-to-tool mapping.
- `terraform/`: IAM role module assuming either a configurable principal
  ARN list or an OIDC/IRSA trust (GitHub Actions, EKS), attaching
  `iam/policy.json` verbatim; `terraform/tests/iam_role.tftest.hcl` native
  `terraform test` (mocked AWS provider) asserting no write action is
  granted and the trust policy matches configuration.
- `.github/workflows/ci.yml`: new `terraform` job (`setup-terraform`,
  `fmt -check`, `init -backend=false`, `validate`, `test`).
- Tests: `tests/test_cost_explorer.py` (37 cases — `botocore.stub.Stubber`
  for `ce`, since moto's Cost Explorer support is too partial to rely on;
  `moto.mock_aws` for `ec2`/`cloudwatch`, which it supports well; one
  in-process MCP tool call through `create_server` against a stubbed AWS
  source), `tests/test_iam_policy.py` (policy has no write/wildcard
  actions and matches the actions the code calls), CLI tests for
  `--source aws`. All tests run with fake, obviously-invalid AWS
  credentials injected by an autouse fixture — no real AWS call is ever
  possible from the suite. 81 tests total, 95.7% coverage (was 96%
  excluding `cost_explorer.py`, which is now fully included and covered).
- README: new "AWS mode" section (usage, IAM, Cost Explorer pricing/cache,
  honest "not yet validated against a live account" caveat), M4 marked
  done in the roadmap, architecture diagram updated to show
  `CostExplorerSource` as implemented.
- `examples/aws-mode.md`: ready-to-copy MCP client config pointing at
  `--source aws`.

### Added — M3: agent integration
- `examples/` directory with ready-to-copy MCP client configs: Claude
  Desktop (`claude_desktop_config.json`), Cursor (`.cursor/mcp.json`),
  Claude Code (`claude mcp add` command), and Hermes
  (`hermes-config.yaml` snippet) — all using the zero-install
  `uvx --from git+https://github.com/thomm-011/mcp-aws-finops` command
  (PyPI release pending) plus a local `uv --directory` variant.
- README: demo GIF near the top, new "Use with your agent" section
  linking `examples/`, M3 marked done in the roadmap.
- `docs/demo.gif` + `docs/demo.tape` (VHS source): a real Hermes agent
  session (separate `finops-demo` profile, `claude-haiku-4-5`, MCP
  toolset restricted to `aws-finops`) answering "which service drove
  the cost spike on 2025-08-25?" and a team-tag cost breakdown, verified
  to call the MCP tools and return correct figures.

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

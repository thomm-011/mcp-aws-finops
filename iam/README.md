# IAM least-privilege policy

`policy.json` is the minimal read-only IAM policy the `mcp-aws-finops`
server needs when run with `--source aws`. It grants exactly the actions
used by `CostExplorerSource` (see `src/mcp_aws_finops/sources/cost_explorer.py`
docstring) — no `List*`, no write/mutate actions, nothing beyond what each
MCP tool actually calls:

| Action | Used by |
|---|---|
| `ce:GetCostAndUsage` | `get_cost_summary`, `compare_periods`, `top_cost_drivers`, `cost_by_tag`, `forecast_month_end`, `explain_anomaly` |
| `ce:GetCostForecast` | optional CE-native forecast (`CostExplorerSource.get_cost_forecast`) |
| `ce:GetAnomalies` | optional CE Anomaly Detection hint for `explain_anomaly` (safe no-op if no monitor is configured) |
| `ec2:DescribeVolumes` | `find_idle_resources` — unattached EBS volumes |
| `ec2:DescribeAddresses` | `find_idle_resources` — unassociated Elastic IPs |
| `ec2:DescribeSnapshots` | `find_idle_resources` — old self-owned snapshots |
| `ec2:DescribeInstances` | `find_idle_resources` — low-CPU EC2 instances |
| `cloudwatch:GetMetricData` / `cloudwatch:GetMetricStatistics` | `find_idle_resources` — average CPU per instance |

`tests/test_iam_policy.py` asserts this file never contains a write action
and stays in sync with the actions actually referenced in
`cost_explorer.py`. The Terraform module in `../terraform/` wraps this
policy in an assumable IAM role; see that directory's README for usage.

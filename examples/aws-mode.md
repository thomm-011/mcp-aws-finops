# AWS mode (`--source aws`)

Points `mcp-aws-finops` at live AWS Cost Explorer / EC2 / CloudWatch data
instead of the bundled sample dataset. Requires an AWS account and the
read-only IAM policy in [`../iam/policy.json`](../iam/policy.json) (see the
main [README's AWS mode section](../README.md#aws-mode) and
[`../terraform/`](../terraform/) for provisioning an assumable role).

**Status:** implemented and tested against mocked AWS APIs
(`botocore.stub.Stubber` + `moto`); **not yet validated against a live AWS
account**.

## Local checkout

```bash
uv run --directory /path/to/mcp-aws-finops mcp-aws-finops \
  --source aws --region us-east-1 --profile my-finops-profile
```

## Claude Desktop / Cursor / Hermes config

Same shape as the `--demo` configs in this directory, with `--source aws`
and your region/profile instead of `--demo`:

```json
{
  "mcpServers": {
    "aws-finops": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/mcp-aws-finops",
        "mcp-aws-finops", "--source", "aws", "--region", "us-east-1",
        "--profile", "my-finops-profile"
      ]
    }
  }
}
```

## Notes

- Omit `--profile` to use the default credential chain (env vars,
  instance profile, ECS task role, EKS IRSA).
- `--metric AmortizedCost` spreads Reserved Instance / Savings Plan
  up-front costs over time; default is `UnblendedCost` (matches the bill).
- `--cache-ttl-seconds 0` disables the in-memory Cost Explorer response
  cache (default 300s) — useful when debugging, costly otherwise
  (`ce:GetCostAndUsage` is ~US$0.01/call).

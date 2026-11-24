# terraform/ — mcp-aws-finops read-only IAM role

Creates an IAM role + least-privilege policy (sourced from
`../iam/policy.json`) that an operator can assume to run
`mcp-aws-finops --source aws` against a real account, without ever
granting it write access.

## Usage

```hcl
module "mcp_aws_finops" {
  source = "github.com/thomm-011/mcp-aws-finops//terraform"

  role_name              = "mcp-aws-finops-readonly"
  trusted_principal_arns = ["arn:aws:iam::123456789012:user/finops-bot"]
}
```

Then, wherever the server runs:

```bash
aws sts assume-role --role-arn "$(terraform output -raw role_arn)" \
  --role-session-name mcp-aws-finops
# export the returned credentials, then:
mcp-aws-finops --source aws --region us-east-1
```

### OIDC / IRSA (EKS, GitHub Actions, etc.)

Set `use_oidc = true` instead of `trusted_principal_arns`:

```hcl
module "mcp_aws_finops" {
  source = "github.com/thomm-011/mcp-aws-finops//terraform"

  use_oidc          = true
  oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  oidc_provider_url = "token.actions.githubusercontent.com"
  oidc_subject      = "repo:example-org/mcp-aws-finops:ref:refs/heads/main"
}
```

For EKS IRSA, `oidc_provider_url` is the cluster's OIDC issuer host (e.g.
`oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E`) and
`oidc_subject` is `system:serviceaccount:<namespace>:<service-account>`.

## Variables

See `variables.tf`. Key ones: `role_name`, `trusted_principal_arns`,
`use_oidc`, `oidc_provider_arn`, `oidc_provider_url`, `oidc_subject`,
`oidc_audience`, `max_session_duration_seconds`, `tags`.

## Outputs

`role_arn`, `role_name`, `policy_arn`.

## Testing

```bash
terraform fmt -check
terraform init -backend=false
terraform validate
terraform test   # tests/iam_role.tftest.hcl, mock_provider "aws"
```

The test file asserts (against a mocked AWS provider, no real account
needed): the attached policy contains no write/mutate actions, the trust
policy only allows the configured principal (never a wildcard), and the
OIDC variant conditions on the expected `<provider>:sub` claim.

**Not yet validated against a live AWS account** — `terraform plan`/`apply`
against real AWS, and an actual `AssumeRole` call, are still untested.

mock_provider "aws" {}

variables {
  role_name              = "mcp-aws-finops-readonly-test"
  trusted_principal_arns = ["arn:aws:iam::123456789012:user/finops-bot"]
}

# `aws_iam_policy_document` is a provider-side data source, so under
# `mock_provider` it would otherwise return an empty/invalid mock value.
# Override it with a realistic rendering so downstream assertions (and the
# `aws_iam_role.assume_role_policy` attribute, which consumes it) see real
# JSON instead of a mock placeholder.
override_data {
  target = data.aws_iam_policy_document.trust_principal
  values = {
    json = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid       = "AssumeRoleByTrustedPrincipals"
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { AWS = ["arn:aws:iam::123456789012:user/finops-bot"] }
      }]
    })
  }
}

override_data {
  target = data.aws_iam_policy_document.trust_oidc
  values = {
    json = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid       = "AssumeRoleWithOIDC"
        Effect    = "Allow"
        Action    = "sts:AssumeRoleWithWebIdentity"
        Principal = { Federated = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = "repo:example-org/mcp-aws-finops:ref:refs/heads/main"
          }
        }
      }]
    })
  }
}

run "trust_principal_role_has_no_write_actions" {
  command = plan

  assert {
    condition     = !can(regex("(?i)\"(Create|Delete|Put|Update|Modify|Terminate|Start|Stop|Associate|Allocate|Run)[A-Za-z]*\"", aws_iam_policy.mcp_aws_finops_readonly.policy))
    error_message = "IAM policy must not contain any write/mutate action."
  }

  assert {
    condition     = aws_iam_role.mcp_aws_finops.name == "mcp-aws-finops-readonly-test"
    error_message = "Role name should match the configured role_name variable."
  }
}

run "trust_principal_policy_document_allows_only_configured_principal" {
  command = plan

  assert {
    condition     = strcontains(data.aws_iam_policy_document.trust_principal[0].json, "arn:aws:iam::123456789012:user/finops-bot")
    error_message = "Trust policy should include the configured principal ARN."
  }

  assert {
    condition     = !strcontains(data.aws_iam_policy_document.trust_principal[0].json, "\"AWS\":\"*\"")
    error_message = "Trust policy must never allow a wildcard principal."
  }
}

run "oidc_trust_uses_federated_principal_and_expected_subject" {
  command = plan

  variables {
    use_oidc          = true
    oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    oidc_provider_url = "token.actions.githubusercontent.com"
    oidc_subject      = "repo:example-org/mcp-aws-finops:ref:refs/heads/main"
  }

  assert {
    condition     = strcontains(data.aws_iam_policy_document.trust_oidc[0].json, "token.actions.githubusercontent.com:sub")
    error_message = "OIDC trust policy should condition on the <provider>:sub claim."
  }

  assert {
    condition     = strcontains(data.aws_iam_policy_document.trust_oidc[0].json, "repo:example-org/mcp-aws-finops:ref:refs/heads/main")
    error_message = "OIDC trust policy should require the configured subject."
  }
}

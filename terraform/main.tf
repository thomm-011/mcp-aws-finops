locals {
  policy_document = file("${path.module}/../iam/policy.json")
}

data "aws_iam_policy_document" "trust_principal" {
  count = var.use_oidc ? 0 : 1

  statement {
    sid     = "AssumeRoleByTrustedPrincipals"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.trusted_principal_arns
    }
  }
}

data "aws_iam_policy_document" "trust_oidc" {
  count = var.use_oidc ? 1 : 0

  statement {
    sid     = "AssumeRoleWithOIDC"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:aud"
      values   = [var.oidc_audience]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:sub"
      values   = [var.oidc_subject]
    }
  }
}

resource "aws_iam_role" "mcp_aws_finops" {
  name                 = var.role_name
  assume_role_policy   = var.use_oidc ? data.aws_iam_policy_document.trust_oidc[0].json : data.aws_iam_policy_document.trust_principal[0].json
  max_session_duration = var.max_session_duration_seconds
  description          = "Read-only role for the mcp-aws-finops MCP server (Cost Explorer + EC2/CloudWatch describe-only access)."
  tags                 = var.tags
}

resource "aws_iam_policy" "mcp_aws_finops_readonly" {
  name        = "${var.role_name}-policy"
  description = "Least-privilege read-only policy for mcp-aws-finops (ce:Get*, ec2:Describe*, cloudwatch:GetMetric*)."
  policy      = local.policy_document
  tags        = var.tags
}

resource "aws_iam_role_policy_attachment" "mcp_aws_finops_readonly" {
  role       = aws_iam_role.mcp_aws_finops.name
  policy_arn = aws_iam_policy.mcp_aws_finops_readonly.arn
}

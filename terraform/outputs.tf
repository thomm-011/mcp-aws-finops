output "role_arn" {
  description = "ARN of the IAM role created for mcp-aws-finops."
  value       = aws_iam_role.mcp_aws_finops.arn
}

output "role_name" {
  description = "Name of the IAM role created for mcp-aws-finops."
  value       = aws_iam_role.mcp_aws_finops.name
}

output "policy_arn" {
  description = "ARN of the least-privilege read-only IAM policy."
  value       = aws_iam_policy.mcp_aws_finops_readonly.arn
}

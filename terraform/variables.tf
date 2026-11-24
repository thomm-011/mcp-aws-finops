variable "role_name" {
  description = "Name of the IAM role mcp-aws-finops (--source aws) will assume."
  type        = string
  default     = "mcp-aws-finops-readonly"
}

variable "trusted_principal_arns" {
  description = <<-EOT
    IAM principal ARNs (users or roles) allowed to assume this role via
    sts:AssumeRole, e.g. ["arn:aws:iam::123456789012:user/finops-bot"].
    Ignored when `use_oidc` is true. Must be non-empty when `use_oidc` is
    false.
  EOT
  type        = list(string)
  default     = []
}

variable "use_oidc" {
  description = <<-EOT
    If true, build an OIDC/IRSA-style trust policy instead of a principal
    ARN list (e.g. for EKS IRSA or a GitHub Actions OIDC provider), using
    `oidc_provider_arn` / `oidc_subject` / `oidc_audience`.
  EOT
  type        = bool
  default     = false
}

variable "oidc_provider_arn" {
  description = "ARN of the IAM OIDC identity provider (required if use_oidc = true), e.g. an EKS cluster's OIDC provider or token.actions.githubusercontent.com."
  type        = string
  default     = ""
}

variable "oidc_provider_url" {
  description = <<-EOT
    The OIDC provider's URL without the scheme, used to build the
    `<url>:sub` / `<url>:aud` condition keys, e.g.
    "token.actions.githubusercontent.com" for GitHub Actions or
    "oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
    for EKS IRSA. Required if use_oidc = true.
  EOT
  type        = string
  default     = ""
}

variable "oidc_subject" {
  description = "Expected `sub` claim to match in the OIDC trust condition, e.g. \"system:serviceaccount:finops:mcp-aws-finops\" for IRSA, or \"repo:org/repo:ref:refs/heads/main\" for GitHub Actions."
  type        = string
  default     = ""
}

variable "oidc_audience" {
  description = "Expected `aud` claim to match in the OIDC trust condition."
  type        = string
  default     = "sts.amazonaws.com"
}

variable "max_session_duration_seconds" {
  description = "Maximum session duration for the role (900-43200 seconds)."
  type        = number
  default     = 3600

  validation {
    condition     = var.max_session_duration_seconds >= 900 && var.max_session_duration_seconds <= 43200
    error_message = "max_session_duration_seconds must be between 900 and 43200."
  }
}

variable "tags" {
  description = "Tags applied to the IAM role and policy."
  type        = map(string)
  default     = {}
}

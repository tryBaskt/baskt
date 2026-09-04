variable "aws_region" {
  description = "AWS region containing the Baskt development resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "This root intentionally manages only the existing dev environment."
  type        = string
  default     = "dev"

  validation {
    condition     = var.environment == "dev"
    error_message = "infrastructure_terraform currently supports only dev."
  }
}

variable "trade_worker_image_uri" {
  description = "Immutable ECR image URI for the existing trade execution worker, preferably tagged by Git SHA."
  type        = string

  validation {
    condition     = trimspace(var.trade_worker_image_uri) != ""
    error_message = "trade_worker_image_uri is required. Passing an empty value would make the worker deployment ambiguous."
  }
}

variable "opensearch_endpoint_override" {
  description = "Existing dev domain endpoint used during initial import. Leave empty after the domain is in Terraform state."
  type        = string
  default     = ""
}

variable "trade_worker_environment" {
  description = "Additional worker environment variables. Sensitive values are stored in encrypted Terraform state."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "runtime_enabled" {
  description = "Whether dev runtime triggers and Lambda execution should be enabled. Keep false while dev is powered down."
  type        = bool
  default     = false
}

variable "cloudwatch_log_retention_days" {
  description = "Number of days to retain CloudWatch logs for dev runtime resources."
  type        = number
  default     = 30

  validation {
    condition = contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653],
      var.cloudwatch_log_retention_days,
    )
    error_message = "cloudwatch_log_retention_days must be a valid CloudWatch Logs retention value."
  }
}

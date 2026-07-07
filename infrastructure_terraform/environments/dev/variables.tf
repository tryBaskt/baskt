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
  description = "Immutable ECR image URI (preferably tagged by Git SHA). Empty skips worker creation during initial ECR bootstrap."
  type        = string
  default     = ""
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

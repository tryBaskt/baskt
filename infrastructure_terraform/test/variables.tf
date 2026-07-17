variable "aws_region" {
  description = "AWS region containing the Baskt test resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "This root intentionally manages only the test environment."
  type        = string
  default     = "test"

  validation {
    condition     = var.environment == "test"
    error_message = "infrastructure_terraform/test supports only test."
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
  description = "Existing test domain endpoint used during initial import. Leave empty after the domain is in Terraform state."
  type        = string
  default     = ""
}

variable "trade_worker_environment" {
  description = "Additional worker environment variables. Sensitive values are stored in encrypted Terraform state."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "backend_image_uri" {
  description = "Immutable ECR image URI for the backend App Runner service. Leave empty until the first backend image has been pushed."
  type        = string
  default     = ""
}

variable "backend_api_domain_name" {
  description = "Custom domain name for the test backend API."
  type        = string
  default     = "api-test.trybaskt.com"
}

variable "hosted_zone_name" {
  description = "Route 53 public hosted zone name for Baskt DNS records."
  type        = string
  default     = "trybaskt.com"
}

variable "backend_cors_origins" {
  description = "Allowed CORS origins for the test backend."
  type        = string
  default     = "https://test.trybaskt.com"
}

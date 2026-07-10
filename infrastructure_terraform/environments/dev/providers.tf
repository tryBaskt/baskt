provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

provider "opensearch" {
  url                = "https://${var.opensearch_endpoint_override != "" ? var.opensearch_endpoint_override : module.opensearch_domain.endpoint}"
  aws_region         = var.aws_region
  sign_aws_requests  = true
  healthcheck        = false
  opensearch_version = "3.5"
}

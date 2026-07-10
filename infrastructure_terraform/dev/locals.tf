locals {
  prefix = var.environment

  common_tags = {
    Application = "Baskt"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }

}

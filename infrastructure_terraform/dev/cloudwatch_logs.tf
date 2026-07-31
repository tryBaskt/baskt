resource "aws_cloudwatch_log_group" "backend_application" {
  name              = "/baskt/${var.environment}/backend/application"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "backend_audit" {
  name              = "/baskt/${var.environment}/backend/audit"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

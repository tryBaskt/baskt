resource "aws_cloudwatch_log_group" "trade_execution_worker" {
  name              = "/aws/lambda/${var.environment}-trade-execution-queue-worker"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "market_hours_controller" {
  name              = "/aws/lambda/${var.environment}-trade-execution-market-hours-controller"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

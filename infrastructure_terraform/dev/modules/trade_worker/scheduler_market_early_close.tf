resource "aws_scheduler_schedule" "market_early_close" {
  name                         = "${var.environment}-trade-execution-early-close"
  schedule_expression          = "cron(58 12 ? * MON-FRI *)"
  schedule_expression_timezone = "America/New_York"
  state                        = var.runtime_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.market_hours_controller.arn
    role_arn = aws_iam_role.market_scheduler.arn
    input    = jsonencode({ action = "early_close" })
  }

  depends_on = [aws_iam_role_policy.market_scheduler]
}

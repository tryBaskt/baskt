resource "aws_scheduler_schedule" "market_prepare" {
  name                         = "${var.environment}-trade-execution-prepare"
  schedule_expression          = "cron(20-29 9 ? * MON-FRI *)"
  schedule_expression_timezone = "America/New_York"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.market_hours_controller.arn
    role_arn = aws_iam_role.market_scheduler.arn
    input    = jsonencode({ action = "prepare" })
  }

  depends_on = [aws_iam_role_policy.market_scheduler]
}

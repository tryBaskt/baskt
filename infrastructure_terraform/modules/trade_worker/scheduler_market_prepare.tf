resource "aws_scheduler_schedule" "market_prepare" {
  count = var.trade_worker_image_uri == "" ? 0 : 1

  name                         = "${var.environment}-trade-execution-prepare"
  schedule_expression          = "cron(20-29 9 ? * MON-FRI *)"
  schedule_expression_timezone = "America/New_York"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.market_hours_controller[0].arn
    role_arn = aws_iam_role.market_scheduler.arn
    input    = jsonencode({ action = "prepare" })
  }

  depends_on = [aws_iam_role_policy.market_scheduler]
}

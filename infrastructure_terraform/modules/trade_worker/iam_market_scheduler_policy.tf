resource "aws_iam_role_policy" "market_scheduler" {
  name = "${var.environment}-trade-execution-market-hours-scheduler"
  role = aws_iam_role.market_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.market_hours_controller.arn
    }]
  })
}

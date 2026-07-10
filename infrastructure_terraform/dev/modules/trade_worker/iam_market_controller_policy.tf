resource "aws_iam_role_policy" "market_controller" {
  name = "${var.environment}-trade-execution-market-hours-controller"
  role = aws_iam_role.market_controller.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:${var.aws_partition}:logs:${var.aws_region}:${var.aws_account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:ListEventSourceMappings", "lambda:UpdateEventSourceMapping"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.trade_execution_worker.arn
      }
    ]
  })
}

data "archive_file" "market_hours_controller" {
  type        = "zip"
  source_file = "${path.module}/../../../../deployables/trade_execution_queue_worker/market_hours_controller.py"
  output_path = "${path.module}/market_hours_controller.zip"
}

resource "aws_lambda_function" "market_hours_controller" {
  function_name    = "${var.environment}-trade-execution-market-hours-controller"
  role             = aws_iam_role.market_controller.arn
  runtime          = "python3.12"
  handler          = "market_hours_controller.lambda_handler"
  filename         = data.archive_file.market_hours_controller.output_path
  source_code_hash = data.archive_file.market_hours_controller.output_base64sha256
  timeout          = 60
  memory_size      = 128

  environment {
    variables = {
      TRADE_EXECUTION_FUNCTION_NAME = aws_lambda_function.trade_execution_worker.function_name
      TRADE_EXECUTION_QUEUE_ARN     = var.queue_arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.market_hours_controller,
    aws_iam_role_policy.market_controller,
  ]
}

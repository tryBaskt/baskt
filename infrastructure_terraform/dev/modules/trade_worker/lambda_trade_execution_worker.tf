resource "aws_lambda_function" "trade_execution_worker" {
  function_name                  = "${var.environment}-trade-execution-queue-worker"
  role                           = aws_iam_role.trade_worker.arn
  package_type                   = "Image"
  image_uri                      = var.trade_worker_image_uri
  architectures                  = ["x86_64"]
  timeout                        = 120
  memory_size                    = 2048
  reserved_concurrent_executions = var.runtime_enabled ? -1 : 0

  environment {
    variables = merge(
      var.trade_worker_environment,
      {
        ENV                                  = var.environment
        ALPACA_ENV                           = "sandbox"
        DEV_TRADE_EXECUTION_QUEUE_URL        = var.queue_url
        ALLOCATION_DYNAMODB                  = "-allocation-dynamodb"
        MODEL_PORTFOLIO_DYNAMODB             = "-model-portfolio-dynamodb"
        ORDER_DYNAMODB                       = "-order-dynamodb"
        MODEL_PORTFOLIO_FOLLOWER_DYNAMODB    = "-model-portfolio-follower-dynamodb"
        USER_TRADE_LOCK_DYNAMODB             = "-user-trade-lock-dynamodb"
        MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB = "-model-portfolio-update-lock-dynamodb"
        BASKT_ACCOUNT_DYNAMODB               = "-baskt-account-dynamodb"
      },
    )
  }

  depends_on = [
    aws_cloudwatch_log_group.trade_execution_worker,
    aws_iam_role_policy.trade_worker_sqs,
    aws_iam_role_policy.trade_worker_dynamodb,
    aws_iam_role_policy_attachment.trade_worker_basic_execution,
  ]
}

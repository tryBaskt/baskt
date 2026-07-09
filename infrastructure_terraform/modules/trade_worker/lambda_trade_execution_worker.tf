resource "aws_lambda_function" "trade_execution_worker" {
  function_name = "${var.environment}-trade-execution-queue-worker"
  role          = aws_iam_role.trade_worker.arn
  package_type  = "Image"
  image_uri     = var.trade_worker_image_uri
  architectures = ["x86_64"]
  timeout       = 120
  memory_size   = 2048

  environment {
    variables = merge(
      {
        ENV                                  = var.environment
        ALPACA_ENV                           = "sandbox"
        DEV_TRADE_EXECUTION_QUEUE_URL        = var.queue_url
        MODEL_PORTFOLIO_DYNAMODB             = "_model_portfolio_dynamodb"
        PORTFOLIO_ALLOCATION_DYNAMODB        = "_portfolio_allocation_dynamodb"
        ORDER_DYNAMODB                       = "_order_dynamodb"
        MODEL_PORTFOLIO_FOLLOWER_DYNAMODB    = "_model_portfolio_follower_dynamodb"
        USER_TRADE_LOCK_DYNAMODB             = "_user_trade_lock_dynamodb"
        MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB = "_model_portfolio_update_lock_dynamodb"
        BASKT_ACCOUNT_DYNAMODB               = "_baskt_account_dynamodb"
      },
      var.trade_worker_environment,
    )
  }

  depends_on = [
    aws_iam_role_policy.trade_worker_sqs,
    aws_iam_role_policy.trade_worker_dynamodb,
    aws_iam_role_policy_attachment.trade_worker_basic_execution,
  ]
}

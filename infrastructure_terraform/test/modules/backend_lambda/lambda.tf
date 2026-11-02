locals {
  create_backend_function = trimspace(var.backend_image_uri) != ""
  backend_environment = {
    ENV                                                              = var.environment
    ALPACA_ENV                                                       = "sandbox"
    CORS_ORIGINS                                                     = var.cors_origins
    (format("%s_COGNITO_REGION", upper(var.environment)))            = var.cognito_region
    (format("%s_COGNITO_USER_POOL_ID", upper(var.environment)))      = var.cognito_user_pool_id
    (format("%s_COGNITO_APP_CLIENT_ID", upper(var.environment)))     = var.cognito_app_client_id
    (format("%s_TRADE_EXECUTION_QUEUE_URL", upper(var.environment))) = var.trade_execution_queue_url
    SANDBOX_ALPACA_BROKER_API_KEY_SECRET_ARN                         = aws_secretsmanager_secret.sandbox_alpaca_broker_api_key.arn
    SANDBOX_ALPACA_BROKER_API_SECRET_SECRET_ARN                      = aws_secretsmanager_secret.sandbox_alpaca_broker_api_secret.arn
  }
}

resource "aws_cloudwatch_log_group" "backend" {
  # Retain the former ECS logs through the cutover and their retention period.
  name              = "/ecs/${var.environment}-backend"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "backend_lambda" {
  name              = "/aws/lambda/${var.environment}-backend"
  retention_in_days = 14
}

resource "aws_lambda_function" "backend" {
  count         = local.create_backend_function ? 1 : 0
  function_name = "${var.environment}-backend"
  package_type  = "Image"
  image_uri     = var.backend_image_uri
  architectures = ["x86_64"]
  role          = aws_iam_role.backend_task.arn
  memory_size   = 6144
  # HTTP API integrations have a hard 30-second request deadline.
  timeout = 30
  publish = true

  ephemeral_storage {
    size = 1024
  }

  environment {
    variables = local.backend_environment
  }

  # No provisioned concurrency or scheduled warmers: compute is request-driven.
  # No VPC attachment: outbound broker/market-data access needs no NAT gateway.
  depends_on = [aws_iam_role_policy.backend_runtime, aws_ecr_repository_policy.backend_lambda]
}

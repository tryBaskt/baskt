locals {
  create_backend_service = trimspace(var.backend_image_uri) != ""

  backend_runtime_environment_variables = {
    ENV                                                              = var.environment
    ALPACA_ENV                                                       = "sandbox"
    AWS_DEFAULT_REGION                                               = var.aws_region
    CORS_ORIGINS                                                     = var.cors_origins
    (format("%s_COGNITO_REGION", upper(var.environment)))            = var.cognito_region
    (format("%s_COGNITO_USER_POOL_ID", upper(var.environment)))      = var.cognito_user_pool_id
    (format("%s_COGNITO_APP_CLIENT_ID", upper(var.environment)))     = var.cognito_app_client_id
    (format("%s_TRADE_EXECUTION_QUEUE_URL", upper(var.environment))) = var.trade_execution_queue_url
    MODEL_PORTFOLIO_DYNAMODB                                         = "-model-portfolio-dynamodb"
    PORTFOLIO_ALLOCATION_DYNAMODB                                    = "-portfolio-allocation-dynamodb"
    ORDER_DYNAMODB                                                   = "-order-dynamodb"
    MODEL_PORTFOLIO_FOLLOWER_DYNAMODB                                = "-model-portfolio-follower-dynamodb"
    USER_TRADE_LOCK_DYNAMODB                                         = "-user-trade-lock-dynamodb"
    MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB                             = "-model-portfolio-update-lock-dynamodb"
    BASKT_ACCOUNT_DYNAMODB                                           = "-baskt-account-dynamodb"
  }

  backend_runtime_environment_secrets = {
    SANDBOX_ALPACA_BROKER_API_KEY    = aws_secretsmanager_secret.sandbox_alpaca_broker_api_key.arn
    SANDBOX_ALPACA_BROKER_API_SECRET = aws_secretsmanager_secret.sandbox_alpaca_broker_api_secret.arn
  }
}

resource "aws_apprunner_service" "backend" {
  count        = local.create_backend_service ? 1 : 0
  service_name = "${var.environment}-backend"

  source_configuration {
    auto_deployments_enabled = false

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr_access.arn
    }

    image_repository {
      image_identifier      = var.backend_image_uri
      image_repository_type = "ECR"

      image_configuration {
        port                          = "8000"
        runtime_environment_variables = local.backend_runtime_environment_variables
        runtime_environment_secrets   = local.backend_runtime_environment_secrets
      }
    }
  }

  instance_configuration {
    cpu               = "1024"
    memory            = "2048"
    instance_role_arn = aws_iam_role.backend_instance.arn
  }

  health_check_configuration {
    healthy_threshold   = 1
    interval            = 10
    path                = "/health"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 5
  }

  tags = var.common_tags

  depends_on = [
    aws_iam_role_policy_attachment.apprunner_ecr_access,
    aws_iam_role_policy.backend_runtime,
  ]
}

resource "aws_apprunner_custom_domain_association" "backend" {
  count       = local.create_backend_service ? 1 : 0
  domain_name = var.api_domain_name
  service_arn = aws_apprunner_service.backend[0].arn
}

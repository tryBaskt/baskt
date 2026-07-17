locals {
  create_backend_service = trimspace(var.backend_image_uri) != ""

  backend_environment = [
    { name = "ENV", value = var.environment },
    { name = "ALPACA_ENV", value = "sandbox" },
    { name = "AWS_DEFAULT_REGION", value = var.aws_region },
    { name = "CORS_ORIGINS", value = var.cors_origins },
    { name = format("%s_COGNITO_REGION", upper(var.environment)), value = var.cognito_region },
    { name = format("%s_COGNITO_USER_POOL_ID", upper(var.environment)), value = var.cognito_user_pool_id },
    { name = format("%s_COGNITO_APP_CLIENT_ID", upper(var.environment)), value = var.cognito_app_client_id },
    { name = format("%s_TRADE_EXECUTION_QUEUE_URL", upper(var.environment)), value = var.trade_execution_queue_url },
    { name = "MODEL_PORTFOLIO_DYNAMODB", value = "-model-portfolio-dynamodb" },
    { name = "PORTFOLIO_ALLOCATION_DYNAMODB", value = "-portfolio-allocation-dynamodb" },
    { name = "ORDER_DYNAMODB", value = "-order-dynamodb" },
    { name = "MODEL_PORTFOLIO_FOLLOWER_DYNAMODB", value = "-model-portfolio-follower-dynamodb" },
    { name = "USER_TRADE_LOCK_DYNAMODB", value = "-user-trade-lock-dynamodb" },
    { name = "MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB", value = "-model-portfolio-update-lock-dynamodb" },
    { name = "BASKT_ACCOUNT_DYNAMODB", value = "-baskt-account-dynamodb" },
  ]

  backend_secrets = [
    {
      name      = "SANDBOX_ALPACA_BROKER_API_KEY"
      valueFrom = aws_secretsmanager_secret.sandbox_alpaca_broker_api_key.arn
    },
    {
      name      = "SANDBOX_ALPACA_BROKER_API_SECRET"
      valueFrom = aws_secretsmanager_secret.sandbox_alpaca_broker_api_secret.arn
    },
  ]
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.environment}-backend"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "backend" {
  name = "${var.environment}-backend"
}

resource "aws_ecs_task_definition" "backend" {
  count                    = local.create_backend_service ? 1 : 0
  family                   = "${var.environment}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.backend_execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.backend_image_uri
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      environment = local.backend_environment
      secrets     = local.backend_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.backend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "backend"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "backend" {
  count           = local.create_backend_service ? 1 : 0
  name            = "${var.environment}-backend"
  cluster         = aws_ecs_cluster.backend.id
  task_definition = aws_ecs_task_definition.backend[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = true
    security_groups  = [aws_security_group.backend_service.id]
    subnets          = data.aws_subnets.default.ids
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  depends_on = [
    aws_iam_role_policy.backend_runtime,
    aws_iam_role_policy.backend_execution_secrets,
    aws_lb_listener.https,
  ]
}

resource "aws_iam_role" "apprunner_ecr_access" {
  name = "${var.environment}-backend-apprunner-ecr-access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "build.apprunner.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  role       = aws_iam_role.apprunner_ecr_access.name
  policy_arn = "arn:${var.aws_partition}:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

resource "aws_iam_role" "backend_instance" {
  name = "${var.environment}-backend-apprunner-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "tasks.apprunner.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "backend_runtime" {
  name = "${var.environment}-backend-runtime"
  role = aws_iam_role.backend_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem"
        ]
        Resource = concat(
          var.dynamodb_table_arns,
          [for arn in var.dynamodb_table_arns : "${arn}/index/*"]
        )
      },
      {
        Sid    = "TradeExecutionQueueAccess"
        Effect = "Allow"
        Action = [
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:SendMessage"
        ]
        Resource = var.trade_execution_queue_arn
      },
      {
        Sid    = "CognitoAccess"
        Effect = "Allow"
        Action = [
          "cognito-idp:AdminCreateUser",
          "cognito-idp:AdminDeleteUser",
          "cognito-idp:AdminGetUser",
          "cognito-idp:AdminUpdateUserAttributes",
          "cognito-idp:AdminSetUserPassword",
          "cognito-idp:ListUsers"
        ]
        Resource = var.cognito_user_pool_arn
      },
      {
        Sid    = "OpenSearchAccess"
        Effect = "Allow"
        Action = [
          "es:DescribeDomain",
          "es:ESHttpGet",
          "es:ESHttpPost"
        ]
        Resource = [
          var.opensearch_domain_arn,
          "${var.opensearch_domain_arn}/*"
        ]
      },
      {
        Sid    = "ReadBackendSecrets"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.sandbox_alpaca_broker_api_key.arn,
          aws_secretsmanager_secret.sandbox_alpaca_broker_api_secret.arn
        ]
      }
    ]
  })
}

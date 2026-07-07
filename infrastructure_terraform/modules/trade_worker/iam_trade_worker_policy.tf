resource "aws_iam_role_policy" "trade_worker" {
  name = "${var.environment}-trade-execution-queue-worker"
  role = aws_iam_role.trade_worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:${var.aws_partition}:logs:${var.aws_region}:${var.aws_account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
        Resource = var.queue_arn
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:BatchWriteItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"]
        Resource = [
          "arn:${var.aws_partition}:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${var.environment}_*",
          "arn:${var.aws_partition}:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${var.environment}_*/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "trade_worker_sqs" {
  name = "${var.environment}-trade-execution-queue-worker-sqs"
  role = aws_iam_role.trade_worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
      Resource = var.queue_arn
    }]
  })
}

resource "aws_iam_role_policy" "trade_worker_dynamodb" {
  name = "${var.environment}-trade-execution-queue-worker-dynamodb"
  role = aws_iam_role.trade_worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:BatchWriteItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"]
      Resource = [
        "arn:${var.aws_partition}:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${var.environment}_*",
        "arn:${var.aws_partition}:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${var.environment}_*/index/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "trade_worker_basic_execution" {
  role       = aws_iam_role.trade_worker.name
  policy_arn = "arn:${var.aws_partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_sqs_queue" "trade_execution" {
  name                       = "${var.environment}-trade-execution-queue"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.trade_execution_dlq.arn
    maxReceiveCount     = 3
  })
}

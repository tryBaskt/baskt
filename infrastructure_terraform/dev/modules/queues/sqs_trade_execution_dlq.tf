resource "aws_sqs_queue" "trade_execution_dlq" {
  name                      = "${var.environment}-trade-execution-dlq"
  message_retention_seconds = 1209600

  lifecycle {
    prevent_destroy = true
  }
}

output "queue_arn" { value = aws_sqs_queue.trade_execution.arn }
output "queue_url" { value = aws_sqs_queue.trade_execution.url }
output "dlq_arn" { value = aws_sqs_queue.trade_execution_dlq.arn }

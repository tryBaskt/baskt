resource "aws_lambda_event_source_mapping" "trade_execution_queue" {
  event_source_arn        = var.queue_arn
  function_name           = aws_lambda_function.trade_execution_worker.arn
  batch_size              = 10
  enabled                 = var.runtime_enabled
  function_response_types = ["ReportBatchItemFailures"]
}

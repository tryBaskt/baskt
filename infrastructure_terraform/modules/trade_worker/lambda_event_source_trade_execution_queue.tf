resource "aws_lambda_event_source_mapping" "trade_execution_queue" {
  count = var.trade_worker_image_uri == "" ? 0 : 1

  event_source_arn        = var.queue_arn
  function_name           = aws_lambda_function.trade_execution_worker[0].arn
  batch_size              = 10
  enabled                 = false
  function_response_types = ["ReportBatchItemFailures"]
}

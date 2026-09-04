resource "aws_lambda_event_source_mapping" "baskt_account_search" {
  event_source_arn               = var.baskt_account_stream_arn
  function_name                  = aws_lambda_function.baskt_account_search_indexer.arn
  starting_position              = "LATEST"
  batch_size                     = 100
  bisect_batch_on_function_error = true
  enabled                        = var.runtime_enabled
  function_response_types        = ["ReportBatchItemFailures"]
  maximum_retry_attempts         = 3
}

resource "aws_lambda_event_source_mapping" "model_portfolio_search" {
  event_source_arn               = var.model_portfolio_stream_arn
  function_name                  = aws_lambda_function.model_portfolio_search_indexer.arn
  starting_position              = "LATEST"
  batch_size                     = 100
  bisect_batch_on_function_error = true
  function_response_types        = ["ReportBatchItemFailures"]
  maximum_retry_attempts         = 3
}

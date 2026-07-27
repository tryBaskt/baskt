data "archive_file" "baskt_account_search_indexer" {
  type        = "zip"
  source_file = "${path.module}/../../../../deployables/search_indexers/baskt_account_search/handler.py"
  output_path = "${path.module}/baskt_account_search_indexer.zip"
}

resource "aws_lambda_function" "baskt_account_search_indexer" {
  function_name    = "${var.environment}-baskt-account-search-indexer"
  role             = aws_iam_role.baskt_account_search.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.baskt_account_search_indexer.output_path
  source_code_hash = data.archive_file.baskt_account_search_indexer.output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      OPENSEARCH_ENDPOINT = "https://${var.opensearch_endpoint}"
      OPENSEARCH_INDEX    = "${var.environment}-baskt-accounts"
      EXPECTED_STREAM_ARN = var.baskt_account_stream_arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.baskt_account_search_indexer,
    aws_iam_role_policy.baskt_account_search,
  ]
}

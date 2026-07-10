data "archive_file" "model_portfolio_search_indexer" {
  type        = "zip"
  source_file = "${path.module}/../../../../deployables/search_indexers/model_portfolio_search/handler.py"
  output_path = "${path.module}/model_portfolio_search_indexer.zip"
}

resource "aws_lambda_function" "model_portfolio_search_indexer" {
  function_name    = "${var.environment}-model-portfolio-search-indexer"
  role             = aws_iam_role.model_portfolio_search.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.model_portfolio_search_indexer.output_path
  source_code_hash = data.archive_file.model_portfolio_search_indexer.output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      OPENSEARCH_ENDPOINT = "https://${var.opensearch_endpoint}"
      OPENSEARCH_INDEX    = "${var.environment}-model-portfolios"
      EXPECTED_STREAM_ARN = var.model_portfolio_stream_arn
    }
  }

  depends_on = [aws_iam_role_policy.model_portfolio_search]
}

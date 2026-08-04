resource "aws_cloudwatch_log_group" "baskt_account_search_indexer" {
  name              = "/aws/lambda/${var.environment}-baskt-account-search-indexer"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "model_portfolio_search_indexer" {
  name              = "/aws/lambda/${var.environment}-model-portfolio-search-indexer"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

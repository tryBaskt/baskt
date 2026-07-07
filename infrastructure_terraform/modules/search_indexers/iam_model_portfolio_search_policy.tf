resource "aws_iam_role_policy" "model_portfolio_search" {
  name = "${var.environment}-model-portfolio-search-indexer-opensearch"
  role = aws_iam_role.model_portfolio_search.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:${var.aws_partition}:logs:${var.aws_region}:${var.aws_account_id}:*"
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"]
        Resource = "${var.model_portfolio_table_arn}/stream/*"
      },
      {
        Effect   = "Allow"
        Action   = ["es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete"]
        Resource = "${var.opensearch_arn}/*"
      }
    ]
  })
}

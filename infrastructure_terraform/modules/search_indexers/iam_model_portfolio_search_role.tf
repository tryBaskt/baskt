resource "aws_iam_role" "model_portfolio_search" {
  name = "${var.environment}-model-portfolio-search-indexer-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

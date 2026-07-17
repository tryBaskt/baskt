resource "aws_iam_role" "baskt_account_search" {
  name = "${var.environment}-baskt-account-search-indexer-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

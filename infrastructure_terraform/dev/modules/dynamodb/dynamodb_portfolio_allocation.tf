resource "aws_dynamodb_table" "portfolio_allocation" {
  name         = "${var.environment}_portfolio_allocation_dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cognito_user_id"
  range_key    = "portfolio_id"

  attribute {
    name = "cognito_user_id"
    type = "S"
  }

  attribute {
    name = "portfolio_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

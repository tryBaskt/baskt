resource "aws_dynamodb_table" "order" {
  name         = "${var.environment}-order-dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "transaction_id"
  range_key    = "order_id"

  attribute {
    name = "transaction_id"
    type = "S"
  }

  attribute {
    name = "order_id"
    type = "S"
  }

  attribute {
    name = "cognito_user_id"
    type = "S"
  }

  attribute {
    name = "portfolio_id"
    type = "S"
  }

  global_secondary_index {
    name            = "cognito_user_id_portfolio_id_index"
    hash_key        = "cognito_user_id"
    range_key       = "portfolio_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

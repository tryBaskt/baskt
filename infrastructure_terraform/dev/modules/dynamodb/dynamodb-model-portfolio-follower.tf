resource "aws_dynamodb_table" "model_portfolio_follower" {
  name         = "${var.environment}-model-portfolio-follower-dynamodb"
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

  global_secondary_index {
    name            = "portfolio_id_index"
    hash_key        = "portfolio_id"
    range_key       = "cognito_user_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

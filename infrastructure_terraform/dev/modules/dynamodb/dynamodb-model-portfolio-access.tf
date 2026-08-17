resource "aws_dynamodb_table" "model_portfolio_access" {
  name         = "${var.environment}-model-portfolio-access-dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "portfolio_id"
  range_key    = "shared_with_cognito_user_id"

  attribute {
    name = "portfolio_id"
    type = "S"
  }

  attribute {
    name = "shared_with_cognito_user_id"
    type = "S"
  }

  attribute {
    name = "portfolio_owner_cognito_user_id"
    type = "S"
  }

  global_secondary_index {
    name            = "shared_with_cognito_user_id_index"
    hash_key        = "shared_with_cognito_user_id"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "portfolio_owner_cognito_user_id_index"
    hash_key        = "portfolio_owner_cognito_user_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

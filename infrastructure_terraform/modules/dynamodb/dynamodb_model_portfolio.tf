resource "aws_dynamodb_table" "model_portfolio" {
  name         = "${var.environment}_model_portfolio_dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "portfolio_id"

  attribute {
    name = "portfolio_id"
    type = "S"
  }

  attribute {
    name = "portfolio_owner_cognito_user_id"
    type = "S"
  }

  global_secondary_index {
    name            = "portfolio_owner_cognito_user_id_index"
    hash_key        = "portfolio_owner_cognito_user_id"
    projection_type = "ALL"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  point_in_time_recovery {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

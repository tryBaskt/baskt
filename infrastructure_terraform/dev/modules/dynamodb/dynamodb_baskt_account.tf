resource "aws_dynamodb_table" "baskt_account" {
  name         = "${var.environment}_baskt_account_dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cognito_user_id"

  attribute {
    name = "cognito_user_id"
    type = "S"
  }

  attribute {
    name = "display_name"
    type = "S"
  }

  global_secondary_index {
    name            = "display_name_index"
    hash_key        = "display_name"
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

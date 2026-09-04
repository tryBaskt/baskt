resource "aws_dynamodb_table" "user_trade_lock" {
  name         = "${var.environment}-user-trade-lock-dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cognito_user_id"

  attribute {
    name = "cognito_user_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

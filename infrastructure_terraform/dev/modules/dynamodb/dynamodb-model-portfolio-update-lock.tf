resource "aws_dynamodb_table" "model_portfolio_update_lock" {
  name         = "${var.environment}-model-portfolio-update-lock-dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "portfolio_id"

  attribute {
    name = "portfolio_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

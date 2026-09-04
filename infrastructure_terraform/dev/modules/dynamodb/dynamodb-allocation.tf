resource "aws_dynamodb_table" "allocation" {
  name         = "${var.environment}-allocation-dynamodb"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cognito_user_id"
  range_key    = "allocation_id"

  attribute {
    name = "cognito_user_id"
    type = "S"
  }

  attribute {
    name = "allocation_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

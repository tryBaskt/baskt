resource "aws_secretsmanager_secret" "sandbox_alpaca_broker_api_key" {
  name                    = "${var.environment}/backend/sandbox_alpaca_broker_api_key"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret" "sandbox_alpaca_broker_api_secret" {
  name                    = "${var.environment}/backend/sandbox_alpaca_broker_api_secret"
  recovery_window_in_days = 7
}

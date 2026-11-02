output "backend_ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "backend_lambda_function_name" {
  value = try(aws_lambda_function.backend[0].function_name, null)
}

output "backend_api_gateway_id" {
  value = aws_apigatewayv2_api.backend.id
}

output "backend_custom_domain" {
  value = "https://${var.api_domain_name}"
}

output "sandbox_alpaca_broker_api_key_secret_arn" {
  value = aws_secretsmanager_secret.sandbox_alpaca_broker_api_key.arn
}

output "sandbox_alpaca_broker_api_secret_secret_arn" {
  value = aws_secretsmanager_secret.sandbox_alpaca_broker_api_secret.arn
}

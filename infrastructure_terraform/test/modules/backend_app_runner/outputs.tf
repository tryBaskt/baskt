output "backend_ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "backend_apprunner_service_arn" {
  value = try(aws_apprunner_service.backend[0].arn, null)
}

output "backend_apprunner_service_url" {
  value = try(aws_apprunner_service.backend[0].service_url, null)
}

output "backend_custom_domain" {
  value = var.api_domain_name
}

output "sandbox_alpaca_broker_api_key_secret_arn" {
  value = aws_secretsmanager_secret.sandbox_alpaca_broker_api_key.arn
}

output "sandbox_alpaca_broker_api_secret_secret_arn" {
  value = aws_secretsmanager_secret.sandbox_alpaca_broker_api_secret.arn
}

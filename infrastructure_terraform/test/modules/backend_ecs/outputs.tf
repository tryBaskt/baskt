output "backend_ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "backend_ecs_cluster_name" {
  value = aws_ecs_cluster.backend.name
}

output "backend_ecs_service_name" {
  value = try(aws_ecs_service.backend[0].name, null)
}

output "backend_alb_dns_name" {
  value = aws_lb.backend.dns_name
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

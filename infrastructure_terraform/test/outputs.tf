output "trade_execution_ecr_repository_url" {
  value = module.ecr.repository_url
}

output "trade_execution_queue_url" {
  value = module.queues.queue_url
}

output "opensearch_endpoint" {
  value = module.opensearch_domain.endpoint
}

output "dynamodb_table_names" {
  value = module.dynamodb.table_names
}

output "cognito_user_pool_id" {
  value = module.cognito.user_pool_id
}

output "cognito_user_pool_arn" {
  value = module.cognito.user_pool_arn
}

output "cognito_app_client_id" {
  value = module.cognito.app_client_id
}

output "cognito_user_pool_domain" {
  value = module.cognito.user_pool_domain
}

output "backend_ecr_repository_url" {
  value = module.backend_ecs.backend_ecr_repository_url
}

output "backend_ecs_cluster_name" {
  value = module.backend_ecs.backend_ecs_cluster_name
}

output "backend_ecs_service_name" {
  value = module.backend_ecs.backend_ecs_service_name
}

output "backend_alb_dns_name" {
  value = module.backend_ecs.backend_alb_dns_name
}

output "backend_custom_domain" {
  value = module.backend_ecs.backend_custom_domain
}

output "backend_sandbox_alpaca_broker_api_key_secret_arn" {
  value = module.backend_ecs.sandbox_alpaca_broker_api_key_secret_arn
}

output "backend_sandbox_alpaca_broker_api_secret_secret_arn" {
  value = module.backend_ecs.sandbox_alpaca_broker_api_secret_secret_arn
}

output "frontend_bucket_name" {
  value = module.frontend_hosting.bucket_name
}

output "frontend_cloudfront_distribution_id" {
  value = module.frontend_hosting.cloudfront_distribution_id
}

output "frontend_cloudfront_domain_name" {
  value = module.frontend_hosting.cloudfront_domain_name
}

output "frontend_url" {
  value = module.frontend_hosting.frontend_url
}

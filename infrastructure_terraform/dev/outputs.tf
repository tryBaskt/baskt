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

output "backend_application_log_group_name" {
  value = aws_cloudwatch_log_group.backend_application.name
}

output "backend_audit_log_group_name" {
  value = aws_cloudwatch_log_group.backend_audit.name
}

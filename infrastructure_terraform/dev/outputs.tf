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

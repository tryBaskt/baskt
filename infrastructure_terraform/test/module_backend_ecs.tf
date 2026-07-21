module "backend_ecs" {
  source = "./modules/backend_ecs"

  environment               = var.environment
  aws_region                = var.aws_region
  aws_account_id            = data.aws_caller_identity.current.account_id
  aws_partition             = data.aws_partition.current.partition
  backend_image_uri         = var.backend_image_uri
  api_domain_name           = var.backend_api_domain_name
  hosted_zone_name          = var.hosted_zone_name
  cors_origins              = var.backend_cors_origins
  cognito_region            = var.aws_region
  cognito_user_pool_id      = module.cognito.user_pool_id
  cognito_app_client_id     = module.cognito.app_client_id
  cognito_user_pool_arn     = module.cognito.user_pool_arn
  trade_execution_queue_url = module.queues.queue_url
  trade_execution_queue_arn = module.queues.queue_arn
  dynamodb_table_arns       = module.dynamodb.table_arns
  opensearch_domain_arn     = module.opensearch_domain.arn
  common_tags               = local.common_tags

  depends_on = [
    module.cognito,
    module.dynamodb,
    module.opensearch_domain,
    module.queues,
  ]
}

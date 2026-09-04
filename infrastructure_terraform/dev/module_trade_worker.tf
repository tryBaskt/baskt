module "trade_worker" {
  source = "./modules/trade_worker"

  environment              = var.environment
  aws_region               = var.aws_region
  aws_account_id           = data.aws_caller_identity.current.account_id
  aws_partition            = data.aws_partition.current.partition
  queue_arn                = module.queues.queue_arn
  queue_url                = module.queues.queue_url
  trade_worker_image_uri   = var.trade_worker_image_uri
  trade_worker_environment = var.trade_worker_environment
  runtime_enabled          = var.runtime_enabled
  log_retention_days       = var.cloudwatch_log_retention_days
  tags                     = local.common_tags

  depends_on = [module.dynamodb, module.ecr]
}

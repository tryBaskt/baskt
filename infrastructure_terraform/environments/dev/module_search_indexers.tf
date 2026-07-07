module "search_indexers" {
  source = "../../modules/search_indexers"

  environment                    = var.environment
  aws_region                     = var.aws_region
  aws_account_id                 = data.aws_caller_identity.current.account_id
  aws_partition                  = data.aws_partition.current.partition
  opensearch_arn                 = module.opensearch_domain.arn
  opensearch_endpoint            = module.opensearch_domain.endpoint
  model_portfolio_table_arn      = module.dynamodb.model_portfolio_arn
  model_portfolio_stream_arn     = module.dynamodb.model_portfolio_stream_arn
  baskt_account_table_arn        = module.dynamodb.baskt_account_arn
  baskt_account_stream_arn       = module.dynamodb.baskt_account_stream_arn

  depends_on = [module.opensearch_indices]
}

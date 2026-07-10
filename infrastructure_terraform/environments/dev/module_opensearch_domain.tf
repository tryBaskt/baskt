module "opensearch_domain" {
  source         = "../../modules/opensearch_domain"
  environment    = var.environment
  aws_region     = var.aws_region
  aws_account_id = data.aws_caller_identity.current.account_id
  aws_partition  = data.aws_partition.current.partition
}

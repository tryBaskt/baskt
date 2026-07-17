module "opensearch_indices" {
  source      = "./modules/opensearch_indices"
  environment = var.environment

  providers = {
    opensearch = opensearch
  }

  depends_on = [module.opensearch_domain]
}

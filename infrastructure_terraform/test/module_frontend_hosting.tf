module "frontend_hosting" {
  source = "./modules/frontend_hosting"

  environment      = var.environment
  bucket_name      = var.frontend_bucket_name
  domain_name      = var.frontend_domain_name
  hosted_zone_name = var.hosted_zone_name
  common_tags      = local.common_tags
}

module "cognito" {
  source = "./modules/cognito"

  user_pool_name   = "${var.environment}-user-pool"
  app_client_name  = "${var.environment}-user-pool-app-client"
  user_pool_domain = "${var.environment}-baskt-auth"
  callback_urls    = ["http://localhost:5173/oauth2/callback"]
  logout_urls      = ["http://localhost:5173/"]
  common_tags      = local.common_tags
}

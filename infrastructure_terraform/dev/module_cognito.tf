module "cognito" {
  source = "./modules/cognito"

  user_pool_name   = "dev-user-pool"
  app_client_name  = "dev-user-pool-app-client"
  user_pool_domain = "dev-baskt-auth"
  callback_urls    = ["http://localhost:5173/oauth2/callback"]
  logout_urls      = ["http://localhost:5173/"]
  common_tags      = local.common_tags
}

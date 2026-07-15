resource "aws_cognito_user_pool_client" "baskt_app" {
  name         = var.app_client_name
  user_pool_id = aws_cognito_user_pool.baskt.id

  generate_secret                               = false
  refresh_token_validity                        = 5
  access_token_validity                         = 60
  id_token_validity                             = 60
  auth_session_validity                         = 3
  prevent_user_existence_errors                 = "ENABLED"
  enable_token_revocation                       = true
  enable_propagate_additional_user_context_data = false

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_AUTH",
    "ALLOW_USER_SRP_AUTH",
  ]

  supported_identity_providers = ["COGNITO"]

  callback_urls        = var.callback_urls
  logout_urls          = var.logout_urls
  default_redirect_uri = var.callback_urls[0]

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["email", "openid", "profile"]
  allowed_oauth_flows_user_pool_client = true
}

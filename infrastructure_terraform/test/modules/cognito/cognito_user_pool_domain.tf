resource "aws_cognito_user_pool_domain" "baskt" {
  domain       = var.user_pool_domain
  user_pool_id = aws_cognito_user_pool.baskt.id
}

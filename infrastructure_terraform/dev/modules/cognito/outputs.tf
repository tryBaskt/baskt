output "user_pool_id" {
  value = aws_cognito_user_pool.baskt.id
}

output "user_pool_arn" {
  value = aws_cognito_user_pool.baskt.arn
}

output "user_pool_endpoint" {
  value = aws_cognito_user_pool.baskt.endpoint
}

output "app_client_id" {
  value = aws_cognito_user_pool_client.baskt_app.id
}

output "user_pool_domain" {
  value = aws_cognito_user_pool_domain.baskt.domain
}

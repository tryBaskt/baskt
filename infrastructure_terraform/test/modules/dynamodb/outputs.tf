output "baskt_account_arn" { value = aws_dynamodb_table.baskt_account.arn }
output "baskt_account_stream_arn" { value = aws_dynamodb_table.baskt_account.stream_arn }
output "model_portfolio_arn" { value = aws_dynamodb_table.model_portfolio.arn }
output "model_portfolio_stream_arn" { value = aws_dynamodb_table.model_portfolio.stream_arn }
output "table_arns" {
  value = [
    aws_dynamodb_table.allocation.arn,
    aws_dynamodb_table.baskt_account.arn,
    aws_dynamodb_table.model_portfolio.arn,
    aws_dynamodb_table.model_portfolio_follower.arn,
    aws_dynamodb_table.model_portfolio_update_lock.arn,
    aws_dynamodb_table.order.arn,
    aws_dynamodb_table.portfolio_allocation.arn,
    aws_dynamodb_table.user_trade_lock.arn,
  ]
}
output "table_names" {
  value = {
    allocation                  = aws_dynamodb_table.allocation.name
    baskt_account               = aws_dynamodb_table.baskt_account.name
    model_portfolio             = aws_dynamodb_table.model_portfolio.name
    model_portfolio_follower    = aws_dynamodb_table.model_portfolio_follower.name
    model_portfolio_update_lock = aws_dynamodb_table.model_portfolio_update_lock.name
    order                       = aws_dynamodb_table.order.name
    portfolio_allocation        = aws_dynamodb_table.portfolio_allocation.name
    user_trade_lock             = aws_dynamodb_table.user_trade_lock.name
  }
}

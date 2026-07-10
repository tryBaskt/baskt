moved {
  from = aws_iam_role_policy.market_controller[0]
  to   = aws_iam_role_policy.market_controller
}

moved {
  from = aws_iam_role_policy.market_scheduler[0]
  to   = aws_iam_role_policy.market_scheduler
}

moved {
  from = aws_lambda_event_source_mapping.trade_execution_queue[0]
  to   = aws_lambda_event_source_mapping.trade_execution_queue
}

moved {
  from = aws_lambda_function.market_hours_controller[0]
  to   = aws_lambda_function.market_hours_controller
}

moved {
  from = aws_lambda_function.trade_execution_worker[0]
  to   = aws_lambda_function.trade_execution_worker
}

moved {
  from = aws_scheduler_schedule.market_close[0]
  to   = aws_scheduler_schedule.market_close
}

moved {
  from = aws_scheduler_schedule.market_early_close[0]
  to   = aws_scheduler_schedule.market_early_close
}

moved {
  from = aws_scheduler_schedule.market_open[0]
  to   = aws_scheduler_schedule.market_open
}

moved {
  from = aws_scheduler_schedule.market_prepare[0]
  to   = aws_scheduler_schedule.market_prepare
}

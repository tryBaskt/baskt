import {
  to = module.trade_worker.aws_cloudwatch_log_group.market_hours_controller
  id = "/aws/lambda/dev-trade-execution-market-hours-controller"
}

import {
  to = module.trade_worker.aws_cloudwatch_log_group.trade_execution_worker
  id = "/aws/lambda/dev-trade-execution-queue-worker"
}

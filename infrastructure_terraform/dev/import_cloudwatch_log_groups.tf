import {
  to = module.search_indexers.aws_cloudwatch_log_group.baskt_account_search_indexer
  id = "/aws/lambda/dev-baskt-account-search-indexer"
}

import {
  to = module.search_indexers.aws_cloudwatch_log_group.model_portfolio_search_indexer
  id = "/aws/lambda/dev-model-portfolio-search-indexer"
}

import {
  to = module.trade_worker.aws_cloudwatch_log_group.market_hours_controller
  id = "/aws/lambda/dev-trade-execution-market-hours-controller"
}

import {
  to = module.trade_worker.aws_cloudwatch_log_group.trade_execution_worker
  id = "/aws/lambda/dev-trade-execution-queue-worker"
}

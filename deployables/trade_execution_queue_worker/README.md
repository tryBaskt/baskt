# Trade Execution Queue Worker

The trade worker is deployed as a Docker image and consumes SQS messages through
`TradeExecutionService`. The same deployment also creates a lightweight
market-hours controller and timezone-aware EventBridge Scheduler schedules.

For the hard-coded 2026 U.S. equity calendar, the controller:

- warms the worker every minute from 9:20 through 9:29 a.m. ET;
- enables the SQS event-source mapping at 9:30 a.m. ET;
- disables it at 12:59:30 p.m. ET on scheduled early-close days; and
- disables it at 3:59:30 p.m. ET on regular trading days.

Messages continue accumulating in SQS while the mapping is disabled.

## Deployment Ownership

Manual deployment from `deployables/` is disabled. This directory provides
runtime artifacts only:

- GitHub Actions builds and pushes the worker image when this folder or
  `backend/` changes.
- Terraform in `infrastructure_terraform/` owns Lambda, SQS, ECR, IAM,
  EventBridge Scheduler, CloudWatch Logs, and environment configuration.
- Create, update, and destroy operations must run through the Terraform GitHub
  Actions workflows for the target environment.

Running old local deployment entrypoints fails closed by design.

## Message Shape

Every message must include:

```json
{
  "action": "portfolio_deposit",
  "payload": {}
}
```

Supported actions:

- `portfolio_update`
- `portfolio_deposit`
- `portfolio_withdraw`
- `portfolio_withdraw_all`
- `stock_buy`
- `stock_sell`
- `stock_close`

Portfolio payloads use `portfolio_id`, `portfolio_owner_cognito_user_id`,
`cognito_user_id`, `alpaca_account_id`, and `amount` except
`portfolio_withdraw_all`, which does not need `amount`.

Stock payloads use `asset_id`, `symbol`, `cognito_user_id`,
`alpaca_account_id`, and `amount` except `stock_close`, which does not need
`amount`.

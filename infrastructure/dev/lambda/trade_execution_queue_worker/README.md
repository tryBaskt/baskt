# Dev Trade Execution Queue Worker

This Lambda is deployed as a Docker image. It consumes SQS messages and forwards
them to the backend trade-execution routes.

## Deploy

```bash
python infrastructure/dev/lambda/trade_execution_queue_worker/trade_execution_queue_worker_lambda.py \
  --create
```

## Destroy

```bash
python infrastructure/dev/lambda/trade_execution_queue_worker/trade_execution_queue_worker_lambda.py \
  --destroy
```

## Message Shape

Every message must include:

```json
{
  "action": "portfolio_deposit",
  "payload": {}
}
```

Supported actions:

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

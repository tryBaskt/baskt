"""SQS worker that executes queued trades through TradeExecutionService."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict


BACKEND_PATH = Path(__file__).resolve().parent / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.dynamodb_client import DynamoDBClient
from core.config import get_settings
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from repository.order_repository import OrderRepository
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from services.trade_execution_service import TradeExecutionService

import boto3


class TradeExecutionWorkerError(Exception):
    """Raised when a queued trade-execution job cannot be processed."""


@lru_cache
def _trade_execution_service() -> TradeExecutionService:
    """Instantiate the trade execution service and its dependencies."""
    settings = get_settings()
    boto3_session = boto3.Session(region_name=settings.aws_region)
    dynamodb = boto3_session.resource("dynamodb", region_name=settings.aws_region)

    alpaca_broker_client = AlpacaBrokerClient(
        alpaca_broker_api_key=settings.alpaca_broker_api_key,
        alpaca_broker_api_secret=settings.alpaca_broker_api_secret,
        alpaca_env=settings.alpaca_env,
    )
    model_portfolio_update_lock_repository = ModelPortfolioUpdateLockRepository(
        dynamodb_client=DynamoDBClient(
            table=dynamodb.Table(settings.model_portfolio_update_lock_dynamodb)
        )
    )
    model_portfolio_follower_repository = ModelPortfolioFollowerRepository(
        dynamodb_client=DynamoDBClient(
            table=dynamodb.Table(settings.model_portfolio_follower_dynamodb)
        ),
        alpaca_broker_client=alpaca_broker_client,
    )
    model_portfolio_repository = ModelPortfolioRepository(
        dynamodb_client=DynamoDBClient(
            table=dynamodb.Table(settings.model_portfolios_dynamodb)
        ),
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
    )
    portfolio_allocation_repository = PortfolioAllocationRepository(
        alpaca_broker_client=alpaca_broker_client,
        dynamodb_client=DynamoDBClient(
            table=dynamodb.Table(settings.portfolio_allocation_dynamodb)
        ),
    )
    order_repository = OrderRepository(
        alpaca_broker_client=alpaca_broker_client,
        dynamodb_client=DynamoDBClient(table=dynamodb.Table(settings.order_dynamodb)),
    )
    user_trade_lock_repository = UserTradeLockRepository(
        dynamodb_client=DynamoDBClient(
            table=dynamodb.Table(settings.user_trade_lock_dynamodb)
        )
    )

    return TradeExecutionService(
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_repository=model_portfolio_repository,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
    )


def _payload(message: Dict[str, Any]) -> Dict[str, Any]:
    """Return and validate the message payload object."""
    payload = message.get("payload")
    if not isinstance(payload, dict):
        raise TradeExecutionWorkerError("Queued message payload must be an object")
    return payload


def _execute_message(message: Dict[str, Any]) -> None:
    """Execute one trade-execution message."""
    action = message.get("action")
    payload = _payload(message)
    service = _trade_execution_service()

    if action == "portfolio_update":
        service.execute_update_in_portfolio(
            portfolio_id=payload["portfolio_id"],
            portfolio_owner_cognito_user_id=payload[
                "portfolio_owner_cognito_user_id"
            ],
            cognito_user_id=payload["cognito_user_id"],
            alpaca_account_id=payload["alpaca_account_id"],
            model_portfolio_snapshot_id=payload["model_portfolio_snapshot_id"],
            transaction_id=payload["transaction_id"],
        )
        return

    if action == "portfolio_deposit":
        service.execute_deposit_to_portfolio(
            portfolio_id=payload["portfolio_id"],
            portfolio_owner_cognito_user_id=payload[
                "portfolio_owner_cognito_user_id"
            ],
            deposit_amount=float(payload["amount"]),
            transaction_id=payload["transaction_id"],
            cognito_user_id=payload["cognito_user_id"],
            alpaca_account_id=payload["alpaca_account_id"],
        )
        return

    if action == "portfolio_withdraw":
        service.execute_withdraw_from_portfolio(
            portfolio_id=payload["portfolio_id"],
            portfolio_owner_cognito_user_id=payload[
                "portfolio_owner_cognito_user_id"
            ],
            withdraw_amount=float(payload["amount"]),
            transaction_id=payload["transaction_id"],
            alpaca_account_id=payload["alpaca_account_id"],
            cognito_user_id=payload["cognito_user_id"],
        )
        return

    if action == "portfolio_withdraw_all":
        service.execute_withdraw_all_from_portfolio(
            portfolio_id=payload["portfolio_id"],
            portfolio_owner_cognito_user_id=payload[
                "portfolio_owner_cognito_user_id"
            ],
            transaction_id=payload["transaction_id"],
            alpaca_account_id=payload["alpaca_account_id"],
            cognito_user_id=payload["cognito_user_id"],
        )
        return

    if action == "stock_buy":
        service.execute_buy_to_stock(
            symbol=str(payload["symbol"]).upper(),
            asset_id=payload["asset_id"],
            transaction_id=payload["transaction_id"],
            deposit_amount=float(payload["amount"]),
            cognito_user_id=payload["cognito_user_id"],
            alpaca_account_id=payload["alpaca_account_id"],
        )
        return

    if action == "stock_sell":
        service.execute_sell_to_stock(
            symbol=str(payload["symbol"]).upper(),
            asset_id=payload["asset_id"],
            transaction_id=payload["transaction_id"],
            withdraw_amount=float(payload["amount"]),
            alpaca_account_id=payload["alpaca_account_id"],
            cognito_user_id=payload["cognito_user_id"],
        )
        return

    if action == "stock_close":
        service.execute_close_stock(
            asset_id=payload["asset_id"],
            transaction_id=payload["transaction_id"],
            alpaca_account_id=payload["alpaca_account_id"],
            cognito_user_id=payload["cognito_user_id"],
        )
        return

    raise TradeExecutionWorkerError(f"Unsupported trade execution action '{action}'")


def _process_record(record: Dict[str, Any]) -> None:
    """Process one SQS record."""
    try:
        message = json.loads(record.get("body", "{}"))
    except json.JSONDecodeError as error:
        raise TradeExecutionWorkerError("Queued message body must be valid JSON") from error

    _execute_message(message)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process SQS messages and report per-record failures for retry."""
    if event.get("action") == "warmup":
        _trade_execution_service()
        return {"warmed": True}

    batch_item_failures = []
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as error:
            print(f"Failed processing trade execution message: {error}")
            batch_item_failures.append(
                {"itemIdentifier": record.get("messageId", "")}
            )

    return {"batchItemFailures": batch_item_failures}

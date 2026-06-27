import os
import sys
import time
from pathlib import Path
from typing import List, Dict

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[2]
backend_root = repo_root / "backend"
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from clients.alpaca_broker_client import AlpacaBrokerClient
from core.config import get_settings
from core.deps import (
    get_boto3_session,
    get_order_dynamodb_client,
    get_trade_execution_queue_url,
)
from repository.order_repository import OrderNotFoundError, OrderRepository
from services.trade_execution_queuing_service import TradeExecutionQueuingService


FUNDED_ALPACA_ACCOUNT_ID = "0bc4fb65-515c-41f7-a2ea-392ba5626c1e"
FUNDED_COGNITO_USER_ID = "f408a4e8-60f1-70d0-4c17-2377bf12babf"


load_dotenv(repo_root / ".env")


@pytest.fixture(scope="session", autouse=True)
def dev_sandbox_settings():
    os.environ["ENV"] = "dev"
    os.environ["ALPACA_ENV"] = "sandbox"
    get_settings.cache_clear()
    get_boto3_session.cache_clear()
    get_trade_execution_queue_url.cache_clear()
    get_order_dynamodb_client.cache_clear()


@pytest.fixture(scope="session")
def trade_execution_queuing_service() -> TradeExecutionQueuingService:
    settings = get_settings()
    session = get_boto3_session()
    return TradeExecutionQueuingService(
        sqs_client=session.client("sqs", region_name=settings.aws_region),
        queue_url=get_trade_execution_queue_url(),
    )


@pytest.fixture(scope="session")
def order_repository() -> OrderRepository:
    settings = get_settings()
    return OrderRepository(
        alpaca_broker_client=AlpacaBrokerClient(
            alpaca_broker_api_key=settings.alpaca_broker_api_key,
            alpaca_broker_api_secret=settings.alpaca_broker_api_secret,
            alpaca_env=settings.alpaca_env,
        ),
        dynamodb_client=get_order_dynamodb_client(),
    )


class TestEngine:
    def __init__(
        self,
        *,
        trade_execution_queuing_service: TradeExecutionQueuingService,
        order_repository: OrderRepository,
    ) -> None:
        self.trade_execution_queuing_service = trade_execution_queuing_service
        self.order_repository = order_repository

    def test_queue_stock_buy(
        self,
        *,
        symbol: str,
        asset_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> List[Dict]:
        message_id = self.trade_execution_queuing_service.queue_stock_buy(
            symbol=symbol,
            asset_id=asset_id,
            amount=amount,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )

        assert message_id

        orders = self._wait_for_orders(
            cognito_user_id=cognito_user_id,
            asset_id=asset_id,
        )

        assert len(orders) >= 1
        assert any(order["symbol"] == symbol.upper() for order in orders)
        assert all(order["cognito_user_id"] == cognito_user_id for order in orders)
        assert all(order["portfolio_id"] == asset_id for order in orders)

        return orders

    def _wait_for_orders(
        self,
        *,
        cognito_user_id: str,
        asset_id: str,
        timeout_seconds: int = 90,
    ) -> List[Dict]:
        deadline = time.monotonic() + timeout_seconds
        last_error = None
        while time.monotonic() < deadline:
            try:
                return self.order_repository.get_orders_by_portfolio(
                    cognito_user_id=cognito_user_id,
                    portfolio_id=asset_id,
                )
            except OrderNotFoundError as error:
                last_error = error
                time.sleep(5)

        raise AssertionError(
            f"Timed out waiting for queued trade orders for asset_id '{asset_id}'"
        ) from last_error


@pytest.fixture(scope="session")
def test_engine(
    trade_execution_queuing_service: TradeExecutionQueuingService,
    order_repository: OrderRepository,
) -> TestEngine:
    return TestEngine(
        trade_execution_queuing_service=trade_execution_queuing_service,
        order_repository=order_repository,
    )

import os
import sys
import json
import threading
from copy import deepcopy
from pathlib import Path
import pytest
from dotenv import load_dotenv
from typing import List, Dict, Any
repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
import uuid
from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.cognito_client import CognitoClient
from backend.services.account_lifecycle_service import AccountLifecycleService
from backend.repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from backend.repository.model_portfolio_repository import ModelPortfolioRepository
from backend.repository.portfolio_allocation_repository import PortfolioAllocationRepository
from backend.repository.order_repository import OrderRepository
from backend.repository.user_trade_lock_repository import UserTradeLockRepository
from backend.repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from backend.services.trade_execution_service import TradeExecutionService
from backend.services.trade_execution_queuing_service import TradeExecutionQueuingService
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.domain.baskt_domain import BasktPosition
from backend.domain.stock_domain import Stock
from time import monotonic, sleep
from datetime import datetime, timezone, timedelta
from backend.schema.model_portfolio_schema import ModelPortfolioPositionRequest
from collections import defaultdict
from alpaca.broker.models import Order
from alpaca.trading.enums import OrderClass, OrderSide, OrderStatus, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest
from unittest.mock import MagicMock
from backend.domain.baskt_domain import BasktPosition
from math import ceil, floor
from collections import deque
from typing import Deque
MARGIN_ERROR = 0.01
FLOAT_ERROR = 1e-6
MOCK_MARGIN = 0.000
EPS = 1e-6
FUNDED_ALPACA_ACCOUNT_ID = "0bc4fb65-515c-41f7-a2ea-392ba5626c1e"
FUNDED_COGNITO_USER_ID = "f408a4e8-60f1-70d0-4c17-2377bf12babf"

load_dotenv()
os.environ["ENV"] = "dev"
os.environ["ALPACA_ENV"] = "sandbox"
get_settings.cache_clear()

#######################################
############### CLIENTS ###############
#######################################


class MockSQSClient:
    """Small in-memory SQS client used with the mock Alpaca test mode."""

    def __init__(self) -> None:
        self.queue_url = "https://mock-sqs.local/trade-execution"
        self.messages: Deque[Dict[str, Any]] = deque()
        self.processed_messages: List[Dict[str, Any]] = []
        self.processing_errors: List[Exception] = []
        self._lambda_handler = None
        self._processor_lock = threading.Lock()

    def set_lambda_handler(self, lambda_handler: Any) -> None:
        """Register the mock Lambda invoked after a message is appended."""
        self._lambda_handler = lambda_handler

    def get_queue_url(self, QueueName: str) -> Dict[str, str]:
        return {"QueueUrl": self.queue_url}

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> Dict[str, str]:
        if QueueUrl != self.queue_url:
            raise ValueError(f"Unknown mock SQS queue URL '{QueueUrl}'.")

        message_id = str(uuid.uuid4())
        self.messages.append(
            {
                "MessageId": message_id,
                "ReceiptHandle": str(uuid.uuid4()),
                "Body": MessageBody,
                "message": json.loads(MessageBody),
            }
        )
        if self._lambda_handler is not None:
            threading.Thread(target=self._process_messages, daemon=True).start()
        return {"MessageId": message_id}

    def _process_messages(self) -> None:
        """Process queued messages from the left with one mock worker."""
        with self._processor_lock:
            while self.messages and self._lambda_handler is not None:
                message = self.messages[0]
                try:
                    self._lambda_handler(message)
                except Exception as error:
                    self.processing_errors.append(error)
                    return
                self.processed_messages.append(self.messages.popleft())

    def wait_until_idle(self, timeout_seconds: float = 10.0) -> None:
        """Wait for processing to finish and surface mock Lambda failures."""
        deadline = monotonic() + timeout_seconds
        while self.messages and not self.processing_errors:
            if monotonic() >= deadline:
                raise TimeoutError("Mock SQS did not finish processing before timeout.")
            sleep(0.01)
        if self.processing_errors:
            raise self.processing_errors[0]

    def receive_message(
        self,
        *,
        QueueUrl: str,
        MaxNumberOfMessages: int = 1,
        **_: Any,
    ) -> Dict[str, List[Dict[str, str]]]:
        if QueueUrl != self.queue_url:
            raise ValueError(f"Unknown mock SQS queue URL '{QueueUrl}'.")

        messages = [
            {
                "MessageId": message["MessageId"],
                "ReceiptHandle": message["ReceiptHandle"],
                "Body": message["Body"],
            }
            for message in list(self.messages)[:MaxNumberOfMessages]
        ]
        return {"Messages": messages} if messages else {}

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> Dict[str, Any]:
        if QueueUrl != self.queue_url:
            raise ValueError(f"Unknown mock SQS queue URL '{QueueUrl}'.")

        self.messages = deque(
            message
            for message in self.messages
            if message["ReceiptHandle"] != ReceiptHandle
        )
        return {}


class MockTradeExecutionLambda:
    """Dispatch the leftmost mock SQS message to TradeExecutionService."""

    def __init__(
        self,
        trade_execution_service: TradeExecutionService,
        user_trade_lock_repository: UserTradeLockRepository,
    ) -> None:
        self.trade_execution_service = trade_execution_service
        self.user_trade_lock_repository = user_trade_lock_repository

    def __call__(self, sqs_message: Dict[str, Any]) -> None:
        message = sqs_message["message"]
        action = message["action"]
        payload = message["payload"]

        # Real SQS invokes Lambda after send_message returns and the queueing
        # service releases this lock. The mock worker waits for the same state.
        self._wait_until_queue_lock_is_released(payload["cognito_user_id"])

        if action == "portfolio_update":
            self.trade_execution_service.execute_update_in_portfolio(
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
            self.trade_execution_service.execute_deposit_to_portfolio(
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
            self.trade_execution_service.execute_withdraw_from_portfolio(
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
            self.trade_execution_service.execute_withdraw_all_from_portfolio(
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
            self.trade_execution_service.execute_buy_to_stock(
                symbol=str(payload["symbol"]).upper(),
                asset_id=payload["asset_id"],
                transaction_id=payload["transaction_id"],
                deposit_amount=float(payload["amount"]),
                cognito_user_id=payload["cognito_user_id"],
                alpaca_account_id=payload["alpaca_account_id"],
            )
            return

        if action == "stock_sell":
            self.trade_execution_service.execute_sell_to_stock(
                symbol=str(payload["symbol"]).upper(),
                asset_id=payload["asset_id"],
                transaction_id=payload["transaction_id"],
                withdraw_amount=float(payload["amount"]),
                alpaca_account_id=payload["alpaca_account_id"],
                cognito_user_id=payload["cognito_user_id"],
            )
            return

        if action == "stock_close":
            self.trade_execution_service.execute_close_stock(
                asset_id=payload["asset_id"],
                transaction_id=payload["transaction_id"],
                alpaca_account_id=payload["alpaca_account_id"],
                cognito_user_id=payload["cognito_user_id"],
            )
            return

        raise ValueError(f"Unsupported mock trade execution action '{action}'.")

    def _wait_until_queue_lock_is_released(
        self,
        cognito_user_id: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        deadline = monotonic() + timeout_seconds
        while self.user_trade_lock_repository.get_lock(cognito_user_id) is not None:
            if monotonic() >= deadline:
                raise TimeoutError(
                    f"Queue lock for user '{cognito_user_id}' was not released."
                )
            sleep(0.01)


@pytest.fixture(scope="session")
def sqs_client(request) -> Any:
    if request.config.getoption("--mock_alpaca"):
        return MockSQSClient()
    return app_deps.get_sqs_client_cached()


@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

"""
Create a mock alpaca client that i can use to test off market hours

"""
def pytest_addoption(parser):
    parser.addoption(
        "--mock_alpaca",
        action="store_true",
        default=False,
        help="Use in-memory mock Alpaca client for integration tests",
    )

def _build_mock_alpaca_broker_client(prices: Dict[str, float]) -> AlpacaBrokerClient:
    real_client = app_deps.get_alpaca_broker_client()
    mock = MagicMock(spec=AlpacaBrokerClient, wraps=real_client)
    mock.client = MagicMock()

    state: Dict[str, Dict[str,Order | BasktPosition | float]] = {
        "positions": defaultdict(dict), # alpaca_account_id -> position.symbol -> position
        "orders": defaultdict(dict), # alpaca_account_id -> order.id -> order
        "prices": prices,
    }

    def _make_order(alpaca_account_id: str, symbol: str, order_side: OrderSide, qty: float):
        now = datetime.now(timezone.utc)
        order_id = str(uuid.uuid4())
        order: Order = Order(
            client_order_id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            submitted_at=now,
            filled_at=None,
            id=order_id,
            symbol=symbol,
            qty=qty,
            filled_qty=None,
            filled_avg_price=None,
            side=order_side,
            status=OrderStatus.NEW,
            notional=None,
            order_class=OrderClass.SIMPLE,
            time_in_force=TimeInForce.DAY,
            extended_hours=False,
            type=OrderType.MARKET,
        )
        state["orders"][alpaca_account_id][order_id] = order
        return order
    
    def _apply_filled_order_to_positions(alpaca_account_id: str, order: Order) -> None:
        """Apply one filled order to in-memory position state and allocation amount."""
        order_symbol = order.symbol
        order_direction = 1 if order.side.name == "BUY" else -1
        order_filled_avg_price = order.filled_avg_price
        order_filled_quantity = order.filled_qty

        if order_symbol not in state["positions"][alpaca_account_id]:
            state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=order_filled_quantity,
                filled_avg_price=order_filled_avg_price,
                direction=order_direction
            )
            return 
        
        pos: BasktPosition = state["positions"][alpaca_account_id][order_symbol]
        pos_avg = pos.filled_avg_price
        pos_qty = pos.filled_quantity
        pos_dir = pos.direction

        pos_signed = pos_dir * pos_qty
        ord_signed = order_direction * order_filled_quantity

        # Same-side increase: weighted-average entry and add full notional.
        if pos_signed * ord_signed > 0:
            new_qty = pos_qty + order_filled_quantity
            new_avg = ((pos_qty * pos_avg) + (order_filled_quantity * order_filled_avg_price)) / new_qty
            state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=new_qty,
                filled_avg_price=new_avg,
                direction=pos_dir
            )
            return 
        
        remaining = pos_qty - order_filled_quantity

        # Fully closed.
        if abs(remaining) <= EPS:
            del state["positions"][alpaca_account_id][order_symbol]
            return 

        # Partial close, same direction remains.
        if remaining > 0:
            state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=remaining,
                filled_avg_price=pos_avg,
                direction=pos_dir
            )
            return 

        # Direction flip: excess opens new position at order avg.
        flipped_qty = abs(remaining)
        state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
            symbol=order_symbol,
            filled_avg_price=order_filled_avg_price,
            filled_quantity=flipped_qty,
            direction=order_direction
        )
        return

    def _apply_fill(alpaca_account_id: str, order_id: str) -> Order:
        order: Order = state["orders"][alpaca_account_id][order_id]
        mid_price = float(state["prices"][order.symbol])
        bid_price = float(floor(mid_price * (1 - MOCK_MARGIN) * 100) / 100)
        ask_price = float(ceil(mid_price * (1 + MOCK_MARGIN) * 100) / 100)
        fill_price = ask_price if order.side == OrderSide.BUY else bid_price

        order.filled_at = datetime.now(timezone.utc)
        order.filled_qty = order.qty
        order.filled_avg_price = fill_price
        order.status = OrderStatus.FILLED
        order.notional = str(order.qty * fill_price)

        state["orders"][alpaca_account_id][order_id] = order

        _apply_filled_order_to_positions(alpaca_account_id=alpaca_account_id, order=order)
        return order
    
    def get_latest_price(symbols: List[str]):
        return {symbol: float(state["prices"][symbol]) for symbol in symbols}


    def execute_quantity_buy(symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str):
        return _make_order(alpaca_account_id=alpaca_account_id, symbol=symbol, order_side=OrderSide.BUY, qty=float(quantity))

    def execute_quantity_sell(symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str):
        return _make_order(alpaca_account_id=alpaca_account_id, symbol=symbol, order_side=OrderSide.SELL, qty=float(quantity))

    def execute_quantity_fractional_sell(symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str):
        # Match real Alpaca client wrapper behavior:
        # sell ceil(quantity), then buy back the excess to achieve exact net sell = quantity.
        sell_order = execute_quantity_sell(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, symbol=symbol, quantity=ceil(quantity))
        if ceil(quantity) - quantity <= 0:
            return sell_order, None
        accepted_sell_order = deepcopy(sell_order)
        _apply_fill(alpaca_account_id=alpaca_account_id, order_id=str(sell_order.id))
        buy_order = execute_quantity_buy(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, symbol=symbol, quantity=ceil(quantity) - quantity)
        return accepted_sell_order, buy_order

    def execute_close_position(symbol: str, alpaca_account_id: str, cognito_user_id: str):
        position: BasktPosition = state["positions"][alpaca_account_id][symbol]
        order_side = OrderSide.SELL if position.direction == 1 else OrderSide.BUY
        return _make_order(
            alpaca_account_id=alpaca_account_id,
            symbol=symbol,
            order_side=order_side,
            qty=float(position.filled_quantity),
        )

    def execute_long_to_short_sell(
        symbol: str,
        quantity: float,
        curr_quantity: float,
        alpaca_account_id: str,
        cognito_user_id: str,
    ):
        close_order = execute_close_position(
            symbol=symbol,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        accepted_close_order = deepcopy(close_order)
        _apply_fill(alpaca_account_id=alpaca_account_id, order_id=str(close_order.id))
        short_orders = execute_quantity_fractional_sell(
            symbol=symbol,
            quantity=quantity - curr_quantity,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        return [accepted_close_order] + [
            order for order in short_orders if order is not None
        ]

    def execute_short_to_long_buy(
        symbol: str,
        quantity: float,
        curr_quantity: float,
        alpaca_account_id: str,
        cognito_user_id: str,
    ):
        close_order = execute_close_position(
            symbol=symbol,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        accepted_close_order = deepcopy(close_order)
        _apply_fill(alpaca_account_id=alpaca_account_id, order_id=str(close_order.id))
        buy_order = execute_quantity_buy(
            symbol=symbol,
            quantity=quantity - curr_quantity,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        return [accepted_close_order, buy_order]


    def get_baskt_positions_dict(alpaca_account_id: str, cognito_user_id: str) -> Dict[str, BasktPosition]:
        return state["positions"][alpaca_account_id]
    

    def get_order_by_id(alpaca_account_id: str, cognito_user_id: str, order_id: str):
        order = state["orders"][alpaca_account_id][order_id]
        if order.status != OrderStatus.FILLED:
            order = _apply_fill(alpaca_account_id=alpaca_account_id, order_id=order_id)
        return order

    def execute_close_all_position(
        alpaca_account_id: str,
        cognito_user_id: str | None = None,
        cancel_open_orders: bool = True,
        wait: bool = True,
        timeout_sec: int = 20,
        poll_interval_sec: float = 2.0,
    ):
        state["positions"][alpaca_account_id].clear()
        return True

    def get_orders_for_account(account_id: str, filter: GetOrdersRequest | None = None):
        orders = list(state["orders"][account_id].values())
        if filter is not None and filter.status == QueryOrderStatus.OPEN:
            return [order for order in orders if order.status != OrderStatus.FILLED]
        return orders

    def cancel_order_for_account_by_id(account_id: str, order_id: str):
        order = state["orders"][account_id][order_id]
        order.status = OrderStatus.CANCELED
        state["orders"][account_id][order_id] = order
        return True

    def get_stock_by_asset_id(*, asset_id: str) -> Stock:
        return Stock(
            symbol="AAPL",
            tradable=True,
            fractionable=True,
            shortable=True,
            marginable=True,
            stock_id=asset_id,
            stock_class="US_EQUITY",
        )

    mock.execute_quantity_buy.side_effect = execute_quantity_buy
    mock.execute_quantity_sell.side_effect = execute_quantity_sell
    mock.execute_quantity_fractional_sell.side_effect = execute_quantity_fractional_sell
    mock.execute_close_position.side_effect = execute_close_position
    mock.execute_long_to_short_sell.side_effect = execute_long_to_short_sell
    mock.execute_short_to_long_buy.side_effect = execute_short_to_long_buy
    mock.get_baskt_positions_dict.side_effect = get_baskt_positions_dict
    mock.get_latest_price.side_effect = get_latest_price
    mock.get_order_by_id.side_effect = get_order_by_id
    mock.execute_close_all_position.side_effect = execute_close_all_position
    mock.client.get_orders_for_account.side_effect = get_orders_for_account
    mock.client.cancel_order_for_account_by_id.side_effect = cancel_order_for_account_by_id
    mock.get_stock_by_asset_id.side_effect = get_stock_by_asset_id

    return mock

@pytest.fixture(scope="session")
def alpaca_broker_client(request) -> AlpacaBrokerClient:
    if request.config.getoption("--mock_alpaca"):
        return _build_mock_alpaca_broker_client(
            {
                "AAPL": 200.0,
                "MSFT": 100.0,
                "AMZN": 180.0,
                "META": 450.0,
                "TSLA": 170.0,
                "NVDA": 900.0,
                "GOOG": 160.0,
                "AMD": 160.0,
                "PLTR": 25.0,
                "SPY": 500.0,
                "QQQ": 430.0,
                "UBER": 100.0,
                "LLY": 95.0
            }
        )

    return app_deps.get_alpaca_broker_client()



########################################
############## REPOSITORY ##############
########################################

@pytest.fixture(scope="session")
def model_portfolio_follower_repository(
    alpaca_broker_client: AlpacaBrokerClient,
) -> ModelPortfolioFollowerRepository:
    
    app_deps.get_model_portfolio_follower_dynamodb_client.cache_clear()
    model_portfolio_follower_dynamodb_client = app_deps.get_model_portfolio_follower_dynamodb_client()

    return app_deps.get_model_portfolio_follower_repository(
        model_portfolio_follower_dynamodb_client=model_portfolio_follower_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )


@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository() -> ModelPortfolioUpdateLockRepository:

    app_deps.get_model_portfolio_update_lock_dynamodb_client.cache_clear()
    model_portfolio_update_lock_dynamodb_client = app_deps.get_model_portfolio_update_lock_dynamodb_client()

    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=model_portfolio_update_lock_dynamodb_client
    )


@pytest.fixture(scope="session")
def model_portfolio_repository(
    alpaca_broker_client: AlpacaBrokerClient,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository
) -> ModelPortfolioRepository:

    app_deps.get_model_portfolio_dynamodb_client.cache_clear()
    model_portfolio_dynamodb_client = app_deps.get_model_portfolio_dynamodb_client()

    return app_deps.get_model_portfolio_repository(
        dynamodb=model_portfolio_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
    )


@pytest.fixture(scope="session")
def portfolio_allocation_repository(alpaca_broker_client: AlpacaBrokerClient) -> PortfolioAllocationRepository:

    app_deps.get_portfolio_allocation_dynamodb_client.cache_clear()
    portfolio_allocation_dynamodb_client = app_deps.get_portfolio_allocation_dynamodb_client()
    return app_deps.get_portfolio_allocation_repository(
        portfolio_allocation_dynamodb_client=portfolio_allocation_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )

@pytest.fixture(scope="session")
def order_repository(alpaca_broker_client: AlpacaBrokerClient) -> OrderRepository:

    app_deps.get_order_dynamodb_client.cache_clear()
    order_dynamodb_client = app_deps.get_order_dynamodb_client()

    return app_deps.get_order_repository(
        order_dynamodb_client=order_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )

@pytest.fixture(scope="session")
def user_trade_lock_repository() -> UserTradeLockRepository:

    app_deps.get_user_trade_lock_dynamodb_client.cache_clear()
    user_trade_lock_dynamodb_client = app_deps.get_user_trade_lock_dynamodb_client()

    return app_deps.get_user_trade_lock_repository(
        user_trade_lock_dynamodb_client=user_trade_lock_dynamodb_client
    )

##################################################
#################### SERVICES ####################
##################################################
    
@pytest.fixture(scope="session")
def account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
) -> AccountLifecycleService:
    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
    )

@pytest.fixture(scope="session")
def trade_execution_service(
    model_portfolio_repository: ModelPortfolioRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    order_repository: OrderRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    user_trade_lock_repository: UserTradeLockRepository
) -> TradeExecutionService:

    return app_deps.get_trade_execution_service(
        model_portfolio_repository=model_portfolio_repository,
        alpaca_broker_client=alpaca_broker_client,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
    )

@pytest.fixture(scope="session")
def trade_execution_queuing_service(
    sqs_client: Any,
    trade_execution_service: TradeExecutionService,
    model_portfolio_repository: ModelPortfolioRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
) -> TradeExecutionQueuingService:

    queue_url = (
        sqs_client.queue_url
        if isinstance(sqs_client, MockSQSClient)
        else app_deps.get_trade_execution_queue_url()
    )
    if isinstance(sqs_client, MockSQSClient):
        sqs_client.set_lambda_handler(
            MockTradeExecutionLambda(
                trade_execution_service=trade_execution_service,
                user_trade_lock_repository=user_trade_lock_repository,
            )
        )
    return TradeExecutionQueuingService(
        sqs_client=sqs_client,
        queue_url=queue_url,
        model_portfolio_repository=model_portfolio_repository,
        portfolio_allocation_repository=portfolio_allocation_repository,
        alpaca_broker_client=alpaca_broker_client,
        user_trade_lock_repository=user_trade_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
    )



###########################################
############### TEST ENGINE ###############
###########################################

class TestEngine:
    def __init__(
        self,
        account_lifecycle_service: AccountLifecycleService,
        trade_execution_service: TradeExecutionService,
        trade_execution_queuing_service: TradeExecutionQueuingService,
        sqs_client: Any,
        model_portfolio_repository: ModelPortfolioRepository,
        order_repository: OrderRepository,
        alpaca_broker_client: AlpacaBrokerClient,
        portfolio_allocation_repository: PortfolioAllocationRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    ):
        self.account_lifecycle_service = account_lifecycle_service
        self.trade_execution_service = trade_execution_service
        self.trade_execution_queuing_service = trade_execution_queuing_service
        self.sqs_client = sqs_client
        self.model_portfolio_repository = model_portfolio_repository
        self.order_repository = order_repository
        self.alpaca_broker_client = alpaca_broker_client
        self.portfolio_allocation_repository = portfolio_allocation_repository
        self.model_portfolio_follower_repository = model_portfolio_follower_repository
        self.baskt_account_portfolio_positions = {}
        self.model_portfolio_update_times = defaultdict(list) # also used to calculate model portfolio position history length
        self.portfolio_allocation_history_size = 0

    def test_queue_stock_buy(
        self,
        *,
        symbol: str,
        asset_id: str,
        amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ) -> str:
        """Queue a stock buy and verify that mock SQS received its payload."""
        message_id = self.trade_execution_queuing_service.queue_stock_buy(
            symbol=symbol,
            asset_id=asset_id,
            amount=amount,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )

        if isinstance(self.sqs_client, MockSQSClient):
            self.sqs_client.wait_until_idle()
            processed_message = self.sqs_client.processed_messages[-1]
            assert processed_message["MessageId"] == message_id
            assert processed_message["message"]["action"] == "stock_buy"
            assert processed_message["message"]["payload"]["asset_id"] == asset_id

        return message_id

    def _queue_and_get_response(
        self,
        *,
        queue_action: Any,
        alpaca_account_id: str,
        cognito_user_id: str,
        portfolio_id: str,
        timeout_seconds: float = 60.0,
    ) -> Dict[str, Any]:
        """Queue one action and wait for either mock or AWS Lambda execution."""
        previous_transaction_ids = set()
        if self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
        ):
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            previous_transaction_ids = {
                transaction.transaction_id
                for transaction in allocation.transaction_history
            }

        message_id = queue_action()
        if isinstance(self.sqs_client, MockSQSClient):
            self.sqs_client.wait_until_idle(timeout_seconds=timeout_seconds)
            processed_message = next(
                message
                for message in reversed(self.sqs_client.processed_messages)
                if message["MessageId"] == message_id
            )
            transaction_id = processed_message["message"]["payload"]["transaction_id"]
        else:
            transaction_id = self._wait_for_new_transaction(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                previous_transaction_ids=previous_transaction_ids,
                timeout_seconds=timeout_seconds,
            )

        transaction = self._wait_for_transaction_execution(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
            transaction_id=transaction_id,
            timeout_seconds=timeout_seconds,
        )
        order_rows = self._wait_for_transaction_orders(
            transaction_id=transaction_id,
            expected_order_count=int(transaction.number_orders or 0),
            timeout_seconds=timeout_seconds,
        )
        order_ids = {str(row["order_id"]) for row in order_rows}
        orders = [
            self.alpaca_broker_client.get_order_by_id(
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
                order_id=order_id,
            )
            for order_id in order_ids
        ]
        return {"transaction_id": transaction_id, "orders": orders}

    def _wait_for_new_transaction(
        self,
        *,
        cognito_user_id: str,
        portfolio_id: str,
        previous_transaction_ids: set[str],
        timeout_seconds: float,
    ) -> str:
        """Find the transaction persisted immediately before the AWS SQS send."""
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            new_transactions = [
                transaction
                for transaction in allocation.transaction_history
                if transaction.transaction_id not in previous_transaction_ids
            ]
            if new_transactions:
                return new_transactions[-1].transaction_id
            sleep(0.25)
        raise TimeoutError(
            f"No new transaction appeared for allocation '{portfolio_id}'."
        )

    def _wait_for_transaction_execution(
        self,
        *,
        cognito_user_id: str,
        portfolio_id: str,
        transaction_id: str,
        timeout_seconds: float,
    ) -> Any:
        """Wait until Lambda advances a queued transaction to an execution state."""
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            transaction = next(
                transaction
                for transaction in allocation.transaction_history
                if transaction.transaction_id == transaction_id
            )
            status = transaction.status.upper()
            if status == "FAILED":
                raise AssertionError(
                    transaction.status_explanation
                    or f"Queued transaction '{transaction_id}' failed."
                )
            if status not in {"QUEUED", "PROCESSING"}:
                return transaction
            sleep(0.25)
        raise TimeoutError(
            f"Transaction '{transaction_id}' was not executed before timeout."
        )

    def _wait_for_transaction_orders(
        self,
        *,
        transaction_id: str,
        expected_order_count: int,
        timeout_seconds: float,
    ) -> List[Dict[str, Any]]:
        """Wait for Lambda's order records to become visible in DynamoDB."""
        if expected_order_count == 0:
            return []

        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            try:
                rows = self.order_repository.get_orders_by_transaction(
                    transaction_id=transaction_id
                )
            except Exception:
                rows = []
            if len(rows) >= expected_order_count:
                return rows
            sleep(0.25)
        raise TimeoutError(
            f"Orders for transaction '{transaction_id}' were not visible before timeout."
        )
    
    def test_create_portfolio(
        self,
        symbols: List[str],
        directions: List[int],
        target_weights: List[float],
        leverages: List[float],
        portfolio_name: str,
        portfolio_owner_cognito_user_id: str
    ):

        positions_request: List[ModelPortfolioPositionRequest] = [
            ModelPortfolioPositionRequest(symbol=s, target_weight=w, direction=d, leverage=l)
            for s, w, d, l in zip(symbols, target_weights, directions, leverages)
        ]
        portfolio_id = self.model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            portfolio_name=portfolio_name,
            positions_request=positions_request,
        )
        self.model_portfolio_update_times[portfolio_id].append(datetime.now(timezone.utc))

        model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
        assert model_portfolio is not None
        assert len(model_portfolio.position_history) == len(self.model_portfolio_update_times[portfolio_id])
        model_snapshot = model_portfolio.position_history[-1]
        for test_position, model_position in zip(sorted(positions_request, key = lambda x: x.symbol),sorted(model_snapshot.positions, key = lambda x: x.symbol)):
            assert test_position.direction == model_position.direction
            assert test_position.leverage == model_position.leverage
            assert test_position.symbol == model_position.symbol
            assert test_position.target_weight == model_position.target_weight

        return portfolio_id

    def test_deposit(
        self,
        deposit_amount: float,
        portfolio_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
        portfolio_owner_cognito_user_id: str,
    ):
        dep_response = self._queue_and_get_response(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
            queue_action=lambda: self.trade_execution_queuing_service.queue_portfolio_deposit(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                amount=deposit_amount,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            ),
        )
        dep_orders = dep_response["orders"]

        if cognito_user_id not in self.baskt_account_portfolio_positions:
            self.baskt_account_portfolio_positions[cognito_user_id] = {}

        if portfolio_id not in self.baskt_account_portfolio_positions[cognito_user_id]:
            self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id] = {
                "all_orders":[],
                "filled_amounts":[]
            }

        # Wait for orders to be filled
        sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            portfolio_id=portfolio_id,
        )

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
        assert len(dep_orders) + len(self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in dep_orders + self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, order_id=order_id, cognito_user_id=cognito_user_id)
            assert order_id in rows2_dict_order_id
            assert rows2_dict_order_id[order_id]["symbol"] == alpaca_order.symbol
            assert float(rows2_dict_order_id[order_id]["filled_qty"]) == float(alpaca_order.filled_qty)
            assert float(rows2_dict_order_id[order_id]["filled_avg_price"]) == float(alpaca_order.filled_avg_price)

        orders_db_symbols_quantity = {}
        for row in rows2:
            symbol = row["symbol"]
            side = 1 if (str(row["side"])=="BUY") else -1
            filled_qty = float(row["filled_qty"])
            orders_db_symbols_quantity[symbol] = (abs(filled_qty) * side) + orders_db_symbols_quantity.get(symbol,0)
            if abs(orders_db_symbols_quantity[symbol]) <= FLOAT_ERROR:
                del orders_db_symbols_quantity[symbol]

        # match order_db and portfolio_allocation
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id,portfolio_id=portfolio_id)
        snapshot = allocation.position_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
        assert symbols_snapshot_sorted == baskt_symbols_sorted
        alpaca_filled_amount = 0.0
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in baskt_positions_dict
            assert abs(snapshot_position.filled_quantity - baskt_positions_dict[snapshot_position.symbol].filled_quantity) <= FLOAT_ERROR
            assert abs(snapshot_position.filled_avg_price - baskt_positions_dict[snapshot_position.symbol].filled_avg_price) <= FLOAT_ERROR
            assert snapshot_position.direction == baskt_positions_dict[snapshot_position.symbol].direction
            alpaca_filled_amount += (baskt_positions_dict[snapshot_position.symbol].filled_quantity * baskt_positions_dict[snapshot_position.symbol].filled_avg_price)
        assert abs(allocation.total_cost_basis - alpaca_filled_amount) <= FLOAT_ERROR

        # match portfolio_allocation to model_portfolio
        model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
        model_portfolio_model_positions = model_portfolio.position_history[-1].positions
        model_symbols_sorted = sorted([model_position.symbol for model_position in model_portfolio_model_positions])
        assert model_symbols_sorted == baskt_symbols_sorted
        for model_position in model_portfolio_model_positions:
            model_position_symbol = model_position.symbol
            assert model_position_symbol in baskt_positions_dict
            assert model_position.direction == baskt_positions_dict[model_position_symbol].direction
            assert abs(model_position.target_weight - ((baskt_positions_dict[model_position_symbol].filled_avg_price * baskt_positions_dict[model_position_symbol].filled_quantity) / alpaca_filled_amount)) <= MARGIN_ERROR

        # Validate incremental deposit amount
        prev_filled_amount = self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["filled_amounts"][-1] if self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["filled_amounts"] else 0.0
        incremental_amount = alpaca_filled_amount - prev_filled_amount
        assert abs(deposit_amount - incremental_amount) / deposit_amount <= MARGIN_ERROR

        self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"].extend(dep_orders)
        self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["filled_amounts"].append(alpaca_filled_amount)
        self.portfolio_allocation_history_size = len(allocation.position_history)

        # Validate user is in model portfolio's followers
        model_portfolio_followers = self.model_portfolio_follower_repository.get_model_portfolio_followers(portfolio_id=portfolio_id)
        assert {"alpaca_account_id": alpaca_account_id, "cognito_user_id": cognito_user_id} in model_portfolio_followers

        return dep_response

    def test_update_effect(
        self,
        portfolio_owner_cognito_user_id: str,
        portfolio_id: str,
        ud_orders_dict: Dict
    ):
        # Test effect for each follower
        followers_alpaca_account_id_cognito_user_id = self.model_portfolio_follower_repository.get_model_portfolio_followers(portfolio_id=portfolio_id)
        assert sorted(list(ud_orders_dict.keys())) == sorted(
            follower_alpaca_account_id_cognito_user_id["cognito_user_id"] 
            for follower_alpaca_account_id_cognito_user_id in followers_alpaca_account_id_cognito_user_id
            )
        for follower_alpaca_account_id_cognito_user_id in followers_alpaca_account_id_cognito_user_id:
            previous_position_history_size = self.portfolio_allocation_history_size
            cognito_user_id = follower_alpaca_account_id_cognito_user_id["cognito_user_id"]
            alpaca_account_id = follower_alpaca_account_id_cognito_user_id["alpaca_account_id"]
            self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                portfolio_id=portfolio_id,
            )

            ud_orders = ud_orders_dict[cognito_user_id]["orders"]
            # match alpaca orders and order_db
            rows2 = self.order_repository.get_orders_by_portfolio(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
            assert len(ud_orders) + len(self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]) == len(rows2)
            rows2_dict_order_id = {
                row["order_id"]: {
                    "symbol": row["symbol"],
                    "filled_qty": row["filled_qty"],
                    "filled_avg_price": row["filled_avg_price"],

                } 
                for row in rows2
            }
            for order in ud_orders + self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]:
                order_id = str(order.id)
                alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, order_id=order_id)
                assert order_id in rows2_dict_order_id
                assert rows2_dict_order_id[order_id]["symbol"] == alpaca_order.symbol
                assert float(rows2_dict_order_id[order_id]["filled_qty"]) == float(alpaca_order.filled_qty)
                assert float(rows2_dict_order_id[order_id]["filled_avg_price"]) == float(alpaca_order.filled_avg_price)

            orders_db_symbols_quantity = {}
            for row in rows2:
                symbol = row["symbol"]
                side = 1 if (str(row["side"])=="BUY") else -1
                filled_qty = float(row["filled_qty"])
                orders_db_symbols_quantity[symbol] = (abs(filled_qty)*side) + orders_db_symbols_quantity.get(symbol, 0)
                if abs(orders_db_symbols_quantity[symbol]) <= FLOAT_ERROR:
                    del orders_db_symbols_quantity[symbol]

            # match order_db and portfolio_allocation
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id,portfolio_id=portfolio_id)
            assert allocation is not None and len(allocation.position_history) == previous_position_history_size + 1
            snapshot = allocation.position_history[-1]
            symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
            symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
            assert symbols_orders_db_sorted == symbols_snapshot_sorted
            for snapshot_position in snapshot.positions:
                assert snapshot_position.symbol in orders_db_symbols_quantity
                assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR

            # match portfolio_allocation to alpaca
            baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
            assert symbols_snapshot_sorted == baskt_symbols_sorted
            alpaca_filled_amount = 0.0
            for snapshot_position in snapshot.positions:
                assert snapshot_position.symbol in baskt_positions_dict
                assert abs(snapshot_position.filled_quantity - baskt_positions_dict[snapshot_position.symbol].filled_quantity) <= FLOAT_ERROR
                assert abs(snapshot_position.filled_avg_price - baskt_positions_dict[snapshot_position.symbol].filled_avg_price) <= FLOAT_ERROR
                assert snapshot_position.direction == baskt_positions_dict[snapshot_position.symbol].direction
                alpaca_filled_amount += (baskt_positions_dict[snapshot_position.symbol].filled_quantity * baskt_positions_dict[snapshot_position.symbol].filled_avg_price)
            assert abs(allocation.total_cost_basis - alpaca_filled_amount) <= FLOAT_ERROR

            # match alpaca to model_positions
            model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
            model_portfolio_model_positions = model_portfolio.position_history[-1].positions
            model_symbols_sorted = sorted([model_position.symbol for model_position in model_portfolio_model_positions])
            assert model_symbols_sorted == baskt_symbols_sorted
            for model_position in model_portfolio_model_positions:
                model_position_symbol = model_position.symbol
                assert model_position_symbol in baskt_positions_dict
                assert model_position.direction == baskt_positions_dict[model_position_symbol].direction
                assert abs(model_position.target_weight - ((baskt_positions_dict[model_position_symbol].filled_avg_price * baskt_positions_dict[model_position_symbol].filled_quantity) / alpaca_filled_amount)) <= MARGIN_ERROR

            prev_fill_amount = self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["filled_amounts"][-1]
            assert abs(prev_fill_amount - alpaca_filled_amount) / prev_fill_amount <= MARGIN_ERROR

            self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["filled_amounts"].append(alpaca_filled_amount)
            self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"].extend(ud_orders)
            self.portfolio_allocation_history_size = len(allocation.position_history)

    def test_update(
        self,
        portfolio_owner_cognito_user_id: str,
        portfolio_id: str,
        new_symbols: List[str],
        new_directions: List[int],
        new_target_weights: List[float],
        new_leverages: List[float],
    ):
        new_positions: List[ModelPortfolioPositionRequest] = [
            ModelPortfolioPositionRequest(
                symbol=s, target_weight=w, direction=d, leverage=l
            )
            for s, w, d, l in zip(new_symbols, new_target_weights, new_directions, new_leverages)
        ]

        update_time = self.model_portfolio_update_times[portfolio_id][-1] + timedelta(minutes = 2)
        updated, new_snapshot_id = self.model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=new_positions,
            update_time=update_time
        )
        if not updated or new_snapshot_id is None:
            return {}
        followers = self.model_portfolio_follower_repository.get_model_portfolio_followers(
            portfolio_id=portfolio_id
        )
        previous_transaction_ids = {}
        for follower in followers:
            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=follower["cognito_user_id"],
                portfolio_id=portfolio_id,
            )
            previous_transaction_ids[follower["cognito_user_id"]] = {
                transaction.transaction_id
                for transaction in allocation.transaction_history
            }

        message_ids = self.trade_execution_queuing_service.queue_portfolio_update(
            portfolio_id=portfolio_id,
            model_portfolio_snapshot_id=new_snapshot_id,
        )
        if isinstance(self.sqs_client, MockSQSClient):
            self.sqs_client.wait_until_idle()

        updated_orders_dict = {}
        followers_by_user = {
            follower["cognito_user_id"]: follower
            for follower in followers
        }
        for cognito_user_id, message_id in message_ids.items():
            if isinstance(self.sqs_client, MockSQSClient):
                processed_message = next(
                    message
                    for message in reversed(self.sqs_client.processed_messages)
                    if message["MessageId"] == message_id
                )
                transaction_id = processed_message["message"]["payload"]["transaction_id"]
            else:
                transaction_id = self._wait_for_new_transaction(
                    cognito_user_id=cognito_user_id,
                    portfolio_id=portfolio_id,
                    previous_transaction_ids=previous_transaction_ids[cognito_user_id],
                    timeout_seconds=60.0,
                )
            transaction = self._wait_for_transaction_execution(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                transaction_id=transaction_id,
                timeout_seconds=60.0,
            )
            rows = self._wait_for_transaction_orders(
                transaction_id=transaction_id,
                expected_order_count=int(transaction.number_orders or 0),
                timeout_seconds=60.0,
            )
            order_ids = {str(row["order_id"]) for row in rows}
            alpaca_account_id = followers_by_user[cognito_user_id]["alpaca_account_id"]
            updated_orders_dict[cognito_user_id] = {
                "transaction_id": transaction_id,
                "orders": [
                    self.alpaca_broker_client.get_order_by_id(
                        alpaca_account_id=alpaca_account_id,
                        cognito_user_id=cognito_user_id,
                        order_id=order_id,
                    )
                    for order_id in order_ids
                ],
            }
        self.model_portfolio_update_times[portfolio_id].append(update_time)

        # Wait for orders to be filled
        sleep(2)

        return updated_orders_dict

    def test_withdraw(
        self,
        portfolio_owner_cognito_user_id: str,
        cognito_user_id: str,
        alpaca_account_id,
        portfolio_id: str,
        withdraw_amount: float,
        slippage_correction: int = 1
    ):
        market_value = 0.0
        portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
        snapshot = portfolio_allocation.position_history[-1]
        symbols = [position.symbol for position in snapshot.positions]
        quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
        for snapshot_position in snapshot.positions:
            price = quotes[snapshot_position.symbol]
            market_value += (price * snapshot_position.filled_quantity)

        wd_response = self._queue_and_get_response(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
            queue_action=lambda: self.trade_execution_queuing_service.queue_portfolio_withdrawal(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                amount=withdraw_amount,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        # Wait for orders to be filled
        sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            portfolio_id=portfolio_id,
        )   
        self.portfolio_allocation_history_size+=1

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)

        assert len(self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]) + len(wd_orders) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in wd_orders + self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, order_id=order_id)
            assert order_id in rows2_dict_order_id
            assert rows2_dict_order_id[order_id]["symbol"] == alpaca_order.symbol
            assert float(rows2_dict_order_id[order_id]["filled_qty"]) == float(alpaca_order.filled_qty)
            assert float(rows2_dict_order_id[order_id]["filled_avg_price"]) == float(alpaca_order.filled_avg_price)

        orders_db_symbols_quantity = {}
        for row in rows2:
            symbol = row["symbol"]
            side = 1 if (str(row["side"])=="BUY") else -1
            filled_qty = float(row["filled_qty"]) 
            orders_db_symbols_quantity[symbol] = (abs(filled_qty)*side) + orders_db_symbols_quantity.get(symbol,0)
            if abs(orders_db_symbols_quantity[symbol]) <= FLOAT_ERROR:
                del orders_db_symbols_quantity[symbol]

        # match order_db and portfolio_allocation
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id,portfolio_id=portfolio_id)
        assert allocation is not None and len(allocation.position_history) == self.portfolio_allocation_history_size
        snapshot = allocation.position_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
        assert symbols_snapshot_sorted == baskt_symbols_sorted
        alpaca_filled_amount2 = 0.0

        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in baskt_positions_dict
            assert abs(snapshot_position.filled_quantity - baskt_positions_dict[snapshot_position.symbol].filled_quantity) <= FLOAT_ERROR
            assert abs(snapshot_position.filled_avg_price - baskt_positions_dict[snapshot_position.symbol].filled_avg_price) <= FLOAT_ERROR
            assert snapshot_position.direction == baskt_positions_dict[snapshot_position.symbol].direction
            alpaca_filled_amount2 += (baskt_positions_dict[snapshot_position.symbol].filled_quantity * baskt_positions_dict[snapshot_position.symbol].filled_avg_price)
        assert abs(allocation.total_cost_basis - alpaca_filled_amount2) <= FLOAT_ERROR

        # match alpaca to test positions
        model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
        model_portfolio_model_positions = model_portfolio.position_history[-1].positions
        model_symbols_sorted = sorted([model_position.symbol for model_position in model_portfolio_model_positions])
        assert model_symbols_sorted == baskt_symbols_sorted
        for model_position in model_portfolio_model_positions:
            model_position_symbol = model_position.symbol
            assert model_position_symbol in baskt_positions_dict
            assert model_position.direction == baskt_positions_dict[model_position_symbol].direction
            assert abs(model_position.target_weight - ((baskt_positions_dict[model_position_symbol].filled_avg_price * baskt_positions_dict[model_position_symbol].filled_quantity) / alpaca_filled_amount2)) <= MARGIN_ERROR * slippage_correction
        
        alpaca_filled_amount = self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["filled_amounts"][-1]
        assert abs(withdraw_amount - (alpaca_filled_amount - alpaca_filled_amount2)) / withdraw_amount <= MARGIN_ERROR

        self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["filled_amounts"].append(alpaca_filled_amount2)
        self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"].extend(wd_orders)

        return wd_response
    

    def test_withdraw_all(
        self,
        portfolio_owner_cognito_user_id: str,
        alpaca_account_id: str,
        cognito_user_id: str,
        portfolio_id: str,
    ):

        wd_response = self._queue_and_get_response(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
            queue_action=lambda: self.trade_execution_queuing_service.queue_portfolio_withdraw_all(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            portfolio_id=portfolio_id,
        )
        self.portfolio_allocation_history_size+=1

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
        assert len(self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]) + len(wd_orders) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in wd_orders + self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, order_id=order_id)
            assert order_id in rows2_dict_order_id
            assert rows2_dict_order_id[order_id]["symbol"] == alpaca_order.symbol
            assert float(rows2_dict_order_id[order_id]["filled_qty"]) == float(alpaca_order.filled_qty)
            assert float(rows2_dict_order_id[order_id]["filled_avg_price"]) == float(alpaca_order.filled_avg_price)

        orders_db_symbols_quantity = {}
        for row in rows2:
            symbol = row["symbol"]
            side = 1 if (str(row["side"])=="BUY") else -1
            filled_qty = float(row["filled_qty"]) 
            orders_db_symbols_quantity[symbol] = (abs(filled_qty)*side) + orders_db_symbols_quantity.get(symbol,0)
            if abs(orders_db_symbols_quantity[symbol]) <= FLOAT_ERROR:
                del orders_db_symbols_quantity[symbol]

        # match order_db and portfolio_allocation
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id,portfolio_id=portfolio_id)
        assert allocation is not None and len(allocation.position_history) == self.portfolio_allocation_history_size

        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        assert len(baskt_positions_dict) == 0
        allocation.total_cost_basis <= FLOAT_ERROR
        len(allocation.position_history) == 0

        return wd_response
    

    def test_buy(
        self,
        symbol: str,
        asset_id: str,
        deposit_amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
    ):
        dep_response = self._queue_and_get_response(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            portfolio_id=asset_id,
            queue_action=lambda: self.trade_execution_queuing_service.queue_stock_buy(
                symbol=symbol,
                asset_id=asset_id,
                amount=deposit_amount,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            ),
        )
        dep_orders = dep_response["orders"]

        if cognito_user_id not in self.baskt_account_portfolio_positions:
            self.baskt_account_portfolio_positions[cognito_user_id] = {}

        if asset_id not in self.baskt_account_portfolio_positions[cognito_user_id]:
            self.baskt_account_portfolio_positions[cognito_user_id][asset_id] = {
                "all_orders":[],
                "filled_amounts":[]
            }

        # Wait for orders to be filled
        sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            portfolio_id=asset_id,
        )

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(cognito_user_id=cognito_user_id, portfolio_id=asset_id)
        assert len(dep_orders) + len(self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"]) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in dep_orders + self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, order_id=order_id, cognito_user_id=cognito_user_id)
            assert order_id in rows2_dict_order_id
            assert rows2_dict_order_id[order_id]["symbol"] == alpaca_order.symbol
            assert float(rows2_dict_order_id[order_id]["filled_qty"]) == float(alpaca_order.filled_qty)
            assert float(rows2_dict_order_id[order_id]["filled_avg_price"]) == float(alpaca_order.filled_avg_price)

        orders_db_symbols_quantity = {}
        for row in rows2:
            symbol = row["symbol"]
            side = 1 if (str(row["side"])=="BUY") else -1
            filled_qty = float(row["filled_qty"])
            orders_db_symbols_quantity[symbol] = (abs(filled_qty) * side) + orders_db_symbols_quantity.get(symbol,0)
            if abs(orders_db_symbols_quantity[symbol]) <= FLOAT_ERROR:
                del orders_db_symbols_quantity[symbol]

        # match order_db and portfolio_allocation
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id,portfolio_id=asset_id)
        snapshot = allocation.position_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
        assert symbols_snapshot_sorted == baskt_symbols_sorted
        alpaca_filled_amount = 0.0
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in baskt_positions_dict
            assert abs(snapshot_position.filled_quantity - baskt_positions_dict[snapshot_position.symbol].filled_quantity) <= FLOAT_ERROR
            assert abs(snapshot_position.filled_avg_price - baskt_positions_dict[snapshot_position.symbol].filled_avg_price) <= FLOAT_ERROR
            assert snapshot_position.direction == baskt_positions_dict[snapshot_position.symbol].direction
            alpaca_filled_amount += (baskt_positions_dict[snapshot_position.symbol].filled_quantity * baskt_positions_dict[snapshot_position.symbol].filled_avg_price)
        assert abs(allocation.total_cost_basis - alpaca_filled_amount) / allocation.total_cost_basis <= MARGIN_ERROR

        # Validate this transaction's fills. Allocation cost basis can decrease
        # during a buy when the order is covering an existing short position.
        deposit_order_ids = {str(order.id) for order in dep_orders}
        net_deposit_filled_amount = sum(
            float(row["filled_qty"]) * float(row["filled_avg_price"])
            * (1 if str(row["side"]).upper() == "BUY" else -1)
            for row in rows2
            if row["order_id"] in deposit_order_ids
        )
        assert (
            abs(deposit_amount - net_deposit_filled_amount) / deposit_amount
            <= MARGIN_ERROR
        )

        self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"].extend(dep_orders)
        self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["filled_amounts"].append(alpaca_filled_amount)
        self.portfolio_allocation_history_size = len(allocation.position_history)

        return dep_response



    def test_sell(
        self,
        cognito_user_id: str,
        alpaca_account_id,
        symbol: str,
        asset_id: str,
        withdraw_amount: float,
        slippage_correction: int = 1
    ):
        # market_value = 0.0
        # if not self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(cognito_user_id=co)
        # portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id, portfolio_id=asset_id)
        # snapshot = portfolio_allocation.position_history[-1]
        # symbols = [position.symbol for position in snapshot.positions]
        # quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
        # for snapshot_position in snapshot.positions:
        #     price = quotes[snapshot_position.symbol]
        #     market_value += (price * snapshot_position.filled_quantity)

        wd_response = self._queue_and_get_response(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            portfolio_id=asset_id,
            queue_action=lambda: self.trade_execution_queuing_service.queue_stock_sell(
                symbol=symbol,
                asset_id=asset_id,
                amount=withdraw_amount,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        if cognito_user_id not in self.baskt_account_portfolio_positions:
            self.baskt_account_portfolio_positions[cognito_user_id] = {}

        if asset_id not in self.baskt_account_portfolio_positions[cognito_user_id]:
            self.baskt_account_portfolio_positions[cognito_user_id][asset_id] = {
                "all_orders":[],
                "filled_amounts":[]
            }
        # Wait for orders to be filled
        sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            portfolio_id=asset_id,
        )   
        self.portfolio_allocation_history_size+=1

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(cognito_user_id=cognito_user_id, portfolio_id=asset_id)

        assert len(self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"]) + len(wd_orders) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in wd_orders + self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, order_id=order_id)
            assert order_id in rows2_dict_order_id
            assert rows2_dict_order_id[order_id]["symbol"] == alpaca_order.symbol
            assert float(rows2_dict_order_id[order_id]["filled_qty"]) == float(alpaca_order.filled_qty)
            assert float(rows2_dict_order_id[order_id]["filled_avg_price"]) == float(alpaca_order.filled_avg_price)

        orders_db_symbols_quantity = {}
        for row in rows2:
            symbol = row["symbol"]
            side = 1 if (str(row["side"])=="BUY") else -1
            filled_qty = float(row["filled_qty"]) 
            orders_db_symbols_quantity[symbol] = (abs(filled_qty)*side) + orders_db_symbols_quantity.get(symbol,0)
            if abs(orders_db_symbols_quantity[symbol]) <= FLOAT_ERROR:
                del orders_db_symbols_quantity[symbol]

        # match order_db and portfolio_allocation
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id,portfolio_id=asset_id)
        assert allocation is not None and len(allocation.position_history) == self.portfolio_allocation_history_size
        snapshot = allocation.position_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
        assert symbols_snapshot_sorted == baskt_symbols_sorted
        alpaca_filled_amount2 = 0.0

        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in baskt_positions_dict
            assert abs(snapshot_position.filled_quantity - baskt_positions_dict[snapshot_position.symbol].filled_quantity) <= FLOAT_ERROR
            assert abs(snapshot_position.filled_avg_price - baskt_positions_dict[snapshot_position.symbol].filled_avg_price) <= FLOAT_ERROR
            assert snapshot_position.direction == baskt_positions_dict[snapshot_position.symbol].direction
            alpaca_filled_amount2 += (baskt_positions_dict[snapshot_position.symbol].filled_quantity * baskt_positions_dict[snapshot_position.symbol].filled_avg_price)
        assert abs(allocation.total_cost_basis - alpaca_filled_amount2) <= FLOAT_ERROR

        withdraw_order_ids = {str(order.id) for order in wd_orders}
        net_withdraw_filled_amount = sum(
            float(row["filled_qty"]) * float(row["filled_avg_price"])
            * (1 if str(row["side"]).upper() == "SELL" else -1)
            for row in rows2
            if row["order_id"] in withdraw_order_ids
        )
        assert (
            abs(withdraw_amount - net_withdraw_filled_amount) / withdraw_amount
            <= MARGIN_ERROR
        )

        self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["filled_amounts"].append(alpaca_filled_amount2)
        self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"].extend(wd_orders)

        return wd_response
    

    def test_close(
        self,
        symbol: str,
        asset_id: str,
        alpaca_account_id: str,
        cognito_user_id: str,
    ):
        wd_response = self._queue_and_get_response(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            portfolio_id=asset_id,
            queue_action=lambda: self.trade_execution_queuing_service.queue_stock_close(
                symbol=symbol,
                asset_id=asset_id,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            portfolio_id=asset_id,
        )
        self.portfolio_allocation_history_size+=1

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(cognito_user_id=cognito_user_id, portfolio_id=asset_id)
        assert len(self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"]) + len(wd_orders) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in wd_orders + self.baskt_account_portfolio_positions[cognito_user_id][asset_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, order_id=order_id)
            assert order_id in rows2_dict_order_id
            assert rows2_dict_order_id[order_id]["symbol"] == alpaca_order.symbol
            assert float(rows2_dict_order_id[order_id]["filled_qty"]) == float(alpaca_order.filled_qty)
            assert float(rows2_dict_order_id[order_id]["filled_avg_price"]) == float(alpaca_order.filled_avg_price)

        orders_db_symbols_quantity = {}
        for row in rows2:
            symbol = row["symbol"]
            side = 1 if (str(row["side"])=="BUY") else -1
            filled_qty = float(row["filled_qty"]) 
            orders_db_symbols_quantity[symbol] = (abs(filled_qty)*side) + orders_db_symbols_quantity.get(symbol,0)
            if abs(orders_db_symbols_quantity[symbol]) <= FLOAT_ERROR:
                del orders_db_symbols_quantity[symbol]

        # match order_db and portfolio_allocation
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id,portfolio_id=asset_id)
        assert allocation is not None and len(allocation.position_history) == self.portfolio_allocation_history_size
        snapshot = allocation.position_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR

        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        assert len(baskt_positions_dict) == 0

        return wd_response
    
    def test_stock_clean_up(
        self,
        traded_accounts: List[List[str]], # [[cognito_user_id, alpaca_account_id, asset_id],...,]
        transaction_id_order_id_dict: Dict[str, List[Order]] # {transaction_id -> [order,...]}
    ):
        for cognito_user_id, alpaca_account_id, asset_id in traded_accounts:
            # delete any unfilled orders
            try:
                open_orders = self.alpaca_broker_client.client.get_orders_for_account(
                    account_id=alpaca_account_id,
                    filter=GetOrdersRequest(status=QueryOrderStatus.OPEN),
                )
            except Exception:
                open_orders = []

            for order in open_orders:
                try:
                    self.alpaca_broker_client.client.cancel_order_for_account_by_id(
                        account_id=alpaca_account_id,
                        order_id=str(order.id),
                    )
                except Exception:
                    continue

            try:
                self.alpaca_broker_client.execute_close_all_position(
                    alpaca_account_id=alpaca_account_id,
                    cognito_user_id=cognito_user_id
                )
            except Exception as e:
                pass

            try:
                self.portfolio_allocation_repository.portfolio_allocation_table_client.delete_item(
                    key={"cognito_user_id": cognito_user_id,"portfolio_id": asset_id}
                )
            except Exception as e:
                pass

        self._delete_order_rows_for_traded_accounts(traded_accounts)

        order_keys = {
            (transaction_id, str(order.id))
            for transaction_id, orders in transaction_id_order_id_dict.items()
            for order in orders
        }
        for transaction_id, order_id in order_keys:
            try:
                self.order_repository.order_table_client.delete_item(
                    key={"transaction_id": transaction_id, "order_id": order_id}
                )
            except Exception as e:
                continue

        for cognito_user_id, _, asset_id in traded_accounts:
            user_allocations = self.baskt_account_portfolio_positions.get(
                cognito_user_id,
                {},
            )
            user_allocations.pop(asset_id, None)
            if not user_allocations:
                self.baskt_account_portfolio_positions.pop(cognito_user_id, None)

        self.portfolio_allocation_history_size = 0


    def _delete_order_rows_for_traded_accounts(
        self,
        traded_accounts: List[List[str]],
    ) -> None:
        """Delete order rows even when a test timed out before returning orders."""
        for cognito_user_id, _, portfolio_id in traded_accounts:
            try:
                rows = self.order_repository.get_orders_by_portfolio(
                    cognito_user_id=cognito_user_id,
                    portfolio_id=portfolio_id,
                )
            except Exception:
                rows = []

            for row in rows:
                try:
                    self.order_repository.order_table_client.delete_item(
                        key={
                            "transaction_id": str(row["transaction_id"]),
                            "order_id": str(row["order_id"]),
                        }
                    )
                except Exception:
                    continue


    def test_clean_up(
        self,
        traded_accounts: List[List[str]], # [[cognito_user_id, alpaca_account_id, portfolio_id],...,]
        portfolio_owner_model_portfolios: List[List[str]], # [[cognito_user_id, portfolio_id],...,]
        transaction_id_order_id_dict: Dict[str, List[Order]] # {transaction_id -> [order,...]}
    ):
        for cognito_user_id, alpaca_account_id, portfolio_id in traded_accounts:
            # delete any unfilled orders
            try:
                open_orders = self.alpaca_broker_client.client.get_orders_for_account(
                    account_id=alpaca_account_id,
                    filter=GetOrdersRequest(status=QueryOrderStatus.OPEN),
                )
            except Exception:
                open_orders = []

            for order in open_orders:
                try:
                    self.alpaca_broker_client.client.cancel_order_for_account_by_id(
                        account_id=alpaca_account_id,
                        order_id=str(order.id),
                    )
                except Exception:
                    continue

            try:
                self.alpaca_broker_client.execute_close_all_position(
                    alpaca_account_id=alpaca_account_id,
                    cognito_user_id=cognito_user_id
                )
            except Exception as e:
                pass

            try:
                self.model_portfolio_follower_repository.delete_model_portfolio_follower(
                    cognito_user_id=cognito_user_id,
                    portfolio_id=portfolio_id
                )
            except Exception as e:
                pass

            try:
                self.portfolio_allocation_repository.portfolio_allocation_table_client.delete_item(
                    key={"cognito_user_id": cognito_user_id,"portfolio_id": portfolio_id}
                )
            except Exception as e:
                pass

        for _, portfolio_id in portfolio_owner_model_portfolios:
            try:
                self.model_portfolio_repository.dynamodb.delete_item(
                    key={"portfolio_id": portfolio_id}
                )
            except Exception as e:
                continue

        self._delete_order_rows_for_traded_accounts(traded_accounts)

        for transaction_id, orders in transaction_id_order_id_dict.items():
            for order in orders:
                try:
                    self.order_repository.order_table_client.delete_item(
                        key={"transaction_id": transaction_id, "order_id": str(order.id)}
                    )
                except Exception as e:
                    continue

        for cognito_user_id, _, portfolio_id in traded_accounts:
            user_allocations = self.baskt_account_portfolio_positions.get(
                cognito_user_id,
                {},
            )
            user_allocations.pop(portfolio_id, None)
            if not user_allocations:
                self.baskt_account_portfolio_positions.pop(cognito_user_id, None)

        self.portfolio_allocation_history_size = 0



@pytest.fixture(scope="session")
def test_engine(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    sqs_client: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    order_repository: OrderRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
) -> TestEngine:
    return TestEngine(
        account_lifecycle_service=account_lifecycle_service,
        trade_execution_service=trade_execution_service,
        trade_execution_queuing_service=trade_execution_queuing_service,
        sqs_client=sqs_client,
        model_portfolio_repository=model_portfolio_repository,
        order_repository=order_repository,
        alpaca_broker_client=alpaca_broker_client,
        portfolio_allocation_repository=portfolio_allocation_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
    )

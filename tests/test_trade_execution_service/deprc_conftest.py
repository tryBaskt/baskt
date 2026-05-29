import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import uuid
from math import ceil, floor
from typing import Any, Dict, List
from unittest.mock import MagicMock
import pytest
from dotenv import load_dotenv
from alpaca.trading.models import Order
from alpaca.trading.enums import OrderClass, OrderSide, OrderStatus, OrderType, TimeInForce

load_dotenv()
os.environ["ENV"] = "dev"

EPS = 1e-7
MOCK_MARGIN = 0.0007
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.clients.dynamodb_client import DynamoDBClient
from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from backend.repository.model_portfolio_repository import ModelPortfolioRepository
from backend.repository.portfolio_allocation_repository import PortfolioAllocationRepository
from backend.repository.order_repository import OrderRepository
from backend.repository.user_trade_lock_repository import UserTradeLockRepository
from backend.repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from backend.services.trade_execution_service import TradeExecutionService
from backend.clients.alpaca_client import AlpacaClient
from backend.domain.baskt import BasktPosition

get_settings.cache_clear()
get_settings.cache_clear()

@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    app_deps.get_alpaca_broker_client.cache_clear()
    return app_deps.get_alpaca_broker_client()

@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

@pytest.fixture(scope="session")
def user_account_repository() -> UserAccountRepository:
    app_deps.get_user_account_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()
    return app_deps.get_user_account_repository(
        user_account_dynamodb_client=user_account_dynamodb_client
    )

@pytest.fixture(scope="session")
def account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    user_account_repository: UserAccountRepository,
) -> AccountLifecycleService:
    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        user_account_repository=user_account_repository,
    )

aws_region = os.environ.get("AWS_DEFAULT_REGION")

model_portfolio_table_suffix = os.environ.get("MODEL_PORTFOLIO_DYNAMODB", "_model_portfolio_dynamodb")
model_portfolio_table_name = f"test{model_portfolio_table_suffix}"

portfolio_allocation_table_suffix = os.environ.get("PORTFOLIO_ALLOCATION_DYNAMODB", "_portfolio_allocation_dynamodb")
portfolio_allocation_table_name = f"test{portfolio_allocation_table_suffix}"

order_table_suffix = os.environ.get("ORDER_DYNAMODB", "_order_dynamodb")
order_table_name = f"test{order_table_suffix}"

model_portfolio_follower_table_suffix = os.environ.get("MODEL_PORTFOLIO_FOLLOWER_DYNAMODB", "_model_portfolio_follower_dynamodb")
model_portfolio_follower_table_name = f"test{model_portfolio_follower_table_suffix}"

user_trade_lock_dynamodb_suffix = os.environ.get("USER_TRADE_LOCK_DYNAMODB", "_user_trade_lock_dynamodb")
user_trade_lock_dynamodb_name = f"test{user_trade_lock_dynamodb_suffix}"

model_portfolio_update_lock_dynamodb_suffix = os.environ.get("MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB", "_model_portfolio_update_lock_dynamodb")
model_portfolio_update_Lock_dynamodb_name = f"test{model_portfolio_update_lock_dynamodb_suffix}"

alpaca_api_key = os.environ.get("TEST_ALPACA_API_KEY")
alpaca_api_secret = os.environ.get("TEST_ALPACA_API_SECRET")

def pytest_addoption(parser):
    parser.addoption(
        "--mock_alpaca",
        action="store_true",
        default=False,
        help="Use in-memory mock Alpaca client for integration tests",
    )

def _build_mock_alpaca_client(prices: Dict[str, float]) -> AlpacaClient:
    mock = MagicMock(spec=AlpacaClient)

    state: Dict[str, Dict[str,Order | BasktPosition | float]] = {
        "positions": {},
        "orders": {},
        "prices": prices,
    }

    def _make_order(symbol: str, order_side: OrderSide, qty: float):
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
        state["orders"][order_id] = order
        return order
    
    def _apply_filled_order_to_positions(order: Order) -> None:
        """Apply one filled order to in-memory position state and allocation amount."""
        order_symbol = order.symbol
        order_direction = 1 if order.side.name == "BUY" else -1
        order_filled_avg_price = order.filled_avg_price
        order_filled_quantity = order.filled_qty

        if order_symbol not in state["positions"]:
            state["positions"][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=order_filled_quantity,
                filled_avg_price=order_filled_avg_price,
                direction=order_direction
            )
            return 
        
        pos = state["positions"][order_symbol]
        pos_avg = pos.filled_avg_price
        pos_qty = pos.filled_quantity
        pos_dir = pos.direction

        pos_signed = pos_dir * pos_qty
        ord_signed = order_direction * order_filled_quantity

        # Same-side increase: weighted-average entry and add full notional.
        if pos_signed * ord_signed > 0:
            new_qty = pos_qty + order_filled_quantity
            new_avg = ((pos_qty * pos_avg) + (order_filled_quantity * order_filled_avg_price)) / new_qty
            state["positions"][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=new_qty,
                filled_avg_price=new_avg,
                direction=pos_dir
            )
            return 
        
        remaining = pos_qty - order_filled_quantity

        # Fully closed.
        if abs(remaining) <= EPS:
            del state["positions"][order_symbol]
            return 

        # Partial close, same direction remains.
        if remaining > 0:
            state["positions"][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=remaining,
                filled_avg_price=pos_avg,
                direction=pos_dir
            )
            return 

        # Direction flip: excess opens new position at order avg.
        flipped_qty = abs(remaining)
        state["positions"][order_symbol] = BasktPosition(
            symbol=order_symbol,
            filled_avg_price=order_filled_avg_price,
            filled_quantity=flipped_qty,
            direction=order_direction
        )
        return

    def _apply_fill(order_id: str) -> Order:
        order = state["orders"][order_id]
        mid_price = float(state["prices"][order.symbol])
        bid_price = float(floor(mid_price * (1 - MOCK_MARGIN) * 100) / 100)
        ask_price = float(ceil(mid_price * (1 + MOCK_MARGIN) * 100) / 100)
        fill_price = ask_price if order.side == OrderSide.BUY else bid_price

        order.filled_at = datetime.now(timezone.utc)
        order.filled_qty = order.qty
        order.filled_avg_price = fill_price
        order.status = OrderStatus.FILLED
        order.notional = str(order.qty * fill_price)

        state["orders"][order_id] = order

        _apply_filled_order_to_positions(order=order)
        return order

    def get_latest_price(symbols: List[str]):
        return {symbol: float(state["prices"][symbol]) for symbol in symbols}

    def execute_quantity_buy(symbol: str, quantity: float):
        return _make_order(symbol=symbol, order_side=OrderSide.BUY, qty=float(quantity))

    def execute_quantity_sell(symbol: str, quantity: float):
        return _make_order(symbol=symbol, order_side=OrderSide.SELL, qty=float(quantity))

    def execute_quantity_fractional_sell(symbol: str, quantity: float):
        # Match real Alpaca client wrapper behavior:
        # sell ceil(quantity), then buy back the excess to achieve exact net sell = quantity.
        sell_order = execute_quantity_sell(symbol=symbol, quantity=ceil(quantity))
        if ceil(quantity) - quantity <= 0:
            return sell_order, None
        buy_order = execute_quantity_buy(symbol=symbol, quantity=ceil(quantity) - quantity)
        return sell_order, buy_order

    def get_baskt_positions_dict() -> Dict[str, BasktPosition]:
        return state["positions"]

    def get_baskt_positions() -> List[BasktPosition]:
        return state["positions"].values()

    def get_order_by_id(order_id: str):
        order = state["orders"][order_id]
        if order.status != OrderStatus.FILLED:
            _apply_fill(order_id=order_id)
        return order

    def close_all_positions(
        cancel_open_orders: bool = True,
        wait: bool = True,
        timeout_sec: int = 20,
        poll_interval_sec: float = 2.0,
    ):
        state["positions"].clear()
        return True

    mock.get_latest_price.side_effect = get_latest_price
    mock.execute_quantity_buy.side_effect = execute_quantity_buy
    mock.execute_quantity_sell.side_effect = execute_quantity_sell
    mock.execute_quantity_fractional_sell.side_effect = execute_quantity_fractional_sell
    mock.get_baskt_positions_dict.side_effect = get_baskt_positions_dict
    mock.get_baskt_positions.side_effect = get_baskt_positions
    mock.get_order_by_id.side_effect = get_order_by_id
    mock.close_all_positions.side_effect = close_all_positions

    return mock

@pytest.fixture(scope="session")
def alpaca_client(request) -> AlpacaClient:
    if request.config.getoption("--mock_alpaca"):
        return _build_mock_alpaca_client(
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
            }
        )

    if not alpaca_api_key or not alpaca_api_secret:
        pytest.skip("Missing ALPACA_API_KEY/ALPACA_API_SECRET; skipping Alpaca-backed tests")
    client = AlpacaClient(alpaca_api_key=alpaca_api_key, alpaca_api_secret=alpaca_api_secret)
    # Probe a simple call to validate creds
    try:
        client.get_latest_price(["AAPL"])  # should return a dict
    except Exception as e:
        pytest.skip(f"Alpaca not accessible: {e}")
    return client


def _dynamodb_client_from_deps(get_client_fn, table_name: str) -> DynamoDBClient:
    if not aws_region or not table_name:
        pytest.skip(
            f"Missing AWS env: {aws_region} or {table_name} not set; skipping AWS I/O test"
        )

    client = get_client_fn()
    try:
        client.table.load()
    except Exception as e:
        pytest.skip(f"DynamoDB table '{table_name}' not accessible: {e}")
    return client


@pytest.fixture(scope="session")
def model_portfolio_dynamodb_client() -> DynamoDBClient:
    return _dynamodb_client_from_deps(
        app_deps.get_model_portfolio_dynamodb_client,
        model_portfolio_table_name,
    )


@pytest.fixture(scope="session")
def portfolio_allocation_dynamodb_client() -> DynamoDBClient:
    return _dynamodb_client_from_deps(
        app_deps.get_portfolio_allocation_dynamodb_client,
        portfolio_allocation_table_name,
    )


@pytest.fixture(scope="session")
def order_dynamodb_client() -> DynamoDBClient:
    return _dynamodb_client_from_deps(
        app_deps.get_order_dynamodb_client,
        order_table_name,
    )


@pytest.fixture(scope="session")
def model_portfolio_follower_dynamodb_client() -> DynamoDBClient:
    return _dynamodb_client_from_deps(
        app_deps.get_model_portfolio_follower_dynamodb_client,
        model_portfolio_follower_table_name,
    )


@pytest.fixture(scope="session")
def user_trade_lock_dynamodb_client() -> DynamoDBClient:
    return _dynamodb_client_from_deps(
        app_deps.get_user_trade_lock_dynamodb_client,
        user_trade_lock_dynamodb_name,
    )

@pytest.fixture(scope="session")
def model_portfolio_update_lock_dynamodb_client() -> DynamoDBClient:
    return _dynamodb_client_from_deps(
        app_deps.get_model_portfolio_update_lock_dynamodb_client,
        model_portfolio_update_Lock_dynamodb_name,
    )


@pytest.fixture(scope="session")
def order_repository(
    alpaca_client: AlpacaClient,
    order_dynamodb_client: DynamoDBClient,
) -> OrderRepository:
    return app_deps.get_order_repository(
        alpaca_client=alpaca_client,
        order_dynamodb_client=order_dynamodb_client,
    )


@pytest.fixture(scope="session")
def portfolio_allocation_repository(
    alpaca_client: AlpacaClient,
    portfolio_allocation_dynamodb_client: DynamoDBClient,
) -> PortfolioAllocationRepository:
    return app_deps.get_portfolio_allocation_repository(
        alpaca_client=alpaca_client,
        portfolio_allocation_dynamodb_client=portfolio_allocation_dynamodb_client,
    )


@pytest.fixture(scope="session")
def model_portfolio_follower_repository(
    model_portfolio_follower_dynamodb_client: DynamoDBClient,
) -> ModelPortfolioFollowerRepository:
    return app_deps.get_model_portfolio_follower_repository(
        model_protfolio_follower_dynamodb_client=model_portfolio_follower_dynamodb_client,
    )


@pytest.fixture(scope="session")
def user_trade_lock_repository(
    user_trade_lock_dynamodb_client: DynamoDBClient,
) -> UserTradeLockRepository:
    return app_deps.get_user_trade_lock_repository(
        user_trade_lock_dynamodb_client=user_trade_lock_dynamodb_client,
    )


@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository(
    model_portfolio_update_lock_dynamodb_client: DynamoDBClient
) -> ModelPortfolioUpdateLockRepository:
    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=model_portfolio_update_lock_dynamodb_client
    )


@pytest.fixture(scope="session")
def model_portfolio_repository(
    model_portfolio_dynamodb_client: DynamoDBClient,
    alpaca_client: AlpacaClient,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository
) -> ModelPortfolioRepository:
    return app_deps.get_model_portfolio_repository(
        dynamodb=model_portfolio_dynamodb_client,
        alpaca_client=alpaca_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository
    )


@pytest.fixture(scope="session")
def trade_execution_service(
    model_portfolio_repository: ModelPortfolioRepository,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    alpaca_client: AlpacaClient,
    order_repository: OrderRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    user_trade_lock_repository: UserTradeLockRepository

) -> TradeExecutionService:
    return app_deps.get_trade_execution_service(
        alpaca_client=alpaca_client,
        model_portfolio_repository=model_portfolio_repository,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
    )

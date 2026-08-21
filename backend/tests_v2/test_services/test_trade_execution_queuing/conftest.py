import os
import pytest
from typing import List, Dict, Any
from core import deps as app_deps
from core.config import get_settings
from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from backend.tests_v2.mock_alpaca.trading import (
    MockSQSClient,
    MockTradeExecutionLambda,
    build_mock_alpaca_broker_client,
)
from services.account_lifecycle_service import AccountLifecycleService
from repository.model_portfolio_access_repository import ModelPortfolioAccessRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.baskt_account_repository import BasktAccountRepository
from repository.allocation_repository import AllocationRepository
from repository.order_repository import OrderRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from services.trade_execution_service import TradeExecutionService
from services.trade_execution_queuing_service import TradeExecutionQueuingService
from time import monotonic, sleep
from datetime import datetime, timezone, timedelta
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from collections import defaultdict
from alpaca.broker.models import Order
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest
from domain.baskt_domain import BasktPosition
MARGIN_ERROR = 0.01
FLOAT_ERROR = 1e-6

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def pause_between_test_cases():
    yield
    sleep(5)


def _test_settings():
    return get_settings()


class TradeExecutionTestAccountIds:
    @property
    def env(self) -> str:
        return _test_settings().env

    @property
    def alpaca_env(self) -> str:
        return _test_settings().alpaca_env

    def _get(self, name: str) -> str:
        env_prefix = self.env.upper()
        test_user_variables = {
            "FUNDED_50000_ALPACA_ACCOUNT_ID": (
                f"{env_prefix}_TEST_USER_1_ALPACA_ACCOUNT_ID"
            ),
            "FUNDED_50000_COGNITO_USER_ID": (
                f"{env_prefix}_TEST_USER_1_COGNITO_USER_ID"
            ),
            "PORTFOLIO_OWNER_ALPACA_ACCOUNT_ID": (
                f"{env_prefix}_TEST_USER_2_ALPACA_ACCOUNT_ID"
            ),
            "PORTFOLIO_OWNER_COGNITO_USER_ID": (
                f"{env_prefix}_TEST_USER_2_COGNITO_USER_ID"
            ),
            "FUNDED_1000_ALPACA_ACCOUNT_ID": (
                f"{env_prefix}_TEST_USER_2_ALPACA_ACCOUNT_ID"
            ),
            "FUNDED_1000_COGNITO_USER_ID": (
                f"{env_prefix}_TEST_USER_2_COGNITO_USER_ID"
            ),
        }
        variable_name = test_user_variables[name]
        value = os.getenv(variable_name, "").strip()
        if not value:
            raise RuntimeError(
                f"{variable_name} is required for trade execution queue tests."
            )
        return value

    @property
    def funded_50000_alpaca_account_id(self) -> str:
        return self._get("FUNDED_50000_ALPACA_ACCOUNT_ID")

    @property
    def funded_50000_cognito_user_id(self) -> str:
        return self._get("FUNDED_50000_COGNITO_USER_ID")

    @property
    def portfolio_owner_alpaca_account_id(self) -> str:
        return self._get("PORTFOLIO_OWNER_ALPACA_ACCOUNT_ID")

    @property
    def portfolio_owner_cognito_user_id(self) -> str:
        return self._get("PORTFOLIO_OWNER_COGNITO_USER_ID")

    @property
    def funded_1000_alpaca_account_id(self) -> str:
        return self._get("FUNDED_1000_ALPACA_ACCOUNT_ID")

    @property
    def funded_1000_cognito_user_id(self) -> str:
        return self._get("FUNDED_1000_COGNITO_USER_ID")

#######################################
############### CLIENTS ###############
#######################################


@pytest.fixture(scope="session")
def sqs_client(request) -> Any:
    if request.config.getoption("--mock_alpaca"):
        return MockSQSClient()
    return app_deps.get_sqs_client_cached()


@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

@pytest.fixture(scope="session")
def alpaca_broker_client(request) -> AlpacaBrokerClient:
    if request.config.getoption("--mock_alpaca"):
        return build_mock_alpaca_broker_client(
            real_client=app_deps.get_alpaca_broker_client(),
            prices={
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
            },
            funded_1000_alpaca_account_id=(
                TradeExecutionTestAccountIds().funded_1000_alpaca_account_id
            ),
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
def model_portfolio_access_repository(
    cognito_client: CognitoClient,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> ModelPortfolioAccessRepository:
    app_deps.get_model_portfolio_access_dynamodb_client.cache_clear()
    model_portfolio_access_dynamodb_client = app_deps.get_model_portfolio_access_dynamodb_client()
    
    return app_deps.get_model_portfolio_access_repository(
        model_portfolio_access_dynamodb_client=model_portfolio_access_dynamodb_client,
        cognito_client=cognito_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
    )


@pytest.fixture(scope="session")
def model_portfolio_repository(
    alpaca_broker_client: AlpacaBrokerClient,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
) -> ModelPortfolioRepository:

    app_deps.get_model_portfolio_dynamodb_client.cache_clear()
    model_portfolio_dynamodb_client = app_deps.get_model_portfolio_dynamodb_client()

    return app_deps.get_model_portfolio_repository(
        dynamodb=model_portfolio_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
    )


@pytest.fixture(scope="session")
def allocation_repository(alpaca_broker_client: AlpacaBrokerClient) -> AllocationRepository:

    app_deps.get_allocation_dynamodb_client.cache_clear()
    allocation_dynamodb_client = app_deps.get_allocation_dynamodb_client()
    return app_deps.get_allocation_repository(
        allocation_dynamodb_client=allocation_dynamodb_client,
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


@pytest.fixture(scope="session")
def baskt_account_repository() -> BasktAccountRepository:

    app_deps.get_baskt_account_dynamodb_client.cache_clear()
    baskt_account_dynamodb_client = app_deps.get_baskt_account_dynamodb_client()

    return app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=baskt_account_dynamodb_client
    )

##################################################
#################### SERVICES ####################
##################################################
    
@pytest.fixture(scope="session")
def account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    baskt_account_repository: BasktAccountRepository,
) -> AccountLifecycleService:
    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        baskt_account_repository=baskt_account_repository,
    )

@pytest.fixture(scope="session")
def trade_execution_service(
    model_portfolio_repository: ModelPortfolioRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
) -> TradeExecutionService:

    return app_deps.get_trade_execution_service(
        model_portfolio_repository=model_portfolio_repository,
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
    )

@pytest.fixture(scope="session")
def trade_execution_queuing_service(
    sqs_client: Any,
    trade_execution_service: TradeExecutionService,
    model_portfolio_repository: ModelPortfolioRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    allocation_repository: AllocationRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
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
        allocation_repository=allocation_repository,
        alpaca_broker_client=alpaca_broker_client,
        user_trade_lock_repository=user_trade_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
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
        allocation_repository: AllocationRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
        model_portfolio_access_repository: ModelPortfolioAccessRepository,
    ):
        self.account_lifecycle_service = account_lifecycle_service
        self.trade_execution_service = trade_execution_service
        self.trade_execution_queuing_service = trade_execution_queuing_service
        self.sqs_client = sqs_client
        self.model_portfolio_repository = model_portfolio_repository
        self.order_repository = order_repository
        self.alpaca_broker_client = alpaca_broker_client
        self.allocation_repository = allocation_repository
        self.model_portfolio_follower_repository = model_portfolio_follower_repository
        self.model_portfolio_access_repository = model_portfolio_access_repository
        self.accounts = TradeExecutionTestAccountIds()
        self.baskt_account_portfolio_positions = {}
        self.model_portfolio_update_times = defaultdict(list) # also used to calculate model portfolio position history length
        self.portfolio_allocation_history_size = 0

    @property
    def env(self) -> str:
        return self.accounts.env

    @property
    def alpaca_env(self) -> str:
        return self.accounts.alpaca_env

    @property
    def funded_50000_alpaca_account_id(self) -> str:
        return self.accounts.funded_50000_alpaca_account_id

    @property
    def funded_50000_cognito_user_id(self) -> str:
        return self.accounts.funded_50000_cognito_user_id

    @property
    def portfolio_owner_alpaca_account_id(self) -> str:
        return self.accounts.portfolio_owner_alpaca_account_id

    @property
    def portfolio_owner_cognito_user_id(self) -> str:
        return self.accounts.portfolio_owner_cognito_user_id

    @property
    def funded_1000_alpaca_account_id(self) -> str:
        return self.accounts.funded_1000_alpaca_account_id

    @property
    def funded_1000_cognito_user_id(self) -> str:
        return self.accounts.funded_1000_cognito_user_id

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
        if self.allocation_repository.is_exists_allocation_for_user(
            cognito_user_id=cognito_user_id,
            allocation_id=portfolio_id,
        ):
            allocation = self.allocation_repository.get_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=portfolio_id,
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
            allocation = self.allocation_repository.get_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=portfolio_id,
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
            allocation = self.allocation_repository.get_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=portfolio_id,
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
            visibility="PUBLIC",
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
                amount=deposit_amount,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            ),
        )
        dep_orders = dep_response["orders"]
        transaction_id = dep_response["transaction_id"]

        if cognito_user_id not in self.baskt_account_portfolio_positions:
            self.baskt_account_portfolio_positions[cognito_user_id] = {}

        if portfolio_id not in self.baskt_account_portfolio_positions[cognito_user_id]:
            self.baskt_account_portfolio_positions[cognito_user_id][portfolio_id] = {
                "all_orders":[],
                "filled_amounts":[]
            }

        # Realize filled orders
        while True:
            all_orders_fully_filled = True
            num_newly_filled_orders = self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                allocation_id=portfolio_id,
            )
            if num_newly_filled_orders > 0:
                self.portfolio_allocation_history_size+=1
            
            baskt_orders_dict = self.order_repository.get_orders_by_allocation(allocation_id=portfolio_id, cognito_user_id=cognito_user_id)
            for baskt_order_dict in baskt_orders_dict:
                if baskt_order_dict["status"] != "FILLED":
                    all_orders_fully_filled = False

            if all_orders_fully_filled:
                break

            sleep(0.25)

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_allocation(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)
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
        allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id,allocation_id=portfolio_id)
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

        # Validate user is in model portfolio's followers
        model_portfolio_followers = self.model_portfolio_follower_repository.get_model_portfolio_followers(portfolio_id=portfolio_id)
        assert {"alpaca_account_id": alpaca_account_id, "cognito_user_id": cognito_user_id} in model_portfolio_followers
        if cognito_user_id != portfolio_owner_cognito_user_id:
            access_record = self.model_portfolio_access_repository.get_access_record(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=cognito_user_id,
            )
            assert access_record is not None

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
            cognito_user_id = follower_alpaca_account_id_cognito_user_id["cognito_user_id"]
            alpaca_account_id = follower_alpaca_account_id_cognito_user_id["alpaca_account_id"]
            ud_orders = ud_orders_dict[cognito_user_id]["orders"]
            transaction_id = ud_orders_dict[cognito_user_id]["transaction_id"]
            previous_allocation = self.allocation_repository.get_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=portfolio_id,
            )
            previous_position_history_size = (
                0
                if previous_allocation is None
                else len(previous_allocation.position_history)
            )

            while True:
                all_orders_fully_filled = True
                num_newly_filled_orders = self.trade_execution_service.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    allocation_id=portfolio_id,
                )
                if num_newly_filled_orders > 0:
                    self.portfolio_allocation_history_size+=1

                baskt_orders_dict = self.order_repository.get_orders_by_allocation(allocation_id=portfolio_id, cognito_user_id=cognito_user_id)
                for baskt_order_dict in baskt_orders_dict:
                    if baskt_order_dict["status"] != "FILLED":
                        all_orders_fully_filled = False
    
                if all_orders_fully_filled:
                    break

                sleep(0.25)

            # match alpaca orders and order_db
            rows2 = self.order_repository.get_orders_by_allocation(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)
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
            allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id,allocation_id=portfolio_id)
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
            # self.portfolio_allocation_history_size = len(allocation.position_history)

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
            visibility="PUBLIC",
            update_time=update_time
        )
        if not updated or new_snapshot_id is None:
            return {}
        followers = self.model_portfolio_follower_repository.get_model_portfolio_followers(
            portfolio_id=portfolio_id
        )
        previous_transaction_ids = {}
        for follower in followers:
            allocation = self.allocation_repository.get_allocation(
                cognito_user_id=follower["cognito_user_id"],
                allocation_id=portfolio_id,
            )
            previous_transaction_ids[follower["cognito_user_id"]] = {
                transaction.transaction_id
                for transaction in allocation.transaction_history
            }

        message_ids = self.trade_execution_queuing_service.queue_portfolio_update(
            portfolio_id=portfolio_id,
            portfolio_snapshot_id=new_snapshot_id,
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
        portfolio_allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)
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
                amount=withdraw_amount,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        transaction_id = wd_response["transaction_id"]

        # Realize filled orders
        while True: 
            all_orders_fully_filled = True
            num_newly_filled_orders = self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                allocation_id=portfolio_id,
            )
            if num_newly_filled_orders > 0:
                self.portfolio_allocation_history_size+=1
            
            baskt_orders_dict = self.order_repository.get_orders_by_allocation(allocation_id=portfolio_id, cognito_user_id=cognito_user_id)
            for baskt_order_dict in baskt_orders_dict:
                if baskt_order_dict["status"] != "FILLED":
                    all_orders_fully_filled = False

            if all_orders_fully_filled:
                break

            sleep(0.25)

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_allocation(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)

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
        allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id,allocation_id=portfolio_id)
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
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        transaction_id = wd_response["transaction_id"]

        # Realize filled orders
        while True:
            all_orders_fully_filled = True
            num_newly_filled_orders = self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                allocation_id=portfolio_id,
            )
            if num_newly_filled_orders > 0:
                self.portfolio_allocation_history_size+=1
            
            baskt_orders_dict = self.order_repository.get_orders_by_allocation(allocation_id=portfolio_id, cognito_user_id=cognito_user_id)
            for baskt_order_dict in baskt_orders_dict:
                if baskt_order_dict["status"] != "FILLED":
                    all_orders_fully_filled = False

            if all_orders_fully_filled:
                break

            sleep(0.25)

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_allocation(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)
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
        allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id,allocation_id=portfolio_id)
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
                asset_id=asset_id,
                amount=deposit_amount,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
            ),
        )
        dep_orders = dep_response["orders"]
        transaction_id = dep_response["transaction_id"]

        if cognito_user_id not in self.baskt_account_portfolio_positions:
            self.baskt_account_portfolio_positions[cognito_user_id] = {}

        if asset_id not in self.baskt_account_portfolio_positions[cognito_user_id]:
            self.baskt_account_portfolio_positions[cognito_user_id][asset_id] = {
                "all_orders":[],
                "filled_amounts":[]
            }

        # Realize filled orders
        while True:
            all_orders_fully_filled = True
            num_newly_filled_orders = self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                allocation_id=asset_id,
            )
            if num_newly_filled_orders > 0:
                self.portfolio_allocation_history_size+=1
            
            baskt_orders_dict = self.order_repository.get_orders_by_allocation(allocation_id=asset_id, cognito_user_id=cognito_user_id)
            for baskt_order_dict in baskt_orders_dict:
                if baskt_order_dict["status"] != "FILLED":
                    all_orders_fully_filled = False

            if all_orders_fully_filled:
                break
            sleep(0.25)

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_allocation(cognito_user_id=cognito_user_id, allocation_id=asset_id)
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
        allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id,allocation_id=asset_id)
        snapshot = allocation.position_history[-1]
        snapshot_positions = [] if snapshot.position is None else [snapshot.position]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot_positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot_positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
        assert symbols_snapshot_sorted == baskt_symbols_sorted
        alpaca_filled_amount = 0.0
        for snapshot_position in snapshot_positions:
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
        # self.portfolio_allocation_history_size = len(allocation.position_history)

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

        wd_response = self._queue_and_get_response(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            portfolio_id=asset_id,
            queue_action=lambda: self.trade_execution_queuing_service.queue_stock_sell(
                asset_id=asset_id,
                amount=withdraw_amount,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        transaction_id = wd_response["transaction_id"]
        if cognito_user_id not in self.baskt_account_portfolio_positions:
            self.baskt_account_portfolio_positions[cognito_user_id] = {}

        if asset_id not in self.baskt_account_portfolio_positions[cognito_user_id]:
            self.baskt_account_portfolio_positions[cognito_user_id][asset_id] = {
                "all_orders":[],
                "filled_amounts":[]
            }

        # Realize filled orders
        while True:
            all_orders_fully_filled = True
            num_newly_filled_orders = self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                allocation_id=asset_id,
            )
            if num_newly_filled_orders > 0:
                self.portfolio_allocation_history_size+=1
            
            baskt_orders_dict = self.order_repository.get_orders_by_allocation(allocation_id=asset_id, cognito_user_id=cognito_user_id)
            for baskt_order_dict in baskt_orders_dict:
                if baskt_order_dict["status"] != "FILLED":
                    all_orders_fully_filled = False

            if all_orders_fully_filled:
                break

            sleep(0.25)

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_allocation(cognito_user_id=cognito_user_id, allocation_id=asset_id)

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
        allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id,allocation_id=asset_id)
        assert allocation is not None and len(allocation.position_history) == self.portfolio_allocation_history_size
        snapshot = allocation.position_history[-1]
        snapshot_positions = [] if snapshot.position is None else [snapshot.position]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot_positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot_positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
        assert symbols_snapshot_sorted == baskt_symbols_sorted
        alpaca_filled_amount2 = 0.0

        for snapshot_position in snapshot_positions:
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
                asset_id=asset_id,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
            ),
        )
        wd_orders = wd_response["orders"]
        transaction_id = wd_response["transaction_id"]

        # Realize filled orders
        while True:
            all_orders_fully_filled = True
            num_newly_filled_orders = self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                allocation_id=asset_id,
            )
            if num_newly_filled_orders > 0:
                self.portfolio_allocation_history_size+=1
            
            baskt_orders_dict = self.order_repository.get_orders_by_allocation(allocation_id=asset_id, cognito_user_id=cognito_user_id)
            for baskt_order_dict in baskt_orders_dict:
                if baskt_order_dict["status"] != "FILLED":
                    all_orders_fully_filled = False

            if all_orders_fully_filled:
                break

            sleep(0.25)

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_allocation(cognito_user_id=cognito_user_id, allocation_id=asset_id)
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
        allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id,allocation_id=asset_id)
        assert allocation is not None and len(allocation.position_history) == self.portfolio_allocation_history_size
        snapshot = allocation.position_history[-1]
        snapshot_positions = [] if snapshot.position is None else [snapshot.position]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot_positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot_positions:
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
                self.allocation_repository.allocation_table_client.delete_item(
                    key={"cognito_user_id": cognito_user_id,"allocation_id": asset_id}
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
                rows = self.order_repository.get_orders_by_allocation(
                    cognito_user_id=cognito_user_id,
                    allocation_id=portfolio_id,
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
                self.model_portfolio_access_repository.dynamodb.delete_item(
                    key={
                        "portfolio_id": portfolio_id,
                        "shared_with_cognito_user_id": cognito_user_id,
                    }
                )
            except Exception as e:
                pass

            try:
                self.allocation_repository.allocation_table_client.delete_item(
                    key={"cognito_user_id": cognito_user_id,"allocation_id": portfolio_id}
                )
            except Exception as e:
                pass

        for _, portfolio_id in portfolio_owner_model_portfolios:
            try:
                for access_record in (
                    self.model_portfolio_access_repository.get_accesses_for_portfolio(
                        portfolio_id=portfolio_id
                    )
                ):
                    self.model_portfolio_access_repository.dynamodb.delete_item(
                        key={
                            "portfolio_id": portfolio_id,
                            "shared_with_cognito_user_id": (
                                access_record.shared_with_cognito_user_id
                            ),
                        }
                    )
            except Exception as e:
                pass

            try:
                self.model_portfolio_repository.dynamodb.delete_item(
                    key={"allocation_id": portfolio_id}
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
    allocation_repository: AllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
) -> TestEngine:
    return TestEngine(
        account_lifecycle_service=account_lifecycle_service,
        trade_execution_service=trade_execution_service,
        trade_execution_queuing_service=trade_execution_queuing_service,
        sqs_client=sqs_client,
        model_portfolio_repository=model_portfolio_repository,
        order_repository=order_repository,
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
    )

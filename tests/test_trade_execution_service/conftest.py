import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv
from typing import List, Dict
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.cognito_client import CognitoClient
from backend.repository.user_account_repository import UserAccountRepository
from backend.services.account_lifecycle_service import AccountLifecycleService
from backend.repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from backend.repository.model_portfolio_repository import ModelPortfolioRepository
from backend.repository.portfolio_allocation_repository import PortfolioAllocationRepository
from backend.repository.order_repository import OrderRepository
from backend.repository.user_trade_lock_repository import UserTradeLockRepository
from backend.repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from backend.services.trade_execution_service import TradeExecutionService
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.domain.baskt import BasktPosition
from time import sleep
import uuid
from datetime import datetime, timezone
from backend.schema.model_portfolio_request import ModelPortfolioPositionRequest

MARGIN_ERROR = 0.01
FLOAT_ERROR = 1e-6

load_dotenv()
os.environ["ENV"] = "dev"
get_settings.cache_clear()

#######################################
############### CLIENTS ###############
#######################################
@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()

@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

########################################
############## REPOSITORY ##############
########################################
@pytest.fixture(scope="session")
def model_portfolio_follower_repository() -> ModelPortfolioFollowerRepository:
    model_portfolio_follower_dynamodb_client = app_deps.get_model_portfolio_dynamodb_client()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    return app_deps.get_model_portfolio_follower_repository(
        model_portfolio_follower_dynamodb_client=model_portfolio_follower_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )

@pytest.fixture(scope="session")
def model_portfolio_repository() -> ModelPortfolioRepository:

    app_deps.get_model_portfolio_dynamodb_client.cache_clear()
    model_portfolio_dynamodb_client = app_deps.get_model_portfolio_dynamodb_client()
    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()

    model_portfolio_update_lock_repository = app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=app_deps.get_model_portfolio_update_lock_dynamodb_client()
    )

    return app_deps.get_model_portfolio_repository(
        dynamodb=model_portfolio_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository
    )

@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository() -> ModelPortfolioUpdateLockRepository:

    app_deps.get_model_portfolio_update_lock_dynamodb_client.cache_clear()
    model_portfolio_update_lock_dynamodb_client = app_deps.get_model_portfolio_update_lock_dynamodb_client()

    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=model_portfolio_update_lock_dynamodb_client
    )

@pytest.fixture(scope="session")
def portfolio_allocation_repository() -> PortfolioAllocationRepository:
    app_deps.get_portfolio_allocation_dynamodb_client.cache_clear()
    portfolio_allocation_dynamodb_client = app_deps.get_portfolio_allocation_dynamodb_client()
    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    return app_deps.get_portfolio_allocation_repository(
        portfolio_allocation_dynamodb_client=portfolio_allocation_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )

@pytest.fixture(scope="session")
def order_repository() -> OrderRepository:
    app_deps.get_order_dynamodb_client.cache_clear()
    order_dynamodb_client = app_deps.get_order_dynamodb_client()
    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
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
def user_account_repository() -> UserAccountRepository:
    app_deps.get_user_account_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()
    return app_deps.get_user_account_repository(
        user_account_dynamodb_client=user_account_dynamodb_client
    )


##################################################
#################### SERVICES ####################
##################################################
    
@pytest.fixture(scope="session")
def account_lifecycle_service(
) -> AccountLifecycleService:
    app_deps.get_cognito_client.cache_clear()
    app_deps.get_alpaca_broker_client.cache_clear()
    app_deps.get_user_account_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()

    cognito_client = app_deps.get_cognito_client()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    user_account_repository = app_deps.get_user_account_repository(user_account_dynamodb_client=user_account_dynamodb_client)

    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        user_account_repository=user_account_repository,
    )

@pytest.fixture(scope="session")
def trade_execution_service() -> TradeExecutionService:

    app_deps.get_model_portfolio_dynamodb_client.cache_clear()
    model_portfolio_dynamodb_client = app_deps.get_model_portfolio_dynamodb_client()
    app_deps.get_alpaca_broker_client.cache_clear()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    app_deps.get_portfolio_allocation_dynamodb_client.cache_clear()
    portfolio_allocation_dynamodb_client = app_deps.get_portfolio_allocation_dynamodb_client()
    app_deps.get_order_dynamodb_client.cache_clear()
    order_dynamodb_client = app_deps.get_order_dynamodb_client()
    app_deps.get_model_portfolio_follower_dynamodb_client.cache_clear()
    model_portfolio_follower_dynamodb_client = app_deps.get_model_portfolio_follower_dynamodb_client()
    app_deps.get_user_trade_lock_dynamodb_client.cache_clear()
    user_trade_lock_dynamodb_client = app_deps.get_user_trade_lock_dynamodb_client()

    model_portfolio_update_lock_repository = app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=app_deps.get_model_portfolio_update_lock_dynamodb_client()
    )
    model_portfolio_repository = app_deps.get_model_portfolio_repository(
        dynamodb=model_portfolio_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository
    )
    portfolio_allocation_repository = app_deps.get_portfolio_allocation_repository(
        portfolio_allocation_dynamodb_client=portfolio_allocation_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )
    order_repository = app_deps.get_order_repository(
        order_dynamodb_client=order_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )
    model_portfolio_follower_repository = app_deps.get_model_portfolio_follower_repository(
        model_portfolio_follower_dynamodb_client=model_portfolio_follower_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client
    )
    user_trade_lock_repository = app_deps.get_user_trade_lock_repository(
        user_trade_lock_dynamodb_client=user_trade_lock_dynamodb_client
    )
    account_lifecycle_service = app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        user_account_repository=user_account_repository
    )


    return app_deps.get_trade_execution_service(
        model_portfolio_repository=model_portfolio_repository,
        alpaca_broker_client=alpaca_broker_client,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
        account_lifecycle_service=account_lifecycle_service
    )

###########################################
############### TEST ENGINE ###############
###########################################

class TestEngine:
    def __init__(
        self,
        account_lifecycle_service: AccountLifecycleService,
        trade_execution_service: TradeExecutionService,
        model_portfolio_repository: ModelPortfolioRepository,
        order_repository: OrderRepository,
        alpaca_broker_client: AlpacaBrokerClient,
        portfolio_allocation_repository: PortfolioAllocationRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository
    ):
        self.account_lifecycle_service = account_lifecycle_service
        self.trade_execution_service = trade_execution_service
        self.model_portfolio_repository = model_portfolio_repository
        self.order_repository = order_repository
        self.alpaca_broker_client = alpaca_broker_client
        self.portfolio_allocation_repository = portfolio_allocation_repository
        self.model_portfolio_follower_repository = model_portfolio_follower_repository
        self.baskt_account_portfolio_positions = {}

    def test_delete_model_portfolio(self, portfolio_id: str):
        return self.model_portfolio_repository.delete_model_portfolio(portfolio_id=portfolio_id)

    def test_create_baskt_account(self):
        unique_suffix = uuid.uuid4().hex[:8]
        signed_at = datetime.now(timezone.utc).isoformat()

        account_data = {
            "contact": {
                "email_address": f"baskt_testuser_{unique_suffix}@example.com",
                "phone_number": "+15555551234",
                "street_address": ["123 Market St"],
                "unit": "9A",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94105",
                "country": "USA",
            },
            "identity": {
                "given_name": "Jane",
                "middle_name": "Q",
                "family_name": "Tester",
                "date_of_birth": "1990-01-01",
                "tax_id": "999-99-1234",
                "tax_id_type": "USA_SSN",
                "country_of_citizenship": "USA",
                "country_of_birth": "USA",
                "country_of_tax_residence": "USA",
                "funding_source": ["employment_income"],
                "annual_income_min": 50000,
                "annual_income_max": 120000,
                "liquid_net_worth_min": 10000,
                "liquid_net_worth_max": 50000,
                "total_net_worth_min": 50000,
                "total_net_worth_max": 200000,
            },
            "disclosures": {
                "is_control_person": False,
                "is_affiliated_exchange_or_finra": False,
                "is_politically_exposed": False,
                "immediate_family_exposed": False,
            },
            "agreements": [
                {
                    "agreement": "customer_agreement",
                    "signed_at": signed_at,
                    "ip_address": "127.0.0.1",
                }
            ],
        }

        password = uuid.uuid4().hex[:15]
        password = "TEST_"+ password

        create_account_response = self.account_lifecycle_service.create_baskt_account(account_data=account_data, password=password)

        assert create_account_response is not None
        assert create_account_response["email_address"] == account_data["contact"]["email_address"]
        baskt_account = self.account_lifecycle_service.get_baskt_account_by_email_address(email_address=create_account_response["email_address"])
        sleep(120)
        baskt_account.alpaca_account_status == "ACTIVE"
        baskt_account.cognito_enabled_status == True

        self.baskt_account_portfolio_positions[baskt_account.cognito_user_id] = {}
        return baskt_account
    
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

        model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
        assert model_portfolio is not None
        assert len(model_portfolio.position_history) == 1
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
        deposit_response = self.trade_execution_service.execute_deposit_to_portfolio(
        portfolio_id=portfolio_id,
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        deposit_amount=deposit_amount,
        cognito_user_id=cognito_user_id,
        is_test=True
        )
        dep_orders = deposit_response["orders"]
        transaction_id = deposit_response["transaction_id"]

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
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, order_id=order_id)
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
        snapshot = allocation.portfolio_allocation_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id)
        baskt_symbols_sorted = sorted([symbol for symbol in baskt_positions_dict])
        assert symbols_snapshot_sorted == baskt_symbols_sorted
        alpaca_filled_amount = 0.0
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in baskt_positions_dict
            assert abs(snapshot_position.filled_quantity - baskt_positions_dict[snapshot_position.symbol].filled_quantity) <= FLOAT_ERROR
            assert abs(snapshot_position.filled_avg_price - baskt_positions_dict[snapshot_position.symbol].filled_avg_price) <= FLOAT_ERROR
            assert snapshot_position.direction == baskt_positions_dict[snapshot_position.symbol].direction
            alpaca_filled_amount += (baskt_positions_dict[snapshot_position.symbol].filled_quantity * baskt_positions_dict[snapshot_position.symbol].filled_avg_price)
        assert abs(snapshot.allocation_amount - alpaca_filled_amount) / snapshot.allocation_amount <= MARGIN_ERROR

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
        assert cognito_user_id in model_portfolio_followers

@pytest.fixture(scope="session")
def test_engine(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    model_portfolio_repository: ModelPortfolioRepository,
    order_repository: OrderRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository
) -> TestEngine:
    return TestEngine(
        account_lifecycle_service=account_lifecycle_service,
        trade_execution_service=trade_execution_service,
        model_portfolio_repository=model_portfolio_repository,
        order_repository=order_repository,
        alpaca_broker_client=alpaca_broker_client,
        portfolio_allocation_repository=portfolio_allocation_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository
    )


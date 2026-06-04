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
from backend.services.account_lifecycle_service import AccountLifecycleService
from backend.repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from backend.repository.model_portfolio_repository import ModelPortfolioRepository
from backend.repository.portfolio_allocation_repository import PortfolioAllocationRepository
from backend.repository.order_repository import OrderRepository
from backend.repository.user_trade_lock_repository import UserTradeLockRepository
from backend.repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from backend.services.trade_execution_service import TradeExecutionService
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.domain.baskt import BasktPosition, BasktAccount
from time import sleep
from datetime import datetime, timezone, timedelta
from backend.schema.model_portfolio_request import ModelPortfolioPositionRequest
from collections import defaultdict

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
    model_portfolio_follower_dynamodb_client = app_deps.get_model_portfolio_follower_dynamodb_client()
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

##################################################
#################### SERVICES ####################
##################################################
    
@pytest.fixture(scope="session")
def account_lifecycle_service(
) -> AccountLifecycleService:
    app_deps.get_cognito_client.cache_clear()
    app_deps.get_alpaca_broker_client.cache_clear()

    cognito_client = app_deps.get_cognito_client()
    alpaca_broker_client = app_deps.get_alpaca_broker_client()

    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
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
    app_deps.get_cognito_client.cache_clear()
    cognito_client = app_deps.get_cognito_client()

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
        self.model_portfolio_update_times = defaultdict(list) # also used to calculate model portfolio position history length
    
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
        dep_orders = self.trade_execution_service.execute_deposit_to_portfolio(
        portfolio_id=portfolio_id,
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        deposit_amount=deposit_amount,
        cognito_user_id=cognito_user_id,
        is_test=True
        )

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
        snapshot = allocation.portfolio_allocation_history[-1]
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


    def test_update_effect(
        self,
        portfolio_owner_cognito_user_id: str,
        portfolio_id: str,
        ud_orders_dict: Dict
    ):
        # Test effect for each follower
        follower_cognito_user_ids = self.model_portfolio_follower_repository.get_model_portfolio_followers(portfolio_id=portfolio_id)
        assert sorted(list(ud_orders_dict.keys())) == sorted(follower_cognito_user_ids)
        for cognito_user_id in ud_orders_dict:
            baskt_account = self.account_lifecycle_service.get_baskt_account_by_cognito_user_id(cognito_user_id=cognito_user_id)
            self.trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                alpaca_account_id=baskt_account.alpaca_account_id,
                portfolio_id=portfolio_id,
            )

            ud_orders = ud_orders_dict[cognito_user_id]
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
            alpaca_order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=baskt_account.alpaca_account_id, cognito_user_id=cognito_user_id, order_id=order_id)
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
        assert allocation is not None and len(allocation.portfolio_allocation_history) == self.portfolio_allocation_history_size
        snapshot = allocation.portfolio_allocation_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=baskt_account.alpaca_account_id, cognito_user_id=cognito_user_id)
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
        updated = self.model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=new_positions,
            update_time=update_time
        )

        updated_orders_dict = self.trade_execution_service.execute_update_in_portfolio(
            portfolio_id=portfolio_id, 
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id, 
            is_test=True
        )
        self.model_portfolio_update_times[portfolio_id].append(update_time)

        # Wait for orders to be filled
        sleep(2)

        return updated_orders_dict

    def test_cleanup(self, baskt_accounts_and_portfolio_ids: List[List[BasktAccount | str]]):
        for baskt_account, portfolio_id in baskt_accounts_and_portfolio_ids:
            self.alpaca_broker_client.execute_close_all_position(alpaca_account_id=baskt_account.alpaca_account_id)

            self.model_portfolio_repository.dynamodb.delete_item(key={"portfolio_id": portfolio_id})
            self.model_portfolio_follower_repository.delete_model_portfolio_follower(cognito_user_id=baskt_account.cognito_user_id,portfolio_id=portfolio_id)
            self.portfolio_allocation_repository.portfolio_allocation_table_client.delete_item(key={"cognito_user_id": baskt_account.cognito_user_id,"portfolio_id": portfolio_id})
            self.order_repository.order_table_client.delete_item(key={"portfolio_id": portfolio_id})

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
        snapshot = portfolio_allocation.portfolio_allocation_history[-1]
        symbols = [position.symbol for position in snapshot.positions]
        quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
        for snapshot_position in snapshot.positions:
            price = quotes[snapshot_position.symbol]
            market_value += (price * snapshot_position.filled_quantity)

        wd_orders = self.trade_execution_service.execute_withdraw_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            withdraw_amount=withdraw_amount,
            cognito_user_id=cognito_user_id,
            is_test=True
        )
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
        assert allocation is not None and len(allocation.portfolio_allocation_history) == self.portfolio_allocation_history_size
        snapshot = allocation.portfolio_allocation_history[-1]
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
        assert abs(snapshot.allocation_amount - alpaca_filled_amount2) / snapshot.allocation_amount <= MARGIN_ERROR

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

    def test_withdraw_all(
        self,
        portfolio_owner_cognito_user_id: str,
        alpaca_account_id: str,
        cognito_user_id: str,
        portfolio_id: str,
    ):

        wd_orders = self.trade_execution_service.execute_withdraw_all_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            cognito_user_id=cognito_user_id,
            is_test=True
        )
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
        rows2 = self.order_repository.get_orders_by_portfolio(portfolio_id=portfolio_id)
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
        assert allocation is not None and len(allocation.portfolio_allocation_history) == self.portfolio_allocation_history_size
        snapshot = allocation.portfolio_allocation_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR

        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        assert len(baskt_positions_dict) == 0


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

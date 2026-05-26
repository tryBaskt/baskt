import uuid
import time
from typing import List, Dict
from datetime import timedelta
import pytest

from backend.domain.model_portfolio import ModelPortfolioPosition
from backend.repository.model_portfolio_repository import ModelPortfolioRepository
from backend.services.trade_execution_service import TradeExecutionService
from backend.clients.alpaca_client import AlpacaClient
from backend.repository.portfolio_allocation_repository import PortfolioAllocationRepository
from backend.domain.baskt import BasktPosition
from backend.repository.order_repository import OrderRepository
from backend.repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from backend.repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from backend.repository.user_trade_lock_repository import UserTradeLockRepository
from backend.schema.model_portfolio_request import ModelPortfolioPositionRequest
MARGIN_ERROR = 0.01
FLOAT_ERROR = 1e-6
class PortfolioTestUser:
    def __init__(
        self, 
        model_portfolio_repository: ModelPortfolioRepository, 
        trade_execution_service: TradeExecutionService, 
        order_repository: OrderRepository,
        portfolio_allocation_repository: PortfolioAllocationRepository,
        user_id: str,
        alpaca_client: AlpacaClient,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
        model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
        user_trade_lock_repository: UserTradeLockRepository
    ):
        self.model_portfolio_repository = model_portfolio_repository
        self.trade_execution_service = trade_execution_service
        self.order_repository = order_repository
        self.portfolio_allocation_repository = portfolio_allocation_repository
        self.user_id = user_id
        self.alpaca_client = alpaca_client

        self.update_times_by_owned_protfolios: Dict[str, List[str]] = {}
        self.data_by_portfolio_id: Dict[str, Dict[str,List]]= {}

        self.portfolio_allocation_history_size = 0
        self.model_portfolio_history_size = 0
        self.allocated_portfolios = []
        self.model_portfolio_follower_repository = model_portfolio_follower_repository

        self.model_portfolio_update_lock_repository = model_portfolio_update_lock_repository
        self.user_trade_lock_repository = user_trade_lock_repository


    def test_create_portfolio(
        self,
        symbols: List[str],
        directions: List[int],
        target_weights: List[float],
        leverages: List[float],
        portfolio_name: str,
        owner = False
    ):
        # Arrange using provided inputs
        owner_id = str(uuid.uuid4())
        if owner:
            owner_id = self.user_id

        positions_request: List[ModelPortfolioPositionRequest] = [
            ModelPortfolioPositionRequest(symbol=s, target_weight=w, direction=d, leverage=l)
            for s, w, d, l in zip(symbols, target_weights, directions, leverages)
        ]
        portfolio_id = self.model_portfolio_repository.create_model_portfolio(
            portfolio_owner_id=owner_id,
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

        self.update_times_by_owned_protfolios[portfolio_id] = [model_portfolio.created_at]

        return portfolio_id, owner_id 
    
    def test_deposit(
        self,
        deposit_amount: float,
        portfolio_id: str,
        portfolio_owner_id: str,
    ):
        dep_orders = self.trade_execution_service.execute_deposit_to_portfolio(
        portfolio_id=portfolio_id,
        portfolio_owner_id=portfolio_owner_id,
        deposit_amount=deposit_amount,
        user_id=self.user_id,
        is_test=True
        )
        # Wait for orders to be filled
        time.sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            user_id=self.user_id,
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
        )
        self.portfolio_allocation_history_size+=1
        self.allocated_portfolios.append(portfolio_id)

        if portfolio_id not in self.data_by_portfolio_id:
            self.data_by_portfolio_id[portfolio_id] = {
                "all_orders": [],
                "filled_amounts": []
            }

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(portfolio_id=portfolio_id)
        assert len(dep_orders) + len(self.data_by_portfolio_id[portfolio_id]["all_orders"]) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in dep_orders + self.data_by_portfolio_id[portfolio_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_client.get_order_by_id(order_id=order_id)
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
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(user_id=self.user_id,portfolio_id=portfolio_id)
        assert allocation is not None and len(allocation.portfolio_allocation_history) == self.portfolio_allocation_history_size
        snapshot = allocation.portfolio_allocation_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_client.get_baskt_positions_dict()
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
        prev_filled_amount = self.data_by_portfolio_id[portfolio_id]["filled_amounts"][-1] if self.data_by_portfolio_id[portfolio_id]["filled_amounts"] else 0.0
        incremental_amount = alpaca_filled_amount - prev_filled_amount
        assert abs(deposit_amount - incremental_amount) / deposit_amount <= MARGIN_ERROR

        self.data_by_portfolio_id[portfolio_id]["all_orders"].extend(dep_orders)
        self.data_by_portfolio_id[portfolio_id]["filled_amounts"].append(alpaca_filled_amount)

        # Validate user is in model portfolio's followers
        model_portfolio_followers = self.model_portfolio_follower_repository.get_model_portfolio_followers(portfolio_id=portfolio_id)
        assert self.user_id in model_portfolio_followers

    def test_update_effect(
        self,
        portfolio_owner_id: str,
        portfolio_id: str,
        ud_orders: List
    ):
        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            user_id=self.user_id,
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
        )
        self.portfolio_allocation_history_size+=1

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(portfolio_id=portfolio_id)
        assert len(rows2) == len(self.data_by_portfolio_id[portfolio_id]["all_orders"]) + len(ud_orders)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"],

            } 
            for row in rows2
        }
        for order in ud_orders + self.data_by_portfolio_id[portfolio_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_client.get_order_by_id(order_id=order_id)
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
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(user_id=self.user_id,portfolio_id=portfolio_id)
        assert allocation is not None and len(allocation.portfolio_allocation_history) == self.portfolio_allocation_history_size
        snapshot = allocation.portfolio_allocation_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_client.get_baskt_positions_dict()
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

        prev_fill_amount = self.data_by_portfolio_id[portfolio_id]["filled_amounts"][-1]
        assert abs(prev_fill_amount - alpaca_filled_amount) / prev_fill_amount <= MARGIN_ERROR


        # self.data_by_portfolio_id[portfolio_id]["update_timestamps"].append(update_time)
        # self.update_times_by_owned_protfolios[portfolio_id].append(update_time)
        self.data_by_portfolio_id[portfolio_id]["filled_amounts"].append(alpaca_filled_amount)
        self.data_by_portfolio_id[portfolio_id]["all_orders"].extend(ud_orders)

        

    def test_update(
        self,
        portfolio_owner_id: str,
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
        update_time = self.update_times_by_owned_protfolios[portfolio_id][-1] + timedelta(minutes = 2)
        updated = self.model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=new_positions,
            update_time=update_time
        )

        updated_orders_dict = self.trade_execution_service.execute_update_in_portfolio(
            portfolio_id=portfolio_id, 
            portfolio_owner_id=portfolio_owner_id, 
            is_test=True
        )
        self.update_times_by_owned_protfolios[portfolio_id].append(update_time)

        # Wait for orders to be filled
        time.sleep(2)

        return updated_orders_dict


    def test_withdraw(
        self,
        portfolio_owner_id: str,
        portfolio_id: str,
        withdraw_amount: float,
        slippage_correction: int = 1
    ):
        market_value = 0.0
        portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(user_id=self.user_id, portfolio_id=portfolio_id)
        snapshot = portfolio_allocation.portfolio_allocation_history[-1]
        symbols = [position.symbol for position in snapshot.positions]
        quotes = self.alpaca_client.get_latest_price(symbols=symbols)
        for snapshot_position in snapshot.positions:
            price = quotes[snapshot_position.symbol]
            market_value += (price * snapshot_position.filled_quantity)

        wd_orders = self.trade_execution_service.execute_withdraw_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            withdraw_amount=withdraw_amount,
            user_id=self.user_id,
            is_test=True
        )
        # Wait for orders to be filled
        time.sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            user_id=self.user_id,
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
        )
        self.portfolio_allocation_history_size+=1

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(portfolio_id=portfolio_id)
        assert len(self.data_by_portfolio_id[portfolio_id]["all_orders"]) + len(wd_orders) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in wd_orders + self.data_by_portfolio_id[portfolio_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_client.get_order_by_id(order_id=order_id)
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
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(user_id=self.user_id,portfolio_id=portfolio_id)
        assert allocation is not None and len(allocation.portfolio_allocation_history) == self.portfolio_allocation_history_size
        snapshot = allocation.portfolio_allocation_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_client.get_baskt_positions_dict()
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
        
        alpaca_filled_amount = self.data_by_portfolio_id[portfolio_id]["filled_amounts"][-1]
        assert abs(withdraw_amount - (alpaca_filled_amount - alpaca_filled_amount2)) / withdraw_amount <= MARGIN_ERROR

        self.data_by_portfolio_id[portfolio_id]["filled_amounts"].append(alpaca_filled_amount2)
        self.data_by_portfolio_id[portfolio_id]["all_orders"].extend(wd_orders)

    def test_withdraw_all(
        self,
        portfolio_owner_id: str,
        portfolio_id: str,
    ):

        wd_orders = self.trade_execution_service.execute_withdraw_all_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            user_id=self.user_id,
            is_test=True
        )
        time.sleep(2)

        # Realize filled orders
        self.trade_execution_service.realize_filled_orders(
            user_id=self.user_id,
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
        )
        self.portfolio_allocation_history_size+=1

        # match alpaca orders and order_db
        rows2 = self.order_repository.get_orders_by_portfolio(portfolio_id=portfolio_id)
        assert len(self.data_by_portfolio_id[portfolio_id]["all_orders"]) + len(wd_orders) == len(rows2)
        rows2_dict_order_id = {
            row["order_id"]: {
                "symbol": row["symbol"],
                "filled_qty": row["filled_qty"],
                "filled_avg_price": row["filled_avg_price"]
            } 
            for row in rows2
        }
        for order in wd_orders + self.data_by_portfolio_id[portfolio_id]["all_orders"]:
            order_id = str(order.id)
            alpaca_order = self.alpaca_client.get_order_by_id(order_id=order_id)
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
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(user_id=self.user_id,portfolio_id=portfolio_id)
        assert allocation is not None and len(allocation.portfolio_allocation_history) == self.portfolio_allocation_history_size
        snapshot = allocation.portfolio_allocation_history[-1]
        symbols_snapshot_sorted = sorted(position.symbol for position in snapshot.positions)
        symbols_orders_db_sorted = sorted(orders_db_symbols_quantity.keys())
        assert symbols_orders_db_sorted == symbols_snapshot_sorted
        for snapshot_position in snapshot.positions:
            assert snapshot_position.symbol in orders_db_symbols_quantity
            assert abs(orders_db_symbols_quantity[snapshot_position.symbol] - snapshot_position.direction * snapshot_position.filled_quantity) <= FLOAT_ERROR


        # match portfolio_allocation to alpaca
        baskt_positions_dict: Dict[str, BasktPosition] = self.alpaca_client.get_baskt_positions_dict()
        assert len(baskt_positions_dict) == 0
        

    def test_clean_up(
        self,
        portfolio_id: str = None,
    ):
        # Cleanup
        try:
            self.model_portfolio_repository.delete_model_portfolio(portfolio_id=portfolio_id)
        except Exception:
            pass
        try:
            self.portfolio_allocation_repository.delete_portfolio_allocation(user_id=self.user_id, portfolio_id=portfolio_id)
        except Exception:
            pass
        try:
            self.order_repository.delete_orders_by_portfolio_id(portfolio_id=portfolio_id)
        except Exception:
            pass
        try:
            self.alpaca_client.close_all_positions(cancel_open_orders=True, wait=True, timeout_sec=120, poll_interval_sec=2.0)
        except Exception:
            pass
        try:
            self.model_portfolio_follower_repository.delete_model_portfolio_follower(user_id=self.user_id, portfolio_id=portfolio_id)
        except Exception:
            pass
        try:
            self.model_portfolio_update_lock_repository.delete_lock(portfolio_id=portfolio_id)
        except Exception:
            pass
        try:
            self.user_trade_lock_repository.delete_lock(user_id=self.user_id)
        except Exception:
            pass



    
@pytest.mark.integration
def test_basic_deposit(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    user_id = str(uuid.uuid4())
    portfolio_id = None
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-dep-wd-realize-{uuid.uuid4()}"
        symbols = [
            "AAPL"
        ]
        directions = [1]
        target_weights = [1.00]
        leverages = [1.0] * len(symbols)
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )

    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )

@pytest.mark.integration
def test_multi_symbol_direction_switch(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    # orders_db: AuroraRDSClient,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    """Test multiple symbols switching directions simultaneously (long -> short)"""
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        # orders_db=orders_db,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-multi-dir-switch-{uuid.uuid4()}"
        symbols = ["AAPL", "GOOG", "MSFT"]
        directions = [1, 1, 1]  # All long
        target_weights = [0.33, 0.33, 0.34]
        leverages = [1.0, 1.0, 1.0]
        
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        
        test_user.test_deposit(
            deposit_amount=300.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Switch all positions from long to short
        new_symbols = ["AAPL", "GOOG", "MSFT"]
        new_directions = [-1, -1, -1]  # All short
        new_target_weights = [0.33, 0.33, 0.34]
        new_leverages = [1.0, 1.0, 1.0]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )

        test_user.test_update_effect(portfolio_owner_id=portfolio_owner_id, portfolio_id=portfolio_id, ud_orders=updated_orders_dict[user_id])
        
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=50.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_full_pos_rev_deposit_update_withdraw(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-dep-wd-realize-{uuid.uuid4()}"
        symbols = [
            "AAPL"
        ]
        directions = [1]
        target_weights = [1.00]
        leverages = [1.0] * len(symbols)
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        test_user.test_deposit(
            deposit_amount= 150.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        new_symbols = ["AAPL"]
        new_directions = [-1]
        new_leverages = [1,1]
        new_target_weights = [1]
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )

        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=20.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_add_new_symbols_keep_existing(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    # orders_db: AuroraRDSClient,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    """Test adding new symbols while keeping existing positions"""
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        # orders_db=orders_db,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-add-symbols-{uuid.uuid4()}"
        symbols = ["AAPL", "GOOG"]
        directions = [1, 1]
        target_weights = [0.50, 0.50]
        leverages = [1.0, 1.0]
        
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        
        test_user.test_deposit(
            deposit_amount=500.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Add MSFT and TSLA while keeping AAPL and GOOG
        new_symbols = ["AAPL", "GOOG", "MSFT", "TSLA"]
        new_directions = [1, 1, -1, 1]
        new_target_weights = [0.25, 0.25, 0.25, 0.25]
        new_leverages = [1.0, 1.0, 1.0, 1.0]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )
        
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=100.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_mixed_symbol_operations(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    """Test removing some symbols, keeping others, and adding new ones (mixed operation)"""
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-mixed-ops-{uuid.uuid4()}"
        symbols = ["AAPL", "GOOG", "MSFT", "TSLA"]
        directions = [1, 1, 1, -1]
        target_weights = [0.25, 0.25, 0.25, 0.25]
        leverages = [1.0, 1.0, 1.0, 1.0]
        
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        
        test_user.test_deposit(
            deposit_amount=600.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Remove GOOG and TSLA, keep AAPL and MSFT, add NVDA and META
        new_symbols = ["AAPL", "MSFT", "NVDA", "META"]
        new_directions = [1, 1, -1, 1]
        new_target_weights = [0.30, 0.30, 0.20, 0.20]
        new_leverages = [1.0, 1.0, 1.0, 1.0]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )
        
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=150.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_rebalance_weights_only(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    """Test rebalancing weights only (same symbols, different allocations)"""
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-rebalance-weights-{uuid.uuid4()}"
        symbols = ["AAPL", "GOOG", "MSFT"]
        directions = [1, -1, 1]
        target_weights = [0.33, 0.33, 0.34]
        leverages = [1.0, 1.0, 1.0]
        
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        
        test_user.test_deposit(
            deposit_amount=450.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Same symbols and directions, only change weights
        new_symbols = ["AAPL", "GOOG", "MSFT"]
        new_directions = [1, -1, 1]
        new_target_weights = [0.50, 0.20, 0.30]  # Rebalanced weights
        new_leverages = [1.0, 1.0, 1.0]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )
        
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=100.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )



@pytest.mark.integration
def test_change_everything_simultaneously(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    """Test changing everything simultaneously (symbols + weights + directions + leverage)"""
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository = order_repository,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-change-all-{uuid.uuid4()}"
        symbols = ["AAPL", "GOOG"]
        directions = [1, -1]
        target_weights = [0.60, 0.40]
        leverages = [1.0, 1.0]
        
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        
        test_user.test_deposit(
            deposit_amount=550.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Change everything: different symbols, weights, directions, and leverage
        new_symbols = ["MSFT", "NVDA", "TSLA"]
        new_directions = [-1, 1, -1]
        new_target_weights = [0.40, 0.35, 0.25]
        new_leverages = [1, 1, 1]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )
        
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=120.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_multiple_deposits_before_update(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    """Test multiple deposits to same portfolio before any update"""
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-multi-deposits-{uuid.uuid4()}"
        symbols = ["AAPL", "GOOG"]
        directions = [1, -1]
        target_weights = [0.60, 0.40]
        leverages = [1.0, 1.0]
        
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        
        # First deposit
        test_user.test_deposit(
            deposit_amount=200.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Second deposit
        test_user.test_deposit(
            deposit_amount=150.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Third deposit
        test_user.test_deposit(
            deposit_amount=250.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Now update after multiple deposits
        new_symbols = ["AAPL", "GOOG", "MSFT"]
        new_directions = [1, -1, 1]
        new_target_weights = [0.40, 0.30, 0.30]
        new_leverages = [1.0, 1.0, 1.0]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )
        
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=100.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_deposit_after_partial_withdrawal(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    """Test deposit after partial withdrawal (cash injection mid-lifecycle)"""
    user_id = str(uuid.uuid4())
    test_user = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=user_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-deposit-after-wd-{uuid.uuid4()}"
        symbols = ["AAPL", "MSFT", "GOOG"]
        directions = [1, 1, -1]
        target_weights = [0.40, 0.40, 0.20]
        leverages = [1.0, 1.0, 1.0]
        
        portfolio_id, portfolio_owner_id = test_user.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )
        
        # Initial deposit
        test_user.test_deposit(
            deposit_amount=500.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # First update
        new_symbols = ["AAPL", "MSFT", "GOOG", "TSLA"]
        new_directions = [1, 1, -1, 1]
        new_target_weights = [0.30, 0.30, 0.20, 0.20]
        new_leverages = [1.0, 1.0, 1.0, 1.0]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )
        
        # Partial withdrawal
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=150.00
        )
        
        # Cash injection - deposit after withdrawal
        test_user.test_deposit(
            deposit_amount=300.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        
        # Another update after cash injection
        new_symbols = ["AAPL", "MSFT", "NVDA"]
        new_directions = [-1, 1, 1]
        new_target_weights = [0.50, 0.25, 0.25]
        new_leverages = [1.0, 1.0, 1.0]
        
        updated_orders_dict = test_user.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[user_id]
        )
        
        # Final withdrawal
        test_user.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=200.00
        )
    finally:
        test_user.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_basic_deposit(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-cross-user-dep-{uuid.uuid4()}"
        symbols = ["AAPL"]
        directions = [1]
        target_weights = [1.00]
        leverages = [1.0]
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=150.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_multi_symbol_direction_switch(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    try:
        portfolio_name = f"pytest-cross-user-dir-switch-{uuid.uuid4()}"
        symbols = ["AAPL", "GOOG", "MSFT"]
        directions = [1, 1, 1]
        target_weights = [0.33, 0.33, 0.34]
        leverages = [1.0, 1.0, 1.0]
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=symbols,
            directions=directions,
            target_weights=target_weights,
            leverages=leverages,
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=300.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL", "GOOG", "MSFT"]
        new_directions=[-1, -1, -1]
        new_leverages=[1.0, 1.0, 1.0]
        new_target_weights=[0.33, 0.33, 0.34]

        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=50.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_full_pos_rev_deposit_update_withdraw(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    portfolio_id = None
    portfolio_owner_id = None
    try:
        portfolio_name = f"pytest-cross-user-full-rev-{uuid.uuid4()}"
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=["AAPL"],
            directions=[1],
            target_weights=[1.00],
            leverages=[1.0],
            portfolio_name=portfolio_name,
            owner=True
        )
        test_user2.test_deposit(
            deposit_amount=150.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL"]
        new_directions=[-1]
        new_leverages=[1]
        new_target_weights=[1]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=20.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_add_new_symbols_keep_existing(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    portfolio_id = None
    portfolio_owner_id = None
    try:
        portfolio_name = f"pytest-cross-user-add-symbols-{uuid.uuid4()}"
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=["AAPL", "GOOG"],
            directions=[1, 1],
            target_weights=[0.50, 0.50],
            leverages=[1.0, 1.0],
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=500.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL", "GOOG", "MSFT", "TSLA"]
        new_directions=[1, 1, -1, 1]
        new_target_weights=[0.25, 0.25, 0.25, 0.25]
        new_leverages=[1.0, 1.0, 1.0, 1.0]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=100.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_mixed_symbol_operations(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    portfolio_id = None
    portfolio_owner_id = None
    try:
        portfolio_name = f"pytest-cross-user-mixed-ops-{uuid.uuid4()}"
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=["AAPL", "GOOG", "MSFT", "TSLA"],
            directions=[1, 1, 1, -1],
            target_weights=[0.25, 0.25, 0.25, 0.25],
            leverages=[1.0, 1.0, 1.0, 1.0],
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=600.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL", "MSFT", "NVDA", "META"]
        new_directions=[1, 1, -1, 1]
        new_target_weights=[0.30, 0.30, 0.20, 0.20]
        new_leverages=[1.0, 1.0, 1.0, 1.0]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=150.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_rebalance_weights_only(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    portfolio_id = None
    portfolio_owner_id = None
    try:
        portfolio_name = f"pytest-cross-user-rebalance-{uuid.uuid4()}"
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=["AAPL", "GOOG", "MSFT"],
            directions=[1, -1, 1],
            target_weights=[0.33, 0.33, 0.34],
            leverages=[1.0, 1.0, 1.0],
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=450.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL", "GOOG", "MSFT"]
        new_directions=[1, -1, 1]
        new_target_weights=[0.50, 0.20, 0.30]
        new_leverages=[1.0, 1.0, 1.0]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=100.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_change_everything_simultaneously(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    portfolio_id = None
    portfolio_owner_id = None
    try:
        portfolio_name = f"pytest-cross-user-change-all-{uuid.uuid4()}"
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=["AAPL", "GOOG"],
            directions=[1, -1],
            target_weights=[0.60, 0.40],
            leverages=[1.0, 1.0],
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=550.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["MSFT", "NVDA", "TSLA"]
        new_directions=[-1, 1, -1]
        new_target_weights=[0.40, 0.35, 0.25]
        new_leverages=[1, 1, 1]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=120.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )


@pytest.mark.integration
def test_cross_user_multiple_deposits_before_update(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    portfolio_id = None
    portfolio_owner_id = None
    try:
        portfolio_name = f"pytest-cross-user-multi-dep-{uuid.uuid4()}"
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=["AAPL", "GOOG"],
            directions=[1, -1],
            target_weights=[0.60, 0.40],
            leverages=[1.0, 1.0],
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=200.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        test_user2.test_deposit(
            deposit_amount=150.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )
        test_user2.test_deposit(
            deposit_amount=250.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL", "GOOG", "MSFT"]
        new_directions=[1, -1, 1]
        new_target_weights=[0.40, 0.30, 0.30]
        new_leverages=[1.0, 1.0, 1.0]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=100.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id,
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_cross_user_deposit_after_partial_withdrawal(
    model_portfolio_repository: ModelPortfolioRepository,
    trade_execution_service: TradeExecutionService,
    order_repository: OrderRepository,
    alpaca_client: AlpacaClient,
    portfolio_allocation_repository: PortfolioAllocationRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    user_trade_lock_repository: UserTradeLockRepository
):
    test_user1_id = str(uuid.uuid4())
    test_user2_id = str(uuid.uuid4())
    test_user1 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user1_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    test_user2 = PortfolioTestUser(
        model_portfolio_repository=model_portfolio_repository,
        trade_execution_service=trade_execution_service,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        user_id=test_user2_id,
        alpaca_client=alpaca_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )
    portfolio_id = None
    portfolio_owner_id = None
    try:
        portfolio_name = f"pytest-cross-user-dep-after-wd-{uuid.uuid4()}"
        portfolio_id, portfolio_owner_id = test_user1.test_create_portfolio(
            symbols=["AAPL", "MSFT", "GOOG"],
            directions=[1, 1, -1],
            target_weights=[0.40, 0.40, 0.20],
            leverages=[1.0, 1.0, 1.0],
            portfolio_name=portfolio_name,
            owner=True
        )

        test_user2.test_deposit(
            deposit_amount=500.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL", "MSFT", "GOOG", "TSLA"]
        new_directions=[1, 1, -1, 1]
        new_target_weights=[0.30, 0.30, 0.20, 0.20]
        new_leverages=[1.0, 1.0, 1.0, 1.0]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=150.00
        )

        test_user2.test_deposit(
            deposit_amount=300.00,
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id
        )

        new_symbols=["AAPL", "MSFT", "NVDA"]
        new_directions=[-1, 1, 1]
        new_target_weights=[0.50, 0.25, 0.25]
        new_leverages=[1.0, 1.0, 1.0]
        updated_orders_dict = test_user1.test_update(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            new_symbols=new_symbols,
            new_directions=new_directions,
            new_leverages=new_leverages,
            new_target_weights=new_target_weights
        )
        test_user2.test_update_effect(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            ud_orders=updated_orders_dict[test_user2_id]
        )

        test_user2.test_withdraw(
            portfolio_owner_id=portfolio_owner_id,
            portfolio_id=portfolio_id,
            withdraw_amount=200.00
        )
    finally:
        test_user1.test_clean_up(
            portfolio_id=portfolio_id
        )
        test_user2.test_clean_up(
            portfolio_id=portfolio_id
        )





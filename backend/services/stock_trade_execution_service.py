# backend/services/stock_trade_execution_service.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict, Optional
from fastapi import HTTPException
from domain.portfolio_allocation import PortfolioAllocationTransactionSnapshot, PortfolioAllocationPosition, PortfolioAllocationPositionSnapshot, PortfolioAllocation
from domain.baskt import DeltaPosition
from domain.baskt import BasktPosition
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.order_repository import OrderRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from alpaca.trading.models import Order
import uuid
from math import floor, ceil
from clients.alpaca_broker_client import AlpacaBrokerClient

MARGIN = 0.001
EPS = 1e-6
LOCK_LEASE_SECONDS = 30

class StockTradeExecutionService:
    def __init__(
        self, 
        alpaca_broker_client: AlpacaBrokerClient,
        portfolio_allocation_repository: PortfolioAllocationRepository,
        order_repository: OrderRepository,
        user_trade_lock_repository: UserTradeLockRepository,
    ):
        self.alpaca_broker_client: AlpacaBrokerClient = alpaca_broker_client
        self.portfolio_allocation_repository: PortfolioAllocationRepository = portfolio_allocation_repository
        self.order_repository: OrderRepository = order_repository
        self.user_trade_lock_repository: UserTradeLockRepository = user_trade_lock_repository
    
    def _sort_delta_positions(self, delta_positions: List[DeltaPosition], baskt_positions_dict: Dict[str, BasktPosition]) -> List[DeltaPosition]:
        first_execution_delta_positions = []
        second_execution_delta_positions = []

        for delta_position in delta_positions:
            symbol = delta_position.symbol
            delta_direction = delta_position.direction
            delta_quantity = delta_position.quantity
            if symbol not in baskt_positions_dict:
                second_execution_delta_positions.append(delta_position)
                continue

            curr_direction = baskt_positions_dict[symbol].direction
            curr_quantity = baskt_positions_dict[symbol].filled_quantity

            if abs(curr_quantity - delta_quantity) <= EPS and curr_direction != delta_direction:
                first_execution_delta_positions.append(delta_position)
                continue

            # current net direction is long, delta is short, and delta will make it net short
            if curr_direction == 1 and delta_direction == -1 and delta_quantity > curr_quantity:
                if delta_quantity < curr_quantity * 2:
                    first_execution_delta_positions.append(delta_position)
                else:
                    second_execution_delta_positions.append(delta_position)
                continue

            # current net direction is short, delta is long, and delta will make it net long
            if curr_direction == -1 and delta_direction == 1 and delta_quantity > curr_quantity:
                if delta_quantity < curr_quantity * 2:
                    first_execution_delta_positions.append(delta_position)
                else:
                    second_execution_delta_positions.append(delta_position)
                continue

            # we will stay net long or net short (approaching flat)
            if (
                (curr_direction == 1 and delta_direction == -1 and delta_quantity < curr_quantity)
                or (curr_direction == -1 and delta_direction == 1 and delta_quantity < curr_quantity)
            ):
                first_execution_delta_positions.append(delta_position)
                continue

            second_execution_delta_positions.append(delta_position)


        return first_execution_delta_positions + second_execution_delta_positions

    def _append_close_order(self, order_results: List[Order], symbol: str, alpaca_account_id: str, cognito_user_id: str) -> None:
        order = self.alpaca_broker_client.execute_close_position(symbol=symbol, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        order_results.append(order)

    def _append_buy_order(self, order_results: List[Order], symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str) -> None:
        order = self.alpaca_broker_client.execute_quantity_buy(symbol=symbol, quantity=quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        order_results.append(order)

    def _append_sell_order(self, order_results: List[Order], symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str) -> None:
        order = self.alpaca_broker_client.execute_quantity_sell(symbol=symbol, quantity=quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        order_results.append(order)

    def _append_fractional_sell_orders(self, order_results: List[Order], symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str) -> None:
        order1, order2 = self.alpaca_broker_client.execute_quantity_fractional_sell(symbol=symbol, quantity=quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        order_results.append(order1)
        if order2:
            order_results.append(order2)

    def _plan_orders_for_delta_position(
        self,
        delta_position: DeltaPosition,
        baskt_positions_dict: Dict[str, BasktPosition],
        alpaca_account_id: str, 
        cognito_user_id: str
    ) -> List[Order]:
        symbol = delta_position.symbol
        delta_direction = delta_position.direction
        delta_quantity = delta_position.quantity
        order_results: List[Order] = []

        if symbol not in baskt_positions_dict:
            if delta_direction == 1:
                self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            else:
                self._append_fractional_sell_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        curr_direction = baskt_positions_dict[symbol].direction
        curr_quantity = baskt_positions_dict[symbol].filled_quantity

        # Full direction flip with equal quantity: close current position.
        if abs(curr_quantity - delta_quantity) <= EPS and curr_direction != delta_direction:
            self._append_close_order(order_results=order_results, symbol=symbol, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        # long -> short crossing through flat.
        if curr_direction == 1 and delta_direction == -1 and delta_quantity > curr_quantity:
            self._append_sell_order(order_results=order_results, symbol=symbol, quantity=curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            self._append_fractional_sell_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity - curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        # short -> long crossing through flat.
        if curr_direction == -1 and delta_direction == 1 and delta_quantity > curr_quantity:
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity - curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        # Position reduction while staying long.
        if curr_direction == 1 and delta_direction == -1 and delta_quantity < curr_quantity:
            self._append_sell_order(order_results=order_results, symbol=symbol, quantity=delta_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        # Position reduction while staying short.
        if curr_direction == -1 and delta_direction == 1 and delta_quantity < curr_quantity:
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        # Same-side increase.
        if delta_direction == 1:
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        self._append_fractional_sell_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        return order_results

    def _execute_trades_helper(
            self, 
            delta_positions: List[DeltaPosition], 
            portfolio_id: str, 
            cognito_user_id: str, 
            alpaca_account_id: str,
            transaction_type: str,
            requested_amount: Optional[float]
        ) -> Dict[str, List[Order] | str]:
        """
        Helper function to execute a list of delta positions (buy/sell orders).
        
        Handles complex position transitions including:
        - Long to short conversions
        - Short to long conversions  
        - Partial position adjustments
        - Full position closures
        - New position openings
        
        Args:
            delta_positions: List of DeltaPosition objects specifying symbol, quantity, and direction to trade
            portfolio_id: ID of the portfolio
            cognito_user_id: ID of the user executing trades
            alpaca_account_id: Alpaca account ID that will execute the orders.
            transaction_type: Transaction type label persisted with the
                allocation snapshot.
            
        Returns:
            Dict[str, List[Order] | str]: Transaction ID and list of Alpaca
            orders created for the trade operation.
        """
        # Get all user's positions 
        baskt_positions_dict = self.alpaca_broker_client.get_baskt_positions_dict(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)

        sorted_delta_positions = self._sort_delta_positions(delta_positions=delta_positions, baskt_positions_dict = baskt_positions_dict) # curr_all_positions_dict=curr_all_positions_dict)
        # Execute the delta positions
        order_results: List[Order] = []
        for delta_position in sorted_delta_positions:
            planned_orders = self._plan_orders_for_delta_position(
                delta_position=delta_position,
                baskt_positions_dict=baskt_positions_dict,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id
            )
            order_results.extend(planned_orders)

        portfolio_allocation = PortfolioAllocation(
            portfolio_id=portfolio_id,
            cognito_user_id=cognito_user_id,
            position_history=[],
            transaction_history=[],
            total_filled_amount=0.0

        )
        if self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id):
            portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)


        # New transaction snapshot
        transaction_id = str(uuid.uuid4())
        new_transaction_snapshot = PortfolioAllocationTransactionSnapshot(
            transaction_id=transaction_id,
            created_at=datetime.now(timezone.utc),
            filled_at=datetime.now(timezone.utc),
            requested_amount=requested_amount,
            number_orders=len(order_results),
            transaction_type=transaction_type,
            filled_amount=0.0,
            order_fill_percent=0.0,
            status="QUEUED",
        )

        portfolio_allocation.transaction_history.append(new_transaction_snapshot)

        new_portfolio_allocation = PortfolioAllocation(
            portfolio_id=portfolio_id, 
            cognito_user_id=cognito_user_id, 
            transaction_history=portfolio_allocation.transaction_history,
            position_history=portfolio_allocation.position_history,
            total_filled_amount=portfolio_allocation.total_filled_amount
        )
        self.portfolio_allocation_repository.set_portfolio_allocation(new_portfolio_allocation)

        # Push all the orders to order repo
        self.order_repository.put_orders(
            portfolio_id=portfolio_id, 
            cognito_user_id=cognito_user_id, 
            transaction_id=transaction_id, 
            orders = order_results
        )

        return {
            "transaction_id": transaction_id,
            "orders": order_results
        }


    def execute_close_stock(self, asset_id: str, alpaca_account_id: str, cognito_user_id: str, is_test: bool = False) -> Dict[str, List[Order] | str]:
        """
        Liquidate all positions in a user's portfolio allocation.
        
        Closes all long positions and covers all short positions, effectively
        withdrawing the user's entire allocation from the portfolio.
        
        Args:
            portfolio_id: ID of the portfolio to withdraw from
            cognito_user_id: ID of the user withdrawing
            is_test: If True, skip realizing filled orders (for testing)
            
        Returns:
            List[Order]: List of Alpaca Order objects executed for the withdrawal
        """

        owner_token = str(uuid.uuid4())

        acquired = self.user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=owner_token,
            lease_seconds=LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

        try:
            # Realize filled orders before withdrawing
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=asset_id
                )

            # Get latest allocation history
            curr_portfolio_allocation_position_snapshot = self.portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id
            )
            curr_portfolio_allocation_positions = curr_portfolio_allocation_position_snapshot.positions

            # Build the delta positions
            delta_positions: List[DeltaPosition] = []
            for position in curr_portfolio_allocation_positions:
                delta_positions.append(
                    DeltaPosition(
                        symbol=position.symbol,
                        quantity=position.filled_quantity,
                        direction=position.direction * -1
                    )
                )

            # Execute trades via helper
            execution_trade_response =  self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=asset_id,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_type="CLOSE",
                requested_amount=None,
            )

            return execution_trade_response
        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)


    def execute_sell_to_stock(self, symbol: str, asset_id: str, withdraw_amount: float, alpaca_account_id: str, cognito_user_id: str, is_test: bool = False) -> Dict[str, List[Order] | str]:
        """
        Partially withdraw a specified dollar amount from a user's portfolio allocation.
        
        Proportionally reduces positions across all holdings based on their current
        weights to maintain the portfolio structure while withdrawing the requested amount.
        
        Args:
            portfolio_id: ID of the portfolio to withdraw from
            withdraw_amount: Dollar amount to withdraw from the portfolio
            cognito_user_id: ID of the user withdrawing
            is_test: If True, skip realizing filled orders (for testing)
            
        Returns:
            List[Order]: List of Alpaca Order objects executed for the withdrawal
            
        Raises:
            ValueError: If withdraw amount exceeds portfolio value or no withdrawable positions found
        """

        owner_token = str(uuid.uuid4())
        acquired = self.user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=owner_token,
            lease_seconds=LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

        try:
            # Realize filled orders before withdrawing
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=asset_id
                )

            # Get value of each position and total allocation
            quotes = self.alpaca_broker_client.get_latest_price(symbols=[symbol])

            # Build delta positions
            price = quotes[symbol]
            margin_bid = float(floor(price * (1 - MARGIN) * 100) / 100)
            order_qty = withdraw_amount / margin_bid
            delta_positions = [DeltaPosition(symbol=symbol, quantity=order_qty, direction=-1)]

            # Execute trades via helper
            return self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=asset_id,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_type="SELL",
                requested_amount=withdraw_amount,
            )
        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)
        
    
    def execute_buy_to_stock(self, symbol: str, asset_id: str, deposit_amount: float, cognito_user_id: str, alpaca_account_id: str, is_test: bool = False) -> Dict[str, List[Order] | str]:
        """
        Deposit a specified dollar amount into a user's portfolio allocation.
        
        Allocates the deposit amount across all positions in the latest model portfolio
        snapshot according to their weights, leverage, and direction. Creates market
        orders to establish or increase positions. If all the positions cannot be filled 
        within x seconds, all positions are unwound.
        
        Args:
            portfolio_id: ID of the portfolio to deposit into
            deposit_amount: Dollar amount to deposit into the portfolio
            cognito_user_id: ID of the user making the deposit
            is_test: If True, skip realizing filled orders (for testing)
            
        Returns:
            List[Order]: List of Alpaca Order objects executed for the deposit
            
        Raises:
            ValueError: If model portfolio is not found
        """

        owner_token = str(uuid.uuid4())
        acquired = self.user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=owner_token,
            lease_seconds=LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

        try:
            # Realize filled orders before withdrawing
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=asset_id,
                )

            # Get the quotes of the latest symbols
            quotes = self.alpaca_broker_client.get_latest_price(symbols=[symbol])

            # Create the delta positions that will be executed
            price = quotes[symbol]
            margin_ask = float(ceil(price * (1 + MARGIN) * 100) / 100)
            order_qty = deposit_amount / margin_ask
            delta_positions = [DeltaPosition(symbol=symbol, quantity=order_qty, direction=1)]

            # Execute trades via helper
            trade_execution_response = self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=asset_id,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_type="BUY",
                requested_amount=deposit_amount,
            )
        
            return trade_execution_response
        
        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)

    def _apply_filled_order_to_positions(
        self,
        curr_positions_dict: Dict[str, Dict[str, float | int]],
        curr_allocation_amount: float,
        order_symbol: str,
        order_direction: int,
        order_filled_avg_price: float,
        order_filled_quantity: float,
    ) -> float:
        """Apply one filled order to in-memory position state and allocation amount."""
        if order_symbol not in curr_positions_dict:
            curr_positions_dict[order_symbol] = {
                "filled_avg_price": order_filled_avg_price,
                "filled_quantity": order_filled_quantity,
                "direction": order_direction,
            }
            return curr_allocation_amount + order_filled_avg_price * order_filled_quantity

        pos = curr_positions_dict[order_symbol]
        pos_avg = float(pos["filled_avg_price"])
        pos_qty = float(pos["filled_quantity"])
        pos_dir = int(pos["direction"])

        pos_signed = pos_dir * pos_qty
        ord_signed = order_direction * order_filled_quantity

        # Same-side increase: weighted-average entry and add full notional.
        if pos_signed * ord_signed > 0:
            new_qty = pos_qty + order_filled_quantity
            new_avg = ((pos_qty * pos_avg) + (order_filled_quantity * order_filled_avg_price)) / new_qty
            curr_positions_dict[order_symbol] = {
                "filled_avg_price": new_avg,
                "filled_quantity": new_qty,
                "direction": pos_dir,
            }
            return curr_allocation_amount + order_filled_avg_price * order_filled_quantity

        closed_qty = min(pos_qty, order_filled_quantity)
        curr_allocation_amount -= pos_avg * closed_qty
        remaining = pos_qty - order_filled_quantity

        # Fully closed.
        if abs(remaining) <= EPS:
            del curr_positions_dict[order_symbol]
            return curr_allocation_amount

        # Partial close, same direction remains.
        if remaining > 0:
            curr_positions_dict[order_symbol] = {
                "filled_avg_price": pos_avg,
                "filled_quantity": remaining,
                "direction": pos_dir,
            }
            return curr_allocation_amount

        # Direction flip: excess opens new position at order avg.
        flipped_qty = abs(remaining)
        curr_positions_dict[order_symbol] = {
            "filled_avg_price": order_filled_avg_price,
            "filled_quantity": flipped_qty,
            "direction": order_direction,
        }
        return curr_allocation_amount + order_filled_avg_price * flipped_qty
    
    def realize_filled_orders(self, cognito_user_id: str, alpaca_account_id: str, portfolio_id: str) -> int:
        """
        Reconcile filled orders from Alpaca with the user's portfolio allocation in DynamoDB.
        
        Queries all orders for a user/portfolio, checks their status with Alpaca, and updates
        the portfolio allocation snapshot to reflect filled orders. Handles complex scenarios:
        - Position averaging (multiple buys)
        - Position reductions (partial sells/covers)
        - Position reversals (long to short, short to long)
        - Position closures (complete liquidation)
        - Allocation amount tracking
        
        Args:
            cognito_user_id: ID of the user
            portfolio_id: ID of the portfolio
            
        Returns:
            int: Number of newly filled orders
        """ 

        # If user has not deposit/withdraw in portfolio at all
        if not self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id): 
            return 0
        
        # Getting current portfolio allocation
        portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
            cognito_user_id=cognito_user_id, portfolio_id=portfolio_id
        )

        # Current positions in portfolio (if any)
        curr_positions = portfolio_allocation.position_history[-1].positions if portfolio_allocation.position_history else []
        curr_positions_dict = {
            position.symbol: {"filled_avg_price": position.filled_avg_price, "filled_quantity": position.filled_quantity, "direction": position.direction} 
            for position in curr_positions
        }

        # Current filled amount
        curr_total_filled_amount = portfolio_allocation.total_filled_amount

        # Check all transactions for newly filled orders
        total_newly_filled_orders: List[Order] = []
        has_transaction_updates = False
        for transaction_snapshot in portfolio_allocation.transaction_history:
            # Continue if transaction is fully filled or cancelled
            if transaction_snapshot.status.upper() in ["CANCELLED", "FULLY_FILLED"]:
                continue

            # Each individual transaction
            curr_transaction_id = transaction_snapshot.transaction_id
            curr_number_orders = transaction_snapshot.number_orders
            curr_filled_amount = transaction_snapshot.filled_amount
            curr_order_fill_percent = transaction_snapshot.order_fill_percent

            # unfilled orders from dynamodb
            unfilled_orders = self.order_repository.get_unfilled_orders_by_transaction(
                transaction_id=curr_transaction_id
            )

            # Continue out of transaction if no unfilled orders (everything is filled)
            if len(unfilled_orders)==0:
                transaction_snapshot.filled_at = datetime.now(timezone.utc)
                transaction_snapshot.order_fill_percent = 100.0
                transaction_snapshot.status = "FULLY_FILLED"
                has_transaction_updates = True
                continue

            # Collect newly filled orders from transaction
            newly_filled_orders: List[Order] = []
            for unfilled_order in unfilled_orders:
                order = self.alpaca_broker_client.get_order_by_id(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id, order_id=unfilled_order["order_id"])
                if order.status.name.upper() != "FILLED":
                    continue
                newly_filled_orders.append(order)
            
            if newly_filled_orders:
                # Put newly filled orders in dynamodb
                self.order_repository.put_orders(
                    portfolio_id=portfolio_id,
                    cognito_user_id=cognito_user_id,
                    transaction_id=curr_transaction_id,
                    orders=newly_filled_orders
                )

                # Calculate new transaction attributes
                newly_filled_amount = 0.0
                latest_filled_at = datetime(year=1960, month=1,day=1, tzinfo=timezone.utc)
                for order in newly_filled_orders:
                    newly_filled_amount += float(order.filled_avg_price) * float(order.filled_qty)
                    latest_filled_at = max(latest_filled_at, order.filled_at)

                newly_order_filled_percent = min(100.0, curr_order_fill_percent + ((len(newly_filled_orders) / curr_number_orders)*100.0))
                newly_status = "QUEUED"
                if newly_order_filled_percent >= 100.0:
                    newly_status = "FULLY_FILLED"
                elif 0.0 < newly_order_filled_percent < 100.0:
                    newly_status = "PARTIALLY_FILLED"
                
                # Update transaction with new attributes
                transaction_snapshot.filled_at = latest_filled_at
                transaction_snapshot.filled_amount = curr_filled_amount + newly_filled_amount
                transaction_snapshot.order_fill_percent = newly_order_filled_percent
                transaction_snapshot.status = newly_status
                has_transaction_updates = True


                total_newly_filled_orders.extend(newly_filled_orders)

        if not total_newly_filled_orders:
            if has_transaction_updates:
                self.portfolio_allocation_repository.set_portfolio_allocation(portfolio_allocation=portfolio_allocation)
            return 0

        total_newly_filled_orders.sort(
            key=lambda order: (str(order.filled_at.isoformat()) if getattr(order, "filled_at", None) else "")
        )

        for order in total_newly_filled_orders:
            order_symbol = order.symbol
            order_direction = 1 if str(order.side.name)=="BUY" else -1
            order_filled_avg_price = float(order.filled_avg_price)
            order_filled_quantity = float(order.filled_qty)
            curr_total_filled_amount = self._apply_filled_order_to_positions(
                curr_positions_dict=curr_positions_dict,
                curr_allocation_amount=curr_total_filled_amount,
                order_symbol=order_symbol,
                order_direction=order_direction,
                order_filled_avg_price=order_filled_avg_price,
                order_filled_quantity=order_filled_quantity,
            )

        new_position_snapshot = PortfolioAllocationPositionSnapshot(
            timestamp=datetime.now(timezone.utc),
            positions=[
                PortfolioAllocationPosition(
                    symbol=symbol,
                    filled_avg_price=curr_positions_dict[symbol]["filled_avg_price"],
                    filled_quantity=curr_positions_dict[symbol]["filled_quantity"],
                    direction=curr_positions_dict[symbol]["direction"]
                )
                for symbol in curr_positions_dict
            ]
        )

        portfolio_allocation.position_history.append(new_position_snapshot)
        portfolio_allocation.total_filled_amount = curr_total_filled_amount

        self.portfolio_allocation_repository.set_portfolio_allocation(portfolio_allocation=portfolio_allocation)

        return len(total_newly_filled_orders)










from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict
from fastapi import HTTPException
from domain.portfolio_allocation import PortfolioAllocationPosition, PortfolioAllocationSnapshot, PortfolioAllocation
from domain.model_portfolio import ModelPortfolioSnapshot, ModelPortfolioPosition, DeltaPosition
from backend.domain.baskt import BasktPosition
from repository.model_portfolio_repository import ModelPortfolioRepository
from clients.alpaca_client import AlpacaClient
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.order_repository import OrderRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from alpaca.trading.models import Order
import uuid
from math import floor, ceil

MARGIN = 0.0007
EPS = 1e-7
LOCK_LEASE_SECONDS = 30

class TradeExecutionService:
    def __init__(
        self, 
        alpaca_client: AlpacaClient,
        model_portfolio_repository: ModelPortfolioRepository,
        portfolio_allocation_repository: PortfolioAllocationRepository,
        order_repository: OrderRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
        user_trade_lock_repository: UserTradeLockRepository,

    ):
        self.alpaca_client: AlpacaClient = alpaca_client
        self.model_portfolio_repository: ModelPortfolioRepository = model_portfolio_repository
        self.portfolio_allocation_repository: PortfolioAllocationRepository = portfolio_allocation_repository
        self.order_repository: OrderRepository = order_repository
        self.model_portfolio_follower_repository: ModelPortfolioFollowerRepository = model_portfolio_follower_repository
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


    def _append_buy_order(self, order_results: List[Order], symbol: str, quantity: float) -> None:
        order = self.alpaca_client.execute_quantity_buy(symbol=symbol, quantity=quantity)
        order_results.append(order)

    def _append_sell_order(self, order_results: List[Order], symbol: str, quantity: float) -> None:
        order = self.alpaca_client.execute_quantity_sell(symbol=symbol, quantity=quantity)
        order_results.append(order)

    def _append_fractional_sell_orders(self, order_results: List[Order], symbol: str, quantity: float) -> None:
        order1, order2 = self.alpaca_client.execute_quantity_fractional_sell(symbol=symbol, quantity=quantity)
        order_results.append(order1)
        if order2:
            order_results.append(order2)

    def _plan_orders_for_delta_position(
        self,
        delta_position: DeltaPosition,
        baskt_positions_dict: Dict[str, BasktPosition],
    ) -> List[Order]:
        symbol = delta_position.symbol
        delta_direction = delta_position.direction
        delta_quantity = delta_position.quantity
        order_results: List[Order] = []

        if symbol not in baskt_positions_dict:
            if delta_direction == 1:
                self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity)
            else:
                self._append_fractional_sell_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity)
            return order_results

        curr_direction = baskt_positions_dict[symbol].direction
        curr_quantity = baskt_positions_dict[symbol].filled_quantity

        # Full direction flip with equal quantity: close current position.
        if abs(curr_quantity - delta_quantity) <= EPS and curr_direction != delta_direction:
            if curr_direction == 1:
                self._append_sell_order(order_results=order_results, symbol=symbol, quantity=curr_quantity)
            else:
                self._append_buy_order(order_results=order_results, symbol=symbol, quantity=curr_quantity)
            return order_results

        # long -> short crossing through flat.
        if curr_direction == 1 and delta_direction == -1 and delta_quantity > curr_quantity:
            self._append_sell_order(order_results=order_results, symbol=symbol, quantity=curr_quantity)
            self._append_fractional_sell_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity - curr_quantity)
            return order_results

        # short -> long crossing through flat.
        if curr_direction == -1 and delta_direction == 1 and delta_quantity > curr_quantity:
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=curr_quantity)
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity - curr_quantity)
            return order_results

        # Position reduction while staying long.
        if curr_direction == 1 and delta_direction == -1 and delta_quantity < curr_quantity:
            self._append_sell_order(order_results=order_results, symbol=symbol, quantity=delta_quantity)
            return order_results

        # Position reduction while staying short.
        if curr_direction == -1 and delta_direction == 1 and delta_quantity < curr_quantity:
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity)
            return order_results

        # Same-side increase.
        if delta_direction == 1:
            self._append_buy_order(order_results=order_results, symbol=symbol, quantity=delta_quantity)
            return order_results

        self._append_fractional_sell_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity)
        return order_results

    def _execute_trades_helper(
            self, 
            delta_positions: List[DeltaPosition], 
            portfolio_id: str, 
            user_id: str, 
            portfolio_owner_id: str
        ):
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
            user_id: ID of the user executing trades
            portfolio_owner_id: ID of the portfolio owner
            
        Returns:
            List[Order]: List of Alpaca Order objects that were executed
        """
        # Get all user's positions 
        baskt_positions_dict = self.alpaca_client.get_baskt_positions_dict()

        sorted_delta_positions = self._sort_delta_positions(delta_positions=delta_positions, baskt_positions_dict = baskt_positions_dict) # curr_all_positions_dict=curr_all_positions_dict)
        # Execute the delta positions
        order_results: List[Order] = []
        for delta_position in sorted_delta_positions:
            planned_orders = self._plan_orders_for_delta_position(
                delta_position=delta_position,
                baskt_positions_dict=baskt_positions_dict
            )
            order_results.extend(planned_orders)
        
        transaction_id = str(uuid.uuid4())

        # Create a valid pending snapshot for this transaction (carry forward current positions/allocation).
        try:
            portfolio_allocation_history = self.portfolio_allocation_repository.get_portfolio_allocation_history(user_id=user_id, portfolio_id=portfolio_id)
        except Exception:
            portfolio_allocation_history = []

        prev_snapshot = portfolio_allocation_history[-1] if portfolio_allocation_history else None
        new_portfolio_allocation_snapshot = PortfolioAllocationSnapshot(
            positions=prev_snapshot.positions if prev_snapshot else [],
            timestamp=datetime.now(timezone.utc),
            allocation_amount=prev_snapshot.allocation_amount if prev_snapshot else 0.0,
            transaction_id=transaction_id,
        )
        portfolio_allocation_history.append(new_portfolio_allocation_snapshot)
        new_portfolio_allocation = PortfolioAllocation(portfolio_id=portfolio_id, portfolio_allocation_history=portfolio_allocation_history, user_id=user_id)
        self.portfolio_allocation_repository.set_portfolio_allocation(new_portfolio_allocation)

        # Push all the orders to order repo
        self.order_repository.put_orders(
            portfolio_id=portfolio_id, 
            user_id=user_id, 
            portfolio_owner_id=portfolio_owner_id, 
            transaction_id=transaction_id, 
            orders = order_results
        )
        return order_results
    



    def execute_withdraw_all_from_portfolio(self, portfolio_id: str, portfolio_owner_id: str, user_id: str, is_test: bool = False) -> List[Order]:
        """
        Liquidate all positions in a user's portfolio allocation.
        
        Closes all long positions and covers all short positions, effectively
        withdrawing the user's entire allocation from the portfolio.
        
        Args:
            portfolio_id: ID of the portfolio to withdraw from
            portfolio_owner_id: ID of the portfolio owner
            user_id: ID of the user withdrawing
            is_test: If True, skip realizing filled orders (for testing)
            
        Returns:
            List[Order]: List of Alpaca Order objects executed for the withdrawal
        """

        owner_token = str(uuid.uuid4())

        acquired = self.user_trade_lock_repository.acquire_lock(
            user_id=user_id,
            owner_token=owner_token,
            lease_seconds=LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

        try:
            # Realize filled orders before withdrawing
            if not is_test:
                self.realize_filled_orders(
                    user_id=user_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_id=portfolio_owner_id,
                )

            # Get latest allocation history
            portfolio_allocation_snapshots: List[PortfolioAllocationSnapshot]  = self.portfolio_allocation_repository.get_n_last_portfolio_allocation_snapshots(user_id=user_id, portfolio_id=portfolio_id, n = 1)
            curr_portfolio_allocation_snapshot = portfolio_allocation_snapshots[-1]
            curr_portfolio_allocation_positions = curr_portfolio_allocation_snapshot.positions

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
            orders =  self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=portfolio_id,
                user_id=user_id,
                portfolio_owner_id=portfolio_owner_id
            )

            # Remove follower from model portfolio
            self.model_portfolio_follower_repository.delete_model_portfolio_follower(portfolio_id=portfolio_id, user_id=user_id)

            return orders
        finally:
            self.user_trade_lock_repository.release_lock(user_id=user_id, owner_token=owner_token)


    def execute_withdraw_from_portfolio(self, portfolio_id: str, portfolio_owner_id: str, withdraw_amount: float, user_id: str, is_test: bool = False) -> List[Order]:
        """
        Partially withdraw a specified dollar amount from a user's portfolio allocation.
        
        Proportionally reduces positions across all holdings based on their current
        weights to maintain the portfolio structure while withdrawing the requested amount.
        
        Args:
            portfolio_id: ID of the portfolio to withdraw from
            portfolio_owner_id: ID of the portfolio owner
            withdraw_amount: Dollar amount to withdraw from the portfolio
            user_id: ID of the user withdrawing
            is_test: If True, skip realizing filled orders (for testing)
            
        Returns:
            List[Order]: List of Alpaca Order objects executed for the withdrawal
            
        Raises:
            ValueError: If withdraw amount exceeds portfolio value or no withdrawable positions found
        """

        owner_token = str(uuid.uuid4())
        acquired = self.user_trade_lock_repository.acquire_lock(
            user_id=user_id,
            owner_token=owner_token,
            lease_seconds=LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

        try:
            # Realize filled orders before withdrawing
            if not is_test:
                self.realize_filled_orders(
                    user_id=user_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_id=portfolio_owner_id,
                )

            # Get latest allocation history
            portfolio_allocation_snapshots: List[PortfolioAllocationSnapshot] = self.portfolio_allocation_repository.get_n_last_portfolio_allocation_snapshots(user_id=user_id, portfolio_id=portfolio_id, n=1)
            curr_portfolio_allocation_snapshot = portfolio_allocation_snapshots[-1]

            # Get value of each position and total allocation
            position_weights_dict, total_portfolio_allocation_value, quotes = self.portfolio_allocation_repository.calculate_positions_current_weight(portfolio_allocation_snapshot=curr_portfolio_allocation_snapshot)

            # Validate portfolio allocation value is greater than zero
            if total_portfolio_allocation_value <= 0:
                raise ValueError(f"No withdrawable positions found: portfolio_id={portfolio_id}")

            # Validate the withdraw amount is less than the portfolio allocation value
            if withdraw_amount > total_portfolio_allocation_value:
                raise ValueError(f"Withdraw amount greater than market value: market value={total_portfolio_allocation_value} portfolio_id={portfolio_id}")

            # Build delta positions
            delta_positions: List[DeltaPosition] = []
            curr_portfolio_allocation_positions = curr_portfolio_allocation_snapshot.positions
            for position in curr_portfolio_allocation_positions:
                symbol = position.symbol
                direction = position.direction * -1 # opposite direction because we are withdrawing
                position_allocation = position_weights_dict[symbol] * withdraw_amount
                price = quotes[symbol]
                margin_ask = float(ceil(price * (1 + MARGIN) * 100) / 100)
                margin_bid = float(floor(price * (1 - MARGIN) * 100) / 100)
                order_qty = position_allocation / (margin_ask if direction == 1 else margin_bid)

                delta_positions.append(
                    DeltaPosition(
                        symbol=position.symbol,
                        quantity=order_qty,
                        direction=direction 
                    )
                )

            # Execute trades via helper
            return self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=portfolio_id,
                user_id=user_id,
                portfolio_owner_id=portfolio_owner_id
            )
        finally:
            self.user_trade_lock_repository.release_lock(user_id=user_id, owner_token=owner_token)
        

    def _execute_update_in_portfolio_helper(self, portfolio_id: str, portfolio_owner_id: str, user_id: str, is_test: bool = False) -> List[Order]:

        owner_token = str(uuid.uuid4())
        acquired = self.user_trade_lock_repository.acquire_lock(
            user_id=user_id,
            owner_token=owner_token,
            lease_seconds=LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

        try:
            # Realize filled orders before withdrawing
            if not is_test:
                self.realize_filled_orders(
                    user_id=user_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_id=portfolio_owner_id,
                )

            # Get the two latest model portfolio's position history
            model_portfolio_snapshots: List[ModelPortfolioSnapshot] = self.model_portfolio_repository.get_n_last_model_portfolio_snapshots(portfolio_id=portfolio_id, n=2)
            new_model_portfolio_snapshot = model_portfolio_snapshots[-1]
            curr_model_portfolio_snapshot = model_portfolio_snapshots[-2]

            # Get the new model portfolio snapshot
            new_model_portfolio_positions: List[ModelPortfolioPosition] = new_model_portfolio_snapshot.positions
            new_model_portfolio_symbols = [position.symbol for position in new_model_portfolio_positions]
            new_model_portfolio_positions_dict = {
                position.symbol: position
                for position in new_model_portfolio_positions
            }
            new_model_portfolio_weights_dict, _, new_model_portfolio_quotes = self.model_portfolio_repository.calculate_positions_current_weight(model_portfolio_snapshot=new_model_portfolio_snapshot)

            # Get the current model portfolio snapshot
            curr_model_portfolio_positions: List[ModelPortfolioPosition] = curr_model_portfolio_snapshot.positions
            curr_model_portfolio_symbols = [pos.symbol for pos in curr_model_portfolio_positions]
            curr_model_portfolio_positions_dict = {
                position.symbol: position
                for position in curr_model_portfolio_positions
            }
            curr_model_portfolio_weights_dict, _, curr_model_portfolio_quotes = self.model_portfolio_repository.calculate_positions_current_weight(model_portfolio_snapshot=curr_model_portfolio_snapshot)
            
            # Get latest allocation history
            portfolio_allocation_snapshots: List[PortfolioAllocationSnapshot] = self.portfolio_allocation_repository.get_n_last_portfolio_allocation_snapshots(user_id=user_id, portfolio_id=portfolio_id, n=1)
            curr_portfolio_allocation_snapshot = portfolio_allocation_snapshots[-1]
            curr_allocation_amount = curr_portfolio_allocation_snapshot.allocation_amount
            curr_portfolio_allocation_positions_dict = {
                pos.symbol: pos
                for pos in curr_portfolio_allocation_snapshot.positions
            }

            # Build delta positions
            delta_positions: List[DeltaPosition] = []

            # Create delta positions for positions no longer in model portfolio
            for curr_symbol in curr_model_portfolio_symbols:
                if curr_symbol not in new_model_portfolio_positions_dict:
                    delta_positions.append(DeltaPosition(
                        symbol=curr_symbol,
                        quantity=curr_portfolio_allocation_positions_dict[curr_symbol].filled_quantity,
                        direction=curr_portfolio_allocation_positions_dict[curr_symbol].direction * -1 # opposite because we are selling / covering
                        )
                    )
            
            # Create delta positions for new position in model Portfolio
            for new_position in new_model_portfolio_positions:
                new_symbol = new_position.symbol
                if new_symbol not in curr_model_portfolio_positions_dict:

                    new_weight = new_model_portfolio_weights_dict[new_symbol]
                    new_leverage = new_position.leverage
                    new_direction = new_position.direction
                    price = new_model_portfolio_quotes[new_symbol]

                    margin_ask = float(ceil(price * (1 + MARGIN) * 100) / 100)
                    margin_bid = float(floor(price * (1 - MARGIN) * 100) / 100)

                    denom = margin_ask if new_direction == 1 else margin_bid
                    order_qty = abs(curr_allocation_amount * new_weight * new_leverage) / denom

                    if order_qty <= 0:
                        continue

                    delta_positions.append(
                        DeltaPosition(
                            symbol= new_symbol,
                            quantity= order_qty,
                            direction = new_direction
                        )
                    )

            # Create delta positions for positions that were in prev and curr model portfolios
            for symbol in list(set(curr_model_portfolio_symbols).intersection(set(new_model_portfolio_symbols))):
                new_pos = new_model_portfolio_positions_dict[symbol]
                curr_pos = curr_model_portfolio_positions_dict[symbol]

                new_net_dollars = 0.0
                curr_net_dollars = 0.0

                if new_pos:
                    new_net_dollars = new_model_portfolio_weights_dict[new_pos.symbol] * float(curr_allocation_amount) * float(new_pos.leverage) * int(new_pos.direction)
                if curr_pos:
                    curr_net_dollars = curr_model_portfolio_weights_dict[curr_pos.symbol] * float(curr_allocation_amount) * float(curr_pos.leverage) * int(curr_pos.direction)

                delta_net_dollars = new_net_dollars - curr_net_dollars

                # Skip tiny changes
                if abs(delta_net_dollars) <= EPS:
                    continue

                price = curr_model_portfolio_quotes[symbol]
                if not price:
                    continue

                margin_ask = float(ceil(price * (1 + MARGIN) * 100) / 100)
                margin_bid = float(floor(price * (1 - MARGIN) * 100) / 100)

                delta_direction = 1 if delta_net_dollars > 0 else -1
                denom = margin_ask if delta_direction == 1 else margin_bid
                order_qty = abs(delta_net_dollars) / denom if denom > 0 else 0.0

                if order_qty <= 0:
                    continue

                delta_positions.append(
                    DeltaPosition(
                        symbol=symbol,
                        quantity=order_qty,
                        direction=delta_direction,
                    )
                )

            return self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=portfolio_id,
                user_id=user_id,
                portfolio_owner_id=portfolio_owner_id
            )
        finally:
            self.user_trade_lock_repository.release_lock(user_id=user_id, owner_token=owner_token)
    
    def execute_update_in_portfolio(self, portfolio_id: str, portfolio_owner_id: str, is_test: bool = False) -> Dict[str, List[Order]]:
        """
        Rebalance a user's portfolio allocation to match an updated model portfolio.
        
        Compares the previous and current model portfolio snapshots to determine:
        - Positions to close (removed from model)
        - Positions to open (added to model)
        - Positions to adjust (weight/direction changed)
        
        Executes trades to align the user's actual holdings with the updated model
        while maintaining their current allocation amount.
        
        Args:
            portfolio_id: ID of the portfolio to update
            portfolio_owner_id: ID of the portfolio owner
            is_test: If True, skip realizing filled orders (for testing)
            
        Returns:
            List[Order]: List of Alpaca Order objects executed for the rebalance
        """

        model_portfolio_followers = self.model_portfolio_follower_repository.get_model_portfolio_followers(portfolio_id=portfolio_id)
        all_update_orders = {}

        for follower_id in model_portfolio_followers:
            all_update_orders[follower_id] = self._execute_update_in_portfolio_helper(portfolio_id=portfolio_id, portfolio_owner_id=portfolio_owner_id, user_id=follower_id, is_test=is_test)

        return all_update_orders

    
    def execute_deposit_to_portfolio(self, portfolio_id: str, portfolio_owner_id: str, deposit_amount: float, user_id: str, is_test: bool = False) -> List[Order]:
        """
        Deposit a specified dollar amount into a user's portfolio allocation.
        
        Allocates the deposit amount across all positions in the latest model portfolio
        snapshot according to their weights, leverage, and direction. Creates market
        orders to establish or increase positions. If all the positions cannot be filled 
        within x seconds, all positions are unwound.
        
        Args:
            portfolio_id: ID of the portfolio to deposit into
            portfolio_owner_id: ID of the portfolio owner
            deposit_amount: Dollar amount to deposit into the portfolio
            user_id: ID of the user making the deposit
            is_test: If True, skip realizing filled orders (for testing)
            
        Returns:
            List[Order]: List of Alpaca Order objects executed for the deposit
            
        Raises:
            ValueError: If model portfolio is not found
        """

        owner_token = str(uuid.uuid4())
        acquired = self.user_trade_lock_repository.acquire_lock(
            user_id=user_id,
            owner_token=owner_token,
            lease_seconds=LOCK_LEASE_SECONDS,
        )
        if not acquired:
            raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

        try:
            # Realize filled orders before withdrawing
            if not is_test:
                self.realize_filled_orders(
                    user_id=user_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_id=portfolio_owner_id,
                )

            # Get the current model portfolio snapshot
            model_portfolio_snapshots = self.model_portfolio_repository.get_n_last_model_portfolio_snapshots(portfolio_id=portfolio_id, n=1)
            curr_model_portfolio_snapshot = model_portfolio_snapshots[-1]
            # Get the latest positions of the model portfolio
            curr_model_portfolio_positions: List[ModelPortfolioPosition]  = curr_model_portfolio_snapshot.positions
            # Get the symbols of the latest positions
            portfolio_symbols = [position.symbol for position in curr_model_portfolio_positions]
            # Get the quotes of the latest symbols
            quotes = self.alpaca_client.get_latest_price(portfolio_symbols)
            # Get the current weight of positions
            model_portfolio_position_value_dict,_,_ = self.model_portfolio_repository.calculate_positions_current_weight(model_portfolio_snapshot=curr_model_portfolio_snapshot)

            # Create the delta positions that will be executed
            delta_positions: List[DeltaPosition] = []
            for position in curr_model_portfolio_positions:
                symbol = position.symbol
                order_direction = position.direction
                position_allocation = model_portfolio_position_value_dict[symbol] * deposit_amount * position.leverage
                price = quotes[symbol]
                margin_ask = float(ceil(price * (1 + MARGIN) * 100) / 100)
                margin_bid = float(floor(price * (1 - MARGIN) * 100) / 100)
                order_qty = position_allocation / (margin_ask if order_direction == 1 else margin_bid)
                delta_positions.append(
                    DeltaPosition(
                        symbol=position.symbol,
                        quantity=order_qty,
                        direction=order_direction
                    )
                )

            # Execute trades via helper
            orders =  self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=portfolio_id,
                user_id=user_id,
                portfolio_owner_id=portfolio_owner_id
            )
        
            # Add user as follower to model portfolio
            self.model_portfolio_follower_repository.put_model_portfolio_follower(user_id=user_id, portfolio_id=portfolio_id, portfolio_owner_id=portfolio_owner_id)

            return orders
        finally:
            self.user_trade_lock_repository.release_lock(user_id=user_id, owner_token=owner_token)

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
    
    def realize_filled_orders(self, user_id: str, portfolio_id: str, portfolio_owner_id: str) -> int:
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
            user_id: ID of the user
            portfolio_id: ID of the portfolio
            
        Returns:
            int: Number of newly filled orders
        """ 
        
        portfolio_allocation_snapshots = self.portfolio_allocation_repository.get_portfolio_allocation_history(user_id=user_id, portfolio_id=portfolio_id)
        curr_portfolio_allocation_snapshot = portfolio_allocation_snapshots[-1]
        curr_transaction_id = curr_portfolio_allocation_snapshot.transaction_id
        curr_positions = curr_portfolio_allocation_snapshot.positions if curr_portfolio_allocation_snapshot.positions else []
        curr_allocation_amount = curr_portfolio_allocation_snapshot.allocation_amount if curr_portfolio_allocation_snapshot.allocation_amount else 0
        curr_positions_dict = {
            pos.symbol: 
                {"filled_avg_price": pos.filled_avg_price, "filled_quantity": pos.filled_quantity, "direction": pos.direction} 
            for pos in curr_positions
        }

        unfilled_orders = self.order_repository.get_unfilled_orders_by_transaction(transaction_id=curr_transaction_id)
        if len(unfilled_orders) == 0: return 0
        newly_filled_orders: List[Order] = []
        for unfilled_order in unfilled_orders:
            order = self.alpaca_client.get_order_by_id(unfilled_order["order_id"])
            if str(order.status.name) != "FILLED": continue
            newly_filled_orders.append(order)

        # apply fills in chronological order, not DynamoDB query order.
        newly_filled_orders.sort(
            key=lambda order: (
                str(order.filled_at.isoformat()) if getattr(order, "filled_at", None) else ""
            )
        )

        for order in newly_filled_orders:
            order_symbol = order.symbol

            order_direction = 1 if str(order.side.name)=="BUY" else -1
            order_filled_avg_price = float(order.filled_avg_price)
            order_filled_quantity = float(order.filled_qty)
            curr_allocation_amount = self._apply_filled_order_to_positions(
                curr_positions_dict=curr_positions_dict,
                curr_allocation_amount=curr_allocation_amount,
                order_symbol=order_symbol,
                order_direction=order_direction,
                order_filled_avg_price=order_filled_avg_price,
                order_filled_quantity=order_filled_quantity,
            )

        if newly_filled_orders:

            self.order_repository.put_orders(
                portfolio_id=portfolio_id, 
                user_id=user_id, 
                portfolio_owner_id=portfolio_owner_id, 
                transaction_id=curr_transaction_id,
                orders=newly_filled_orders
            )

            updated_portfolio_allocation_snapshot = PortfolioAllocationSnapshot(
                positions=[
                    PortfolioAllocationPosition(
                        filled_avg_price=curr_positions_dict[symbol]["filled_avg_price"],
                        symbol=symbol, filled_quantity=curr_positions_dict[symbol]["filled_quantity"], 
                        direction=curr_positions_dict[symbol]["direction"]
                    ) 
                    for symbol in curr_positions_dict
                ],
                timestamp=datetime.now(timezone.utc),
                allocation_amount=curr_allocation_amount,
                transaction_id=curr_transaction_id
            )
            portfolio_allocation_snapshots[-1] = updated_portfolio_allocation_snapshot

            updated_portfolio_allocation = PortfolioAllocation(
                portfolio_id=portfolio_id,
                portfolio_allocation_history=portfolio_allocation_snapshots,
                user_id=user_id
            )
            self.portfolio_allocation_repository.set_portfolio_allocation(portfolio_allocation=updated_portfolio_allocation)
            

        return len(newly_filled_orders)
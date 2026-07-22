
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from domain.portfolio_allocation_domain import PortfolioAllocationTransactionSnapshot, PortfolioAllocationPosition, PortfolioAllocationPositionSnapshot, PortfolioAllocation
from domain.baskt_domain import BasktPosition, DeltaPosition
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.order_repository import OrderRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from alpaca.trading.models import Order
import uuid
from math import floor, ceil
from clients.alpaca_broker_client import AlpacaBrokerClient
from copy import deepcopy
MARGIN = 0.000
EPS = 1e-6
LOCK_LEASE_SECONDS = 30

MINIMUM_PORTFOLIO_BALANCE = 1.0
MINIMUM_STOCK_BALANCE = 1.0

TRADE_AMOUNT_MIN = 10.0

class TradeExecutionInternalServerError(Exception):
	def __init__(self, message: str, code: str = "TRADE_EXECUTION_SERVICE_ERROR") -> None:
		"""
		Initialize an Trade Execution service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class TradeExecutionService:
    def __init__(
        self,
        alpaca_broker_client: AlpacaBrokerClient,
        model_portfolio_repository: ModelPortfolioRepository,
        portfolio_allocation_repository: PortfolioAllocationRepository,
        order_repository: OrderRepository,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
        user_trade_lock_repository: UserTradeLockRepository
    ):
        self.alpaca_broker_client: AlpacaBrokerClient = alpaca_broker_client
        self.model_portfolio_repository: ModelPortfolioRepository = model_portfolio_repository
        self.portfolio_allocation_repository: PortfolioAllocationRepository = portfolio_allocation_repository
        self.order_repository: OrderRepository = order_repository
        self.model_portfolio_follower_repository: ModelPortfolioFollowerRepository = model_portfolio_follower_repository
        self.user_trade_lock_repository: UserTradeLockRepository = user_trade_lock_repository


    # Shared execution and reconciliation helpers

    def _validate_amount(self, amount: float) -> None:
        """Validate the minimum numeric amount accepted for trade execution."""
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise TradeExecutionInternalServerError(
                message="Trade execution amount must be numeric.",
                code="TRADE_EXECUTION_AMOUNT_INVALID",
            )
        if amount < TRADE_AMOUNT_MIN:
            raise TradeExecutionInternalServerError(
                message=f"Trade execution amount must be at least ${TRADE_AMOUNT_MIN:.2f}.",
                code="TRADE_EXECUTION_AMOUNT_INVALID",
            )

    @staticmethod
    def _find_transaction(
        portfolio_allocation: PortfolioAllocation,
        transaction_id: str,
    ) -> PortfolioAllocationTransactionSnapshot:
        """Return the queued transaction that owns an execution request."""
        for transaction in portfolio_allocation.transaction_history:
            if transaction.transaction_id == transaction_id:
                return transaction
        raise TradeExecutionInternalServerError(
            message=f"Queued transaction '{transaction_id}' was not found.",
            code="TRADE_EXECUTION_TRANSACTION_NOT_FOUND",
        )

    def _mark_transaction_failed(
        self,
        *,
        cognito_user_id: str,
        portfolio_id: str,
        transaction_id: str,
        error: Exception,
    ) -> bool:
        """Persist a failed execution state without creating a new transaction."""
        allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
        )
        transaction = self._find_transaction(allocation, transaction_id)
        if transaction.status.upper() not in {"QUEUED", "PROCESSING"}:
            return
        transaction.status = "FAILED"
        transaction.updated_at = datetime.now(timezone.utc)
        transaction.status_explanation = str(error) or "Trade execution failed."
        self.portfolio_allocation_repository.set_portfolio_allocation(
            portfolio_allocation=allocation
        )

    @staticmethod
    def _project_stock_equity(
        *,
        current_equity: float,
        current_direction: Optional[int],
        amount: float,
        trade_direction: int,
    ) -> float:
        """Project absolute stock exposure after a dollar buy or sell."""
        if current_direction is None or current_direction == trade_direction:
            return current_equity + amount
        return abs(current_equity - amount)

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


    def _calculate_transaction_filled_amount(
        self,
        transaction_orders: List[Dict[str, Any]],
    ) -> float:
        """Calculate net executed notional for a transaction by symbol.

        Offsetting broker orders are netted before taking absolute values. This
        keeps multi-order fractional sells from reporting gross turnover as the
        amount filled.

        Args:
            transaction_orders: Cached order rows for one transaction, updated
                in memory with any fills discovered during reconciliation.

        Returns:
            float: Absolute net filled notional summed across symbols.

        Raises:
            TradeExecutionInternalServerError: If a filled order has an
                unsupported side or lacks its filled price or quantity.
        """
        net_notional_by_symbol: Dict[str, float] = {}
        for transaction_order in transaction_orders:
            if str(transaction_order.get("status", "")).upper() != "FILLED":
                continue
            symbol = str(transaction_order["symbol"])
            side = str(transaction_order["side"]).upper()
            if side == "BUY":
                side_multiplier = 1.0
            elif side == "SELL":
                side_multiplier = -1.0
            else:
                raise TradeExecutionInternalServerError(
                    message=(
                        f"Filled order '{transaction_order['order_id']}' has "
                        f"unsupported side '{side}'."
                    ),
                    code="TRADE_EXECUTION_ORDER_SIDE_INVALID",
                )
            filled_avg_price = transaction_order.get("filled_avg_price")
            filled_qty = transaction_order.get("filled_qty")
            if filled_avg_price is None or filled_qty is None:
                raise TradeExecutionInternalServerError(
                    message=(
                        f"Filled order '{transaction_order['order_id']}' is "
                        "missing filled price or quantity."
                    ),
                    code="TRADE_EXECUTION_ORDER_FILL_DATA_MISSING",
                )
            net_notional_by_symbol[symbol] = (
                net_notional_by_symbol.get(symbol, 0.0)
                + side_multiplier
                * float(filled_avg_price)
                * float(filled_qty)
            )
        return sum(abs(net_notional) for net_notional in net_notional_by_symbol.values())

    def realize_filled_orders(
        self,
        cognito_user_id: str,
        alpaca_account_id: str,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: Optional[str] = None,
        lock_already_acquired: bool = False,
    ) -> int:
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

        owner_token: Optional[str] = None
        try:
            if not lock_already_acquired:
                owner_token = str(uuid.uuid4())
                acquired = self.user_trade_lock_repository.acquire_lock(
                    cognito_user_id=cognito_user_id,
                    owner_token=owner_token,
                    lease_seconds=LOCK_LEASE_SECONDS,
                )
                if not acquired:
                    raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

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
            curr_total_filled_amount = portfolio_allocation.total_cost_basis

            # Only submitted broker orders can be reconciled. QUEUED transactions
            # are waiting for this service to create their orders.
            total_newly_filled_orders: List[Order] = []
            has_transaction_updates = False
            for transaction_snapshot in portfolio_allocation.transaction_history:
                if transaction_snapshot.status.upper() not in {"ORDERED", "PARTIALLY_FILLED"}:
                    continue

                # Each individual transaction
                curr_transaction_id = transaction_snapshot.transaction_id
                curr_number_orders = transaction_snapshot.number_orders or 0
                curr_order_fill_percent = transaction_snapshot.order_fill_percent or 0.0

                # Load this transaction's orders once and reuse the rows while
                # reconciling broker status and calculating filled amount.
                transaction_orders = self.order_repository.get_orders_by_transaction(
                    transaction_id=curr_transaction_id
                )
                unfilled_orders = [
                    order
                    for order in transaction_orders
                    if str(order.get("status", "")).upper() != "FILLED"
                ]

                # Continue out of transaction if no unfilled orders (everything is filled)
                if len(unfilled_orders)==0:
                    transaction_snapshot.filled_at = datetime.now(timezone.utc)
                    transaction_snapshot.updated_at = transaction_snapshot.filled_at
                    transaction_snapshot.cost_basis = self._calculate_transaction_filled_amount(
                        transaction_orders=transaction_orders
                    )
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
                    unfilled_order.update(
                        {
                            "status": "FILLED",
                            "symbol": str(order.symbol),
                            "side": str(order.side.name),
                            "filled_avg_price": order.filled_avg_price,
                            "filled_qty": order.filled_qty,
                        }
                    )
                    newly_filled_orders.append(order)

                if newly_filled_orders:
                    # Put newly filled orders in dynamodb
                    self.order_repository.put_orders(
                        portfolio_id=portfolio_id,
                        cognito_user_id=cognito_user_id,
                        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                        transaction_id=curr_transaction_id,
                        orders=newly_filled_orders
                    )

                    # Calculate new transaction attributes
                    latest_filled_at = datetime(year=1960, month=1,day=1, tzinfo=timezone.utc)
                    for order in newly_filled_orders:
                        latest_filled_at = max(latest_filled_at, order.filled_at)

                    # Recompute from every filled order in the transaction so
                    # offsetting legs remain correct across separate polls.
                    # Fractional shorts, for example, sell a whole share and
                    # buy back the excess; grossing both legs inflates the
                    # amount even though only their net changes the position.
                    transaction_filled_amount = self._calculate_transaction_filled_amount(
                        transaction_orders=transaction_orders
                    )

                    if curr_number_orders <= 0:
                        raise TradeExecutionInternalServerError(
                            message=(
                                f"Transaction '{curr_transaction_id}' has orders but its "
                                "number_orders value is not positive."
                            ),
                            code="TRADE_EXECUTION_TRANSACTION_ORDER_COUNT_INVALID",
                        )
                    newly_order_filled_percent = min(100.0, curr_order_fill_percent + ((len(newly_filled_orders) / curr_number_orders)*100.0))
                    newly_status = "ORDERED"
                    if newly_order_filled_percent >= 100.0:
                        newly_status = "FULLY_FILLED"
                    elif 0.0 < newly_order_filled_percent < 100.0:
                        newly_status = "PARTIALLY_FILLED"

                    # Update transaction with new attributes
                    transaction_snapshot.filled_at = latest_filled_at
                    transaction_snapshot.updated_at = datetime.now(timezone.utc)
                    transaction_snapshot.cost_basis = transaction_filled_amount
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
            portfolio_allocation.total_cost_basis = curr_total_filled_amount

            self.portfolio_allocation_repository.set_portfolio_allocation(portfolio_allocation=portfolio_allocation)

            return len(total_newly_filled_orders)

        finally:
            if owner_token is not None:
                self.user_trade_lock_repository.release_lock(
                    cognito_user_id=cognito_user_id,
                    owner_token=owner_token,
                )


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

    def _append_long_to_short_sell_orders(self, order_results: List[Order], symbol: str, quantity: float, curr_quantity: float, alpaca_account_id: str, cognito_user_id: str) -> None:
        orders = self.alpaca_broker_client.execute_long_to_short_sell(symbol=symbol, quantity=quantity, curr_quantity=curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        order_results.extend(orders)

    def _append_short_to_long_buy_orders(self, order_results: List[Order], symbol: str, quantity: float, curr_quantity: float, alpaca_account_id: str, cognito_user_id: str) -> None:
        orders = self.alpaca_broker_client.execute_short_to_long_buy(symbol=symbol, quantity=quantity, curr_quantity=curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        order_results.extend(orders)


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
            self._append_long_to_short_sell_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity, curr_quantity=curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            return order_results

        # short -> long crossing through flat.
        if curr_direction == -1 and delta_direction == 1 and delta_quantity > curr_quantity:
            self._append_short_to_long_buy_orders(order_results=order_results, symbol=symbol, quantity=delta_quantity, curr_quantity=curr_quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
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
        transaction_id: str,
        portfolio_owner_cognito_user_id: Optional[str],
        model_portfolio_snapshot_id: Optional[str] = None
    ) -> bool:
        """Submit planned orders and update the transaction created by the queue."""
        portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
        )
        transaction = self._find_transaction(portfolio_allocation, transaction_id)

        # SQS is at-least-once. A message that already advanced beyond QUEUED
        # must not submit the same broker orders again.
        if transaction.status.upper() != "QUEUED":
            return False

        transaction.status = "PROCESSING"
        transaction.updated_at = datetime.now(timezone.utc)
        transaction.status_explanation = None
        self.portfolio_allocation_repository.set_portfolio_allocation(
            portfolio_allocation=portfolio_allocation
        )

        baskt_positions_dict = self.alpaca_broker_client.get_baskt_positions_dict(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        # Execute the delta positions
        sorted_delta_positions = self._sort_delta_positions(delta_positions=delta_positions, baskt_positions_dict = baskt_positions_dict)
        order_results: List[Order] = []
        for delta_position in sorted_delta_positions:
            planned_orders = self._plan_orders_for_delta_position(
                delta_position=delta_position,
                baskt_positions_dict=baskt_positions_dict,
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id
            )
            order_results.extend(planned_orders)

        if order_results:
            self.order_repository.put_orders(
                portfolio_id=portfolio_id,
                cognito_user_id=cognito_user_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                transaction_id=transaction_id,
                orders=order_results,
            )

        transaction.updated_at = datetime.now(timezone.utc)
        transaction.number_orders = len(order_results)
        transaction.cost_basis = 0.0
        transaction.order_fill_percent = 100.0 if not order_results else 0.0
        transaction.status = "FULLY_FILLED" if not order_results else "ORDERED"
        transaction.model_portfolio_snapshot_id = model_portfolio_snapshot_id
        if not order_results:
            transaction.filled_at = transaction.updated_at
        self.portfolio_allocation_repository.set_portfolio_allocation(
            portfolio_allocation=portfolio_allocation
        )
        return True


    # Model portfolio execution
    def execute_withdraw_all_from_portfolio(
        self,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        transaction_id: str,
        alpaca_account_id: str,
        cognito_user_id: str,
        is_test: bool = False,
    ) -> None:
        """
        Liquidate all positions in a user's portfolio allocation.

        Closes all long positions and covers all short positions, effectively
        withdrawing the user's entire allocation from the portfolio.

        Args:
            portfolio_id: ID of the portfolio to withdraw from
            portfolio_owner_cognito_user_id: ID of the portfolio owner
            cognito_user_id: ID of the user withdrawing
            is_test: If True, skip realizing filled orders (for testing)

        Returns:
            List[Order]: List of Alpaca Order objects executed for the withdrawal
        """

        owner_token = str(uuid.uuid4())
        try:
            acquired = self.user_trade_lock_repository.acquire_lock(
                cognito_user_id=cognito_user_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS,
            )
            if not acquired:
                raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

            # Reconcile previously submitted orders before this execution.
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                    lock_already_acquired=True,
                )

            # Get current positions to close out
            curr_portfolio_allocation_position_snapshot = self.portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
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
            executed = self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=portfolio_id,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_id=transaction_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            )

            if executed:
                self.model_portfolio_follower_repository.delete_model_portfolio_follower(
                    portfolio_id=portfolio_id,
                    cognito_user_id=cognito_user_id,
                )

            return None
        except Exception as error:
            self._mark_transaction_failed(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                transaction_id=transaction_id,
                error=error,
            )
            raise TradeExecutionInternalServerError(
                message=(
                    f"Failed to execute withdraw-all for portfolio '{portfolio_id}', "
                    f"user '{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_PORTFOLIO_WITHDRAW_ALL_FAILED",
            ) from error
        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)


    def execute_withdraw_from_portfolio(
        self,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        transaction_id: str,
        withdraw_amount: float,
        alpaca_account_id: str,
        cognito_user_id: str,
        is_test: bool = False
    ) -> None:
        """
        Partially withdraw a specified dollar amount from a user's portfolio allocation.

        Proportionally reduces positions across all holdings based on their current
        weights to maintain the portfolio structure while withdrawing the requested amount.

        Args:
            portfolio_id: ID of the portfolio to withdraw from
            portfolio_owner_cognito_user_id: ID of the portfolio owner
            withdraw_amount: Dollar amount to withdraw from the portfolio
            cognito_user_id: ID of the user withdrawing
            is_test: If True, skip realizing filled orders (for testing)

        Returns:
            List[Order]: List of Alpaca Order objects executed for the withdrawal

        Raises:
            ValueError: If withdraw amount exceeds portfolio value or no withdrawable positions found
        """

        owner_token = str(uuid.uuid4())
        try:
            self._validate_amount(withdraw_amount)
            acquired = self.user_trade_lock_repository.acquire_lock(
                cognito_user_id=cognito_user_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS,
            )
            if not acquired:
                raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

            # Reconcile previously submitted orders before this execution.
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                    lock_already_acquired=True,
                )

            # Get current portfolio allocation equity and portfolio allocation position weight
            curr_portfolio_allocation_position_snapshot = self.portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(
                cognito_user_id=cognito_user_id, portfolio_id=portfolio_id
            )
            position_weights_dict, portfolio_allocation_equity, quotes = self.portfolio_allocation_repository.calculate_positions_current_weight(
                portfolio_allocation_position_snapshot=curr_portfolio_allocation_position_snapshot
            )

            # Valid portfolio allocation equity is greater than zero
            if portfolio_allocation_equity < 0.0:
                raise ValueError(f"Portfolio allocation equity is less than 0 for portfolio {portfolio_id} for cognito user {cognito_user_id} and alpaca account {alpaca_account_id}")

            # Validate the withdraw amount is less than the portfolio allocation equity
            if withdraw_amount > portfolio_allocation_equity:
                raise ValueError(f"Withdraw amount greater than market value: market value={portfolio_allocation_equity} portfolio_id={portfolio_id}")

            # Validate account minimum is met
            if portfolio_allocation_equity - withdraw_amount < MINIMUM_PORTFOLIO_BALANCE:
                raise ValueError(f"Minimum balance is {MINIMUM_PORTFOLIO_BALANCE} dollars. Withdraw results in {portfolio_allocation_equity - withdraw_amount}. Withdraw all if needed.")

            # Build delta positions
            delta_positions: List[DeltaPosition] = []
            for position in curr_portfolio_allocation_position_snapshot.positions:
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
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_id=transaction_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            )
        except Exception as e:
            self._mark_transaction_failed(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                transaction_id=transaction_id,
                error=e,
            )

            raise TradeExecutionInternalServerError(
                message=(
                    f"Failed to execute portfolio withdrawal for portfolio '{portfolio_id}', "
                    f"user '{cognito_user_id}', and account '{alpaca_account_id}': {e}"
                ),
                code="TRADE_EXECUTION_PORTFOLIO_WITHDRAWAL_FAILED",
            ) from e

        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)

    def execute_update_in_portfolio(
        self,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
        model_portfolio_snapshot_id: str,
        transaction_id: str,
        is_test: bool = False,
        lock_already_acquired: bool = False,
    ) -> bool:

        owner_token: Optional[str] = None

        try:
            if not lock_already_acquired:
                owner_token = str(uuid.uuid4())
                acquired = self.user_trade_lock_repository.acquire_lock(
                    cognito_user_id=cognito_user_id,
                    owner_token=owner_token,
                    lease_seconds=LOCK_LEASE_SECONDS,
                )
                if not acquired:
                    raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

            # Reconcile previously submitted orders before this execution.
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                    lock_already_acquired=True,
                )

            allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            update_transaction = self._find_transaction(allocation, transaction_id)
            if update_transaction.transaction_type.upper() != "UPDATE":
                raise TradeExecutionInternalServerError(
                    message=f"Transaction '{transaction_id}' is not an UPDATE transaction.",
                    code="TRADE_EXECUTION_UPDATE_TRANSACTION_TYPE_INVALID",
                )
            if update_transaction.model_portfolio_snapshot_id != model_portfolio_snapshot_id:
                raise TradeExecutionInternalServerError(
                    message=(
                        f"Transaction '{transaction_id}' targets model snapshot "
                        f"'{update_transaction.model_portfolio_snapshot_id}', not "
                        f"'{model_portfolio_snapshot_id}'."
                    ),
                    code="TRADE_EXECUTION_UPDATE_SNAPSHOT_MISMATCH",
                )

            # Load the exact model snapshot named by the queued transaction.
            model_portfolio_snapshots = self.model_portfolio_repository.get_position_history(
                portfolio_id=portfolio_id
            )
            new_model_portfolio_snapshot = None
            for snap in model_portfolio_snapshots:
                if snap.snapshot_id == model_portfolio_snapshot_id:
                    new_model_portfolio_snapshot = deepcopy(snap)
                    break
            if not new_model_portfolio_snapshot:
                raise TradeExecutionInternalServerError(
                    message=f"Model portfolio snapshot id {model_portfolio_snapshot_id} not found in model portfolio {portfolio_id}",
                    code="TRADE_EXECUTION_UPDATE_FAILED"
                )
            new_model_portfolio_positions = new_model_portfolio_snapshot.positions
            new_model_portfolio_symbols = [position.symbol for position in new_model_portfolio_positions]
            new_model_portfolio_positions_dict = {
                position.symbol: position
                for position in new_model_portfolio_positions
            }
            new_model_portfolio_weights_dict, _, new_model_portfolio_quotes = self.model_portfolio_repository.calculate_positions_current_weight(model_portfolio_snapshot=new_model_portfolio_snapshot)

            # Get current portfolio allocation positions
            portfolio_allocation_position_snapshot = self.portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id
            )
            portfolio_allocation_positions = portfolio_allocation_position_snapshot.positions
            curr_portfolio_allocation_symbols = [position.symbol for position in portfolio_allocation_positions]
            curr_portfolio_allocation_positions_dict = {
                pos.symbol: pos
                for pos in portfolio_allocation_positions
            }
            curr_portfolio_allocation_weights_dict, _, _ = self.portfolio_allocation_repository.calculate_positions_current_weight(portfolio_allocation_position_snapshot=portfolio_allocation_position_snapshot)

            # Build delta positions
            delta_positions: List[DeltaPosition] = []

            # Create delta positions for positions no longer in model portfolio
            for curr_symbol in curr_portfolio_allocation_positions_dict:
                if curr_symbol not in new_model_portfolio_positions_dict:
                    delta_positions.append(
                        DeltaPosition(
                            symbol=curr_symbol,
                            quantity=curr_portfolio_allocation_positions_dict[curr_symbol].filled_quantity,
                            direction=curr_portfolio_allocation_positions_dict[curr_symbol].direction * -1 # opposite because we are selling / covering
                        )
                    )

            curr_allocation_amount = self.portfolio_allocation_repository.get_portfolio_allocation_total_cost_basis(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)

            # Create delta positions for new position in model Portfolio
            for new_position in new_model_portfolio_positions:
                new_symbol = new_position.symbol
                if new_symbol not in curr_portfolio_allocation_positions_dict:

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

            # Create delta positions for positions that were in current portfolio allocation and new model portfolio snapshot
            for symbol in list(set(curr_portfolio_allocation_symbols).intersection(set(new_model_portfolio_symbols))):
                new_pos = new_model_portfolio_positions_dict[symbol]
                curr_pos = curr_portfolio_allocation_positions_dict[symbol]

                new_net_dollars = 0.0
                curr_net_dollars = 0.0

                if new_pos:
                    new_net_dollars = new_model_portfolio_weights_dict[new_pos.symbol] * float(curr_allocation_amount) * float(new_pos.leverage) * int(new_pos.direction)
                if curr_pos:
                    curr_net_dollars = (
                        curr_portfolio_allocation_weights_dict[curr_pos.symbol]
                        * float(curr_allocation_amount)
                        * int(curr_pos.direction)
                    )

                delta_net_dollars = new_net_dollars - curr_net_dollars

                # Skip tiny changes
                if abs(delta_net_dollars) <= EPS:
                    continue

                price = new_model_portfolio_quotes[symbol]

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
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_id=transaction_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                model_portfolio_snapshot_id=model_portfolio_snapshot_id
            )
        except Exception as error:
            self._mark_transaction_failed(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                transaction_id=transaction_id,
                error=error,
            )
            raise TradeExecutionInternalServerError(
                message=(
                    f"Failed to execute portfolio update for portfolio '{portfolio_id}', "
                    f"snapshot '{model_portfolio_snapshot_id}', user '{cognito_user_id}', "
                    f"and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_PORTFOLIO_UPDATE_FAILED",
            ) from error
        finally:
            if owner_token is not None:
                self.user_trade_lock_repository.release_lock(
                    cognito_user_id=cognito_user_id,
                    owner_token=owner_token,
                )
    def execute_deposit_to_portfolio(
        self,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        deposit_amount: float,
        transaction_id: str,
        cognito_user_id: str,
        alpaca_account_id: str,
        is_test: bool = False
    ) -> None:
        """
        Deposit a specified dollar amount into a user's portfolio allocation.

        Allocates the deposit amount across all positions in the latest model portfolio
        snapshot according to their weights, leverage, and direction. Creates market
        orders to establish or increase positions. If all the positions cannot be filled
        within x seconds, all positions are unwound.

        Args:
            portfolio_id: ID of the portfolio to deposit into
            portfolio_owner_cognito_user_id: ID of the portfolio owner
            deposit_amount: Dollar amount to deposit into the portfolio
            cognito_user_id: ID of the user making the deposit
            is_test: If True, skip realizing filled orders (for testing)

        Returns:
            List[Order]: List of Alpaca Order objects executed for the deposit

        Raises:
            ValueError: If model portfolio is not found
        """

        owner_token = str(uuid.uuid4())
        try:
            self._validate_amount(deposit_amount)
            acquired = self.user_trade_lock_repository.acquire_lock(
                cognito_user_id=cognito_user_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS,
            )
            if not acquired:
                raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

            # Reconcile previously submitted orders before this execution.
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                    lock_already_acquired=True,
                )

            # Get the latest model portfolio position's weights
            model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
            curr_model_portfolio_snapshot = model_portfolio.position_history[-1]
            curr_model_portfolio_snapshot_id = curr_model_portfolio_snapshot.snapshot_id
            curr_model_portfolio_positions = curr_model_portfolio_snapshot.positions
            symbols = [position.symbol for position in curr_model_portfolio_positions]
            model_portfolio_position_weight_dict,_,_ = self.model_portfolio_repository.calculate_positions_current_weight(model_portfolio_snapshot=curr_model_portfolio_snapshot)

            # Get the portfolio allocation equity (if any)
            portfolio_allocation_equity = 0.0
            portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                with_wait=True
            )
            portfolio_allocation_position_snapshots = portfolio_allocation.position_history
            quotes = {}
            if portfolio_allocation_position_snapshots and portfolio_allocation_position_snapshots[-1].positions:
                _, portfolio_allocation_equity, quotes = self.portfolio_allocation_repository.calculate_positions_current_value(portfolio_allocation_position_snapshot=portfolio_allocation_position_snapshots[-1])
            else:
                quotes = self.alpaca_broker_client.get_latest_price(symbols)
            if portfolio_allocation_equity + deposit_amount < MINIMUM_PORTFOLIO_BALANCE:
                raise ValueError(f"Minimum balance is {MINIMUM_PORTFOLIO_BALANCE} dollars. Deposit only results in {portfolio_allocation_equity + deposit_amount}.")

            # Create the delta positions that will be executed
            delta_positions: List[DeltaPosition] = []
            for position in curr_model_portfolio_positions:
                symbol = position.symbol
                order_direction = position.direction
                position_allocation = model_portfolio_position_weight_dict[symbol] * deposit_amount * position.leverage
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
            executed = self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=portfolio_id,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_id=transaction_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                model_portfolio_snapshot_id = curr_model_portfolio_snapshot_id
            )

            if executed:
                self.model_portfolio_follower_repository.put_model_portfolio_follower(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=portfolio_id,
                    portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                )

                model_portfolio_2 = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
                if model_portfolio_2.position_history[-1].snapshot_id != curr_model_portfolio_snapshot_id:
                    update_snapshot_id = model_portfolio_2.position_history[-1].snapshot_id
                    queued_at = datetime.now(timezone.utc)
                    update_transaction = PortfolioAllocationTransactionSnapshot(
                        transaction_id=str(uuid.uuid4()),
                        created_at=queued_at,
                        updated_at=queued_at,
                        requested_amount=None,
                        transaction_type="UPDATE",
                        status="QUEUED",
                        model_portfolio_snapshot_id=update_snapshot_id,
                    )
                    updated_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                        cognito_user_id=cognito_user_id,
                        portfolio_id=portfolio_id,
                    )
                    updated_allocation.transaction_history.append(update_transaction)
                    self.portfolio_allocation_repository.set_portfolio_allocation(
                        portfolio_allocation=updated_allocation
                    )
                    self.execute_update_in_portfolio(
                        portfolio_id=portfolio_id,
                        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                        cognito_user_id=cognito_user_id,
                        alpaca_account_id=alpaca_account_id,
                        model_portfolio_snapshot_id=update_snapshot_id,
                        transaction_id=update_transaction.transaction_id,
                        lock_already_acquired=True,
                    )

        except Exception as e:
            self._mark_transaction_failed(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                transaction_id=transaction_id,
                error=e,
            )

            raise TradeExecutionInternalServerError(
                message=(
                    f"Failed to execute portfolio deposit for portfolio '{portfolio_id}', "
                    f"user '{cognito_user_id}', and account '{alpaca_account_id}': {e}"
                ),
                code="TRADE_EXECUTION_PORTFOLIO_DEPOSIT_FAILED",
            ) from e

        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)



    # Stock execution

    def execute_close_stock(
        self, 
        asset_id: str, 
        transaction_id: str, 
        alpaca_account_id: str, 
        cognito_user_id: str, 
        is_test: bool = False
    ) -> None:
        """
        Liquidate stock position in a user's portfolio allocation.

        Args:
            portfolio_id: ID of the portfolio to withdraw from
            cognito_user_id: ID of the user withdrawing
            is_test: If True, skip realizing filled orders (for testing)

        Returns:
            List[Order]: List of Alpaca Order objects executed for the withdrawal
        """

        owner_token = str(uuid.uuid4())
        try:
            acquired = self.user_trade_lock_repository.acquire_lock(
                cognito_user_id=cognito_user_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS,
            )
            if not acquired:
                raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

            # Reconcile previously submitted orders before this execution.
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=asset_id,
                    lock_already_acquired=True,
                )

            # Get positions to close
            curr_portfolio_allocation_position_snapshot = self.portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(cognito_user_id=cognito_user_id, portfolio_id=asset_id)
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
                transaction_id=transaction_id,
                portfolio_owner_cognito_user_id=None,
            )

            return execution_trade_response
        except Exception as error:
            self._mark_transaction_failed(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id,
                transaction_id=transaction_id,
                error=error,
            )
            raise TradeExecutionInternalServerError(
                message=(
                    f"Failed to execute stock close for asset '{asset_id}', user "
                    f"'{cognito_user_id}', and account '{alpaca_account_id}': {error}"
                ),
                code="TRADE_EXECUTION_STOCK_CLOSE_FAILED",
            ) from error
        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)


    def execute_sell_to_stock(
        self,
        symbol: str,
        asset_id: str,
        transaction_id: str,
        withdraw_amount: float,
        alpaca_account_id: str,
        cognito_user_id: str,
        is_test: bool = False
    ) -> None:
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
        try:
            self._validate_amount(withdraw_amount)
            acquired = self.user_trade_lock_repository.acquire_lock(
                cognito_user_id=cognito_user_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS,
            )
            if not acquired:
                raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

            # Reconcile previously submitted orders before this execution.
            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=asset_id,
                    lock_already_acquired=True,
                )

            # Get the current value of stock allocation (if any)
            stock_allocation_equity = 0.0
            quotes = {}
            portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id,
                with_wait=True
            )
            portfolio_allocation_position_snapshots = portfolio_allocation.position_history
            if portfolio_allocation_position_snapshots and portfolio_allocation_position_snapshots[-1].positions:
                _, stock_allocation_equity, quotes = self.portfolio_allocation_repository.calculate_positions_current_value(portfolio_allocation_position_snapshot=portfolio_allocation_position_snapshots[-1])
                current_direction = portfolio_allocation_position_snapshots[-1].positions[0].direction
            else:
                quotes = self.alpaca_broker_client.get_latest_price(symbols=[symbol])
                current_direction = None

            projected_equity = self._project_stock_equity(
                current_equity=stock_allocation_equity,
                current_direction=current_direction,
                amount=withdraw_amount,
                trade_direction=-1,
            )
            if projected_equity < MINIMUM_STOCK_BALANCE:
                raise TradeExecutionInternalServerError(
                    message=(
                        f"Sell would leave ${projected_equity:.2f}; close the position or "
                        f"retain at least ${MINIMUM_STOCK_BALANCE:.2f}."
                    ),
                    code="TRADE_EXECUTION_MINIMUM_STOCK_BALANCE",
                )

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
                transaction_id=transaction_id,
                portfolio_owner_cognito_user_id=None,
            )

        except Exception as e:
            self._mark_transaction_failed(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id,
                transaction_id=transaction_id,
                error=e,
            )

            raise TradeExecutionInternalServerError(
                message=(
                    f"Failed to execute stock sell for asset '{asset_id}', user "
                    f"'{cognito_user_id}', and account '{alpaca_account_id}': {e}"
                ),
                code="TRADE_EXECUTION_STOCK_SELL_FAILED",
            ) from e

        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)


    def execute_buy_to_stock(
        self,
        symbol: str,
        asset_id: str,
        transaction_id: str,
        deposit_amount: float,
        cognito_user_id: str,
        alpaca_account_id: str,
        is_test: bool = False
    ) -> None:
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
        try:
            self._validate_amount(deposit_amount)
            acquired = self.user_trade_lock_repository.acquire_lock(
                cognito_user_id=cognito_user_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS,
            )
            if not acquired:
                raise HTTPException(status_code=409, detail="Another trade operation is in progress for this user")

            if not is_test:
                self.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    portfolio_id=asset_id,
                    lock_already_acquired=True,
                )

            # Get the current value of stock allocation (if any)
            stock_allocation_equity = 0.0
            quotes = {}
            portfolio_allocation = self.portfolio_allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id,
                with_wait=True,
            )
            portfolio_allocation_position_snapshots = portfolio_allocation.position_history
            if portfolio_allocation_position_snapshots and portfolio_allocation_position_snapshots[-1].positions:
                _, stock_allocation_equity, quotes = self.portfolio_allocation_repository.calculate_positions_current_value(portfolio_allocation_position_snapshot=portfolio_allocation_position_snapshots[-1])
                current_direction = portfolio_allocation_position_snapshots[-1].positions[0].direction
            else:
                quotes = self.alpaca_broker_client.get_latest_price(symbols=[symbol])
                current_direction = None

            projected_equity = self._project_stock_equity(
                current_equity=stock_allocation_equity,
                current_direction=current_direction,
                amount=deposit_amount,
                trade_direction=1,
            )
            if projected_equity < MINIMUM_STOCK_BALANCE:
                raise TradeExecutionInternalServerError(
                    message=(
                        f"Buy would leave ${projected_equity:.2f}; close the position or "
                        f"retain at least ${MINIMUM_STOCK_BALANCE:.2f}."
                    ),
                    code="TRADE_EXECUTION_MINIMUM_STOCK_BALANCE",
                )

            # Create the delta positions that will be executed
            price = quotes[symbol]
            margin_ask = float(ceil(price * (1 + MARGIN) * 100) / 100)
            order_qty = deposit_amount / margin_ask
            delta_positions = [DeltaPosition(symbol=symbol, quantity=order_qty, direction=1)]

            # Execute trades via helper
            self._execute_trades_helper(
                delta_positions=delta_positions,
                portfolio_id=asset_id,
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transaction_id=transaction_id,
                portfolio_owner_cognito_user_id=None,
            )
        except Exception as e:
            self._mark_transaction_failed(
                cognito_user_id=cognito_user_id,
                portfolio_id=asset_id,
                transaction_id=transaction_id,
                error=e,
            )

            raise TradeExecutionInternalServerError(
                message=(
                    f"Failed to execute stock buy for asset '{asset_id}', user "
                    f"'{cognito_user_id}', and account '{alpaca_account_id}': {e}"
                ),
                code="TRADE_EXECUTION_STOCK_BUY_FAILED",
            ) from e

        finally:
            self.user_trade_lock_repository.release_lock(cognito_user_id=cognito_user_id, owner_token=owner_token)

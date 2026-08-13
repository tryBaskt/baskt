from __future__ import annotations

import json
import threading
import uuid
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
from math import ceil, floor
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any, Deque, Dict, List
from unittest.mock import MagicMock

from alpaca.broker.models import Order
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    OrderStatus,
    OrderType,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.trading.requests import GetOrdersRequest

from clients.alpaca_broker_client import AlpacaBrokerClient
from domain.baskt_domain import BasktPosition
from domain.stock_domain import Stock
from repository.user_trade_lock_repository import UserTradeLockRepository
from services.trade_execution_service import TradeExecutionService


MOCK_MARGIN = 0.000
EPS = 1e-6


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
            raise self.processing_errors.pop(0)

    def reset(self) -> None:
        """Clear queued/processed mock SQS state between integrated tests."""
        with self._processor_lock:
            self.messages.clear()
            self.processed_messages.clear()
            self.processing_errors.clear()

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

        self._wait_until_queue_lock_is_released(payload["cognito_user_id"])

        if action == "portfolio_update":
            self.trade_execution_service.execute_update_in_portfolio(
                portfolio_id=payload["portfolio_id"],
                cognito_user_id=payload["cognito_user_id"],
                alpaca_account_id=payload["alpaca_account_id"],
                portfolio_snapshot_id=payload["portfolio_snapshot_id"],
                transaction_id=payload["transaction_id"],
            )
            return

        if action == "portfolio_deposit":
            self.trade_execution_service.execute_deposit_to_portfolio(
                portfolio_id=payload["portfolio_id"],
                deposit_amount=float(payload["amount"]),
                transaction_id=payload["transaction_id"],
                cognito_user_id=payload["cognito_user_id"],
                alpaca_account_id=payload["alpaca_account_id"],
            )
            return

        if action == "portfolio_withdraw":
            self.trade_execution_service.execute_withdraw_from_portfolio(
                portfolio_id=payload["portfolio_id"],
                withdraw_amount=float(payload["amount"]),
                transaction_id=payload["transaction_id"],
                alpaca_account_id=payload["alpaca_account_id"],
                cognito_user_id=payload["cognito_user_id"],
            )
            return

        if action == "portfolio_withdraw_all":
            self.trade_execution_service.execute_withdraw_all_from_portfolio(
                portfolio_id=payload["portfolio_id"],
                transaction_id=payload["transaction_id"],
                alpaca_account_id=payload["alpaca_account_id"],
                cognito_user_id=payload["cognito_user_id"],
            )
            return

        if action == "stock_buy":
            self.trade_execution_service.execute_buy_to_stock(
                stock_id=payload["asset_id"],
                transaction_id=payload["transaction_id"],
                deposit_amount=float(payload["amount"]),
                cognito_user_id=payload["cognito_user_id"],
                alpaca_account_id=payload["alpaca_account_id"],
            )
            return

        if action == "stock_sell":
            self.trade_execution_service.execute_sell_to_stock(
                stock_id=payload["asset_id"],
                transaction_id=payload["transaction_id"],
                withdraw_amount=float(payload["amount"]),
                alpaca_account_id=payload["alpaca_account_id"],
                cognito_user_id=payload["cognito_user_id"],
            )
            return

        if action == "stock_close":
            self.trade_execution_service.execute_close_stock(
                stock_id=payload["asset_id"],
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


def build_mock_alpaca_broker_client(
    *,
    real_client: AlpacaBrokerClient,
    prices: Dict[str, float],
    funded_1000_alpaca_account_id: str,
) -> AlpacaBrokerClient:
    """Wrap a real Alpaca client while mocking trading-side behavior."""
    mock = MagicMock(spec=AlpacaBrokerClient, wraps=real_client)
    mock.client = MagicMock()

    state: Dict[str, Dict[str, Order | BasktPosition | float]] = {
        "positions": defaultdict(dict),
        "orders": defaultdict(dict),
        "prices": prices,
    }

    def _make_order(
        alpaca_account_id: str,
        symbol: str,
        order_side: OrderSide,
        qty: float,
    ) -> Order:
        now = datetime.now(timezone.utc)
        order_id = str(uuid.uuid4())
        order = Order(
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

    def _apply_filled_order_to_positions(
        alpaca_account_id: str,
        order: Order,
    ) -> None:
        order_symbol = order.symbol
        order_direction = 1 if order.side.name == "BUY" else -1
        order_filled_avg_price = order.filled_avg_price
        order_filled_quantity = order.filled_qty

        if order_symbol not in state["positions"][alpaca_account_id]:
            state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=order_filled_quantity,
                filled_avg_price=order_filled_avg_price,
                direction=order_direction,
            )
            return

        pos = state["positions"][alpaca_account_id][order_symbol]
        pos_signed = pos.direction * pos.filled_quantity
        ord_signed = order_direction * order_filled_quantity

        if pos_signed * ord_signed > 0:
            new_qty = pos.filled_quantity + order_filled_quantity
            new_avg = (
                (pos.filled_quantity * pos.filled_avg_price)
                + (order_filled_quantity * order_filled_avg_price)
            ) / new_qty
            state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=new_qty,
                filled_avg_price=new_avg,
                direction=pos.direction,
            )
            return

        remaining = pos.filled_quantity - order_filled_quantity
        if abs(remaining) <= EPS:
            del state["positions"][alpaca_account_id][order_symbol]
            return

        if remaining > 0:
            state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
                symbol=order_symbol,
                filled_quantity=remaining,
                filled_avg_price=pos.filled_avg_price,
                direction=pos.direction,
            )
            return

        state["positions"][alpaca_account_id][order_symbol] = BasktPosition(
            symbol=order_symbol,
            filled_avg_price=order_filled_avg_price,
            filled_quantity=abs(remaining),
            direction=order_direction,
        )

    def _apply_fill(alpaca_account_id: str, order_id: str) -> Order:
        order = state["orders"][alpaca_account_id][order_id]
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
        _apply_filled_order_to_positions(alpaca_account_id, order)
        return order

    def get_latest_price(symbols: List[str]) -> Dict[str, float]:
        return {symbol: float(state["prices"][symbol]) for symbol in symbols}

    def execute_quantity_buy(
        symbol: str,
        quantity: float,
        alpaca_account_id: str,
        cognito_user_id: str,
    ) -> Order:
        return _make_order(
            alpaca_account_id,
            symbol,
            OrderSide.BUY,
            float(quantity),
        )

    def execute_quantity_sell(
        symbol: str,
        quantity: float,
        alpaca_account_id: str,
        cognito_user_id: str,
    ) -> Order:
        return _make_order(
            alpaca_account_id,
            symbol,
            OrderSide.SELL,
            float(quantity),
        )

    def execute_quantity_fractional_sell(
        symbol: str,
        quantity: float,
        alpaca_account_id: str,
        cognito_user_id: str,
    ):
        sell_order = execute_quantity_sell(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            symbol=symbol,
            quantity=ceil(quantity),
        )
        if ceil(quantity) - quantity <= 0:
            return sell_order, None
        accepted_sell_order = deepcopy(sell_order)
        _apply_fill(alpaca_account_id, str(sell_order.id))
        buy_order = execute_quantity_buy(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            symbol=symbol,
            quantity=ceil(quantity) - quantity,
        )
        return accepted_sell_order, buy_order

    def execute_close_position(
        symbol: str,
        alpaca_account_id: str,
        cognito_user_id: str,
    ) -> Order:
        position = state["positions"][alpaca_account_id][symbol]
        order_side = OrderSide.SELL if position.direction == 1 else OrderSide.BUY
        return _make_order(
            alpaca_account_id,
            symbol,
            order_side,
            float(position.filled_quantity),
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
        _apply_fill(alpaca_account_id, str(close_order.id))
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
        _apply_fill(alpaca_account_id, str(close_order.id))
        buy_order = execute_quantity_buy(
            symbol=symbol,
            quantity=quantity - curr_quantity,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        return [accepted_close_order, buy_order]

    def get_baskt_positions_dict(
        alpaca_account_id: str,
        cognito_user_id: str,
    ) -> Dict[str, BasktPosition]:
        return state["positions"][alpaca_account_id]

    def get_position_by_asset_id(
        alpaca_account_id: str,
        cognito_user_id: str,
        asset_id: str,
        error_if_no_position: bool = False,
    ) -> BasktPosition | None:
        position = state["positions"][alpaca_account_id].get("AAPL")
        if position is None and error_if_no_position:
            raise Exception(f"No position found for asset id '{asset_id}'")
        return position

    def get_trade_account(account_id: str, cognito_user_id: str):
        if account_id == funded_1000_alpaca_account_id:
            return SimpleNamespace(multiplier="1", shorting_enabled=False)
        return SimpleNamespace(multiplier="2", shorting_enabled=True)

    def get_order_by_id(
        alpaca_account_id: str,
        cognito_user_id: str,
        order_id: str,
    ) -> Order:
        order = state["orders"][alpaca_account_id][order_id]
        if order.status != OrderStatus.FILLED:
            order = _apply_fill(alpaca_account_id, order_id)
        return order

    def execute_close_all_position(
        alpaca_account_id: str,
        cognito_user_id: str | None = None,
        cancel_open_orders: bool = True,
        wait: bool = True,
        timeout_sec: int = 20,
        poll_interval_sec: float = 2.0,
    ) -> bool:
        state["positions"][alpaca_account_id].clear()
        return True

    def reset_trading_state() -> None:
        state["positions"].clear()
        state["orders"].clear()

    def get_orders_for_account(
        account_id: str,
        filter: GetOrdersRequest | None = None,
    ) -> List[Order]:
        orders = list(state["orders"][account_id].values())
        if filter is not None and filter.status == QueryOrderStatus.OPEN:
            return [order for order in orders if order.status != OrderStatus.FILLED]
        return orders

    def cancel_order_for_account_by_id(account_id: str, order_id: str) -> bool:
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

    def get_symbol_by_asset_id(*, asset_id: str) -> str:
        return get_stock_by_asset_id(asset_id=asset_id).symbol

    mock.execute_quantity_buy.side_effect = execute_quantity_buy
    mock.execute_quantity_sell.side_effect = execute_quantity_sell
    mock.execute_quantity_fractional_sell.side_effect = execute_quantity_fractional_sell
    mock.execute_close_position.side_effect = execute_close_position
    mock.execute_long_to_short_sell.side_effect = execute_long_to_short_sell
    mock.execute_short_to_long_buy.side_effect = execute_short_to_long_buy
    mock.get_baskt_positions_dict.side_effect = get_baskt_positions_dict
    mock.get_position_by_asset_id.side_effect = get_position_by_asset_id
    mock.get_trade_account.side_effect = get_trade_account
    mock.get_latest_price.side_effect = get_latest_price
    mock.get_order_by_id.side_effect = get_order_by_id
    mock.execute_close_all_position.side_effect = execute_close_all_position
    mock.reset_trading_state = reset_trading_state
    mock.client.get_orders_for_account.side_effect = get_orders_for_account
    mock.client.cancel_order_for_account_by_id.side_effect = cancel_order_for_account_by_id
    mock.get_stock_by_asset_id.side_effect = get_stock_by_asset_id
    mock.get_symbol_by_asset_id.side_effect = get_symbol_by_asset_id

    return mock

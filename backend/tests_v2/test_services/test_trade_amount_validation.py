from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.trade_execution_queuing_service import (
    TradeExecutionQueuingInternalServerError,
    TradeExecutionQueuingService,
)
from services.trade_execution_service import (
    TradeExecutionInternalServerError,
    TradeExecutionService,
)


def _stock_allocation(direction: int) -> SimpleNamespace:
    return SimpleNamespace(
        position_history=[
            SimpleNamespace(
                position=SimpleNamespace(
                    symbol="AAPL",
                    direction=direction,
                ),
            ),
        ],
    )


def _execution_service_with_lock() -> TradeExecutionService:
    service = object.__new__(TradeExecutionService)
    service.user_trade_lock_repository = SimpleNamespace(
        acquire_lock=lambda **_: True,
        release_lock=lambda **_: None,
    )
    service.realize_filled_orders = lambda **_: None
    service._mark_transaction_failed = lambda **_: None
    service._validate_amount = lambda amount, **_: amount
    return service


def test_queue_validate_amount_accepts_at_most_two_decimals_and_checks_cash(monkeypatch):
    service = object.__new__(TradeExecutionQueuingService)
    monkeypatch.setattr(
        service,
        "_get_available_cash",
        lambda **_: 10.10,
    )

    assert service._validate_amount(
        10.1,
        cognito_user_id="user-1",
        alpaca_account_id="account-1",
        validate_cash=True,
    ) == 10.10


def test_queue_validate_amount_rejects_more_than_two_decimals():
    service = object.__new__(TradeExecutionQueuingService)

    with pytest.raises(TradeExecutionQueuingInternalServerError) as exc_info:
        service._validate_amount(10.001)

    assert exc_info.value.code == "TRADE_EXECUTION_QUEUE_AMOUNT_INVALID"
    assert "at most two decimal places" in str(exc_info.value)


def test_queue_validate_amount_rejects_amount_above_cash(monkeypatch):
    service = object.__new__(TradeExecutionQueuingService)
    monkeypatch.setattr(
        service,
        "_get_available_cash",
        lambda **_: 99.99,
    )

    with pytest.raises(TradeExecutionQueuingInternalServerError) as exc_info:
        service._validate_amount(
            100.00,
            cognito_user_id="user-1",
            alpaca_account_id="account-1",
            validate_cash=True,
        )

    assert exc_info.value.code == "TRADE_EXECUTION_QUEUE_AMOUNT_EXCEEDS_CASH"


def test_queue_portfolio_withdraw_rejects_amount_above_allocation_equity(monkeypatch):
    service = object.__new__(TradeExecutionQueuingService)
    service.model_portfolio_repository = SimpleNamespace(
        get_portfolio_cognito_owner_id_by_portfolio=lambda **_: "owner-1",
    )
    service.allocation_repository = SimpleNamespace(
        get_portfolio_allocation=lambda **_: SimpleNamespace(),
    )
    monkeypatch.setattr(service, "_validate_common_portfolio_fields", lambda **_: None)
    monkeypatch.setattr(service, "_validate_amount", lambda amount, **_: amount)
    monkeypatch.setattr(service, "_portfolio_allocation_equity", lambda _: 100.00)

    with pytest.raises(TradeExecutionQueuingInternalServerError) as exc_info:
        TradeExecutionQueuingService.queue_portfolio_withdrawal.__wrapped__(
            service,
            portfolio_id="portfolio-1",
            amount=100.50,
            cognito_user_id="user-1",
            alpaca_account_id="account-1",
        )

    assert exc_info.value.code == "TRADE_EXECUTION_QUEUE_AMOUNT_EXCEEDS_EQUITY"


def test_queue_stock_sell_rejects_long_to_short_below_minimum_balance(monkeypatch):
    service = object.__new__(TradeExecutionQueuingService)
    service.alpaca_broker_client = SimpleNamespace(
        get_stock_by_asset_id=lambda **_: SimpleNamespace(
            symbol="AAPL",
            tradable=True,
            fractionable=True,
            shortable=True,
        ),
    )
    monkeypatch.setattr(service, "_validate_common_stock_fields", lambda **_: None)
    monkeypatch.setattr(service, "_validate_amount", lambda amount, **_: amount)
    monkeypatch.setattr(service, "_stock_allocation", lambda **_: SimpleNamespace())
    monkeypatch.setattr(service, "_stock_allocation_equity", lambda _: 100.00)
    monkeypatch.setattr(service, "_stock_direction", lambda _: 1)

    with pytest.raises(TradeExecutionQueuingInternalServerError) as exc_info:
        service._queue_stock_trade(
            asset_id="asset-1",
            amount=100.50,
            cognito_user_id="user-1",
            alpaca_account_id="account-1",
            trade_direction=-1,
        )

    assert exc_info.value.code == "TRADE_EXECUTION_QUEUE_MINIMUM_BALANCE"


def test_queue_stock_buy_rejects_short_to_long_below_minimum_balance(monkeypatch):
    service = object.__new__(TradeExecutionQueuingService)
    service.alpaca_broker_client = SimpleNamespace(
        get_stock_by_asset_id=lambda **_: SimpleNamespace(
            symbol="AAPL",
            tradable=True,
            fractionable=True,
            shortable=True,
        ),
    )
    monkeypatch.setattr(service, "_validate_common_stock_fields", lambda **_: None)
    monkeypatch.setattr(service, "_validate_amount", lambda amount, **_: amount)
    monkeypatch.setattr(service, "_stock_allocation", lambda **_: SimpleNamespace())
    monkeypatch.setattr(service, "_stock_allocation_equity", lambda _: 100.00)
    monkeypatch.setattr(service, "_stock_direction", lambda _: -1)

    with pytest.raises(TradeExecutionQueuingInternalServerError) as exc_info:
        service._queue_stock_trade(
            asset_id="asset-1",
            amount=100.50,
            cognito_user_id="user-1",
            alpaca_account_id="account-1",
            trade_direction=1,
        )

    assert exc_info.value.code == "TRADE_EXECUTION_QUEUE_MINIMUM_BALANCE"


def test_execution_validate_amount_accepts_at_most_two_decimals_and_checks_cash(monkeypatch):
    service = object.__new__(TradeExecutionService)
    monkeypatch.setattr(
        service,
        "_get_available_cash_for_execution",
        lambda **_: 10.10,
    )

    assert service._validate_amount(
        10.1,
        cognito_user_id="user-1",
        alpaca_account_id="account-1",
        validate_cash=True,
    ) == 10.10


def test_execution_validate_amount_rejects_more_than_two_decimals():
    service = object.__new__(TradeExecutionService)

    with pytest.raises(TradeExecutionInternalServerError) as exc_info:
        service._validate_amount(10.001)

    assert exc_info.value.code == "TRADE_EXECUTION_AMOUNT_INVALID"
    assert "at most two decimal places" in str(exc_info.value)


def test_execution_validate_amount_rejects_amount_above_cash(monkeypatch):
    service = object.__new__(TradeExecutionService)
    monkeypatch.setattr(
        service,
        "_get_available_cash_for_execution",
        lambda **_: 99.99,
    )

    with pytest.raises(TradeExecutionInternalServerError) as exc_info:
        service._validate_amount(
            100.00,
            cognito_user_id="user-1",
            alpaca_account_id="account-1",
            validate_cash=True,
        )

    assert exc_info.value.code == "TRADE_EXECUTION_AMOUNT_EXCEEDS_CASH"


def test_execution_portfolio_withdraw_rejects_amount_above_allocation_equity():
    service = _execution_service_with_lock()
    service.model_portfolio_repository = SimpleNamespace(
        get_portfolio_cognito_owner_id_by_portfolio=lambda **_: "owner-1",
    )
    service.allocation_repository = SimpleNamespace(
        get_latest_portfolio_allocation_position_snapshot=lambda **_: SimpleNamespace(
            positions=[],
        ),
        calculate_portfolio_allocation_position_snapshot_current_weight=lambda **_: (
            {},
            100.00,
            {},
        ),
    )

    with pytest.raises(TradeExecutionInternalServerError) as exc_info:
        service.execute_withdraw_from_portfolio(
            portfolio_id="portfolio-1",
            withdraw_amount=100.50,
            transaction_id="transaction-1",
            alpaca_account_id="account-1",
            cognito_user_id="user-1",
            is_test=True,
        )

    assert exc_info.value.code == "TRADE_EXECUTION_PORTFOLIO_WITHDRAWAL_FAILED"
    assert "Withdraw amount greater than market value" in str(exc_info.value)


def test_execution_stock_sell_rejects_long_to_short_below_minimum_balance():
    service = _execution_service_with_lock()
    service.allocation_repository = SimpleNamespace(
        get_allocation=lambda **_: _stock_allocation(direction=1),
        calculate_stock_allocation_position_snapshot_current_value=lambda **_: (
            100.00,
            20.00,
        ),
    )
    service.alpaca_broker_client = SimpleNamespace(
        get_symbol_by_asset_id=lambda **_: "AAPL",
    )

    with pytest.raises(TradeExecutionInternalServerError) as exc_info:
        service.execute_sell_to_stock(
            stock_id="asset-1",
            transaction_id="transaction-1",
            withdraw_amount=100.50,
            alpaca_account_id="account-1",
            cognito_user_id="user-1",
            is_test=True,
        )

    assert exc_info.value.code == "TRADE_EXECUTION_STOCK_SELL_FAILED"
    assert "Sell would leave $0.50" in str(exc_info.value)


def test_execution_stock_buy_rejects_short_to_long_below_minimum_balance():
    service = _execution_service_with_lock()
    service.allocation_repository = SimpleNamespace(
        get_allocation=lambda **_: _stock_allocation(direction=-1),
        calculate_stock_allocation_position_snapshot_current_value=lambda **_: (
            100.00,
            20.00,
        ),
    )
    service.alpaca_broker_client = SimpleNamespace(
        get_symbol_by_asset_id=lambda **_: "AAPL",
    )

    with pytest.raises(TradeExecutionInternalServerError) as exc_info:
        service.execute_buy_to_stock(
            stock_id="asset-1",
            transaction_id="transaction-1",
            deposit_amount=100.50,
            cognito_user_id="user-1",
            alpaca_account_id="account-1",
            is_test=True,
        )

    assert exc_info.value.code == "TRADE_EXECUTION_STOCK_BUY_FAILED"
    assert "Buy would leave $0.50" in str(exc_info.value)

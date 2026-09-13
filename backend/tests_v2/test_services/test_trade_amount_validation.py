from __future__ import annotations

import pytest

from services.trade_execution_queuing_service import (
    TradeExecutionQueuingInternalServerError,
    TradeExecutionQueuingService,
)
from services.trade_execution_service import (
    TradeExecutionInternalServerError,
    TradeExecutionService,
)


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

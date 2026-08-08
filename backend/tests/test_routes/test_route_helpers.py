from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessBadGatewayError,
    ModelPortfolioAccessRepositoryError,
    ModelPortfolioAccessUnprocessableEntityError,
    ModelPortfolioAccessUserIsFollowerError,
    ModelPortfolioAccessUserNotFoundError,
)
from repository.model_portfolio_repository import (
    ModelPortfolioBadGatewayError,
    ModelPortfolioInternalServerError,
    ModelPortfolioLockedError,
    ModelPortfolioNotFoundError,
    ModelPortfolioTooManyRequestsError,
    ModelPortfolioUnprocessableEntityError,
)
from routes.account_lifecycle_route import (
    _raise_account_lifecycle_http_exception,
    _to_ach_relationship_response,
    _to_bank_response,
    _to_enum_name,
    _to_optional_str,
    _to_trade_account_response,
    _to_transfer_response,
)
from routes.backtest_route import _raise_backtest_http_exception
from routes.explore_search_route import _raise_search_http_exception
from routes.model_portfolio_route import _raise_model_portfolio_http_exception
from routes.stock_route import _raise_stock_http_exception
from routes.trade_execution_route import _raise_trade_execution_http_exception
from services.account_lifecycle_service import (
    AccountLifecycleDisplayNameTakenError,
    AccountLifecycleInternalServerError,
    AccountLifecycleServiceBasktAccountDisabled,
)
from services.backtest_analytics_service import (
    BacktestInternalServerError,
    BacktestServiceCalculationError,
    BacktestServiceDataError,
    BacktestServiceValidationError,
)
from services.explore_search_service import ExploreSearchInternalServerError
from services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsInternalServerError,
)
from services.stock_analytics_service import StockAnalyticsInternalServerError
from services.trade_execution_queuing_service import (
    TradeExecutionQueuingInternalServerError,
)


def _assert_http_exception(
    translator,
    error: Exception,
    *,
    status_code: int,
    code: str | None = None,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        translator(error)

    assert exc_info.value.status_code == status_code
    if code is not None:
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["code"] == code


def test_account_lifecycle_error_mapping() -> None:
    _assert_http_exception(
        _raise_account_lifecycle_http_exception,
        AccountLifecycleServiceBasktAccountDisabled("disabled"),
        status_code=403,
        code="ACCOUNT_LIFECYCLE_SERVICE_BASKT_ACCOUNT_DISABLED",
    )
    _assert_http_exception(
        _raise_account_lifecycle_http_exception,
        AccountLifecycleDisplayNameTakenError("taken"),
        status_code=409,
        code="ACCOUNT_LIFECYCLE_DISPLAY_NAME_TAKEN",
    )
    _assert_http_exception(
        _raise_account_lifecycle_http_exception,
        AccountLifecycleInternalServerError("invalid", code="ACCOUNT_INVALID"),
        status_code=422,
        code="ACCOUNT_INVALID",
    )
    _assert_http_exception(
        _raise_account_lifecycle_http_exception,
        ValueError("unexpected"),
        status_code=500,
        code="ACCOUNT_LIFECYCLE_UNEXPECTED_ERROR",
    )


def test_backtest_error_mapping() -> None:
    for error, status_code in (
        (ValueError("bad request"), 400),
        (BacktestServiceValidationError("invalid"), 422),
        (BacktestServiceDataError("data"), 502),
        (BacktestServiceCalculationError("calculation"), 422),
        (BacktestInternalServerError("internal"), 500),
    ):
        _assert_http_exception(
            _raise_backtest_http_exception,
            error,
            status_code=status_code,
        )

    _assert_http_exception(
        _raise_backtest_http_exception,
        RuntimeError("unexpected"),
        status_code=500,
        code="BACKTEST_UNEXPECTED_ERROR",
    )


def test_explore_search_error_mapping() -> None:
    _assert_http_exception(
        _raise_search_http_exception,
        ExploreSearchInternalServerError(
            "invalid",
            code="MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT",
        ),
        status_code=422,
        code="MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT",
    )
    _assert_http_exception(
        _raise_search_http_exception,
        ExploreSearchInternalServerError("upstream", code="SEARCH_FAILED"),
        status_code=502,
        code="SEARCH_FAILED",
    )
    _assert_http_exception(
        _raise_search_http_exception,
        ModelPortfolioAccessBadGatewayError(operation="reading access"),
        status_code=502,
        code="MODEL_PORTFOLIO_ACCESS_BAD_GATEWAY",
    )
    _assert_http_exception(
        _raise_search_http_exception,
        ModelPortfolioAccessRepositoryError("access failed"),
        status_code=500,
        code="MODEL_PORTFOLIO_ACCESS_REPOSITORY_ERROR",
    )


def test_model_portfolio_error_mapping() -> None:
    cases = (
        (
            ModelPortfolioAccessUserNotFoundError("user@example.com", "email"),
            404,
            "MODEL_PORTFOLIO_ACCESS_USER_NOT_FOUND",
        ),
        (
            ModelPortfolioAccessUserIsFollowerError(
                portfolio_id="portfolio-1",
                shared_with_cognito_user_id="user-1",
            ),
            409,
            "MODEL_PORTFOLIO_ACCESS_USER_IS_FOLLOWER",
        ),
        (
            ModelPortfolioAccessUnprocessableEntityError("missing"),
            422,
            "MODEL_PORTFOLIO_ACCESS_UNPROCESSABLE_ENTITY",
        ),
        (
            ModelPortfolioAccessBadGatewayError(operation="read"),
            502,
            "MODEL_PORTFOLIO_ACCESS_BAD_GATEWAY",
        ),
        (
            TradeExecutionQueuingInternalServerError(
                "locked",
                code="TRADE_EXECUTION_QUEUE_LOCKED",
            ),
            409,
            "TRADE_EXECUTION_QUEUE_LOCKED",
        ),
        (
            TradeExecutionQueuingInternalServerError(
                "missing snapshot",
                code="TRADE_EXECUTION_QUEUE_MODEL_PORTFOLIO_SNAPSHOT_NOT_FOUND",
            ),
            422,
            "TRADE_EXECUTION_QUEUE_MODEL_PORTFOLIO_SNAPSHOT_NOT_FOUND",
        ),
        (
            TradeExecutionQueuingInternalServerError(
                "send failed",
                code="TRADE_EXECUTION_QUEUE_SEND_FAILED",
            ),
            502,
            "TRADE_EXECUTION_QUEUE_SEND_FAILED",
        ),
        (
            ModelPortfolioNotFoundError("portfolio-1"),
            404,
            "MODEL_PORTFOLIO_NOT_FOUND_ERROR",
        ),
        (
            ModelPortfolioLockedError("portfolio-1", "read"),
            423,
            "MODEL_PORTFOLIO_UPDATE_LOCK_ERROR",
        ),
        (
            ModelPortfolioTooManyRequestsError(30),
            429,
            "MODEL_PORTFOLIO_TOO_MANY_UPDATES_ERROR",
        ),
        (
            ModelPortfolioUnprocessableEntityError("parse"),
            422,
            "MODEL_PORTFOLIO_ENTITY_UNPROCESSABLE_ERROR",
        ),
        (
            ModelPortfolioBadGatewayError(source="DynamoDB", operation="read"),
            502,
            "MODEL_PORTFOLIO_UPSTREAM_ERROR",
        ),
        (
            ModelPortfolioInternalServerError("internal"),
            500,
            "MODEL_PORTFOLIO_INTERNAL_SERVER_ERROR",
        ),
        (
            ModelPortfolioAnalyticsInternalServerError("analytics"),
            500,
            "MODEL_PORTFOLIO_ANALYTICS_SERVICE_ERROR",
        ),
    )

    for error, status_code, code in cases:
        _assert_http_exception(
            _raise_model_portfolio_http_exception,
            error,
            status_code=status_code,
            code=code,
        )


def test_stock_and_trade_execution_error_mapping() -> None:
    _assert_http_exception(
        _raise_stock_http_exception,
        StockAnalyticsInternalServerError("stock failed"),
        status_code=500,
        code="STOCK_ANALYTICS_SERVICE_ERROR",
    )
    _assert_http_exception(
        _raise_stock_http_exception,
        RuntimeError("unexpected"),
        status_code=500,
        code="STOCK_UNEXPECTED_ERROR",
    )

    for code, status_code in (
        ("TRADE_EXECUTION_QUEUE_LOCKED", 409),
        ("TRADE_EXECUTION_QUEUE_SEND_FAILED", 502),
        ("TRADE_EXECUTION_QUEUE_MESSAGE_SERIALIZATION_FAILED", 502),
        ("TRADE_EXECUTION_QUEUE_AMOUNT_INVALID", 422),
        ("TRADE_EXECUTION_QUEUE_UNKNOWN", 500),
    ):
        _assert_http_exception(
            _raise_trade_execution_http_exception,
            TradeExecutionQueuingInternalServerError("trade failed", code=code),
            status_code=status_code,
            code=code,
        )

    _assert_http_exception(
        _raise_trade_execution_http_exception,
        RuntimeError("unexpected"),
        status_code=500,
        code="TRADE_EXECUTION_QUEUE_UNEXPECTED_ERROR",
    )


def test_account_lifecycle_response_converters() -> None:
    now = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    enum_value = SimpleNamespace(name="active", value="active-value")

    assert _to_optional_str(None) is None
    assert _to_optional_str(enum_value) == "active-value"
    assert _to_enum_name(enum_value) == "ACTIVE"

    trade_account = _to_trade_account_response(
        SimpleNamespace(
            equity="1000.00",
            cash_withdrawable="250.00",
            cash_transferable="300.00",
            previous_close="990.00",
            multiplier="1",
            shorting_enabled=False,
            trading_blocked=False,
            account_blocked=False,
            status=SimpleNamespace(name="ACTIVE"),
            last_long_market_value="800.00",
            last_short_market_value="0.00",
            last_cash="200.00",
            last_initial_margin="0.00",
            last_regt_buying_power="250.00",
            last_daytrading_buying_power="250.00",
            last_daytrade_count="0",
            last_buying_power="250.00",
            clearing_broker=SimpleNamespace(name="VELOX"),
        )
    )
    assert trade_account.equity == "1000.00"
    assert trade_account.status == "ACTIVE"
    assert trade_account.clearing_broker == "VELOX"

    ach = _to_ach_relationship_response(
        "alpaca-1",
        SimpleNamespace(
            id="ach-1",
            created_at=now,
            updated_at=None,
            status=SimpleNamespace(name="APPROVED"),
            account_owner_name="Route Tester",
            bank_account_type=SimpleNamespace(name="CHECKING"),
            bank_account_number="1234",
            bank_routing_number="121000358",
            nickname="Primary",
            processor_token=None,
        ),
    )
    assert ach.relationship_id == "ach-1"
    assert ach.alpaca_account_id == "alpaca-1"
    assert ach.updated_at is None

    bank = _to_bank_response(
        "alpaca-1",
        SimpleNamespace(
            id="bank-1",
            created_at=now,
            updated_at=now,
            name="Primary Bank",
            status=SimpleNamespace(name="ACTIVE"),
            country="USA",
            state_province="CA",
            postal_code="94105",
            city="San Francisco",
            street_address="123 Test St",
            account_number="000123",
            bank_code="121000358",
            bank_code_type=SimpleNamespace(name="ABA"),
        ),
    )
    assert bank.bank_id == "bank-1"
    assert bank.updated_at == now.isoformat()
    assert bank.bank_code_type == "ABA"

    transfer = _to_transfer_response(
        "alpaca-1",
        SimpleNamespace(
            id="transfer-1",
            created_at=now,
            updated_at=None,
            expires_at=now,
            relationship_id="ach-1",
            bank_id=None,
            amount="25.00",
            type=SimpleNamespace(name="ACH"),
            status=SimpleNamespace(name="QUEUED"),
            direction=SimpleNamespace(name="INCOMING"),
            reason=None,
            requested_amount="25.00",
            fee=None,
            fee_payment_method=None,
            additional_information=None,
        ),
    )
    assert transfer.transfer_id == "transfer-1"
    assert transfer.relationship_id == "ach-1"
    assert transfer.bank_id is None

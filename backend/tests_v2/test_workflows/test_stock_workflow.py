from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clients.alpaca_broker_client import AlpacaBrokerClient
from core.authentication import get_current_user
from core.deps import (
    get_alpaca_broker_client,
    get_baskt_account_repository,
    get_stock_analytics_service,
)
from repository.baskt_account_repository import BasktAccountRepository
from routes import stock_route
from services.stock_analytics_service import StockAnalyticsService


pytestmark = pytest.mark.integration


"""
These workflow tests exercise stock_route.py through FastAPI's TestClient while
keeping stock metadata, analytics, and Baskt account dependencies wired to the
real tests_v2 integration stack.

Coverage goals:
- get_stock(): authenticated users with a Baskt account can fetch AAPL metadata
  by its Alpaca asset id and receive the expected StockResponse fields.
- get_stock(): random Alpaca asset ids fail through the route error mapper.
- get_stock(): authenticated users without a persisted Baskt account are denied
  before stock metadata is loaded.
- get_stock(): missing auth headers, token Alpaca-account mismatches, and
  unknown token Cognito user ids are rejected by authentication; whitespace
  stock ids return 400.
- get_stock_analytics(): authenticated users with a Baskt account can fetch
  AAPL analytics and receive default-period payloads with prices, UTC
  timestamps, and metric fields; requested period filters return only those
  periods.
- get_stock_analytics(): recently IPO'd stocks still return a valid 1A
  analytics payload when their history starts inside the one-year lookback.
- get_stock_analytics(): random symbols fail through the stock analytics route
  error mapper.
- get_stock_analytics(): authenticated users without a persisted Baskt account
  are denied before analytics are loaded; missing auth headers, token
  Alpaca-account mismatches, and unknown token Cognito user ids are rejected by
  authentication.
"""


METRIC_FIELDS = {
    "final_cumulative_return",
    "cagr",
    "annualized_volatility",
    "leverage_adjusted_direction",
    "alpha",
    "beta",
    "sharpe_ratio",
    "maximum_drawdown",
    "maximum_drawdown_duration",
}
DEFAULT_PERIOD_TIMEFRAMES = {
    "all": "1D",
    "1D": "5Min",
    "1W": "1H",
    "1M": "1D",
    "3M": "1D",
    "1A": "1D",
}


def _claims_for_user(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _claims_without_baskt_account() -> dict[str, str]:
    unique = uuid4()
    return {
        "sub": f"tests-v2-no-baskt-account-{unique}",
        "custom:alpaca_acct_id": f"tests-v2-no-baskt-alpaca-{unique}",
    }


def _claims_with_mismatched_alpaca_account(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": f"tests-v2-wrong-alpaca-{uuid4()}",
    }


def _claims_with_mismatched_cognito_user_id(test_user: Any) -> dict[str, str]:
    return {
        "sub": f"tests-v2-wrong-cognito-{uuid4()}",
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _client_for_claims(
    *,
    claims: dict[str, str] | None,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
) -> TestClient:
    app = FastAPI()
    app.include_router(stock_route.router)
    if claims is not None:
        app.dependency_overrides[get_current_user] = lambda: claims
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[stock_route.get_alpaca_broker_client] = (
        lambda: alpaca_broker_client
    )
    app.dependency_overrides[get_alpaca_broker_client] = lambda: alpaca_broker_client
    app.dependency_overrides[stock_route.get_stock_analytics_service] = (
        lambda: stock_analytics_service
    )
    app.dependency_overrides[get_stock_analytics_service] = (
        lambda: stock_analytics_service
    )
    return TestClient(app)


def _client_for_user(
    *,
    test_user: Any,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
) -> TestClient:
    return _client_for_claims(
        claims=_claims_for_user(test_user),
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )


def _client_without_baskt_account(
    *,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
) -> TestClient:
    return _client_for_claims(
        claims=_claims_without_baskt_account(),
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )


def _unauthenticated_client(
    *,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
) -> TestClient:
    return _client_for_claims(
        claims=None,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )


def _assert_metric_is_valid(value: float | int | None) -> None:
    assert value is None or isinstance(value, (int, float))
    if isinstance(value, (int, float)):
        assert math.isfinite(float(value))


def _assert_analytics_payload(
    payload: dict[str, Any],
    *,
    expected_periods: set[str] | None = None,
) -> None:
    assert set(payload) == (expected_periods or set(DEFAULT_PERIOD_TIMEFRAMES))
    for period, period_payload in payload.items():
        assert period_payload["timeframe"] == DEFAULT_PERIOD_TIMEFRAMES[period]
        assert len(period_payload["timestamp"]) == len(period_payload["prices"])
        assert period_payload["timestamp"]
        assert period_payload["prices"]
        for price in period_payload["prices"]:
            assert isinstance(price, (int, float))
            assert math.isfinite(float(price))
            assert price > 0.0
        for field in METRIC_FIELDS:
            _assert_metric_is_valid(period_payload[field])


def test_stock_route_get_stock_happy_path_for_aapl_asset_id(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    aapl = alpaca_broker_client.get_stock_by_symbol(symbol="AAPL")
    assert aapl is not None
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stocks/{aapl.stock_id}")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "AAPL",
        "tradable": aapl.tradable,
        "fractionable": aapl.fractionable,
        "shortable": aapl.shortable,
        "marginable": aapl.marginable,
        "stock_id": aapl.stock_id,
        "stock_class": aapl.stock_class,
    }


def test_stock_route_get_stock_random_stock_id_errors(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stocks/{uuid4()}")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "STOCK_UNEXPECTED_ERROR"


def test_stock_route_get_stock_blank_stock_id_returns_400(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get("/stocks/%20%20%20")

    assert response.status_code == 400
    assert response.json()["detail"] == "stock_id is required."


def test_stock_route_get_stock_requires_baskt_account(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
) -> None:
    aapl = alpaca_broker_client.get_stock_by_symbol(symbol="AAPL")
    assert aapl is not None
    client = _client_without_baskt_account(
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stocks/{aapl.stock_id}")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user does not have a Baskt account."
    )


def test_stock_route_get_stock_requires_authorization_header(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
) -> None:
    aapl = alpaca_broker_client.get_stock_by_symbol(symbol="AAPL")
    assert aapl is not None
    client = _unauthenticated_client(
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stocks/{aapl.stock_id}")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid Authorization header"


def test_stock_route_get_stock_rejects_token_alpaca_account_mismatch(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    aapl = alpaca_broker_client.get_stock_by_symbol(symbol="AAPL")
    assert aapl is not None
    client = _client_for_claims(
        claims=_claims_with_mismatched_alpaca_account(test_user_1),
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stocks/{aapl.stock_id}")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user's Alpaca account does not match Baskt account."
    )


def test_stock_route_get_stock_rejects_token_cognito_user_mismatch(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    aapl = alpaca_broker_client.get_stock_by_symbol(symbol="AAPL")
    assert aapl is not None
    client = _client_for_claims(
        claims=_claims_with_mismatched_cognito_user_id(test_user_1),
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stocks/{aapl.stock_id}")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user does not have a Baskt account."
    )


def test_stock_route_get_stock_analytics_happy_path_for_aapl(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get("/stock-analytics/aapl")

    assert response.status_code == 200
    _assert_analytics_payload(response.json())


def test_stock_route_get_stock_analytics_filters_requested_periods(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get("/stock-analytics/aapl?periods=1D&periods=1M")

    assert response.status_code == 200
    response_body = response.json()
    _assert_analytics_payload(response_body, expected_periods={"1D", "1M"})


def test_stock_route_get_stock_analytics_recent_ipo_returns_one_year_payload(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    symbol = "JMKE"
    current_datetime = datetime.now(timezone.utc)
    earliest_price_datetime = stock_analytics_service.get_earliest_price_datetime(
        symbol=symbol,
        current_datetime=current_datetime,
    )
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stock-analytics/{symbol.lower()}")

    assert response.status_code == 200
    response_body = response.json()
    assert earliest_price_datetime > current_datetime - timedelta(days=365)
    assert "1A" in response_body
    _assert_analytics_payload(response_body)
    first_timestamp = datetime.fromisoformat(
        response_body["1A"]["timestamp"][0].replace("Z", "+00:00")
    )
    assert first_timestamp >= earliest_price_datetime
    assert first_timestamp > current_datetime - timedelta(days=365)


def test_stock_route_get_stock_analytics_random_symbol_errors(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get(f"/stock-analytics/NOTAREALBASKTSTOCK{uuid4().hex}")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] in {
        "STOCK_ANALYTICS_GET_BARS_FAILED",
        "STOCK_ANALYTICS_EARLIEST_PRICE_LOOKUP_FAILED",
        "STOCK_ANALYTICS_PRICE_HISTORY_MISSING",
    }


def test_stock_route_get_stock_analytics_requires_authorization_header(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
) -> None:
    client = _unauthenticated_client(
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get("/stock-analytics/aapl")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid Authorization header"


def test_stock_route_get_stock_analytics_requires_baskt_account(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
) -> None:
    client = _client_without_baskt_account(
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get("/stock-analytics/aapl")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user does not have a Baskt account."
    )


def test_stock_route_get_stock_analytics_rejects_token_alpaca_account_mismatch(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_claims(
        claims=_claims_with_mismatched_alpaca_account(test_user_1),
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get("/stock-analytics/aapl")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user's Alpaca account does not match Baskt account."
    )


def test_stock_route_get_stock_analytics_rejects_token_cognito_user_mismatch(
    alpaca_broker_client: AlpacaBrokerClient,
    stock_analytics_service: StockAnalyticsService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_claims(
        claims=_claims_with_mismatched_cognito_user_id(test_user_1),
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
        stock_analytics_service=stock_analytics_service,
    )

    response = client.get("/stock-analytics/aapl")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user does not have a Baskt account."
    )

"""
Coverage / scenarios:
- get_tradeable_fractionable_us_baskt_assets(): authenticated users with a
  Baskt account can load real tradable/fractionable US stock metadata from the
  backtest analytics route.
- get_tradeable_fractionable_us_baskt_assets(): missing auth, authenticated
  users without a Baskt account, token Alpaca-account mismatches, and unknown
  token Cognito user ids are rejected before assets are loaded.
- backtest(): successful single-stock long, multi-stock long, mixed long/short,
  lowercase-symbol, same-day, and weekend-inclusive backtests return aligned
  timestamps/cumulative returns and all expected metric fields.
- backtest(): timestamps are sorted, stay inside the requested date window,
  and cumulative returns/metrics are finite when present.
- backtest(): rejects empty positions, missing weight even when target_weight
  is supplied, missing required fields, invalid directions, end_date before
  start_date, and unusable market data.
- backtest(): missing auth, users without a Baskt account, token
  Alpaca-account mismatches, and unknown token Cognito user ids are rejected
  before the service runs.
- Not covered: leveraged-position happy paths, duplicate symbols, non-close
  price_col behavior, benchmark-missing internals, or mocked lower-level
  failures.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clients.alpaca_broker_client import AlpacaBrokerClient
from core.authentication import get_current_user
from core.deps import get_backtest_service, get_baskt_account_repository
from repository.baskt_account_repository import BasktAccountRepository
from routes import backtest_analytics_route
from services.asset_analytics_service import AssetAnalyticsService
from services.backtest_analytics_service import BacktestService


pytestmark = pytest.mark.integration


METRIC_FIELDS = {
    "final_cumulative_return",
    "cagr",
    "leverage_adjusted_direction",
    "annualized_volatility",
    "alpha",
    "beta",
    "sharpe_ratio",
    "maximum_drawdown",
    "maximum_drawdown_duration",
}


def _position(
    *,
    symbol: str = "AAPL",
    weight: Any = 1.0,
    direction: Any = 1,
    leverage: Any = 1.0,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "weight": weight,
        "direction": direction,
        "leverage": leverage,
    }


def _backtest_payload(
    *,
    start_date: str = "2024-07-01",
    end_date: str = "2024-07-31",
    positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "start_date": start_date,
        "end_date": end_date,
        "positions": positions if positions is not None else [_position()],
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
    backtest_service: BacktestService,
    baskt_account_repository: BasktAccountRepository,
) -> TestClient:
    app = FastAPI()
    app.include_router(backtest_analytics_route.router)
    if claims is not None:
        app.dependency_overrides[get_current_user] = lambda: claims
    app.dependency_overrides[get_backtest_service] = lambda: backtest_service
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    return TestClient(app)


def _client_for_user(
    *,
    test_user: Any,
    backtest_service: BacktestService,
    baskt_account_repository: BasktAccountRepository,
) -> TestClient:
    return _client_for_claims(
        claims=_claims_for_user(test_user),
        backtest_service=backtest_service,
        baskt_account_repository=baskt_account_repository,
    )


@pytest.fixture(scope="session")
def backtest_service(
    alpaca_broker_client: AlpacaBrokerClient,
    asset_analytics_service: AssetAnalyticsService,
) -> BacktestService:
    return BacktestService(
        alpaca_broker_client=alpaca_broker_client,
        asset_analytics_service=asset_analytics_service,
    )


def _assert_numeric_or_none(value: Any) -> None:
    assert value is None or isinstance(value, (int, float))
    if isinstance(value, (int, float)):
        assert math.isfinite(float(value))


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _assert_backtest_response(
    body: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
) -> None:
    assert body["start_date"] == start_date
    assert body["end_date"] == end_date
    assert set(METRIC_FIELDS).issubset(body)

    timestamps = body["timestamps"]
    cumulative_returns = body["cumulative_returns"]
    assert timestamps
    assert cumulative_returns
    assert len(timestamps) == len(cumulative_returns)

    parsed_timestamps = [_parse_timestamp(timestamp) for timestamp in timestamps]
    assert parsed_timestamps == sorted(parsed_timestamps)
    assert parsed_timestamps[0].date() >= date.fromisoformat(start_date)
    assert parsed_timestamps[-1].date() <= date.fromisoformat(end_date)

    for cumulative_return in cumulative_returns:
        assert isinstance(cumulative_return, (int, float))
        assert math.isfinite(float(cumulative_return))

    for metric in METRIC_FIELDS:
        _assert_numeric_or_none(body[metric])


def test_backtest_analytics_route_get_tradeable_fractionable_assets_happy_path(
    backtest_service: BacktestService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        backtest_service=backtest_service,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.get("/backtest/tradeable-fractionable-us-baskt-assets")

    assert response.status_code == 200
    assets = response.json()
    assert assets
    assert any(asset["symbol"] == "AAPL" for asset in assets)
    for asset in assets:
        assert asset["symbol"]
        assert asset["stock_id"]
        assert asset["tradable"] is True
        assert asset["fractionable"] is True
        assert "shortable" in asset
        assert "marginable" in asset
        assert str(asset["stock_class"]).upper() == "US_EQUITY"


@pytest.mark.parametrize(
    "claims_factory",
    [
        lambda test_user: None,
        lambda test_user: _claims_without_baskt_account(),
        lambda test_user: _claims_with_mismatched_alpaca_account(test_user),
        lambda test_user: _claims_with_mismatched_cognito_user_id(test_user),
    ],
)
def test_backtest_analytics_route_get_tradeable_fractionable_assets_auth_errors(
    backtest_service: BacktestService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    claims_factory,
) -> None:
    claims = claims_factory(test_user_1)
    client = _client_for_claims(
        claims=claims,
        backtest_service=backtest_service,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.get("/backtest/tradeable-fractionable-us-baskt-assets")

    assert response.status_code == (401 if claims is None else 403)


@pytest.mark.parametrize(
    ("payload", "start_date", "end_date"),
    [
        (
            _backtest_payload(
                positions=[_position(symbol="AAPL", weight=1.0, direction=1)]
            ),
            "2024-07-01",
            "2024-07-31",
        ),
        (
            _backtest_payload(
                positions=[
                    _position(symbol="AAPL", weight=0.4, direction=1),
                    _position(symbol="MSFT", weight=0.35, direction=1),
                    _position(symbol="GOOG", weight=0.25, direction=1),
                ]
            ),
            "2024-07-01",
            "2024-07-31",
        ),
        (
            _backtest_payload(
                positions=[
                    _position(symbol="AAPL", weight=0.6, direction=1),
                    _position(symbol="MSFT", weight=0.4, direction=-1),
                ]
            ),
            "2024-07-01",
            "2024-07-31",
        ),
        (
            _backtest_payload(
                positions=[_position(symbol="aapl", weight=1.0, direction=1)]
            ),
            "2024-07-01",
            "2024-07-31",
        ),
        (
            _backtest_payload(
                start_date="2024-07-05",
                end_date="2024-07-05",
                positions=[_position(symbol="AAPL", weight=1.0, direction=1)],
            ),
            "2024-07-05",
            "2024-07-05",
        ),
        (
            _backtest_payload(
                start_date="2024-07-05",
                end_date="2024-07-08",
                positions=[_position(symbol="AAPL", weight=1.0, direction=1)],
            ),
            "2024-07-05",
            "2024-07-08",
        ),
    ],
)
def test_backtest_analytics_route_backtest_happy_paths(
    backtest_service: BacktestService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    payload: dict[str, Any],
    start_date: str,
    end_date: str,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        backtest_service=backtest_service,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.post("/backtest", json=payload)

    assert response.status_code == 200
    _assert_backtest_response(
        response.json(),
        start_date=start_date,
        end_date=end_date,
    )


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        (_backtest_payload(positions=[]), 422),
        (
            _backtest_payload(
                start_date="2024-07-31",
                end_date="2024-07-01",
                positions=[_position()],
            ),
            422,
        ),
        (
            _backtest_payload(
                positions=[
                    {
                        "symbol": "AAPL",
                        "target_weight": 1.0,
                        "direction": 1,
                    }
                ]
            ),
            422,
        ),
        (_backtest_payload(positions=[{"weight": 1.0, "direction": 1}]), 422),
        (_backtest_payload(positions=[{"symbol": "AAPL", "direction": 1}]), 422),
        (_backtest_payload(positions=[{"symbol": "AAPL", "weight": 1.0}]), 422),
        (_backtest_payload(positions=[_position(direction=0)]), 422),
        (_backtest_payload(positions=[_position(direction=2)]), 422),
        (
            _backtest_payload(
                positions=[_position(symbol="NOTAREALBASKTTESTSYMBOL")]
            ),
            502,
        ),
    ],
)
def test_backtest_analytics_route_backtest_validation_and_data_errors(
    backtest_service: BacktestService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    payload: dict[str, Any],
    expected_status: int,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        backtest_service=backtest_service,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.post("/backtest", json=payload)

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "claims_factory",
    [
        lambda test_user: None,
        lambda test_user: _claims_without_baskt_account(),
        lambda test_user: _claims_with_mismatched_alpaca_account(test_user),
        lambda test_user: _claims_with_mismatched_cognito_user_id(test_user),
    ],
)
def test_backtest_analytics_route_backtest_auth_errors(
    backtest_service: BacktestService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    claims_factory,
) -> None:
    claims = claims_factory(test_user_1)
    client = _client_for_claims(
        claims=claims,
        backtest_service=backtest_service,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.post("/backtest", json=_backtest_payload())

    assert response.status_code == (401 if claims is None else 403)

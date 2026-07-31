from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pytest

from core.deps import get_backtest_service
from routes.backtest_route import router as backtest_router
from services.backtest_analytics_service import BacktestServiceValidationError


@dataclass(frozen=True)
class FakeAsset:
    symbol: str = "AAPL"
    tradable: bool = True
    fractionable: bool = True
    shortable: bool = True
    marginable: bool = True
    stock_id: str = "asset-aapl"
    stock_class: str = "us_equity"


class FakeBacktestService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.assets_called = False
        self.run_calls: list[dict[str, Any]] = []

    def get_tradeable_fractionable_US_baskt_assets(self):
        self.assets_called = True
        return [FakeAsset()]

    def run_backtest(self, **kwargs: Any) -> dict[str, Any]:
        self.run_calls.append(kwargs)
        if self.fail:
            raise BacktestServiceValidationError("invalid backtest")
        return {
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 1, 31),
            "timestamps": [datetime(2024, 1, 2, tzinfo=timezone.utc)],
            "cumulative_returns": [0.05],
            "final_cumulative_return": 0.05,
            "cagr": 0.12,
            "leverage_adjusted_direction": 1.0,
            "annualized_volatility": 0.2,
            "alpha": 0.01,
            "beta": 1.1,
            "sharpe_ratio": 0.8,
            "maximum_drawdown": -0.03,
            "maximum_drawdown_duration": 2.0,
        }


@pytest.fixture
def backtest_app(app_factory):
    app = app_factory(backtest_router)
    service = FakeBacktestService()
    app.dependency_overrides[get_backtest_service] = lambda: service
    return {"app": app, "service": service}


@pytest.fixture
def backtest_client(backtest_app, client_for_app):
    with client_for_app(backtest_app["app"]) as client:
        yield client


def test_backtest_routes_return_assets_and_backtest_results(
    backtest_client,
    backtest_app,
) -> None:
    assets_response = backtest_client.get(
        "/backtest/tradeable-fractionable-us-baskt-assets"
    )
    assert assets_response.status_code == 200, assets_response.text
    assert assets_response.json()[0]["symbol"] == "AAPL"

    backtest_response = backtest_client.post(
        "/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "positions": [
                {
                    "symbol": "AAPL",
                    "weight": 1.0,
                    "direction": 1,
                    "leverage": 1.0,
                }
            ],
        },
    )

    assert backtest_response.status_code == 200, backtest_response.text
    assert backtest_response.json()["final_cumulative_return"] == 0.05
    assert backtest_app["service"].run_calls == [
        {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "positions_conf": [
                {
                    "symbol": "AAPL",
                    "weight": 1.0,
                    "direction": 1,
                    "leverage": 1.0,
                }
            ],
        }
    ]


def test_backtest_route_maps_validation_errors(backtest_client, backtest_app) -> None:
    backtest_app["app"].dependency_overrides[get_backtest_service] = (
        lambda: FakeBacktestService(fail=True)
    )

    response = backtest_client.post(
        "/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "positions": [
                {
                    "symbol": "AAPL",
                    "weight": 1.0,
                    "direction": 1,
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "BACKTEST_SERVICE_VALIDATION_ERROR"

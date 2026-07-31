from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.deps import get_stock_analytics_service
from routes.stock_analytics_route import router as stock_analytics_router
from services.stock_analytics_service import StockAnalyticsInternalServerError


class FakeStockAnalyticsService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def get_stock_bars(self, symbol: str):
        if self.fail:
            raise StockAnalyticsInternalServerError("stock analytics failed")
        return {
            "1M": {
                "timeframe": "1M",
                "timestamp": [datetime(2024, 1, 2, tzinfo=timezone.utc)],
                "prices": [100.0],
                "final_cumulative_return": 0.02,
                "cagr": None,
                "annualized_volatility": None,
                "leverage_adjusted_direction": None,
                "alpha": None,
                "beta": None,
                "sharpe_ratio": None,
                "maximum_drawdown": None,
                "maximum_drawdown_duration": None,
            }
        }


@pytest.fixture
def stock_analytics_app(app_factory):
    app = app_factory(stock_analytics_router)
    app.dependency_overrides[get_stock_analytics_service] = (
        lambda: FakeStockAnalyticsService()
    )
    return app


@pytest.fixture
def stock_analytics_client(stock_analytics_app, client_for_app):
    with client_for_app(stock_analytics_app) as client:
        yield client


def test_stock_analytics_route_returns_periods_and_maps_errors(
    stock_analytics_client,
    stock_analytics_app,
) -> None:
    response = stock_analytics_client.get("/stock-analytics/aapl")
    assert response.status_code == 200, response.text
    assert response.json()["1M"]["prices"] == [100.0]

    stock_analytics_app.dependency_overrides[get_stock_analytics_service] = (
        lambda: FakeStockAnalyticsService(fail=True)
    )
    error_response = stock_analytics_client.get("/stock-analytics/aapl")
    assert error_response.status_code == 500
    assert error_response.json()["detail"]["code"] == "STOCK_ANALYTICS_SERVICE_ERROR"

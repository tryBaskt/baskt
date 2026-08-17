from __future__ import annotations

import pytest

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.vectorbt_client import VectorBTClient
from clients.yfinance_client import YFinanceClient
from core import deps as app_deps
from services.asset_analytics_service import AssetAnalyticsService
from services.stock_analytics_service import StockAnalyticsService


@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def yfinance_client() -> YFinanceClient:
    return app_deps.get_yfinance_client()


@pytest.fixture(scope="session")
def vectorbt_client() -> VectorBTClient:
    return app_deps.get_vectorbt_client()


@pytest.fixture(scope="session")
def asset_analytics_service(
    alpaca_broker_client: AlpacaBrokerClient,
    yfinance_client: YFinanceClient,
    vectorbt_client: VectorBTClient,
) -> AssetAnalyticsService:
    return app_deps.get_asset_analytics_service(
        alpaca_broker_client=alpaca_broker_client,
        yfinance_client=yfinance_client,
        vectorbt_client=vectorbt_client,
    )


@pytest.fixture(scope="session")
def stock_analytics_service(
    asset_analytics_service: AssetAnalyticsService,
) -> StockAnalyticsService:
    return app_deps.get_stock_analytics_service(
        asset_analytics_service=asset_analytics_service,
    )

import sys
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
from typing import Dict, List

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[4]
backend_dir = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

load_dotenv(repo_root / ".env")

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.dynamodb_client import DynamoDBClient
from clients.vectorbt_client import VectorBTClient
from clients.yfinance_client import YFinanceClient
from core import deps as app_deps
from core.config import get_settings
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.asset_analytics_service import AssetAnalyticsService
from services.backtest_analytics_service import BacktestService
from services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsService,
)
from services.stock_analytics_service import StockAnalyticsService


get_settings.cache_clear()


ALPACA_IEX_HISTORY_START = datetime(2021, 1, 1, tzinfo=timezone.utc)


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
def model_portfolio_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository() -> ModelPortfolioUpdateLockRepository:
    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=(
            app_deps.get_model_portfolio_update_lock_dynamodb_client()
        )
    )


@pytest.fixture(scope="session")
def model_portfolio_follower_repository(
    alpaca_broker_client: AlpacaBrokerClient,
) -> ModelPortfolioFollowerRepository:
    return app_deps.get_model_portfolio_follower_repository(
        model_portfolio_follower_dynamodb_client=(
            app_deps.get_model_portfolio_follower_dynamodb_client()
        ),
        alpaca_broker_client=alpaca_broker_client,
    )


@pytest.fixture(scope="session")
def model_portfolio_repository(
    model_portfolio_dynamodb_client: DynamoDBClient,
    alpaca_broker_client: AlpacaBrokerClient,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
) -> ModelPortfolioRepository:
    return app_deps.get_model_portfolio_repository(
        dynamodb=model_portfolio_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=(
            model_portfolio_update_lock_repository
        ),
        model_portfolio_follower_repository=(
            model_portfolio_follower_repository
        ),
    )


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
def backtest_service(
    alpaca_broker_client: AlpacaBrokerClient,
    asset_analytics_service: AssetAnalyticsService,
) -> BacktestService:
    return app_deps.get_backtest_service(
        alpaca_broker_client=alpaca_broker_client,
        asset_analytics_service=asset_analytics_service,
    )


@pytest.fixture(scope="session")
def stock_analytics_service(
    asset_analytics_service: AssetAnalyticsService,
) -> StockAnalyticsService:
    return app_deps.get_stock_analytics_service(
        asset_analytics_service=asset_analytics_service,
    )


@pytest.fixture(scope="session")
def model_portfolio_analytics_service(
    model_portfolio_repository: ModelPortfolioRepository,
    asset_analytics_service: AssetAnalyticsService,
) -> ModelPortfolioAnalyticsService:
    return app_deps.get_model_portfolio_analytics_service(
        model_portfolio_repository=model_portfolio_repository,
        asset_analytics_service=asset_analytics_service,
    )


class TestEngine:
    __test__ = False

    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        yfinance_client: YFinanceClient,
        model_portfolio_repository: ModelPortfolioRepository,
        backtest_service: BacktestService,
        stock_analytics_service: StockAnalyticsService,
        model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    ) -> None:
        self.alpaca_broker_client = alpaca_broker_client
        self.yfinance_client = yfinance_client
        self.model_portfolio_repository = model_portfolio_repository
        self.backtest_service = backtest_service
        self.stock_analytics_service = stock_analytics_service
        self.model_portfolio_analytics_service = (
            model_portfolio_analytics_service
        )

    def get_earliest_analytics_compatible_stock_timestamp(
        self,
        *,
        symbol: str,
    ) -> datetime:
        prices = self.yfinance_client.get_stock_prices_over_time(
            symbols=[symbol],
            start_datetime=ALPACA_IEX_HISTORY_START,
            end_datetime=datetime.now(timezone.utc),
            timeframe="1D",
        )
        if prices.empty:
            raise AssertionError(
                f"No yfinance price history found for {symbol} after "
                f"{ALPACA_IEX_HISTORY_START.isoformat()}."
            )

        for timestamp in prices.index[:90]:
            candidate_timestamp = timestamp.to_pydatetime() + timedelta(hours=21)
            try:
                self.alpaca_broker_client.get_stock_prices_at_time(
                    symbols=[symbol],
                    timestamp=candidate_timestamp,
                )
                return candidate_timestamp
            except Exception:
                continue

        raise AssertionError(
            f"No Alpaca-compatible point-in-time price found for {symbol} "
            "near the earliest yfinance history window."
        )

    def create_single_stock_model_portfolio(
        self,
        *,
        symbol: str,
        creation_time: datetime,
    ) -> str:
        return self.model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id="analytics-integration-test-owner",
            portfolio_name=f"{symbol} Analytics Integration Test",
            positions_request=[
                ModelPortfolioPositionRequest(
                    symbol=symbol,
                    target_weight=1.0,
                    direction=1,
                    leverage=1.0,
                )
            ],
            creation_time=creation_time,
            description=(
                "Created by analytics integration test and deleted during "
                "test cleanup."
            ),
        )

    def get_stock_metrics(
        self,
        *,
        symbol: str,
        current_datetime: datetime,
    ) -> Dict:
        return self.stock_analytics_service.get_stock_bars(
            symbol=symbol,
            current_datetime=current_datetime,
        )

    def get_backtest_metrics(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Dict:
        return self.backtest_service.run_backtest(
            start_date=start_date,
            end_date=end_date,
            positions_conf=[
                {
                    "symbol": symbol,
                    "weight": 1.0,
                    "direction": 1,
                    "leverage": 1.0,
                }
            ],
        )

    def get_model_portfolio_metrics(
        self,
        *,
        portfolio_id: str,
        current_datetime: datetime,
    ) -> Dict:
        return self.model_portfolio_analytics_service.get_model_portfolio_bars(
            portfolio_id=portfolio_id,
            current_datetime=current_datetime,
        )

    def delete_model_portfolio(self, *, portfolio_id: str) -> None:
        self.model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )


@pytest.fixture(scope="session")
def test_engine(
    alpaca_broker_client: AlpacaBrokerClient,
    yfinance_client: YFinanceClient,
    model_portfolio_repository: ModelPortfolioRepository,
    backtest_service: BacktestService,
    stock_analytics_service: StockAnalyticsService,
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> TestEngine:
    return TestEngine(
        alpaca_broker_client=alpaca_broker_client,
        yfinance_client=yfinance_client,
        model_portfolio_repository=model_portfolio_repository,
        backtest_service=backtest_service,
        stock_analytics_service=stock_analytics_service,
        model_portfolio_analytics_service=model_portfolio_analytics_service,
    )

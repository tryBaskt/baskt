import os
import sys
from pathlib import Path
from typing import List
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

load_dotenv(repo_root / ".env")
os.environ["ENV"] = "dev"

from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.dynamodb_client import DynamoDBClient
from backend.clients.yfinance_client import YFinanceClient
from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from backend.repository.model_portfolio_repository import ModelPortfolioRepository
from backend.repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from backend.services.backtest_service import BacktestService
from backend.services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsService,
)
from backend.schema.model_portfolio_schema import ModelPortfolioPositionRequest



get_settings.cache_clear()


#######################################
############### CLIENTS ###############
#######################################

@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def yfinance_client() -> YFinanceClient:
    return app_deps.get_yfinance_client()


@pytest.fixture(scope="session")
def model_portfolio_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_follower_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_follower_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_update_lock_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_update_lock_dynamodb_client()


########################################
############## REPOSITORIES ############
########################################

@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository(
    model_portfolio_update_lock_dynamodb_client: DynamoDBClient,
) -> ModelPortfolioUpdateLockRepository:
    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=(
            model_portfolio_update_lock_dynamodb_client
        )
    )


@pytest.fixture(scope="session")
def model_portfolio_follower_repository(
    model_portfolio_follower_dynamodb_client: DynamoDBClient,
    alpaca_broker_client: AlpacaBrokerClient,
) -> ModelPortfolioFollowerRepository:
    return app_deps.get_model_portfolio_follower_repository(
        model_portfolio_follower_dynamodb_client=(
            model_portfolio_follower_dynamodb_client
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
        model_portfolio_follower_repository=model_portfolio_follower_repository,
    )


#######################################
############## SERVICES ###############
#######################################

@pytest.fixture(scope="session")
def backtest_service(
    yfinance_client: YFinanceClient,
    alpaca_broker_client: AlpacaBrokerClient,
) -> BacktestService:
    return app_deps.get_backtest_service(
        yfinance_client=yfinance_client,
        alpaca_broker_client=alpaca_broker_client,
    )


@pytest.fixture(scope="session")
def model_portfolio_analytics_service(
    alpaca_broker_client: AlpacaBrokerClient,
    model_portfolio_repository: ModelPortfolioRepository,
) -> ModelPortfolioAnalyticsService:
    return app_deps.get_model_portfolio_analytics_service(
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_repository=model_portfolio_repository,
    )


###########################################
############### TEST ENGINE ###############
###########################################

class TestEngine:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        backtest_service: BacktestService,
        model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
        model_portfolio_repository: ModelPortfolioRepository,
        yfinance_client: YFinanceClient,
    ) -> None:
        self.alpaca_broker_client = alpaca_broker_client
        self.backtest_service = backtest_service
        self.model_portfolio_analytics_service = model_portfolio_analytics_service
        self.model_portfolio_repository = model_portfolio_repository
        self.yfinance_client = yfinance_client

    def test_delete_portfolio(
        self,
        portfolio_id: str
    ):
        self.model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )

    def test_create_portfolio(
        self,
        symbols: List[str],
        directions: List[int],
        target_weights: List[float],
        leverages: List[float],
        portfolio_name: str,
        portfolio_owner_cognito_user_id: str,
        creation_time: datetime
    ):

        positions_request: List[ModelPortfolioPositionRequest] = [
            ModelPortfolioPositionRequest(symbol=s, target_weight=w, direction=d, leverage=l)
            for s, w, d, l in zip(symbols, target_weights, directions, leverages)
        ]
        portfolio_id = self.model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            portfolio_name=portfolio_name,
            positions_request=positions_request,
            creation_time=creation_time
        )

        model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
        assert model_portfolio is not None
        model_snapshot = model_portfolio.position_history[-1]
        for test_position, model_position in zip(sorted(positions_request, key = lambda x: x.symbol),sorted(model_snapshot.positions, key = lambda x: x.symbol)):
            assert test_position.direction == model_position.direction
            assert test_position.leverage == model_position.leverage
            assert test_position.symbol == model_position.symbol
            assert test_position.target_weight == model_position.target_weight

        return portfolio_id


@pytest.fixture(scope="session")
def test_engine(
    alpaca_broker_client: AlpacaBrokerClient,
    backtest_service: BacktestService,
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    yfinance_client: YFinanceClient,
) -> TestEngine:
    return TestEngine(
        alpaca_broker_client=alpaca_broker_client,
        backtest_service=backtest_service,
        model_portfolio_analytics_service=model_portfolio_analytics_service,
        model_portfolio_repository=model_portfolio_repository,
        yfinance_client=yfinance_client,
    )

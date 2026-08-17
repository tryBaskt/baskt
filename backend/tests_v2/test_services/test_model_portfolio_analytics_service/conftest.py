from __future__ import annotations

import pytest

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from clients.dynamodb_client import DynamoDBClient
from clients.vectorbt_client import VectorBTClient
from clients.yfinance_client import YFinanceClient
from core import deps as app_deps
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from services.asset_analytics_service import AssetAnalyticsService
from services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsService,
)


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
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()


@pytest.fixture(scope="session")
def model_portfolio_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_access_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_access_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_follower_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_follower_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_update_lock_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_update_lock_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_update_lock_repository(
    model_portfolio_update_lock_dynamodb_client: DynamoDBClient,
) -> ModelPortfolioUpdateLockRepository:
    return app_deps.get_model_portfolio_update_lock_repository(
        model_portfolio_update_lock_dynamodb_client=(
            model_portfolio_update_lock_dynamodb_client
        ),
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
def model_portfolio_access_repository(
    model_portfolio_access_dynamodb_client: DynamoDBClient,
    cognito_client: CognitoClient,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> ModelPortfolioAccessRepository:
    return app_deps.get_model_portfolio_access_repository(
        model_portfolio_access_dynamodb_client=(
            model_portfolio_access_dynamodb_client
        ),
        cognito_client=cognito_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=(
            model_portfolio_update_lock_repository
        ),
    )


@pytest.fixture(scope="session")
def model_portfolio_repository(
    model_portfolio_dynamodb_client: DynamoDBClient,
    alpaca_broker_client: AlpacaBrokerClient,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
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
        model_portfolio_access_repository=model_portfolio_access_repository,
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
def model_portfolio_analytics_service(
    model_portfolio_repository: ModelPortfolioRepository,
    asset_analytics_service: AssetAnalyticsService,
) -> ModelPortfolioAnalyticsService:
    return app_deps.get_model_portfolio_analytics_service(
        model_portfolio_repository=model_portfolio_repository,
        asset_analytics_service=asset_analytics_service,
    )

from __future__ import annotations

from typing import Any

import pytest

from backend.tests_v2.mock_alpaca.trading import (
    MockSQSClient,
    MockTradeExecutionLambda,
    build_mock_alpaca_broker_client,
)
from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from clients.dynamodb_client import DynamoDBClient
from clients.opensearch_client import OpenSearchClient
from clients.vectorbt_client import VectorBTClient
from clients.yfinance_client import YFinanceClient
from core import deps as app_deps
from repository.baskt_account_repository import BasktAccountRepository
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
from repository.allocation_repository import AllocationRepository
from repository.order_repository import OrderRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from services.account_lifecycle_service import AccountLifecycleService
from services.asset_analytics_service import AssetAnalyticsService
from services.explore_search_service import ExploreSearchService
from services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsService,
)
from services.stock_analytics_service import StockAnalyticsService
from services.trade_execution_queuing_service import TradeExecutionQueuingService
from services.trade_execution_service import TradeExecutionService


@pytest.fixture(scope="session")
def alpaca_broker_client(request, test_user_2) -> AlpacaBrokerClient:
    if request.config.getoption("--mock_alpaca"):
        return build_mock_alpaca_broker_client(
            real_client=app_deps.get_alpaca_broker_client(),
            prices={
                "AAPL": 200.0,
                "MSFT": 100.0,
                "AMZN": 180.0,
                "META": 450.0,
                "TSLA": 170.0,
                "NVDA": 900.0,
                "GOOG": 160.0,
                "AMD": 160.0,
                "PLTR": 25.0,
                "SPY": 500.0,
                "QQQ": 430.0,
                "UBER": 100.0,
                "LLY": 95.0,
            },
            funded_1000_alpaca_account_id=test_user_2.alpaca_account_id,
        )
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def sqs_client(request) -> Any:
    if request.config.getoption("--mock_alpaca"):
        return MockSQSClient()
    return app_deps.get_sqs_client_cached()


@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()


@pytest.fixture(scope="session")
def opensearch_client() -> OpenSearchClient:
    return app_deps.get_opensearch_client()


@pytest.fixture(scope="session")
def yfinance_client() -> YFinanceClient:
    return app_deps.get_yfinance_client()


@pytest.fixture(scope="session")
def vectorbt_client() -> VectorBTClient:
    return app_deps.get_vectorbt_client()


@pytest.fixture(scope="session")
def baskt_account_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_baskt_account_dynamodb_client()


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
def allocation_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_allocation_dynamodb_client()


@pytest.fixture(scope="session")
def order_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_order_dynamodb_client()


@pytest.fixture(scope="session")
def user_trade_lock_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_user_trade_lock_dynamodb_client()


@pytest.fixture(scope="session")
def baskt_account_repository(
    baskt_account_dynamodb_client: DynamoDBClient,
) -> BasktAccountRepository:
    return app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=baskt_account_dynamodb_client,
    )


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
def allocation_repository(
    alpaca_broker_client: AlpacaBrokerClient,
    allocation_dynamodb_client: DynamoDBClient,
) -> AllocationRepository:
    return app_deps.get_allocation_repository(
        alpaca_broker_client=alpaca_broker_client,
        allocation_dynamodb_client=allocation_dynamodb_client,
    )


@pytest.fixture(scope="session")
def order_repository(
    alpaca_broker_client: AlpacaBrokerClient,
    order_dynamodb_client: DynamoDBClient,
) -> OrderRepository:
    return app_deps.get_order_repository(
        alpaca_broker_client=alpaca_broker_client,
        order_dynamodb_client=order_dynamodb_client,
    )


@pytest.fixture(scope="session")
def user_trade_lock_repository(
    user_trade_lock_dynamodb_client: DynamoDBClient,
) -> UserTradeLockRepository:
    return app_deps.get_user_trade_lock_repository(
        user_trade_lock_dynamodb_client=user_trade_lock_dynamodb_client,
    )


@pytest.fixture(scope="session")
def account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    baskt_account_repository: BasktAccountRepository,
) -> AccountLifecycleService:
    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        baskt_account_repository=baskt_account_repository,
    )


@pytest.fixture(scope="session")
def trade_execution_service(
    model_portfolio_repository: ModelPortfolioRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    user_trade_lock_repository: UserTradeLockRepository,
) -> TradeExecutionService:
    return app_deps.get_trade_execution_service(
        model_portfolio_repository=model_portfolio_repository,
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
    )


@pytest.fixture(scope="session")
def trade_execution_queuing_service(
    sqs_client: Any,
    trade_execution_service: TradeExecutionService,
    model_portfolio_repository: ModelPortfolioRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    allocation_repository: AllocationRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
) -> TradeExecutionQueuingService:
    queue_url = (
        sqs_client.queue_url
        if isinstance(sqs_client, MockSQSClient)
        else app_deps.get_trade_execution_queue_url()
    )
    if isinstance(sqs_client, MockSQSClient):
        sqs_client.set_lambda_handler(
            MockTradeExecutionLambda(
                trade_execution_service=trade_execution_service,
                user_trade_lock_repository=user_trade_lock_repository,
            )
        )
    return TradeExecutionQueuingService(
        sqs_client=sqs_client,
        queue_url=queue_url,
        model_portfolio_repository=model_portfolio_repository,
        allocation_repository=allocation_repository,
        alpaca_broker_client=alpaca_broker_client,
        user_trade_lock_repository=user_trade_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
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


@pytest.fixture(scope="session")
def stock_analytics_service(
    asset_analytics_service: AssetAnalyticsService,
) -> StockAnalyticsService:
    return app_deps.get_stock_analytics_service(
        asset_analytics_service=asset_analytics_service,
    )


@pytest.fixture(scope="session")
def explore_search_service(
    opensearch_client: OpenSearchClient,
    alpaca_broker_client: AlpacaBrokerClient,
    baskt_account_repository: BasktAccountRepository,
) -> ExploreSearchService:
    return app_deps.get_explore_search_service(
        opensearch_client=opensearch_client,
        alpaca_broker_client=alpaca_broker_client,
        baskt_account_repository=baskt_account_repository,
    )

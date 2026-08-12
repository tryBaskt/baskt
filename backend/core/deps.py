# backend/core/deps.py

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict

import boto3
from fastapi import Depends

from core.config import Settings, get_settings
from clients.yfinance_client import YFinanceClient
from services.backtest_analytics_service import BacktestService
from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from clients.dynamodb_client import DynamoDBClient
from clients.opensearch_client import OpenSearchClient
from clients.vectorbt_client import VectorBTClient
from repository.model_portfolio_repository import ModelPortfolioRepository
from services.trade_execution_service import TradeExecutionService
from repository.allocation_repository import AllocationRepository
from repository.order_repository import OrderRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.model_portfolio_access_repository import ModelPortfolioAccessRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from repository.baskt_account_repository import BasktAccountRepository
from services.account_lifecycle_service import AccountLifecycleService
from services.allocation_analytics_service import AllocationAnalyticsService
from services.asset_analytics_service import AssetAnalyticsService
from services.model_portfolio_analytics_service import ModelPortfolioAnalyticsService
from services.explore_search_service import ExploreSearchService
from services.stock_analytics_service import StockAnalyticsService
from services.trade_execution_queuing_service import TradeExecutionQueuingService

# -----------------------------
# Settings (cached by lru_cache in config.py)
# -----------------------------

def settings_dep() -> Settings:
    return get_settings()

# -----------------------------
# AWS
# -----------------------------

@lru_cache
def get_boto3_session() -> boto3.Session:
    """
    Cache session globally. Do NOT accept Settings as an argument (unhashable).
    """
    s = get_settings()

    kwargs: Dict[str, Any] = {"region_name": s.aws_region}

    # Local dev only; on AWS rely on IAM role
    if s.aws_access_key_id and s.aws_secret_access_key:
        kwargs.update(
            aws_access_key_id=s.aws_access_key_id,
            aws_secret_access_key=s.aws_secret_access_key,
        )
        if s.aws_session_token:
            kwargs["aws_session_token"] = s.aws_session_token

    return boto3.Session(**kwargs)

@lru_cache
def get_dynamodb_resource_cached() -> Any:
    s = get_settings()
    session = get_boto3_session()
    return session.resource("dynamodb", region_name=s.aws_region)

@lru_cache
def get_cognito_idp_client_cached() -> Any:
    s = get_settings()
    session = get_boto3_session()
    return session.client("cognito-idp", region_name=s.cognito_region)

@lru_cache
def get_sqs_client_cached() -> Any:
    s = get_settings()
    session = get_boto3_session()
    return session.client("sqs", region_name=s.aws_region)

# -----------------------------
# Clients
# -----------------------------

@lru_cache
def get_model_portfolio_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.model_portfolios_dynamodb))

@lru_cache
def get_allocation_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.allocation_dynamodb))

@lru_cache
def get_order_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.order_dynamodb))

@lru_cache
def get_model_portfolio_follower_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.model_portfolio_follower_dynamodb))

@lru_cache
def get_model_portfolio_access_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.model_portfolio_access_dynamodb))

@lru_cache
def get_user_trade_lock_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.user_trade_lock_dynamodb))

@lru_cache
def get_model_portfolio_update_lock_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.model_portfolio_update_lock_dynamodb))

@lru_cache
def get_baskt_account_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.baskt_account_dynamodb))

@lru_cache
def get_yfinance_client() -> YFinanceClient:
    return YFinanceClient()


@lru_cache
def get_vectorbt_client() -> VectorBTClient:
    return VectorBTClient()

@lru_cache
def get_alpaca_broker_client() -> AlpacaBrokerClient:
    s = get_settings()
    return AlpacaBrokerClient(
        alpaca_broker_api_key=s.alpaca_broker_api_key,
        alpaca_broker_api_secret=s.alpaca_broker_api_secret,
        alpaca_env=s.alpaca_env
    )

@lru_cache
def get_cognito_client() -> CognitoClient:
    s = get_settings()
    cognito_idp_client = get_cognito_idp_client_cached()
    return CognitoClient(
        env=s.env,
        region=s.cognito_region,
        user_pool_id=s.cognito_user_pool_id,
        app_client_id=s.cognito_app_client_id,
        cognito_client=cognito_idp_client,
    )

@lru_cache
def get_opensearch_client() -> OpenSearchClient:
    s = get_settings()
    return OpenSearchClient(
        session=get_boto3_session(),
        region=s.aws_region,
        domain_name=s.opensearch_domain_name,
        index_name=s.model_portfolio_search_index,
    )

# -----------------------------
# Repository
# -----------------------------
@lru_cache
def get_baskt_account_repository(
    baskt_account_dynamodb_client: DynamoDBClient = Depends(
        get_baskt_account_dynamodb_client
    ),
) -> BasktAccountRepository:
    return BasktAccountRepository(
        dynamodb_client=baskt_account_dynamodb_client
    )

@lru_cache
def get_model_portfolio_update_lock_repository(
    model_portfolio_update_lock_dynamodb_client: DynamoDBClient = Depends(get_model_portfolio_update_lock_dynamodb_client)
) -> ModelPortfolioUpdateLockRepository:
    return ModelPortfolioUpdateLockRepository(dynamodb_client = model_portfolio_update_lock_dynamodb_client)

@lru_cache
def get_model_portfolio_follower_repository(
    model_portfolio_follower_dynamodb_client: DynamoDBClient = Depends(get_model_portfolio_follower_dynamodb_client),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client)
) -> ModelPortfolioFollowerRepository:
    return ModelPortfolioFollowerRepository(dynamodb_client=model_portfolio_follower_dynamodb_client, alpaca_broker_client=alpaca_broker_client)

@lru_cache
def get_model_portfolio_access_repository(
    model_portfolio_access_dynamodb_client: DynamoDBClient = Depends(
        get_model_portfolio_access_dynamodb_client
    ),
    cognito_client: CognitoClient = Depends(get_cognito_client),
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository = Depends(
        get_model_portfolio_follower_repository
    ),
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository = Depends(
        get_model_portfolio_update_lock_repository
    ),
) -> ModelPortfolioAccessRepository:
    return ModelPortfolioAccessRepository(
        dynamodb_client=model_portfolio_access_dynamodb_client,
        cognito_client=cognito_client,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
    )

@lru_cache
def get_model_portfolio_repository(
    dynamodb: DynamoDBClient = Depends(get_model_portfolio_dynamodb_client),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository = Depends(get_model_portfolio_update_lock_repository),
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository = Depends(get_model_portfolio_follower_repository),
    model_portfolio_access_repository: ModelPortfolioAccessRepository = Depends(get_model_portfolio_access_repository),
) -> ModelPortfolioRepository:
    return ModelPortfolioRepository(
        dynamodb_client=dynamodb,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
    )

@lru_cache
def get_allocation_repository(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    allocation_dynamodb_client: DynamoDBClient = Depends(get_allocation_dynamodb_client),
) -> AllocationRepository:
    return AllocationRepository(
        alpaca_broker_client=alpaca_broker_client,
        dynamodb_client=allocation_dynamodb_client,
    )

@lru_cache
def get_order_repository(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    order_dynamodb_client: DynamoDBClient = Depends(get_order_dynamodb_client),
) -> OrderRepository:
    return OrderRepository(alpaca_broker_client=alpaca_broker_client, dynamodb_client=order_dynamodb_client)

@lru_cache
def get_user_trade_lock_repository(
    user_trade_lock_dynamodb_client: DynamoDBClient = Depends(get_user_trade_lock_dynamodb_client)
) -> UserTradeLockRepository:
    return UserTradeLockRepository(dynamodb_client=user_trade_lock_dynamodb_client)

# -----------------------------
# Services
# -----------------------------

@lru_cache
def get_asset_analytics_service(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    yfinance_client: YFinanceClient = Depends(get_yfinance_client),
    vectorbt_client: VectorBTClient = Depends(get_vectorbt_client),
) -> AssetAnalyticsService:
    return AssetAnalyticsService(
        alpaca_broker_client=alpaca_broker_client,
        yfinance_client=yfinance_client,
        vectorbt_client=vectorbt_client,
    )

@lru_cache
def get_backtest_service(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    asset_analytics_service: AssetAnalyticsService = Depends(
        get_asset_analytics_service
    ),
) -> BacktestService:
    return BacktestService(
        alpaca_broker_client=alpaca_broker_client,
        asset_analytics_service=asset_analytics_service,
    )

@lru_cache
def get_account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    cognito_client: CognitoClient = Depends(get_cognito_client),
    baskt_account_repository: BasktAccountRepository = Depends(
        get_baskt_account_repository
    ),
) -> AccountLifecycleService:
    return AccountLifecycleService(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        baskt_account_repository=baskt_account_repository,
    )

@lru_cache
def get_trade_execution_service(
    model_portfolio_repository: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    allocation_repository: AllocationRepository = Depends(get_allocation_repository),
    order_repository: OrderRepository = Depends(get_order_repository),
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository = Depends(get_model_portfolio_follower_repository),
    user_trade_lock_repository: UserTradeLockRepository = Depends(get_user_trade_lock_repository),
) -> TradeExecutionService:
    return TradeExecutionService(
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_repository=model_portfolio_repository,
        allocation_repository=allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository
    )

@lru_cache
def get_trade_execution_queue_url() -> str:
    s = get_settings()
    if s.trade_execution_queue_url:
        return s.trade_execution_queue_url

    sqs_client = get_sqs_client_cached()
    response = sqs_client.get_queue_url(
        QueueName=s.trade_execution_queue_name,
    )
    return str(response["QueueUrl"])

@lru_cache
def get_trade_execution_queuing_service(
    sqs_client: Any = Depends(get_sqs_client_cached),
    model_portfolio_repository: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
    allocation_repository: AllocationRepository = Depends(get_allocation_repository),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    user_trade_lock_repository: UserTradeLockRepository = Depends(get_user_trade_lock_repository),
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository = Depends(get_model_portfolio_follower_repository),
) -> TradeExecutionQueuingService:
    return TradeExecutionQueuingService(
        sqs_client=sqs_client,
        queue_url=get_trade_execution_queue_url(),
        model_portfolio_repository=model_portfolio_repository,
        allocation_repository=allocation_repository,
        alpaca_broker_client=alpaca_broker_client,
        user_trade_lock_repository=user_trade_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
    )

@lru_cache
def get_allocation_analytics_service(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    allocation_repository: AllocationRepository = Depends(get_allocation_repository),
) -> AllocationAnalyticsService:
    return AllocationAnalyticsService(
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
    )

@lru_cache
def get_model_portfolio_analytics_service(
    model_portfolio_repository: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
    asset_analytics_service: AssetAnalyticsService = Depends(
        get_asset_analytics_service
    ),
) -> ModelPortfolioAnalyticsService:
    return ModelPortfolioAnalyticsService(
        model_portfolio_repository=model_portfolio_repository,
        asset_analytics_service=asset_analytics_service,
    )


@lru_cache
def get_stock_analytics_service(
    asset_analytics_service: AssetAnalyticsService = Depends(
        get_asset_analytics_service
    ),
) -> StockAnalyticsService:
    return StockAnalyticsService(
        asset_analytics_service=asset_analytics_service,
    )


@lru_cache
def get_explore_search_service(
    opensearch_client: OpenSearchClient = Depends(get_opensearch_client),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    baskt_account_repository: BasktAccountRepository = Depends(
        get_baskt_account_repository
    ),
) -> ExploreSearchService:
    s = get_settings()
    return ExploreSearchService(
        opensearch_client=opensearch_client,
        alpaca_broker_client=alpaca_broker_client,
        baskt_account_repository=baskt_account_repository,
        baskt_account_search_index=s.baskt_account_search_index,
    )

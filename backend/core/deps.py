# backend/core/deps.py

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict

import boto3
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from core.security import CognitoTokenVerifier
from clients.yfinance_client import YFinanceClient
from services.backtest_service import BacktestService
from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from clients.dynamodb_client import DynamoDBClient
from repository.model_portfolio_repository import ModelPortfolioRepository
from services.trade_execution_service import TradeExecutionService
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.order_repository import OrderRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from repository.user_account_repository import UserAccountRepository
from repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from services.account_lifecycle_service import AccountLifecycleService

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

    return boto3.Session(**kwargs)

@lru_cache
def get_dynamodb_resource_cached() -> Any:
    s = get_settings()
    session = get_boto3_session()
    return session.resource("dynamodb", region_name=s.aws_region)

# -----------------------------
# Clients
# -----------------------------

@lru_cache
def get_model_portfolio_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.model_portfolios_dynamodb))

@lru_cache
def get_portfolio_allocation_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.portfolio_allocation_dynamodb))

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
def get_user_trade_lock_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.user_trade_lock_dynamodb))

@lru_cache
def get_user_account_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.user_account_dynamodb))

@lru_cache
def get_model_portfolio_update_lock_dynamodb_client() -> DynamoDBClient:
    s = get_settings()
    dynamodb = get_dynamodb_resource_cached()
    return DynamoDBClient(table=dynamodb.Table(s.model_portfolio_update_lock_dynamodb))

@lru_cache
def get_yfinance_client() -> YFinanceClient:
    return YFinanceClient()

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
    return CognitoClient(
        env=s.env,
        region=s.cognito_region,
        user_pool_id=s.cognito_user_pool_id,
        app_client_id=s.cognito_app_client_id,
    )

# -----------------------------
# Repository
# -----------------------------
def get_model_portfolio_update_lock_repository(
    model_portfolio_update_lock_dynamodb_client: DynamoDBClient = Depends(get_model_portfolio_update_lock_dynamodb_client)
) -> ModelPortfolioUpdateLockRepository:
    return ModelPortfolioUpdateLockRepository(dynamodb_client = model_portfolio_update_lock_dynamodb_client)

def get_model_portfolio_follower_repository(
    model_portfolio_follower_dynamodb_client: DynamoDBClient = Depends(get_model_portfolio_follower_dynamodb_client),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client)
) -> ModelPortfolioFollowerRepository:
    return ModelPortfolioFollowerRepository(dynamodb_client=model_portfolio_follower_dynamodb_client, alpaca_broker_client=alpaca_broker_client)

def get_model_portfolio_repository(
    dynamodb: DynamoDBClient = Depends(get_model_portfolio_dynamodb_client),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository = Depends(get_model_portfolio_update_lock_repository),
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository = Depends(get_model_portfolio_follower_repository),
) -> ModelPortfolioRepository:
    return ModelPortfolioRepository(
        dynamodb_client=dynamodb,
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
    )

def get_portfolio_allocation_repository(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    portfolio_allocation_dynamodb_client: DynamoDBClient = Depends(get_portfolio_allocation_dynamodb_client),
) -> PortfolioAllocationRepository:
    # Use the portfolio allocation table, which has keys (cognito_user_id, portfolio_id)
    return PortfolioAllocationRepository(alpaca_broker_client=alpaca_broker_client, dynamodb_client=portfolio_allocation_dynamodb_client)

def get_order_repository(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    order_dynamodb_client: DynamoDBClient = Depends(get_order_dynamodb_client),
) -> OrderRepository:
    return OrderRepository(alpaca_broker_client=alpaca_broker_client, dynamodb_client=order_dynamodb_client)

def get_user_trade_lock_repository(
    user_trade_lock_dynamodb_client: DynamoDBClient = Depends(get_user_trade_lock_dynamodb_client)
) -> UserTradeLockRepository:
    return UserTradeLockRepository(dynamodb_client=user_trade_lock_dynamodb_client)


def get_user_account_repository(
    user_account_dynamodb_client: DynamoDBClient = Depends(get_user_account_dynamodb_client)
) -> UserAccountRepository:
    return UserAccountRepository(client=user_account_dynamodb_client)
# -----------------------------
# Services
# -----------------------------

def get_backtest_service(yfinance_client: YFinanceClient = Depends(get_yfinance_client)) -> BacktestService:
    return BacktestService(yfinance_client=yfinance_client)

def get_account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    cognito_client: CognitoClient = Depends(get_cognito_client),
    user_account_repository: UserAccountRepository = Depends(get_user_account_repository),
) -> AccountLifecycleService:
    return AccountLifecycleService(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        user_account_repository=user_account_repository,
    )

def get_trade_execution_service(
    model_portfolio_repository: ModelPortfolioRepository = Depends(get_model_portfolio_repository),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    portfolio_allocation_repository: PortfolioAllocationRepository = Depends(get_portfolio_allocation_repository),
    order_repository: OrderRepository = Depends(get_order_repository),
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository = Depends(get_model_portfolio_follower_repository),
    user_trade_lock_repository: UserTradeLockRepository = Depends(get_user_trade_lock_repository),
    account_lifecycle_service: AccountLifecycleService = Depends(get_account_lifecycle_service)
) -> TradeExecutionService:
    return TradeExecutionService(
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_repository=model_portfolio_repository,
        portfolio_allocation_repository=portfolio_allocation_repository,
        order_repository=order_repository,
        model_portfolio_follower_repository=model_portfolio_follower_repository,
        user_trade_lock_repository=user_trade_lock_repository,
        account_lifecycle_service=account_lifecycle_service
    )



# -----------------------------
# Auth
# -----------------------------

@lru_cache
def get_token_verifier() -> CognitoTokenVerifier:
    """
    Cache verifier globally. Do NOT accept Settings as an argument (unhashable).
    """
    s = get_settings()
    return CognitoTokenVerifier(
        user_pool_id=s.cognito_user_pool_id,
        app_client_id=s.cognito_app_client_id,
        region=s.cognito_region,
    )


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = credentials.credentials.strip()
    verifier = get_token_verifier()
    return verifier.verify(token)

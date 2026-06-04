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
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from clients.cognito_client import CognitoClient
from clients.dynamodb_client import DynamoDBClient
from repository.model_portfolio_repository import ModelPortfolioRepository
from services.trade_execution_service import TradeExecutionService
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.order_repository import OrderRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from repository.model_portfolio_update_lock_repository import ModelPortfolioUpdateLockRepository
from services.account_lifecycle_service import AccountLifecycleService
from services.account_performance_service import AccountPerformanceService

from alpaca.broker.models import Account

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

@lru_cache
def get_cognito_idp_client_cached() -> Any:
    s = get_settings()
    session = get_boto3_session()
    return session.client("cognito-idp", region_name=s.cognito_region)

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
    cognito_idp_client = get_cognito_idp_client_cached()
    return CognitoClient(
        env=s.env,
        region=s.cognito_region,
        user_pool_id=s.cognito_user_pool_id,
        app_client_id=s.cognito_app_client_id,
        cognito_client=cognito_idp_client,
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

# -----------------------------
# Services
# -----------------------------

def get_backtest_service(yfinance_client: YFinanceClient = Depends(get_yfinance_client)) -> BacktestService:
    return BacktestService(yfinance_client=yfinance_client)

def get_account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    cognito_client: CognitoClient = Depends(get_cognito_client),
) -> AccountLifecycleService:
    return AccountLifecycleService(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
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

def get_account_performance_service(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
) -> AccountPerformanceService:
    return AccountPerformanceService(
        alpaca_broker_client=alpaca_broker_client,
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


def get_current_alpaca_account_id(
    user: Dict[str, Any] = Depends(get_current_user),
) -> str:
    alpaca_account_id = user.get("custom:alpaca_acct_id")
    if not alpaca_account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not have an Alpaca account id.",
        )

    return str(alpaca_account_id)


def get_current_alpaca_account(
    user: Dict[str, Any] = Depends(get_current_user),
    alpaca_account_id: str = Depends(get_current_alpaca_account_id),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
) -> Any:
    cognito_user_id = user.get("sub")
    if not cognito_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated token is missing Cognito user id.",
        )

    try:
        return alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=str(cognito_user_id),
        )
    except AlpacaBrokerClientError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to verify Alpaca account: {err}",
        ) from err


def get_current_active_alpaca_account(
    alpaca_account: Account = Depends(get_current_alpaca_account),
) -> Any:
    account_status = alpaca_account.status.name.upper()

    if account_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Alpaca account must be ACTIVE, APPROVED, or . Current status is '{account_status}'.",
        )

    return alpaca_account

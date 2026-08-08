import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[3]
backend_dir = Path(__file__).resolve().parents[2]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

load_dotenv(repo_root / ".env")

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.dynamodb_client import DynamoDBClient
from core import deps as app_deps
from core.config import get_settings
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from repository.baskt_account_repository import BasktAccountRepository
from repository.order_repository import OrderRepository
from repository.allocation_repository import AllocationRepository
from repository.user_trade_lock_repository import UserTradeLockRepository


get_settings.cache_clear()


@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def model_portfolio_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_follower_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_follower_dynamodb_client()


@pytest.fixture(scope="session")
def model_portfolio_update_lock_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_update_lock_dynamodb_client()


@pytest.fixture(scope="session")
def baskt_account_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_baskt_account_dynamodb_client()


@pytest.fixture(scope="session")
def order_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_order_dynamodb_client()


@pytest.fixture(scope="session")
def allocation_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_allocation_dynamodb_client()


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
def order_repository(
    order_dynamodb_client: DynamoDBClient,
    alpaca_broker_client: AlpacaBrokerClient,
) -> OrderRepository:
    return app_deps.get_order_repository(
        order_dynamodb_client=order_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
    )


@pytest.fixture(scope="session")
def allocation_repository(
    allocation_dynamodb_client: DynamoDBClient,
    alpaca_broker_client: AlpacaBrokerClient,
) -> AllocationRepository:
    return app_deps.get_allocation_repository(
        allocation_dynamodb_client=allocation_dynamodb_client,
        alpaca_broker_client=alpaca_broker_client,
    )


@pytest.fixture(scope="session")
def user_trade_lock_repository(
    user_trade_lock_dynamodb_client: DynamoDBClient,
) -> UserTradeLockRepository:
    return app_deps.get_user_trade_lock_repository(
        user_trade_lock_dynamodb_client=user_trade_lock_dynamodb_client,
    )


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
        model_portfolio_follower_repository=(
            model_portfolio_follower_repository
        ),
        model_portfolio_access_repository=(
            app_deps.get_model_portfolio_access_repository(
                model_portfolio_follower_repository=(
                    model_portfolio_follower_repository
                )
            )
        ),
    )

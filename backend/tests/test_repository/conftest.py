import os
import sys
from dataclasses import dataclass
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
from clients.cognito_client import CognitoClient
from clients.dynamodb_client import DynamoDBClient
from core import deps as app_deps
from core.config import get_settings
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
from repository.baskt_account_repository import BasktAccountRepository
from repository.order_repository import OrderRepository
from repository.allocation_repository import AllocationRepository
from repository.user_trade_lock_repository import UserTradeLockRepository


get_settings.cache_clear()


@dataclass(frozen=True)
class RepositoryTestUser:
    cognito_user_id: str
    alpaca_account_id: str
    email_address: str


def _required_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for repository integration tests")
    return value


def _test_user(number: int) -> RepositoryTestUser:
    env_prefix = get_settings().env.upper()
    return RepositoryTestUser(
        cognito_user_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_COGNITO_USER_ID"
        ),
        alpaca_account_id=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_ALPACA_ACCOUNT_ID"
        ),
        email_address=_required_env_value(
            f"{env_prefix}_TEST_USER_{number}_EMAIL_ADDRESS"
        ),
    )


@pytest.fixture(scope="session")
def test_user_1() -> RepositoryTestUser:
    return _test_user(1)


@pytest.fixture(scope="session")
def test_user_2() -> RepositoryTestUser:
    return _test_user(2)




@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()


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
def model_portfolio_access_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_model_portfolio_access_dynamodb_client()


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

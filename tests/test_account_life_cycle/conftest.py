import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.cognito_client import CognitoClient
from backend.repository.user_account_repository import UserAccountRepository
from backend.services.account_lifecycle_service import AccountLifecycleService



load_dotenv()
os.environ["ENV"] = "dev"

get_settings.cache_clear()

@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    app_deps.get_alpaca_broker_client.cache_clear()
    return app_deps.get_alpaca_broker_client()

@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()

@pytest.fixture(scope="session")
def user_account_repository() -> UserAccountRepository:
    app_deps.get_user_account_dynamodb_client.cache_clear()
    user_account_dynamodb_client = app_deps.get_user_account_dynamodb_client()
    return app_deps.get_user_account_repository(
        user_account_dynamodb_client=user_account_dynamodb_client
    )

@pytest.fixture(scope="session")
def account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    user_account_repository: UserAccountRepository,
) -> AccountLifecycleService:
    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        user_account_repository=user_account_repository,
    )


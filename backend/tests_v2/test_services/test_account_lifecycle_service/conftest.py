from __future__ import annotations

import pytest

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from clients.dynamodb_client import DynamoDBClient
from core import deps as app_deps
from repository.baskt_account_repository import BasktAccountRepository
from services.account_lifecycle_service import AccountLifecycleService


@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()


@pytest.fixture(scope="session")
def baskt_account_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_baskt_account_dynamodb_client()


@pytest.fixture(scope="session")
def baskt_account_repository(
    baskt_account_dynamodb_client: DynamoDBClient,
) -> BasktAccountRepository:
    return app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=baskt_account_dynamodb_client,
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

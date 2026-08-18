from __future__ import annotations

import pytest

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.dynamodb_client import DynamoDBClient
from core import deps as app_deps
from repository.allocation_repository import AllocationRepository
from services.allocation_analytics_service import AllocationAnalyticsService


@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def allocation_dynamodb_client() -> DynamoDBClient:
    return app_deps.get_allocation_dynamodb_client()


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
def allocation_analytics_service(
    alpaca_broker_client: AlpacaBrokerClient,
    allocation_repository: AllocationRepository,
) -> AllocationAnalyticsService:
    return AllocationAnalyticsService(
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
    )

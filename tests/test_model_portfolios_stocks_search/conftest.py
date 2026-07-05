import os
import sys
from pathlib import Path
from typing import List
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

load_dotenv(repo_root / ".env")
os.environ["ENV"] = "dev"

from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.opensearch_client import OpenSearchClient
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.services.model_portfolios_stocks_search_service import ModelPortfoliosStocksSearchService
from backend.repository.baskt_account_repository import BasktAccountRepository




get_settings.cache_clear()


#######################################
############### CLIENTS ###############
#######################################

@pytest.fixture(scope="session")
def opensearch_client() -> OpenSearchClient:
    return app_deps.get_opensearch_client()


@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def baskt_account_repository() -> BasktAccountRepository:
    return app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=(
            app_deps.get_baskt_account_dynamodb_client()
        )
    )


#######################################
############## SERVICES ###############
#######################################

@pytest.fixture(scope="session")
def model_portfolios_stocks_search_service(
    opensearch_client: OpenSearchClient,
    alpaca_broker_client: AlpacaBrokerClient,
    baskt_account_repository: BasktAccountRepository,
) -> ModelPortfoliosStocksSearchService:
    return app_deps.get_model_portfolios_stocks_search_service(
        opensearch_client=opensearch_client,
        alpaca_broker_client=alpaca_broker_client,
        baskt_account_repository=baskt_account_repository,
    )


###########################################
############### TEST ENGINE ###############
###########################################

class TestEngine:
    def __init__(
        self,
        *,
        model_portfolios_stocks_search_service: ModelPortfoliosStocksSearchService
    ) -> None:
        self.model_portfolios_stocks_search_service = model_portfolios_stocks_search_service

    def test_search_model_portfolios(self,*,query: str,limit: int = 20,offset: int = 0):
        return self.model_portfolios_stocks_search_service.search_model_portfolios(query=query, limit=limit, offset=offset)

    def test_search_stocks(self, *, query: str):
        return self.model_portfolios_stocks_search_service.search_stocks(query=query)

    def test_search_model_portfolios_and_stocks(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ):
        return self.model_portfolios_stocks_search_service.search_model_portfolios_and_stocks(
            query=query,
            limit=limit,
            offset=offset,
        )



@pytest.fixture(scope="session")
def test_engine(
    model_portfolios_stocks_search_service: ModelPortfoliosStocksSearchService
) -> TestEngine:
    return TestEngine(
        model_portfolios_stocks_search_service=model_portfolios_stocks_search_service
    )

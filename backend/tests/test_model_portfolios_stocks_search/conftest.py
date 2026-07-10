import os
import sys
from pathlib import Path
from typing import List
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv


repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

load_dotenv(repo_root / ".env")
os.environ["ENV"] = "dev"

from backend.core import deps as app_deps
from backend.core.config import get_settings
from backend.clients.opensearch_client import OpenSearchClient
from backend.clients.alpaca_broker_client import AlpacaBrokerClient
from backend.clients.cognito_client import CognitoClient
from backend.services.model_portfolios_stocks_search_service import ModelPortfoliosStocksSearchService
from backend.services.account_lifecycle_service import AccountLifecycleService
from backend.repository.baskt_account_repository import BasktAccountRepository
from backend.repository.model_portfolio_repository import ModelPortfolioRepository




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
def cognito_client() -> CognitoClient:
    return app_deps.get_cognito_client()


@pytest.fixture(scope="session")
def baskt_account_repository() -> BasktAccountRepository:
    return app_deps.get_baskt_account_repository(
        baskt_account_dynamodb_client=(
            app_deps.get_baskt_account_dynamodb_client()
        )
    )


@pytest.fixture(scope="session")
def model_portfolio_repository(
    alpaca_broker_client: AlpacaBrokerClient,
) -> ModelPortfolioRepository:
    return app_deps.get_model_portfolio_repository(
        dynamodb=app_deps.get_model_portfolio_dynamodb_client(),
        alpaca_broker_client=alpaca_broker_client,
        model_portfolio_update_lock_repository=(
            app_deps.get_model_portfolio_update_lock_repository(
                model_portfolio_update_lock_dynamodb_client=(
                    app_deps.get_model_portfolio_update_lock_dynamodb_client()
                )
            )
        ),
        model_portfolio_follower_repository=(
            app_deps.get_model_portfolio_follower_repository(
                model_portfolio_follower_dynamodb_client=(
                    app_deps.get_model_portfolio_follower_dynamodb_client()
                ),
                alpaca_broker_client=alpaca_broker_client,
            )
        ),
    )


#######################################
############## SERVICES ###############
#######################################
@pytest.fixture(scope="session")
def account_lifecycle_service(
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    baskt_account_repository: BasktAccountRepository
) -> AccountLifecycleService:
    return app_deps.get_account_lifecycle_service(
        alpaca_broker_client=alpaca_broker_client,
        cognito_client=cognito_client,
        baskt_account_repository=baskt_account_repository,
    )

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
    __test__ = False

    def __init__(
        self,
        *,
        model_portfolios_stocks_search_service: ModelPortfoliosStocksSearchService,
        account_lifecycle_service: AccountLifecycleService,
        baskt_account_repository: BasktAccountRepository,
        model_portfolio_repository: ModelPortfolioRepository,
    ) -> None:
        self.model_portfolios_stocks_search_service = model_portfolios_stocks_search_service
        self.account_lifecycle_service = account_lifecycle_service
        self.baskt_account_repository = baskt_account_repository
        self.model_portfolio_repository = model_portfolio_repository

    def test_search_model_portfolios(self,*,query: str,limit: int = 20,offset: int = 0):
        return self.model_portfolios_stocks_search_service.search_model_portfolios(query=query, limit=limit, offset=offset)

    def test_search_stocks(self, *, query: str):
        return self.model_portfolios_stocks_search_service.search_stocks(query=query)
    
    def test_search_baskt_accounts(self, *, query: str):
        return self.model_portfolios_stocks_search_service.search_baskt_accounts(query=query)

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
    model_portfolios_stocks_search_service: ModelPortfoliosStocksSearchService,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
) -> TestEngine:
    return TestEngine(
        model_portfolios_stocks_search_service=model_portfolios_stocks_search_service,
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        model_portfolio_repository=model_portfolio_repository,
    )

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
from backend.services.model_portfolios_stocks_search_service import ModelPortfoliosStocksSearchService




get_settings.cache_clear()


#######################################
############### CLIENTS ###############
#######################################

@pytest.fixture(scope="session")
def opensearch_client() -> OpenSearchClient:
    return app_deps.get_opensearch_client()


#######################################
############## SERVICES ###############
#######################################

@pytest.fixture(scope="session")
def model_portfolios_stocks_search_service(
    opensearch_client: OpenSearchClient
) -> ModelPortfoliosStocksSearchService:
    return app_deps.get_model_portfolios_stocks_search_service(
        opensearch_client=opensearch_client
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



@pytest.fixture(scope="session")
def test_engine(
    model_portfolios_stocks_search_service: ModelPortfoliosStocksSearchService
) -> TestEngine:
    return TestEngine(
        model_portfolios_stocks_search_service=model_portfolios_stocks_search_service
    )

import pytest

from .conftest import TestEngine
# from backend.services.model_portfolios_stocks_search_service import (
#     ModelPortfolioSearchResult,
#     ModelPortfoliosSearchResponse,
# )

#from backend.schema.model_portfolios_stocks_search_schema import M

@pytest.mark.integration
def test_search_model_portfolio_by_name_apple(test_engine: TestEngine) -> None:
    search_response = test_engine.test_search_model_portfolios(query="Apple")

    print(search_response)


def test_search_baskt_account_by_display_name(test_engine: TestEngine) -> None:
    search_response = test_engine.test_search_baskt_accounts(query="sibster")
    print(search_response)

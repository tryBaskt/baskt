import pytest

from conftest import TestEngine
from backend.services.model_portfolios_stocks_search_service import (
    ModelPortfolioSearchResult,
    ModelPortfoliosSearchResponse,
)

@pytest.mark.integration
def test_search_model_portfolio_by_name_apple(test_engine: TestEngine) -> None:
    search_response = test_engine.test_search_model_portfolios(query="Apple")

    print(search_response)

    assert search_response["total"] > 0
    assert any(
        model_portfolio["portfolio_name"].casefold() == "apple"
        for model_portfolio in search_response["model_portfolios"]
    )

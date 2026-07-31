from __future__ import annotations

from typing import Any

import pytest

from conftest import OWNER_USER_ID
from core.deps import get_model_portfolios_stocks_search_service
from domain.baskt_account_domain import BasktAccountOpenSearch, BasktAccountsOpenSearch
from domain.model_portfolio_domain import (
    ModelPortfolioOpenSearchResult,
    ModelPortfoliosOpenSearchResult,
)
from domain.stock_domain import StockSearchResult
from routes.model_portfolios_stocks_search_route import router as search_router
from services.model_portfolios_stocks_search_service import (
    ModelPortfoliosStocksSearchInternalServerError,
)


class FakeSearchService:
    def __init__(self, *, fail_code: str | None = None) -> None:
        self.fail_code = fail_code

    def _maybe_fail(self) -> None:
        if self.fail_code:
            raise ModelPortfoliosStocksSearchInternalServerError(
                "search failed",
                code=self.fail_code,
            )

    def _portfolio_result(self) -> ModelPortfolioOpenSearchResult:
        return ModelPortfolioOpenSearchResult(
            portfolio_id="portfolio-1",
            portfolio_name="Growth",
            description="Public growth portfolio",
            portfolio_owner_cognito_user_id=OWNER_USER_ID,
            portfolio_owner_display_name="Owner",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
            visibility="PUBLIC",
            score=1.0,
        )

    def _account_result(self) -> BasktAccountOpenSearch:
        return BasktAccountOpenSearch(
            cognito_user_id=OWNER_USER_ID,
            display_name="Owner",
            description="Public profile",
            profile_image="avatar.png",
        )

    def search_model_portfolios_and_stocks(self, **kwargs: Any):
        self._maybe_fail()
        return {
            "model_portfolios_opensearch_result": ModelPortfoliosOpenSearchResult(
                model_portfolios=[self._portfolio_result()],
                total=1,
                limit=kwargs["limit"],
                offset=kwargs["offset"],
            ),
            "stocks_search_result": [
                StockSearchResult(
                    stock_id="asset-aapl",
                    symbol="AAPL",
                    tradable=True,
                    marginable=True,
                    shortable=True,
                    fractionable=True,
                    stock_class="us_equity",
                )
            ],
            "baskt_accounts_opensearch_result": BasktAccountsOpenSearch(
                baskt_accounts=[self._account_result()],
                total=1,
                limit=kwargs["limit"],
                offset=kwargs["offset"],
            ),
        }

    def search_baskt_accounts(self, **kwargs: Any) -> BasktAccountsOpenSearch:
        self._maybe_fail()
        return BasktAccountsOpenSearch(
            baskt_accounts=[self._account_result()],
            total=1,
            limit=kwargs["limit"],
            offset=kwargs["offset"],
        )

    def search_model_portfolios(self, **kwargs: Any) -> ModelPortfoliosOpenSearchResult:
        self._maybe_fail()
        return ModelPortfoliosOpenSearchResult(
            model_portfolios=[self._portfolio_result()],
            total=1,
            limit=kwargs["limit"],
            offset=kwargs["offset"],
        )


@pytest.fixture
def search_app(app_factory):
    app = app_factory(search_router)
    app.dependency_overrides[get_model_portfolios_stocks_search_service] = (
        lambda: FakeSearchService()
    )
    return app


@pytest.fixture
def search_client(search_app, client_for_app):
    with client_for_app(search_app) as client:
        yield client


def test_search_routes_return_combined_and_filtered_results(search_client) -> None:
    combined = search_client.get("/search", params={"query": "aapl", "limit": 5})
    assert combined.status_code == 200, combined.text
    assert combined.json()["stocks"][0]["symbol"] == "AAPL"
    assert combined.json()["model_portfolios"]["model_portfolios"][0]["visibility"] == "PUBLIC"

    accounts = search_client.get("/search/baskt-accounts", params={"query": "owner"})
    assert accounts.status_code == 200, accounts.text
    assert accounts.json()["baskt_accounts"][0]["display_name"] == "Owner"

    portfolios = search_client.get(
        "/search/model-portfolios",
        params={"query": "growth"},
    )
    assert portfolios.status_code == 200, portfolios.text
    assert portfolios.json()["model_portfolios"][0]["portfolio_id"] == "portfolio-1"


def test_search_route_maps_service_validation_error(search_client, search_app) -> None:
    search_app.dependency_overrides[get_model_portfolios_stocks_search_service] = (
        lambda: FakeSearchService(fail_code="MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT")
    )

    response = search_client.get("/search/model-portfolios", params={"query": "growth"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT"

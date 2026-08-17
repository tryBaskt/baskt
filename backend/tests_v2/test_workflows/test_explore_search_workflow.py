from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.authentication import get_current_user
from core.deps import (
    get_baskt_account_repository,
    get_explore_search_service,
)
from domain.baskt_account_domain import BasktAccount
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_repository import ModelPortfolioRepository
from routes import explore_search_route
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.explore_search_service import ExploreSearchService


pytestmark = pytest.mark.integration


"""
These workflow tests exercise explore_search_route.py through FastAPI's
TestClient while keeping auth, repository, OpenSearch, Alpaca, and search
service dependencies wired to the real tests_v2 integration stack.

Coverage goals:
- GET /search: authenticated users receive the expected response shape with
  model_portfolios, stocks, and baskt_accounts.
- GET /search: a single AAPL query can return a real stock, a persisted model
  portfolio named AAPL, and a DynamoDB-only Baskt account named AAPL.
- GET /search: private model portfolio metadata is searchable by a different
  authenticated user.
- GET /search: a non-stock query can return a matching portfolio and account
  while stocks is empty.
- GET /search: limit/offset pagination is passed through to model portfolio
  and Baskt account result groups.
- GET /search: FastAPI rejects missing/blank query and invalid limit/offset
  values.
- Authentication: missing auth headers, token Alpaca-account mismatches, and
  unknown token Cognito user ids are rejected by the real Baskt account auth
  dependency.

Every synthetic Baskt account and model portfolio created here is cleaned up in
finally blocks. Synthetic Baskt accounts are written only to DynamoDB; these
tests do not create Cognito or Alpaca accounts.
"""


CREATED_AT = datetime(2024, 1, 2, 14, tzinfo=timezone.utc)


def _claims_for_user(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _claims_without_baskt_account() -> dict[str, str]:
    unique = uuid4()
    return {
        "sub": f"tests-v2-no-search-baskt-account-{unique}",
        "custom:alpaca_acct_id": f"tests-v2-no-search-alpaca-{unique}",
    }


def _claims_with_mismatched_alpaca_account(account: BasktAccount) -> dict[str, str]:
    return {
        "sub": account.cognito_user_id,
        "custom:alpaca_acct_id": f"tests-v2-wrong-alpaca-{uuid4()}",
    }


def _claims_with_mismatched_cognito_user_id(account: BasktAccount) -> dict[str, str]:
    return {
        "sub": f"tests-v2-wrong-cognito-{uuid4()}",
        "custom:alpaca_acct_id": account.alpaca_account_id,
    }


def _client_for_claims(
    *,
    claims: dict[str, str] | None,
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
) -> TestClient:
    app = FastAPI()
    app.include_router(explore_search_route.router)
    if claims is not None:
        app.dependency_overrides[get_current_user] = lambda: claims
    app.dependency_overrides[
        explore_search_route.get_explore_search_service
    ] = lambda: explore_search_service
    app.dependency_overrides[get_explore_search_service] = (
        lambda: explore_search_service
    )
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    return TestClient(app)


def _client_for_user(
    *,
    test_user: Any,
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
) -> TestClient:
    return _client_for_claims(
        claims=_claims_for_user(test_user),
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )


def _unauthenticated_client(
    *,
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
) -> TestClient:
    return _client_for_claims(
        claims=None,
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )


def _wait_until(predicate, *, description: str, timeout_seconds: float = 60) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.5)
    raise AssertionError(f"Timed out waiting for {description}")


def _create_single_stock_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    portfolio_name: str,
    visibility: str,
    description: str,
) -> str:
    return model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=owner_cognito_user_id,
        portfolio_name=portfolio_name,
        positions_request=[
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
            )
        ],
        visibility=visibility,
        creation_time=CREATED_AT,
        description=description,
    )


def _create_search_baskt_account(
    *,
    baskt_account_repository: BasktAccountRepository,
    base_account: BasktAccount,
    cognito_user_id: str,
    display_name: str,
    description: str,
) -> BasktAccount:
    account = replace(
        base_account,
        cognito_user_id=cognito_user_id,
        display_name=display_name,
        description=description,
        alpaca_account_id=f"alpaca-{uuid4()}",
        alpaca_account_number=f"acct-{uuid4().hex[:12]}",
    )
    baskt_account_repository.write_baskt_account(account)
    return account


def _delete_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    portfolio_id: str | None,
) -> None:
    if portfolio_id is not None:
        model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )


def _delete_baskt_account(
    *,
    baskt_account_repository: BasktAccountRepository,
    account: BasktAccount | None,
) -> None:
    if account is not None:
        baskt_account_repository.delete_baskt_account(
            cognito_user_id=account.cognito_user_id
        )


def test_explore_search_route_returns_all_result_types_for_aapl(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id
    )
    test_run_id = uuid4().hex[:10]
    account = None
    portfolio_id = None

    try:
        account = _create_search_baskt_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            cognito_user_id=f"route-search-aapl-{test_run_id}",
            display_name="AAPL",
            description=f"Route AAPL account {test_run_id}",
        )
        portfolio_id = _create_single_stock_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_2.cognito_user_id,
            portfolio_name="AAPL",
            visibility="PRIVATE",
            description=f"Route AAPL portfolio {test_run_id}",
        )

        response_body = None

        def all_result_types_are_searchable() -> bool:
            nonlocal response_body
            response = client.get("/search", params={"query": "AAPL", "limit": 50})
            assert response.status_code == 200, response.text
            response_body = response.json()
            return (
                any(stock["symbol"] == "AAPL" for stock in response_body["stocks"])
                and any(
                    portfolio["portfolio_id"] == portfolio_id
                    for portfolio in response_body["model_portfolios"][
                        "model_portfolios"
                    ]
                )
                and any(
                    result["cognito_user_id"] == account.cognito_user_id
                    for result in response_body["baskt_accounts"]["baskt_accounts"]
                )
            )

        _wait_until(
            all_result_types_are_searchable,
            description="AAPL stock, model portfolio, and account route results",
        )

        assert set(response_body) == {"model_portfolios", "stocks", "baskt_accounts"}
        stock_result = next(
            stock for stock in response_body["stocks"] if stock["symbol"] == "AAPL"
        )
        portfolio_result = next(
            portfolio
            for portfolio in response_body["model_portfolios"]["model_portfolios"]
            if portfolio["portfolio_id"] == portfolio_id
        )
        account_result = next(
            result
            for result in response_body["baskt_accounts"]["baskt_accounts"]
            if result["cognito_user_id"] == account.cognito_user_id
        )

        assert stock_result["stock_id"]
        assert stock_result["stock_class"] == "US_EQUITY"
        assert stock_result["tradable"] is True

        assert portfolio_result["portfolio_name"] == "AAPL"
        assert portfolio_result["description"] == f"Route AAPL portfolio {test_run_id}"
        assert (
            portfolio_result["portfolio_owner_cognito_user_id"]
            == test_user_2.cognito_user_id
        )
        assert portfolio_result["visibility"] == "PRIVATE"
        assert response_body["model_portfolios"]["limit"] == 50
        assert response_body["model_portfolios"]["offset"] == 0

        assert account_result["display_name"] == "AAPL"
        assert account_result["description"] == f"Route AAPL account {test_run_id}"
        assert account_result["profile_image"] is None
        assert response_body["baskt_accounts"]["limit"] == 50
        assert response_body["baskt_accounts"]["offset"] == 0
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )
        _delete_baskt_account(
            baskt_account_repository=baskt_account_repository,
            account=account,
        )


def test_explore_search_route_returns_private_portfolio_to_different_user(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )
    test_run_id = uuid4().hex[:10]
    portfolio_name = f"routeprivate{test_run_id}"
    portfolio_id = None

    try:
        portfolio_id = _create_single_stock_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_2.cognito_user_id,
            portfolio_name=portfolio_name,
            visibility="PRIVATE",
            description=f"Route private portfolio {test_run_id}",
        )

        response_body = None

        def private_portfolio_is_searchable() -> bool:
            nonlocal response_body
            response = client.get("/search", params={"query": portfolio_name})
            assert response.status_code == 200, response.text
            response_body = response.json()
            return any(
                portfolio["portfolio_id"] == portfolio_id
                for portfolio in response_body["model_portfolios"][
                    "model_portfolios"
                ]
            )

        _wait_until(
            private_portfolio_is_searchable,
            description=f"private portfolio '{portfolio_name}' route result",
        )

        portfolio_result = next(
            portfolio
            for portfolio in response_body["model_portfolios"]["model_portfolios"]
            if portfolio["portfolio_id"] == portfolio_id
        )
        assert portfolio_result["portfolio_name"] == portfolio_name
        assert portfolio_result["visibility"] == "PRIVATE"
        assert (
            portfolio_result["portfolio_owner_cognito_user_id"]
            == test_user_2.cognito_user_id
        )
        assert response_body["stocks"] == []
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


def test_explore_search_route_returns_portfolio_and_account_for_non_stock_query(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id
    )
    test_run_id = uuid4().hex[:10]
    query = f"routenonstock{test_run_id}"
    account = None
    portfolio_id = None

    try:
        account = _create_search_baskt_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            cognito_user_id=f"{query}-account",
            display_name=query,
            description=f"{query} account description",
        )
        portfolio_id = _create_single_stock_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_2.cognito_user_id,
            portfolio_name=query,
            visibility="PUBLIC",
            description=f"{query} portfolio description",
        )

        response_body = None

        def created_results_are_searchable() -> bool:
            nonlocal response_body
            response = client.get("/search", params={"query": query, "limit": 50})
            assert response.status_code == 200, response.text
            response_body = response.json()
            return (
                any(
                    portfolio["portfolio_id"] == portfolio_id
                    for portfolio in response_body["model_portfolios"][
                        "model_portfolios"
                    ]
                )
                and any(
                    result["cognito_user_id"] == account.cognito_user_id
                    for result in response_body["baskt_accounts"]["baskt_accounts"]
                )
            )

        _wait_until(
            created_results_are_searchable,
            description=f"portfolio and account route results matching '{query}'",
        )

        assert response_body["stocks"] == []
        assert any(
            portfolio["portfolio_id"] == portfolio_id
            for portfolio in response_body["model_portfolios"]["model_portfolios"]
        )
        assert any(
            result["cognito_user_id"] == account.cognito_user_id
            for result in response_body["baskt_accounts"]["baskt_accounts"]
        )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )
        _delete_baskt_account(
            baskt_account_repository=baskt_account_repository,
            account=account,
        )


def test_explore_search_route_passes_pagination_to_portfolios_and_accounts(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id
    )
    test_run_id = uuid4().hex[:10]
    query = f"routepagination{test_run_id}"
    accounts = []
    portfolio_ids = []

    try:
        for index in range(15):
            accounts.append(
                _create_search_baskt_account(
                    baskt_account_repository=baskt_account_repository,
                    base_account=base_account,
                    cognito_user_id=f"{query}-account-{index:02d}",
                    display_name=f"{query} Account {index:02d}",
                    description=f"{query} account description {index:02d}",
                )
            )
            portfolio_ids.append(
                _create_single_stock_model_portfolio(
                    model_portfolio_repository=model_portfolio_repository,
                    owner_cognito_user_id=test_user_2.cognito_user_id,
                    portfolio_name=f"{query} Portfolio {index:02d}",
                    visibility="PRIVATE" if index % 2 else "PUBLIC",
                    description=f"{query} portfolio description {index:02d}",
                )
            )

        account_ids = {account.cognito_user_id for account in accounts}
        portfolio_id_set = set(portfolio_ids)

        def all_created_results_are_searchable() -> bool:
            response = client.get("/search", params={"query": query, "limit": 50})
            assert response.status_code == 200, response.text
            body = response.json()
            found_portfolio_ids = {
                portfolio["portfolio_id"]
                for portfolio in body["model_portfolios"]["model_portfolios"]
                if portfolio["portfolio_id"] in portfolio_id_set
            }
            found_account_ids = {
                account["cognito_user_id"]
                for account in body["baskt_accounts"]["baskt_accounts"]
                if account["cognito_user_id"] in account_ids
            }
            return (
                found_portfolio_ids == portfolio_id_set
                and found_account_ids == account_ids
            )

        _wait_until(
            all_created_results_are_searchable,
            description=f"15 portfolio and 15 account route results for '{query}'",
        )

        first_five_response = client.get(
            "/search",
            params={"query": query, "limit": 5, "offset": 0},
        )
        middle_response = client.get(
            "/search",
            params={"query": query, "limit": 10, "offset": 5},
        )

        assert first_five_response.status_code == 200, first_five_response.text
        assert middle_response.status_code == 200, middle_response.text
        first_five = first_five_response.json()
        middle_page = middle_response.json()

        first_five_portfolio_ids = {
            portfolio["portfolio_id"]
            for portfolio in first_five["model_portfolios"]["model_portfolios"]
        }
        first_five_account_ids = {
            account["cognito_user_id"]
            for account in first_five["baskt_accounts"]["baskt_accounts"]
        }
        middle_portfolios = middle_page["model_portfolios"]
        middle_accounts = middle_page["baskt_accounts"]
        middle_portfolio_ids = {
            portfolio["portfolio_id"]
            for portfolio in middle_portfolios["model_portfolios"]
        }
        middle_account_ids = {
            account["cognito_user_id"]
            for account in middle_accounts["baskt_accounts"]
        }

        assert middle_page["stocks"] == []
        assert middle_portfolios["total"] == 15
        assert middle_portfolios["limit"] == 10
        assert middle_portfolios["offset"] == 5
        assert len(middle_portfolios["model_portfolios"]) == 10
        assert middle_portfolio_ids.issubset(portfolio_id_set)
        assert not middle_portfolio_ids.intersection(first_five_portfolio_ids)

        assert middle_accounts["total"] == 15
        assert middle_accounts["limit"] == 10
        assert middle_accounts["offset"] == 5
        assert len(middle_accounts["baskt_accounts"]) == 10
        assert middle_account_ids.issubset(account_ids)
        assert not middle_account_ids.intersection(first_five_account_ids)
    finally:
        for portfolio_id in portfolio_ids:
            _delete_model_portfolio(
                model_portfolio_repository=model_portfolio_repository,
                portfolio_id=portfolio_id,
            )
        for account in accounts:
            _delete_baskt_account(
                baskt_account_repository=baskt_account_repository,
                account=account,
            )


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"query": ""},
        {"query": "AAPL", "limit": 0},
        {"query": "AAPL", "limit": 51},
        {"query": "AAPL", "offset": -1},
    ],
)
def test_explore_search_route_rejects_invalid_request_params(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
    test_user_1: Any,
    params: dict[str, Any],
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )

    response = client.get("/search", params=params)

    assert response.status_code == 422


def test_explore_search_route_requires_authentication(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
) -> None:
    client = _unauthenticated_client(
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )

    response = client.get("/search", params={"query": "AAPL"})

    assert response.status_code == 401


def test_explore_search_route_rejects_authenticated_user_without_baskt_account(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
) -> None:
    client = _client_for_claims(
        claims=_claims_without_baskt_account(),
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )

    response = client.get("/search", params={"query": "AAPL"})

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user does not have a Baskt account."
    )


def test_explore_search_route_rejects_token_alpaca_account_mismatch(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
    test_user_1: Any,
) -> None:
    account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    client = _client_for_claims(
        claims=_claims_with_mismatched_alpaca_account(account),
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )

    response = client.get("/search", params={"query": "AAPL"})

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user's Alpaca account does not match Baskt account."
    )


def test_explore_search_route_rejects_token_cognito_user_mismatch(
    baskt_account_repository: BasktAccountRepository,
    explore_search_service: ExploreSearchService,
    test_user_1: Any,
) -> None:
    account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    client = _client_for_claims(
        claims=_claims_with_mismatched_cognito_user_id(account),
        baskt_account_repository=baskt_account_repository,
        explore_search_service=explore_search_service,
    )

    response = client.get("/search", params={"query": "AAPL"})

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user does not have a Baskt account."
    )

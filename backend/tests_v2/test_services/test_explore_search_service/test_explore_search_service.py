"""
Coverage / scenarios:
- search_model_portfolios(): User A creates a private model portfolio, User B
  can still search for it because search no longer enforces portfolio access or
  visibility.
- search_model_portfolios(): User A creates 30 similarly named model
  portfolios with mixed public/private visibility. User B searches with
  limit/offset pagination and verifies all created portfolios are returned
  exactly once across aligned pages, offset=30 is empty, and offset=5 skips the
  first five results.
- search_model_portfolios(): blank queries return an empty page without calling
  lower systems for results.
- search_model_portfolios(): invalid pagination raises the service validation
  error for limit below range, limit above range, and negative offset.
- search_stocks(): exact ticker match for AAPL returns one stock result with
  expected stock metadata.
- search_stocks(): lowercase and whitespace-padded symbols normalize to the
  expected uppercase stock result.
- search_stocks(): exact ticker match for a known ETF returns one stock result.
- search_stocks(): blank query returns an empty result list before calling
  Alpaca.
- search_stocks(): random non-ticker query returns an empty result list.
- search_stocks(): unsupported, malformed, and inactive-style symbols return an
  empty result list when Alpaca reports no matching asset.
- search_baskt_accounts(): User A account metadata written directly to
  DynamoDB is searchable by display name without creating Cognito or Alpaca
  resources.
- search_baskt_accounts(): 30 similarly named DynamoDB-only accounts paginate
  through limit/offset and are returned exactly once across aligned pages.
- search_baskt_accounts(): blank queries return an empty page.
- search_baskt_accounts(): invalid pagination raises the service validation
  error for limit below range, limit above range, and negative offset.
- search_model_portfolios_and_stocks(): one AAPL query returns the real AAPL
  stock plus a matching persisted model portfolio and DynamoDB-only Baskt
  account.
- search_model_portfolios_and_stocks(): blank query returns the expected
  response shape with empty model portfolio, stock, and account results.
- search_model_portfolios_and_stocks(): non-stock query can return matching
  model portfolio and account results while stock results stay empty.
- search_model_portfolios_and_stocks(): stock-only, portfolio-only, and
  account-only queries each return their matching result type without breaking
  the others.
- search_model_portfolios_and_stocks(): limit/offset pagination applies to
  model portfolio and Baskt account OpenSearch result sets independently.
- search_model_portfolios_and_stocks(): invalid pagination raises model
  portfolio validation errors before downstream searches run.
- search_model_portfolios_and_stocks(): whitespace-padded lowercase AAPL query
  still returns the AAPL stock and matching AAPL portfolio/account results.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic, sleep
import uuid

import pytest

from backend.tests_v2.conftest import RepositoryTestUser
from domain.baskt_account_domain import BasktAccount
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_repository import ModelPortfolioRepository
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.explore_search_service import (
    ExploreSearchInternalServerError,
    ExploreSearchService,
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
        creation_time=datetime.now(timezone.utc),
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
        alpaca_account_id=f"alpaca-{uuid.uuid4()}",
        alpaca_account_number=f"acct-{uuid.uuid4().hex[:12]}",
    )
    baskt_account_repository.write_baskt_account(account)
    return account


def test_explore_search_model_portfolios_blank_query_returns_empty_page(
    explore_search_service: ExploreSearchService,
) -> None:
    response = explore_search_service.search_model_portfolios(
        query="   ",
        limit=10,
        offset=5,
    )

    assert response.model_portfolios == []
    assert response.total == 0
    assert response.limit == 10
    assert response.offset == 5


@pytest.mark.parametrize(
    ("limit", "offset", "expected_code"),
    [
        (0, 0, "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT"),
        (51, 0, "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT"),
        (10, -1, "MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET"),
    ],
)
def test_explore_search_model_portfolios_rejects_invalid_pagination(
    explore_search_service: ExploreSearchService,
    limit: int,
    offset: int,
    expected_code: str,
) -> None:
    with pytest.raises(ExploreSearchInternalServerError) as exc_info:
        explore_search_service.search_model_portfolios(
            query="AAPL",
            limit=limit,
            offset=offset,
        )

    assert exc_info.value.code == expected_code


def test_explore_search_baskt_accounts_blank_query_returns_empty_page(
    explore_search_service: ExploreSearchService,
) -> None:
    response = explore_search_service.search_baskt_accounts(
        query="   ",
        limit=10,
        offset=5,
    )

    assert response.baskt_accounts == []
    assert response.total == 0
    assert response.limit == 10
    assert response.offset == 5


@pytest.mark.parametrize(
    ("limit", "offset", "expected_code"),
    [
        (0, 0, "BASKT_ACCOUNT_SEARCH_INVALID_LIMIT"),
        (51, 0, "BASKT_ACCOUNT_SEARCH_INVALID_LIMIT"),
        (10, -1, "BASKT_ACCOUNT_SEARCH_INVALID_OFFSET"),
    ],
)
def test_explore_search_baskt_accounts_rejects_invalid_pagination(
    explore_search_service: ExploreSearchService,
    limit: int,
    offset: int,
    expected_code: str,
) -> None:
    with pytest.raises(ExploreSearchInternalServerError) as exc_info:
        explore_search_service.search_baskt_accounts(
            query="search",
            limit=limit,
            offset=offset,
        )

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    ("query", "expected_symbol"),
    [
        ("AAPL", "AAPL"),
        ("aapl", "AAPL"),
        ("  AAPL  ", "AAPL"),
        ("SPY", "SPY"),
    ],
)
def test_explore_search_stocks_returns_expected_asset_for_known_symbols(
    explore_search_service: ExploreSearchService,
    query: str,
    expected_symbol: str,
) -> None:
    response = explore_search_service.search_stocks(query=query)

    assert len(response) == 1
    stock = response[0]
    assert stock.symbol == expected_symbol
    assert stock.stock_id
    assert stock.stock_class == "US_EQUITY"
    assert stock.tradable is True
    assert isinstance(stock.fractionable, bool)
    assert isinstance(stock.shortable, bool)
    assert isinstance(stock.marginable, bool)


def test_explore_search_stocks_returns_empty_for_blank_query(
    explore_search_service: ExploreSearchService,
) -> None:
    response = explore_search_service.search_stocks(query="   ")

    assert response == []


@pytest.mark.parametrize(
    "query",
    [
        f"NOTATICKER{uuid.uuid4().hex[:12]}",
        "7203.T",
        "@@@",
        "BASKTDELISTEDZZZ",
    ],
)
def test_explore_search_stocks_returns_empty_for_unknown_or_unsupported_symbols(
    explore_search_service: ExploreSearchService,
    query: str,
) -> None:
    response = explore_search_service.search_stocks(query=query)

    assert response == []


def test_explore_search_model_portfolios_and_stocks_blank_query_returns_empty_shape(
    explore_search_service: ExploreSearchService,
) -> None:
    response = explore_search_service.search_model_portfolios_and_stocks(
        query="   ",
        limit=10,
        offset=5,
    )

    assert set(response) == {
        "model_portfolios_opensearch_result",
        "stocks_search_result",
        "baskt_accounts_opensearch_result",
    }

    model_portfolios_response = response["model_portfolios_opensearch_result"]
    stocks_response = response["stocks_search_result"]
    accounts_response = response["baskt_accounts_opensearch_result"]

    assert model_portfolios_response.model_portfolios == []
    assert model_portfolios_response.total == 0
    assert model_portfolios_response.limit == 10
    assert model_portfolios_response.offset == 5
    assert stocks_response == []
    assert accounts_response.baskt_accounts == []
    assert accounts_response.total == 0
    assert accounts_response.limit == 10
    assert accounts_response.offset == 5


@pytest.mark.parametrize(
    ("limit", "offset", "expected_code"),
    [
        (0, 0, "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT"),
        (51, 0, "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT"),
        (10, -1, "MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET"),
    ],
)
def test_explore_search_model_portfolios_and_stocks_rejects_invalid_pagination(
    explore_search_service: ExploreSearchService,
    limit: int,
    offset: int,
    expected_code: str,
) -> None:
    with pytest.raises(ExploreSearchInternalServerError) as exc_info:
        explore_search_service.search_model_portfolios_and_stocks(
            query="AAPL",
            limit=limit,
            offset=offset,
        )

    assert exc_info.value.code == expected_code


def test_explore_search_model_portfolios_and_stocks_returns_stock_only_result(
    explore_search_service: ExploreSearchService,
) -> None:
    response = explore_search_service.search_model_portfolios_and_stocks(
        query="SPY",
        limit=10,
        offset=0,
    )

    assert set(response) == {
        "model_portfolios_opensearch_result",
        "stocks_search_result",
        "baskt_accounts_opensearch_result",
    }
    stocks_response = response["stocks_search_result"]
    assert len(stocks_response) == 1
    assert stocks_response[0].symbol == "SPY"
    assert response["model_portfolios_opensearch_result"].limit == 10
    assert response["model_portfolios_opensearch_result"].offset == 0
    assert response["baskt_accounts_opensearch_result"].limit == 10
    assert response["baskt_accounts_opensearch_result"].offset == 0


@pytest.mark.integration
def test_explore_search_baskt_accounts_returns_dynamodb_only_account(
    explore_search_service: ExploreSearchService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id,
    )

    test_run_id = uuid.uuid4().hex[:10]
    cognito_user_id = f"search-account-{test_run_id}"
    display_name = f"searchaccount{test_run_id}"
    description = f"DynamoDB only searchable account {test_run_id}"
    created_account = None

    try:
        created_account = _create_search_baskt_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            cognito_user_id=cognito_user_id,
            display_name=display_name,
            description=description,
        )

        account_result = None

        def account_is_searchable() -> bool:
            nonlocal account_result
            response = explore_search_service.search_baskt_accounts(
                query=display_name,
            )
            account_result = next(
                (
                    item
                    for item in response.baskt_accounts
                    if item.cognito_user_id == created_account.cognito_user_id
                ),
                None,
            )
            return account_result is not None

        _wait_until(
            account_is_searchable,
            description=f"account '{display_name}' to be indexed for search",
        )

        assert account_result.cognito_user_id == cognito_user_id
        assert account_result.display_name == display_name
        assert account_result.description == description
        assert account_result.profile_image is None
    finally:
        if created_account is not None:
            baskt_account_repository.delete_baskt_account(
                cognito_user_id=created_account.cognito_user_id
            )


@pytest.mark.integration
def test_explore_search_baskt_accounts_paginates_through_thirty_similar_names(
    explore_search_service: ExploreSearchService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id,
    )

    test_run_id = uuid.uuid4().hex[:10]
    query = f"accountpagination{test_run_id}"
    created_accounts = []

    try:
        for index in range(30):
            account = _create_search_baskt_account(
                baskt_account_repository=baskt_account_repository,
                base_account=base_account,
                cognito_user_id=f"{query}-{index:02d}",
                display_name=f"{query} Account {index:02d}",
                description=f"{query} description {index:02d}",
            )
            created_accounts.append(account)

        created_cognito_user_ids = {
            account.cognito_user_id for account in created_accounts
        }

        def all_accounts_are_searchable() -> bool:
            response = explore_search_service.search_baskt_accounts(
                query=query,
                limit=50,
            )
            result_ids = {
                item.cognito_user_id
                for item in response.baskt_accounts
                if item.cognito_user_id in created_cognito_user_ids
            }
            return result_ids == created_cognito_user_ids and response.total == 30

        _wait_until(
            all_accounts_are_searchable,
            description=f"all 30 accounts matching '{query}' to be indexed",
        )

        page_zero = explore_search_service.search_baskt_accounts(
            query=query,
            limit=10,
            offset=0,
        )
        page_one = explore_search_service.search_baskt_accounts(
            query=query,
            limit=10,
            offset=10,
        )
        page_two = explore_search_service.search_baskt_accounts(
            query=query,
            limit=10,
            offset=20,
        )
        empty_page = explore_search_service.search_baskt_accounts(
            query=query,
            limit=10,
            offset=30,
        )
        middle_page = explore_search_service.search_baskt_accounts(
            query=query,
            limit=10,
            offset=5,
        )

        pages = [page_zero, page_one, page_two]
        for page in pages:
            assert page.total == 30
            assert page.limit == 10
            assert len(page.baskt_accounts) == 10

        assert page_zero.offset == 0
        assert page_one.offset == 10
        assert page_two.offset == 20

        page_zero_ids = [
            item.cognito_user_id for item in page_zero.baskt_accounts
        ]
        page_one_ids = [
            item.cognito_user_id for item in page_one.baskt_accounts
        ]
        page_two_ids = [
            item.cognito_user_id for item in page_two.baskt_accounts
        ]
        paged_ids = page_zero_ids + page_one_ids + page_two_ids

        assert len(paged_ids) == 30
        assert len(set(paged_ids)) == 30
        assert set(paged_ids) == created_cognito_user_ids

        assert empty_page.total == 30
        assert empty_page.limit == 10
        assert empty_page.offset == 30
        assert empty_page.baskt_accounts == []

        middle_page_ids = [
            item.cognito_user_id for item in middle_page.baskt_accounts
        ]
        assert middle_page.total == 30
        assert middle_page.limit == 10
        assert middle_page.offset == 5
        assert len(middle_page_ids) == 10
        assert len(set(middle_page_ids)) == 10
        assert set(middle_page_ids).issubset(created_cognito_user_ids)
        assert not set(middle_page_ids).intersection(set(page_zero_ids[:5]))
    finally:
        for account in created_accounts:
            baskt_account_repository.delete_baskt_account(
                cognito_user_id=account.cognito_user_id
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_and_stocks_returns_all_result_types_for_aapl(
    explore_search_service: ExploreSearchService,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id,
    )

    test_run_id = uuid.uuid4().hex[:10]
    account = None
    portfolio_id = None

    try:
        account = _create_search_baskt_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            cognito_user_id=f"combined-search-aapl-{test_run_id}",
            display_name="AAPL",
            description=f"Combined AAPL account {test_run_id}",
        )
        portfolio_id = _create_single_stock_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_2.cognito_user_id,
            portfolio_name="AAPL",
            visibility="PRIVATE",
            description=f"Combined AAPL portfolio {test_run_id}",
        )

        combined_response = None

        def all_result_types_are_searchable() -> bool:
            nonlocal combined_response
            combined_response = (
                explore_search_service.search_model_portfolios_and_stocks(
                    query="AAPL",
                    limit=50,
                )
            )
            portfolio_results = combined_response[
                "model_portfolios_opensearch_result"
            ].model_portfolios
            account_results = combined_response[
                "baskt_accounts_opensearch_result"
            ].baskt_accounts
            stock_results = combined_response["stocks_search_result"]

            return (
                any(stock.symbol == "AAPL" for stock in stock_results)
                and any(
                    portfolio.portfolio_id == portfolio_id
                    for portfolio in portfolio_results
                )
                and any(
                    result.cognito_user_id == account.cognito_user_id
                    for result in account_results
                )
            )

        _wait_until(
            all_result_types_are_searchable,
            description="AAPL stock, model portfolio, and account search results",
        )

        stock_results = combined_response["stocks_search_result"]
        portfolio_response = combined_response[
            "model_portfolios_opensearch_result"
        ]
        account_response = combined_response["baskt_accounts_opensearch_result"]

        stock_result = next(stock for stock in stock_results if stock.symbol == "AAPL")
        portfolio_result = next(
            portfolio
            for portfolio in portfolio_response.model_portfolios
            if portfolio.portfolio_id == portfolio_id
        )
        account_result = next(
            result
            for result in account_response.baskt_accounts
            if result.cognito_user_id == account.cognito_user_id
        )

        assert stock_result.stock_id
        assert stock_result.stock_class == "US_EQUITY"
        assert stock_result.tradable is True

        assert portfolio_result.portfolio_name == "AAPL"
        assert portfolio_result.description == f"Combined AAPL portfolio {test_run_id}"
        assert (
            portfolio_result.portfolio_owner_cognito_user_id
            == test_user_2.cognito_user_id
        )
        assert portfolio_result.visibility == "PRIVATE"
        assert portfolio_response.limit == 50
        assert portfolio_response.offset == 0
        assert portfolio_response.total >= 1

        assert account_result.display_name == "AAPL"
        assert account_result.description == f"Combined AAPL account {test_run_id}"
        assert account_result.profile_image is None
        assert account_response.limit == 50
        assert account_response.offset == 0
        assert account_response.total >= 1
    finally:
        if portfolio_id is not None:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )
        if account is not None:
            baskt_account_repository.delete_baskt_account(
                cognito_user_id=account.cognito_user_id
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_and_stocks_returns_portfolio_and_account_without_stock(
    explore_search_service: ExploreSearchService,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id,
    )

    test_run_id = uuid.uuid4().hex[:10]
    query = f"combinednonstock{test_run_id}"
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
            visibility="PRIVATE",
            description=f"{query} portfolio description",
        )

        combined_response = None

        def created_results_are_searchable() -> bool:
            nonlocal combined_response
            combined_response = (
                explore_search_service.search_model_portfolios_and_stocks(
                    query=query,
                    limit=50,
                )
            )
            portfolio_results = combined_response[
                "model_portfolios_opensearch_result"
            ].model_portfolios
            account_results = combined_response[
                "baskt_accounts_opensearch_result"
            ].baskt_accounts
            return (
                any(
                    portfolio.portfolio_id == portfolio_id
                    for portfolio in portfolio_results
                )
                and any(
                    result.cognito_user_id == account.cognito_user_id
                    for result in account_results
                )
            )

        _wait_until(
            created_results_are_searchable,
            description=f"portfolio and account matching '{query}'",
        )

        assert combined_response["stocks_search_result"] == []
        assert any(
            portfolio.portfolio_id == portfolio_id
            for portfolio in combined_response[
                "model_portfolios_opensearch_result"
            ].model_portfolios
        )
        assert any(
            result.cognito_user_id == account.cognito_user_id
            for result in combined_response[
                "baskt_accounts_opensearch_result"
            ].baskt_accounts
        )
    finally:
        if portfolio_id is not None:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )
        if account is not None:
            baskt_account_repository.delete_baskt_account(
                cognito_user_id=account.cognito_user_id
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_and_stocks_returns_portfolio_only_result(
    explore_search_service: ExploreSearchService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id

    test_run_id = uuid.uuid4().hex[:10]
    query = f"combinedportfolioonly{test_run_id}"
    portfolio_id = None

    try:
        portfolio_id = _create_single_stock_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_2.cognito_user_id,
            portfolio_name=query,
            visibility="PUBLIC",
            description=f"{query} portfolio description",
        )

        combined_response = None

        def portfolio_is_searchable() -> bool:
            nonlocal combined_response
            combined_response = (
                explore_search_service.search_model_portfolios_and_stocks(
                    query=query,
                    limit=50,
                )
            )
            return any(
                portfolio.portfolio_id == portfolio_id
                for portfolio in combined_response[
                    "model_portfolios_opensearch_result"
                ].model_portfolios
            )

        _wait_until(
            portfolio_is_searchable,
            description=f"portfolio-only result matching '{query}'",
        )

        assert combined_response["stocks_search_result"] == []
        assert any(
            portfolio.portfolio_id == portfolio_id
            for portfolio in combined_response[
                "model_portfolios_opensearch_result"
            ].model_portfolios
        )
        assert not any(
            account.display_name == query
            for account in combined_response[
                "baskt_accounts_opensearch_result"
            ].baskt_accounts
        )
    finally:
        if portfolio_id is not None:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_and_stocks_returns_account_only_result(
    explore_search_service: ExploreSearchService,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id,
    )

    test_run_id = uuid.uuid4().hex[:10]
    query = f"combinedaccountonly{test_run_id}"
    account = None

    try:
        account = _create_search_baskt_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            cognito_user_id=f"{query}-account",
            display_name=query,
            description=f"{query} account description",
        )

        combined_response = None

        def account_is_searchable() -> bool:
            nonlocal combined_response
            combined_response = (
                explore_search_service.search_model_portfolios_and_stocks(
                    query=query,
                    limit=50,
                )
            )
            return any(
                result.cognito_user_id == account.cognito_user_id
                for result in combined_response[
                    "baskt_accounts_opensearch_result"
                ].baskt_accounts
            )

        _wait_until(
            account_is_searchable,
            description=f"account-only result matching '{query}'",
        )

        assert combined_response["stocks_search_result"] == []
        assert not any(
            portfolio.portfolio_name == query
            for portfolio in combined_response[
                "model_portfolios_opensearch_result"
            ].model_portfolios
        )
        assert any(
            result.cognito_user_id == account.cognito_user_id
            for result in combined_response[
                "baskt_accounts_opensearch_result"
            ].baskt_accounts
        )
    finally:
        if account is not None:
            baskt_account_repository.delete_baskt_account(
                cognito_user_id=account.cognito_user_id
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_and_stocks_paginates_portfolios_and_accounts_independently(
    explore_search_service: ExploreSearchService,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id,
    )

    test_run_id = uuid.uuid4().hex[:10]
    query = f"combinedpagination{test_run_id}"
    accounts = []
    portfolio_ids = []

    try:
        for index in range(15):
            account = _create_search_baskt_account(
                baskt_account_repository=baskt_account_repository,
                base_account=base_account,
                cognito_user_id=f"{query}-account-{index:02d}",
                display_name=f"{query} Account {index:02d}",
                description=f"{query} account description {index:02d}",
            )
            accounts.append(account)

            portfolio_id = _create_single_stock_model_portfolio(
                model_portfolio_repository=model_portfolio_repository,
                owner_cognito_user_id=test_user_2.cognito_user_id,
                portfolio_name=f"{query} Portfolio {index:02d}",
                visibility="PRIVATE" if index % 2 else "PUBLIC",
                description=f"{query} portfolio description {index:02d}",
            )
            portfolio_ids.append(portfolio_id)

        account_ids = {account.cognito_user_id for account in accounts}
        portfolio_id_set = set(portfolio_ids)

        def all_created_results_are_searchable() -> bool:
            response = explore_search_service.search_model_portfolios_and_stocks(
                query=query,
                limit=50,
            )
            found_portfolio_ids = {
                portfolio.portfolio_id
                for portfolio in response[
                    "model_portfolios_opensearch_result"
                ].model_portfolios
                if portfolio.portfolio_id in portfolio_id_set
            }
            found_account_ids = {
                account.cognito_user_id
                for account in response[
                    "baskt_accounts_opensearch_result"
                ].baskt_accounts
                if account.cognito_user_id in account_ids
            }
            return (
                found_portfolio_ids == portfolio_id_set
                and found_account_ids == account_ids
            )

        _wait_until(
            all_created_results_are_searchable,
            description=f"15 portfolios and 15 accounts matching '{query}'",
        )

        first_five = explore_search_service.search_model_portfolios_and_stocks(
            query=query,
            limit=5,
            offset=0,
        )
        middle_page = explore_search_service.search_model_portfolios_and_stocks(
            query=query,
            limit=10,
            offset=5,
        )

        first_five_portfolio_ids = {
            portfolio.portfolio_id
            for portfolio in first_five[
                "model_portfolios_opensearch_result"
            ].model_portfolios
        }
        first_five_account_ids = {
            account.cognito_user_id
            for account in first_five[
                "baskt_accounts_opensearch_result"
            ].baskt_accounts
        }
        middle_portfolios = middle_page["model_portfolios_opensearch_result"]
        middle_accounts = middle_page["baskt_accounts_opensearch_result"]

        middle_portfolio_ids = {
            portfolio.portfolio_id for portfolio in middle_portfolios.model_portfolios
        }
        middle_account_ids = {
            account.cognito_user_id for account in middle_accounts.baskt_accounts
        }

        assert middle_page["stocks_search_result"] == []
        assert middle_portfolios.total == 15
        assert middle_portfolios.limit == 10
        assert middle_portfolios.offset == 5
        assert len(middle_portfolios.model_portfolios) == 10
        assert middle_portfolio_ids.issubset(portfolio_id_set)
        assert not middle_portfolio_ids.intersection(first_five_portfolio_ids)

        assert middle_accounts.total == 15
        assert middle_accounts.limit == 10
        assert middle_accounts.offset == 5
        assert len(middle_accounts.baskt_accounts) == 10
        assert middle_account_ids.issubset(account_ids)
        assert not middle_account_ids.intersection(first_five_account_ids)
    finally:
        for portfolio_id in portfolio_ids:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )
        for account in accounts:
            baskt_account_repository.delete_baskt_account(
                cognito_user_id=account.cognito_user_id
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_and_stocks_normalizes_whitespace_and_case_for_aapl(
    explore_search_service: ExploreSearchService,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id,
    )

    test_run_id = uuid.uuid4().hex[:10]
    account = None
    portfolio_id = None

    try:
        account = _create_search_baskt_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            cognito_user_id=f"combined-aapl-normalized-{test_run_id}",
            display_name="AAPL",
            description=f"Normalized AAPL account {test_run_id}",
        )
        portfolio_id = _create_single_stock_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_2.cognito_user_id,
            portfolio_name="AAPL",
            visibility="PUBLIC",
            description=f"Normalized AAPL portfolio {test_run_id}",
        )

        combined_response = None

        def normalized_query_returns_all_created_results() -> bool:
            nonlocal combined_response
            combined_response = (
                explore_search_service.search_model_portfolios_and_stocks(
                    query="  aapl  ",
                    limit=50,
                )
            )
            return (
                any(
                    stock.symbol == "AAPL"
                    for stock in combined_response["stocks_search_result"]
                )
                and any(
                    portfolio.portfolio_id == portfolio_id
                    for portfolio in combined_response[
                        "model_portfolios_opensearch_result"
                    ].model_portfolios
                )
                and any(
                    result.cognito_user_id == account.cognito_user_id
                    for result in combined_response[
                        "baskt_accounts_opensearch_result"
                    ].baskt_accounts
                )
            )

        _wait_until(
            normalized_query_returns_all_created_results,
            description="normalized AAPL combined search results",
        )

        assert any(
            stock.symbol == "AAPL"
            for stock in combined_response["stocks_search_result"]
        )
        assert any(
            portfolio.portfolio_id == portfolio_id
            for portfolio in combined_response[
                "model_portfolios_opensearch_result"
            ].model_portfolios
        )
        assert any(
            result.cognito_user_id == account.cognito_user_id
            for result in combined_response[
                "baskt_accounts_opensearch_result"
            ].baskt_accounts
        )
    finally:
        if portfolio_id is not None:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )
        if account is not None:
            baskt_account_repository.delete_baskt_account(
                cognito_user_id=account.cognito_user_id
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_returns_private_portfolio_to_other_user(
    explore_search_service: ExploreSearchService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id

    test_run_id = uuid.uuid4().hex[:10]
    portfolio_name = f"crossuserprivate{test_run_id}"
    portfolio_description = f"Private portfolio searchable by user B {test_run_id}"
    portfolio_id = None

    try:
        portfolio_id = _create_single_stock_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_2.cognito_user_id,
            portfolio_name=portfolio_name,
            visibility="PRIVATE",
            description=portfolio_description,
        )

        portfolio_result = None

        def private_portfolio_is_searchable() -> bool:
            nonlocal portfolio_result
            response = explore_search_service.search_model_portfolios(
                query=portfolio_name,
            )
            portfolio_result = next(
                (
                    item
                    for item in response.model_portfolios
                    if item.portfolio_id == portfolio_id
                ),
                None,
            )
            return portfolio_result is not None

        _wait_until(
            private_portfolio_is_searchable,
            description=(
                f"private portfolio '{portfolio_name}' to be indexed for search"
            ),
        )

        assert portfolio_result.portfolio_name == portfolio_name
        assert portfolio_result.description == portfolio_description
        assert (
            portfolio_result.portfolio_owner_cognito_user_id
            == test_user_2.cognito_user_id
        )
        assert portfolio_result.visibility == "PRIVATE"
        assert portfolio_result.score is None or portfolio_result.score >= 0
    finally:
        if portfolio_id is not None:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )


@pytest.mark.integration
def test_explore_search_model_portfolios_paginates_through_thirty_similar_names(
    explore_search_service: ExploreSearchService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: RepositoryTestUser,
    test_user_2: RepositoryTestUser,
) -> None:
    assert test_user_1.cognito_user_id != test_user_2.cognito_user_id

    test_run_id = uuid.uuid4().hex[:10]
    query = f"searchpagination{test_run_id}"
    created_portfolio_ids = []

    try:
        for index in range(30):
            portfolio_id = _create_single_stock_model_portfolio(
                model_portfolio_repository=model_portfolio_repository,
                owner_cognito_user_id=test_user_2.cognito_user_id,
                portfolio_name=f"{query} Portfolio {index:02d}",
                visibility="PRIVATE" if index % 2 else "PUBLIC",
                description=f"{query} description {index:02d}",
            )
            created_portfolio_ids.append(portfolio_id)

        created_portfolio_id_set = set(created_portfolio_ids)

        def all_portfolios_are_searchable() -> bool:
            response = explore_search_service.search_model_portfolios(
                query=query,
                limit=50,
            )
            result_ids = {
                item.portfolio_id
                for item in response.model_portfolios
                if item.portfolio_id in created_portfolio_id_set
            }
            return result_ids == created_portfolio_id_set and response.total == 30

        _wait_until(
            all_portfolios_are_searchable,
            description=f"all 30 portfolios matching '{query}' to be indexed",
        )

        page_zero = explore_search_service.search_model_portfolios(
            query=query,
            limit=10,
            offset=0,
        )
        page_one = explore_search_service.search_model_portfolios(
            query=query,
            limit=10,
            offset=10,
        )
        page_two = explore_search_service.search_model_portfolios(
            query=query,
            limit=10,
            offset=20,
        )
        empty_page = explore_search_service.search_model_portfolios(
            query=query,
            limit=10,
            offset=30,
        )
        middle_page = explore_search_service.search_model_portfolios(
            query=query,
            limit=10,
            offset=5,
        )

        pages = [page_zero, page_one, page_two]
        for page in pages:
            assert page.total == 30
            assert page.limit == 10
            assert len(page.model_portfolios) == 10

        assert page_zero.offset == 0
        assert page_one.offset == 10
        assert page_two.offset == 20

        page_zero_ids = [item.portfolio_id for item in page_zero.model_portfolios]
        page_one_ids = [item.portfolio_id for item in page_one.model_portfolios]
        page_two_ids = [item.portfolio_id for item in page_two.model_portfolios]
        paged_ids = page_zero_ids + page_one_ids + page_two_ids

        assert len(paged_ids) == 30
        assert len(set(paged_ids)) == 30
        assert set(paged_ids) == created_portfolio_id_set

        assert empty_page.total == 30
        assert empty_page.limit == 10
        assert empty_page.offset == 30
        assert empty_page.model_portfolios == []

        middle_page_ids = [
            item.portfolio_id for item in middle_page.model_portfolios
        ]
        assert middle_page.total == 30
        assert middle_page.limit == 10
        assert middle_page.offset == 5
        assert len(middle_page_ids) == 10
        assert len(set(middle_page_ids)) == 10
        assert set(middle_page_ids).issubset(created_portfolio_id_set)
        assert not set(middle_page_ids).intersection(set(page_zero_ids[:5]))
    finally:
        for portfolio_id in created_portfolio_ids:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )

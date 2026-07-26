from datetime import datetime, timezone
from time import monotonic, sleep
import uuid

import pytest

from .conftest import TestEngine
from backend.schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.model_portfolios_stocks_search_service import (
    ModelPortfoliosStocksSearchInternalServerError,
)

DEV_PORTFOLIO_OWNER_COGNITO_USER_ID = "b4b8a418-a081-704c-377b-3acfedba3e34"
TEST_PORTFOLIO_OWNER_COGNITO_USER_ID = "e46834b8-6091-70a3-1135-bccdc6174b07"


def _owner_cognito_user_id(test_engine: TestEngine) -> str:
    return globals()[f"{test_engine.env.upper()}_PORTFOLIO_OWNER_COGNITO_USER_ID"]


def _account_data(*, display_name: str, email_address: str) -> dict:
    return {
        "display_name": display_name,
        "contact": {
            "email_address": email_address,
            "phone_number": "+15555551234",
            "street_address": ["123 Market St"],
            "unit": "9A",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        "identity": {
            "given_name": "Search",
            "family_name": "Tester",
            "date_of_birth": "1990-01-01",
            "tax_id": "999-99-1234",
            "tax_id_type": "USA_SSN",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income", "savings"],
            "annual_income_min": 50000,
            "annual_income_max": 120000,
            "liquid_net_worth_min": 10000,
            "liquid_net_worth_max": 50000,
            "total_net_worth_min": 50000,
            "total_net_worth_max": 200000,
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
            "employment_status": "EMPLOYED",
            "employer_name": "Baskt Search Test Employer",
            "employer_address": "123 Market St, San Francisco, CA 94105",
            "employment_position": "Software Engineer",
        },
        "agreements": [
            {
                "agreement": agreement,
                "signed_at": datetime.now(timezone.utc).isoformat(),
                "ip_address": "127.0.0.1",
            }
            for agreement in (
                "account_agreement",
                "customer_agreement",
                "margin_agreement",
            )
        ],
    }


def _wait_until(predicate, *, description: str, timeout_seconds: float = 30) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.5)
    raise AssertionError(f"Timed out waiting for {description}")


@pytest.mark.integration
def test_created_accounts_and_model_portfolios_are_searchable(
    test_engine: TestEngine,
) -> None:
    """Create two owners and portfolios and verify both search indexes populate."""
    test_run_id = uuid.uuid4().hex[:10]
    created_accounts = []
    created_portfolio_ids = []

    try:
        for label in ("Alpha", "Beta"):
            display_name = f"Search Account {test_run_id} {label}"
            portfolio_name = f"Search Portfolio {test_run_id} {label}"
            portfolio_description = (
                f"Discovery description {test_run_id} {label}"
            )
            account = test_engine.account_lifecycle_service.create_baskt_account(
                account_data=_account_data(
                    display_name=display_name,
                    email_address=(
                        f"search_{test_run_id}_{label.lower()}@example.com"
                    ),
                ),
                password=f"Test_9aA{uuid.uuid4().hex[:16]}",
            )
            created_accounts.append(account)

            portfolio_id = test_engine.model_portfolio_repository.create_model_portfolio(
                portfolio_owner_cognito_user_id=account["cognito_user_id"],
                portfolio_name=portfolio_name,
                positions_request=[
                    ModelPortfolioPositionRequest(
                        symbol="AAPL",
                        target_weight=1.0,
                        direction=1,
                        leverage=1.0,
                    )
                ],
                description=portfolio_description,
            )
            created_portfolio_ids.append(portfolio_id)

            account_result = None

            def account_is_searchable() -> bool:
                nonlocal account_result
                response = test_engine.test_search_baskt_accounts(
                    query=display_name,
                )
                account_result = next(
                    (
                        item
                        for item in response.baskt_accounts
                        if item.cognito_user_id == account["cognito_user_id"]
                    ),
                    None,
                )
                return account_result is not None

            _wait_until(
                account_is_searchable,
                description=f"account '{display_name}' to be indexed",
            )
            assert account_result.display_name == display_name

            portfolio_result = None

            def portfolio_is_searchable() -> bool:
                nonlocal portfolio_result
                response = test_engine.test_search_model_portfolios(
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
                portfolio_is_searchable,
                description=f"portfolio '{portfolio_name}' to be indexed",
            )
            assert portfolio_result.portfolio_name == portfolio_name
            assert (
                portfolio_result.portfolio_owner_cognito_user_id
                == account["cognito_user_id"]
            )
            assert portfolio_result.portfolio_owner_display_name == display_name
            assert portfolio_result.description == portfolio_description

            portfolio_description_result = None

            def portfolio_description_is_searchable() -> bool:
                nonlocal portfolio_description_result
                response = test_engine.test_search_model_portfolios(
                    query=portfolio_description,
                )
                portfolio_description_result = next(
                    (
                        item
                        for item in response.model_portfolios
                        if item.portfolio_id == portfolio_id
                    ),
                    None,
                )
                return portfolio_description_result is not None

            _wait_until(
                portfolio_description_is_searchable,
                description=(
                    f"portfolio description '{portfolio_description}' to be searchable"
                ),
            )
            assert portfolio_description_result.portfolio_name == portfolio_name
            assert portfolio_description_result.description == portfolio_description
    finally:
        for portfolio_id in created_portfolio_ids:
            test_engine.model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )

        for account in created_accounts:
            try:
                test_engine.account_lifecycle_service.permanently_close_baskt_account(
                    cognito_user_id=account["cognito_user_id"],
                    alpaca_account_id=account["alpaca_account_id"],
                )
            finally:
                test_engine.baskt_account_repository.dynamodb.delete_item(
                    key={"cognito_user_id": account["cognito_user_id"]}
                )


def test_search_service_error_class_sets_code() -> None:
    error = ModelPortfoliosStocksSearchInternalServerError(
        "failed",
        code="SEARCH_CUSTOM_CODE",
    )

    assert str(error) == "failed"
    assert error.code == "SEARCH_CUSTOM_CODE"


def test_search_service_validation_and_blank_query_paths(
    test_engine: TestEngine,
) -> None:
    service = test_engine.model_portfolios_stocks_search_service

    assert service.search_stocks(query="   ") == []

    empty_model_portfolios = service.search_model_portfolios(query="   ")
    assert empty_model_portfolios.model_portfolios == []
    assert empty_model_portfolios.total == 0

    empty_baskt_accounts = service.search_baskt_accounts(query="   ")
    assert empty_baskt_accounts.baskt_accounts == []
    assert empty_baskt_accounts.total == 0

    with pytest.raises(ModelPortfoliosStocksSearchInternalServerError) as mp_limit:
        service.search_model_portfolios(query="aapl", limit=0)
    assert mp_limit.value.code == "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT"

    with pytest.raises(ModelPortfoliosStocksSearchInternalServerError) as mp_offset:
        service.search_model_portfolios(query="aapl", offset=-1)
    assert mp_offset.value.code == "MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET"

    with pytest.raises(ModelPortfoliosStocksSearchInternalServerError) as acct_limit:
        service.search_baskt_accounts(query="john_doe_3", limit=0)
    assert acct_limit.value.code == "BASKT_ACCOUNT_SEARCH_INVALID_LIMIT"

    with pytest.raises(ModelPortfoliosStocksSearchInternalServerError) as acct_offset:
        service.search_baskt_accounts(query="john_doe_3", offset=-1)
    assert acct_offset.value.code == "BASKT_ACCOUNT_SEARCH_INVALID_OFFSET"


@pytest.mark.integration
def test_search_service_finds_stock_existing_account_and_created_model_portfolio(
    test_engine: TestEngine,
) -> None:
    owner_cognito_user_id = _owner_cognito_user_id(test_engine)
    test_run_id = uuid.uuid4().hex[:10]
    portfolio_name = f"Search Coverage Portfolio {test_run_id}"
    portfolio_description = f"Search coverage description {test_run_id}"
    portfolio_id = None

    try:
        portfolio_id = test_engine.model_portfolio_repository.create_model_portfolio(
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
            creation_time=datetime.now(timezone.utc),
            description=portfolio_description,
        )

        stock_results = test_engine.test_search_stocks(query="aapl")
        assert len(stock_results) == 1
        assert stock_results[0].symbol == "AAPL"
        assert stock_results[0].stock_id

        account_results = test_engine.test_search_baskt_accounts(
            query="john_doe_3",
        )
        assert account_results.limit == 20
        assert account_results.offset == 0
        assert account_results.total >= len(account_results.baskt_accounts)

        portfolio_result = None

        def portfolio_is_searchable() -> bool:
            nonlocal portfolio_result
            response = test_engine.test_search_model_portfolios(
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
            portfolio_is_searchable,
            description=f"portfolio '{portfolio_name}' to be indexed",
        )

        assert portfolio_result.portfolio_name == portfolio_name
        assert portfolio_result.description == portfolio_description
        assert portfolio_result.portfolio_owner_cognito_user_id == owner_cognito_user_id

        combined_results = test_engine.test_search_model_portfolios_and_stocks(
            query=portfolio_name,
        )
        assert any(
            item.portfolio_id == portfolio_id
            for item in combined_results[
                "model_portfolios_opensearch_result"
            ].model_portfolios
        )
        assert combined_results["stocks_search_result"] == []
        assert combined_results["baskt_accounts_opensearch_result"].total >= 0

        combined_stock_results = test_engine.test_search_model_portfolios_and_stocks(
            query="AAPL",
        )
        assert combined_stock_results["stocks_search_result"][0].symbol == "AAPL"
    finally:
        if portfolio_id is not None:
            test_engine.model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )

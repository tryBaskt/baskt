"""Offline regression coverage for DynamoDB-backed Explore search."""

from unittest.mock import MagicMock

import pytest

from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_repository import ModelPortfolioBadGatewayError
from services.explore_search_service import ExploreSearchInternalServerError, ExploreSearchService


def _service(portfolios=(), accounts=()):
    portfolio_repository = MagicMock()
    portfolio_repository.get_search_metadata.return_value = list(portfolios)
    account_repository = MagicMock()
    account_repository.get_search_metadata.return_value = list(accounts)
    account_repository.get_display_name.return_value = "Portfolio Owner"
    return ExploreSearchService(
        model_portfolio_repository=portfolio_repository,
        baskt_account_repository=account_repository,
        alpaca_broker_client=MagicMock(),
    )


def _portfolio(portfolio_id, name, description=None):
    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": name,
        "description": description,
        "portfolio_owner_cognito_user_id": "owner",
        "created_at": "2026-10-01T00:00:00+00:00",
        "updated_at": "2026-10-01T00:00:00+00:00",
        "visibility": "PUBLIC",
    }


def test_scan_all_includes_later_pages_after_an_empty_filtered_page():
    table = MagicMock()
    table.name = "test-search-table"
    paginator = table.meta.client.get_paginator.return_value
    paginator.paginate.return_value = [
        {"Items": [{"id": "first"}]},
        {"Items": [], "LastEvaluatedKey": {"id": "filtered"}},
        {"Items": [{"id": "last"}]},
    ]
    result = DynamoDBClient(table).scan_all(ProjectionExpression="id")
    assert result == [{"id": "first"}, {"id": "last"}]
    table.meta.client.get_paginator.assert_called_once_with("scan")
    paginator.paginate.assert_called_once_with(
        TableName="test-search-table", ProjectionExpression="id",
    )


def test_scan_all_wraps_failures_on_later_pages():
    def pages():
        yield {"Items": [{"id": "first"}]}
        raise RuntimeError("read failed on page two")

    table = MagicMock()
    table.meta.client.get_paginator.return_value.paginate.return_value = pages()
    with pytest.raises(DynamoDBClientError, match="page two"):
        DynamoDBClient(table).scan_all()


def test_portfolio_search_ranks_names_and_paginates_stably():
    service = _service(portfolios=[
        _portfolio("description", "Income", "TECH companies"),
        _portfolio("substring", "Big Tech"),
        _portfolio("prefix", "Tech Growth"),
        _portfolio("exact", "TECH"),
        _portfolio("unmatched", "Retail"),
    ])
    first = service.search_model_portfolios(query="  tech  ", limit=2)
    second = service.search_model_portfolios(query="tech", limit=2, offset=2)
    assert first.total == second.total == 4
    assert [item.portfolio_id for item in first.model_portfolios] == ["exact", "prefix"]
    assert [item.portfolio_id for item in second.model_portfolios] == ["substring", "description"]
    assert first.model_portfolios[0].portfolio_owner_display_name == "Portfolio Owner"
    assert service.search_model_portfolios(query="tech", offset=4).model_portfolios == []


def test_account_search_matches_case_and_terms_across_profile_fields():
    service = _service(accounts=[
        {"cognito_user_id": "growth", "display_name": "Tech Investor", "description": "Growth stocks"},
        {"cognito_user_id": "income", "display_name": "Tech Investor 2", "description": "Income stocks"},
    ])
    result = service.search_baskt_accounts(query=" TECH growth ")
    assert result.total == 1
    assert result.baskt_accounts[0].cognito_user_id == "growth"


def test_blank_search_does_not_read_dynamodb():
    service = _service()
    assert service.search_model_portfolios(query=" ").total == 0
    assert service.search_baskt_accounts(query=" ").total == 0
    service.model_portfolio_repository.get_search_metadata.assert_not_called()
    service.baskt_account_repository.get_search_metadata.assert_not_called()


def test_search_reports_dynamodb_failure():
    service = _service()
    service.model_portfolio_repository.get_search_metadata.side_effect = ModelPortfolioBadGatewayError(
        source="DynamoDB", operation="reading search metadata",
    )
    with pytest.raises(ExploreSearchInternalServerError) as error:
        service.search_model_portfolios(query="tech")
    assert error.value.code == "MODEL_PORTFOLIOS_SEARCH_DYNAMODB_FAILED"


def test_account_metadata_scan_only_requests_public_profile_attributes():
    dynamodb = MagicMock()
    repository = BasktAccountRepository(dynamodb)
    repository.get_search_metadata()
    attributes = set(dynamodb.scan_all.call_args.kwargs["ExpressionAttributeNames"].values())
    assert attributes == {"cognito_user_id", "display_name", "description", "profile_image"}

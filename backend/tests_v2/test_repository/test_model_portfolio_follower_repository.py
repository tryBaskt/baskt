from __future__ import annotations

from uuid import uuid4

import pytest

from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)


"""
These tests exercise the non-mocked ModelPortfolioFollowerRepository paths
against the configured test DynamoDB table.

Coverage goals:
- is_model_portfolio_follower(): check a portfolio/user pair before and after a
  follower record is written so both false and true paths are covered.
- put_model_portfolio_follower(): write a follower record for a portfolio and
  verify the record can be read back through the follower APIs.
- get_model_portfolio_followers(): return no followers for a fresh portfolio
  ID, return n followers after an initial write, return n+1 followers after
  another follower is added, and return n-1 followers after one is deleted.
- delete_model_portfolio_follower(): delete an existing follower and verify the
  follower is gone, then call delete for a user/portfolio pair that does not
  exist and verify the no-op returns None.

Every test deletes follower records it creates in finally blocks so the shared
integration tables are left clean.
"""


def _delete_follower(
    repository: ModelPortfolioFollowerRepository,
    *,
    cognito_user_id: str,
    portfolio_id: str,
) -> None:
    repository.dynamodb.delete_item(
        key={
            "cognito_user_id": cognito_user_id,
            "portfolio_id": portfolio_id,
        }
    )


@pytest.mark.integration
def test_model_portfolio_follower_repository_put_is_follower_and_delete(
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Write, detect, delete, and no-op delete a follower record."""
    portfolio_id = f"tests-v2-follower-{uuid4()}"

    try:
        assert (
            model_portfolio_follower_repository.is_model_portfolio_follower(
                cognito_user_id=test_user_2.cognito_user_id,
                portfolio_id=portfolio_id,
            )
            is False
        )

        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            alpaca_account_id=test_user_2.alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
        )
        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        assert model_portfolio_follower_repository.get_model_portfolio_followers(
            portfolio_id=portfolio_id
        ) == [
            {
                "alpaca_account_id": test_user_2.alpaca_account_id,
                "cognito_user_id": test_user_2.cognito_user_id,
            }
        ]

        assert (
            model_portfolio_follower_repository.delete_model_portfolio_follower(
                cognito_user_id=test_user_2.cognito_user_id,
                portfolio_id=portfolio_id,
            )
            is None
        )
        assert (
            model_portfolio_follower_repository.is_model_portfolio_follower(
                cognito_user_id=test_user_2.cognito_user_id,
                portfolio_id=portfolio_id,
            )
            is False
        )

        assert (
            model_portfolio_follower_repository.delete_model_portfolio_follower(
                cognito_user_id=test_user_2.cognito_user_id,
                portfolio_id=portfolio_id,
            )
            is None
        )
    finally:
        _delete_follower(
            model_portfolio_follower_repository,
            cognito_user_id=test_user_2.cognito_user_id,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_follower_repository_get_followers_count_changes(
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Read zero, n, n+1, and n-1 followers for the same portfolio."""
    portfolio_id = f"tests-v2-follower-counts-{uuid4()}"

    try:
        assert (
            model_portfolio_follower_repository.get_model_portfolio_followers(
                portfolio_id=portfolio_id
            )
            == []
        )

        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            alpaca_account_id=test_user_2.alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
        )
        followers_after_first_add = (
            model_portfolio_follower_repository.get_model_portfolio_followers(
                portfolio_id=portfolio_id
            )
        )
        assert len(followers_after_first_add) == 1
        assert {
            "alpaca_account_id": test_user_2.alpaca_account_id,
            "cognito_user_id": test_user_2.cognito_user_id,
        } in followers_after_first_add

        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
        )
        followers_after_second_add = (
            model_portfolio_follower_repository.get_model_portfolio_followers(
                portfolio_id=portfolio_id
            )
        )
        assert len(followers_after_second_add) == len(followers_after_first_add) + 1
        assert {
            "alpaca_account_id": test_user_1.alpaca_account_id,
            "cognito_user_id": test_user_1.cognito_user_id,
        } in followers_after_second_add

        model_portfolio_follower_repository.delete_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        followers_after_delete = (
            model_portfolio_follower_repository.get_model_portfolio_followers(
                portfolio_id=portfolio_id
            )
        )
        assert len(followers_after_delete) == len(followers_after_second_add) - 1
        assert {
            "alpaca_account_id": test_user_1.alpaca_account_id,
            "cognito_user_id": test_user_1.cognito_user_id,
        } in followers_after_delete
    finally:
        for cognito_user_id in (
            test_user_1.cognito_user_id,
            test_user_2.cognito_user_id,
        ):
            _delete_follower(
                model_portfolio_follower_repository,
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )

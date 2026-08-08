from uuid import uuid4

import pytest

from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)


@pytest.mark.integration
def test_model_portfolio_follower_repository_put_get_and_delete(
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    test_user_1,
    test_user_2,
) -> None:
    cognito_user_id = test_user_2.cognito_user_id
    alpaca_account_id = test_user_2.alpaca_account_id
    portfolio_id = f"repository-test-portfolio-{uuid4()}"
    portfolio_owner_cognito_user_id = test_user_1.cognito_user_id

    try:
        assert (
            model_portfolio_follower_repository.is_model_portfolio_follower(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            is False
        )

        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        )

        assert (
            model_portfolio_follower_repository.is_model_portfolio_follower(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            is True
        )
        assert model_portfolio_follower_repository.get_model_portfolio_followers(
            portfolio_id=portfolio_id,
        ) == [
            {
                "alpaca_account_id": alpaca_account_id,
                "cognito_user_id": cognito_user_id,
            }
        ]

        model_portfolio_follower_repository.delete_model_portfolio_follower(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
        )
        assert (
            model_portfolio_follower_repository.is_model_portfolio_follower(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
            is False
        )
        assert model_portfolio_follower_repository.get_model_portfolio_followers(
            portfolio_id=portfolio_id,
        ) == []
    finally:
        model_portfolio_follower_repository.dynamodb.delete_item(
            key={
                "cognito_user_id": cognito_user_id,
                "portfolio_id": portfolio_id,
            }
        )


@pytest.mark.integration
def test_model_portfolio_follower_repository_idempotent_put_and_delete_noop(
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    test_user_1,
    test_user_2,
) -> None:
    cognito_user_id = test_user_2.cognito_user_id
    alpaca_account_id = test_user_2.alpaca_account_id
    portfolio_id = f"repository-test-portfolio-{uuid4()}"
    portfolio_owner_cognito_user_id = test_user_1.cognito_user_id

    try:
        model_portfolio_follower_repository.delete_model_portfolio_follower(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
        )

        for _ in range(2):
            model_portfolio_follower_repository.put_model_portfolio_follower(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            )

        followers = model_portfolio_follower_repository.get_model_portfolio_followers(
            portfolio_id=portfolio_id,
        )
        assert followers == [
            {
                "alpaca_account_id": alpaca_account_id,
                "cognito_user_id": cognito_user_id,
            }
        ]
    finally:
        model_portfolio_follower_repository.dynamodb.delete_item(
            key={
                "cognito_user_id": cognito_user_id,
                "portfolio_id": portfolio_id,
            }
        )

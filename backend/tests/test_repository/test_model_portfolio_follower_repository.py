from uuid import uuid4

import pytest

from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerNotFoundError,
    ModelPortfolioFollowerRepository,
)


@pytest.mark.integration
def test_model_portfolio_follower_repository_put_get_and_delete(
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
) -> None:
    cognito_user_id = f"repository-test-follower-{uuid4()}"
    alpaca_account_id = f"repository-test-alpaca-{uuid4()}"
    portfolio_id = f"repository-test-portfolio-{uuid4()}"
    portfolio_owner_cognito_user_id = f"repository-test-owner-{uuid4()}"

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
        with pytest.raises(ModelPortfolioFollowerNotFoundError):
            model_portfolio_follower_repository.get_model_portfolio_followers(
                portfolio_id=portfolio_id,
            )
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
) -> None:
    cognito_user_id = f"repository-test-follower-{uuid4()}"
    alpaca_account_id = f"repository-test-alpaca-{uuid4()}"
    portfolio_id = f"repository-test-portfolio-{uuid4()}"
    portfolio_owner_cognito_user_id = f"repository-test-owner-{uuid4()}"

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

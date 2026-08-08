from __future__ import annotations

import pytest

from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
    ModelPortfolioAccessUserIsFollowerError,
)


class FakeDynamoDBClient:
    def __init__(self) -> None:
        self.deleted_keys = []

    def delete_item(self, *, key):
        self.deleted_keys.append(key)


class FakeCognitoClient:
    pass


class FakeModelPortfolioFollowerRepository:
    def __init__(self, *, is_follower: bool) -> None:
        self.is_follower = is_follower
        self.calls = []

    def is_model_portfolio_follower(
        self,
        *,
        cognito_user_id: str,
        portfolio_id: str,
    ) -> bool:
        self.calls.append(
            {
                "cognito_user_id": cognito_user_id,
                "portfolio_id": portfolio_id,
            }
        )
        return self.is_follower


def test_remove_access_for_user_deletes_when_user_is_not_follower() -> None:
    dynamodb = FakeDynamoDBClient()
    follower_repository = FakeModelPortfolioFollowerRepository(is_follower=False)
    repository = ModelPortfolioAccessRepository(
        dynamodb_client=dynamodb,
        cognito_client=FakeCognitoClient(),
        model_portfolio_follower_repository=follower_repository,
    )

    repository.remove_access_for_user(
        portfolio_id="portfolio-1",
        shared_with_cognito_user_id="shared-user",
    )

    assert follower_repository.calls == [
        {
            "cognito_user_id": "shared-user",
            "portfolio_id": "portfolio-1",
        }
    ]
    assert dynamodb.deleted_keys == [
        {
            "portfolio_id": "portfolio-1",
            "shared_with_cognito_user_id": "shared-user",
        }
    ]


def test_remove_access_for_user_blocks_follower_before_delete() -> None:
    dynamodb = FakeDynamoDBClient()
    repository = ModelPortfolioAccessRepository(
        dynamodb_client=dynamodb,
        cognito_client=FakeCognitoClient(),
        model_portfolio_follower_repository=FakeModelPortfolioFollowerRepository(
            is_follower=True
        ),
    )

    with pytest.raises(ModelPortfolioAccessUserIsFollowerError):
        repository.remove_access_for_user(
            portfolio_id="portfolio-1",
            shared_with_cognito_user_id="shared-user",
        )

    assert dynamodb.deleted_keys == []

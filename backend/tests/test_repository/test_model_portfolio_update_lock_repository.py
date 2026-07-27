from uuid import uuid4

import pytest

from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)


@pytest.mark.integration
def test_model_portfolio_update_lock_repository_acquire_renew_release(
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> None:
    portfolio_id = f"repository-test-lock-{uuid4()}"
    owner_token = str(uuid4())
    other_owner_token = str(uuid4())

    try:
        assert model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id,
        ) is None
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        ) is True
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=other_owner_token,
            lease_seconds=30,
        ) is False

        lock = model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id,
        )
        assert lock is not None
        assert lock["owner_token"] == owner_token

        assert model_portfolio_update_lock_repository.renew_lock(
            portfolio_id=portfolio_id,
            owner_token=other_owner_token,
            lease_seconds=30,
        ) is False
        assert model_portfolio_update_lock_repository.renew_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        ) is True

        assert model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=other_owner_token,
        ) is False
        assert model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        ) is True
        assert model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id,
        ) is None
    finally:
        model_portfolio_update_lock_repository.lock_table_client.delete_item(
            key={"portfolio_id": portfolio_id}
        )


@pytest.mark.integration
def test_model_portfolio_update_lock_repository_expired_lock_can_be_reacquired(
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> None:
    portfolio_id = f"repository-test-expired-lock-{uuid4()}"
    expired_owner_token = str(uuid4())
    new_owner_token = str(uuid4())

    try:
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=expired_owner_token,
            lease_seconds=-1,
        ) is True
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=new_owner_token,
            lease_seconds=30,
        ) is True
        lock = model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id,
        )
        assert lock["owner_token"] == new_owner_token
    finally:
        model_portfolio_update_lock_repository.lock_table_client.delete_item(
            key={"portfolio_id": portfolio_id}
        )

from uuid import uuid4

import pytest

from repository.user_trade_lock_repository import UserTradeLockRepository


@pytest.mark.integration
def test_user_trade_lock_repository_acquire_renew_release(
    user_trade_lock_repository: UserTradeLockRepository,
) -> None:
    cognito_user_id = f"repository-lock-user-{uuid4()}"
    owner_token = str(uuid4())
    other_owner_token = str(uuid4())

    try:
        assert (
            user_trade_lock_repository.get_lock(cognito_user_id=cognito_user_id)
            is None
        )
        assert user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=owner_token,
            lease_seconds=30,
            wait_seconds=0,
        ) is True
        assert user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=other_owner_token,
            lease_seconds=30,
            wait_seconds=0,
        ) is False

        assert user_trade_lock_repository.renew_lock(
            cognito_user_id=cognito_user_id,
            owner_token=other_owner_token,
        ) is False
        assert user_trade_lock_repository.renew_lock(
            cognito_user_id=cognito_user_id,
            owner_token=owner_token,
        ) is True

        assert user_trade_lock_repository.release_lock(
            cognito_user_id=cognito_user_id,
            owner_token=other_owner_token,
        ) is False
        assert user_trade_lock_repository.release_lock(
            cognito_user_id=cognito_user_id,
            owner_token=owner_token,
        ) is True
        assert (
            user_trade_lock_repository.get_lock(cognito_user_id=cognito_user_id)
            is None
        )
    finally:
        user_trade_lock_repository.lock_table_client.delete_item(
            key={"cognito_user_id": cognito_user_id}
        )


@pytest.mark.integration
def test_user_trade_lock_repository_expired_lock_can_be_reacquired(
    user_trade_lock_repository: UserTradeLockRepository,
) -> None:
    cognito_user_id = f"repository-expired-lock-user-{uuid4()}"
    expired_owner_token = str(uuid4())
    new_owner_token = str(uuid4())

    try:
        assert user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=expired_owner_token,
            lease_seconds=-1,
            wait_seconds=0,
        ) is True
        assert user_trade_lock_repository.acquire_lock(
            cognito_user_id=cognito_user_id,
            owner_token=new_owner_token,
            lease_seconds=30,
            wait_seconds=0,
        ) is True
        lock = user_trade_lock_repository.get_lock(cognito_user_id=cognito_user_id)
        assert lock["owner_token"] == new_owner_token
    finally:
        user_trade_lock_repository.lock_table_client.delete_item(
            key={"cognito_user_id": cognito_user_id}
        )

from __future__ import annotations

from uuid import uuid4

import pytest

from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)


"""
These tests exercise the non-mocked ModelPortfolioUpdateLockRepository paths
against the configured test DynamoDB table.

Coverage goals:
- acquire_lock(), get_lock(), renew_lock(), and release_lock(): acquire a new
  lock, verify the persisted lock fields, renew it with the owning token, then
  release it and verify the lock record is gone.
- active lock conflicts: verify a second owner cannot acquire, renew, or
  release a lock while the original owner's lease is still active, and verify
  the original owner cannot acquire the same active lock again because renewal
  is the supported extension path. Wrong-token renew must not change the lock
  expiration, and wrong-token release must not delete the lock.
- expired and missing lock paths: verify an expired lock can be reacquired by a
  new owner, old owners cannot release the new lock, and renew/release return
  false when no lock exists, including renewing after a lock has been released.
- string normalization: verify non-string portfolio IDs and owner tokens are
  stored as strings because the repository normalizes both with str(...).

Every test deletes the lock record it creates in finally blocks so the shared
integration lock table is left clean.
"""


def _delete_lock(
    repository: ModelPortfolioUpdateLockRepository,
    *,
    portfolio_id: str,
) -> None:
    repository.lock_table_client.delete_item(key={"portfolio_id": portfolio_id})


@pytest.mark.integration
def test_model_portfolio_update_lock_repository_acquire_get_renew_release(
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> None:
    """Acquire, read, renew, release, and verify removal of a lock."""
    portfolio_id = f"tests-v2-update-lock-{uuid4()}"
    owner_token = str(uuid4())

    try:
        assert (
            model_portfolio_update_lock_repository.get_lock(
                portfolio_id=portfolio_id
            )
            is None
        )
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )

        lock = model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id
        )
        assert lock is not None
        assert lock["portfolio_id"] == portfolio_id
        assert lock["owner_token"] == owner_token
        assert lock["created_at"]
        assert lock["updated_at"]
        assert lock["expires_at"]

        old_updated_at = lock["updated_at"]
        old_expires_at = lock["expires_at"]
        assert model_portfolio_update_lock_repository.renew_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=90,
        )

        renewed_lock = model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id
        )
        assert renewed_lock is not None
        assert renewed_lock["owner_token"] == owner_token
        assert renewed_lock["updated_at"] >= old_updated_at
        assert renewed_lock["expires_at"] > old_expires_at

        assert model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        )
        assert (
            model_portfolio_update_lock_repository.get_lock(
                portfolio_id=portfolio_id
            )
            is None
        )
    finally:
        _delete_lock(
            model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_update_lock_repository_active_lock_rejects_duplicate_and_other_owner(
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> None:
    """Reject duplicate acquire and non-owner acquire, renew, and release."""
    portfolio_id = f"tests-v2-update-lock-conflict-{uuid4()}"
    owner_token = str(uuid4())
    other_owner_token = str(uuid4())

    try:
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        assert not model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        assert not model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=other_owner_token,
            lease_seconds=30,
        )
        lock_before_wrong_token_renew = (
            model_portfolio_update_lock_repository.get_lock(
                portfolio_id=portfolio_id
            )
        )
        assert lock_before_wrong_token_renew is not None
        assert not model_portfolio_update_lock_repository.renew_lock(
            portfolio_id=portfolio_id,
            owner_token=other_owner_token,
            lease_seconds=60,
        )
        lock_after_wrong_token_renew = (
            model_portfolio_update_lock_repository.get_lock(
                portfolio_id=portfolio_id
            )
        )
        assert lock_after_wrong_token_renew is not None
        assert lock_after_wrong_token_renew["owner_token"] == owner_token
        assert lock_after_wrong_token_renew["expires_at"] == (
            lock_before_wrong_token_renew["expires_at"]
        )

        assert not model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=other_owner_token,
        )
        lock = model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id
        )
        assert lock is not None
        assert lock["owner_token"] == owner_token

        assert model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        )
    finally:
        _delete_lock(
            model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_update_lock_repository_expired_and_missing_lock_paths(
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> None:
    """Reacquire expired locks and return false for missing lock operations."""
    portfolio_id = f"tests-v2-update-lock-expired-{uuid4()}"
    owner_token = str(uuid4())
    new_owner_token = str(uuid4())
    missing_portfolio_id = f"tests-v2-update-lock-missing-{uuid4()}"

    try:
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=-1,
        )
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=new_owner_token,
            lease_seconds=30,
        )

        lock = model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id
        )
        assert lock is not None
        assert lock["owner_token"] == new_owner_token
        assert not model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        )
        assert model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=new_owner_token,
        )
        assert not model_portfolio_update_lock_repository.renew_lock(
            portfolio_id=portfolio_id,
            owner_token=new_owner_token,
            lease_seconds=30,
        )

        assert not model_portfolio_update_lock_repository.renew_lock(
            portfolio_id=missing_portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        assert not model_portfolio_update_lock_repository.release_lock(
            portfolio_id=missing_portfolio_id,
            owner_token=owner_token,
        )
    finally:
        for lock_portfolio_id in (portfolio_id, missing_portfolio_id):
            _delete_lock(
                model_portfolio_update_lock_repository,
                portfolio_id=lock_portfolio_id,
            )


@pytest.mark.integration
def test_model_portfolio_update_lock_repository_normalizes_ids_to_strings(
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
) -> None:
    """Store non-string portfolio IDs and owner tokens as strings."""
    portfolio_id = uuid4()
    owner_token = uuid4()
    portfolio_id_key = str(portfolio_id)

    try:
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )

        lock = model_portfolio_update_lock_repository.get_lock(
            portfolio_id=portfolio_id
        )
        assert lock is not None
        assert lock["portfolio_id"] == portfolio_id_key
        assert lock["owner_token"] == str(owner_token)

        assert model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        )
    finally:
        _delete_lock(
            model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id_key,
        )

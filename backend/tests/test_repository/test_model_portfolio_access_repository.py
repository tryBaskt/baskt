from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest

from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
    ModelPortfolioAccessUserIsFollowerError,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)


def _delete_access(
    repository: ModelPortfolioAccessRepository,
    *,
    portfolio_id: str,
    shared_with_cognito_user_id: str,
) -> None:
    repository.dynamodb.delete_item(
        key={
            "portfolio_id": portfolio_id,
            "shared_with_cognito_user_id": shared_with_cognito_user_id,
        }
    )


@pytest.mark.integration
def test_model_portfolio_access_repository_add_get_has_and_remove(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    portfolio_id = f"repository-access-{uuid4()}"

    try:
        model_portfolio_access_repository.add_access_via_email(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_email=test_user_2.email_address,
            granted_access_by="PORTFOLIO_OWNER",
        )

        assert model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        accesses = model_portfolio_access_repository.get_accesses_for_portfolio(
            portfolio_id=portfolio_id,
        )
        assert len(accesses) == 1
        assert accesses[0]["portfolio_id"] == portfolio_id
        assert accesses[0]["portfolio_owner_cognito_user_id"] == (
            test_user_1.cognito_user_id
        )
        assert accesses[0]["shared_with_cognito_user_id"] == (
            test_user_2.cognito_user_id
        )
        assert accesses[0]["shared_with_cognito_user_email"] == (
            test_user_2.email_address.strip().lower()
        )

        shared_with_user = (
            model_portfolio_access_repository.get_accesses_for_shared_with_user(
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )
        )
        assert any(access.portfolio_id == portfolio_id for access in shared_with_user)

        model_portfolio_access_repository.remove_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        assert (
            model_portfolio_access_repository.has_access(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )
            is False
        )
    finally:
        _delete_access(
            model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )


@pytest.mark.integration
def test_model_portfolio_access_repository_blocks_remove_for_follower(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    test_user_1,
    test_user_2,
) -> None:
    portfolio_id = f"repository-access-follower-{uuid4()}"

    try:
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            alpaca_account_id=test_user_2.alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
        )

        with pytest.raises(ModelPortfolioAccessUserIsFollowerError):
            model_portfolio_access_repository.remove_access_via_cognito_user_id(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )

        assert model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
    finally:
        model_portfolio_follower_repository.dynamodb.delete_item(
            key={
                "cognito_user_id": test_user_2.cognito_user_id,
                "portfolio_id": portfolio_id,
            }
        )
        _delete_access(
            model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )


@pytest.mark.integration
def test_model_portfolio_access_repository_add_by_cognito_user_id_writes_expected_item(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    portfolio_id = f"repository-access-cognito-id-{uuid4()}"

    try:
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )

        access = model_portfolio_access_repository.dynamodb.get_item(
            key={
                "portfolio_id": portfolio_id,
                "shared_with_cognito_user_id": test_user_2.cognito_user_id,
            }
        )
        assert access is not None
        assert access["portfolio_id"] == portfolio_id
        assert access["portfolio_owner_cognito_user_id"] == (
            test_user_1.cognito_user_id
        )
        assert access["shared_with_cognito_user_id"] == test_user_2.cognito_user_id
        assert access["shared_with_cognito_user_email"] == (
            test_user_2.email_address.strip().lower()
        )
        assert access["granted_access_at"]
    finally:
        _delete_access(
            model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )


@pytest.mark.integration
@pytest.mark.integration
def test_model_portfolio_access_repository_has_access_returns_false_for_missing_access(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_2,
) -> None:
    portfolio_id = f"repository-access-missing-{uuid4()}"

    assert (
        model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        is False
    )


def _release_lock_later(
    lock_repository: ModelPortfolioUpdateLockRepository,
    *,
    portfolio_id: str,
    owner_token: str,
    delay_seconds: float,
) -> threading.Timer:
    timer = threading.Timer(
        delay_seconds,
        lambda: lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        ),
    )
    timer.start()
    return timer


@pytest.mark.integration
def test_model_portfolio_access_repository_reads_wait_for_update_lock(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1,
    test_user_2,
) -> None:
    portfolio_id = f"repository-access-lock-wait-{uuid4()}"
    owner_token = str(uuid4())
    lock_acquired = False

    try:
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        lock_acquired = True

        timer = _release_lock_later(
            model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            delay_seconds=0.5,
        )
        started_at = time.monotonic()
        assert model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        assert time.monotonic() - started_at >= 0.4
        timer.join(timeout=2)

        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        lock_acquired = True
        timer = _release_lock_later(
            model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            delay_seconds=0.5,
        )
        started_at = time.monotonic()
        assert len(
            model_portfolio_access_repository.get_accesses_for_portfolio(
                portfolio_id=portfolio_id,
            )
        ) == 1
        assert time.monotonic() - started_at >= 0.4
        timer.join(timeout=2)
    finally:
        if lock_acquired:
            model_portfolio_update_lock_repository.release_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )
        _delete_access(
            model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )

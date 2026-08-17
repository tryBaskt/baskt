from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest

from clients.cognito_client import CognitoClient, CognitoClientCognitoUserNotFound
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessLockedError,
    ModelPortfolioAccessNotFoundError,
    ModelPortfolioAccessRepository,
    ModelPortfolioAccessUserNotFoundError,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)


"""
These tests exercise the non-mocked ModelPortfolioAccessRepository paths against
the configured test DynamoDB table and Cognito user pool.

Coverage goals:
- add_access_via_email(): resolve an existing shared user's email through
  Cognito and write the access record, then assert an unknown email raises
  ModelPortfolioAccessUserNotFoundError.
- add_access_via_cognito_user_id(): resolve an existing Cognito user ID
  and write the access record, then assert an unknown Cognito user ID raises
  ModelPortfolioAccessUserNotFoundError.
- remove_access_via_cognito_user_id(): delete an existing access record, return
  a pending-removal result for a follower, and assert removing a missing access
  raises ModelPortfolioAccessNotFoundError.
- has_access(): return false before an access grant exists and true after the
  grant is written.
- lock handling: assert add/remove operations fail while another update lock is
  held, and assert read operations wait for the lock to be released before
  returning access records.
- add_access_via_cognito_user_id_without_lock(): write an access record
  while a caller-owned portfolio update lock is active.
- get_accesses_for_portfolio(): return no records for a new portfolio ID,
  return multiple records after grants are added, return n-1 records after a
  grant is removed, and return n+1 records after a grant is added back.
- get_accesses_for_shared_with_user(): return no records for a user with no grants,
  return multiple records for one shared user, return n-1 records after one
  portfolio grant is removed, and return n+1 records after it is added back.
- granted_access_by precedence: assert PORTFOLIO_OWNER access upgrades an
  existing ALLOCATION access record, and assert a later ALLOCATION write does
  not downgrade an existing PORTFOLIO_OWNER access record.

Every test deletes access and follower records it creates. The one test that
creates a temporary Cognito user also deletes that user in its finally block.
"""


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


def _create_cognito_user(cognito_client: CognitoClient) -> tuple[str, str]:
    email_address = f"tests_v2_access_{uuid4().hex}@example.com"
    cognito_user_id = cognito_client.create_cognito_user(
        account_data={
            "contact": {"email_address": email_address},
            "identity": {
                "given_name": "Access",
                "family_name": "Tester",
            },
        },
        alpaca_account_id=str(uuid4()),
        alpaca_account_number=f"ACCT{uuid4().hex[:8].upper()}",
        password=f"Test_9aA{uuid4().hex[:16]}",
    )
    return cognito_user_id, email_address


def _delete_cognito_user(
    cognito_client: CognitoClient,
    *,
    cognito_user_id: str,
) -> None:
    try:
        cognito_client.delete_cognito_user(cognito_user_id=cognito_user_id)
    except CognitoClientCognitoUserNotFound:
        pass


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
def test_model_portfolio_access_repository_add_access_via_email_success_and_missing_email(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Add access by email and raise when the shared email does not exist."""
    portfolio_id = f"tests-v2-access-email-{uuid4()}"

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

        with pytest.raises(ModelPortfolioAccessUserNotFoundError):
            model_portfolio_access_repository.add_access_via_email(
                portfolio_id=f"tests-v2-access-missing-email-{uuid4()}",
                portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
                shared_with_email=f"missing-tests-v2-{uuid4().hex}@example.com",
                granted_access_by="PORTFOLIO_OWNER",
            )
    finally:
        _delete_access(
            model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )


@pytest.mark.integration
def test_model_portfolio_access_repository_add_access_by_cognito_id_success_and_missing_user(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Add access by Cognito user ID and raise when that user does not exist."""
    portfolio_id = f"tests-v2-access-cognito-{uuid4()}"

    try:
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        assert model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )

        with pytest.raises(ModelPortfolioAccessUserNotFoundError):
            model_portfolio_access_repository.add_access_via_cognito_user_id(
                portfolio_id=f"tests-v2-access-missing-cognito-{uuid4()}",
                portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
                shared_with_cognito_user_id=f"missing-tests-v2-user-{uuid4()}",
                granted_access_by="PORTFOLIO_OWNER",
            )
    finally:
        _delete_access(
            model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )


@pytest.mark.integration
def test_model_portfolio_access_repository_remove_access_success_follower_and_missing(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Remove access, defer follower removal, and raise for missing access."""
    removable_portfolio_id = f"tests-v2-access-remove-{uuid4()}"
    follower_portfolio_id = f"tests-v2-access-follower-{uuid4()}"

    try:
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=removable_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        removal_result = model_portfolio_access_repository.remove_access_via_cognito_user_id(
            portfolio_id=removable_portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        assert removal_result.removed is True
        assert removal_result.pending_removal is False
        assert removal_result.message is None
        assert not model_portfolio_access_repository.has_access(
            portfolio_id=removable_portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )

        with pytest.raises(ModelPortfolioAccessNotFoundError):
            model_portfolio_access_repository.remove_access_via_cognito_user_id(
                portfolio_id=f"tests-v2-access-missing-remove-{uuid4()}",
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )

        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=follower_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            alpaca_account_id=test_user_2.alpaca_account_id,
            portfolio_id=follower_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
        )
        follower_removal_result = model_portfolio_access_repository.remove_access_via_cognito_user_id(
            portfolio_id=follower_portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        assert follower_removal_result.removed is False
        assert follower_removal_result.pending_removal is True
        assert follower_removal_result.message == (
            "User is currently following this model portfolio. "
            "Access will be removed after they withdraw all their money."
        )
        access_record = model_portfolio_access_repository.get_access_record(
            portfolio_id=follower_portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        assert access_record is not None
        assert access_record.status == "TO_BE_DELETED"
    finally:
        for portfolio_id in (removable_portfolio_id, follower_portfolio_id):
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
def test_model_portfolio_access_repository_has_access_true_and_false(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Return true for an existing access record and false for a missing one."""
    portfolio_id = f"tests-v2-access-has-{uuid4()}"

    try:
        assert not model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        assert model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
    finally:
        _delete_access(
            model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )


@pytest.mark.integration
def test_model_portfolio_access_repository_locked_add_read_and_remove_paths(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Block writes while locked and wait for the lock before reading access."""
    portfolio_id = f"tests-v2-access-lock-{uuid4()}"
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
        with pytest.raises(ModelPortfolioAccessLockedError):
            model_portfolio_access_repository.add_access_via_cognito_user_id(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
                granted_access_by="PORTFOLIO_OWNER",
            )
        model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        )
        lock_acquired = False

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
        lock_acquired = False

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
                portfolio_id=portfolio_id
            )
        ) == 1
        assert time.monotonic() - started_at >= 0.4
        timer.join(timeout=2)
        lock_acquired = False

        assert model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        lock_acquired = True
        with pytest.raises(ModelPortfolioAccessLockedError):
            model_portfolio_access_repository.remove_access_via_cognito_user_id(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )
        model_portfolio_update_lock_repository.release_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
        )
        lock_acquired = False

        model_portfolio_access_repository.remove_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        assert not model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
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


@pytest.mark.integration
def test_model_portfolio_access_repository_write_without_lock_under_existing_lock(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Write access without acquiring a lock while an outer lock is active."""
    portfolio_id = f"tests-v2-access-write-no-lock-{uuid4()}"
    owner_token = str(uuid4())
    lock_acquired = False

    try:
        lock_acquired = model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        assert lock_acquired

        model_portfolio_access_repository.add_access_via_cognito_user_id_without_lock(
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
        assert access["portfolio_owner_cognito_user_id"] == (
            test_user_1.cognito_user_id
        )
        assert access["shared_with_email"] == (
            test_user_2.email_address.strip().lower()
        )
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


@pytest.mark.integration
def test_model_portfolio_access_repository_get_accesses_for_portfolio_counts_change(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    cognito_client: CognitoClient,
    test_user_1,
    test_user_2,
) -> None:
    """Return no, multiple, n-1, and n+1 portfolio access records."""
    portfolio_id = f"tests-v2-access-portfolio-counts-{uuid4()}"
    shared_user_3_id = None
    shared_user_3_email = None

    try:
        shared_user_3_id, shared_user_3_email = _create_cognito_user(cognito_client)

        assert (
            model_portfolio_access_repository.get_accesses_for_portfolio(
                portfolio_id=portfolio_id
            )
            == []
        )
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        model_portfolio_access_repository.add_access_via_email(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_email=shared_user_3_email,
            granted_access_by="PORTFOLIO_OWNER",
        )
        assert len(
            model_portfolio_access_repository.get_accesses_for_portfolio(
                portfolio_id=portfolio_id
            )
        ) == 2

        model_portfolio_access_repository.remove_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        assert len(
            model_portfolio_access_repository.get_accesses_for_portfolio(
                portfolio_id=portfolio_id
            )
        ) == 1

        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        assert len(
            model_portfolio_access_repository.get_accesses_for_portfolio(
                portfolio_id=portfolio_id
            )
        ) == 2
    finally:
        for shared_with_cognito_user_id in (
            test_user_2.cognito_user_id,
            shared_user_3_id,
        ):
            if shared_with_cognito_user_id:
                _delete_access(
                    model_portfolio_access_repository,
                    portfolio_id=portfolio_id,
                    shared_with_cognito_user_id=shared_with_cognito_user_id,
                )
        if shared_user_3_id:
            _delete_cognito_user(cognito_client, cognito_user_id=shared_user_3_id)


@pytest.mark.integration
def test_model_portfolio_access_repository_get_accesses_for_shared_with_user_counts_change(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Return no, multiple, n-1, and n+1 access records shared with a user."""
    first_portfolio_id = f"tests-v2-shared-first-{uuid4()}"
    second_portfolio_id = f"tests-v2-shared-second-{uuid4()}"
    missing_user_id = f"tests-v2-shared-missing-user-{uuid4()}"

    try:
        assert (
            model_portfolio_access_repository.get_accesses_for_shared_with_user(
                shared_with_cognito_user_id=missing_user_id
            )
            == []
        )
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=first_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=second_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        shared_accesses = (
            model_portfolio_access_repository.get_accesses_for_shared_with_user(
                shared_with_cognito_user_id=test_user_2.cognito_user_id
            )
        )
        assert {first_portfolio_id, second_portfolio_id} <= {
            access.portfolio_id
            for access in shared_accesses
        }

        model_portfolio_access_repository.remove_access_via_cognito_user_id(
            portfolio_id=first_portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
        shared_after_remove = (
            model_portfolio_access_repository.get_accesses_for_shared_with_user(
                shared_with_cognito_user_id=test_user_2.cognito_user_id
            )
        )
        assert len(shared_after_remove) == len(shared_accesses) - 1
        assert second_portfolio_id in {
            access.portfolio_id
            for access in shared_after_remove
        }

        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=first_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
        )
        shared_after_add = (
            model_portfolio_access_repository.get_accesses_for_shared_with_user(
                shared_with_cognito_user_id=test_user_2.cognito_user_id
            )
        )
        assert len(shared_after_add) == len(shared_after_remove) + 1
        assert {first_portfolio_id, second_portfolio_id} <= {
            access.portfolio_id
            for access in shared_after_add
        }
    finally:
        for portfolio_id in (first_portfolio_id, second_portfolio_id):
            _delete_access(
                model_portfolio_access_repository,
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )


@pytest.mark.integration
def test_model_portfolio_access_repository_portfolio_owner_access_takes_precedence(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    """PORTFOLIO_OWNER grants upgrade and cannot be downgraded by ALLOCATION grants."""
    allocation_first_portfolio_id = (
        f"tests-v2-access-precedence-allocation-first-{uuid4()}"
    )
    owner_first_portfolio_id = f"tests-v2-access-precedence-owner-first-{uuid4()}"

    try:
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=allocation_first_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="ALLOCATION",
        )
        assert (
            model_portfolio_access_repository.get_access_record(
                portfolio_id=allocation_first_portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            ).granted_access_by
            == "ALLOCATION"
        )

        model_portfolio_access_repository.add_access_via_email(
            portfolio_id=allocation_first_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_email=test_user_2.email_address,
            granted_access_by="PORTFOLIO_OWNER",
        )
        assert (
            model_portfolio_access_repository.get_access_record(
                portfolio_id=allocation_first_portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            ).granted_access_by
            == "PORTFOLIO_OWNER"
        )

        model_portfolio_access_repository.add_access_via_email(
            portfolio_id=owner_first_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_email=test_user_2.email_address,
            granted_access_by="PORTFOLIO_OWNER",
        )
        model_portfolio_access_repository.add_access_via_cognito_user_id(
            portfolio_id=owner_first_portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
            granted_access_by="ALLOCATION",
        )
        assert (
            model_portfolio_access_repository.get_access_record(
                portfolio_id=owner_first_portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            ).granted_access_by
            == "PORTFOLIO_OWNER"
        )
    finally:
        for portfolio_id in (
            allocation_first_portfolio_id,
            owner_first_portfolio_id,
        ):
            _delete_access(
                model_portfolio_access_repository,
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )

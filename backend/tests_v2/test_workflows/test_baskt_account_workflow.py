from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.authentication import get_current_baskt_account
from core.deps import (
    get_baskt_account_repository,
    get_model_portfolio_repository,
)
from domain.baskt_account_domain import BasktAccount
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from routes import baskt_account_route
from schema.model_portfolio_schema import ModelPortfolioPositionRequest


pytestmark = pytest.mark.integration


"""
These workflow tests exercise baskt_account_route.py through FastAPI's
TestClient while keeping repository dependencies wired to the real tests_v2
integration repositories.

Coverage goals:
- get_baskt_account_profile(): the path profile_cognito_user_id identifies the
  profile account being viewed; the authenticated Baskt account is only the
  viewer.
- get_baskt_account_profile(): return the profile account's public account
  metadata, not the authenticated viewer's account metadata.
- get_baskt_account_profile(): return an empty model_portfolios response when
  the profile account owns no model portfolios.
- get_baskt_account_profile(): return n > 0 model portfolio metadata rows when
  the profile account owns portfolios.
- get_baskt_account_profile(): return model portfolio metadata scoped to the
  profile owner, without leaking portfolios owned by the viewer or other users.
- get_baskt_account_profile(): include public and private portfolio metadata on
  the profile page even when the viewer was not granted model portfolio access.
- get_baskt_account_profile(): return 404 for unknown profile accounts and 400
  for blank/whitespace profile_cognito_user_id values.
- Authentication: unauthenticated requests are rejected by the auth dependency.

Every synthetic account and model portfolio created here is cleaned up in
finally blocks.
"""


CREATED_AT = datetime(2024, 1, 2, 14, tzinfo=timezone.utc)


def _client_for_viewer(
    *,
    viewer_baskt_account: BasktAccount,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
) -> TestClient:
    app = FastAPI()
    app.include_router(baskt_account_route.router)
    app.dependency_overrides[
        baskt_account_route.get_current_baskt_account
    ] = lambda: viewer_baskt_account
    app.dependency_overrides[get_current_baskt_account] = (
        lambda: viewer_baskt_account
    )
    app.dependency_overrides[
        baskt_account_route.get_baskt_account_repository
    ] = lambda: baskt_account_repository
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[
        baskt_account_route.get_model_portfolio_repository
    ] = lambda: model_portfolio_repository
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    return TestClient(app)


def _unauthenticated_client(
    *,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
) -> TestClient:
    app = FastAPI()
    app.include_router(baskt_account_route.router)
    app.dependency_overrides[
        baskt_account_route.get_baskt_account_repository
    ] = lambda: baskt_account_repository
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[
        baskt_account_route.get_model_portfolio_repository
    ] = lambda: model_portfolio_repository
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    return TestClient(app)


def _synthetic_account(
    *,
    base_account: BasktAccount,
    label: str,
) -> BasktAccount:
    unique = uuid4().hex
    return replace(
        base_account,
        cognito_user_id=f"tests-v2-{label}-{unique}",
        display_name=f"tests-v2-{label}-{unique}",
        description=f"tests-v2 {label} profile",
    )


def _write_synthetic_account(
    *,
    baskt_account_repository: BasktAccountRepository,
    base_account: BasktAccount,
    label: str,
) -> BasktAccount:
    account = _synthetic_account(base_account=base_account, label=label)
    baskt_account_repository.write_baskt_account(account)
    return account


def _delete_account(
    *,
    baskt_account_repository: BasktAccountRepository,
    account: BasktAccount | None,
) -> None:
    if account is not None:
        baskt_account_repository.delete_baskt_account(
            cognito_user_id=account.cognito_user_id
        )


def _create_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    visibility: str,
    description: str,
) -> str:
    return model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=owner_cognito_user_id,
        portfolio_name=f"baskt-account-workflow-{uuid4()}",
        positions_request=[
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1,
            )
        ],
        visibility=visibility,
        creation_time=CREATED_AT,
        description=description,
    )


def _delete_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    portfolio_id: str | None,
) -> None:
    if portfolio_id is None:
        return
    try:
        for access in model_portfolio_access_repository.get_accesses_for_portfolio(
            portfolio_id=portfolio_id,
            wait_for_lock=False,
        ):
            model_portfolio_access_repository.dynamodb.delete_item(
                key={
                    "portfolio_id": portfolio_id,
                    "shared_with_cognito_user_id": access[
                        "shared_with_cognito_user_id"
                    ],
                }
            )
    except Exception:
        pass
    try:
        for follower in (
            model_portfolio_follower_repository.get_model_portfolio_followers(
                portfolio_id=portfolio_id,
            )
        ):
            model_portfolio_follower_repository.delete_model_portfolio_follower(
                cognito_user_id=follower["cognito_user_id"],
                portfolio_id=portfolio_id,
            )
    except Exception:
        pass
    try:
        model_portfolio_update_lock_repository.lock_table_client.delete_item(
            key={"portfolio_id": portfolio_id}
        )
    except Exception:
        pass
    model_portfolio_repository.dynamodb.delete_item(key={"portfolio_id": portfolio_id})


def _portfolio_ids(body: dict[str, Any]) -> set[str]:
    return {
        portfolio["portfolio_id"]
        for portfolio in body["model_portfolios"]
    }


def test_baskt_account_profile_returns_profile_metadata_with_no_portfolios(
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: Any,
) -> None:
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    profile_account: BasktAccount | None = None
    try:
        profile_account = _write_synthetic_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            label="profile-empty",
        )
        client = _client_for_viewer(
            viewer_baskt_account=profile_account,
            baskt_account_repository=baskt_account_repository,
            model_portfolio_repository=model_portfolio_repository,
        )

        response = client.get(
            f"/baskt-accounts/{profile_account.cognito_user_id}/profile"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["baskt_account"] == {
            "cognito_user_id": profile_account.cognito_user_id,
            "display_name": profile_account.display_name,
            "description": profile_account.description,
        }
        assert body["model_portfolios"] == []
    finally:
        _delete_account(
            baskt_account_repository=baskt_account_repository,
            account=profile_account,
        )


def test_baskt_account_profile_returns_owned_model_portfolio_metadata(
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1: Any,
) -> None:
    base_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    profile_account: BasktAccount | None = None
    portfolio_ids: list[str] = []
    try:
        profile_account = _write_synthetic_account(
            baskt_account_repository=baskt_account_repository,
            base_account=base_account,
            label="profile-owned",
        )
        public_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=profile_account.cognito_user_id,
            visibility="PUBLIC",
            description="public profile portfolio",
        )
        private_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=profile_account.cognito_user_id,
            visibility="PRIVATE",
            description="private profile portfolio",
        )
        portfolio_ids.extend([public_id, private_id])
        client = _client_for_viewer(
            viewer_baskt_account=profile_account,
            baskt_account_repository=baskt_account_repository,
            model_portfolio_repository=model_portfolio_repository,
        )

        response = client.get(
            f"/baskt-accounts/{profile_account.cognito_user_id}/profile"
        )

        assert response.status_code == 200
        body = response.json()
        assert {public_id, private_id} <= _portfolio_ids(body)
        returned = {
            portfolio["portfolio_id"]: portfolio
            for portfolio in body["model_portfolios"]
            if portfolio["portfolio_id"] in {public_id, private_id}
        }
        assert returned[public_id]["portfolio_owner_cognito_user_id"] == (
            profile_account.cognito_user_id
        )
        assert returned[public_id]["description"] == "public profile portfolio"
        assert returned[public_id]["visibility"] == "PUBLIC"
        assert returned[private_id]["description"] == "private profile portfolio"
        assert returned[private_id]["visibility"] == "PRIVATE"
    finally:
        for portfolio_id in portfolio_ids:
            _delete_model_portfolio(
                model_portfolio_repository=model_portfolio_repository,
                model_portfolio_access_repository=model_portfolio_access_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
                portfolio_id=portfolio_id,
            )
        _delete_account(
            baskt_account_repository=baskt_account_repository,
            account=profile_account,
        )


def test_baskt_account_profile_viewer_sees_unshared_profile_portfolio_metadata(
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    viewer_base = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    profile_base = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_2.cognito_user_id
    )
    viewer_account: BasktAccount | None = None
    profile_account: BasktAccount | None = None
    portfolio_ids: list[str] = []
    try:
        viewer_account = _write_synthetic_account(
            baskt_account_repository=baskt_account_repository,
            base_account=viewer_base,
            label="viewer",
        )
        profile_account = _write_synthetic_account(
            baskt_account_repository=baskt_account_repository,
            base_account=profile_base,
            label="profile-visible",
        )
        profile_public_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=profile_account.cognito_user_id,
            visibility="PUBLIC",
            description="profile public metadata",
        )
        profile_private_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=profile_account.cognito_user_id,
            visibility="PRIVATE",
            description="profile private metadata",
        )
        viewer_portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=viewer_account.cognito_user_id,
            visibility="PUBLIC",
            description="viewer portfolio should not leak",
        )
        portfolio_ids.extend(
            [profile_public_id, profile_private_id, viewer_portfolio_id]
        )
        assert not model_portfolio_access_repository.has_access(
            portfolio_id=profile_private_id,
            shared_with_cognito_user_id=viewer_account.cognito_user_id,
        )
        client = _client_for_viewer(
            viewer_baskt_account=viewer_account,
            baskt_account_repository=baskt_account_repository,
            model_portfolio_repository=model_portfolio_repository,
        )

        response = client.get(
            f"/baskt-accounts/{profile_account.cognito_user_id}/profile"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["baskt_account"]["cognito_user_id"] == (
            profile_account.cognito_user_id
        )
        assert body["baskt_account"]["cognito_user_id"] != (
            viewer_account.cognito_user_id
        )
        assert {profile_public_id, profile_private_id} <= _portfolio_ids(body)
        assert viewer_portfolio_id not in _portfolio_ids(body)
    finally:
        for portfolio_id in portfolio_ids:
            _delete_model_portfolio(
                model_portfolio_repository=model_portfolio_repository,
                model_portfolio_access_repository=model_portfolio_access_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
                portfolio_id=portfolio_id,
            )
        _delete_account(
            baskt_account_repository=baskt_account_repository,
            account=viewer_account,
        )
        _delete_account(
            baskt_account_repository=baskt_account_repository,
            account=profile_account,
        )


def test_baskt_account_profile_unknown_and_blank_profile_ids(
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: Any,
) -> None:
    viewer_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    client = _client_for_viewer(
        viewer_baskt_account=viewer_account,
        baskt_account_repository=baskt_account_repository,
        model_portfolio_repository=model_portfolio_repository,
    )

    missing_response = client.get(f"/baskt-accounts/{uuid4()}/profile")
    blank_response = client.get("/baskt-accounts/%20%20/profile")

    assert missing_response.status_code == 404
    assert blank_response.status_code == 400
    assert blank_response.json()["detail"] == "profile_cognito_user_id is required."


def test_baskt_account_profile_requires_authentication(
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1: Any,
) -> None:
    client = _unauthenticated_client(
        baskt_account_repository=baskt_account_repository,
        model_portfolio_repository=model_portfolio_repository,
    )

    response = client.get(f"/baskt-accounts/{test_user_1.cognito_user_id}/profile")

    assert response.status_code == 401

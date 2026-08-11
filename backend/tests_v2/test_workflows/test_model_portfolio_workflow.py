from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.authentication import get_current_user
from core.deps import (
    get_baskt_account_repository,
    get_model_portfolio_access_repository,
    get_model_portfolio_repository,
)
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
from routes import model_portfolio_route
from schema.model_portfolio_schema import ModelPortfolioPositionRequest


pytestmark = pytest.mark.integration


"""
These workflow tests exercise model_portfolio_route.py through FastAPI's
TestClient while keeping repository dependencies wired to the real tests_v2
integration repositories.

Coverage goals:
- create/list workflow: create public and private model portfolios through the
  route and verify owned metadata is listed with visibility.
- request validation workflow: assert route/schema-level validation for invalid
  create and update payloads before repository work should happen.
- get authorization workflow: owners and public viewers can fetch a portfolio,
  unshared private viewers are denied, and shared private viewers are allowed.
- update workflow: route updates description, visibility, and positions; changed
  positions enqueue one portfolio update message; missing, non-owner, and
  too-soon updates map to the expected HTTP errors.
- access workflow: owners can add access by email, list accesses, see the shared
  portfolio from the recipient account, remove access, and then the recipient is
  denied again.
- access error workflow: non-owners cannot manage accesses, missing portfolios
  return not found, empty access lists return an empty response, and follower
  users cannot have access removed.
- public-to-private follower workflow: changing a public portfolio with a
  follower to private preserves the follower, grants explicit access to that
  follower, and does not add a new snapshot when positions are unchanged.

The analytics route is intentionally excluded. Every portfolio, access,
follower, and update-lock item created here is cleaned up in finally blocks.
"""


CREATED_AT = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)


class QueueRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def queue_portfolio_update(
        self,
        *,
        portfolio_id: str,
        portfolio_snapshot_id: str,
    ) -> None:
        self.calls.append(
            {
                "portfolio_id": portfolio_id,
                "portfolio_snapshot_id": portfolio_snapshot_id,
            }
        )


def _claims_for_user(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _client_for_user(
    *,
    test_user: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    baskt_account_repository: BasktAccountRepository,
    queue_recorder: QueueRecorder | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(model_portfolio_route.router)
    app.dependency_overrides[get_current_user] = lambda: _claims_for_user(test_user)
    app.dependency_overrides[
        model_portfolio_route.get_model_portfolio_repository
    ] = lambda: model_portfolio_repository
    app.dependency_overrides[
        model_portfolio_route.get_model_portfolio_access_repository
    ] = lambda: model_portfolio_access_repository
    app.dependency_overrides[
        model_portfolio_route.get_baskt_account_repository
    ] = lambda: baskt_account_repository
    app.dependency_overrides[
        get_model_portfolio_repository
    ] = lambda: model_portfolio_repository
    app.dependency_overrides[
        get_model_portfolio_access_repository
    ] = lambda: model_portfolio_access_repository
    app.dependency_overrides[
        get_baskt_account_repository
    ] = lambda: baskt_account_repository

    if queue_recorder is not None:
        app.dependency_overrides[
            model_portfolio_route.get_trade_execution_queuing_service
        ] = lambda: queue_recorder

    return TestClient(app)


def _position(
    *,
    symbol: str = "AAPL",
    target_weight: float = 1.0,
    direction: int = 1,
    leverage: int = 1,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "target_weight": target_weight,
        "direction": direction,
        "leverage": leverage,
    }


def _create_payload(
    *,
    name: str,
    description: str = "Workflow route portfolio",
    visibility: str = "PUBLIC",
    positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "visibility": visibility,
        "positions": positions if positions is not None else [_position()],
    }


def _update_payload(
    *,
    description: str = "Updated workflow route portfolio",
    visibility: str = "PUBLIC",
    positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "description": description,
        "visibility": visibility,
        "positions": positions if positions is not None else [_position()],
    }


def _repository_position(
    *,
    symbol: str = "AAPL",
    target_weight: float = 1.0,
    direction: int = 1,
) -> ModelPortfolioPositionRequest:
    return ModelPortfolioPositionRequest(
        symbol=symbol,
        target_weight=target_weight,
        direction=direction,
        leverage=1,
    )


def _create_portfolio_direct(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    portfolio_name: str,
    visibility: str = "PUBLIC",
    description: str = "Workflow route portfolio",
    positions: list[ModelPortfolioPositionRequest] | None = None,
) -> str:
    return model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=owner_cognito_user_id,
        portfolio_name=portfolio_name,
        positions_request=positions or [_repository_position()],
        visibility=visibility,
        creation_time=CREATED_AT,
        description=description,
    )


def _find_portfolio_id_by_name(
    *,
    client: TestClient,
    portfolio_name: str,
) -> str:
    response = client.get("/model-portfolios")
    assert response.status_code == 200
    for portfolio in response.json():
        if portfolio["portfolio_name"] == portfolio_name:
            return portfolio["portfolio_id"]
    raise AssertionError(f"portfolio '{portfolio_name}' was not listed")


def _delete_access(
    *,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    portfolio_id: str,
    shared_with_cognito_user_id: str,
) -> None:
    model_portfolio_access_repository.dynamodb.delete_item(
        key={
            "portfolio_id": portfolio_id,
            "shared_with_cognito_user_id": shared_with_cognito_user_id,
        }
    )


def _delete_follower(
    *,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    portfolio_id: str,
    cognito_user_id: str,
) -> None:
    model_portfolio_follower_repository.dynamodb.delete_item(
        key={
            "cognito_user_id": cognito_user_id,
            "portfolio_id": portfolio_id,
        }
    )


def _delete_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    portfolio_id: str,
) -> None:
    for access in model_portfolio_access_repository.get_accesses_for_portfolio(
        portfolio_id=portfolio_id,
        wait_for_lock=False,
    ):
        _delete_access(
            model_portfolio_access_repository=model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=access["shared_with_cognito_user_id"],
        )

    for follower in model_portfolio_follower_repository.get_model_portfolio_followers(
        portfolio_id=portfolio_id,
    ):
        _delete_follower(
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            portfolio_id=portfolio_id,
            cognito_user_id=follower["cognito_user_id"],
        )

    model_portfolio_update_lock_repository.lock_table_client.delete_item(
        key={"portfolio_id": portfolio_id}
    )
    model_portfolio_repository.dynamodb.delete_item(
        key={"portfolio_id": portfolio_id}
    )


def test_model_portfolio_route_create_and_list_owned_public_and_private_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    """Create public/private portfolios through the route and list owned metadata."""
    client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    public_name = f"workflow-public-{uuid4()}"
    private_name = f"workflow-private-{uuid4()}"
    created_ids: list[str] = []

    try:
        public_response = client.post(
            "/model-portfolios",
            json=_create_payload(name=public_name, visibility="PUBLIC"),
        )
        assert public_response.status_code == 201
        public_id = _find_portfolio_id_by_name(
            client=client,
            portfolio_name=public_name,
        )
        created_ids.append(public_id)

        private_response = client.post(
            "/model-portfolios",
            json=_create_payload(name=private_name, visibility="PRIVATE"),
        )
        assert private_response.status_code == 201
        private_id = _find_portfolio_id_by_name(
            client=client,
            portfolio_name=private_name,
        )
        created_ids.append(private_id)

        listed = {
            portfolio["portfolio_id"]: portfolio
            for portfolio in client.get("/model-portfolios").json()
        }
        assert listed[public_id]["visibility"] == "PUBLIC"
        assert listed[private_id]["visibility"] == "PRIVATE"
    finally:
        for portfolio_id in created_ids:
            _delete_portfolio(
                model_portfolio_repository=model_portfolio_repository,
                model_portfolio_access_repository=model_portfolio_access_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                model_portfolio_update_lock_repository=(
                    model_portfolio_update_lock_repository
                ),
                portfolio_id=portfolio_id,
            )


@pytest.mark.parametrize(
    ("payload", "expected_status_code"),
    [
        (_create_payload(name=""), 422),
        (_create_payload(name="workflow-invalid", positions=[]), 422),
        (
            _create_payload(
                name="workflow-invalid",
                positions=[_position(target_weight=-0.1)],
            ),
            422,
        ),
        (
            _create_payload(
                name="workflow-invalid",
                positions=[_position(target_weight=1.1)],
            ),
            422,
        ),
        (
            _create_payload(
                name="workflow-invalid",
                positions=[_position(symbol="")],
            ),
            422,
        ),
        (
            _create_payload(
                name="workflow-invalid",
                positions=[_position(direction=0)],
            ),
            422,
        ),
        (
            _create_payload(
                name="workflow-invalid",
                positions=[_position(leverage=2)],
            ),
            422,
        ),
        (_create_payload(name="workflow-invalid", visibility="HIDDEN"), 422),
        (
            _create_payload(
                name="workflow-invalid",
                positions=[_position(target_weight=0.4)],
            ),
            422,
        ),
    ],
)
def test_model_portfolio_route_create_rejects_invalid_request_workflow(
    payload: dict[str, Any],
    expected_status_code: int,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    """Reject invalid create requests at the schema or repository boundary."""
    client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.post("/model-portfolios", json=payload)

    assert response.status_code == expected_status_code


def test_model_portfolio_route_get_authorization_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Allow owner/public/shared reads and deny unshared private reads."""
    owner_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    shared_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    public_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-get-public-{uuid4()}",
        visibility="PUBLIC",
    )
    private_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-get-private-{uuid4()}",
        visibility="PRIVATE",
    )

    try:
        owner_response = owner_client.get(f"/model-portfolios/{private_id}")
        assert owner_response.status_code == 200
        assert owner_response.json()["portfolio_owner_display_name"]

        public_response = shared_client.get(f"/model-portfolios/{public_id}")
        assert public_response.status_code == 200
        assert public_response.json()["visibility"] == "PUBLIC"

        denied_response = shared_client.get(f"/model-portfolios/{private_id}")
        assert denied_response.status_code == 403

        model_portfolio_access_repository.add_access_for_user(
            portfolio_id=private_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_email=test_user_2.email_address,
        )
        shared_response = shared_client.get(f"/model-portfolios/{private_id}")
        assert shared_response.status_code == 200
        assert shared_response.json()["visibility"] == "PRIVATE"
    finally:
        for portfolio_id in (public_id, private_id):
            _delete_portfolio(
                model_portfolio_repository=model_portfolio_repository,
                model_portfolio_access_repository=model_portfolio_access_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                model_portfolio_update_lock_repository=(
                    model_portfolio_update_lock_repository
                ),
                portfolio_id=portfolio_id,
            )


def test_model_portfolio_route_update_description_visibility_positions_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    """Update description, visibility, and positions through the route."""
    queue_recorder = QueueRecorder()
    client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        queue_recorder=queue_recorder,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-update-{uuid4()}",
        visibility="PRIVATE",
    )

    try:
        description_response = client.put(
            f"/model-portfolios/{portfolio_id}",
            json=_update_payload(
                description="Route updated description",
                visibility="PRIVATE",
            ),
        )
        assert description_response.status_code == 201
        after_description = client.get(f"/model-portfolios/{portfolio_id}").json()
        assert after_description["description"] == "Route updated description"
        assert len(after_description["position_history"]) == 1
        assert queue_recorder.calls == []

        visibility_response = client.put(
            f"/model-portfolios/{portfolio_id}",
            json=_update_payload(
                description="Route updated description",
                visibility="PUBLIC",
            ),
        )
        assert visibility_response.status_code == 201
        after_visibility = client.get(f"/model-portfolios/{portfolio_id}").json()
        assert after_visibility["visibility"] == "PUBLIC"
        assert len(after_visibility["position_history"]) == 1
        assert queue_recorder.calls == []

        positions_response = client.put(
            f"/model-portfolios/{portfolio_id}",
            json=_update_payload(
                description="Route updated description",
                visibility="PUBLIC",
                positions=[
                    _position(symbol="AAPL", target_weight=0.6),
                    _position(symbol="MSFT", target_weight=0.4),
                ],
            ),
        )
        assert positions_response.status_code == 201
        after_positions = client.get(f"/model-portfolios/{portfolio_id}").json()
        assert len(after_positions["position_history"]) == 2
        assert len(queue_recorder.calls) == 1
        assert queue_recorder.calls[0]["portfolio_id"] == portfolio_id
        assert queue_recorder.calls[0]["portfolio_snapshot_id"] == (
            after_positions["position_history"][-1]["snapshot_id"]
        )
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.parametrize(
    ("payload", "expected_status_code"),
    [
        (_update_payload(positions=[]), 422),
        (_update_payload(positions=[_position(target_weight=-0.1)]), 422),
        (_update_payload(positions=[_position(target_weight=1.1)]), 422),
        (_update_payload(positions=[_position(symbol="")]), 422),
        (_update_payload(positions=[_position(direction=0)]), 422),
        (_update_payload(positions=[_position(leverage=2)]), 422),
        (_update_payload(visibility="HIDDEN"), 422),
        (_update_payload(positions=[_position(target_weight=0.4)]), 422),
    ],
)
def test_model_portfolio_route_update_rejects_invalid_request_workflow(
    payload: dict[str, Any],
    expected_status_code: int,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    """Reject invalid update requests at the schema or repository boundary."""
    client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        queue_recorder=QueueRecorder(),
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-invalid-update-{uuid4()}",
        visibility="PUBLIC",
    )

    try:
        response = client.put(f"/model-portfolios/{portfolio_id}", json=payload)

        assert response.status_code == expected_status_code
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_model_portfolio_route_update_error_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Map non-owner, missing, and too-soon update cases to HTTP errors."""
    owner_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        queue_recorder=QueueRecorder(),
    )
    other_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        queue_recorder=QueueRecorder(),
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-update-errors-{uuid4()}",
        visibility="PUBLIC",
    )
    too_soon_name = f"workflow-too-soon-{uuid4()}"
    too_soon_id: str | None = None

    try:
        non_owner_response = other_client.put(
            f"/model-portfolios/{portfolio_id}",
            json=_update_payload(),
        )
        assert non_owner_response.status_code == 403

        missing_response = owner_client.put(
            f"/model-portfolios/{uuid4()}",
            json=_update_payload(),
        )
        assert missing_response.status_code == 404

        create_response = owner_client.post(
            "/model-portfolios",
            json=_create_payload(name=too_soon_name, visibility="PUBLIC"),
        )
        assert create_response.status_code == 201
        too_soon_id = _find_portfolio_id_by_name(
            client=owner_client,
            portfolio_name=too_soon_name,
        )
        too_soon_response = owner_client.put(
            f"/model-portfolios/{too_soon_id}",
            json=_update_payload(description="Too soon update"),
        )
        assert too_soon_response.status_code == 429
    finally:
        for cleanup_portfolio_id in (portfolio_id, too_soon_id):
            if cleanup_portfolio_id:
                _delete_portfolio(
                    model_portfolio_repository=model_portfolio_repository,
                    model_portfolio_access_repository=model_portfolio_access_repository,
                    model_portfolio_follower_repository=(
                        model_portfolio_follower_repository
                    ),
                    model_portfolio_update_lock_repository=(
                        model_portfolio_update_lock_repository
                    ),
                    portfolio_id=cleanup_portfolio_id,
                )


def test_model_portfolio_route_access_add_list_shared_remove_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Add access by email, list it, read shared-with-me, then remove access."""
    owner_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    shared_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-access-{uuid4()}",
        visibility="PRIVATE",
    )

    try:
        empty_response = owner_client.get(f"/model-portfolios/{portfolio_id}/accesses")
        assert empty_response.status_code == 200
        assert empty_response.json() == []

        add_response = owner_client.post(
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"email_address": test_user_2.email_address},
        )
        assert add_response.status_code == 201

        accesses_response = owner_client.get(
            f"/model-portfolios/{portfolio_id}/accesses"
        )
        assert accesses_response.status_code == 200
        assert {
            "cognito_user_id": test_user_2.cognito_user_id,
            "email_address": test_user_2.email_address,
        } in accesses_response.json()

        shared_response = shared_client.get("/model-portfolios/shared-with-me")
        assert shared_response.status_code == 200
        assert portfolio_id in {
            portfolio["portfolio_id"] for portfolio in shared_response.json()
        }

        shared_get_response = shared_client.get(f"/model-portfolios/{portfolio_id}")
        assert shared_get_response.status_code == 200

        remove_response = owner_client.request(
            "DELETE",
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"cognito_user_id": test_user_2.cognito_user_id},
        )
        assert remove_response.status_code == 200
        assert owner_client.get(f"/model-portfolios/{portfolio_id}/accesses").json() == []

        denied_after_remove = shared_client.get(f"/model-portfolios/{portfolio_id}")
        assert denied_after_remove.status_code == 403
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_model_portfolio_route_access_error_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Cover access management errors for ownership, missing records, and followers."""
    owner_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    other_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-access-errors-{uuid4()}",
        visibility="PRIVATE",
    )

    try:
        non_owner_add = other_client.post(
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"email_address": test_user_1.email_address},
        )
        assert non_owner_add.status_code == 403

        non_owner_get = other_client.get(f"/model-portfolios/{portfolio_id}/accesses")
        assert non_owner_get.status_code == 403

        missing_add = owner_client.post(
            f"/model-portfolios/{uuid4()}/accesses",
            json={"email_address": test_user_2.email_address},
        )
        assert missing_add.status_code == 404

        empty_email = owner_client.post(
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"email_address": ""},
        )
        assert empty_email.status_code == 422

        not_found_remove = owner_client.request(
            "DELETE",
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"cognito_user_id": test_user_2.cognito_user_id},
        )
        assert not_found_remove.status_code == 404

        model_portfolio_access_repository.add_access_for_user(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            shared_with_email=test_user_2.email_address,
        )
        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            alpaca_account_id=test_user_2.alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
        )

        follower_remove = owner_client.request(
            "DELETE",
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"cognito_user_id": test_user_2.cognito_user_id},
        )
        assert follower_remove.status_code == 409
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_model_portfolio_route_public_to_private_follower_access_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Keep follower access when a public portfolio becomes private."""
    owner_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        queue_recorder=QueueRecorder(),
    )
    follower_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-public-private-{uuid4()}",
        visibility="PUBLIC",
        description="Follower visibility workflow",
    )

    try:
        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            alpaca_account_id=test_user_2.alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
        )

        update_response = owner_client.put(
            f"/model-portfolios/{portfolio_id}",
            json=_update_payload(
                description="Follower visibility workflow",
                visibility="PRIVATE",
            ),
        )
        assert update_response.status_code == 201

        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        assert model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )

        follower_response = follower_client.get(f"/model-portfolios/{portfolio_id}")
        assert follower_response.status_code == 200
        response_body = follower_response.json()
        assert response_body["visibility"] == "PRIVATE"
        assert len(response_body["position_history"]) == 1
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )

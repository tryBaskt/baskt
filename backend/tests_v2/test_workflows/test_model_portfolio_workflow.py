from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clients.dynamodb_client import to_dynamodb_value
from core.authentication import get_current_user
from core.deps import (
    get_baskt_account_repository,
    get_model_portfolio_access_repository,
    get_model_portfolio_analytics_service,
    get_model_portfolio_repository,
)
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository import model_portfolio_repository as model_portfolio_repository_module
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from routes import model_portfolio_route
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services import model_portfolio_analytics_service as analytics_service_module
from services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsService,
)


pytestmark = pytest.mark.integration


"""
These workflow tests exercise model_portfolio_route.py through FastAPI's
TestClient while keeping repository dependencies wired to the real tests_v2
integration repositories.

Coverage goals:
- create/list workflow: create public and private model portfolios through the
  route and verify owned metadata is listed with visibility.
- owner list isolation workflow: portfolios created by different owners only
  appear in the authenticated owner's metadata list.
- request validation workflow: assert route/schema-level validation for invalid
  create and update payloads before repository work should happen.
- get authorization workflow: owners and public viewers can fetch a portfolio,
  unshared private viewers are denied, and shared private viewers are allowed.
- detail response workflow: fetched portfolios include mapped owner display
  names, snapshots, timestamps, and latest current weights.
- update workflow: route updates description, visibility, and positions; changed
  positions enqueue one portfolio update message; missing, non-owner, and
  too-soon updates map to the expected HTTP errors.
- no-op update workflow: unchanged description, visibility, and positions return
  successfully without adding a snapshot or queueing a portfolio update.
- access workflow: owners can add access by email, list accesses, see the shared
  portfolio from the recipient account, remove access, and then the recipient is
  denied again.
- shared-with-me workflow: explicit grants appear in the recipient's shared list,
  removed grants disappear, and public-only readable portfolios are not listed.
- access error workflow: non-owners cannot manage accesses, missing portfolios
  return not found, empty access lists return an empty response, nonexistent
  shared users by email and Cognito user id cannot be authenticated, and
  follower users cannot have access removed.
- public-to-private follower workflow: changing a public portfolio with a
  follower to private preserves the follower, grants explicit access to that
  follower, and does not add a new snapshot when positions are unchanged.
- private-to-public access workflow: changing a shared private portfolio to
  public keeps direct reads working even after explicit access is removed.
- analytics workflow: reject blank portfolio ids, deny analytics for users
  without model portfolio access, and return default-period analytics for a
  persisted portfolio with more than seven snapshots and a start time more than
  one year before the deterministic analytics clock, including metric
  verification from the returned cumulative-return series.
- Authentication workflow: token Alpaca-account mismatches and unknown token
  Cognito user ids are rejected by the real Baskt account auth dependency.

Every portfolio, access, follower, and update-lock item created here is cleaned
up in finally blocks.
"""


CREATED_AT = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)


def _put_model_portfolio_at(
    *,
    client: TestClient,
    portfolio_id: str,
    payload: dict[str, Any],
    update_time: datetime,
):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return update_time.replace(tzinfo=None)
            return update_time.astimezone(tz)

    with patch.object(
        model_portfolio_repository_module,
        "datetime",
        FixedDateTime,
    ):
        return client.put(f"/model-portfolios/{portfolio_id}", json=payload)


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


def _claims_with_mismatched_alpaca_account(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": f"tests-v2-wrong-alpaca-{uuid4()}",
    }


def _claims_with_mismatched_cognito_user_id(test_user: Any) -> dict[str, str]:
    return {
        "sub": f"tests-v2-wrong-cognito-{uuid4()}",
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _client_for_user(
    *,
    test_user: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    baskt_account_repository: BasktAccountRepository,
    queue_recorder: QueueRecorder | None = None,
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(model_portfolio_route.router)
    app.dependency_overrides[get_current_user] = lambda: _claims_for_user(test_user)
    app.dependency_overrides[model_portfolio_route.get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[
        model_portfolio_route.get_model_portfolio_access_repository
    ] = lambda: model_portfolio_access_repository
    app.dependency_overrides[model_portfolio_route.get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[get_model_portfolio_access_repository] = (
        lambda: model_portfolio_access_repository
    )
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )

    if model_portfolio_analytics_service is not None:
        app.dependency_overrides[
            model_portfolio_route.get_model_portfolio_analytics_service
        ] = lambda: model_portfolio_analytics_service
        app.dependency_overrides[get_model_portfolio_analytics_service] = (
            lambda: model_portfolio_analytics_service
        )

    if queue_recorder is not None:
        app.dependency_overrides[
            model_portfolio_route.get_trade_execution_queuing_service
        ] = lambda: queue_recorder

    return TestClient(app)


def _client_for_claims(
    *,
    claims: dict[str, str],
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    baskt_account_repository: BasktAccountRepository,
) -> TestClient:
    app = FastAPI()
    app.include_router(model_portfolio_route.router)
    app.dependency_overrides[get_current_user] = lambda: claims
    app.dependency_overrides[model_portfolio_route.get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[
        model_portfolio_route.get_model_portfolio_access_repository
    ] = lambda: model_portfolio_access_repository
    app.dependency_overrides[model_portfolio_route.get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[get_model_portfolio_access_repository] = (
        lambda: model_portfolio_access_repository
    )
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
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
    model_portfolio_repository.dynamodb.delete_item(key={"portfolio_id": portfolio_id})


def _raw_model_position(
    *,
    symbol: str,
    target_weight: float,
    direction: int,
    model_filled_quantity: float,
    model_filled_avg_price: float,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "target_weight": target_weight,
        "direction": direction,
        "leverage": 1.0,
        "model_filled_quantity": model_filled_quantity,
        "model_filled_avg_price": model_filled_avg_price,
    }


def _raw_model_snapshot(
    *,
    timestamp: datetime,
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "snapshot_id": str(uuid4()),
        "timestamp": timestamp.isoformat(),
        "positions": positions,
    }


def _put_raw_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    snapshots: list[dict[str, Any]],
    visibility: str = "PRIVATE",
) -> str:
    portfolio_id = str(uuid4())
    snapshot_timestamps = [
        datetime.fromisoformat(snapshot["timestamp"])
        for snapshot in snapshots
    ]
    created_at = min(snapshot_timestamps) if snapshot_timestamps else CREATED_AT
    updated_at = max(snapshot_timestamps) if snapshot_timestamps else CREATED_AT
    model_portfolio_repository.dynamodb.put_item(
        item=to_dynamodb_value(
            {
                "portfolio_id": portfolio_id,
                "portfolio_owner_cognito_user_id": owner_cognito_user_id,
                "portfolio_name": f"workflow-analytics-{portfolio_id}",
                "position_history": snapshots,
                "created_at": created_at.isoformat(),
                "updated_at": updated_at.isoformat(),
                "description": "Analytics workflow portfolio",
                "visibility": visibility,
            }
        )
    )
    return portfolio_id


def _analytics_history_more_than_one_year() -> list[dict[str, Any]]:
    return [
        _raw_model_snapshot(
            timestamp=datetime(2023, 6, 30, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="AAPL",
                    target_weight=0.55,
                    direction=1,
                    model_filled_quantity=28.0,
                    model_filled_avg_price=190.0,
                ),
                _raw_model_position(
                    symbol="MSFT",
                    target_weight=0.45,
                    direction=-1,
                    model_filled_quantity=10.0,
                    model_filled_avg_price=340.0,
                ),
            ],
        ),
        _raw_model_snapshot(
            timestamp=datetime(2023, 9, 15, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="AAPL",
                    target_weight=0.4,
                    direction=1,
                    model_filled_quantity=22.0,
                    model_filled_avg_price=176.0,
                ),
                _raw_model_position(
                    symbol="GOOG",
                    target_weight=0.6,
                    direction=1,
                    model_filled_quantity=32.0,
                    model_filled_avg_price=138.0,
                ),
            ],
        ),
        _raw_model_snapshot(
            timestamp=datetime(2023, 12, 15, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="MSFT",
                    target_weight=0.5,
                    direction=1,
                    model_filled_quantity=12.0,
                    model_filled_avg_price=370.0,
                ),
                _raw_model_position(
                    symbol="GOOG",
                    target_weight=0.5,
                    direction=-1,
                    model_filled_quantity=35.0,
                    model_filled_avg_price=134.0,
                ),
            ],
        ),
        _raw_model_snapshot(
            timestamp=datetime(2024, 2, 15, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="AAPL",
                    target_weight=0.35,
                    direction=1,
                    model_filled_quantity=18.0,
                    model_filled_avg_price=184.0,
                ),
                _raw_model_position(
                    symbol="MSFT",
                    target_weight=0.65,
                    direction=1,
                    model_filled_quantity=14.0,
                    model_filled_avg_price=406.0,
                ),
            ],
        ),
        _raw_model_snapshot(
            timestamp=datetime(2024, 4, 15, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="AAPL",
                    target_weight=0.5,
                    direction=-1,
                    model_filled_quantity=30.0,
                    model_filled_avg_price=172.0,
                ),
                _raw_model_position(
                    symbol="GOOG",
                    target_weight=0.5,
                    direction=1,
                    model_filled_quantity=28.0,
                    model_filled_avg_price=156.0,
                ),
            ],
        ),
        _raw_model_snapshot(
            timestamp=datetime(2024, 6, 10, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="AAPL",
                    target_weight=0.45,
                    direction=1,
                    model_filled_quantity=20.0,
                    model_filled_avg_price=193.0,
                ),
                _raw_model_position(
                    symbol="GOOG",
                    target_weight=0.55,
                    direction=1,
                    model_filled_quantity=27.0,
                    model_filled_avg_price=176.0,
                ),
            ],
        ),
        _raw_model_snapshot(
            timestamp=datetime(2024, 7, 1, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="MSFT",
                    target_weight=0.4,
                    direction=1,
                    model_filled_quantity=9.0,
                    model_filled_avg_price=456.0,
                ),
                _raw_model_position(
                    symbol="GOOG",
                    target_weight=0.6,
                    direction=-1,
                    model_filled_quantity=31.0,
                    model_filled_avg_price=184.0,
                ),
            ],
        ),
        _raw_model_snapshot(
            timestamp=datetime(2024, 7, 9, 14, tzinfo=timezone.utc),
            positions=[
                _raw_model_position(
                    symbol="AAPL",
                    target_weight=0.25,
                    direction=1,
                    model_filled_quantity=11.0,
                    model_filled_avg_price=226.0,
                ),
                _raw_model_position(
                    symbol="MSFT",
                    target_weight=0.75,
                    direction=1,
                    model_filled_quantity=16.0,
                    model_filled_avg_price=460.0,
                ),
            ],
        ),
    ]


def _assert_analytics_period_metrics(period_response: dict[str, Any]) -> None:
    timestamps = [
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        for timestamp in period_response["timestamp"]
    ]
    cumulative_returns = period_response["cumulative_returns"]

    assert timestamps
    assert cumulative_returns
    assert len(timestamps) == len(cumulative_returns)
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))
    for timestamp in timestamps:
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() == timedelta(0)
    for cumulative_return in cumulative_returns:
        assert isinstance(cumulative_return, float)
        assert math.isfinite(cumulative_return)

    assert period_response["final_cumulative_return"] == pytest.approx(
        cumulative_returns[-1] / 100.0
    )
    equity_curve = [
        1.0 + cumulative_return / 100.0
        for cumulative_return in cumulative_returns
    ]
    running_peak = equity_curve[0]
    drawdowns = []
    for equity_value in equity_curve:
        running_peak = max(running_peak, equity_value)
        drawdowns.append((equity_value / running_peak) - 1.0)
    assert period_response["maximum_drawdown"] == pytest.approx(min(drawdowns))

    for metric_name in [
        "cagr",
        "annualized_volatility",
        "leverage_adjusted_direction",
        "alpha",
        "beta",
        "sharpe_ratio",
        "maximum_drawdown",
        "maximum_drawdown_duration",
    ]:
        metric_value = period_response[metric_name]
        if metric_value is not None:
            assert math.isfinite(metric_value)


def test_model_portfolio_route_rejects_token_alpaca_account_mismatch(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_claims(
        claims=_claims_with_mismatched_alpaca_account(test_user_1),
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.get("/model-portfolios")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user's Alpaca account does not match Baskt account."
    )


def test_model_portfolio_route_rejects_token_cognito_user_mismatch(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    client = _client_for_claims(
        claims=_claims_with_mismatched_cognito_user_id(test_user_1),
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.get("/model-portfolios")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated user does not have a Baskt account."
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


def test_model_portfolio_route_owned_list_is_scoped_to_authenticated_owner_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Only list model portfolio metadata owned by the authenticated user."""
    user_1_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    user_2_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    user_1_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-owner-1-{uuid4()}",
        visibility="PUBLIC",
    )
    user_2_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_2.cognito_user_id,
        portfolio_name=f"workflow-owner-2-{uuid4()}",
        visibility="PUBLIC",
    )

    try:
        user_1_list = {
            portfolio["portfolio_id"]
            for portfolio in user_1_client.get("/model-portfolios").json()
        }
        user_2_list = {
            portfolio["portfolio_id"]
            for portfolio in user_2_client.get("/model-portfolios").json()
        }

        assert user_1_id in user_1_list
        assert user_2_id not in user_1_list
        assert user_2_id in user_2_list
        assert user_1_id not in user_2_list
    finally:
        for portfolio_id in (user_1_id, user_2_id):
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


def test_model_portfolio_route_get_detail_response_and_current_weights_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    """Return mapped portfolio detail fields and latest normalized weights."""
    client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-detail-{uuid4()}",
        visibility="PUBLIC",
        description="Detail response workflow",
        positions=[
            _repository_position(symbol="AAPL", target_weight=0.75),
            _repository_position(symbol="MSFT", target_weight=0.25),
        ],
    )

    try:
        response = client.get(f"/model-portfolios/{portfolio_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["portfolio_id"] == portfolio_id
        assert body["portfolio_owner_cognito_user_id"] == test_user_1.cognito_user_id
        assert body["portfolio_owner_display_name"]
        assert body["portfolio_name"].startswith("workflow-detail-")
        assert body["description"] == "Detail response workflow"
        assert body["visibility"] == "PUBLIC"
        assert body["created_at"] == CREATED_AT.isoformat()
        assert body["updated_at"] == CREATED_AT.isoformat()

        assert len(body["position_history"]) == 1
        snapshot = body["position_history"][0]
        assert snapshot["timestamp"] == CREATED_AT.isoformat()
        assert {position["symbol"] for position in snapshot["positions"]} == {
            "AAPL",
            "MSFT",
        }

        current_weights = body["positions_current_weight"]
        assert set(current_weights) == {"AAPL", "MSFT"}
        assert sum(current_weights.values()) == pytest.approx(1.0)
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_model_portfolio_route_analytics_rejects_blank_portfolio_id_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    test_user_1: Any,
) -> None:
    """Reject analytics requests whose stripped portfolio id is empty."""
    client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        model_portfolio_analytics_service=model_portfolio_analytics_service,
    )

    response = client.get("/model-portfolios/%20%20/analytics")

    assert response.status_code == 400
    assert response.json()["detail"] == "portfolio_id is required."


def test_model_portfolio_route_analytics_denies_user_without_access_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Deny analytics for an unshared private model portfolio."""
    viewer_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        model_portfolio_analytics_service=model_portfolio_analytics_service,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-analytics-denied-{uuid4()}",
        visibility="PRIVATE",
    )

    try:
        response = viewer_client.get(f"/model-portfolios/{portfolio_id}/analytics")

        assert response.status_code == 403
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_model_portfolio_route_analytics_happy_path_metrics_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    test_user_1: Any,
) -> None:
    """Return analytics for a persisted portfolio with more than seven snapshots."""
    client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        model_portfolio_analytics_service=model_portfolio_analytics_service,
    )
    current_datetime = datetime(2024, 7, 10, 15, 30, tzinfo=timezone.utc)
    snapshots = _analytics_history_more_than_one_year()
    portfolio_id = _put_raw_model_portfolio(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        snapshots=snapshots,
        visibility="PRIVATE",
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return current_datetime.replace(tzinfo=None)
            return current_datetime.astimezone(tz)

    try:
        with patch.object(
            analytics_service_module,
            "datetime",
            FixedDateTime,
        ):
            response = client.get(f"/model-portfolios/{portfolio_id}/analytics")

        assert response.status_code == 200
        body = response.json()
        expected_timeframes = {
            "1D": "5Min",
            "1W": "1H",
            "1M": "1D",
            "3M": "1D",
            "1A": "1D",
            "all": "1D",
        }

        assert set(body) == set(expected_timeframes)
        assert len(snapshots) > 7
        assert (
            current_datetime
            - datetime.fromisoformat(snapshots[0]["timestamp"])
        ) > timedelta(days=365)
        for period, expected_timeframe in expected_timeframes.items():
            period_response = body[period]
            assert period_response["timeframe"] == expected_timeframe
            _assert_analytics_period_metrics(period_response)

        first_all_timestamp = datetime.fromisoformat(
            body["all"]["timestamp"][0].replace("Z", "+00:00")
        )
        assert first_all_timestamp == datetime(2023, 6, 30, 14, tzinfo=timezone.utc)
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
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
        description_response = _put_model_portfolio_at(
            client=client,
            portfolio_id=portfolio_id,
            payload=_update_payload(
                description="Route updated description",
                visibility="PRIVATE",
            ),
            update_time=CREATED_AT.replace(minute=2),
        )
        assert description_response.status_code == 201
        after_description = client.get(f"/model-portfolios/{portfolio_id}").json()
        assert after_description["description"] == "Route updated description"
        assert len(after_description["position_history"]) == 1
        assert queue_recorder.calls == []

        visibility_response = _put_model_portfolio_at(
            client=client,
            portfolio_id=portfolio_id,
            payload=_update_payload(
                description="Route updated description",
                visibility="PUBLIC",
            ),
            update_time=CREATED_AT.replace(minute=4),
        )
        assert visibility_response.status_code == 201
        after_visibility = client.get(f"/model-portfolios/{portfolio_id}").json()
        assert after_visibility["visibility"] == "PUBLIC"
        assert len(after_visibility["position_history"]) == 1
        assert queue_recorder.calls == []

        positions_response = _put_model_portfolio_at(
            client=client,
            portfolio_id=portfolio_id,
            payload=_update_payload(
                description="Route updated description",
                visibility="PUBLIC",
                positions=[
                    _position(symbol="AAPL", target_weight=0.6),
                    _position(symbol="MSFT", target_weight=0.4),
                ],
            ),
            update_time=CREATED_AT.replace(minute=6),
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


def test_model_portfolio_route_no_op_update_does_not_snapshot_or_queue_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    """Return successfully for unchanged updates without side effects."""
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
        portfolio_name=f"workflow-no-op-{uuid4()}",
        visibility="PRIVATE",
        description="No-op route portfolio",
    )

    try:
        before = client.get(f"/model-portfolios/{portfolio_id}").json()
        response = client.put(
            f"/model-portfolios/{portfolio_id}",
            json=_update_payload(
                description="No-op route portfolio",
                visibility="PRIVATE",
            ),
        )
        after = client.get(f"/model-portfolios/{portfolio_id}").json()

        assert response.status_code == 201
        assert after["updated_at"] == before["updated_at"]
        assert after["position_history"] == before["position_history"]
        assert queue_recorder.calls == []
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
        assert (
            owner_client.get(f"/model-portfolios/{portfolio_id}/accesses").json() == []
        )
        shared_after_remove = shared_client.get("/model-portfolios/shared-with-me")
        assert shared_after_remove.status_code == 200
        assert portfolio_id not in {
            portfolio["portfolio_id"] for portfolio in shared_after_remove.json()
        }

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


def test_model_portfolio_route_shared_with_me_excludes_public_only_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Do not list public-only portfolios as explicitly shared with the viewer."""
    public_client = _client_for_user(
        test_user=test_user_2,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-public-only-{uuid4()}",
        visibility="PUBLIC",
    )

    try:
        direct_response = public_client.get(f"/model-portfolios/{portfolio_id}")
        shared_response = public_client.get("/model-portfolios/shared-with-me")

        assert direct_response.status_code == 200
        assert shared_response.status_code == 200
        assert portfolio_id not in {
            portfolio["portfolio_id"] for portfolio in shared_response.json()
        }
    finally:
        _delete_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_model_portfolio_route_access_email_whitespace_normalization_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Trim access email input and persist the authenticated email address."""
    owner_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
    )
    portfolio_id = _create_portfolio_direct(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=test_user_1.cognito_user_id,
        portfolio_name=f"workflow-access-email-{uuid4()}",
        visibility="PRIVATE",
    )

    try:
        add_response = owner_client.post(
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"email_address": f"  {test_user_2.email_address}  "},
        )
        accesses_response = owner_client.get(
            f"/model-portfolios/{portfolio_id}/accesses"
        )

        assert add_response.status_code == 201
        assert accesses_response.status_code == 200
        assert {
            "cognito_user_id": test_user_2.cognito_user_id,
            "email_address": test_user_2.email_address,
        } in accesses_response.json()
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

        missing_email_user = owner_client.post(
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"email_address": f"missing-{uuid4()}@example.invalid"},
        )
        assert missing_email_user.status_code == 403

        missing_cognito_user = owner_client.request(
            "DELETE",
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"cognito_user_id": str(uuid4())},
        )
        assert missing_cognito_user.status_code == 403

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


def test_model_portfolio_route_private_to_public_keeps_read_after_access_removed_workflow(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Allow shared readers to continue reading after private portfolio becomes public."""
    owner_client = _client_for_user(
        test_user=test_user_1,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        baskt_account_repository=baskt_account_repository,
        queue_recorder=QueueRecorder(),
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
        portfolio_name=f"workflow-private-public-{uuid4()}",
        visibility="PRIVATE",
        description="Private to public workflow",
    )

    try:
        add_response = owner_client.post(
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"email_address": test_user_2.email_address},
        )
        assert add_response.status_code == 201
        assert shared_client.get(f"/model-portfolios/{portfolio_id}").status_code == 200

        update_response = _put_model_portfolio_at(
            client=owner_client,
            portfolio_id=portfolio_id,
            payload=_update_payload(
                description="Private to public workflow",
                visibility="PUBLIC",
            ),
            update_time=CREATED_AT.replace(minute=2),
        )
        assert update_response.status_code == 201

        remove_response = owner_client.request(
            "DELETE",
            f"/model-portfolios/{portfolio_id}/accesses",
            json={"cognito_user_id": test_user_2.cognito_user_id},
        )
        assert remove_response.status_code == 200

        shared_after_remove = shared_client.get("/model-portfolios/shared-with-me")
        direct_after_remove = shared_client.get(f"/model-portfolios/{portfolio_id}")

        assert shared_after_remove.status_code == 200
        assert portfolio_id not in {
            portfolio["portfolio_id"] for portfolio in shared_after_remove.json()
        }
        assert direct_after_remove.status_code == 200
        assert direct_after_remove.json()["visibility"] == "PUBLIC"
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

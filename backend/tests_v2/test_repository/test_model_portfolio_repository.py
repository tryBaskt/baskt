from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from clients.dynamodb_client import to_dynamodb_value
from domain.model_portfolio_domain import ModelPortfolioPosition, ModelPortfolioSnapshot
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import (
    ModelPortfolioBadGatewayError,
    ModelPortfolioInvalidPositionRequest,
    ModelPortfolioLockedError,
    ModelPortfolioNotFoundError,
    ModelPortfolioRepository,
    ModelPortfolioTooManyRequestsError,
    ModelPortfolioUnprocessableEntityError,
)
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from schema.model_portfolio_schema import ModelPortfolioPositionRequest


"""
These tests exercise the non-mocked ModelPortfolioRepository create and update
paths against the configured test DynamoDB table and Alpaca market-data client.

Coverage goals:
- create_model_portfolio(): create public and private portfolios successfully,
  including long and short positions, with explicit creation timestamps.
- create_model_portfolio() validation: reject empty position lists, target
  weights below 1, target weights above 1, empty symbols, invalid direction,
  invalid leverage, and repository-level invalid target weights with
  ModelPortfolioInvalidPositionRequest.
- create_model_portfolio() Alpaca failure: pass a syntactically valid but
  nonexistent stock symbol so AlpacaBrokerClientError is translated into
  ModelPortfolioBadGatewayError.
- update_model_portfolio(): update description, visibility, and positions with
  explicit update timestamps, verifying description/visibility updates keep one
  snapshot and position updates append a new snapshot.
- update_model_portfolio() validation: reject the same invalid position request
  shapes as create_model_portfolio() before any portfolio write happens.
- update_model_portfolio() Alpaca failure: update an existing portfolio with a
  nonexistent stock symbol and assert ModelPortfolioBadGatewayError.
- update_model_portfolio() state behavior: reject updates inside the one-minute
  cooldown, return no-op for unchanged inputs, raise ModelPortfolioNotFoundError
  for missing portfolios, and raise ModelPortfolioLockedError while the
  portfolio update lock is held.
- private visibility sync: create a public portfolio, add a follower, update it
  to private, verify the follower record remains, verify the follower receives
  access, and verify snapshots stay at one.
- get_portfolio_cognito_owner_id_by_portfolio(): read an existing owner ID and
  raise ModelPortfolioNotFoundError for a missing portfolio.
- get_position_history(): read one and multiple parsed snapshots, raise
  ModelPortfolioNotFoundError for missing portfolios, raise
  ModelPortfolioUnprocessableEntityError for missing or malformed history, and
  verify the read waits for an active update lock to be released.
- get_n_last_model_portfolio_snapshots(): read the latest one and latest two
  snapshots, raise ValueError for invalid n values, raise
  ModelPortfolioNotFoundError for missing portfolios, and raise
  ModelPortfolioUnprocessableEntityError for malformed history.
- get_model_portfolio(): read a complete portfolio, verify missing visibility
  defaults to PRIVATE, raise ModelPortfolioNotFoundError for missing
  portfolios, raise ModelPortfolioUnprocessableEntityError for malformed items,
  and raise ModelPortfolioLockedError when a no-wait locked read times out.
- get_model_portfolio_metadata_by_owner(): cover no portfolios, one portfolio,
  multiple portfolios, default visibility, and malformed owner metadata rows.
- get_model_portfolio_metadata_by_portfolio_id(): cover success, missing
  portfolio, default visibility, and malformed metadata rows.
- calculate_positions_current_weight(): calculate expected current weights from
  today's latest prices for manual long-only, short-only, and mixed long/short
  snapshots, then create a model portfolio and calculate expected current
  weights from its stored snapshot.

Every test deletes model portfolio, follower, access, and lock records it
creates in finally blocks so the shared integration tables are left clean.
"""


CREATED_AT = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
UPDATE_AFTER_COOLDOWN = CREATED_AT + timedelta(minutes=2)
UPDATE_WITHIN_COOLDOWN = CREATED_AT + timedelta(seconds=30)
BAD_STOCK_SYMBOL = f"ZZZNOTREAL{uuid4().hex[:8].upper()}"


def _long_position(
    *,
    symbol: str = "AAPL",
    target_weight: float = 1.0,
) -> ModelPortfolioPositionRequest:
    return ModelPortfolioPositionRequest(
        symbol=symbol,
        target_weight=target_weight,
        direction=1,
        leverage=1,
    )


def _short_position(
    *,
    symbol: str = "MSFT",
    target_weight: float = 1.0,
) -> ModelPortfolioPositionRequest:
    return ModelPortfolioPositionRequest(
        symbol=symbol,
        target_weight=target_weight,
        direction=-1,
        leverage=1,
    )


def _position(
    *,
    symbol: object = "AAPL",
    target_weight: object = 1.0,
    direction: object = 1,
    leverage: object = 1.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        target_weight=target_weight,
        direction=direction,
        leverage=leverage,
    )


def _two_positions() -> list[ModelPortfolioPositionRequest]:
    return [
        _long_position(symbol="AAPL", target_weight=0.6),
        _long_position(symbol="MSFT", target_weight=0.4),
    ]


def _expected_current_weights(
    *,
    snapshot: ModelPortfolioSnapshot,
    quotes: dict[str, float],
) -> tuple[dict[str, float], float]:
    position_values = {}
    for position in snapshot.positions:
        current_price = quotes[position.symbol]
        position_values[position.symbol] = position.model_filled_quantity * (
            position.model_filled_avg_price
            + position.direction * (current_price - position.model_filled_avg_price)
        )

    total_value = sum(position_values.values())
    if total_value == 0:
        return {symbol: 0.0 for symbol in position_values}, 0.0
    return {
        symbol: value / total_value
        for symbol, value in position_values.items()
    }, total_value


def _delete_model_portfolio(
    model_portfolio_repository: ModelPortfolioRepository,
    *,
    portfolio_id: str | None,
) -> None:
    if portfolio_id:
        model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )


def _delete_access(
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    *,
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
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    *,
    portfolio_id: str,
    cognito_user_id: str,
) -> None:
    model_portfolio_follower_repository.dynamodb.delete_item(
        key={
            "cognito_user_id": cognito_user_id,
            "portfolio_id": portfolio_id,
        }
    )


def _delete_lock(
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    *,
    portfolio_id: str,
) -> None:
    model_portfolio_update_lock_repository.lock_table_client.delete_item(
        key={"portfolio_id": portfolio_id}
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


def _put_raw_model_portfolio_item(
    model_portfolio_repository: ModelPortfolioRepository,
    item: dict,
) -> None:
    model_portfolio_repository.dynamodb.put_item(item=to_dynamodb_value(item))


def _raw_position(
    *,
    symbol: str = "AAPL",
    target_weight: float = 1.0,
    direction: int = 1,
    leverage: float = 1.0,
    model_filled_quantity: float = 10.0,
    model_filled_avg_price: float = 100.0,
) -> dict:
    return {
        "symbol": symbol,
        "target_weight": target_weight,
        "direction": direction,
        "leverage": leverage,
        "model_filled_quantity": model_filled_quantity,
        "model_filled_avg_price": model_filled_avg_price,
    }


def _raw_snapshot(
    *,
    snapshot_id: str | None = None,
    timestamp: datetime = CREATED_AT,
    positions: list[dict] | None = None,
) -> dict:
    return {
        "snapshot_id": snapshot_id or str(uuid4()),
        "timestamp": timestamp.isoformat(),
        "positions": positions or [_raw_position()],
    }


def _raw_portfolio_item(
    *,
    portfolio_id: str,
    owner_id: str,
    portfolio_name: str = "Tests V2 Raw Portfolio",
    created_at: datetime = CREATED_AT,
    updated_at: datetime = CREATED_AT,
    position_history: list[dict] | None = None,
    description: str | None = "raw portfolio",
    visibility: str | None = "PUBLIC",
) -> dict:
    item = {
        "portfolio_id": portfolio_id,
        "portfolio_owner_cognito_user_id": owner_id,
        "portfolio_name": portfolio_name,
        "position_history": position_history or [_raw_snapshot()],
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "description": description,
    }
    if visibility is not None:
        item["visibility"] = visibility
    return item


def _create_portfolio(
    model_portfolio_repository: ModelPortfolioRepository,
    *,
    owner_id: str,
    positions: list[ModelPortfolioPositionRequest] | None = None,
    visibility: str = "PUBLIC",
    description: str = "tests-v2 model portfolio",
    creation_time: datetime = CREATED_AT,
) -> str:
    return model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=owner_id,
        portfolio_name=f"Tests V2 Model Portfolio {uuid4()}",
        positions_request=positions or [_long_position()],
        visibility=visibility,
        creation_time=creation_time,
        description=description,
    )


@pytest.mark.integration
def test_model_portfolio_repository_create_model_portfolio_success(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Create a public model portfolio and verify its stored fields."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=_two_positions(),
            visibility="PUBLIC",
            description="created successfully",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )

        assert portfolio.portfolio_id == portfolio_id
        assert portfolio.portfolio_owner_cognito_user_id == (
            test_user_1.cognito_user_id
        )
        assert portfolio.visibility == "PUBLIC"
        assert portfolio.description == "created successfully"
        assert portfolio.created_at == CREATED_AT
        assert portfolio.updated_at == CREATED_AT
        assert len(portfolio.position_history) == 1
        assert len(portfolio.position_history[0].positions) == 2
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_create_model_portfolio_short_position_success(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Create a private model portfolio with a valid short position."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_short_position()],
            visibility="PRIVATE",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )

        assert portfolio.visibility == "PRIVATE"
        assert portfolio.position_history[0].positions[0].direction == -1
        assert len(portfolio.position_history) == 1
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "positions_request",
    [
        [],
        [_position(target_weight=-0.1)],
        [_position(target_weight=0.99)],
        [_position(target_weight=1.01)],
        [_position(symbol="")],
        [_position(direction=0)],
        [_position(leverage=2.0)],
        [_position(target_weight=object())],
    ],
)
def test_model_portfolio_repository_create_invalid_positions_raise_invalid_position_request(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
    positions_request,
) -> None:
    """Reject invalid create position requests before creating a portfolio."""
    with pytest.raises(ModelPortfolioInvalidPositionRequest):
        model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            portfolio_name=f"Invalid Create Portfolio {uuid4()}",
            positions_request=positions_request,
            visibility="PUBLIC",
            creation_time=CREATED_AT,
            description="invalid create",
        )


@pytest.mark.integration
def test_model_portfolio_repository_create_bad_stock_raises_bad_gateway(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Translate Alpaca latest-price failure during create into bad gateway."""
    with pytest.raises(ModelPortfolioBadGatewayError):
        model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
            portfolio_name=f"Bad Stock Create Portfolio {uuid4()}",
            positions_request=[_long_position(symbol=BAD_STOCK_SYMBOL)],
            visibility="PUBLIC",
            creation_time=CREATED_AT,
            description="bad stock create",
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_model_portfolio_success(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Update description after cooldown and verify snapshots stay at one."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="before update",
        )
        updated, snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_long_position()],
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="after update",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )

        assert updated is True
        assert snapshot_id is None
        assert portfolio.description == "after update"
        assert portfolio.updated_at == UPDATE_AFTER_COOLDOWN
        assert len(portfolio.position_history) == 1
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "positions_request",
    [
        [],
        [_position(target_weight=-0.1)],
        [_position(target_weight=0.99)],
        [_position(target_weight=1.01)],
        [_position(symbol="")],
        [_position(direction=0)],
        [_position(leverage=2.0)],
        [_position(target_weight=object())],
    ],
)
def test_model_portfolio_repository_update_invalid_positions_raise_invalid_position_request(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
    positions_request,
) -> None:
    """Reject invalid update position requests before loading a portfolio."""
    with pytest.raises(ModelPortfolioInvalidPositionRequest):
        model_portfolio_repository.update_model_portfolio(
            portfolio_id=f"missing-invalid-update-{uuid4()}",
            positions_request=positions_request,
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="invalid update",
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_bad_stock_raises_bad_gateway(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Translate Alpaca latest-price failure during update into bad gateway."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="before bad stock update",
        )

        with pytest.raises(ModelPortfolioBadGatewayError):
            model_portfolio_repository.update_model_portfolio(
                portfolio_id=portfolio_id,
                positions_request=[_long_position(symbol=BAD_STOCK_SYMBOL)],
                visibility="PUBLIC",
                update_time=UPDATE_AFTER_COOLDOWN,
                description="bad stock update",
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_within_cooldown_raises_too_many_requests(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Reject an update that changes data within one minute of creation."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="cooldown before",
        )

        with pytest.raises(ModelPortfolioTooManyRequestsError):
            model_portfolio_repository.update_model_portfolio(
                portfolio_id=portfolio_id,
                positions_request=[_long_position()],
                visibility="PUBLIC",
                update_time=UPDATE_WITHIN_COOLDOWN,
                description="cooldown after",
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_description_only_keeps_one_snapshot(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Update only description and verify no snapshot is appended."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="old description",
        )
        updated, snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_long_position()],
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="new description",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )

        assert updated is True
        assert snapshot_id is None
        assert portfolio.description == "new description"
        assert len(portfolio.position_history) == 1
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_public_to_private_preserves_follower_access(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    test_user_1,
    test_user_2,
) -> None:
    """Make a public followed portfolio private and grant follower access."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="public portfolio",
        )
        model_portfolio_follower_repository.put_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            alpaca_account_id=test_user_2.alpaca_account_id,
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=test_user_1.cognito_user_id,
        )

        updated, snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_long_position()],
            visibility="PRIVATE",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="public portfolio",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )

        assert updated is True
        assert snapshot_id is None
        assert portfolio.visibility == "PRIVATE"
        assert len(portfolio.position_history) == 1
        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=test_user_2.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        assert model_portfolio_access_repository.has_access(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=test_user_2.cognito_user_id,
        )
    finally:
        if portfolio_id:
            _delete_access(
                model_portfolio_access_repository,
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=test_user_2.cognito_user_id,
            )
            _delete_follower(
                model_portfolio_follower_repository,
                portfolio_id=portfolio_id,
                cognito_user_id=test_user_2.cognito_user_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_positions_appends_snapshot(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Update positions after cooldown and verify a snapshot is appended."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="before position update",
        )
        updated, snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_short_position()],
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="before position update",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )

        assert updated is True
        assert snapshot_id is not None
        assert len(portfolio.position_history) == 2
        assert portfolio.position_history[-1].snapshot_id == snapshot_id
        assert portfolio.position_history[-1].positions[0].direction == -1
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_visibility_only_keeps_one_snapshot(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Update only visibility and verify no snapshot is appended."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PRIVATE",
            description="visibility only",
        )
        updated, snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_long_position()],
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="visibility only",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )

        assert updated is True
        assert snapshot_id is None
        assert portfolio.visibility == "PUBLIC"
        assert len(portfolio.position_history) == 1
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_noop_returns_false(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Return no-op when positions, description, and visibility are unchanged."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="no-op",
        )
        updated, snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_long_position()],
            visibility="PUBLIC",
            update_time=UPDATE_WITHIN_COOLDOWN,
            description="no-op",
        )

        assert updated is False
        assert snapshot_id is None
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_missing_portfolio_raises_not_found(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    """Raise not found when updating a portfolio ID that does not exist."""
    with pytest.raises(ModelPortfolioNotFoundError):
        model_portfolio_repository.update_model_portfolio(
            portfolio_id=f"tests-v2-missing-portfolio-{uuid4()}",
            positions_request=[_long_position()],
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="missing",
        )


@pytest.mark.integration
def test_model_portfolio_repository_update_locked_portfolio_raises_locked(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1,
) -> None:
    """Raise locked when updating while a portfolio update lock is active."""
    portfolio_id = None
    owner_token = str(uuid4())
    lock_acquired = False

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
            visibility="PUBLIC",
            description="locked before",
        )
        lock_acquired = model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        assert lock_acquired

        with pytest.raises(ModelPortfolioLockedError):
            model_portfolio_repository.update_model_portfolio(
                portfolio_id=portfolio_id,
                positions_request=[_long_position()],
                visibility="PUBLIC",
                update_time=UPDATE_AFTER_COOLDOWN,
                description="locked after",
            )
    finally:
        if portfolio_id and lock_acquired:
            model_portfolio_update_lock_repository.release_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )
            _delete_lock(
                model_portfolio_update_lock_repository,
                portfolio_id=portfolio_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_get_owner_id_success_and_missing(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Read a portfolio owner ID and raise not found for a missing portfolio."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
        )

        assert model_portfolio_repository.get_portfolio_cognito_owner_id_by_portfolio(
            portfolio_id=portfolio_id
        ) == test_user_1.cognito_user_id
        with pytest.raises(ModelPortfolioNotFoundError):
            model_portfolio_repository.get_portfolio_cognito_owner_id_by_portfolio(
                portfolio_id=f"tests-v2-owner-missing-{uuid4()}"
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_get_position_history_success_missing_and_malformed(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Read position history and reject missing or malformed history data."""
    portfolio_id = None
    missing_history_portfolio_id = f"tests-v2-missing-history-{uuid4()}"
    malformed_history_portfolio_id = f"tests-v2-malformed-history-{uuid4()}"

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=_two_positions(),
        )
        history = model_portfolio_repository.get_position_history(
            portfolio_id=portfolio_id
        )
        assert len(history) == 1
        assert history[0].timestamp == CREATED_AT
        assert {position.symbol for position in history[0].positions} == {
            "AAPL",
            "MSFT",
        }

        _, new_snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_short_position()],
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="tests-v2 model portfolio",
        )
        updated_history = model_portfolio_repository.get_position_history(
            portfolio_id=portfolio_id
        )
        assert len(updated_history) == 2
        assert updated_history[-1].snapshot_id == new_snapshot_id

        with pytest.raises(ModelPortfolioNotFoundError):
            model_portfolio_repository.get_position_history(
                portfolio_id=f"tests-v2-history-missing-{uuid4()}"
            )

        missing_history_item = _raw_portfolio_item(
            portfolio_id=missing_history_portfolio_id,
            owner_id=test_user_1.cognito_user_id,
        )
        missing_history_item.pop("position_history")
        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            missing_history_item,
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_position_history(
                portfolio_id=missing_history_portfolio_id
            )

        malformed_history_item = _raw_portfolio_item(
            portfolio_id=malformed_history_portfolio_id,
            owner_id=test_user_1.cognito_user_id,
            position_history=[{"snapshot_id": str(uuid4())}],
        )
        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            malformed_history_item,
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_position_history(
                portfolio_id=malformed_history_portfolio_id
            )
    finally:
        for cleanup_portfolio_id in (
            portfolio_id,
            missing_history_portfolio_id,
            malformed_history_portfolio_id,
        ):
            _delete_model_portfolio(
                model_portfolio_repository,
                portfolio_id=cleanup_portfolio_id,
            )


@pytest.mark.integration
def test_model_portfolio_repository_get_position_history_waits_for_lock_release(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1,
) -> None:
    """Wait for an active update lock before reading position history."""
    portfolio_id = None
    owner_token = str(uuid4())
    lock_acquired = False

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
        )
        lock_acquired = model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        assert lock_acquired
        timer = _release_lock_later(
            model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            delay_seconds=0.5,
        )
        started_at = time.monotonic()
        history = model_portfolio_repository.get_position_history(
            portfolio_id=portfolio_id
        )
        assert time.monotonic() - started_at >= 0.4
        assert len(history) == 1
        timer.join(timeout=2)
        lock_acquired = False
    finally:
        if portfolio_id and lock_acquired:
            model_portfolio_update_lock_repository.release_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )
            _delete_lock(
                model_portfolio_update_lock_repository,
                portfolio_id=portfolio_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_get_n_last_snapshots_success_and_boundaries(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Read latest snapshots and raise for invalid n values."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[_long_position()],
        )
        _, latest_snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[_short_position()],
            visibility="PUBLIC",
            update_time=UPDATE_AFTER_COOLDOWN,
            description="tests-v2 model portfolio",
        )

        latest_snapshot = (
            model_portfolio_repository.get_n_last_model_portfolio_snapshots(
                portfolio_id=portfolio_id,
                n=1,
            )
        )
        assert len(latest_snapshot) == 1
        assert latest_snapshot[0].snapshot_id == latest_snapshot_id

        latest_two_snapshots = (
            model_portfolio_repository.get_n_last_model_portfolio_snapshots(
                portfolio_id=portfolio_id,
                n=2,
            )
        )
        assert len(latest_two_snapshots) == 2
        assert latest_two_snapshots[0].timestamp == CREATED_AT
        assert latest_two_snapshots[1].timestamp == UPDATE_AFTER_COOLDOWN

        for invalid_n in (0, -1, 3):
            with pytest.raises(ValueError):
                model_portfolio_repository.get_n_last_model_portfolio_snapshots(
                    portfolio_id=portfolio_id,
                    n=invalid_n,
                )

        with pytest.raises(ModelPortfolioNotFoundError):
            model_portfolio_repository.get_n_last_model_portfolio_snapshots(
                portfolio_id=f"tests-v2-n-last-missing-{uuid4()}",
                n=1,
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_get_n_last_snapshots_malformed_history(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Raise unprocessable when n-last snapshots parses malformed history."""
    portfolio_id = f"tests-v2-n-last-malformed-{uuid4()}"

    try:
        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            _raw_portfolio_item(
                portfolio_id=portfolio_id,
                owner_id=test_user_1.cognito_user_id,
                position_history=[{"timestamp": CREATED_AT.isoformat()}],
            ),
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_n_last_model_portfolio_snapshots(
                portfolio_id=portfolio_id,
                n=1,
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_get_model_portfolio_success_defaults_and_errors(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Read full portfolios, default visibility, and reject malformed items."""
    portfolio_id = None
    default_visibility_portfolio_id = f"tests-v2-default-visibility-{uuid4()}"
    malformed_portfolio_id = f"tests-v2-malformed-full-{uuid4()}"

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=_two_positions(),
            visibility="PUBLIC",
            description="get full portfolio",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )
        assert portfolio.portfolio_id == portfolio_id
        assert portfolio.visibility == "PUBLIC"
        assert portfolio.description == "get full portfolio"
        assert len(portfolio.position_history) == 1

        default_visibility_item = _raw_portfolio_item(
            portfolio_id=default_visibility_portfolio_id,
            owner_id=test_user_1.cognito_user_id,
            visibility=None,
        )
        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            default_visibility_item,
        )
        assert model_portfolio_repository.get_model_portfolio(
            portfolio_id=default_visibility_portfolio_id
        ).visibility == "PRIVATE"

        with pytest.raises(ModelPortfolioNotFoundError):
            model_portfolio_repository.get_model_portfolio(
                portfolio_id=f"tests-v2-full-missing-{uuid4()}"
            )

        malformed_item = _raw_portfolio_item(
            portfolio_id=malformed_portfolio_id,
            owner_id=test_user_1.cognito_user_id,
        )
        malformed_item.pop("portfolio_name")
        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            malformed_item,
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_model_portfolio(
                portfolio_id=malformed_portfolio_id
            )
    finally:
        for cleanup_portfolio_id in (
            portfolio_id,
            default_visibility_portfolio_id,
            malformed_portfolio_id,
        ):
            _delete_model_portfolio(
                model_portfolio_repository,
                portfolio_id=cleanup_portfolio_id,
            )


@pytest.mark.integration
def test_model_portfolio_repository_get_model_portfolio_locked_read_times_out(
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1,
) -> None:
    """Raise locked when get_model_portfolio is called with no wait."""
    portfolio_id = None
    owner_token = str(uuid4())
    lock_acquired = False

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
        )
        lock_acquired = model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=owner_token,
            lease_seconds=30,
        )
        assert lock_acquired
        with pytest.raises(ModelPortfolioLockedError):
            model_portfolio_repository.get_model_portfolio(
                portfolio_id=portfolio_id,
                wait_seconds=0,
            )
    finally:
        if portfolio_id and lock_acquired:
            model_portfolio_update_lock_repository.release_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )
            _delete_lock(
                model_portfolio_update_lock_repository,
                portfolio_id=portfolio_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.integration
def test_model_portfolio_repository_get_metadata_by_owner_scenarios(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Read owner metadata for none, one, multiple, default, and malformed rows."""
    first_portfolio_id = None
    second_portfolio_id = None
    default_visibility_portfolio_id = f"tests-v2-owner-default-{uuid4()}"
    malformed_portfolio_id = f"tests-v2-owner-malformed-{uuid4()}"
    missing_owner_id = f"tests-v2-owner-none-{uuid4()}"
    malformed_owner_id = f"tests-v2-owner-malformed-{uuid4()}"

    try:
        assert (
            model_portfolio_repository.get_model_portfolio_metadata_by_owner(
                portfolio_owner_cognito_user_id=missing_owner_id
            )
            == []
        )

        first_portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            visibility="PUBLIC",
            description="owner first",
        )
        second_portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            visibility="PRIVATE",
            description="owner second",
        )
        owner_metadata = (
            model_portfolio_repository.get_model_portfolio_metadata_by_owner(
                portfolio_owner_cognito_user_id=test_user_1.cognito_user_id
            )
        )
        assert {first_portfolio_id, second_portfolio_id} <= {
            metadata["portfolio_id"]
            for metadata in owner_metadata
        }

        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            _raw_portfolio_item(
                portfolio_id=default_visibility_portfolio_id,
                owner_id=test_user_1.cognito_user_id,
                visibility=None,
            ),
        )
        owner_metadata_with_default = (
            model_portfolio_repository.get_model_portfolio_metadata_by_owner(
                portfolio_owner_cognito_user_id=test_user_1.cognito_user_id
            )
        )
        assert any(
            metadata["portfolio_id"] == default_visibility_portfolio_id
            and metadata["visibility"] == "PRIVATE"
            for metadata in owner_metadata_with_default
        )

        malformed_item = _raw_portfolio_item(
            portfolio_id=malformed_portfolio_id,
            owner_id=malformed_owner_id,
        )
        malformed_item.pop("portfolio_name")
        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            malformed_item,
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_model_portfolio_metadata_by_owner(
                portfolio_owner_cognito_user_id=malformed_owner_id
            )
    finally:
        for cleanup_portfolio_id in (
            first_portfolio_id,
            second_portfolio_id,
            default_visibility_portfolio_id,
            malformed_portfolio_id,
        ):
            _delete_model_portfolio(
                model_portfolio_repository,
                portfolio_id=cleanup_portfolio_id,
            )


@pytest.mark.integration
def test_model_portfolio_repository_get_metadata_by_portfolio_id_scenarios(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Read metadata by portfolio ID and cover missing/default/malformed cases."""
    portfolio_id = None
    default_visibility_portfolio_id = f"tests-v2-portfolio-default-{uuid4()}"
    malformed_portfolio_id = f"tests-v2-portfolio-malformed-{uuid4()}"

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            visibility="PUBLIC",
            description="metadata by id",
        )
        metadata = model_portfolio_repository.get_model_portfolio_metadata_by_portfolio_id(
            portfolio_id=portfolio_id
        )
        assert metadata["portfolio_id"] == portfolio_id
        assert metadata["portfolio_owner_cognito_user_id"] == (
            test_user_1.cognito_user_id
        )
        assert metadata["description"] == "metadata by id"
        assert metadata["visibility"] == "PUBLIC"

        with pytest.raises(ModelPortfolioNotFoundError):
            model_portfolio_repository.get_model_portfolio_metadata_by_portfolio_id(
                portfolio_id=f"tests-v2-metadata-id-missing-{uuid4()}"
            )

        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            _raw_portfolio_item(
                portfolio_id=default_visibility_portfolio_id,
                owner_id=test_user_1.cognito_user_id,
                visibility=None,
            ),
        )
        assert model_portfolio_repository.get_model_portfolio_metadata_by_portfolio_id(
            portfolio_id=default_visibility_portfolio_id
        )["visibility"] == "PRIVATE"

        malformed_item = _raw_portfolio_item(
            portfolio_id=malformed_portfolio_id,
            owner_id=test_user_1.cognito_user_id,
        )
        malformed_item.pop("portfolio_name")
        _put_raw_model_portfolio_item(
            model_portfolio_repository,
            malformed_item,
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_model_portfolio_metadata_by_portfolio_id(
                portfolio_id=malformed_portfolio_id
            )
    finally:
        for cleanup_portfolio_id in (
            portfolio_id,
            default_visibility_portfolio_id,
            malformed_portfolio_id,
        ):
            _delete_model_portfolio(
                model_portfolio_repository,
                portfolio_id=cleanup_portfolio_id,
            )


@pytest.mark.integration
def test_model_portfolio_repository_calculate_current_weight_for_manual_long_short_snapshot(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    """Calculate expected current weights for manual long and short positions."""
    snapshot = ModelPortfolioSnapshot(
        positions=[
            ModelPortfolioPosition(
                symbol="AAPL",
                target_weight=0.6,
                direction=1,
                leverage=1.0,
                model_filled_quantity=60.0,
                model_filled_avg_price=150.0,
            ),
            ModelPortfolioPosition(
                symbol="MSFT",
                target_weight=0.4,
                direction=-1,
                leverage=1.0,
                model_filled_quantity=40.0,
                model_filled_avg_price=300.0,
            ),
        ],
        timestamp=CREATED_AT,
        snapshot_id=str(uuid4()),
    )

    actual_weights, actual_total_value, quotes = (
        model_portfolio_repository.calculate_positions_current_weight(snapshot)
    )
    expected_weights, expected_total_value = _expected_current_weights(
        snapshot=snapshot,
        quotes=quotes,
    )

    assert set(quotes) == {"AAPL", "MSFT"}
    assert actual_total_value == pytest.approx(expected_total_value)
    assert actual_weights == pytest.approx(expected_weights)


@pytest.mark.integration
def test_model_portfolio_repository_calculate_current_weight_for_manual_long_only_snapshot(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    """Calculate expected current weights for manual long-only positions."""
    snapshot = ModelPortfolioSnapshot(
        positions=[
            ModelPortfolioPosition(
                symbol="AAPL",
                target_weight=0.6,
                direction=1,
                leverage=1.0,
                model_filled_quantity=60.0,
                model_filled_avg_price=150.0,
            ),
            ModelPortfolioPosition(
                symbol="MSFT",
                target_weight=0.4,
                direction=1,
                leverage=1.0,
                model_filled_quantity=40.0,
                model_filled_avg_price=300.0,
            ),
        ],
        timestamp=CREATED_AT,
        snapshot_id=str(uuid4()),
    )

    actual_weights, actual_total_value, quotes = (
        model_portfolio_repository.calculate_positions_current_weight(snapshot)
    )
    expected_weights, expected_total_value = _expected_current_weights(
        snapshot=snapshot,
        quotes=quotes,
    )

    assert set(quotes) == {"AAPL", "MSFT"}
    assert actual_total_value == pytest.approx(expected_total_value)
    assert actual_weights == pytest.approx(expected_weights)


@pytest.mark.integration
def test_model_portfolio_repository_calculate_current_weight_for_manual_short_only_snapshot(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    """Calculate expected current weights for manual short-only positions."""
    snapshot = ModelPortfolioSnapshot(
        positions=[
            ModelPortfolioPosition(
                symbol="AAPL",
                target_weight=0.6,
                direction=-1,
                leverage=1.0,
                model_filled_quantity=60.0,
                model_filled_avg_price=150.0,
            ),
            ModelPortfolioPosition(
                symbol="MSFT",
                target_weight=0.4,
                direction=-1,
                leverage=1.0,
                model_filled_quantity=40.0,
                model_filled_avg_price=300.0,
            ),
        ],
        timestamp=CREATED_AT,
        snapshot_id=str(uuid4()),
    )

    actual_weights, actual_total_value, quotes = (
        model_portfolio_repository.calculate_positions_current_weight(snapshot)
    )
    expected_weights, expected_total_value = _expected_current_weights(
        snapshot=snapshot,
        quotes=quotes,
    )

    assert set(quotes) == {"AAPL", "MSFT"}
    assert actual_total_value == pytest.approx(expected_total_value)
    assert actual_weights == pytest.approx(expected_weights)


@pytest.mark.integration
def test_model_portfolio_repository_calculate_current_weight_for_created_portfolio(
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    """Create a portfolio and calculate expected current weights from its snapshot."""
    portfolio_id = None

    try:
        portfolio_id = _create_portfolio(
            model_portfolio_repository,
            owner_id=test_user_1.cognito_user_id,
            positions=[
                _long_position(symbol="AAPL", target_weight=0.6),
                _long_position(symbol="MSFT", target_weight=0.4),
            ],
            visibility="PUBLIC",
            description="calculate current weights",
        )
        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )
        snapshot = portfolio.position_history[0]

        actual_weights, actual_total_value, quotes = (
            model_portfolio_repository.calculate_positions_current_weight(snapshot)
        )
        expected_weights, expected_total_value = _expected_current_weights(
            snapshot=snapshot,
            quotes=quotes,
        )

        assert set(quotes) == {"AAPL", "MSFT"}
        assert actual_total_value == pytest.approx(expected_total_value)
        assert actual_weights == pytest.approx(expected_weights)
    finally:
        _delete_model_portfolio(
            model_portfolio_repository,
            portfolio_id=portfolio_id,
        )

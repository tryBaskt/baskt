from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from domain.model_portfolio_domain import (
    ModelPortfolioPosition,
    ModelPortfolioSnapshot,
)
from repository.model_portfolio_repository import (
    ModelPortfolioInvalidWeightError,
    ModelPortfolioLockedError,
    ModelPortfolioNotFoundError,
    ModelPortfolioRepository,
    ModelPortfolioTooManyRequestsError,
    ModelPortfolioUnprocessableEntityError,
)
from schema.model_portfolio_schema import ModelPortfolioPositionRequest


def _position(
    *,
    symbol: str,
    target_weight: float,
    direction: int = 1,
    leverage: float = 1.0,
) -> ModelPortfolioPositionRequest:
    return ModelPortfolioPositionRequest(
        symbol=symbol,
        target_weight=target_weight,
        direction=direction,
        leverage=leverage,
    )


@pytest.mark.integration
def test_model_portfolio_repository_create_get_update_and_history(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    owner_cognito_user_id = f"repository-test-owner-{uuid4()}"
    created_at = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
    updated_at = created_at + timedelta(seconds=61)
    portfolio_id = None

    try:
        portfolio_id = model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id=owner_cognito_user_id,
            portfolio_name="Repository Test Portfolio",
            positions_request=[
                _position(symbol="AAPL", target_weight=0.6),
                _position(symbol="MSFT", target_weight=0.4),
            ],
            creation_time=created_at,
            description="Created by repository integration test.",
        )

        portfolio = model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id,
        )
        assert portfolio.portfolio_id == portfolio_id
        assert portfolio.portfolio_owner_cognito_user_id == owner_cognito_user_id
        assert portfolio.portfolio_name == "Repository Test Portfolio"
        assert portfolio.description == "Created by repository integration test."
        assert portfolio.created_at == created_at
        assert portfolio.updated_at == created_at
        assert len(portfolio.position_history) == 1
        assert {
            position.symbol: position.target_weight
            for position in portfolio.position_history[0].positions
        } == {"AAPL": 0.6, "MSFT": 0.4}

        metadata = model_portfolio_repository.get_model_portfolio_metadata_by_owner(
            portfolio_owner_cognito_user_id=owner_cognito_user_id,
        )
        assert any(item["portfolio_id"] == portfolio_id for item in metadata)

        updated, snapshot_id = model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=[
                _position(symbol="AAPL", target_weight=0.5),
                _position(symbol="MSFT", target_weight=0.3),
                _position(symbol="GOOG", target_weight=0.2, direction=-1),
            ],
            update_time=updated_at,
            description="Updated by repository integration test.",
        )
        assert updated is True
        assert snapshot_id is not None

        history = model_portfolio_repository.get_position_history(
            portfolio_id=portfolio_id,
        )
        assert len(history) == 2
        assert history[-1].snapshot_id == snapshot_id
        assert history[-1].timestamp == updated_at
        assert {
            position.symbol: position.target_weight
            for position in history[-1].positions
        } == {"AAPL": 0.5, "MSFT": 0.3, "GOOG": 0.2}

        last_snapshot = model_portfolio_repository.get_n_last_model_portfolio_snapshots(
            portfolio_id=portfolio_id,
            n=1,
        )
        assert len(last_snapshot) == 1
        assert last_snapshot[0].snapshot_id == snapshot_id
    finally:
        if portfolio_id is not None:
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )


def test_model_portfolio_repository_rejects_invalid_weight_total(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    with pytest.raises(ModelPortfolioInvalidWeightError):
        model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id=f"repository-test-owner-{uuid4()}",
            portfolio_name="Invalid Weight Portfolio",
            positions_request=[
                _position(symbol="AAPL", target_weight=0.5),
                _position(symbol="MSFT", target_weight=0.4),
            ],
            creation_time=datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc),
        )


@pytest.mark.integration
def test_model_portfolio_repository_missing_and_invalid_snapshot_paths(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    missing_portfolio_id = f"missing-repository-portfolio-{uuid4()}"

    with pytest.raises(ModelPortfolioNotFoundError):
        model_portfolio_repository.get_model_portfolio(missing_portfolio_id)

    with pytest.raises(ModelPortfolioNotFoundError):
        model_portfolio_repository.get_position_history(missing_portfolio_id)

    with pytest.raises(ValueError):
        model_portfolio_repository.get_n_last_model_portfolio_snapshots(
            portfolio_id=missing_portfolio_id,
            n=0,
        )

    assert (
        model_portfolio_repository.get_model_portfolio_metadata_by_owner(
            portfolio_owner_cognito_user_id=f"missing-owner-{uuid4()}",
        )
        == []
    )


@pytest.mark.integration
def test_model_portfolio_repository_malformed_items_are_wrapped(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    missing_history_portfolio_id = f"missing-history-{uuid4()}"
    malformed_history_portfolio_id = f"malformed-history-{uuid4()}"
    malformed_metadata_owner_id = f"malformed-owner-{uuid4()}"
    malformed_metadata_portfolio_id = f"malformed-metadata-{uuid4()}"

    try:
        model_portfolio_repository.dynamodb.put_item(
            {
                "portfolio_id": missing_history_portfolio_id,
                "portfolio_owner_cognito_user_id": f"owner-{uuid4()}",
                "portfolio_name": "Missing History",
            }
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_position_history(
                missing_history_portfolio_id
            )

        model_portfolio_repository.dynamodb.put_item(
            {
                "portfolio_id": malformed_history_portfolio_id,
                "portfolio_owner_cognito_user_id": f"owner-{uuid4()}",
                "portfolio_name": "Malformed History",
                "position_history": [{"positions": "not-position-list"}],
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_model_portfolio(
                malformed_history_portfolio_id
            )

        model_portfolio_repository.dynamodb.put_item(
            {
                "portfolio_id": malformed_metadata_portfolio_id,
                "portfolio_owner_cognito_user_id": malformed_metadata_owner_id,
                "description": "Missing portfolio name",
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
        )
        with pytest.raises(ModelPortfolioUnprocessableEntityError):
            model_portfolio_repository.get_model_portfolio_metadata_by_owner(
                malformed_metadata_owner_id
            )
    finally:
        for portfolio_id in (
            missing_history_portfolio_id,
            malformed_history_portfolio_id,
            malformed_metadata_portfolio_id,
        ):
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )


@pytest.mark.integration
def test_model_portfolio_repository_noop_cooldown_locked_and_zero_weight_paths(
    model_portfolio_repository: ModelPortfolioRepository,
) -> None:
    owner_cognito_user_id = f"repository-test-owner-{uuid4()}"
    created_at = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
    positions = [_position(symbol="AAPL", target_weight=1.0)]
    portfolio_id = None
    lock_owner_token = str(uuid4())

    try:
        portfolio_id = model_portfolio_repository.create_model_portfolio(
            portfolio_owner_cognito_user_id=owner_cognito_user_id,
            portfolio_name="Repository Branch Portfolio",
            positions_request=positions,
            creation_time=created_at,
            description="Original description",
        )

        assert model_portfolio_repository.update_model_portfolio(
            portfolio_id=portfolio_id,
            positions_request=positions,
            update_time=created_at + timedelta(seconds=1),
            description="Original description",
        ) == (False, None)

        with pytest.raises(ModelPortfolioTooManyRequestsError):
            model_portfolio_repository.update_model_portfolio(
                portfolio_id=portfolio_id,
                positions_request=positions,
                update_time=created_at + timedelta(seconds=30),
                description="Changed too soon",
            )

        assert model_portfolio_repository.model_portfolio_update_lock_repository.acquire_lock(
            portfolio_id=portfolio_id,
            owner_token=lock_owner_token,
            lease_seconds=30,
        )
        with pytest.raises(ModelPortfolioLockedError):
            model_portfolio_repository.update_model_portfolio(
                portfolio_id=portfolio_id,
                positions_request=[
                    _position(symbol="MSFT", target_weight=1.0),
                ],
                update_time=created_at + timedelta(seconds=120),
                description="Locked update",
            )

        snapshot = ModelPortfolioSnapshot(
            positions=[
                ModelPortfolioPosition(
                    symbol="AAPL",
                    target_weight=1.0,
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=0.0,
                    model_filled_avg_price=100.0,
                )
            ],
            timestamp=created_at,
            snapshot_id=str(uuid4()),
        )
        weights, total_value, quotes = (
            model_portfolio_repository.calculate_positions_current_weight(snapshot)
        )
        assert weights == {"AAPL": 0.0}
        assert total_value == 0.0
        assert "AAPL" in quotes
    finally:
        if portfolio_id is not None:
            model_portfolio_repository.model_portfolio_update_lock_repository.release_lock(
                portfolio_id=portfolio_id,
                owner_token=lock_owner_token,
            )
            model_portfolio_repository.dynamodb.delete_item(
                key={"portfolio_id": portfolio_id}
            )

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from domain.model_portfolio_domain import (
    ModelPortfolio,
    ModelPortfolioPosition,
    ModelPortfolioSnapshot,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from schema.model_portfolio_schema import ModelPortfolioPositionRequest


def _repository(existing: ModelPortfolio) -> ModelPortfolioRepository:
    repository = ModelPortfolioRepository.__new__(ModelPortfolioRepository)
    repository.get_model_portfolio = MagicMock(return_value=existing)
    repository.model_portfolio_update_lock_repository = MagicMock()
    repository.model_portfolio_update_lock_repository.acquire_lock.return_value = True
    repository.alpaca_broker_client = MagicMock()
    repository.dynamodb = MagicMock()
    return repository


def _existing_portfolio() -> ModelPortfolio:
    created_at = datetime.now(timezone.utc) - timedelta(days=1)
    position = ModelPortfolioPosition(
        symbol="AAPL",
        target_weight=1.0,
        direction=1,
        leverage=1.0,
        model_filled_quantity=50.0,
        model_filled_avg_price=200.0,
    )
    snapshot = ModelPortfolioSnapshot(
        positions=[position],
        timestamp=created_at,
        snapshot_id="snapshot-1",
    )
    return ModelPortfolio(
        portfolio_id="portfolio-1",
        portfolio_owner_cognito_user_id="owner-1",
        portfolio_name="Apple",
        position_history=[snapshot],
        created_at=created_at,
        updated_at=created_at,
        description="Original description",
    )


def _position_request(target_weight: float = 1.0) -> ModelPortfolioPositionRequest:
    return ModelPortfolioPositionRequest(
        symbol="AAPL",
        target_weight=target_weight,
        direction=1,
        leverage=1.0,
    )


def test_no_change_does_not_persist() -> None:
    repository = _repository(_existing_portfolio())

    result = repository.update_model_portfolio(
        portfolio_id="portfolio-1",
        positions_request=[_position_request()],
        description="Original description",
    )

    assert result == (False, None)
    repository.dynamodb.put_item.assert_not_called()
    repository.alpaca_broker_client.get_latest_price.assert_not_called()
    repository.model_portfolio_update_lock_repository.acquire_lock.assert_not_called()


def test_description_only_update_reuses_position_history() -> None:
    repository = _repository(_existing_portfolio())

    result = repository.update_model_portfolio(
        portfolio_id="portfolio-1",
        positions_request=[_position_request()],
        update_time=datetime.now(timezone.utc),
        description="Updated description",
    )

    assert result == (True, None)
    repository.alpaca_broker_client.get_latest_price.assert_not_called()
    item = repository.dynamodb.put_item.call_args.args[0]
    assert item["description"] == "Updated description"
    assert len(item["position_history"]) == 1
    assert item["position_history"][0]["snapshot_id"] == "snapshot-1"


def test_position_update_appends_snapshot_and_returns_its_id() -> None:
    repository = _repository(_existing_portfolio())
    repository.alpaca_broker_client.get_latest_price.return_value = {"AAPL": 250.0}

    updated, snapshot_id = repository.update_model_portfolio(
        portfolio_id="portfolio-1",
        positions_request=[_position_request(target_weight=0.75)],
        update_time=datetime.now(timezone.utc),
        description="Original description",
    )

    assert updated is True
    assert snapshot_id is not None
    item = repository.dynamodb.put_item.call_args.args[0]
    assert len(item["position_history"]) == 2
    assert item["position_history"][-1]["snapshot_id"] == snapshot_id
    repository.alpaca_broker_client.get_latest_price.assert_called_once_with(
        symbols=["AAPL"]
    )

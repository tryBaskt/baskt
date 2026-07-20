import pytest

from repository.model_portfolio_repository import (
    ModelPortfolioInvalidWeightError,
    ModelPortfolioRepository,
)
from schema.model_portfolio_schema import ModelPortfolioPositionRequest


class UnexpectedDependency:
    def __getattr__(self, name):
        raise AssertionError(f"Unexpected dependency call: {name}")


def make_repository() -> ModelPortfolioRepository:
    return ModelPortfolioRepository(
        dynamodb_client=UnexpectedDependency(),
        alpaca_broker_client=UnexpectedDependency(),
        model_portfolio_update_lock_repository=UnexpectedDependency(),
        model_portfolio_follower_repository=UnexpectedDependency(),
    )


def make_position(symbol: str, target_weight: float) -> ModelPortfolioPositionRequest:
    return ModelPortfolioPositionRequest(
        symbol=symbol,
        target_weight=target_weight,
        direction=1,
        leverage=1,
    )


def test_create_model_portfolio_rejects_positions_when_target_weights_do_not_total_100_percent():
    repository = make_repository()

    with pytest.raises(ModelPortfolioInvalidWeightError) as exc_info:
        repository.create_model_portfolio(
            portfolio_owner_cognito_user_id="user-123",
            portfolio_name="Underweight Baskt",
            positions_request=[
                make_position("AAPL", 0.4),
                make_position("MSFT", 0.4),
            ],
        )

    assert exc_info.value.code == "MODEL_PORTFOLIO_INVALID_TARGET_WEIGHT_TOTAL"
    assert "must total 100%" in str(exc_info.value)


def test_update_model_portfolio_rejects_positions_when_target_weights_do_not_total_100_percent():
    repository = make_repository()

    with pytest.raises(ModelPortfolioInvalidWeightError) as exc_info:
        repository.update_model_portfolio(
            portfolio_id="portfolio-123",
            positions_request=[
                make_position("AAPL", 0.5),
                make_position("MSFT", 0.3),
            ],
        )

    assert exc_info.value.code == "MODEL_PORTFOLIO_INVALID_TARGET_WEIGHT_TOTAL"
    assert "must total 100%" in str(exc_info.value)

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from conftest import OWNER_USER_ID
from core.deps import (
    get_baskt_account_repository,
    get_model_portfolio_repository,
    get_trade_execution_queuing_service,
)
from domain.model_portfolio_domain import (
    ModelPortfolio,
    ModelPortfolioPosition,
    ModelPortfolioSnapshot,
)
from repository.model_portfolio_repository import ModelPortfolioNotFoundError
from routes.model_portfolio_route import router as model_portfolio_router


class FakeBasktAccountRepository:
    def get_display_name(self, cognito_user_id: str) -> str:
        return f"display-{cognito_user_id}"


class FakeModelPortfolioRepository:
    def __init__(self, *, portfolio_visibility: str = "PUBLIC") -> None:
        now = datetime.now(timezone.utc)
        self.portfolio = ModelPortfolio(
            portfolio_id="portfolio-1",
            portfolio_owner_cognito_user_id=OWNER_USER_ID,
            portfolio_name="Owner Portfolio",
            position_history=[
                ModelPortfolioSnapshot(
                    snapshot_id="snapshot-1",
                    timestamp=now,
                    positions=[
                        ModelPortfolioPosition(
                            symbol="AAPL",
                            target_weight=1.0,
                            direction=1,
                            leverage=1.0,
                            model_filled_quantity=10.0,
                            model_filled_avg_price=100.0,
                        )
                    ],
                )
            ],
            created_at=now,
            updated_at=now,
            description="owned by owner-user",
        )
        object.__setattr__(self.portfolio, "visibility", portfolio_visibility)
        self.update_called = False

    def get_model_portfolio(
        self,
        portfolio_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ModelPortfolio:
        if portfolio_id != self.portfolio.portfolio_id:
            raise ModelPortfolioNotFoundError(portfolio_id=portfolio_id)
        return self.portfolio

    def calculate_positions_current_weight(
        self,
        model_portfolio_snapshot: ModelPortfolioSnapshot,
    ):
        return {"AAPL": 1.0}, 1000.0, {"AAPL": 100.0}

    def update_model_portfolio(self, *args: Any, **kwargs: Any):
        self.update_called = True
        return True, "snapshot-2"


class FakeTradeExecutionQueuingService:
    def __init__(self) -> None:
        self.queue_update_called = False

    def queue_portfolio_update(self, *args: Any, **kwargs: Any) -> Dict[str, str]:
        self.queue_update_called = True
        return {}


@pytest.fixture
def model_portfolio_app(app_factory):
    app = app_factory(model_portfolio_router)
    repository = FakeModelPortfolioRepository()
    queuing_service = FakeTradeExecutionQueuingService()
    app.dependency_overrides[get_model_portfolio_repository] = lambda: repository
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: FakeBasktAccountRepository()
    )
    app.dependency_overrides[get_trade_execution_queuing_service] = (
        lambda: queuing_service
    )
    return {
        "app": app,
        "repository": repository,
        "queuing_service": queuing_service,
    }


@pytest.fixture
def model_portfolio_client(model_portfolio_app, client_for_app):
    with client_for_app(model_portfolio_app["app"]) as client:
        yield client


def test_non_owner_cannot_update_model_portfolio(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    response = model_portfolio_client.put(
        "/model-portfolios/portfolio-1",
        json={
            "positions": [
                {
                    "symbol": "AAPL",
                    "target_weight": 1.0,
                    "direction": 1,
                    "leverage": 1.0,
                }
            ],
            "description": "attempted cross-user update",
        },
    )

    assert response.status_code == 403
    assert model_portfolio_app["repository"].update_called is False
    assert model_portfolio_app["queuing_service"].queue_update_called is False


def test_authenticated_user_can_fetch_public_model_portfolio(
    model_portfolio_client,
) -> None:
    response = model_portfolio_client.get("/model-portfolios/portfolio-1")

    assert response.status_code == 200, response.text
    assert response.json()["portfolio_id"] == "portfolio-1"
    assert response.json()["portfolio_owner_cognito_user_id"] == OWNER_USER_ID


@pytest.mark.xfail(
    reason=(
        "Model portfolio routes do not enforce visibility yet; private "
        "portfolio reads currently look identical to public reads."
    ),
    strict=True,
)
def test_authenticated_non_owner_cannot_fetch_private_model_portfolio(
    model_portfolio_client,
    model_portfolio_app,
) -> None:
    model_portfolio_app["repository"].portfolio = FakeModelPortfolioRepository(
        portfolio_visibility="PRIVATE"
    ).portfolio

    response = model_portfolio_client.get("/model-portfolios/portfolio-1")

    assert response.status_code == 403

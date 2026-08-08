from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from conftest import (
    OTHER_ALPACA_ACCOUNT_ID,
    OTHER_USER_ID,
    OWNER_USER_ID,
    fake_baskt_account,
)
from core.authentication import get_current_baskt_account
from core.deps import (
    get_model_portfolio_access_repository,
    get_model_portfolio_repository,
    get_trade_execution_queuing_service,
)
from domain.model_portfolio_domain import (
    ModelPortfolio,
    ModelPortfolioPosition,
    ModelPortfolioSnapshot,
)
from routes.trade_execution_route import router as trade_execution_router
from services.trade_execution_queuing_service import (
    TradeExecutionQueuingInternalServerError,
)


class FakeTradeExecutionQueuingService:
    def __init__(self, *, fail_code: str | None = None) -> None:
        self.fail_code = fail_code
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, action: str, **kwargs: Any) -> None:
        self.calls.append((action, kwargs))
        if self.fail_code:
            raise TradeExecutionQueuingInternalServerError(
                "trade queue failed",
                code=self.fail_code,
            )

    def queue_portfolio_deposit(self, **kwargs: Any) -> None:
        self._record("portfolio_deposit", **kwargs)

    def queue_portfolio_withdrawal(self, **kwargs: Any) -> None:
        self._record("portfolio_withdrawal", **kwargs)

    def queue_portfolio_withdraw_all(self, **kwargs: Any) -> None:
        self._record("portfolio_withdraw_all", **kwargs)

    def queue_stock_buy(self, **kwargs: Any) -> None:
        self._record("stock_buy", **kwargs)

    def queue_stock_sell(self, **kwargs: Any) -> None:
        self._record("stock_sell", **kwargs)

    def queue_stock_close(self, **kwargs: Any) -> None:
        self._record("stock_close", **kwargs)


class FakeModelPortfolioRepository:
    def __init__(self, *, visibility: str = "PUBLIC") -> None:
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
            visibility=visibility,
        )

    def get_model_portfolio(self, *, portfolio_id: str) -> ModelPortfolio:
        return self.portfolio


class FakeModelPortfolioAccessRepository:
    def __init__(self, *, has_access: bool = False) -> None:
        self._has_access = has_access

    def has_access(self, **kwargs: Any) -> bool:
        return self._has_access


@pytest.fixture
def trade_execution_app(app_factory):
    app = app_factory(trade_execution_router)
    service = FakeTradeExecutionQueuingService()
    portfolio_repository = FakeModelPortfolioRepository()
    access_repository = FakeModelPortfolioAccessRepository()
    app.dependency_overrides[get_trade_execution_queuing_service] = lambda: service
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: portfolio_repository
    )
    app.dependency_overrides[get_model_portfolio_access_repository] = (
        lambda: access_repository
    )
    return {
        "app": app,
        "service": service,
        "portfolio_repository": portfolio_repository,
        "access_repository": access_repository,
    }


@pytest.fixture
def trade_execution_client(trade_execution_app, client_for_app):
    with client_for_app(trade_execution_app["app"]) as client:
        yield client


@pytest.mark.parametrize(
    ("method", "path", "json_body", "expected_action"),
    [
        (
            "post",
            "/trade-execution/portfolios/portfolio-1/deposit",
            {"amount": 25.0},
            "portfolio_deposit",
        ),
        (
            "post",
            "/trade-execution/portfolios/portfolio-1/withdrawal",
            {"amount": 25.0},
            "portfolio_withdrawal",
        ),
        (
            "post",
            "/trade-execution/portfolios/portfolio-1/withdraw-all",
            None,
            "portfolio_withdraw_all",
        ),
        (
            "post",
            "/trade-execution/stocks/asset-aapl/buy",
            {"amount": 25.0},
            "stock_buy",
        ),
        (
            "post",
            "/trade-execution/stocks/asset-aapl/sell",
            {"amount": 25.0},
            "stock_sell",
        ),
        ("post", "/trade-execution/stocks/asset-aapl/close", None, "stock_close"),
    ],
)
def test_trade_execution_routes_queue_authenticated_user_actions(
    trade_execution_client,
    trade_execution_app,
    method,
    path,
    json_body,
    expected_action,
) -> None:
    response = getattr(trade_execution_client, method)(path, json=json_body)

    assert response.status_code == 202, response.text
    assert response.json() == {"success": True}
    action, kwargs = trade_execution_app["service"].calls[-1]
    assert action == expected_action
    assert kwargs["cognito_user_id"] == OTHER_USER_ID
    assert kwargs["alpaca_account_id"] == OTHER_ALPACA_ACCOUNT_ID


def test_trade_execution_route_maps_queue_errors(
    trade_execution_client,
    trade_execution_app,
) -> None:
    trade_execution_app["app"].dependency_overrides[get_trade_execution_queuing_service] = (
        lambda: FakeTradeExecutionQueuingService(
            fail_code="TRADE_EXECUTION_QUEUE_AMOUNT_INVALID"
        )
    )

    response = trade_execution_client.post(
        "/trade-execution/stocks/asset-aapl/buy",
        json={"amount": 25.0},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TRADE_EXECUTION_QUEUE_AMOUNT_INVALID"


def test_private_portfolio_deposit_requires_access(
    trade_execution_client,
    trade_execution_app,
) -> None:
    trade_execution_app["portfolio_repository"].portfolio = (
        FakeModelPortfolioRepository(visibility="PRIVATE").portfolio
    )

    response = trade_execution_client.post(
        "/trade-execution/portfolios/portfolio-1/deposit",
        json={"amount": 25.0},
    )

    assert response.status_code == 403
    assert trade_execution_app["service"].calls == []


@pytest.mark.parametrize(
    ("path", "json_body", "expected_action"),
    [
        (
            "/trade-execution/portfolios/portfolio-1/deposit",
            {"amount": 25.0},
            "portfolio_deposit",
        ),
        (
            "/trade-execution/portfolios/portfolio-1/withdrawal",
            {"amount": 25.0},
            "portfolio_withdrawal",
        ),
        (
            "/trade-execution/portfolios/portfolio-1/withdraw-all",
            None,
            "portfolio_withdraw_all",
        ),
    ],
)
def test_private_portfolio_trade_routes_allow_shared_user(
    trade_execution_client,
    trade_execution_app,
    path,
    json_body,
    expected_action,
) -> None:
    trade_execution_app["portfolio_repository"].portfolio = (
        FakeModelPortfolioRepository(visibility="PRIVATE").portfolio
    )
    trade_execution_app["app"].dependency_overrides[
        get_model_portfolio_access_repository
    ] = lambda: FakeModelPortfolioAccessRepository(has_access=True)

    response = trade_execution_client.post(path, json=json_body)

    assert response.status_code == 202, response.text
    action, kwargs = trade_execution_app["service"].calls[-1]
    assert action == expected_action
    assert kwargs["cognito_user_id"] == OTHER_USER_ID


def test_private_portfolio_trade_routes_allow_owner_without_access_grant(
    trade_execution_client,
    trade_execution_app,
) -> None:
    trade_execution_app["portfolio_repository"].portfolio = (
        FakeModelPortfolioRepository(visibility="PRIVATE").portfolio
    )
    trade_execution_app["app"].dependency_overrides[get_current_baskt_account] = (
        lambda: fake_baskt_account(cognito_user_id=OWNER_USER_ID)
    )

    response = trade_execution_client.post(
        "/trade-execution/portfolios/portfolio-1/deposit",
        json={"amount": 25.0},
    )

    assert response.status_code == 202, response.text
    action, kwargs = trade_execution_app["service"].calls[-1]
    assert action == "portfolio_deposit"
    assert kwargs["cognito_user_id"] == OWNER_USER_ID

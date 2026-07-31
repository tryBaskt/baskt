from __future__ import annotations

from typing import Any

import pytest

from conftest import OTHER_ALPACA_ACCOUNT_ID, OTHER_USER_ID
from core.deps import get_trade_execution_queuing_service
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


@pytest.fixture
def trade_execution_app(app_factory):
    app = app_factory(trade_execution_router)
    service = FakeTradeExecutionQueuingService()
    app.dependency_overrides[get_trade_execution_queuing_service] = lambda: service
    return {"app": app, "service": service}


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

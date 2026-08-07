from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from conftest import OTHER_ALPACA_ACCOUNT_ID, OTHER_USER_ID, FakeAlpacaAccount
from core.authentication import get_current_alpaca_account
from core.deps import (
    get_allocation_analytics_service,
    get_order_repository,
    get_allocation_repository,
    get_trade_execution_service,
)
from domain.allocation_domain import PortfolioAllocationTransactionSnapshot
from repository.allocation_repository import AllocationNotFoundError
from routes.allocation_analytics_route import router as allocation_analytics_router
from services.allocation_analytics_service import AllocationAnalyticsInternalServerError


class FakeOrderRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_allocation_ids_of_unfilled_orders(self, cognito_user_id: str):
        self.calls.append(cognito_user_id)
        return [("portfolio-1", "owner-user")]


class FakeTradeExecutionService:
    def __init__(self) -> None:
        self.realize_calls: list[Dict[str, Any]] = []

    def realize_filled_orders(self, **kwargs: Any) -> None:
        self.realize_calls.append(kwargs)


class FakeAllocationAnalyticsService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.analytics_calls: list[tuple[str, str | None]] = []
        now = datetime(2024, 1, 2, tzinfo=timezone.utc)
        self.transaction = PortfolioAllocationTransactionSnapshot(
            transaction_id="transaction-1",
            created_at=now,
            updated_at=now,
            filled_at=now,
            requested_amount=100.0,
            number_orders=2,
            transaction_type="DEPOSIT",
            cost_basis=100.0,
            order_fill_percent=1.0,
            status="FULLY_FILLED",
        )

    def _maybe_fail(self) -> None:
        if self.fail:
            raise AllocationAnalyticsInternalServerError("analytics failed")

    def get_all_active_allocation_analytics(self, cognito_user_id: str, alpaca_account_id: str):
        self._maybe_fail()
        self.analytics_calls.append((cognito_user_id, alpaca_account_id))
        return {
            "cash": 25.0,
            "equity": 125.0,
            "equity_graph": {
                "1M": {
                    "equity": [100.0, 125.0],
                    "timestamp": [
                        datetime(2024, 1, 1, tzinfo=timezone.utc),
                        datetime(2024, 1, 2, tzinfo=timezone.utc),
                    ],
                }
            },
            "allocations": {
                "portfolio-1": {"equity": 125.0, "portfolio_name": "Growth"}
            },
        }

    def get_portfolio_allocation_analytics(
        self,
        cognito_user_id: str,
        portfolio_id: str,
    ):
        self._maybe_fail()
        self.analytics_calls.append((cognito_user_id, portfolio_id))
        return {
            "total_cost_basis": 100.0,
            "equity": 125.0,
            "profit_loss": 25.0,
            "profit_loss_percent": 0.25,
        }

    def get_portfolio_allocation_transaction_history(
        self,
        cognito_user_id: str,
        portfolio_id: str,
    ):
        self.analytics_calls.append((cognito_user_id, portfolio_id))
        return [self.transaction]

    def get_stock_allocation_analytics(
        self,
        cognito_user_id: str,
        stock_id: str,
    ):
        self._maybe_fail()
        self.analytics_calls.append((cognito_user_id, stock_id))
        return {
            "total_cost_basis": 100.0,
            "equity": 125.0,
            "profit_loss": 25.0,
            "profit_loss_percent": 0.25,
            "direction": 1,
        }

    def get_stock_allocation_transaction_history(
        self,
        cognito_user_id: str,
        stock_id: str,
    ):
        self.analytics_calls.append((cognito_user_id, stock_id))
        return [self.transaction]


class FakeAllocationRepository:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.calls: list[tuple[str, str]] = []

    def get_allocation(self, cognito_user_id: str, allocation_id: str):
        self.calls.append((cognito_user_id, allocation_id))
        if self.missing:
            raise AllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            )
        return object()


@pytest.fixture
def allocation_analytics_app(app_factory):
    app = app_factory(allocation_analytics_router)
    order_repository = FakeOrderRepository()
    trade_execution_service = FakeTradeExecutionService()
    analytics_service = FakeAllocationAnalyticsService()
    allocation_repository = FakeAllocationRepository()
    app.dependency_overrides[get_order_repository] = lambda: order_repository
    app.dependency_overrides[get_trade_execution_service] = (
        lambda: trade_execution_service
    )
    app.dependency_overrides[get_allocation_analytics_service] = (
        lambda: analytics_service
    )
    app.dependency_overrides[get_allocation_repository] = (
        lambda: allocation_repository
    )
    return {
        "app": app,
        "order_repository": order_repository,
        "trade_execution_service": trade_execution_service,
        "analytics_service": analytics_service,
        "allocation_repository": allocation_repository,
    }


@pytest.fixture
def allocation_analytics_client(allocation_analytics_app, client_for_app):
    with client_for_app(allocation_analytics_app["app"]) as client:
        yield client


def test_account_analytics_realizes_unfilled_orders_and_returns_equity_graph(
    allocation_analytics_client,
    allocation_analytics_app,
) -> None:
    response = allocation_analytics_client.get("/allocation_analytics")

    assert response.status_code == 200, response.text
    assert response.json()["cash"] == 25.0
    assert response.json()["equity_graph"]["1M"]["equity"] == [100.0, 125.0]
    assert allocation_analytics_app["order_repository"].calls == [OTHER_USER_ID]
    assert allocation_analytics_app["trade_execution_service"].realize_calls == [
        {
            "cognito_user_id": OTHER_USER_ID,
            "alpaca_account_id": OTHER_ALPACA_ACCOUNT_ID,
            "allocation_id": "portfolio-1",
            "lock_already_acquired": False,
        }
    ]


def test_account_analytics_returns_empty_response_for_inactive_alpaca_account(
    allocation_analytics_client,
    allocation_analytics_app,
) -> None:
    allocation_analytics_app["app"].dependency_overrides[get_current_alpaca_account] = (
        lambda: FakeAlpacaAccount(status="INACTIVE")
    )

    response = allocation_analytics_client.get("/allocation_analytics")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "cash": 0.0,
        "equity": 0.0,
        "equity_graph": {},
        "allocations": {},
    }
    assert allocation_analytics_app["order_repository"].calls == []


def test_portfolio_allocation_analytics_returns_owned_allocation(
    allocation_analytics_client,
    allocation_analytics_app,
) -> None:
    response = allocation_analytics_client.get(
        "/allocation_analytics/portfolios/portfolio-1/analytics"
    )

    assert response.status_code == 200, response.text
    assert response.json()["portfolio_id"] == "portfolio-1"
    assert response.json()["transaction_history"][0]["transaction_id"] == "transaction-1"
    assert response.json()["profit_loss_percent"] == 0.25
    assert allocation_analytics_app["allocation_repository"].calls == [
        (OTHER_USER_ID, "portfolio-1")
    ]


def test_user_cannot_read_another_users_portfolio_allocation_analytics(
    allocation_analytics_client,
    allocation_analytics_app,
) -> None:
    allocation_analytics_app["app"].dependency_overrides[
        get_allocation_repository
    ] = lambda: FakeAllocationRepository(missing=True)

    response = allocation_analytics_client.get(
        "/allocation_analytics/portfolios/portfolio-1/analytics"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "portfolio_id": "portfolio-1",
        "transaction_history": None,
        "total_cost_basis": None,
        "equity": None,
        "profit_loss": None,
        "profit_loss_percent": None,
    }
    assert allocation_analytics_app["analytics_service"].analytics_calls == []
    assert allocation_analytics_app["trade_execution_service"].realize_calls == []


def test_stock_allocation_analytics_returns_owned_allocation(
    allocation_analytics_client,
) -> None:
    response = allocation_analytics_client.get(
        "/allocation_analytics/stocks/asset-aapl/analytics"
    )

    assert response.status_code == 200, response.text
    assert response.json()["stock_id"] == "asset-aapl"
    assert response.json()["transaction_history"][0]["transaction_id"] == "transaction-1"
    assert response.json()["equity"] == 125.0


def test_allocation_analytics_route_maps_service_errors(
    allocation_analytics_client,
    allocation_analytics_app,
) -> None:
    allocation_analytics_app["app"].dependency_overrides[
        get_allocation_analytics_service
    ] = lambda: FakeAllocationAnalyticsService(fail=True)

    response = allocation_analytics_client.get("/allocation_analytics")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "ALLOCATION_ANALYTICS_SERVICE_ERROR"

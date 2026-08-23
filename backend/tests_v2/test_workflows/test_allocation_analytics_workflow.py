from __future__ import annotations

"""
These workflow tests exercise allocation_analytics_route.py through FastAPI's
TestClient while keeping repositories, allocation analytics, trade execution
realization, and Alpaca price/account data wired to the real tests_v2
integration stack.

Allocation records are written directly to the allocation DynamoDB table. Model
portfolio allocations are backed by real model portfolio rows so
realize_filled_orders() can load the portfolio owner through the real
repository.

Coverage goals:
- GET /allocation_analytics: authenticated ACTIVE/APPROVED users receive cash,
  equity, equity graph, and active allocation rows.
- GET /allocation_analytics: inactive Alpaca accounts return an empty account
  analytics payload without loading allocation analytics.
- GET /allocation_analytics: active stock and portfolio allocations are
  included, inactive allocations are skipped, open-order-only allocations are
  included with zero equity, stock and portfolio allocations are split into
  separate response maps, names/types/direction are shaped correctly, and
  allocation equity percentages are calculated from account equity.
- GET /allocation_analytics/portfolios/{portfolio_id}/analytics: whitespace
  portfolio ids return 400, missing allocations return an empty response model,
  inactive Alpaca accounts return an empty response model, and persisted
  allocations return analytics plus fully-filled transaction history.
- GET /allocation_analytics/stocks/{stock_id}/analytics: whitespace stock ids
  return 400, missing allocations return an empty response model, inactive
  Alpaca accounts return an empty response model, and persisted allocations
  return analytics plus fully-filled transaction history and direction.
- Authentication: missing auth headers, token Alpaca-account mismatches, and
  unknown token Cognito user ids are rejected by the real Baskt account auth
  dependency.

Skipped by design:
- Forced lower-level Alpaca/DynamoDB failures, because those require mock
  resource failures instead of a fully integrated route workflow.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clients.dynamodb_client import DynamoDBClient, dataclass_to_dynamodb_item
from core import deps as app_deps
from core.authentication import get_current_alpaca_account, get_current_user
from core.deps import (
    get_allocation_analytics_service,
    get_allocation_repository,
    get_alpaca_broker_client,
    get_baskt_account_repository,
    get_order_repository,
    get_trade_execution_service,
)
from domain.allocation_domain import (
    PortfolioAllocation,
    PortfolioAllocationPosition,
    PortfolioAllocationPositionSnapshot,
    PortfolioAllocationTransactionSnapshot,
    StockAllocation,
    StockAllocationPosition,
    StockAllocationPositionSnapshot,
    StockAllocationTransactionSnapshot,
)
from repository.allocation_repository import AllocationRepository
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_access_repository import ModelPortfolioAccessRepository
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from repository.order_repository import OrderRepository
from routes import allocation_analytics_route
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.allocation_analytics_service import AllocationAnalyticsService
from services.trade_execution_service import TradeExecutionService


pytestmark = pytest.mark.integration

TIMESTAMP = datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc)
SECOND_TIMESTAMP = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
LIVE_PRICE_REL_TOLERANCE = 0.01


def _claims_for_user(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _claims_without_baskt_account() -> dict[str, str]:
    unique = uuid4()
    return {
        "sub": f"tests-v2-no-allocation-analytics-account-{unique}",
        "custom:alpaca_acct_id": f"tests-v2-no-allocation-analytics-alpaca-{unique}",
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


def _alpaca_account(status_name: str = "ACTIVE") -> SimpleNamespace:
    return SimpleNamespace(status=SimpleNamespace(name=status_name))


def _allocation_analytics_service(
    *,
    allocation_repository: AllocationRepository,
) -> AllocationAnalyticsService:
    return AllocationAnalyticsService(
        alpaca_broker_client=app_deps.get_alpaca_broker_client(),
        allocation_repository=allocation_repository,
    )


def _client_for_claims(
    *,
    claims: dict[str, str] | None,
    alpaca_account_status: str,
    alpaca_broker_client: Any,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
) -> TestClient:
    service = _allocation_analytics_service(
        allocation_repository=allocation_repository,
    )
    app = FastAPI()
    app.include_router(allocation_analytics_route.router)
    if claims is not None:
        app.dependency_overrides[get_current_user] = lambda: claims
    app.dependency_overrides[get_current_alpaca_account] = lambda: _alpaca_account(
        alpaca_account_status
    )
    app.dependency_overrides[
        allocation_analytics_route.get_current_alpaca_account
    ] = lambda: _alpaca_account(alpaca_account_status)
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[get_alpaca_broker_client] = lambda: alpaca_broker_client
    app.dependency_overrides[get_allocation_repository] = lambda: allocation_repository
    app.dependency_overrides[
        allocation_analytics_route.get_allocation_repository
    ] = lambda: allocation_repository
    app.dependency_overrides[get_order_repository] = lambda: order_repository
    app.dependency_overrides[
        allocation_analytics_route.get_order_repository
    ] = lambda: order_repository
    app.dependency_overrides[get_trade_execution_service] = (
        lambda: trade_execution_service
    )
    app.dependency_overrides[
        allocation_analytics_route.get_trade_execution_service
    ] = lambda: trade_execution_service
    app.dependency_overrides[get_allocation_analytics_service] = lambda: service
    app.dependency_overrides[
        allocation_analytics_route.get_allocation_analytics_service
    ] = lambda: service
    return TestClient(app)


def _client_for_user(
    *,
    test_user: Any,
    alpaca_account_status: str = "ACTIVE",
    alpaca_broker_client: Any,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
) -> TestClient:
    return _client_for_claims(
        claims=_claims_for_user(test_user),
        alpaca_account_status=alpaca_account_status,
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
        order_repository=order_repository,
        trade_execution_service=trade_execution_service,
    )


def _portfolio_snapshot() -> PortfolioAllocationPositionSnapshot:
    return PortfolioAllocationPositionSnapshot(
        positions=[
            PortfolioAllocationPosition(
                symbol="AAPL",
                filled_quantity=2.0,
                direction=1,
                filled_avg_price=100.0,
            ),
            PortfolioAllocationPosition(
                symbol="MSFT",
                filled_quantity=1.5,
                direction=-1,
                filled_avg_price=300.0,
            ),
        ],
        timestamp=TIMESTAMP,
    )


def _stock_snapshot(direction: int = 1) -> StockAllocationPositionSnapshot:
    return StockAllocationPositionSnapshot(
        position=StockAllocationPosition(
            symbol="AAPL",
            filled_quantity=3.0,
            direction=direction,
            filled_avg_price=100.0,
        ),
        timestamp=TIMESTAMP,
    )


def _portfolio_transactions() -> list[PortfolioAllocationTransactionSnapshot]:
    return [
        PortfolioAllocationTransactionSnapshot(
            transaction_id=f"allocation-analytics-route-portfolio-tx-{uuid4()}",
            created_at=TIMESTAMP,
            updated_at=TIMESTAMP,
            requested_amount=650.0,
            transaction_type="DEPOSIT",
            status="FULLY_FILLED",
            filled_at=TIMESTAMP,
            portfolio_snapshot_id=f"snapshot-{uuid4()}",
            number_orders=2,
            cost_basis=650.0,
            order_fill_percent=100.0,
        ),
        PortfolioAllocationTransactionSnapshot(
            transaction_id=f"allocation-analytics-route-portfolio-tx-{uuid4()}",
            created_at=SECOND_TIMESTAMP,
            updated_at=SECOND_TIMESTAMP,
            requested_amount=150.0,
            transaction_type="WITHDRAW",
            status="FULLY_FILLED",
            filled_at=SECOND_TIMESTAMP,
            portfolio_snapshot_id=f"snapshot-{uuid4()}",
            number_orders=2,
            cost_basis=150.0,
            order_fill_percent=100.0,
            status_explanation="fully filled route fixture",
        ),
    ]


def _stock_transactions() -> list[StockAllocationTransactionSnapshot]:
    return [
        StockAllocationTransactionSnapshot(
            transaction_id=f"allocation-analytics-route-stock-tx-{uuid4()}",
            created_at=TIMESTAMP,
            updated_at=TIMESTAMP,
            requested_amount=300.0,
            transaction_type="BUY",
            status="FULLY_FILLED",
            filled_at=TIMESTAMP,
            number_orders=1,
            cost_basis=300.0,
            order_fill_percent=100.0,
        ),
        StockAllocationTransactionSnapshot(
            transaction_id=f"allocation-analytics-route-stock-tx-{uuid4()}",
            created_at=SECOND_TIMESTAMP,
            updated_at=SECOND_TIMESTAMP,
            requested_amount=100.0,
            transaction_type="SELL",
            status="FULLY_FILLED",
            filled_at=SECOND_TIMESTAMP,
            number_orders=1,
            cost_basis=100.0,
            order_fill_percent=100.0,
            status_explanation="fully filled route fixture",
        ),
    ]


def _stock_allocation(
    *,
    cognito_user_id: str,
    allocation_id: str | None = None,
    total_cost_basis: float = 300.0,
    direction: int = 1,
    open_positions: bool = True,
    open_orders: bool = False,
    position_history: list[StockAllocationPositionSnapshot] | None = None,
    transaction_history: list[StockAllocationTransactionSnapshot] | None = None,
    symbol: str = "AAPL",
) -> StockAllocation:
    return StockAllocation(
        allocation_id=allocation_id or f"allocation-analytics-route-stock-{uuid4()}",
        cognito_user_id=cognito_user_id,
        total_cost_basis=total_cost_basis,
        open_positions=open_positions,
        open_orders=open_orders,
        allocation_type="STOCK",
        position_history=(
            position_history
            if position_history is not None
            else [_stock_snapshot(direction=direction)]
        ),
        transaction_history=(
            transaction_history if transaction_history is not None else _stock_transactions()
        ),
        symbol=symbol,
    )


def _portfolio_allocation(
    *,
    cognito_user_id: str,
    portfolio_id: str,
    portfolio_name: str,
    total_cost_basis: float = 650.0,
    open_positions: bool = True,
    open_orders: bool = False,
    position_history: list[PortfolioAllocationPositionSnapshot] | None = None,
    transaction_history: list[PortfolioAllocationTransactionSnapshot] | None = None,
) -> PortfolioAllocation:
    return PortfolioAllocation(
        allocation_id=portfolio_id,
        cognito_user_id=cognito_user_id,
        total_cost_basis=total_cost_basis,
        open_positions=open_positions,
        open_orders=open_orders,
        allocation_type="MODEL_PORTFOLIO",
        position_history=position_history if position_history is not None else [_portfolio_snapshot()],
        transaction_history=(
            transaction_history if transaction_history is not None else _portfolio_transactions()
        ),
        portfolio_name=portfolio_name,
    )


def _put_allocation(
    *,
    allocation_dynamodb_client: DynamoDBClient,
    allocation: PortfolioAllocation | StockAllocation,
) -> None:
    allocation_dynamodb_client.put_item(item=dataclass_to_dynamodb_item(allocation))


def _delete_allocation(
    *,
    allocation_dynamodb_client: DynamoDBClient,
    allocation: PortfolioAllocation | StockAllocation,
) -> None:
    allocation_dynamodb_client.delete_item(
        key={
            "cognito_user_id": allocation.cognito_user_id,
            "allocation_id": allocation.allocation_id,
        }
    )


def _cleanup_allocations(
    *,
    allocation_dynamodb_client: DynamoDBClient,
    allocations: list[PortfolioAllocation | StockAllocation],
) -> None:
    for allocation in allocations:
        _delete_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )


def _create_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    portfolio_name: str | None = None,
) -> tuple[str, str]:
    name = portfolio_name or f"allocation-analytics-route-portfolio-{uuid4()}"
    portfolio_id = model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=owner_cognito_user_id,
        portfolio_name=name,
        positions_request=[
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1,
            )
        ],
        visibility="PRIVATE",
        creation_time=TIMESTAMP,
        description="Allocation analytics route test portfolio",
    )
    return portfolio_id, name


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


def _delete_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    portfolio_id: str | None,
) -> None:
    if portfolio_id is None:
        return
    for access in model_portfolio_access_repository.get_accesses_for_portfolio(
        portfolio_id=portfolio_id,
        wait_for_lock=False,
    ):
        _delete_access(
            model_portfolio_access_repository=model_portfolio_access_repository,
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=access.shared_with_cognito_user_id,
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


def _assert_transaction_response_is_fully_filled(transaction: dict[str, Any]) -> None:
    assert transaction["status"] == "FULLY_FILLED"
    assert transaction["filled_at"] is not None
    assert transaction["order_fill_percent"] == pytest.approx(100.0)


def test_allocation_analytics_route_get_all_active_allocations_happy_path(
    alpaca_broker_client: Any,
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1: Any,
) -> None:
    portfolio_id: str | None = None
    allocations: list[PortfolioAllocation | StockAllocation] = []
    try:
        portfolio_id, portfolio_name = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
        )
        stock_allocation = _stock_allocation(
            cognito_user_id=test_user_1.cognito_user_id,
            total_cost_basis=300.0,
            symbol="AAPL",
        )
        portfolio_allocation = _portfolio_allocation(
            cognito_user_id=test_user_1.cognito_user_id,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            total_cost_basis=650.0,
        )
        inactive_allocation = _stock_allocation(
            cognito_user_id=test_user_1.cognito_user_id,
            total_cost_basis=0.0,
            open_positions=False,
            open_orders=False,
            position_history=[],
            transaction_history=[],
            symbol="MSFT",
        )
        open_order_allocation = _stock_allocation(
            cognito_user_id=test_user_1.cognito_user_id,
            total_cost_basis=100.0,
            open_positions=False,
            open_orders=True,
            position_history=[],
            symbol="AAPL",
        )
        allocations = [
            stock_allocation,
            portfolio_allocation,
            inactive_allocation,
            open_order_allocation,
        ]
        for allocation in allocations:
            _put_allocation(
                allocation_dynamodb_client=allocation_dynamodb_client,
                allocation=allocation,
            )

        expected_stock_equity, _ = (
            allocation_repository.calculate_stock_allocation_position_snapshot_current_value(
                position_snapshot=stock_allocation.position_history[-1],
            )
        )
        _, expected_portfolio_equity, _ = (
            allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
                position_snapshot=portfolio_allocation.position_history[-1],
            )
        )
        trade_account = app_deps.get_alpaca_broker_client().get_trade_account(
            account_id=test_user_1.alpaca_account_id,
            cognito_user_id=test_user_1.cognito_user_id,
        )
        account_equity = float(trade_account.equity)
        client = _client_for_user(
            test_user=test_user_1,
            alpaca_broker_client=alpaca_broker_client,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
        )

        response = client.get("/allocation_analytics")

        assert response.status_code == 200
        body = response.json()
        assert body["cash"] == pytest.approx(
            float(trade_account.cash),
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert body["equity"] == pytest.approx(
            account_equity,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert set(body["equity_graph"]) == {"1D", "1W", "1M", "3M", "1A", "ALL"}
        assert set(body["stock_allocations"]) >= {
            stock_allocation.allocation_id,
            open_order_allocation.allocation_id,
        }
        assert set(body["portfolio_allocations"]) >= {
            portfolio_allocation.allocation_id,
        }
        assert inactive_allocation.allocation_id not in body["stock_allocations"]
        assert inactive_allocation.allocation_id not in body["portfolio_allocations"]

        stock_row = body["stock_allocations"][stock_allocation.allocation_id]
        assert stock_row["stock_symbol"] == "AAPL"
        assert stock_row["allocation_type"] == "STOCK"
        assert stock_row["direction"] == 1
        assert stock_row["allocation_equity"] == pytest.approx(
            expected_stock_equity,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert stock_row["allocation_equity_percent"] == pytest.approx(
            expected_stock_equity / account_equity,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )

        portfolio_row = body["portfolio_allocations"][portfolio_allocation.allocation_id]
        assert portfolio_row["portfolio_name"] == portfolio_name
        assert portfolio_row["allocation_type"] == "MODEL_PORTFOLIO"
        assert portfolio_row["allocation_equity"] == pytest.approx(
            expected_portfolio_equity,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert portfolio_row["allocation_equity_percent"] == pytest.approx(
            expected_portfolio_equity / account_equity,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )

        open_order_row = body["stock_allocations"][open_order_allocation.allocation_id]
        assert open_order_row["stock_symbol"] == "AAPL"
        assert open_order_row["direction"] is None
        assert open_order_row["allocation_equity"] == pytest.approx(0.0)
        assert open_order_row["allocation_equity_percent"] == pytest.approx(0.0)
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=allocations,
        )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_allocation_analytics_route_get_all_inactive_account_returns_empty(
    alpaca_broker_client: Any,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        alpaca_account_status="SUBMITTED",
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
        order_repository=order_repository,
        trade_execution_service=trade_execution_service,
    )

    response = client.get("/allocation_analytics")

    assert response.status_code == 200
    assert response.json() == {
        "cash": 0.0,
        "equity": 0.0,
        "equity_graph": {},
        "stock_allocations": {},
        "portfolio_allocations": {},
    }


def test_allocation_analytics_route_portfolio_happy_path(
    alpaca_broker_client: Any,
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    test_user_1: Any,
) -> None:
    portfolio_id: str | None = None
    allocations: list[PortfolioAllocation | StockAllocation] = []
    try:
        portfolio_id, portfolio_name = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
        )
        allocation = _portfolio_allocation(
            cognito_user_id=test_user_1.cognito_user_id,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            total_cost_basis=650.0,
        )
        allocations = [allocation]
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )
        _, expected_equity, _ = (
            allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
                position_snapshot=allocation.position_history[-1],
            )
        )
        client = _client_for_user(
            test_user=test_user_1,
            alpaca_broker_client=alpaca_broker_client,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
        )

        response = client.get(f"/allocation_analytics/portfolios/{portfolio_id}/analytics")

        assert response.status_code == 200
        body = response.json()
        assert body["portfolio_id"] == portfolio_id
        assert body["total_cost_basis"] == pytest.approx(650.0)
        assert body["equity"] == pytest.approx(
            expected_equity,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert body["profit_loss"] == pytest.approx(
            expected_equity - 650.0,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert body["profit_loss_percent"] == pytest.approx(
            (expected_equity - 650.0) / 650.0,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert len(body["transaction_history"]) == 2
        for transaction in body["transaction_history"]:
            _assert_transaction_response_is_fully_filled(transaction)
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=allocations,
        )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_allocation_analytics_route_portfolio_missing_inactive_and_blank_paths(
    alpaca_broker_client: Any,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
        order_repository=order_repository,
        trade_execution_service=trade_execution_service,
    )
    missing_id = f"missing-portfolio-{uuid4()}"

    missing_response = client.get(
        f"/allocation_analytics/portfolios/{missing_id}/analytics"
    )
    blank_response = client.get("/allocation_analytics/portfolios/%20%20/analytics")
    inactive_client = _client_for_user(
        test_user=test_user_1,
        alpaca_account_status="SUBMITTED",
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
        order_repository=order_repository,
        trade_execution_service=trade_execution_service,
    )
    inactive_response = inactive_client.get(
        f"/allocation_analytics/portfolios/{missing_id}/analytics"
    )

    assert missing_response.status_code == 200
    assert missing_response.json()["portfolio_id"] == missing_id
    assert blank_response.status_code == 400
    assert blank_response.json()["detail"] == "portfolio_id is required."
    assert inactive_response.status_code == 200
    assert inactive_response.json()["portfolio_id"] == missing_id


def test_allocation_analytics_route_stock_happy_path(
    alpaca_broker_client: Any,
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    test_user_1: Any,
) -> None:
    allocation = _stock_allocation(
        cognito_user_id=test_user_1.cognito_user_id,
        total_cost_basis=300.0,
        direction=-1,
    )
    try:
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )
        expected_equity, _ = (
            allocation_repository.calculate_stock_allocation_position_snapshot_current_value(
                position_snapshot=allocation.position_history[-1],
            )
        )
        client = _client_for_user(
            test_user=test_user_1,
            alpaca_broker_client=alpaca_broker_client,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
        )

        response = client.get(
            f"/allocation_analytics/stocks/{allocation.allocation_id}/analytics"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["stock_id"] == allocation.allocation_id
        assert body["total_cost_basis"] == pytest.approx(300.0)
        assert body["equity"] == pytest.approx(
            expected_equity,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert body["profit_loss"] == pytest.approx(
            expected_equity - 300.0,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert body["profit_loss_percent"] == pytest.approx(
            (expected_equity - 300.0) / 300.0,
            rel=LIVE_PRICE_REL_TOLERANCE,
        )
        assert body["direction"] == -1
        assert len(body["transaction_history"]) == 2
        for transaction in body["transaction_history"]:
            _assert_transaction_response_is_fully_filled(transaction)
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_allocation_analytics_route_stock_missing_inactive_and_blank_paths(
    alpaca_broker_client: Any,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    test_user_1: Any,
) -> None:
    client = _client_for_user(
        test_user=test_user_1,
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
        order_repository=order_repository,
        trade_execution_service=trade_execution_service,
    )
    missing_id = f"missing-stock-{uuid4()}"

    missing_response = client.get(
        f"/allocation_analytics/stocks/{missing_id}/analytics"
    )
    blank_response = client.get("/allocation_analytics/stocks/%20%20/analytics")
    inactive_client = _client_for_user(
        test_user=test_user_1,
        alpaca_account_status="SUBMITTED",
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
        order_repository=order_repository,
        trade_execution_service=trade_execution_service,
    )
    inactive_response = inactive_client.get(
        f"/allocation_analytics/stocks/{missing_id}/analytics"
    )

    assert missing_response.status_code == 200
    assert missing_response.json()["stock_id"] == missing_id
    assert blank_response.status_code == 400
    assert blank_response.json()["detail"] == "stock_id is required."
    assert inactive_response.status_code == 200
    assert inactive_response.json()["stock_id"] == missing_id


@pytest.mark.parametrize(
    ("claims_factory", "expected_status"),
    [
        (lambda test_user: None, 401),
        (lambda _test_user: _claims_without_baskt_account(), 403),
        (_claims_with_mismatched_alpaca_account, 403),
        (_claims_with_mismatched_cognito_user_id, 403),
    ],
)
def test_allocation_analytics_route_authentication_failures(
    claims_factory,
    expected_status: int,
    alpaca_broker_client: Any,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    test_user_1: Any,
) -> None:
    claims = claims_factory(test_user_1)
    client = _client_for_claims(
        claims=claims,
        alpaca_account_status="ACTIVE",
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
        order_repository=order_repository,
        trade_execution_service=trade_execution_service,
    )

    response = client.get("/allocation_analytics")

    assert response.status_code == expected_status

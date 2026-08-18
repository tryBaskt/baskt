from __future__ import annotations

"""
These tests exercise AllocationAnalyticsService against the real tests_v2
repository and DynamoDB table. Allocation records are created directly in
DynamoDB so the tests focus on analytics service behavior, not trade execution
workflows.

Coverage goals:
- get_portfolio_allocation_analytics(): return empty analytics for a missing
  allocation and for an inactive allocation with no open orders/positions.
- get_portfolio_allocation_analytics(): return zero analytics for an
  open-order-only allocation.
- get_portfolio_allocation_analytics(): calculate total cost basis, current
  equity, profit/loss, and profit/loss percent for open portfolio positions.
- get_portfolio_allocation_analytics(): avoid divide-by-zero when cost basis is
  zero and positions exist.
- get_stock_allocation_analytics(): return empty analytics for a missing
  allocation and for an inactive allocation with no open orders/positions.
- get_stock_allocation_analytics(): return zero analytics for an
  open-order-only allocation.
- get_stock_allocation_analytics(): calculate total cost basis, current equity,
  profit/loss, profit/loss percent, and direction for long and short stock
  positions.
- get_stock_allocation_analytics(): avoid divide-by-zero when cost basis is
  zero and positions exist.
- get_portfolio_allocation_transaction_history(): return [] for a missing
  allocation and return persisted portfolio transaction snapshots in order.
- get_stock_allocation_transaction_history(): return [] for a missing
  allocation and return persisted stock transaction snapshots in order.
- get_all_active_allocation_analytics(): return cash, equity, equity graph, and
  active allocation rows.
- get_all_active_allocation_analytics(): include active stock/portfolio
  allocations, skip inactive allocations, include open-order-only allocations at
  zero equity, calculate allocation equity percentages, and use symbol/name
  display values.

Skipped by design:
- Forced lower-level Alpaca/DynamoDB failure wrapping, because that would require
  mock resources instead of a fully integrated system.
- Account equity == 0.0 handling, because the integrated Alpaca account equity
  is external state and should not be mocked here.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from clients.dynamodb_client import DynamoDBClient, dataclass_to_dynamodb_item
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
from services.allocation_analytics_service import AllocationAnalyticsService


pytestmark = pytest.mark.integration

TIMESTAMP = datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc)
SECOND_TIMESTAMP = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)


def _unique_user_id() -> str:
    return f"allocation-analytics-user-{uuid4().hex}"


def _unique_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


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


def _stock_snapshot(
    *,
    direction: int = 1,
    filled_quantity: float = 3.0,
    filled_avg_price: float = 100.0,
) -> StockAllocationPositionSnapshot:
    return StockAllocationPositionSnapshot(
        position=StockAllocationPosition(
            symbol="AAPL",
            filled_quantity=filled_quantity,
            direction=direction,
            filled_avg_price=filled_avg_price,
        ),
        timestamp=TIMESTAMP,
    )


def _portfolio_transactions() -> list[PortfolioAllocationTransactionSnapshot]:
    first_id = _unique_id("allocation-analytics-portfolio-transaction")
    second_id = _unique_id("allocation-analytics-portfolio-transaction")
    return [
        PortfolioAllocationTransactionSnapshot(
            transaction_id=first_id,
            created_at=TIMESTAMP,
            updated_at=TIMESTAMP,
            requested_amount=650.0,
            transaction_type="DEPOSIT",
            status="FULLY_FILLED",
            portfolio_snapshot_id=_unique_id("snapshot"),
            filled_at=TIMESTAMP,
            number_orders=2,
            cost_basis=650.0,
            order_fill_percent=100.0,
        ),
        PortfolioAllocationTransactionSnapshot(
            transaction_id=second_id,
            created_at=SECOND_TIMESTAMP,
            updated_at=SECOND_TIMESTAMP,
            requested_amount=150.0,
            transaction_type="WITHDRAW",
            status="FULLY_FILLED",
            portfolio_snapshot_id=_unique_id("snapshot"),
            filled_at=SECOND_TIMESTAMP,
            number_orders=2,
            cost_basis=150.0,
            order_fill_percent=100.0,
            status_explanation="fully filled analytics fixture",
        ),
    ]


def _stock_transactions() -> list[StockAllocationTransactionSnapshot]:
    first_id = _unique_id("allocation-analytics-stock-transaction")
    second_id = _unique_id("allocation-analytics-stock-transaction")
    return [
        StockAllocationTransactionSnapshot(
            transaction_id=first_id,
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
            transaction_id=second_id,
            created_at=SECOND_TIMESTAMP,
            updated_at=SECOND_TIMESTAMP,
            requested_amount=100.0,
            transaction_type="SELL",
            status="FULLY_FILLED",
            filled_at=SECOND_TIMESTAMP,
            number_orders=1,
            cost_basis=100.0,
            order_fill_percent=100.0,
            status_explanation="partial fill",
        ),
    ]


def _portfolio_allocation(
    *,
    cognito_user_id: str,
    allocation_id: str | None = None,
    total_cost_basis: float = 650.0,
    open_positions: bool = True,
    open_orders: bool = False,
    position_history: list[PortfolioAllocationPositionSnapshot] | None = None,
    transaction_history: list[PortfolioAllocationTransactionSnapshot] | None = None,
    portfolio_name: str | None = None,
) -> PortfolioAllocation:
    unique_suffix = uuid4().hex
    return PortfolioAllocation(
        allocation_id=allocation_id or _unique_id("allocation-analytics-portfolio"),
        cognito_user_id=cognito_user_id,
        total_cost_basis=total_cost_basis,
        open_positions=open_positions,
        open_orders=open_orders,
        allocation_type="MODEL_PORTFOLIO",
        position_history=position_history if position_history is not None else [_portfolio_snapshot()],
        transaction_history=(
            transaction_history if transaction_history is not None else _portfolio_transactions()
        ),
        portfolio_name=portfolio_name or f"Allocation Analytics Portfolio {unique_suffix[:8]}",
    )


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
        allocation_id=allocation_id or _unique_id("allocation-analytics-stock"),
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


def _put_allocation(
    *,
    allocation_dynamodb_client: DynamoDBClient,
    allocation: PortfolioAllocation | StockAllocation,
) -> None:
    allocation_dynamodb_client.put_item(
        item=dataclass_to_dynamodb_item(allocation),
    )


def _delete_allocation(
    *,
    allocation_dynamodb_client: DynamoDBClient,
    cognito_user_id: str,
    allocation_id: str,
) -> None:
    allocation_dynamodb_client.delete_item(
        key={
            "cognito_user_id": cognito_user_id,
            "allocation_id": allocation_id,
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
            cognito_user_id=allocation.cognito_user_id,
            allocation_id=allocation.allocation_id,
        )


def _assert_transaction_matches_domain(transaction, expected) -> None:
    assert asdict(transaction) == asdict(expected)


def test_portfolio_allocation_analytics_returns_empty_for_missing_allocation(
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    analytics = allocation_analytics_service.get_portfolio_allocation_analytics(
        cognito_user_id=_unique_user_id(),
        portfolio_id=_unique_id("missing-portfolio"),
    )

    assert analytics == {}


def test_portfolio_allocation_analytics_returns_empty_for_inactive_allocation(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=0.0,
        open_positions=False,
        open_orders=False,
        position_history=[],
        transaction_history=[],
    )

    try:
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        analytics = allocation_analytics_service.get_portfolio_allocation_analytics(
            cognito_user_id=cognito_user_id,
            portfolio_id=allocation.allocation_id,
        )

        assert analytics == {}
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_portfolio_allocation_analytics_returns_zero_for_open_orders_only(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=250.0,
        open_positions=False,
        open_orders=True,
        position_history=[],
    )

    try:
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        analytics = allocation_analytics_service.get_portfolio_allocation_analytics(
            cognito_user_id=cognito_user_id,
            portfolio_id=allocation.allocation_id,
        )

        assert analytics == {
            "total_cost_basis": 0.0,
            "equity": 0.0,
            "profit_loss": 0.0,
            "profit_loss_percent": 0.0,
        }
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_portfolio_allocation_analytics_calculates_open_position_metrics(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=650.0,
    )

    try:
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        _, expected_equity, _ = (
            allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
                position_snapshot=allocation.position_history[-1],
            )
        )
        analytics = allocation_analytics_service.get_portfolio_allocation_analytics(
            cognito_user_id=cognito_user_id,
            portfolio_id=allocation.allocation_id,
        )

        assert analytics["total_cost_basis"] == pytest.approx(650.0)
        assert analytics["equity"] == pytest.approx(expected_equity)
        assert analytics["profit_loss"] == pytest.approx(expected_equity - 650.0)
        assert analytics["profit_loss_percent"] == pytest.approx(
            (expected_equity - 650.0) / 650.0
        )
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_portfolio_allocation_analytics_zero_cost_basis_uses_zero_percent(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=0.0,
    )

    try:
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        _, expected_equity, _ = (
            allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
                position_snapshot=allocation.position_history[-1],
            )
        )
        analytics = allocation_analytics_service.get_portfolio_allocation_analytics(
            cognito_user_id=cognito_user_id,
            portfolio_id=allocation.allocation_id,
        )

        assert analytics["total_cost_basis"] == pytest.approx(0.0)
        assert analytics["equity"] == pytest.approx(expected_equity)
        assert analytics["profit_loss"] == pytest.approx(expected_equity)
        assert analytics["profit_loss_percent"] == pytest.approx(0.0)
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_stock_allocation_analytics_returns_empty_for_missing_allocation(
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    analytics = allocation_analytics_service.get_stock_allocation_analytics(
        cognito_user_id=_unique_user_id(),
        stock_id=_unique_id("missing-stock"),
    )

    assert analytics == {}


def test_stock_allocation_analytics_returns_empty_for_inactive_allocation(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=0.0,
        open_positions=False,
        open_orders=False,
        position_history=[],
        transaction_history=[],
    )

    try:
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        analytics = allocation_analytics_service.get_stock_allocation_analytics(
            cognito_user_id=cognito_user_id,
            stock_id=allocation.allocation_id,
        )

        assert analytics == {}
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_stock_allocation_analytics_returns_zero_for_open_orders_only(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=250.0,
        open_positions=False,
        open_orders=True,
        position_history=[],
    )

    try:
        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        analytics = allocation_analytics_service.get_stock_allocation_analytics(
            cognito_user_id=cognito_user_id,
            stock_id=allocation.allocation_id,
        )

        assert analytics == {
            "total_cost_basis": 0.0,
            "equity": 0.0,
            "profit_loss": 0.0,
            "profit_loss_percent": 0.0,
        }
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


@pytest.mark.parametrize("direction", [1, -1])
def test_stock_allocation_analytics_calculates_open_position_metrics(
    direction: int,
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=300.0,
        direction=direction,
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
        analytics = allocation_analytics_service.get_stock_allocation_analytics(
            cognito_user_id=cognito_user_id,
            stock_id=allocation.allocation_id,
        )

        assert analytics["total_cost_basis"] == pytest.approx(300.0)
        assert analytics["equity"] == pytest.approx(expected_equity)
        assert analytics["profit_loss"] == pytest.approx(expected_equity - 300.0)
        assert analytics["profit_loss_percent"] == pytest.approx(
            (expected_equity - 300.0) / 300.0
        )
        assert analytics["direction"] == direction
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_stock_allocation_analytics_zero_cost_basis_uses_zero_percent(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=0.0,
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
        analytics = allocation_analytics_service.get_stock_allocation_analytics(
            cognito_user_id=cognito_user_id,
            stock_id=allocation.allocation_id,
        )

        assert analytics["total_cost_basis"] == pytest.approx(0.0)
        assert analytics["equity"] == pytest.approx(expected_equity)
        assert analytics["profit_loss"] == pytest.approx(expected_equity)
        assert analytics["profit_loss_percent"] == pytest.approx(0.0)
        assert analytics["direction"] == 1
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_portfolio_allocation_transaction_history_missing_and_persisted_order(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    transactions = _portfolio_transactions()
    allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        transaction_history=transactions,
    )

    try:
        assert (
            allocation_analytics_service.get_portfolio_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                portfolio_id=_unique_id("missing-portfolio"),
            )
            == []
        )

        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        loaded_transactions = (
            allocation_analytics_service.get_portfolio_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                portfolio_id=allocation.allocation_id,
            )
        )

        assert [transaction.transaction_id for transaction in loaded_transactions] == [
            transaction.transaction_id for transaction in transactions
        ]
        for loaded, expected in zip(loaded_transactions, transactions):
            _assert_transaction_matches_domain(loaded, expected)
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_stock_allocation_transaction_history_missing_and_persisted_order(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    cognito_user_id = _unique_user_id()
    transactions = _stock_transactions()
    allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        transaction_history=transactions,
    )

    try:
        assert (
            allocation_analytics_service.get_stock_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                stock_id=_unique_id("missing-stock"),
            )
            == []
        )

        _put_allocation(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocation=allocation,
        )

        loaded_transactions = (
            allocation_analytics_service.get_stock_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                stock_id=allocation.allocation_id,
            )
        )

        assert [transaction.transaction_id for transaction in loaded_transactions] == [
            transaction.transaction_id for transaction in transactions
        ]
        for loaded, expected in zip(loaded_transactions, transactions):
            _assert_transaction_matches_domain(loaded, expected)
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=[allocation],
        )


def test_all_active_allocation_analytics_returns_account_graph_and_allocations(
    allocation_dynamodb_client: DynamoDBClient,
    allocation_repository: AllocationRepository,
    allocation_analytics_service: AllocationAnalyticsService,
    test_user_1,
) -> None:
    cognito_user_id = _unique_user_id()
    stock_allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=300.0,
        symbol="AAPL",
    )
    portfolio_allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=650.0,
        portfolio_name="Allocation Analytics Service Portfolio",
    )
    inactive_allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=0.0,
        open_positions=False,
        open_orders=False,
        position_history=[],
        transaction_history=[],
        symbol="MSFT",
    )
    open_order_allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=100.0,
        open_positions=False,
        open_orders=True,
        position_history=[],
        portfolio_name="Allocation Analytics Open Orders",
    )
    allocations = [
        stock_allocation,
        portfolio_allocation,
        inactive_allocation,
        open_order_allocation,
    ]

    try:
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
        trade_account = allocation_analytics_service.alpaca_broker_client.get_trade_account(
            account_id=test_user_1.alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        account_equity = float(trade_account.equity)

        analytics = allocation_analytics_service.get_all_active_allocation_analytics(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
        )

        assert analytics["cash"] == pytest.approx(float(trade_account.cash))
        assert analytics["equity"] == pytest.approx(account_equity)
        assert set(analytics["equity_graph"]) == {"1D", "1W", "1M", "3M", "1A", "ALL"}
        for graph in analytics["equity_graph"].values():
            assert graph["equity"]
            assert graph["timestamp"]

        allocation_rows = analytics["allocations"]
        assert set(allocation_rows) == {
            stock_allocation.allocation_id,
            portfolio_allocation.allocation_id,
            open_order_allocation.allocation_id,
        }
        assert inactive_allocation.allocation_id not in allocation_rows

        stock_row = allocation_rows[stock_allocation.allocation_id]
        assert stock_row["allocation_name"] == "AAPL"
        assert stock_row["allocation_id"] == stock_allocation.allocation_id
        assert stock_row["allocation_type"] == "STOCK"
        assert stock_row["allocation_equity"] == pytest.approx(expected_stock_equity)
        assert stock_row["allocation_equity_percent"] == pytest.approx(
            expected_stock_equity / account_equity
        )

        portfolio_row = allocation_rows[portfolio_allocation.allocation_id]
        assert portfolio_row["allocation_name"] == portfolio_allocation.portfolio_name
        assert portfolio_row["allocation_id"] == portfolio_allocation.allocation_id
        assert portfolio_row["allocation_type"] == "MODEL_PORTFOLIO"
        assert portfolio_row["allocation_equity"] == pytest.approx(
            expected_portfolio_equity
        )
        assert portfolio_row["allocation_equity_percent"] == pytest.approx(
            expected_portfolio_equity / account_equity
        )

        open_order_row = allocation_rows[open_order_allocation.allocation_id]
        assert open_order_row["allocation_name"] == open_order_allocation.portfolio_name
        assert open_order_row["allocation_type"] == "MODEL_PORTFOLIO"
        assert open_order_row["allocation_equity"] == pytest.approx(0.0)
        assert open_order_row["allocation_equity_percent"] == pytest.approx(0.0)
    finally:
        _cleanup_allocations(
            allocation_dynamodb_client=allocation_dynamodb_client,
            allocations=allocations,
        )

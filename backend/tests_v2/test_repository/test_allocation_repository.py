from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

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
from repository.allocation_repository import (
    AllocationNotFoundError,
    AllocationRepository,
    AllocationUnprocessableEntityError,
)


"""
These tests exercise AllocationRepository behavior directly. They are repository
tests, not allocation analytics or trade execution workflow tests.

Coverage goals:
- is_exists_allocation_for_user(): return True for an existing allocation and
  False for a missing allocation.
- get_allocation_total_cost_basis(): return cost basis for stock and portfolio
  allocations and raise AllocationNotFoundError for missing allocations.
- get_allocations_by_cognito_user_id(): return stock and portfolio allocations
  for one user and return an empty list for a user with no allocations.
- get_allocation(): return parsed stock and portfolio allocations and raise
  AllocationNotFoundError for missing allocations.
- get_stock_allocation() and get_portfolio_allocation(): return the matching
  typed allocation and reject type mismatches with
  AllocationUnprocessableEntityError.
- get_portfolio_allocation_transaction_history() and
  get_stock_allocation_transaction_history(): return parsed transaction
  snapshots and raise AllocationNotFoundError for missing allocations.
- get_n_last_portfolio_allocation_transaction_snapshots() and
  get_n_last_stock_allocation_transaction_snapshots(): return latest one/latest
  all snapshots and reject invalid n values.
- get_portfolio_allocation_position_history() and
  get_stock_allocation_position_history(): return parsed position snapshots,
  including empty stock positions, and raise AllocationNotFoundError for missing
  allocations.
- get_latest_portfolio_allocation_position_snapshot() and
  get_latest_stock_allocation_position_snapshot(): return the final stored
  position snapshot.
- getter parse errors: malformed allocation, position-history, and
  transaction-history rows are wrapped in AllocationUnprocessableEntityError.
- set_allocation(): persist stock and portfolio allocations successfully and
  wrap invalid allocation serialization in AllocationUnprocessableEntityError.
- calculate_portfolio_allocation_position_snapshot_current_value(): calculate
  mixed long/short position values from hardcoded entry prices and latest
  prices returned by Alpaca.
- calculate_portfolio_allocation_position_snapshot_current_weight(): calculate
  normalized mixed long/short weights from current values.
- portfolio allocation object calculations: persist a full portfolio allocation,
  reload its latest snapshot, and calculate current values and weights.
- calculate_stock_allocation_position_snapshot_current_value(): calculate long
  and short stock allocation values from hardcoded entry prices and latest
  prices returned by Alpaca.
- stock allocation object calculations: persist a full stock allocation, reload
  its latest snapshot, and calculate current value.
"""


pytestmark = pytest.mark.integration

TIMESTAMP = datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc)


def _unique_user_id() -> str:
    return f"repository-user-{uuid4().hex}"


def _portfolio_position_snapshot() -> PortfolioAllocationPositionSnapshot:
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


def _stock_position_snapshot(
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


def _portfolio_allocation(
    *,
    cognito_user_id: str,
    allocation_id: str | None = None,
    total_cost_basis: float = 650.0,
) -> PortfolioAllocation:
    unique_suffix = uuid4().hex
    return PortfolioAllocation(
        allocation_id=allocation_id or f"repository-portfolio-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        total_cost_basis=total_cost_basis,
        open_positions=True,
        open_orders=False,
        allocation_type="MODEL_PORTFOLIO",
        position_history=[_portfolio_position_snapshot()],
        transaction_history=[
            PortfolioAllocationTransactionSnapshot(
                transaction_id=f"repository-portfolio-transaction-{unique_suffix}",
                created_at=TIMESTAMP,
                updated_at=TIMESTAMP,
                requested_amount=total_cost_basis,
                transaction_type="DEPOSIT",
                status="FULLY_FILLED",
                portfolio_snapshot_id=f"snapshot-{unique_suffix}",
                filled_at=TIMESTAMP,
                number_orders=2,
                cost_basis=total_cost_basis,
                order_fill_percent=100.0,
            )
        ],
        portfolio_name=f"Repository Portfolio {unique_suffix[:8]}",
    )


def _portfolio_allocation_with_two_histories(
    *,
    cognito_user_id: str,
) -> PortfolioAllocation:
    allocation = _portfolio_allocation(cognito_user_id=cognito_user_id)
    unique_suffix = uuid4().hex
    second_timestamp = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
    allocation.position_history.append(
        PortfolioAllocationPositionSnapshot(
            positions=[
                PortfolioAllocationPosition(
                    symbol="AAPL",
                    filled_quantity=3.0,
                    direction=1,
                    filled_avg_price=110.0,
                ),
                PortfolioAllocationPosition(
                    symbol="MSFT",
                    filled_quantity=2.0,
                    direction=-1,
                    filled_avg_price=280.0,
                ),
            ],
            timestamp=second_timestamp,
        )
    )
    allocation.transaction_history.append(
        PortfolioAllocationTransactionSnapshot(
            transaction_id=f"repository-portfolio-transaction-2-{unique_suffix}",
            created_at=second_timestamp,
            updated_at=second_timestamp,
            requested_amount=250.0,
            transaction_type="DEPOSIT",
            status="FULLY_FILLED",
            portfolio_snapshot_id=f"snapshot-2-{unique_suffix}",
            filled_at=second_timestamp,
            number_orders=2,
            cost_basis=250.0,
            order_fill_percent=100.0,
        )
    )
    return allocation


def _stock_allocation(
    *,
    cognito_user_id: str,
    allocation_id: str | None = None,
    total_cost_basis: float = 300.0,
    direction: int = 1,
) -> StockAllocation:
    unique_suffix = uuid4().hex
    return StockAllocation(
        allocation_id=allocation_id or f"repository-stock-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        total_cost_basis=total_cost_basis,
        open_positions=True,
        open_orders=False,
        allocation_type="STOCK",
        position_history=[
            _stock_position_snapshot(
                direction=direction,
                filled_quantity=3.0,
                filled_avg_price=100.0,
            )
        ],
        transaction_history=[
            StockAllocationTransactionSnapshot(
                transaction_id=f"repository-stock-transaction-{unique_suffix}",
                created_at=TIMESTAMP,
                updated_at=TIMESTAMP,
                requested_amount=total_cost_basis,
                transaction_type="BUY",
                status="FULLY_FILLED",
                filled_at=TIMESTAMP,
                number_orders=1,
                cost_basis=total_cost_basis,
                order_fill_percent=100.0,
            )
        ],
        symbol="AAPL",
    )


def _stock_allocation_with_two_histories(
    *,
    cognito_user_id: str,
) -> StockAllocation:
    allocation = _stock_allocation(cognito_user_id=cognito_user_id)
    unique_suffix = uuid4().hex
    second_timestamp = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
    allocation.position_history.append(
        StockAllocationPositionSnapshot(
            position=None,
            timestamp=second_timestamp,
        )
    )
    allocation.transaction_history.append(
        StockAllocationTransactionSnapshot(
            transaction_id=f"repository-stock-transaction-2-{unique_suffix}",
            created_at=second_timestamp,
            updated_at=second_timestamp,
            requested_amount=150.0,
            transaction_type="SELL",
            status="FULLY_FILLED",
            filled_at=second_timestamp,
            number_orders=1,
            cost_basis=150.0,
            order_fill_percent=100.0,
        )
    )
    return allocation


def _delete_allocation(
    *,
    allocation_repository: AllocationRepository,
    cognito_user_id: str,
    allocation_id: str,
) -> None:
    allocation_repository.allocation_table_client.delete_item(
        key={
            "cognito_user_id": cognito_user_id,
            "allocation_id": allocation_id,
        }
    )


def _expected_portfolio_values(
    *,
    snapshot: PortfolioAllocationPositionSnapshot,
    quotes: dict[str, float],
) -> dict[str, float]:
    return {
        position.symbol: position.filled_quantity
        * (
            position.filled_avg_price
            + position.direction * (quotes[position.symbol] - position.filled_avg_price)
        )
        for position in snapshot.positions
    }


def _expected_stock_value(
    *,
    position: StockAllocationPosition,
    current_price: float,
) -> float:
    return position.filled_quantity * (
        position.filled_avg_price
        + position.direction * (current_price - position.filled_avg_price)
    )


def test_allocation_repository_exists_returns_true_and_false(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation(cognito_user_id=cognito_user_id)

    try:
        allocation_repository.set_allocation(allocation)

        assert allocation_repository.is_exists_allocation_for_user(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        assert not allocation_repository.is_exists_allocation_for_user(
            cognito_user_id=cognito_user_id,
            allocation_id=f"missing-allocation-{uuid4().hex}",
        )
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )


def test_allocation_repository_get_total_cost_basis_for_stock_and_portfolio(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    portfolio_allocation = _portfolio_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=650.25,
    )
    stock_allocation = _stock_allocation(
        cognito_user_id=cognito_user_id,
        total_cost_basis=300.75,
    )

    try:
        allocation_repository.set_allocation(portfolio_allocation)
        allocation_repository.set_allocation(stock_allocation)

        assert allocation_repository.get_allocation_total_cost_basis(
            cognito_user_id=cognito_user_id,
            allocation_id=portfolio_allocation.allocation_id,
        ) == 650.25
        assert allocation_repository.get_allocation_total_cost_basis(
            cognito_user_id=cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        ) == 300.75
        with pytest.raises(AllocationNotFoundError):
            allocation_repository.get_allocation_total_cost_basis(
                cognito_user_id=cognito_user_id,
                allocation_id=f"missing-allocation-{uuid4().hex}",
            )
    finally:
        for allocation in (portfolio_allocation, stock_allocation):
            _delete_allocation(
                allocation_repository=allocation_repository,
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
            )


def test_allocation_repository_get_allocations_by_cognito_user_id(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    portfolio_allocation = _portfolio_allocation(cognito_user_id=cognito_user_id)
    stock_allocation = _stock_allocation(cognito_user_id=cognito_user_id)

    try:
        allocation_repository.set_allocation(portfolio_allocation)
        allocation_repository.set_allocation(stock_allocation)

        allocations = allocation_repository.get_allocations_by_cognito_user_id(
            cognito_user_id=cognito_user_id,
        )

        assert {allocation.allocation_id for allocation in allocations} == {
            portfolio_allocation.allocation_id,
            stock_allocation.allocation_id,
        }
        assert {
            allocation.allocation_type for allocation in allocations
        } == {"MODEL_PORTFOLIO", "STOCK"}
        assert allocation_repository.get_allocations_by_cognito_user_id(
            cognito_user_id=_unique_user_id(),
        ) == []
    finally:
        for allocation in (portfolio_allocation, stock_allocation):
            _delete_allocation(
                allocation_repository=allocation_repository,
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
            )


def test_allocation_repository_get_allocation_for_stock_portfolio_and_missing(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    portfolio_allocation = _portfolio_allocation(cognito_user_id=cognito_user_id)
    stock_allocation = _stock_allocation(cognito_user_id=cognito_user_id)

    try:
        allocation_repository.set_allocation(portfolio_allocation)
        allocation_repository.set_allocation(stock_allocation)

        loaded_portfolio = allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=portfolio_allocation.allocation_id,
        )
        loaded_stock = allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        )

        assert isinstance(loaded_portfolio, PortfolioAllocation)
        assert loaded_portfolio.allocation_id == portfolio_allocation.allocation_id
        assert loaded_portfolio.position_history[0].positions[0].symbol == "AAPL"
        assert loaded_portfolio.transaction_history[0].transaction_type == "DEPOSIT"
        assert isinstance(loaded_stock, StockAllocation)
        assert loaded_stock.allocation_id == stock_allocation.allocation_id
        assert loaded_stock.position_history[0].position.symbol == "AAPL"
        assert loaded_stock.transaction_history[0].transaction_type == "BUY"

        with pytest.raises(AllocationNotFoundError):
            allocation_repository.get_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=f"missing-allocation-{uuid4().hex}",
            )
    finally:
        for allocation in (portfolio_allocation, stock_allocation):
            _delete_allocation(
                allocation_repository=allocation_repository,
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
            )


def test_allocation_repository_typed_getters_validate_allocation_type(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    portfolio_allocation = _portfolio_allocation(cognito_user_id=cognito_user_id)
    stock_allocation = _stock_allocation(cognito_user_id=cognito_user_id)

    try:
        allocation_repository.set_allocation(portfolio_allocation)
        allocation_repository.set_allocation(stock_allocation)

        loaded_portfolio = allocation_repository.get_portfolio_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=portfolio_allocation.allocation_id,
        )
        loaded_stock = allocation_repository.get_stock_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        )

        assert loaded_portfolio.allocation_id == portfolio_allocation.allocation_id
        assert loaded_portfolio.portfolio_name == portfolio_allocation.portfolio_name
        assert loaded_stock.allocation_id == stock_allocation.allocation_id
        assert loaded_stock.symbol == stock_allocation.symbol

        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_stock_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=portfolio_allocation.allocation_id,
            )
        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_portfolio_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=stock_allocation.allocation_id,
            )
    finally:
        for allocation in (portfolio_allocation, stock_allocation):
            _delete_allocation(
                allocation_repository=allocation_repository,
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
            )


def test_allocation_repository_gets_portfolio_transaction_history_and_last_n(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation_with_two_histories(
        cognito_user_id=cognito_user_id,
    )

    try:
        allocation_repository.set_allocation(allocation)

        transaction_history = (
            allocation_repository.get_portfolio_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
            )
        )
        latest_one = (
            allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=1,
            )
        )
        latest_two = (
            allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=2,
            )
        )

        assert [snap.transaction_id for snap in transaction_history] == [
            snap.transaction_id for snap in allocation.transaction_history
        ]
        assert [snap.transaction_id for snap in latest_one] == [
            allocation.transaction_history[-1].transaction_id
        ]
        assert [snap.transaction_id for snap in latest_two] == [
            snap.transaction_id for snap in allocation.transaction_history
        ]
        with pytest.raises(ValueError):
            allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=0,
            )
        with pytest.raises(ValueError):
            allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=3,
            )
        with pytest.raises(AllocationNotFoundError):
            allocation_repository.get_portfolio_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                allocation_id=f"missing-allocation-{uuid4().hex}",
            )
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )


def test_allocation_repository_gets_stock_transaction_history_and_last_n(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _stock_allocation_with_two_histories(
        cognito_user_id=cognito_user_id,
    )

    try:
        allocation_repository.set_allocation(allocation)

        transaction_history = allocation_repository.get_stock_allocation_transaction_history(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        latest_one = allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
            n=1,
        )
        latest_two = allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
            n=2,
        )

        assert [snap.transaction_id for snap in transaction_history] == [
            snap.transaction_id for snap in allocation.transaction_history
        ]
        assert [snap.transaction_id for snap in latest_one] == [
            allocation.transaction_history[-1].transaction_id
        ]
        assert [snap.transaction_id for snap in latest_two] == [
            snap.transaction_id for snap in allocation.transaction_history
        ]
        with pytest.raises(ValueError):
            allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=0,
            )
        with pytest.raises(ValueError):
            allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=3,
            )
        with pytest.raises(AllocationNotFoundError):
            allocation_repository.get_stock_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                allocation_id=f"missing-allocation-{uuid4().hex}",
            )
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )


def test_allocation_repository_gets_portfolio_position_history_and_latest(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation_with_two_histories(
        cognito_user_id=cognito_user_id,
    )

    try:
        allocation_repository.set_allocation(allocation)

        position_history = allocation_repository.get_portfolio_allocation_position_history(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        latest = allocation_repository.get_latest_portfolio_allocation_position_snapshot(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )

        assert len(position_history) == 2
        assert [snapshot.timestamp for snapshot in position_history] == [
            snapshot.timestamp for snapshot in allocation.position_history
        ]
        assert latest.timestamp == allocation.position_history[-1].timestamp
        assert [position.symbol for position in latest.positions] == ["AAPL", "MSFT"]
        with pytest.raises(AllocationNotFoundError):
            allocation_repository.get_portfolio_allocation_position_history(
                cognito_user_id=cognito_user_id,
                allocation_id=f"missing-allocation-{uuid4().hex}",
            )
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )


def test_allocation_repository_gets_stock_position_history_and_latest(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _stock_allocation_with_two_histories(
        cognito_user_id=cognito_user_id,
    )

    try:
        allocation_repository.set_allocation(allocation)

        position_history = allocation_repository.get_stock_allocation_position_history(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        latest = allocation_repository.get_latest_stock_allocation_position_snapshot(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )

        assert len(position_history) == 2
        assert position_history[0].position.symbol == "AAPL"
        assert position_history[1].position is None
        assert latest.timestamp == allocation.position_history[-1].timestamp
        assert latest.position is None
        with pytest.raises(AllocationNotFoundError):
            allocation_repository.get_stock_allocation_position_history(
                cognito_user_id=cognito_user_id,
                allocation_id=f"missing-allocation-{uuid4().hex}",
            )
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )


def test_allocation_repository_getters_wrap_malformed_rows(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation_id = f"malformed-allocation-{uuid4().hex}"

    try:
        allocation_repository.allocation_table_client.put_item(
            {
                "cognito_user_id": cognito_user_id,
                "allocation_id": allocation_id,
                "allocation_type": "MODEL_PORTFOLIO",
                "portfolio_name": "Malformed Allocation",
                "total_cost_basis": "not-a-number",
                "open_positions": True,
                "open_orders": False,
                "position_history": [],
                "transaction_history": [{"transaction_id": "broken"}],
            }
        )

        for call in (
            lambda: allocation_repository.get_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            ),
            lambda: allocation_repository.get_allocation_total_cost_basis(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            ),
            lambda: allocation_repository.get_portfolio_allocation_position_history(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            ),
            lambda: allocation_repository.get_latest_portfolio_allocation_position_snapshot(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            ),
            lambda: allocation_repository.get_portfolio_allocation_transaction_history(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            ),
        ):
            with pytest.raises(AllocationUnprocessableEntityError):
                call()
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
        )


def test_allocation_repository_set_allocation_persists_stock_and_portfolio(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    portfolio_allocation = _portfolio_allocation(cognito_user_id=cognito_user_id)
    stock_allocation = _stock_allocation(cognito_user_id=cognito_user_id)

    try:
        allocation_repository.set_allocation(portfolio_allocation)
        allocation_repository.set_allocation(stock_allocation)

        loaded_portfolio = allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=portfolio_allocation.allocation_id,
        )
        loaded_stock = allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        )

        assert isinstance(loaded_portfolio, PortfolioAllocation)
        assert loaded_portfolio.allocation_id == portfolio_allocation.allocation_id
        assert loaded_portfolio.portfolio_name == portfolio_allocation.portfolio_name
        assert loaded_portfolio.position_history[-1].positions[0].symbol == "AAPL"
        assert isinstance(loaded_stock, StockAllocation)
        assert loaded_stock.allocation_id == stock_allocation.allocation_id
        assert loaded_stock.symbol == "AAPL"
        assert loaded_stock.position_history[-1].position.symbol == "AAPL"
    finally:
        for allocation in (portfolio_allocation, stock_allocation):
            _delete_allocation(
                allocation_repository=allocation_repository,
                cognito_user_id=cognito_user_id,
                allocation_id=allocation.allocation_id,
            )


def test_allocation_repository_set_allocation_wraps_invalid_serialization(
    allocation_repository: AllocationRepository,
) -> None:
    invalid_allocation = SimpleNamespace(
        cognito_user_id=_unique_user_id(),
        allocation_id=f"invalid-allocation-{uuid4().hex}",
    )

    with pytest.raises(AllocationUnprocessableEntityError) as exc_info:
        allocation_repository.set_allocation(invalid_allocation)

    assert exc_info.value.code == "ALLOCATION_UNPROCESSABLE_ENTITY"


def test_allocation_repository_calculates_portfolio_snapshot_current_value(
    allocation_repository: AllocationRepository,
) -> None:
    snapshot = _portfolio_position_snapshot()

    values, total_value, quotes = (
        allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
            position_snapshot=snapshot,
        )
    )
    expected_values = _expected_portfolio_values(snapshot=snapshot, quotes=quotes)

    assert values == pytest.approx(expected_values)
    assert total_value == pytest.approx(sum(expected_values.values()))
    assert set(quotes) == {"AAPL", "MSFT"}


def test_allocation_repository_calculates_portfolio_snapshot_current_weight(
    allocation_repository: AllocationRepository,
) -> None:
    snapshot = _portfolio_position_snapshot()

    weights, total_value, quotes = (
        allocation_repository.calculate_portfolio_allocation_position_snapshot_current_weight(
            position_snapshot=snapshot,
        )
    )
    expected_values = _expected_portfolio_values(snapshot=snapshot, quotes=quotes)
    expected_total = sum(expected_values.values())

    assert total_value == pytest.approx(expected_total)
    assert weights == pytest.approx(
        {
            symbol: value / expected_total
            for symbol, value in expected_values.items()
        }
    )


def test_allocation_repository_calculates_persisted_portfolio_allocation_snapshot(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _portfolio_allocation(cognito_user_id=cognito_user_id)

    try:
        allocation_repository.set_allocation(allocation)
        loaded = allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        snapshot = loaded.position_history[-1]

        values, total_value, quotes = (
            allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
                position_snapshot=snapshot,
            )
        )
        weights, weight_total_value, weight_quotes = (
            allocation_repository.calculate_portfolio_allocation_position_snapshot_current_weight(
                position_snapshot=snapshot,
            )
        )
        expected_values = _expected_portfolio_values(snapshot=snapshot, quotes=quotes)
        expected_total = sum(expected_values.values())

        assert values == pytest.approx(expected_values)
        assert total_value == pytest.approx(expected_total)
        assert weight_total_value == pytest.approx(expected_total)
        assert weight_quotes == pytest.approx(quotes)
        assert weights == pytest.approx(
            {
                symbol: value / expected_total
                for symbol, value in expected_values.items()
            }
        )
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )


def test_allocation_repository_calculates_long_stock_snapshot_current_value(
    allocation_repository: AllocationRepository,
) -> None:
    snapshot = _stock_position_snapshot(direction=1)

    position_value, current_price = (
        allocation_repository.calculate_stock_allocation_position_snapshot_current_value(
            position_snapshot=snapshot,
        )
    )
    expected_value = _expected_stock_value(
        position=snapshot.position,
        current_price=current_price,
    )

    assert position_value == pytest.approx(expected_value)
    assert current_price > 0


def test_allocation_repository_calculates_short_stock_snapshot_current_value(
    allocation_repository: AllocationRepository,
) -> None:
    snapshot = _stock_position_snapshot(
        direction=-1,
        filled_quantity=2.0,
        filled_avg_price=250.0,
    )

    position_value, current_price = (
        allocation_repository.calculate_stock_allocation_position_snapshot_current_value(
            position_snapshot=snapshot,
        )
    )
    expected_value = _expected_stock_value(
        position=snapshot.position,
        current_price=current_price,
    )

    assert position_value == pytest.approx(expected_value)
    assert current_price > 0


def test_allocation_repository_calculates_persisted_stock_allocation_snapshot(
    allocation_repository: AllocationRepository,
) -> None:
    cognito_user_id = _unique_user_id()
    allocation = _stock_allocation(cognito_user_id=cognito_user_id)

    try:
        allocation_repository.set_allocation(allocation)
        loaded = allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        snapshot = loaded.position_history[-1]

        position_value, current_price = (
            allocation_repository.calculate_stock_allocation_position_snapshot_current_value(
                position_snapshot=snapshot,
            )
        )
        expected_value = _expected_stock_value(
            position=snapshot.position,
            current_price=current_price,
        )

        assert position_value == pytest.approx(expected_value)
        assert current_price > 0
    finally:
        _delete_allocation(
            allocation_repository=allocation_repository,
            cognito_user_id=cognito_user_id,
            allocation_id=allocation.allocation_id,
        )

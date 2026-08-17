from datetime import datetime, timezone
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
from repository.allocation_repository import AllocationRepository
from repository.allocation_repository import (
    AllocationRepositoryError,
    AllocationNotFoundError,
    AllocationUnprocessableEntityError,
)


def _allocation(cognito_user_id: str) -> PortfolioAllocation:
    unique_suffix = uuid4().hex
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return PortfolioAllocation(
        allocation_id=f"repository-portfolio-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        position_history=[
            PortfolioAllocationPositionSnapshot(
                positions=[
                    PortfolioAllocationPosition(
                        symbol="AAPL",
                        filled_quantity=2,
                        direction=1,
                        filled_avg_price=100,
                    ),
                    PortfolioAllocationPosition(
                        symbol="MSFT",
                        filled_quantity=1,
                        direction=-1,
                        filled_avg_price=200,
                    ),
                ],
                timestamp=timestamp,
            )
        ],
        transaction_history=[
            PortfolioAllocationTransactionSnapshot(
                transaction_id=f"repository-transaction-{unique_suffix}",
                created_at=timestamp,
                updated_at=timestamp,
                requested_amount=500,
                transaction_type="DEPOSIT",
                status="FULLY_FILLED",
                filled_at=timestamp,
                number_orders=2,
                cost_basis=500,
                order_fill_percent=100,
            )
        ],
        total_cost_basis=500,
        open_positions=True,
        open_orders=False,
        allocation_type="MODEL_PORTFOLIO",
        portfolio_name=f"Repository Allocation Test {unique_suffix[:8]}",
    )


def _stock_allocation(cognito_user_id: str) -> StockAllocation:
    unique_suffix = uuid4().hex
    first_timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    second_timestamp = datetime(2024, 1, 2, tzinfo=timezone.utc)
    return StockAllocation(
        allocation_id=f"repository-stock-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        position_history=[
            StockAllocationPositionSnapshot(
                position=StockAllocationPosition(
                    symbol="AAPL",
                    filled_quantity=2,
                    direction=1,
                    filled_avg_price=100,
                ),
                timestamp=first_timestamp,
            )
        ],
        transaction_history=[
            StockAllocationTransactionSnapshot(
                transaction_id=f"repository-stock-transaction-1-{unique_suffix}",
                created_at=first_timestamp,
                updated_at=first_timestamp,
                requested_amount=100,
                transaction_type="BUY",
                status="FULLY_FILLED",
                filled_at=first_timestamp,
                number_orders=1,
                cost_basis=100,
                order_fill_percent=100,
            ),
            StockAllocationTransactionSnapshot(
                transaction_id=f"repository-stock-transaction-2-{unique_suffix}",
                created_at=second_timestamp,
                updated_at=second_timestamp,
                requested_amount=50,
                transaction_type="SELL",
                status="FULLY_FILLED",
                filled_at=second_timestamp,
                number_orders=1,
                cost_basis=50,
                order_fill_percent=100,
            ),
        ],
        total_cost_basis=100,
        open_positions=True,
        open_orders=False,
        allocation_type="STOCK",
        symbol="AAPL",
    )


@pytest.mark.integration
def test_allocation_repository_persists_and_loads_all_views(
    allocation_repository: AllocationRepository,
    test_user_1,
) -> None:
    """Persist a portfolio allocation and load each public repository view."""
    allocation = _allocation(test_user_1.cognito_user_id)

    try:
        allocation_repository.set_allocation(allocation)

        assert allocation_repository.is_exists_allocation_for_user(
            cognito_user_id=allocation.cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        loaded = allocation_repository.get_allocation(
            cognito_user_id=allocation.cognito_user_id,
            allocation_id=allocation.allocation_id,
        )
        assert loaded.allocation_id == allocation.allocation_id
        assert loaded.transaction_history[0].transaction_id == (
            allocation.transaction_history[0].transaction_id
        )
        assert allocation_repository.get_allocation_total_cost_basis(
            cognito_user_id=allocation.cognito_user_id,
            allocation_id=allocation.allocation_id,
        ) == 500.0
        assert allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
            cognito_user_id=allocation.cognito_user_id,
            allocation_id=allocation.allocation_id,
            n=1,
        )[0].transaction_id == allocation.transaction_history[0].transaction_id
        assert allocation_repository.get_latest_portfolio_allocation_position_snapshot(
            cognito_user_id=allocation.cognito_user_id,
            allocation_id=allocation.allocation_id,
        ).positions[0].symbol == "AAPL"
        assert allocation_repository.get_portfolio_allocation_transaction_history(
            cognito_user_id=allocation.cognito_user_id,
            allocation_id=allocation.allocation_id,
        )[0].transaction_id == allocation.transaction_history[0].transaction_id
        assert allocation_repository.get_allocations_by_cognito_user_id(
            cognito_user_id=allocation.cognito_user_id,
        )[0].portfolio_name == allocation.portfolio_name
    finally:
        allocation_repository.allocation_table_client.delete_item(
            key={
                "cognito_user_id": allocation.cognito_user_id,
                "allocation_id": allocation.allocation_id,
            }
        )


@pytest.mark.integration
def test_allocation_repository_calculates_values_and_weights(
    allocation_repository: AllocationRepository,
    test_user_1,
) -> None:
    """Calculate portfolio position values and weights using real latest prices."""
    snapshot = _allocation(test_user_1.cognito_user_id).position_history[0]

    values, total_value, quotes = allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
        position_snapshot=snapshot,
    )
    expected_values = {
        "AAPL": 2 * quotes["AAPL"],
        "MSFT": 1 * (200 + -1 * (quotes["MSFT"] - 200)),
    }
    assert values == expected_values
    assert total_value == sum(expected_values.values())

    weights, total_weight_value, _ = allocation_repository.calculate_portfolio_allocation_position_snapshot_current_weight(
        position_snapshot=snapshot,
    )
    assert weights == {
        symbol: value / total_value for symbol, value in expected_values.items()
    }
    assert total_weight_value == total_value


@pytest.mark.integration
def test_allocation_repository_calculates_stock_value(
    allocation_repository: AllocationRepository,
    test_user_1,
) -> None:
    """Calculate stock allocation value and handle an empty stock position snapshot."""
    stock_snapshot = _stock_allocation(test_user_1.cognito_user_id).position_history[0]

    position_value, current_price = (
        allocation_repository.calculate_stock_allocation_position_snapshot_current_value(
            position_snapshot=stock_snapshot,
        )
    )

    assert position_value == 2 * current_price
    assert current_price > 0

    empty_snapshot = StockAllocationPositionSnapshot(
        position=None,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    assert (
        allocation_repository.calculate_stock_allocation_position_snapshot_current_value(
            position_snapshot=empty_snapshot,
        )
        == (0.0, 0.0)
    )


@pytest.mark.integration
def test_allocation_repository_gets_last_n_stock_transaction_snapshots(
    allocation_repository: AllocationRepository,
    test_user_1,
) -> None:
    """Load stock transaction history and validate last-n snapshot bounds."""
    stock_allocation = _stock_allocation(test_user_1.cognito_user_id)

    try:
        allocation_repository.set_allocation(stock_allocation)

        transaction_history = allocation_repository.get_stock_allocation_transaction_history(
            cognito_user_id=stock_allocation.cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        )
        assert [snapshot.transaction_id for snapshot in transaction_history] == [
            snapshot.transaction_id
            for snapshot in stock_allocation.transaction_history
        ]

        last_snapshot = allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
            cognito_user_id=stock_allocation.cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
            n=1,
        )
        assert len(last_snapshot) == 1
        assert last_snapshot[0].transaction_id == (
            stock_allocation.transaction_history[-1].transaction_id
        )

        all_snapshots = allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
            cognito_user_id=stock_allocation.cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
            n=2,
        )
        assert [snapshot.transaction_id for snapshot in all_snapshots] == [
            snapshot.transaction_id
            for snapshot in stock_allocation.transaction_history
        ]

        with pytest.raises(ValueError):
            allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
                cognito_user_id=stock_allocation.cognito_user_id,
                allocation_id=stock_allocation.allocation_id,
                n=0,
            )
        with pytest.raises(ValueError):
            allocation_repository.get_n_last_stock_allocation_transaction_snapshots(
                cognito_user_id=stock_allocation.cognito_user_id,
                allocation_id=stock_allocation.allocation_id,
                n=3,
            )
    finally:
        allocation_repository.allocation_table_client.delete_item(
            key={
                "cognito_user_id": stock_allocation.cognito_user_id,
                "allocation_id": stock_allocation.allocation_id,
            }
        )


@pytest.mark.integration
def test_allocation_repository_allocation_type_accessors_validate_type(
    allocation_repository: AllocationRepository,
    test_user_1,
) -> None:
    """Load stock and portfolio allocations through typed accessors and reject mismatches."""
    portfolio_allocation = _allocation(test_user_1.cognito_user_id)
    stock_allocation = _stock_allocation(test_user_1.cognito_user_id)

    try:
        allocation_repository.set_allocation(portfolio_allocation)
        allocation_repository.set_allocation(stock_allocation)

        loaded_stock = allocation_repository.get_stock_allocation(
            cognito_user_id=stock_allocation.cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        )
        assert loaded_stock.allocation_id == stock_allocation.allocation_id
        assert loaded_stock.symbol == stock_allocation.symbol
        assert allocation_repository.get_stock_allocation_position_history(
            cognito_user_id=stock_allocation.cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        )[0].position.symbol == stock_allocation.symbol
        assert allocation_repository.get_latest_stock_allocation_position_snapshot(
            cognito_user_id=stock_allocation.cognito_user_id,
            allocation_id=stock_allocation.allocation_id,
        ).position.symbol == stock_allocation.symbol

        loaded_portfolio = allocation_repository.get_portfolio_allocation(
            cognito_user_id=portfolio_allocation.cognito_user_id,
            allocation_id=portfolio_allocation.allocation_id,
        )
        assert loaded_portfolio.allocation_id == portfolio_allocation.allocation_id
        assert loaded_portfolio.portfolio_name == portfolio_allocation.portfolio_name

        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_stock_allocation(
                cognito_user_id=portfolio_allocation.cognito_user_id,
                allocation_id=portfolio_allocation.allocation_id,
            )
        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_portfolio_allocation(
                cognito_user_id=stock_allocation.cognito_user_id,
                allocation_id=stock_allocation.allocation_id,
            )
    finally:
        for allocation in (portfolio_allocation, stock_allocation):
            allocation_repository.allocation_table_client.delete_item(
                key={
                    "cognito_user_id": allocation.cognito_user_id,
                    "allocation_id": allocation.allocation_id,
                }
            )


@pytest.mark.integration
def test_allocation_repository_missing_and_invalid_n_paths(
    allocation_repository: AllocationRepository,
    test_user_1,
) -> None:
    """Raise expected errors for missing allocations and invalid portfolio snapshot counts."""
    allocation = _allocation(test_user_1.cognito_user_id)
    missing_cognito_user_id = f"missing-user-{uuid4()}"
    missing_portfolio_id = f"missing-portfolio-{uuid4()}"

    for call in (
        lambda: allocation_repository.get_allocation(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: allocation_repository.get_allocation_total_cost_basis(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: allocation_repository.get_portfolio_allocation_position_history(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: allocation_repository.get_latest_portfolio_allocation_position_snapshot(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: allocation_repository.get_portfolio_allocation_transaction_history(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
    ):
        with pytest.raises(AllocationNotFoundError):
            call()

    assert allocation_repository.get_allocations_by_cognito_user_id(
        missing_cognito_user_id
    ) == []

    try:
        allocation_repository.set_allocation(allocation)

        with pytest.raises(ValueError):
            allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=allocation.cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=0,
            )
        with pytest.raises(ValueError):
            allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=allocation.cognito_user_id,
                allocation_id=allocation.allocation_id,
                n=2,
            )
    finally:
        allocation_repository.allocation_table_client.delete_item(
            key={
                "cognito_user_id": allocation.cognito_user_id,
                "allocation_id": allocation.allocation_id,
            }
        )


@pytest.mark.integration
def test_allocation_repository_empty_and_zero_value_snapshots(
    allocation_repository: AllocationRepository,
) -> None:
    """Handle empty portfolio snapshots and zero-value weight calculations."""
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(AllocationRepositoryError):
        allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(
            PortfolioAllocationPositionSnapshot(
                positions=[],
                timestamp=timestamp,
            )
        )

    snapshot = PortfolioAllocationPositionSnapshot(
        positions=[
            PortfolioAllocationPosition(
                symbol="AAPL",
                filled_quantity=0,
                direction=1,
                filled_avg_price=100,
            )
        ],
        timestamp=timestamp,
    )
    weights, total_value, quotes = (
        allocation_repository.calculate_portfolio_allocation_position_snapshot_current_weight(snapshot)
    )
    assert weights == {"AAPL": 0.0}
    assert total_value == 0.0
    assert "AAPL" in quotes


@pytest.mark.integration
def test_allocation_repository_malformed_items_are_wrapped(
    allocation_repository: AllocationRepository,
) -> None:
    """Wrap malformed DynamoDB allocation items in unprocessable entity errors."""
    malformed_cognito_user_id = f"malformed-user-{uuid4()}"
    malformed_portfolio_id = f"malformed-portfolio-{uuid4()}"

    try:
        allocation_repository.allocation_table_client.put_item(
            {
                "cognito_user_id": malformed_cognito_user_id,
                "allocation_id": malformed_portfolio_id,
                "position_history": [],
                "transaction_history": [{"transaction_id": "broken"}],
                "total_cost_basis": "not-a-number",
                "allocation_type": "MODEL_PORTFOLIO",
                "portfolio_name": "Malformed Allocation",
            }
        )

        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_portfolio_allocation_position_history(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_latest_portfolio_allocation_position_snapshot(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_allocation_total_cost_basis(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
        with pytest.raises(AllocationUnprocessableEntityError):
            allocation_repository.get_allocation(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
    finally:
        allocation_repository.allocation_table_client.delete_item(
            key={
                "cognito_user_id": malformed_cognito_user_id,
                "allocation_id": malformed_portfolio_id,
            }
        )

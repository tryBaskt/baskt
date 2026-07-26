from datetime import datetime, timezone
from uuid import uuid4

import pytest

from domain.portfolio_allocation_domain import (
    PortfolioAllocation,
    PortfolioAllocationPosition,
    PortfolioAllocationPositionSnapshot,
    PortfolioAllocationTransactionSnapshot,
)
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.portfolio_allocation_repository import (
    PortfolioAllocationInternalServerError,
    PortfolioAllocationNotFoundError,
    PortfolioAllocationUnprocessableEntityError,
)


def _allocation() -> PortfolioAllocation:
    unique_suffix = uuid4().hex
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return PortfolioAllocation(
        portfolio_id=f"repository-portfolio-{unique_suffix}",
        cognito_user_id=f"repository-user-{unique_suffix}",
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
        portfolio_allocation_type="MODEL_PORTFOLIO",
        portfolio_name=f"Repository Allocation Test {unique_suffix[:8]}",
    )


@pytest.mark.integration
def test_portfolio_allocation_repository_persists_and_loads_all_views(
    portfolio_allocation_repository: PortfolioAllocationRepository,
) -> None:
    allocation = _allocation()

    try:
        portfolio_allocation_repository.set_portfolio_allocation(allocation)

        assert portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(
            cognito_user_id=allocation.cognito_user_id,
            portfolio_id=allocation.portfolio_id,
        )
        loaded = portfolio_allocation_repository.get_portfolio_allocation(
            cognito_user_id=allocation.cognito_user_id,
            portfolio_id=allocation.portfolio_id,
        )
        assert loaded.portfolio_id == allocation.portfolio_id
        assert loaded.transaction_history[0].transaction_id == (
            allocation.transaction_history[0].transaction_id
        )
        assert portfolio_allocation_repository.get_portfolio_allocation_total_cost_basis(
            cognito_user_id=allocation.cognito_user_id,
            portfolio_id=allocation.portfolio_id,
        ) == 500.0
        assert portfolio_allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
            cognito_user_id=allocation.cognito_user_id,
            portfolio_id=allocation.portfolio_id,
            n=1,
        )[0].transaction_id == allocation.transaction_history[0].transaction_id
        assert portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(
            cognito_user_id=allocation.cognito_user_id,
            portfolio_id=allocation.portfolio_id,
        ).positions[0].symbol == "AAPL"
        assert portfolio_allocation_repository.get_portfolio_allocations_by_cognito_user_id(
            cognito_user_id=allocation.cognito_user_id,
        )[0].portfolio_name == allocation.portfolio_name
    finally:
        portfolio_allocation_repository.portfolio_allocation_table_client.delete_item(
            key={
                "cognito_user_id": allocation.cognito_user_id,
                "portfolio_id": allocation.portfolio_id,
            }
        )


@pytest.mark.integration
def test_portfolio_allocation_repository_calculates_values_and_weights(
    portfolio_allocation_repository: PortfolioAllocationRepository,
) -> None:
    snapshot = _allocation().position_history[0]

    values, total_value, quotes = portfolio_allocation_repository.calculate_positions_current_value(
        portfolio_allocation_position_snapshot=snapshot,
    )
    expected_values = {
        "AAPL": 2 * quotes["AAPL"],
        "MSFT": 1 * (200 + -1 * (quotes["MSFT"] - 200)),
    }
    assert values == expected_values
    assert total_value == sum(expected_values.values())

    weights, total_weight_value, _ = portfolio_allocation_repository.calculate_positions_current_weight(
        portfolio_allocation_position_snapshot=snapshot,
    )
    assert weights == {
        symbol: value / total_value for symbol, value in expected_values.items()
    }
    assert total_weight_value == total_value


@pytest.mark.integration
def test_portfolio_allocation_repository_missing_and_invalid_n_paths(
    portfolio_allocation_repository: PortfolioAllocationRepository,
) -> None:
    allocation = _allocation()
    missing_cognito_user_id = f"missing-user-{uuid4()}"
    missing_portfolio_id = f"missing-portfolio-{uuid4()}"

    for call in (
        lambda: portfolio_allocation_repository.get_portfolio_allocation(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: portfolio_allocation_repository.get_portfolio_allocation_total_cost_basis(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: portfolio_allocation_repository.get_portfolio_allocation_position_snapshots(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
        lambda: portfolio_allocation_repository.get_portfolio_allocation_transaction_history(
            missing_cognito_user_id,
            missing_portfolio_id,
        ),
    ):
        with pytest.raises(PortfolioAllocationNotFoundError):
            call()

    assert portfolio_allocation_repository.get_portfolio_allocations_by_cognito_user_id(
        missing_cognito_user_id
    ) == []

    try:
        portfolio_allocation_repository.set_portfolio_allocation(allocation)

        with pytest.raises(ValueError):
            portfolio_allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=allocation.cognito_user_id,
                portfolio_id=allocation.portfolio_id,
                n=0,
            )
        with pytest.raises(ValueError):
            portfolio_allocation_repository.get_n_last_portfolio_allocation_transaction_snapshots(
                cognito_user_id=allocation.cognito_user_id,
                portfolio_id=allocation.portfolio_id,
                n=2,
            )
    finally:
        portfolio_allocation_repository.portfolio_allocation_table_client.delete_item(
            key={
                "cognito_user_id": allocation.cognito_user_id,
                "portfolio_id": allocation.portfolio_id,
            }
        )


@pytest.mark.integration
def test_portfolio_allocation_repository_empty_and_zero_value_snapshots(
    portfolio_allocation_repository: PortfolioAllocationRepository,
) -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(PortfolioAllocationInternalServerError):
        portfolio_allocation_repository.calculate_positions_current_value(
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
        portfolio_allocation_repository.calculate_positions_current_weight(snapshot)
    )
    assert weights == {"AAPL": 0.0}
    assert total_value == 0.0
    assert "AAPL" in quotes


@pytest.mark.integration
def test_portfolio_allocation_repository_malformed_items_are_wrapped(
    portfolio_allocation_repository: PortfolioAllocationRepository,
) -> None:
    malformed_cognito_user_id = f"malformed-user-{uuid4()}"
    malformed_portfolio_id = f"malformed-portfolio-{uuid4()}"

    try:
        portfolio_allocation_repository.portfolio_allocation_table_client.put_item(
            {
                "cognito_user_id": malformed_cognito_user_id,
                "portfolio_id": malformed_portfolio_id,
                "position_history": [],
                "transaction_history": [{"transaction_id": "broken"}],
                "total_cost_basis": "not-a-number",
                "portfolio_allocation_type": "MODEL_PORTFOLIO",
                "portfolio_name": "Malformed Allocation",
            }
        )

        with pytest.raises(PortfolioAllocationUnprocessableEntityError):
            portfolio_allocation_repository.get_portfolio_allocation_position_snapshots(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
        with pytest.raises(PortfolioAllocationUnprocessableEntityError):
            portfolio_allocation_repository.get_latest_portfolio_allocation_position_snapshot(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
        with pytest.raises(PortfolioAllocationUnprocessableEntityError):
            portfolio_allocation_repository.get_portfolio_allocation_total_cost_basis(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
        with pytest.raises(PortfolioAllocationUnprocessableEntityError):
            portfolio_allocation_repository.get_portfolio_allocation(
                malformed_cognito_user_id,
                malformed_portfolio_id,
            )
    finally:
        portfolio_allocation_repository.portfolio_allocation_table_client.delete_item(
            key={
                "cognito_user_id": malformed_cognito_user_id,
                "portfolio_id": malformed_portfolio_id,
            }
        )

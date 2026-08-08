from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alpaca.trading.enums import OrderClass, OrderSide, OrderStatus, TimeInForce
from alpaca.trading.models import Order

from repository.order_repository import (
    OrderNotFoundError,
    OrderRepository,
    OrderUnprocessableEntityError,
)


def _order_item(
    *,
    transaction_id: str,
    order_id: str,
    cognito_user_id: str,
    allocation_id: str,
    portfolio_owner_cognito_user_id: str,
    status: str = "FILLED",
) -> dict:
    return {
        "transaction_id": transaction_id,
        "order_id": order_id,
        "cognito_user_id": cognito_user_id,
        "allocation_id": allocation_id,
        "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:01:00+00:00",
        "filled_at": "2024-01-01T00:02:00+00:00",
        "symbol": "AAPL",
        "notional": "100",
        "qty": "1",
        "filled_qty": "1",
        "filled_avg_price": "100",
        "side": "BUY",
        "status": status,
    }


@pytest.mark.integration
def test_order_repository_normalizes_and_filters_orders(
    order_repository: OrderRepository,
    test_user_1,
    test_user_2,
) -> None:
    unique_suffix = uuid4().hex
    transaction_id = f"repository-transaction-{unique_suffix}"
    cognito_user_id = test_user_1.cognito_user_id
    allocation_id = f"repository-allocation-{unique_suffix}"
    owner_id = test_user_2.cognito_user_id

    filled_item = _order_item(
        transaction_id=transaction_id,
        order_id=f"filled-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
        portfolio_owner_cognito_user_id=owner_id,
        status="FILLED",
    )
    open_item = _order_item(
        transaction_id=transaction_id,
        order_id=f"open-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
        portfolio_owner_cognito_user_id=owner_id,
        status="NEW",
    )

    try:
        order_repository.order_table_client.put_item(filled_item)
        order_repository.order_table_client.put_item(open_item)

        orders = order_repository.get_orders_by_transaction(transaction_id)
        assert {order["order_id"] for order in orders} == {
            filled_item["order_id"],
            open_item["order_id"],
        }
        assert orders[0]["created_at"] == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert orders[0]["qty"] == 1.0
        assert order_repository.get_unfilled_orders_by_transaction(transaction_id)[0][
            "order_id"
        ] == open_item["order_id"]
        assert order_repository.get_unfilled_orders_by_cognito_user_id(
            cognito_user_id
        )[0]["order_id"] == open_item["order_id"]
        assert order_repository.get_unfilled_orders_by_allocation_id(allocation_id)[0][
            "order_id"
        ] == open_item["order_id"]
    finally:
        for item in (filled_item, open_item):
            order_repository.order_table_client.delete_item(
                key={
                    "transaction_id": item["transaction_id"],
                    "order_id": item["order_id"],
                }
            )


@pytest.mark.integration
def test_order_repository_put_orders_and_missing_records(
    order_repository: OrderRepository,
    test_user_1,
    test_user_2,
) -> None:
    unique_suffix = uuid4().hex
    transaction_id = f"repository-transaction-{unique_suffix}"
    order_id = f"alpaca-order-{unique_suffix}"
    order = Order(
        id=uuid4(),
        client_order_id=f"client-order-{unique_suffix}",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        submitted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        filled_at=None,
        symbol="AAPL",
        notional=None,
        qty=1,
        filled_qty=None,
        filled_avg_price=None,
        order_class=OrderClass.SIMPLE,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        status=OrderStatus.NEW,
        extended_hours=False,
    )
    order_id = str(order.id)

    try:
        assert order_repository.put_orders(
            allocation_id=f"repository-allocation-{unique_suffix}",
            cognito_user_id=test_user_1.cognito_user_id,
            transaction_id=transaction_id,
            orders=[order],
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
        ) == 1
        stored = order_repository.order_table_client.get_item(
            key={"transaction_id": transaction_id, "order_id": order_id}
        )
        assert stored["order_id"] == order_id

        with pytest.raises(OrderNotFoundError):
            order_repository.get_orders_by_transaction(f"missing-{uuid4().hex}")
    finally:
        order_repository.order_table_client.delete_item(
            key={"transaction_id": transaction_id, "order_id": order_id}
        )


def test_order_repository_parse_errors_are_wrapped(
    order_repository: OrderRepository,
) -> None:
    with pytest.raises(OrderUnprocessableEntityError):
        order_repository._norm_data_types([{"transaction_id": "broken"}])


@pytest.mark.integration
def test_order_repository_missing_portfolio_and_empty_paths(
    order_repository: OrderRepository,
    test_user_1,
    test_user_2,
) -> None:
    assert order_repository.put_orders(
        allocation_id=f"repository-allocation-{uuid4()}",
        cognito_user_id=test_user_1.cognito_user_id,
        transaction_id=f"repository-transaction-{uuid4()}",
        orders=[],
        portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
    ) == 0

    with pytest.raises(OrderNotFoundError):
        order_repository.get_orders_by_allocation(
            cognito_user_id=f"missing-user-{uuid4()}",
            allocation_id=f"missing-allocation-{uuid4()}",
        )

    assert order_repository.get_unfilled_orders_by_cognito_user_id(
        f"missing-user-{uuid4()}"
    ) == []
    assert order_repository.get_unfilled_orders_by_allocation_id(
        f"missing-allocation-{uuid4()}"
    ) == []
    assert order_repository.get_allocation_ids_of_unfilled_orders(
        f"missing-user-{uuid4()}"
    ) == []


@pytest.mark.integration
def test_order_repository_allocation_ids_of_unfilled_orders_are_deduped(
    order_repository: OrderRepository,
    test_user_1,
    test_user_2,
) -> None:
    unique_suffix = uuid4().hex
    cognito_user_id = test_user_1.cognito_user_id
    allocation_id = f"repository-allocation-{unique_suffix}"
    owner_id = test_user_2.cognito_user_id
    filled_item = _order_item(
        transaction_id=f"filled-transaction-{unique_suffix}",
        order_id=f"filled-order-{unique_suffix}",
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
        portfolio_owner_cognito_user_id=owner_id,
        status="FILLED",
    )
    open_items = [
        _order_item(
            transaction_id=f"open-transaction-{unique_suffix}-{index}",
            order_id=f"open-order-{unique_suffix}-{index}",
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
            portfolio_owner_cognito_user_id=owner_id,
            status=status,
        )
        for index, status in enumerate(("NEW", "PARTIALLY_FILLED"))
    ]

    try:
        for item in [filled_item, *open_items]:
            order_repository.order_table_client.put_item(item)

        assert order_repository.get_allocation_ids_of_unfilled_orders(
            cognito_user_id
        ) == [(allocation_id, owner_id)]
    finally:
        for item in [filled_item, *open_items]:
            order_repository.order_table_client.delete_item(
                key={
                    "transaction_id": item["transaction_id"],
                    "order_id": item["order_id"],
                }
            )

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

import pytest
from alpaca.trading.enums import OrderClass, OrderSide, OrderStatus, TimeInForce
from alpaca.trading.models import Order

from repository.order_repository import (
    OrderBadGatewayError,
    OrderNotFoundError,
    OrderRepository,
    OrderUnprocessableEntityError,
)


"""
These tests exercise OrderRepository behavior directly. They are repository
tests, not larger trade execution workflow tests.

Coverage goals:
- _norm_data_types(): normalize complete stored DynamoDB order records into
  application types, preserve order identity fields, parse timestamps, convert
  numeric quantities/prices, and support nullable Alpaca fill fields.
- _norm_data_types() errors: wrap missing required fields, malformed timestamps,
  and invalid numeric values in OrderUnprocessableEntityError.
- put_orders(): persist multiple Alpaca Order models, return the written count,
  store portfolio owner context, and return zero for an empty order list.
- put_orders() conversion errors: wrap invalid Alpaca order shapes in
  OrderUnprocessableEntityError before any lower-level write failure is needed.
- get_orders_by_transaction(): load and normalize transaction-scoped orders and
  raise OrderNotFoundError for missing transactions.
- get_orders_by_allocation(): query the cognito_user_id/allocation_id index,
  scope results by both user and allocation, and raise OrderNotFoundError for
  missing user/allocation pairs.
- get_unfilled_orders_by_transaction(): exclude FILLED orders
  case-insensitively, retain other statuses, and propagate missing transaction
  OrderNotFoundError.
- get_unfilled_orders_by_cognito_user_id(): return normalized non-filled orders
  and return an empty list for users with no orders.
- get_unfilled_orders_by_allocation_id(): scan by allocation ID, return
  normalized non-filled orders, and return an empty list for missing
  allocations.
- get_allocation_ids_of_unfilled_orders(): return unique allocation/portfolio
  owner pairs for orders whose status is not FILLED, including distinct owners
  for the same allocation ID.
- order repository exceptions: expose stable error codes and useful contextual
  messages.

Lower-level dependency-failure scenarios such as DynamoDB query, scan, and
batch-writer failures are intentionally excluded because they require mock
resources to simulate upstream failures.
"""


pytestmark = pytest.mark.integration


def _order_item(
    *,
    transaction_id: str,
    order_id: str,
    cognito_user_id: str,
    allocation_id: str,
    portfolio_owner_cognito_user_id: str | None,
    status: str = "FILLED",
    created_at: str | None = "2024-01-01T00:00:00+00:00",
    updated_at: str | None = "2024-01-01T00:01:00+00:00",
    filled_at: str | None = "2024-01-01T00:02:00+00:00",
    notional: str | None = "100",
    qty: str = "1",
    filled_qty: str | None = "1",
    filled_avg_price: str | None = "100",
    side: str = "BUY",
) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "order_id": order_id,
        "cognito_user_id": cognito_user_id,
        "allocation_id": allocation_id,
        "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "filled_at": filled_at,
        "symbol": "AAPL",
        "notional": notional,
        "qty": qty,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "side": side,
        "status": status,
    }


def _alpaca_order(
    *,
    order_id: str | None = None,
    symbol: str = "AAPL",
    notional: float | None = None,
    qty: float | None = 1,
    filled_qty: float | None = None,
    filled_avg_price: float | None = None,
    side: OrderSide = OrderSide.BUY,
    status: OrderStatus = OrderStatus.NEW,
) -> Order:
    return Order(
        id=order_id or uuid4(),
        client_order_id=f"client-order-{uuid4().hex}",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        submitted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        filled_at=None,
        symbol=symbol,
        notional=notional,
        qty=qty,
        filled_qty=filled_qty,
        filled_avg_price=filled_avg_price,
        order_class=OrderClass.SIMPLE,
        side=side,
        time_in_force=TimeInForce.DAY,
        status=status,
        extended_hours=False,
    )


def _delete_order_item(
    *,
    order_repository: OrderRepository,
    transaction_id: str,
    order_id: str,
) -> None:
    order_repository.order_table_client.delete_item(
        key={
            "transaction_id": transaction_id,
            "order_id": order_id,
        }
    )


def _wait_for_order(
    *,
    load_orders: Callable[[], list[dict[str, Any]]],
    order_id: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        try:
            orders = load_orders()
        except OrderNotFoundError:
            orders = []

        for order in orders:
            if order["order_id"] == order_id:
                return order
        sleep(0.25)
    raise AssertionError(f"Order '{order_id}' was not returned.")


def _wait_for_allocation_owner_pairs(
    *,
    load_pairs: Callable[[], list[tuple[str, str | None]]],
    expected_pairs: set[tuple[str, str | None]],
    timeout_seconds: float = 10.0,
) -> list[tuple[str, str | None]]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        pairs = load_pairs()
        if expected_pairs.issubset(set(pairs)):
            return pairs
        sleep(0.25)
    raise AssertionError(f"Allocation/owner pairs {expected_pairs} were not returned.")


def test_order_repository_normalizes_complete_order_records(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Normalize stored DynamoDB order values into application types."""
    item = _order_item(
        transaction_id=f"repository-transaction-{uuid4().hex}",
        order_id=f"order-{uuid4().hex}",
        cognito_user_id=test_user_1.cognito_user_id,
        allocation_id=f"repository-allocation-{uuid4().hex}",
        portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
    )

    [order] = order_repository._norm_data_types([item])

    assert order["transaction_id"] == item["transaction_id"]
    assert order["order_id"] == item["order_id"]
    assert order["cognito_user_id"] == test_user_1.cognito_user_id
    assert order["allocation_id"] == item["allocation_id"]
    assert order["portfolio_owner_cognito_user_id"] == test_user_2.cognito_user_id
    assert order["created_at"] == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert order["updated_at"] == datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc)
    assert order["filled_at"] == datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc)
    assert order["symbol"] == "AAPL"
    assert order["notional"] == "100"
    assert order["qty"] == 1.0
    assert order["filled_qty"] == 1.0
    assert order["filled_avg_price"] == 100.0
    assert order["side"] == "BUY"
    assert order["status"] == "FILLED"


def test_order_repository_normalizes_nullable_order_fields(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    """Normalize optional order fields when Alpaca has not filled an order."""
    item = _order_item(
        transaction_id=f"repository-transaction-{uuid4().hex}",
        order_id=f"order-{uuid4().hex}",
        cognito_user_id=test_user_1.cognito_user_id,
        allocation_id=f"repository-allocation-{uuid4().hex}",
        portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
        status="NEW",
        updated_at=None,
        filled_at=None,
        notional=None,
        filled_qty=None,
        filled_avg_price=None,
    )

    [order] = order_repository._norm_data_types([item])

    assert order["updated_at"] is None
    assert order["filled_at"] is None
    assert order["notional"] is None
    assert order["filled_qty"] is None
    assert order["filled_avg_price"] is None
    assert order["qty"] == 1.0
    assert order["status"] == "NEW"


@pytest.mark.parametrize(
    "item",
    [
        {"transaction_id": "broken"},
        _order_item(
            transaction_id="bad-timestamp",
            order_id="bad-timestamp-order",
            cognito_user_id="user",
            allocation_id="allocation",
            portfolio_owner_cognito_user_id="owner",
            created_at="not-a-timestamp",
        ),
        _order_item(
            transaction_id="bad-qty",
            order_id="bad-qty-order",
            cognito_user_id="user",
            allocation_id="allocation",
            portfolio_owner_cognito_user_id="owner",
            qty="not-a-number",
        ),
    ],
)
def test_order_repository_wraps_malformed_stored_records(
    order_repository: OrderRepository,
    item: dict[str, Any],
) -> None:
    with pytest.raises(OrderUnprocessableEntityError) as exc_info:
        order_repository._norm_data_types([item])

    assert exc_info.value.code == "ORDER_UNPROCESSABLE_ENTITY"


def test_order_repository_put_orders_persists_multiple_alpaca_orders(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    unique_suffix = uuid4().hex
    transaction_id = f"repository-transaction-{unique_suffix}"
    allocation_id = f"repository-allocation-{unique_suffix}"
    orders = [
        _alpaca_order(
            symbol="AAPL",
            qty=2,
            status=OrderStatus.NEW,
        ),
        _alpaca_order(
            symbol="MSFT",
            qty=3,
            filled_qty=3,
            filled_avg_price=100,
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
        ),
    ]
    order_ids = [str(order.id) for order in orders]

    try:
        count = order_repository.put_orders(
            allocation_id=allocation_id,
            cognito_user_id=test_user_1.cognito_user_id,
            transaction_id=transaction_id,
            orders=orders,
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
        )

        assert count == 2
        stored_orders = order_repository.get_orders_by_transaction(transaction_id)
        assert {order["order_id"] for order in stored_orders} == set(order_ids)
        assert {order["symbol"] for order in stored_orders} == {"AAPL", "MSFT"}
        assert {
            order["portfolio_owner_cognito_user_id"] for order in stored_orders
        } == {test_user_2.cognito_user_id}
    finally:
        for order_id in order_ids:
            _delete_order_item(
                order_repository=order_repository,
                transaction_id=transaction_id,
                order_id=order_id,
            )


def test_order_repository_put_orders_allows_empty_order_list(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    assert (
        order_repository.put_orders(
            allocation_id=f"repository-allocation-{uuid4().hex}",
            cognito_user_id=test_user_1.cognito_user_id,
            transaction_id=f"repository-transaction-{uuid4().hex}",
            orders=[],
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
        )
        == 0
    )


@pytest.mark.parametrize(
    "bad_order",
    [
        SimpleNamespace(),
        SimpleNamespace(
            id=uuid4(),
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            filled_at=None,
            symbol="AAPL",
            notional=None,
            qty="not-a-number",
            filled_qty=None,
            filled_avg_price=None,
            side=SimpleNamespace(name="BUY"),
            status=SimpleNamespace(name="NEW"),
        ),
        SimpleNamespace(
            id=uuid4(),
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            filled_at=None,
            symbol="AAPL",
            notional=None,
            qty=1,
            filled_qty=None,
            filled_avg_price=None,
            side="BUY",
            status=SimpleNamespace(name="NEW"),
        ),
    ],
)
def test_order_repository_wraps_invalid_alpaca_order_conversion(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
    bad_order: Any,
) -> None:
    with pytest.raises(OrderUnprocessableEntityError) as exc_info:
        order_repository.put_orders(
            allocation_id=f"repository-allocation-{uuid4().hex}",
            cognito_user_id=test_user_1.cognito_user_id,
            transaction_id=f"repository-transaction-{uuid4().hex}",
            orders=[bad_order],
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
        )

    assert exc_info.value.code == "ORDER_UNPROCESSABLE_ENTITY"


def test_order_repository_get_orders_by_transaction_and_missing_transaction(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    unique_suffix = uuid4().hex
    transaction_id = f"repository-transaction-{unique_suffix}"
    item = _order_item(
        transaction_id=transaction_id,
        order_id=f"order-{unique_suffix}",
        cognito_user_id=test_user_1.cognito_user_id,
        allocation_id=f"repository-allocation-{unique_suffix}",
        portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
    )

    try:
        order_repository.order_table_client.put_item(item)

        orders = order_repository.get_orders_by_transaction(transaction_id)

        assert [order["order_id"] for order in orders] == [item["order_id"]]
        with pytest.raises(OrderNotFoundError) as exc_info:
            order_repository.get_orders_by_transaction(f"missing-{uuid4().hex}")
        assert exc_info.value.code == "ORDER_NOT_FOUND"
    finally:
        _delete_order_item(
            order_repository=order_repository,
            transaction_id=transaction_id,
            order_id=item["order_id"],
        )


def test_order_repository_get_orders_by_allocation_scopes_by_user_and_allocation(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    unique_suffix = uuid4().hex
    allocation_id = f"repository-allocation-{unique_suffix}"
    owner_id = test_user_2.cognito_user_id
    matching_item = _order_item(
        transaction_id=f"matching-transaction-{unique_suffix}",
        order_id=f"matching-order-{unique_suffix}",
        cognito_user_id=test_user_1.cognito_user_id,
        allocation_id=allocation_id,
        portfolio_owner_cognito_user_id=owner_id,
    )
    other_user_item = _order_item(
        transaction_id=f"other-user-transaction-{unique_suffix}",
        order_id=f"other-user-order-{unique_suffix}",
        cognito_user_id=test_user_2.cognito_user_id,
        allocation_id=allocation_id,
        portfolio_owner_cognito_user_id=owner_id,
    )
    other_allocation_item = _order_item(
        transaction_id=f"other-allocation-transaction-{unique_suffix}",
        order_id=f"other-allocation-order-{unique_suffix}",
        cognito_user_id=test_user_1.cognito_user_id,
        allocation_id=f"other-allocation-{unique_suffix}",
        portfolio_owner_cognito_user_id=owner_id,
    )

    try:
        for item in (matching_item, other_user_item, other_allocation_item):
            order_repository.order_table_client.put_item(item)

        matching_order = _wait_for_order(
            load_orders=lambda: order_repository.get_orders_by_allocation(
                cognito_user_id=test_user_1.cognito_user_id,
                allocation_id=allocation_id,
            ),
            order_id=matching_item["order_id"],
        )
        orders = order_repository.get_orders_by_allocation(
            cognito_user_id=test_user_1.cognito_user_id,
            allocation_id=allocation_id,
        )

        assert matching_order["order_id"] == matching_item["order_id"]
        assert {order["order_id"] for order in orders} == {
            matching_item["order_id"]
        }
        with pytest.raises(OrderNotFoundError):
            order_repository.get_orders_by_allocation(
                cognito_user_id=f"missing-user-{uuid4().hex}",
                allocation_id=f"missing-allocation-{uuid4().hex}",
            )
    finally:
        for item in (matching_item, other_user_item, other_allocation_item):
            _delete_order_item(
                order_repository=order_repository,
                transaction_id=item["transaction_id"],
                order_id=item["order_id"],
            )


def test_order_repository_unfilled_orders_by_transaction_filter_statuses(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    unique_suffix = uuid4().hex
    transaction_id = f"repository-transaction-{unique_suffix}"
    items = [
        _order_item(
            transaction_id=transaction_id,
            order_id=f"filled-upper-{unique_suffix}",
            cognito_user_id=test_user_1.cognito_user_id,
            allocation_id=f"repository-allocation-{unique_suffix}",
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="FILLED",
        ),
        _order_item(
            transaction_id=transaction_id,
            order_id=f"filled-lower-{unique_suffix}",
            cognito_user_id=test_user_1.cognito_user_id,
            allocation_id=f"repository-allocation-{unique_suffix}",
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="filled",
        ),
        _order_item(
            transaction_id=transaction_id,
            order_id=f"new-{unique_suffix}",
            cognito_user_id=test_user_1.cognito_user_id,
            allocation_id=f"repository-allocation-{unique_suffix}",
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="NEW",
        ),
        _order_item(
            transaction_id=transaction_id,
            order_id=f"partial-{unique_suffix}",
            cognito_user_id=test_user_1.cognito_user_id,
            allocation_id=f"repository-allocation-{unique_suffix}",
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="PARTIALLY_FILLED",
        ),
    ]

    try:
        for item in items:
            order_repository.order_table_client.put_item(item)

        unfilled_orders = order_repository.get_unfilled_orders_by_transaction(
            transaction_id
        )

        assert {order["order_id"] for order in unfilled_orders} == {
            f"new-{unique_suffix}",
            f"partial-{unique_suffix}",
        }
        with pytest.raises(OrderNotFoundError):
            order_repository.get_unfilled_orders_by_transaction(
                f"missing-{uuid4().hex}"
            )
    finally:
        for item in items:
            _delete_order_item(
                order_repository=order_repository,
                transaction_id=item["transaction_id"],
                order_id=item["order_id"],
            )


def test_order_repository_get_unfilled_orders_by_cognito_user_id(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    unique_suffix = uuid4().hex
    cognito_user_id = test_user_1.cognito_user_id
    items = [
        _order_item(
            transaction_id=f"filled-transaction-{unique_suffix}",
            order_id=f"filled-order-{unique_suffix}",
            cognito_user_id=cognito_user_id,
            allocation_id=f"repository-allocation-{unique_suffix}",
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="FILLED",
        ),
        _order_item(
            transaction_id=f"new-transaction-{unique_suffix}",
            order_id=f"new-order-{unique_suffix}",
            cognito_user_id=cognito_user_id,
            allocation_id=f"repository-allocation-{unique_suffix}",
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="NEW",
        ),
    ]

    try:
        for item in items:
            order_repository.order_table_client.put_item(item)

        unfilled_order = _wait_for_order(
            load_orders=lambda: order_repository.get_unfilled_orders_by_cognito_user_id(
                cognito_user_id
            ),
            order_id=f"new-order-{unique_suffix}",
        )

        assert unfilled_order["order_id"] == f"new-order-{unique_suffix}"
        assert all(
            order["status"].upper() != "FILLED"
            for order in order_repository.get_unfilled_orders_by_cognito_user_id(
                cognito_user_id
            )
        )
        assert (
            order_repository.get_unfilled_orders_by_cognito_user_id(
                f"missing-user-{uuid4().hex}"
            )
            == []
        )
    finally:
        for item in items:
            _delete_order_item(
                order_repository=order_repository,
                transaction_id=item["transaction_id"],
                order_id=item["order_id"],
            )


def test_order_repository_get_unfilled_orders_by_allocation_id(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    unique_suffix = uuid4().hex
    allocation_id = f"repository-allocation-{unique_suffix}"
    items = [
        _order_item(
            transaction_id=f"filled-transaction-{unique_suffix}",
            order_id=f"filled-order-{unique_suffix}",
            cognito_user_id=test_user_1.cognito_user_id,
            allocation_id=allocation_id,
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="FILLED",
        ),
        _order_item(
            transaction_id=f"new-transaction-{unique_suffix}",
            order_id=f"new-order-{unique_suffix}",
            cognito_user_id=test_user_1.cognito_user_id,
            allocation_id=allocation_id,
            portfolio_owner_cognito_user_id=test_user_2.cognito_user_id,
            status="NEW",
        ),
    ]

    try:
        for item in items:
            order_repository.order_table_client.put_item(item)

        unfilled_orders = order_repository.get_unfilled_orders_by_allocation_id(
            allocation_id
        )

        assert {order["order_id"] for order in unfilled_orders} == {
            f"new-order-{unique_suffix}"
        }
        assert (
            order_repository.get_unfilled_orders_by_allocation_id(
                f"missing-allocation-{uuid4().hex}"
            )
            == []
        )
    finally:
        for item in items:
            _delete_order_item(
                order_repository=order_repository,
                transaction_id=item["transaction_id"],
                order_id=item["order_id"],
            )


def test_order_repository_allocation_ids_of_unfilled_orders_are_unique_by_owner(
    order_repository: OrderRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    unique_suffix = uuid4().hex
    cognito_user_id = test_user_1.cognito_user_id
    allocation_id = f"repository-allocation-{unique_suffix}"
    owner_id = test_user_2.cognito_user_id
    other_owner_id = f"other-owner-{unique_suffix}"
    items = [
        _order_item(
            transaction_id=f"filled-transaction-{unique_suffix}",
            order_id=f"filled-order-{unique_suffix}",
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
            portfolio_owner_cognito_user_id=owner_id,
            status="FILLED",
        ),
        _order_item(
            transaction_id=f"new-transaction-{unique_suffix}-1",
            order_id=f"new-order-{unique_suffix}-1",
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
            portfolio_owner_cognito_user_id=owner_id,
            status="NEW",
        ),
        _order_item(
            transaction_id=f"new-transaction-{unique_suffix}-2",
            order_id=f"new-order-{unique_suffix}-2",
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
            portfolio_owner_cognito_user_id=owner_id,
            status="PARTIALLY_FILLED",
        ),
        _order_item(
            transaction_id=f"new-transaction-{unique_suffix}-3",
            order_id=f"new-order-{unique_suffix}-3",
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
            portfolio_owner_cognito_user_id=other_owner_id,
            status="NEW",
        ),
    ]

    try:
        for item in items:
            order_repository.order_table_client.put_item(item)

        expected_pairs = {
            (allocation_id, owner_id),
            (allocation_id, other_owner_id),
        }
        allocation_owner_pairs = _wait_for_allocation_owner_pairs(
            load_pairs=lambda: order_repository.get_allocation_ids_of_unfilled_orders(
                cognito_user_id
            ),
            expected_pairs=expected_pairs,
        )

        assert expected_pairs.issubset(set(allocation_owner_pairs))
        assert (
            order_repository.get_allocation_ids_of_unfilled_orders(
                f"missing-user-{uuid4().hex}"
            )
            == []
        )
    finally:
        for item in items:
            _delete_order_item(
                order_repository=order_repository,
                transaction_id=item["transaction_id"],
                order_id=item["order_id"],
            )


def test_order_repository_error_types_expose_stable_codes_and_context() -> None:
    not_found_by_transaction = OrderNotFoundError(transaction_id="txn-1")
    not_found_by_allocation = OrderNotFoundError(allocation_id="allocation-1")
    bad_gateway = OrderBadGatewayError(
        operation="loading orders",
        transaction_id="txn-1",
        allocation_id="allocation-1",
        cause=RuntimeError("upstream failed"),
    )
    unprocessable = OrderUnprocessableEntityError(
        operation="parse order records",
        cause=ValueError("bad value"),
    )

    assert not_found_by_transaction.code == "ORDER_NOT_FOUND"
    assert "txn-1" in str(not_found_by_transaction)
    assert not_found_by_allocation.code == "ORDER_NOT_FOUND"
    assert "allocation-1" in str(not_found_by_allocation)
    assert bad_gateway.code == "ORDER_BAD_GATEWAY"
    assert "loading orders" in str(bad_gateway)
    assert "txn-1" in str(bad_gateway)
    assert "allocation-1" in str(bad_gateway)
    assert unprocessable.code == "ORDER_UNPROCESSABLE_ENTITY"
    assert "parse order records" in str(unprocessable)

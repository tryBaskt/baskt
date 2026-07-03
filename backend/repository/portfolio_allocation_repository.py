# backend/repository/portfolio_allocation_repository.py

# Python imports
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from decimal import Decimal
from boto3.dynamodb.conditions import Key
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError
import time

# Baskt imports
from domain.portfolio_allocation_domain import PortfolioAllocationPosition, PortfolioAllocationTransactionSnapshot, PortfolioAllocationPositionSnapshot, PortfolioAllocation
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from core.timeutils import to_utc_from_iso

WAIT_TIME_SECONDS = 10


def _optional_datetime(value: object) -> Optional[datetime]:
    return None if value is None else to_utc_from_iso(str(value))


def _optional_float(value: object) -> Optional[float]:
    return None if value is None else float(value)


def _optional_int(value: object) -> Optional[int]:
    return None if value is None else int(value)


def _parse_transaction_snapshot(item: Dict) -> PortfolioAllocationTransactionSnapshot:
    """Convert a stored DynamoDB transaction map into its domain model."""
    return PortfolioAllocationTransactionSnapshot(
        transaction_id=str(item["transaction_id"]),
        model_portfolio_snapshot_id=(
            None
            if item.get("model_portfolio_snapshot_id") is None
            else str(item["model_portfolio_snapshot_id"])
        ),
        created_at=to_utc_from_iso(item["created_at"]),
        updated_at=to_utc_from_iso(item.get("updated_at", item["created_at"])),
        requested_amount=_optional_float(item.get("requested_amount")),
        transaction_type=str(item["transaction_type"]),
        status=str(item["status"]),
        filled_at=_optional_datetime(item.get("filled_at")),
        number_orders=_optional_int(item.get("number_orders")),
        cost_basis=_optional_float(item.get("cost_basis")),
        order_fill_percent=_optional_float(item.get("order_fill_percent")),
        status_explanation=(
            None
            if item.get("status_explanation") is None
            else str(item["status_explanation"])
        ),
    )


def _serialize_transaction_snapshot(
    transaction: PortfolioAllocationTransactionSnapshot,
) -> Dict:
    """Convert a transaction domain model into a DynamoDB-compatible map."""
    return {
        "transaction_id": str(transaction.transaction_id),
        "model_portfolio_snapshot_id": transaction.model_portfolio_snapshot_id,
        "created_at": transaction.created_at.isoformat(),
        "updated_at": transaction.updated_at.isoformat(),
        "filled_at": (
            transaction.filled_at.isoformat()
            if transaction.filled_at is not None
            else None
        ),
        "requested_amount": (
            Decimal(str(transaction.requested_amount))
            if transaction.requested_amount is not None
            else None
        ),
        "number_orders": (
            int(transaction.number_orders)
            if transaction.number_orders is not None
            else None
        ),
        "transaction_type": str(transaction.transaction_type),
        "cost_basis": (
            Decimal(str(transaction.cost_basis))
            if transaction.cost_basis is not None
            else None
        ),
        "order_fill_percent": (
            Decimal(str(transaction.order_fill_percent))
            if transaction.order_fill_percent is not None
            else None
        ),
        "status": str(transaction.status),
        "status_explanation": transaction.status_explanation,
    }


class PortfolioAllocationInternalServerError(Exception):
    def __init__(self, message: str, code: str = "PORTFOLIO_ALLOCATION_INTERNAL_SERVER_ERROR") -> None:
        """
        Initialize a portfolio allocation repository exception.

        Args:
            message: Human-readable error details.
            code: Stable application error code identifying the failed operation.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(message)
        self.code = code


class PortfolioAllocationBadGatewayError(PortfolioAllocationInternalServerError):
    def __init__(
        self,
        source: str,
        operation: str,
        *,
        cognito_user_id: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        Initialize an upstream dependency failure for allocation operations.

        Args:
            source: Upstream dependency that failed, such as "DynamoDB" or
                "Alpaca".
            operation: Description of the allocation operation that failed.
            cognito_user_id: Optional Cognito user ID involved in the failure.
            portfolio_id: Optional portfolio ID involved in the failure.
            cause: Optional upstream exception that caused the failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        context = []
        if cognito_user_id:
            context.append(f"user '{cognito_user_id}'")
        if portfolio_id:
            context.append(f"portfolio '{portfolio_id}'")
        message = f"Upstream {source} client failed while {operation}"
        if context:
            message = f"{message} for {', '.join(context)}"
        if cause:
            message = f"{message}: {cause}"
        super().__init__(
            message=message,
            code="PORTFOLIO_ALLOCATION_BAD_GATEWAY"
        )


class PortfolioAllocationNotFoundError(PortfolioAllocationInternalServerError):
    def __init__(self, cognito_user_id: str, portfolio_id: str) -> None:
        """
        Initialize a missing portfolio allocation exception.

        Args:
            cognito_user_id: Cognito user ID whose allocation was not found.
            portfolio_id: Portfolio ID whose allocation was not found.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"Portfolio allocation not found for user '{cognito_user_id}' and portfolio '{portfolio_id}'.",
            code="PORTFOLIO_ALLOCATION_NOT_FOUND",
        )


class PortfolioAllocationUnprocessableEntityError(PortfolioAllocationInternalServerError):
    def __init__(
        self,
        operation: Optional[str] = None,
        *,
        field_name: Optional[str] = None,
        cognito_user_id: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        symbol: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        Initialize an invalid allocation request or parse failure exception.

        Args:
            operation: Optional operation that failed to process valid data.
            field_name: Optional required field name that was missing.
            cognito_user_id: Optional Cognito user ID involved in the failure.
            portfolio_id: Optional portfolio ID involved in the failure.
            symbol: Optional symbol involved in the failure.
            cause: Optional exception that caused the processing failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        if field_name:
            message = f"{field_name} is required."
        else:
            message = f"Failed to {operation}"
            context = []
            if cognito_user_id:
                context.append(f"user '{cognito_user_id}'")
            if portfolio_id:
                context.append(f"portfolio '{portfolio_id}'")
            if symbol:
                context.append(f"symbol '{symbol}'")
            if context:
                message = f"{message} for {', '.join(context)}"
            if cause:
                message = f"{message}: {cause}"
        super().__init__(
            message=message,
            code="PORTFOLIO_ALLOCATION_UNPROCESSABLE_ENTITY",
        )



class PortfolioAllocationRepository:
    """
    Repository for managing user portfolio allocation records in DynamoDB.
    """

    def __init__(self,
            alpaca_broker_client: AlpacaBrokerClient,
            dynamodb_client: DynamoDBClient
    ) -> None:
        """
        Initialize portfolio allocation repository dependencies.

        Args:
            alpaca_broker_client: Alpaca broker client used for latest prices.
            dynamodb_client: DynamoDB client wrapper for allocation persistence.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        self.alpaca_broker_client = alpaca_broker_client
        self.portfolio_allocation_table_client = dynamodb_client

    def _wait_exists(self, cognito_user_id: str, portfolio_id: str):
        expire_time = time.time() + WAIT_TIME_SECONDS
        while time.time() < expire_time and not self.is_exists_portfolio_allocation_for_user(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id):
            time.sleep(0.25)

    def calculate_positions_current_value(self, portfolio_allocation_position_snapshot: PortfolioAllocationPositionSnapshot) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """
        Calculate each position's current portfolio value using latest prices.

        Args:
            portfolio_allocation_snapshot: Snapshot containing historical position state.

        Returns:
            Tuple[Dict[str, float], float, Dict[str, float]]: Position values
            by symbol, total allocation value, and latest quotes.

        Raises:
            PortfolioAllocationBadGatewayError: If Alpaca fails while fetching
            latest prices.
            KeyError: If a latest price is missing for a position symbol.
        """

        curr_positions = portfolio_allocation_position_snapshot.positions
        if not curr_positions:
            raise PortfolioAllocationInternalServerError(
                message=f"No positions in snapshot",
                code="PORTFOLIO_ALLOCATION_CALC_POS_CURRENT_VALUE_FAILED"
            )
        symbols = [pos.symbol for pos in curr_positions]
        try:
            quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
        except AlpacaBrokerClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="Alpaca",
                operation="fetching latest prices for portfolio allocation",
                cause=e,
            ) from e

        position_values: Dict[str, float] = {}
        for position in curr_positions:
            current_price = quotes[position.symbol]
            filled_quantity = float(position.filled_quantity)
            entry_price = float(position.filled_avg_price)

            # Long: value rises with price; short: value falls with price.
            position_values[position.symbol] = filled_quantity * (
                entry_price + position.direction * (current_price - entry_price)
            )

        return position_values, sum(position_values.values()), quotes

    def calculate_positions_current_weight(self, portfolio_allocation_position_snapshot: PortfolioAllocationPositionSnapshot) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """
        Calculate each position's current portfolio weight using latest prices.

        Args:
            portfolio_allocation_snapshot: Snapshot containing historical position state.

        Returns:
            Tuple[Dict[str, float], float, Dict[str, float]]: Normalized
            current weights by symbol, total allocation value, and latest
            quotes.

        Raises:
            PortfolioAllocationBadGatewayError: If Alpaca fails while fetching
            latest prices.
            PortfolioAllocationUnprocessableEntityError: If a latest price is
            missing for a position symbol.
        """

        position_values, total_portfolio_allocation_value, quotes = self.calculate_positions_current_value(portfolio_allocation_position_snapshot=portfolio_allocation_position_snapshot)

        if total_portfolio_allocation_value == 0:
            return {symbol: 0.0 for symbol in position_values}, 0.0, quotes

        return (
            {
                symbol: value / total_portfolio_allocation_value
                for symbol, value in position_values.items()
            },
            total_portfolio_allocation_value,
            quotes
        )

    def is_exists_portfolio_allocation_for_user(self, cognito_user_id: str, portfolio_id: str) -> bool:
        """
        Check whether a user has an allocation record for a portfolio.

        Args:
            cognito_user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            bool: True if an allocation record exists, otherwise False.

        Raises:
            DynamoDBClientError: If DynamoDB fails while checking item
            existence.
        """

        key = {"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id}
        return self.portfolio_allocation_table_client.item_exists(key=key)

    def get_portfolio_allocation_transaction_history(self, cognito_user_id: str, portfolio_id: str, with_wait: bool = False) -> List[PortfolioAllocationTransactionSnapshot]:
        """
        Retrieve transaction snapshots for a user's portfolio allocation.

        Args:
            cognito_user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            List[PortfolioAllocationTransactionSnapshot]: Transaction snapshots
            in stored order.

        Raises:
            PortfolioAllocationBadGatewayError: If DynamoDB fails while loading
            transaction history.
            PortfolioAllocationNotFoundError: If the allocation record does not
            exist.
            PortfolioAllocationUnprocessableEntityError: If transaction history
            is missing or cannot be parsed into the domain model.
        """
        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)

        try:
            item = self.portfolio_allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id},
                projection_expression="transaction_history"
            )
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="loading transaction history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not item:
            raise PortfolioAllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )

        if "transaction_history" not in item:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="load transaction history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=KeyError("transaction_history"),
            )

        # Parse all transaction snapshots
        transaction_history = item["transaction_history"]
        result = []
        try:
            for snap in transaction_history:
                result.append(_parse_transaction_snapshot(snap))


        except Exception as e:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="parse transaction history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        return result


    def get_n_last_portfolio_allocation_transaction_snapshots(self, cognito_user_id: str, portfolio_id: str, n: int, with_wait: bool = False) -> List[PortfolioAllocationTransactionSnapshot]:
        """
        Retrieve the last n allocation snapshots for a user's portfolio.

        Args:
            cognito_user_id: User identifier.
            portfolio_id: Portfolio identifier.
            n: Number of trailing snapshots to return.

        Returns:
            List[PortfolioAllocationSnapshot]: Most recent n allocation
            snapshots.

        Raises:
            ValueError: If n is out of range.
            PortfolioAllocationUnprocessableEntityError: If stored allocation
            history cannot be parsed.
            PortfolioAllocationBadGatewayError: If DynamoDB fails while loading
            allocation history.
            PortfolioAllocationNotFoundError: If the allocation record does not
            exist.
        """

        if n <= 0:
            raise ValueError(
                f"validate n argument '{n}' greater than 0"
            )

        transaction_history = self.get_portfolio_allocation_transaction_history(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id, with_wait=with_wait)
        if n > len(transaction_history):
            raise ValueError(
                f"validate n argument '{n}' less than or equal to the number of snapshots '{len(transaction_history)}'"
            )
        last_n_snapshots = transaction_history[-n:]

        return last_n_snapshots

    def get_portfolio_allocation_position_snapshots(self, cognito_user_id: str, portfolio_id: str, with_wait: bool = False) -> List[PortfolioAllocationPositionSnapshot]:

        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)

        try:
            item = self.portfolio_allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id},
                projection_expression="position_history"
            )
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="loading portfolio allocation",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not item:
            raise PortfolioAllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id
            )

        if "position_history" not in item:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="load position history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=KeyError("position_history"),
            )
        if len(item["position_history"]) < 1:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="load position history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=KeyError("position_history"),
            )

        return [
            PortfolioAllocationPositionSnapshot(
                positions=[
                    PortfolioAllocationPosition(
                        symbol=position["symbol"],
                        filled_quantity=float(position["filled_quantity"]),
                        direction=int(position["direction"]),
                        filled_avg_price=float(position["filled_avg_price"])
                    )
                    for position in position_snapshot["positions"]
                ],
                timestamp=to_utc_from_iso(position_snapshot["timestamp"])
            )
            for position_snapshot in item["position_history"]
        ]


    def get_latest_portfolio_allocation_position_snapshot(self, cognito_user_id: str, portfolio_id: str, with_wait: bool = False) -> PortfolioAllocationPositionSnapshot:

        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)

        try:
            item = self.portfolio_allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id},
                projection_expression="position_history"
            )
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="loading portfolio allocation",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not item:
            raise PortfolioAllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id
            )

        if "position_history" not in item:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="load position history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=KeyError("position_history"),
            )
        if len(item["position_history"]) < 1:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="load position history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=KeyError("position_history"),
            )

        position_snapshot = item["position_history"][-1]

        return PortfolioAllocationPositionSnapshot(
            positions=[
                PortfolioAllocationPosition(
                    symbol=position["symbol"],
                    filled_quantity=float(position["filled_quantity"]),
                    direction=int(position["direction"]),
                    filled_avg_price=float(position["filled_avg_price"])
                )
                for position in position_snapshot["positions"]
            ],
            timestamp=to_utc_from_iso(position_snapshot["timestamp"])
        )


    def get_portfolio_allocation_total_cost_basis(self, cognito_user_id: str, portfolio_id: str) -> float:
        """
        Retrieve the total cost basis for a user's portfolio allocation.

        Args:
            cognito_user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            float: Total cost basis currently stored for the allocation.

        Raises:
            PortfolioAllocationBadGatewayError: If DynamoDB fails while loading
            the allocation.
            PortfolioAllocationNotFoundError: If the allocation record does not
            exist.
            PortfolioAllocationUnprocessableEntityError: If total_cost_basis
            is missing or cannot be converted to a float.
        """
        try:
            item = self.portfolio_allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id},
                projection_expression="total_cost_basis"
            )
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="loading portfolio allocation",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not item:
            raise PortfolioAllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id
            )

        try:
            return float(item["total_cost_basis"])
        except Exception as e:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="parse total cost basis",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

    def get_portfolio_allocations_by_cognito_user_id(self, cognito_user_id: str) -> List[PortfolioAllocation]:
        """
        Load all portfolio allocations for a Cognito user.

        Args:
            cognito_user_id: Cognito user ID whose allocations should be
                returned.

        Returns:
            List[PortfolioAllocation]: All allocation records for the user. The
            list is empty when the user has no allocation records.

        Raises:
            PortfolioAllocationBadGatewayError: If DynamoDB fails while querying
            portfolio allocations.
            PortfolioAllocationUnprocessableEntityError: If any returned record
            cannot be parsed into the domain model.
        """
        try:
            items = self.portfolio_allocation_table_client.query(
                key_condition=Key("cognito_user_id").eq(cognito_user_id),
            )
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="querying portfolio allocations",
                cognito_user_id=cognito_user_id,
                cause=e,
            ) from e

        try:
            portfolio_allocations: List[PortfolioAllocation] = []
            for item in items:
                portfolio_id = str(item["portfolio_id"])
                position_history = [
                    PortfolioAllocationPositionSnapshot(
                        positions=[
                            PortfolioAllocationPosition(
                                filled_avg_price=float(position["filled_avg_price"]),
                                symbol=str(position["symbol"]),
                                filled_quantity=float(position["filled_quantity"]),
                                direction=int(position["direction"]),
                            )
                            for position in position_snapshot["positions"]
                        ],
                        timestamp=to_utc_from_iso(position_snapshot["timestamp"]),
                    )
                    for position_snapshot in item["position_history"]
                ]

                transaction_history = [
                    _parse_transaction_snapshot(transaction_snapshot)
                    for transaction_snapshot in item["transaction_history"]
                ]

                portfolio_allocations.append(
                    PortfolioAllocation(
                        portfolio_id=portfolio_id,
                        cognito_user_id=str(item["cognito_user_id"]),
                        position_history=position_history,
                        transaction_history=transaction_history,
                        total_cost_basis=float(item["total_cost_basis"]),
                        portfolio_allocation_type=str(item["portfolio_allocation_type"]),
                        portfolio_name=str(item["portfolio_name"]),
                    )
                )

            return portfolio_allocations
        except Exception as e:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="parsing portfolio allocations for user",
                cognito_user_id=cognito_user_id,
                cause=e,
            ) from e

    def get_portfolio_allocation(self, cognito_user_id: str, portfolio_id: str, with_wait: bool = False) -> PortfolioAllocation:
        """Load a full portfolio allocation aggregate for a user and portfolio.

        Args:
            cognito_user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            PortfolioAllocation: Portfolio allocation object.

        Raises:
            PortfolioAllocationBadGatewayError: If DynamoDB fails while loading
            the allocation.
            PortfolioAllocationNotFoundError: If the allocation record does not
            exist.
            PortfolioAllocationUnprocessableEntityError: If stored allocation
            data cannot be parsed.
        """

        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)

        try:
            item = self.portfolio_allocation_table_client.get_item(key={"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id})
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="loading portfolio allocation",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not item:
            raise PortfolioAllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id
            )

        try:
            position_history = [
                PortfolioAllocationPositionSnapshot(
                    positions=[
                        PortfolioAllocationPosition(
                            filled_avg_price=float(position["filled_avg_price"]),
                            symbol=position["symbol"],
                            filled_quantity=float(position["filled_quantity"]),
                            direction=int(position["direction"]),
                        )
                        for position in position_snapshot["positions"]
                    ],
                    timestamp=to_utc_from_iso(position_snapshot["timestamp"])
                )
                for position_snapshot in item["position_history"]
            ]

            portfolio_allocation = PortfolioAllocation(
                portfolio_id=item["portfolio_id"],
                cognito_user_id=item["cognito_user_id"],
                position_history=position_history,
                transaction_history=[
                    _parse_transaction_snapshot(transaction_snapshot)
                    for transaction_snapshot in item["transaction_history"]
                ],
                total_cost_basis=float(item["total_cost_basis"]),
                portfolio_allocation_type=str(item["portfolio_allocation_type"]),
                portfolio_name=str(item["portfolio_name"])

            )
        except Exception as e:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="parsing portfolio allocation for getting",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause = e
            ) from e

        return portfolio_allocation

    def set_portfolio_allocation(self, portfolio_allocation: PortfolioAllocation) -> None:
        """Persist a portfolio allocation aggregate to storage.

        Args:
            portfolio_allocation: Allocation object to serialize and write.

        Returns:
            None.

        Raises:
            PortfolioAllocationUnprocessableEntityError: If the allocation
            cannot be serialized into the DynamoDB item shape.
            PortfolioAllocationBadGatewayError: If DynamoDB fails while
            persisting the allocation.
        """

        try:
            item = {
                "cognito_user_id": portfolio_allocation.cognito_user_id,
                "portfolio_id": portfolio_allocation.portfolio_id,
                "position_history": [
                    {
                        "positions": [
                            {
                                "filled_avg_price": Decimal(str(position.filled_avg_price)),
                                "symbol": position.symbol,
                                "filled_quantity": Decimal(str(position.filled_quantity)),
                                "direction": int(position.direction),
                            }
                            for position in position_snapshot.positions
                        ],
                        "timestamp": position_snapshot.timestamp.isoformat()
                    }
                    for position_snapshot in portfolio_allocation.position_history
                ],
                "transaction_history": [
                    _serialize_transaction_snapshot(transaction_snapshot)
                    for transaction_snapshot in portfolio_allocation.transaction_history
                ],
                "total_cost_basis": Decimal(str(portfolio_allocation.total_cost_basis)),
                "portfolio_allocation_type": str(portfolio_allocation.portfolio_allocation_type),
                "portfolio_name": str(portfolio_allocation.portfolio_name)
            }
        except Exception as e:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="serializing portfolio allocation for persistence",
                cognito_user_id=portfolio_allocation.cognito_user_id,
                portfolio_id=portfolio_allocation.portfolio_id,
                cause=e,
            ) from e


        try:
            self.portfolio_allocation_table_client.put_item(item=item)
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="persisting portfolio allocation",
                cognito_user_id=portfolio_allocation.cognito_user_id,
                portfolio_id=portfolio_allocation.portfolio_id,
                cause=e,
            ) from e

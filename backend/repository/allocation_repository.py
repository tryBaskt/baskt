# backend/repository/allocation_repository.py

# Python imports
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from boto3.dynamodb.conditions import Key
from clients.dynamodb_client import (
    DynamoDBClient,
    DynamoDBClientError,
    dataclass_to_dynamodb_item,
)
import time

# Baskt imports
from domain.allocation_domain import (
    PortfolioAllocationPosition, 
    PortfolioAllocationTransactionSnapshot, 
    PortfolioAllocationPositionSnapshot, 
    PortfolioAllocation,
    StockAllocationPosition,
    StockAllocationTransactionSnapshot,
    StockAllocationPositionSnapshot,
    StockAllocation
)
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from core.timeutils import to_utc_from_iso

WAIT_TIME_SECONDS = 10


def _optional_datetime(value: object) -> Optional[datetime]:
    return None if value is None else to_utc_from_iso(str(value))


def _optional_float(value: object) -> Optional[float]:
    return None if value is None else float(value)


def _optional_int(value: object) -> Optional[int]:
    return None if value is None else int(value)


def _parse_portfolio_allocation_position(item: Dict) -> PortfolioAllocationPosition:
    """Convert a stored allocation position map into its domain model."""
    return PortfolioAllocationPosition(
        symbol=str(item["symbol"]),
        filled_quantity=float(item["filled_quantity"]),
        direction=int(item["direction"]),
        filled_avg_price=float(item["filled_avg_price"]),
    )


def _parse_stock_allocation_position(item: Dict) -> StockAllocationPosition:
    """Convert a stored allocation position map into its domain model."""
    return StockAllocationPosition(
        symbol=str(item["symbol"]),
        filled_quantity=float(item["filled_quantity"]),
        direction=int(item["direction"]),
        filled_avg_price=float(item["filled_avg_price"]),
    )


def _parse_portfolio_allocation_transaction_snapshot(item: Dict) -> PortfolioAllocationTransactionSnapshot:
    """Convert a stored DynamoDB transaction map into its domain model."""
    portfolio_snapshot_id = item.get("portfolio_snapshot_id")
    return PortfolioAllocationTransactionSnapshot(
        transaction_id=str(item["transaction_id"]),
        created_at=to_utc_from_iso(item["created_at"]),
        updated_at=to_utc_from_iso(item.get("updated_at", item["created_at"])),
        requested_amount=_optional_float(item.get("requested_amount")),
        transaction_type=str(item["transaction_type"]),
        status=str(item["status"]),
        portfolio_snapshot_id=(
            None
            if portfolio_snapshot_id is None
            else str(portfolio_snapshot_id)
        ),
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


def _parse_stock_allocation_transaction_snapshot(item: Dict) -> StockAllocationTransactionSnapshot:
    """Convert a stored DynamoDB transaction map into its domain model."""
    return StockAllocationTransactionSnapshot(
        transaction_id=str(item["transaction_id"]),
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


def _parse_portfolio_allocation_position_snapshot(item: Dict) -> PortfolioAllocationPositionSnapshot:
    """Convert a stored portfolio position snapshot map into its domain model."""
    return PortfolioAllocationPositionSnapshot(
        positions=[
            _parse_portfolio_allocation_position(position)
            for position in item["positions"]
        ],
        timestamp=to_utc_from_iso(item["timestamp"]),
    )


def _parse_stock_allocation_position_snapshot(item: Dict) -> StockAllocationPositionSnapshot:
    """Convert a stored stock position snapshot map into its domain model."""
    position = item.get("position")
    return StockAllocationPositionSnapshot(
        position=(
            None
            if position is None
            else _parse_stock_allocation_position(position)
        ),
        timestamp=to_utc_from_iso(item["timestamp"]),
    )


def _parse_allocation(item: Dict) -> PortfolioAllocation | StockAllocation:
    """Convert a stored allocation item into the matching allocation aggregate."""
    allocation_type = str(item["allocation_type"])
    base_kwargs = {
        "allocation_id": str(item["allocation_id"]),
        "cognito_user_id": str(item["cognito_user_id"]),
        "total_cost_basis": float(item["total_cost_basis"]),
        "allocation_type": allocation_type,
    }

    if allocation_type == "STOCK":
        return StockAllocation(
            **base_kwargs,
            position_history=[
                _parse_stock_allocation_position_snapshot(position_snapshot)
                for position_snapshot in item["position_history"]
            ],
            transaction_history=[
                _parse_stock_allocation_transaction_snapshot(transaction_snapshot)
                for transaction_snapshot in item["transaction_history"]
            ],
            symbol=str(item["symbol"]),
        )

    return PortfolioAllocation(
        **base_kwargs,
        position_history=[
            _parse_portfolio_allocation_position_snapshot(position_snapshot)
            for position_snapshot in item["position_history"]
        ],
        transaction_history=[
            _parse_portfolio_allocation_transaction_snapshot(transaction_snapshot)
            for transaction_snapshot in item["transaction_history"]
        ],
        portfolio_name=str(item["portfolio_name"]),
    )


class AllocationRepositoryError(Exception):
    def __init__(self, message: str, code: str = "ALLOCATION_REPOSITORY_ERROR") -> None:
        """
        """
        super().__init__(message)
        self.code = code


class AllocationBadGatewayError(AllocationRepositoryError):
    def __init__(
        self,
        source: str,
        operation: str,
        *,
        cognito_user_id: Optional[str] = None,
        allocation_id: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        """
        context = []
        if cognito_user_id:
            context.append(f"user '{cognito_user_id}'")
        if allocation_id:
            context.append(f"allocation '{allocation_id}'")
        message = f"Upstream {source} client failed while {operation}"
        if context:
            message = f"{message} for {', '.join(context)}"
        if cause:
            message = f"{message}: {cause}"
        super().__init__(
            message=message,
            code="ALLOCATION_BAD_GATEWAY"
        )


class AllocationNotFoundError(AllocationRepositoryError):
    def __init__(self, cognito_user_id: str, allocation_id: str) -> None:
        """
        """
        super().__init__(
            message=f"Allocation not found for user '{cognito_user_id}' and allocation '{allocation_id}'.",
            code="ALLOCATION_NOT_FOUND",
        )


class AllocationUnprocessableEntityError(AllocationRepositoryError):
    def __init__(
        self,
        operation: Optional[str] = None,
        *,
        field_name: Optional[str] = None,
        cognito_user_id: Optional[str] = None,
        allocation_id: Optional[str] = None,
        symbol: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        """
        if field_name:
            message = f"{field_name} is required."
        else:
            message = f"Failed to {operation}"
            context = []
            if cognito_user_id:
                context.append(f"user '{cognito_user_id}'")
            if allocation_id:
                context.append(f"allocation '{allocation_id}'")
            if symbol:
                context.append(f"symbol '{symbol}'")
            if context:
                message = f"{message} for {', '.join(context)}"
            if cause:
                message = f"{message}: {cause}"
        super().__init__(
            message=message,
            code="ALLOCATION_UNPROCESSABLE_ENTITY",
        )



class AllocationRepository:
    """
    Repository for managing allocation records in DynamoDB.
    """

    def __init__(self,
            alpaca_broker_client: AlpacaBrokerClient,
            dynamodb_client: DynamoDBClient
    ) -> None:
        """
        """
        self.alpaca_broker_client = alpaca_broker_client
        self.allocation_table_client = dynamodb_client

    def _wait_exists(self, cognito_user_id: str, allocation_id: str):
        expire_time = time.time() + WAIT_TIME_SECONDS
        while time.time() < expire_time and not self.is_exists_allocation_for_user(cognito_user_id=cognito_user_id, allocation_id=allocation_id):
            time.sleep(0.25)

    def calculate_portfolio_allocation_position_snapshot_current_value(self, position_snapshot: PortfolioAllocationPositionSnapshot) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """
        """

        curr_positions = position_snapshot.positions
        if not curr_positions:
            raise AllocationRepositoryError(
                message=f"No positions in snapshot",
                code="PORTFOLIO_ALLOCATION_CALC_POS_CURRENT_VALUE_FAILED"
            )
        symbols = [pos.symbol for pos in curr_positions]
        try:
            quotes = self.alpaca_broker_client.get_latest_price(symbols=symbols)
        except AlpacaBrokerClientError as e:
            raise AllocationBadGatewayError(
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


    def calculate_stock_allocation_position_snapshot_current_value(self, position_snapshot: StockAllocationPositionSnapshot) -> Tuple[float, float]:
        """
        Calculate a stock allocation position's current value.
        """

        position = position_snapshot.position
        if position is None:
            return 0.0, 0.0

        symbol = position.symbol
        try:
            quotes = self.alpaca_broker_client.get_latest_price(symbols=[symbol])
        except AlpacaBrokerClientError as e:
            raise AllocationBadGatewayError(
                source="Alpaca",
                operation="fetching latest prices for stock allocation",
                cause=e,
            ) from e

        current_price = quotes[symbol]
        filled_quantity = float(position.filled_quantity)
        entry_price = float(position.filled_avg_price)
        position_value = filled_quantity * (
            entry_price + position.direction * (current_price - entry_price)
        )

        return position_value, current_price

    def calculate_portfolio_allocation_position_snapshot_current_weight(self, position_snapshot: PortfolioAllocationPositionSnapshot) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """
        """

        position_values, total_portfolio_allocation_value, quotes = self.calculate_portfolio_allocation_position_snapshot_current_value(position_snapshot=position_snapshot)

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

    def is_exists_allocation_for_user(self, cognito_user_id: str, allocation_id: str) -> bool:
        """
        """

        key = {"cognito_user_id": cognito_user_id, "allocation_id": allocation_id}
        return self.allocation_table_client.item_exists(key=key)

    def calculate_positions_current_value(
        self,
        portfolio_allocation_position_snapshot: PortfolioAllocationPositionSnapshot | StockAllocationPositionSnapshot,
    ) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """
        Calculate the current value for a portfolio or stock allocation snapshot.
        """
        if isinstance(portfolio_allocation_position_snapshot, StockAllocationPositionSnapshot):
            if portfolio_allocation_position_snapshot.position is None:
                return {}, 0.0, {}
            position_value, current_price = self.calculate_stock_allocation_position_snapshot_current_value(
                position_snapshot=portfolio_allocation_position_snapshot,
            )
            return (
                {portfolio_allocation_position_snapshot.position.symbol: position_value},
                position_value,
                {portfolio_allocation_position_snapshot.position.symbol: current_price},
            )
        return self.calculate_portfolio_allocation_position_snapshot_current_value(
            position_snapshot=portfolio_allocation_position_snapshot,
        )

    def calculate_positions_current_weight(
        self,
        portfolio_allocation_position_snapshot: PortfolioAllocationPositionSnapshot | StockAllocationPositionSnapshot,
    ) -> Tuple[Dict[str, float], float, Dict[str, float]]:
        """
        Calculate current weights for a portfolio or stock allocation snapshot.
        """
        if isinstance(portfolio_allocation_position_snapshot, StockAllocationPositionSnapshot):
            position_values, allocation_value, quotes = self.calculate_positions_current_value(
                portfolio_allocation_position_snapshot=portfolio_allocation_position_snapshot,
            )
            if allocation_value == 0:
                return {symbol: 0.0 for symbol in position_values}, 0.0, quotes
            return (
                {
                    symbol: value / allocation_value
                    for symbol, value in position_values.items()
                },
                allocation_value,
                quotes,
            )
        return self.calculate_portfolio_allocation_position_snapshot_current_weight(
            position_snapshot=portfolio_allocation_position_snapshot,
        )

    def get_portfolio_allocation_transaction_history(
        self,
        cognito_user_id: str,
        allocation_id: str,
        with_wait: bool = False,
    ) -> List[PortfolioAllocationTransactionSnapshot]:
        """
        """
        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, allocation_id=allocation_id)

        try:
            item = self.allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "allocation_id": allocation_id},
                projection_expression="transaction_history"
            )
        except DynamoDBClientError as e:
            raise AllocationBadGatewayError(
                source="DynamoDB",
                operation="loading transaction history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

        if not item:
            raise AllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            )

        if "transaction_history" not in item:
            raise AllocationUnprocessableEntityError(
                operation="load transaction history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=KeyError("transaction_history"),
            )

        # Parse all transaction snapshots
        transaction_history = item["transaction_history"]
        result = []
        try:
            for snap in transaction_history:
                result.append(_parse_portfolio_allocation_transaction_snapshot(snap))

        except Exception as e:
            raise AllocationUnprocessableEntityError(
                operation="parse transaction history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

        return result


    def get_n_last_portfolio_allocation_transaction_snapshots(
        self,
        cognito_user_id: str,
        allocation_id: str,
        n: int,
        with_wait: bool = False,
    ) -> List[PortfolioAllocationTransactionSnapshot]:
        """
        Retrieve the last n allocation snapshots for a user's portfolio.

        Args:
            cognito_user_id: User identifier.
            allocation_id: Allocation identifier.
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

        transaction_history = self.get_portfolio_allocation_transaction_history(cognito_user_id=cognito_user_id, allocation_id=allocation_id, with_wait=with_wait)
        if n > len(transaction_history):
            raise ValueError(
                f"validate n argument '{n}' less than or equal to the number of snapshots '{len(transaction_history)}'"
            )
        last_n_snapshots = transaction_history[-n:]

        return last_n_snapshots


    def _get_position_history(self, cognito_user_id: str, allocation_id: str, with_wait: bool = False):
        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, allocation_id=allocation_id)
        
        try:
            item = self.allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "allocation_id": allocation_id},
                projection_expression="position_history"
            )
        except DynamoDBClientError as e:
            raise AllocationBadGatewayError(
                source="DynamoDB",
                operation="loading portfolio allocation",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

        if not item:
            raise AllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id
            )

        if "position_history" not in item:
            raise AllocationUnprocessableEntityError(
                operation="load position history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=KeyError("position_history"),
            )
        if len(item["position_history"]) < 1:
            raise AllocationUnprocessableEntityError(
                operation="load position history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=KeyError("position_history"),
            )

        return item


    def get_portfolio_allocation_position_history(
        self,
        cognito_user_id: str,
        allocation_id: str,
        with_wait: bool = False,
    ) -> List[PortfolioAllocationPositionSnapshot]:

        item = self._get_position_history(cognito_user_id=cognito_user_id, allocation_id=allocation_id, with_wait=with_wait)

        return [
            _parse_portfolio_allocation_position_snapshot(position_snapshot)
            for position_snapshot in item["position_history"]
        ]


    def get_stock_allocation_position_history(self, cognito_user_id: str, allocation_id: str, with_wait: bool = False) -> List[StockAllocationPositionSnapshot]:
    
        item = self._get_position_history(cognito_user_id=cognito_user_id, allocation_id=allocation_id, with_wait=with_wait)

        return [
            _parse_stock_allocation_position_snapshot(position_snapshot)
            for position_snapshot in item["position_history"]
        ]


    def get_latest_portfolio_allocation_position_snapshot(
        self,
        cognito_user_id: str,
        allocation_id: str,
        with_wait: bool = False,
    ) -> PortfolioAllocationPositionSnapshot:

        position_history = self.get_portfolio_allocation_position_history(cognito_user_id=cognito_user_id, allocation_id=allocation_id, with_wait=with_wait)

        return position_history[-1]


    def get_latest_stock_allocation_position_snapshot(self, cognito_user_id: str, allocation_id: str, with_wait: bool = False) -> StockAllocationPositionSnapshot:

        position_history = self.get_stock_allocation_position_history(cognito_user_id=cognito_user_id, allocation_id=allocation_id, with_wait=with_wait)

        return position_history[-1]


    def get_allocation_total_cost_basis(self, cognito_user_id: str, allocation_id: str) -> float:
        """
        """
        try:
            item = self.allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "allocation_id": allocation_id},
                projection_expression="total_cost_basis"
            )
        except DynamoDBClientError as e:
            raise AllocationBadGatewayError(
                source="DynamoDB",
                operation="loading  allocation",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

        if not item:
            raise AllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id
            )

        try:
            return float(item["total_cost_basis"])
        except Exception as e:
            raise AllocationUnprocessableEntityError(
                operation="parse total cost basis",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e


    def get_stock_allocation_transaction_history(self, cognito_user_id: str, allocation_id: str, with_wait: bool = False) -> List[StockAllocationTransactionSnapshot]:
        """
        Retrieve stock transaction snapshots for a user's allocation.
        """
        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, allocation_id=allocation_id)

        try:
            item = self.allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "allocation_id": allocation_id},
                projection_expression="transaction_history"
            )
        except DynamoDBClientError as e:
            raise AllocationBadGatewayError(
                source="DynamoDB",
                operation="loading stock transaction history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

        if not item:
            raise AllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            )

        if "transaction_history" not in item:
            raise AllocationUnprocessableEntityError(
                operation="load stock transaction history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=KeyError("transaction_history"),
            )

        try:
            return [
                _parse_stock_allocation_transaction_snapshot(snap)
                for snap in item["transaction_history"]
            ]
        except Exception as e:
            raise AllocationUnprocessableEntityError(
                operation="parse stock transaction history",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

    def get_n_last_stock_allocation_transaction_snapshots(self, cognito_user_id: str, allocation_id: str, n: int, with_wait: bool = False) -> List[StockAllocationTransactionSnapshot]:
        """
        Retrieve the last n transaction snapshots for a user's stock allocation.
        """
        if n <= 0:
            raise ValueError(
                f"validate n argument '{n}' greater than 0"
            )

        transaction_history = self.get_stock_allocation_transaction_history(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
            with_wait=with_wait,
        )
        if n > len(transaction_history):
            raise ValueError(
                f"validate n argument '{n}' less than or equal to the number of snapshots '{len(transaction_history)}'"
            )

        return transaction_history[-n:]

    def get_allocations_by_cognito_user_id(self, cognito_user_id: str) -> List[PortfolioAllocation | StockAllocation]:
        """
        Load all allocations for a Cognito user.
        """
        try:
            items = self.allocation_table_client.query(
                key_condition=Key("cognito_user_id").eq(cognito_user_id),
            )
        except DynamoDBClientError as e:
            raise AllocationBadGatewayError(
                source="DynamoDB",
                operation="querying allocations",
                cognito_user_id=cognito_user_id,
                cause=e,
            ) from e

        try:
            return [_parse_allocation(item) for item in items]
        except Exception as e:
            raise AllocationUnprocessableEntityError(
                operation="parse allocations for user",
                cognito_user_id=cognito_user_id,
                cause=e,
            ) from e

    def get_allocation(self, cognito_user_id: str, allocation_id: str, with_wait: bool = False) -> PortfolioAllocation | StockAllocation:
        """
        Load a full allocation aggregate for a user.
        """
        if with_wait:
            self._wait_exists(cognito_user_id=cognito_user_id, allocation_id=allocation_id)

        try:
            item = self.allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "allocation_id": allocation_id}
            )
        except DynamoDBClientError as e:
            raise AllocationBadGatewayError(
                source="DynamoDB",
                operation="loading allocation",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

        if not item:
            raise AllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            )

        try:
            return _parse_allocation(item)
        except Exception as e:
            raise AllocationUnprocessableEntityError(
                operation="parse allocation",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=e,
            ) from e

    def get_stock_allocation(self, cognito_user_id: str, allocation_id: str, with_wait: bool = False) -> StockAllocation:
        """
        Load a stock allocation aggregate for a user.
        """
        allocation = self.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
            with_wait=with_wait,
        )
        if not isinstance(allocation, StockAllocation):
            raise AllocationUnprocessableEntityError(
                operation="load stock allocation",
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
                cause=TypeError(f"expected StockAllocation, got {type(allocation).__name__}"),
            )
        return allocation

    def set_allocation(self, allocation: PortfolioAllocation | StockAllocation) -> None:
        """
        Persist an allocation aggregate to storage.
        """
        try:
            item = dataclass_to_dynamodb_item(allocation)
        except Exception as e:
            raise AllocationUnprocessableEntityError(
                operation="serialize allocation for persistence",
                cognito_user_id=allocation.cognito_user_id,
                allocation_id=allocation.allocation_id,
                cause=e,
            ) from e

        try:
            self.allocation_table_client.put_item(item=item)
        except DynamoDBClientError as e:
            raise AllocationBadGatewayError(
                source="DynamoDB",
                operation="persisting allocation",
                cognito_user_id=allocation.cognito_user_id,
                allocation_id=allocation.allocation_id,
                cause=e,
            ) from e

# backend/repository/portfolio_allocation_repository.py

# Python imports
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Tuple
from decimal import Decimal
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError

# Baskt imports
from domain.portfolio_allocation import PortfolioAllocationPosition, PortfolioAllocationSnapshot, PortfolioAllocation
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from core.timeutils import to_utc_from_iso


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
        cognito_user_id: str | None = None,
        portfolio_id: str | None = None,
        cause: Exception | None = None,
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
        operation: str | None = None,
        *,
        field_name: str | None = None,
        cognito_user_id: str | None = None,
        portfolio_id: str | None = None,
        symbol: str | None = None,
        cause: Exception | None = None,
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

    def calculate_positions_current_value(self, portfolio_allocation_snapshot: PortfolioAllocationSnapshot) -> Tuple[Dict[str, float], float, Dict[str, float]]:
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

        curr_positions = portfolio_allocation_snapshot.positions
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

    def calculate_positions_current_weight(self, portfolio_allocation_snapshot: PortfolioAllocationSnapshot) -> Tuple[Dict[str, float], float, Dict[str, float]]:
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

        position_values, total_portfolio_allocation_value, quotes = self.calculate_positions_current_value(portfolio_allocation_snapshot=portfolio_allocation_snapshot)

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
    
    def get_portfolio_allocation_history(self, cognito_user_id: str, portfolio_id: str) -> List[PortfolioAllocationSnapshot]:
        """
        Retrieve all saved allocation snapshots for a user's portfolio.

        Args:
            cognito_user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            List[PortfolioAllocationSnapshot]: Allocation snapshots in stored
            order.

        Raises:
            PortfolioAllocationBadGatewayError: If DynamoDB fails while loading
            allocation history.
            PortfolioAllocationNotFoundError: If the allocation record does not
            exist.
            PortfolioAllocationUnprocessableEntityError: If stored allocation
            history cannot be parsed.
        """
        try:
            # Only fetch portfolio_allocation_history to reduce bandwidth
            item = self.portfolio_allocation_table_client.get_item(
                key={"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id},
                projection_expression="portfolio_allocation_history"
            )
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                source="DynamoDB",
                operation="loading allocation history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
        
        if not item:
            raise PortfolioAllocationNotFoundError(
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
            )
        
        if "portfolio_allocation_history" not in item: 
            raise PortfolioAllocationUnprocessableEntityError(
                operation="load allocation history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=KeyError("portfolio_allocation_history"),
            )

        # Parse all the snapshots
        portfolio_allocation_history = item["portfolio_allocation_history"]
        result = []
        try:
            for snap in portfolio_allocation_history:
                positions = [
                    PortfolioAllocationPosition(
                        filled_avg_price=float(position["filled_avg_price"]),
                        symbol=position["symbol"],
                        filled_quantity=float(position["filled_quantity"]),
                        direction=int(position["direction"]),
                    )
                    for position in snap["positions"]
                ]
                timestamp = to_utc_from_iso(snap["timestamp"])
                allocation_amount = float(snap["allocation_amount"])
                transaction_id = str(snap["transaction_id"])

                result.append(
                    PortfolioAllocationSnapshot(
                        positions=positions,
                        timestamp=timestamp,
                        allocation_amount=allocation_amount,
                        transaction_id=transaction_id
                    )
                )
        except Exception as e:
            raise PortfolioAllocationUnprocessableEntityError(
                operation="parse allocation history",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e
        
        return result

    def get_n_last_portfolio_allocation_snapshots(self, cognito_user_id: str, portfolio_id: str, n: int) -> List[PortfolioAllocationSnapshot]:
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
        
        portfolio_allocation_history = self.get_portfolio_allocation_history(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
        if n > len(portfolio_allocation_history):
            raise ValueError(
                f"validate n argument '{n}' less than or equal to the number of snapshots '{len(portfolio_allocation_history)}'"
            )
        last_n_snapshots = portfolio_allocation_history[-n:]

        return last_n_snapshots

    
    def get_portfolio_allocation(self, cognito_user_id: str, portfolio_id: str) -> PortfolioAllocation:
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
            portfolio_allocation = PortfolioAllocation(
                portfolio_id=item["portfolio_id"],
                cognito_user_id=item["cognito_user_id"],
                portfolio_allocation_history=[
                    PortfolioAllocationSnapshot(
                        positions=[
                            PortfolioAllocationPosition(
                                filled_avg_price=float(position["filled_avg_price"]),
                                symbol=position["symbol"],
                                filled_quantity=float(position["filled_quantity"]),
                                direction=int(position["direction"]),
                            )
                            for position in positions_snapshot["positions"]
                        ],
                        timestamp=datetime.fromisoformat(positions_snapshot["timestamp"]),
                        allocation_amount= float(positions_snapshot["allocation_amount"]),
                        transaction_id=str(positions_snapshot["transaction_id"])
                    )
                    for positions_snapshot in item["portfolio_allocation_history"]
                ]
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
                "portfolio_allocation_history": [
                    {
                        "positions": [
                            {
                                "filled_avg_price": Decimal(str(position.filled_avg_price)),
                                "symbol": position.symbol,
                                "filled_quantity": Decimal(str(position.filled_quantity)),
                                "direction": int(position.direction),
                            }
                            for position in (positions_snapshot.positions or [])
                        ],
                        "timestamp": positions_snapshot.timestamp.isoformat() if positions_snapshot.timestamp else datetime.utcnow().isoformat(),
                        "allocation_amount": Decimal(str(positions_snapshot.allocation_amount if positions_snapshot.allocation_amount is not None else 0.0)),
                        "transaction_id": str(positions_snapshot.transaction_id or "")
                    }
                    for positions_snapshot in portfolio_allocation.portfolio_allocation_history
                ],
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

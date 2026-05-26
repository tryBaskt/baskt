# backend/repository/portfolio_allocation_repository.py

# Python imports
from __future__ import annotations
from datetime import datetime
from typing import List, Dict
from decimal import Decimal
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError

# Baskt imports
from domain.portfolio_allocation import PortfolioAllocationPosition, PortfolioAllocationSnapshot, PortfolioAllocation
from clients.alpaca_client import AlpacaClient, AlpacaClientError
from core.timeutils import to_utc_from_iso


class PortfolioAllocationInternalServerError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "PORTFOLIO_ALLOCATION_INTERNAL_SERVER_ERROR"


class PortfolioAllocationBadGatewayError(PortfolioAllocationInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="PORTFOLIO_ALLOCATION_BAD_GATEWAY"
        )


class PortfolioAllocationNotFoundError(PortfolioAllocationInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="PORTFOLIO_ALLOCATION_NOT_FOUND",
        )


class PortfolioAllocationUnprocessableEntityError(PortfolioAllocationInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="PORTFOLIO_ALLOCATION_UNPROCESSABLE_ENTITY",
        )



class PortfolioAllocationRepository:
    def __init__(self,
            alpaca_client: AlpacaClient,
            dynamodb_client: DynamoDBClient
    ):
        self.alpaca_client = alpaca_client
        self.portfolio_allocation_table_client = dynamodb_client

    def calculate_positions_current_value(self, portfolio_allocation_snapshot: PortfolioAllocationSnapshot) -> List[Dict[str, float], float, Dict[str, float]]:
        """
        Calculate each position's current portfolio value using latest prices.

        Args:
            portfolio_allocation_snapshot: Snapshot containing historical position state.

        Returns:
            A mapping of symbol to its value.
        """

        curr_positions = portfolio_allocation_snapshot.positions
        symbols = [pos.symbol for pos in curr_positions]
        try:
            quotes = self.alpaca_client.get_latest_price(symbols=symbols)
        except AlpacaClientError as e:
            raise PortfolioAllocationBadGatewayError(
                message=f"Upstream Alpaca client failed while fetching latest prices for portfolio allocation: {e}."
            )

        position_values: Dict[str, float] = {}
        for position in curr_positions:
            current_price = quotes.get(position.symbol)
            if current_price is None:
                raise PortfolioAllocationUnprocessableEntityError(
                    message=f"Missing latest price for symbol '{position.symbol}' while calculating allocation values."
                )
            filled_quantity = float(position.filled_quantity)
            entry_price = float(position.filled_avg_price)

            # Long: value rises with price; short: value falls with price.
            position_values[position.symbol] = filled_quantity * (
                entry_price + position.direction * (current_price - entry_price)
            )
        
        return [position_values, sum(position_values.values()), quotes]

    def calculate_positions_current_weight(self, portfolio_allocation_snapshot: PortfolioAllocationSnapshot) -> List[Dict[str, float], float, Dict[str, float]]:
        """
        Calculate each position's current portfolio weight using latest prices.

        Args:
            portfolio_allocation_snapshot: Snapshot containing historical position state.

        Returns:
            A mapping of symbol to normalized current portfolio weight.
        """

        position_values, total_portfolio_allocation_value, quotes = self.calculate_positions_current_value(portfolio_allocation_snapshot=portfolio_allocation_snapshot)

        if total_portfolio_allocation_value == 0:
            return {symbol: 0.0 for symbol in position_values},0.0, quotes

        return [
            {
                symbol: value / total_portfolio_allocation_value
                for symbol, value in position_values.items()
            }, 
            total_portfolio_allocation_value,
            quotes
        ]

    def is_exists_portfolio_allocation_for_user(self, user_id: str, portfolio_id: str) -> bool:
        """
        Check whether a user has an allocation record for a portfolio.

        Args:
            user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            True if an allocation record exists, otherwise False.

        """

        key = {"user_id": user_id, "portfolio_id": portfolio_id}
        return self.portfolio_allocation_table_client.item_exists(key=key)
    
    def get_portfolio_allocation_history(self, user_id: str, portfolio_id: str) -> List[PortfolioAllocationSnapshot]:
        """
        Retrieve all saved allocation snapshots for a user's portfolio.

        Args:
            user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            A list of allocation snapshots in stored order.
        """
        try:
            # Only fetch portfolio_allocation_history to reduce bandwidth
            item = self.portfolio_allocation_table_client.get_item(
                key={"user_id": user_id, "portfolio_id": portfolio_id},
                projection_expression="portfolio_allocation_history"
            )
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                message=f"Upstream DynamoDB client failed while loading allocation history for user '{user_id}' and portfolio '{portfolio_id}': {e}."
            )
        
        if not item:
            raise PortfolioAllocationNotFoundError(
                message=f"Portfolio allocation not found for user '{user_id}' and portfolio '{portfolio_id}'."
            )
        
        if "portfolio_allocation_history" not in item: return []

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
                transaction_id = str(snap.get("transaction_id", ""))

                result.append(PortfolioAllocationSnapshot(
                    positions=positions,
                    timestamp=timestamp,
                    allocation_amount=allocation_amount,
                    transaction_id=transaction_id
                ))
        except Exception as e:
            raise PortfolioAllocationUnprocessableEntityError(
                message=f"Failed to parse allocation history for user '{user_id}' and portfolio '{portfolio_id}': {e}."
            )
        
        return result

    def get_n_last_portfolio_allocation_snapshots(self, user_id: str, portfolio_id: str, n: int) -> List[PortfolioAllocationSnapshot]:
        """
        Retrieve the last n allocation snapshots for a user's portfolio.

        Args:
            user_id: User identifier.
            portfolio_id: Portfolio identifier.
            n: Number of trailing snapshots to return.

        Returns:
            A list containing the most recent n snapshots.
        """
        
        if n <= 0:
            raise PortfolioAllocationUnprocessableEntityError(
                message=f"n argument '{n}' must be greater than 0."
            )
        
        portfolio_allocation_history = self.get_portfolio_allocation_history(user_id=user_id, portfolio_id=portfolio_id)
        if n > len(portfolio_allocation_history):
            raise PortfolioAllocationUnprocessableEntityError(
                message=f"n argument '{n}' must be less than or equal to the number of snapshots '{len(portfolio_allocation_history)}'."
            )
        last_n_snapshots = portfolio_allocation_history[-n:]

        return last_n_snapshots

    
    def get_portfolio_allocation(self, user_id: str, portfolio_id: str) -> PortfolioAllocation:
        """Load a full portfolio allocation aggregate for a user and portfolio.

        Args:
            user_id: User identifier.
            portfolio_id: Portfolio identifier.

        Returns:
            The portfolio allocation object if found, otherwise None.
        """

        try:
            item = self.portfolio_allocation_table_client.get_item(key={"user_id": user_id, "portfolio_id": portfolio_id})
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                message=f"Upstream DynamoDB client failed while loading portfolio allocation for user '{user_id}' and portfolio '{portfolio_id}': {e}."
            )

        if not item:
            return None

        return PortfolioAllocation(
            portfolio_id=item["portfolio_id"],
            user_id=item["user_id"],
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
                    transaction_id=str(positions_snapshot.get("transaction_id", ""))
                )
                for positions_snapshot in item["portfolio_allocation_history"]
            ],
        )

    def set_portfolio_allocation(self, portfolio_allocation: PortfolioAllocation) -> None:
        """Persist a portfolio allocation aggregate to storage.

        Args:
            portfolio_allocation: Allocation object to serialize and write.

        Returns:
            None.
        """

        item = {
            "user_id": portfolio_allocation.user_id,
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

        try:
            self.portfolio_allocation_table_client.put_item(item=item)
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                message=f"Upstream DynamoDB client failed while persisting portfolio allocation for user '{portfolio_allocation.user_id}' and portfolio '{portfolio_allocation.portfolio_id}': {e}."
            )

    def delete_portfolio_allocation(self, user_id: str, portfolio_id: str):
        try:
            self.portfolio_allocation_table_client.delete_item(key={"user_id": user_id, "portfolio_id": portfolio_id})
        except DynamoDBClientError as e:
            raise PortfolioAllocationBadGatewayError(
                message=f"Upstream DynamoDB client failed while deleting portfolio allocation for user '{user_id}' and portfolio '{portfolio_id}': {e}."
            )

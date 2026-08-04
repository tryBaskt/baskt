# backend/repository/order_repository.py

# Python imports
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
from boto3.dynamodb.conditions import Attr, Key

# Baskt imports
from clients.dynamodb_client import (
    DynamoDBClient,
    DynamoDBClientError,
    to_dynamodb_value,
)
from alpaca.trading.models import Order
from clients.alpaca_broker_client import AlpacaBrokerClient
from core.timeutils import to_utc_from_iso


class OrderInternalServerError(Exception):
    def __init__(self, message: str, code: str = "ORDER_INTERNAL_SERVER_ERROR") -> None:
        """
        Initialize an order repository exception.

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


class OrderBadGatewayError(OrderInternalServerError):
    def __init__(
        self,
        operation: str,
        *,
        transaction_id: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        """
        Initialize an upstream dependency failure for order operations.

        Args:
            operation: Description of the order operation that failed.
            transaction_id: Optional transaction ID involved in the failure.
            portfolio_id: Optional portfolio ID involved in the failure.
            cause: Optional upstream exception that caused the failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        context = []
        if transaction_id:
            context.append(f"transaction '{transaction_id}'")
        if portfolio_id:
            context.append(f"portfolio '{portfolio_id}'")
        message = f"Upstream DynamoDB client failed while {operation}"
        if context:
            message = f"{message} for {', '.join(context)}"
        if cause:
            message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="ORDER_BAD_GATEWAY",
        )


class OrderUnprocessableEntityError(OrderInternalServerError):
    def __init__(self, *, field_name: Optional[str] = None, operation: Optional[str] = None, cause: Optional[Exception] = None) -> None:
        """
        Initialize an invalid order request or parse failure exception.

        Args:
            field_name: Optional required field name that was missing.
            operation: Optional operation that failed to process valid data.
            cause: Optional exception that caused the processing failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        message = f"{field_name} is required." if field_name else f"Failed to {operation}"
        if cause:
            message = f"{message}: {cause}"
        super().__init__(
            message=message,
            code="ORDER_UNPROCESSABLE_ENTITY",
        )


class OrderNotFoundError(OrderInternalServerError):
    def __init__(self, *, transaction_id: Optional[str] = None, portfolio_id: Optional[str] = None) -> None:
        """
        Initialize a missing orders exception.

        Args:
            transaction_id: Optional transaction ID whose orders were not found.
            portfolio_id: Optional portfolio ID whose orders were not found.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        if transaction_id:
            message = f"Orders not found for transaction '{transaction_id}'."
        else:
            message = f"Orders not found for portfolio '{portfolio_id}'."
        super().__init__(
            message=message,
            code="ORDER_NOT_FOUND",
        )



class OrderRepository:
    """
    Repository for persisting and loading trade order records from DynamoDB.
    """

    def __init__(
            self,
            alpaca_broker_client: AlpacaBrokerClient,
            dynamodb_client: DynamoDBClient
        ) -> None:
        """
        Initialize order repository dependencies.

        Args:
            alpaca_broker_client: Alpaca broker client dependency.
            dynamodb_client: DynamoDB client wrapper for order persistence.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        self.alpaca_broker_client = alpaca_broker_client
        self.order_table_client = dynamodb_client

    def _norm_data_types(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize stored DynamoDB order records into application data types.

        Args:
            orders: Raw order records loaded from DynamoDB.

        Returns:
            List[Dict[str, Any]]: Normalized order records with parsed
            timestamps and numeric values.

        Raises:
            OrderUnprocessableEntityError: If an order record cannot be parsed.
        """
        try:
            return [
                {
                    "transaction_id": str(order["transaction_id"]),
                    "order_id": str(order["order_id"]),
                    "cognito_user_id": str(order["cognito_user_id"]),
                    "portfolio_id": str(order["portfolio_id"]),
                    "portfolio_owner_cognito_user_id": str(order["portfolio_owner_cognito_user_id"]),
                    "created_at": to_utc_from_iso(order["created_at"]),
                    "updated_at": to_utc_from_iso(order["updated_at"]) if order["updated_at"] else None,
                    "filled_at": to_utc_from_iso(order["filled_at"]) if order["filled_at"] else None,
                    "symbol": str(order["symbol"]),
                    "notional": str(order["notional"]) if order["notional"] else None,
                    "qty": float(order["qty"]),
                    "filled_qty": float(order["filled_qty"]) if order["filled_qty"] else None,
                    "filled_avg_price": float(order["filled_avg_price"]) if order["filled_avg_price"] else None,
                    "side": str(order["side"]),
                    "status": str(order["status"])
                }
                for order in orders
            ]
        except Exception as e:
            raise OrderUnprocessableEntityError(
                operation="parse order records",
                cause=e,
            ) from e


    def put_orders(self, portfolio_id: str, cognito_user_id: str, transaction_id: str, orders: List[Order], portfolio_owner_cognito_user_id: Optional[str] = None) -> int:
        """
        Persist Alpaca orders for a portfolio transaction.

        Args:
            portfolio_id: Portfolio ID associated with the orders.
            cognito_user_id: Cognito user ID that owns the transaction.
            portfolio_owner_cognito_user_id: Cognito user ID of the portfolio owner.
            transaction_id: Transaction ID shared by the orders.
            orders: Alpaca order models to persist.

        Returns:
            int: Number of order records written.

        Raises:
            OrderUnprocessableEntityError: If an order record cannot be
            converted into the DynamoDB item shape.
            OrderBadGatewayError: If DynamoDB fails while writing orders.
        """
        try:
            items = [
                to_dynamodb_value({"transaction_id": transaction_id,
                 "order_id": str(order.id),
                 "cognito_user_id": cognito_user_id,
                 "portfolio_id": portfolio_id,
                 "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
                 "created_at": order.created_at,
                 "updated_at": order.updated_at,
                 "filled_at": order.filled_at,
                 "symbol": str(order.symbol),
                 "notional": str(order.notional) if order.notional else None,
                 "qty": float(order.qty),
                 "filled_qty": float(order.filled_qty) if order.filled_qty else None,
                 "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                 "side": str(order.side.name),
                 "status": str(order.status.name)
                })
                for order in orders
            ]
        except Exception as e:
            raise OrderUnprocessableEntityError(
                operation="convert orders for persistence",
                cause=e,
            ) from e

        try:
            with self.order_table_client.table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
        except Exception as e:
            raise OrderBadGatewayError(
                operation="persisting orders",
                transaction_id=transaction_id,
                cause=e,
            ) from e

        return len(items)

    def get_orders_by_transaction(self, transaction_id: str) -> List[Dict[str, Any]]:
        """
        Load orders for a transaction ID.

        Args:
            transaction_id: Transaction ID to query.

        Returns:
            List[Dict[str, Any]]: Normalized orders for the transaction.

        Raises:
            OrderBadGatewayError: If DynamoDB fails while loading orders.
            OrderNotFoundError: If no orders are found for the transaction.
            OrderUnprocessableEntityError: If stored order records cannot be parsed.
        """
        try:
            orders = self.order_table_client.query(
                key_condition=Key("transaction_id").eq(str(transaction_id))
            )
        except DynamoDBClientError as e:
            raise OrderBadGatewayError(
                operation="loading orders",
                transaction_id=transaction_id,
                cause=e,
            ) from e

        if not orders:
            raise OrderNotFoundError(
                transaction_id=transaction_id
            )
        return self._norm_data_types(orders=orders)
    
    def get_orders_by_portfolio(self, cognito_user_id: str, portfolio_id: str) -> List[Dict[str, Any]]:
        """
        Load orders for a user's portfolio.

        Args:
            cognito_user_id: Cognito user ID that owns the orders.
            portfolio_id: Portfolio ID to query.

        Returns:
            List[Dict[str, Any]]: Normalized orders for the portfolio.

        Raises:
            OrderBadGatewayError: If DynamoDB fails while loading orders.
            OrderNotFoundError: If no orders are found for the portfolio.
            OrderUnprocessableEntityError: If stored order records cannot be parsed.
        """
        
        try:
            orders = self.order_table_client.query(
                key_condition=Key("cognito_user_id").eq(str(cognito_user_id)) & Key("portfolio_id").eq(str(portfolio_id)),
                IndexName="cognito_user_id_portfolio_id_index"
            )
        except DynamoDBClientError as e:
            raise OrderBadGatewayError(
                operation="loading orders",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not orders:
            raise OrderNotFoundError(
                portfolio_id=portfolio_id
            )
        return self._norm_data_types(orders=orders)
    
    def get_unfilled_orders_by_transaction(self, transaction_id: str) -> List[Dict[str, Any]]:
        """
        Load unfilled orders for a transaction ID.

        Args:
            transaction_id: Transaction ID to query.

        Returns:
            List[Dict[str, Any]]: Normalized orders whose status is not FILLED.

        Raises:
            OrderBadGatewayError: If DynamoDB fails while loading orders.
            OrderNotFoundError: If no orders are found for the transaction.
            OrderUnprocessableEntityError: If stored order records cannot be parsed.
        """
        orders = self.get_orders_by_transaction(transaction_id)
        return [
            order for order in orders if str(order.get("status", "")).upper() != "FILLED"
        ]
    
    def get_portfolio_ids_of_unfilled_orders(
        self,
        cognito_user_id: str,
    ) -> List[Tuple[str,str]]:
        """Get portfolio identifiers with unfilled orders for a Cognito user.

        The DynamoDB query projects only ``portfolio_id``,
        ``portfolio_owner_cognito_user_id``, and ``status`` from the
        user/portfolio global secondary index. Duplicate portfolio IDs are
        removed while preserving their query order.

        Args:
            cognito_user_id: Cognito user ID whose pending portfolios should
                be identified.

        Returns:
            List[Dict[str, str | None]]: Unique portfolio and owner identifiers
                having at least one order whose status is not FILLED. Returns
                an empty list when none exist.

        Raises:
            OrderBadGatewayError: If DynamoDB fails while querying the user.
        """
        try:
            orders = self.order_table_client.query(
                key_condition=Key("cognito_user_id").eq(str(cognito_user_id)),
                IndexName="cognito_user_id_portfolio_id_index",
                ProjectionExpression=(
                    "portfolio_id, portfolio_owner_cognito_user_id, #order_status"
                ),
                ExpressionAttributeNames={"#order_status": "status"},
            )
        except DynamoDBClientError as error:
            raise OrderBadGatewayError(
                operation=f"loading unfilled orders for Cognito user '{cognito_user_id}'",
                cause=error,
            ) from error
        
        portfolio_ids_owner_ids = set()
        for order in orders:
            if str(order.get("status","")).upper() == "FILLED":
                continue
            portfolio_ids_owner_ids.add((order.get("portfolio_id"), order.get("portfolio_owner_cognito_user_id")))

        return list(portfolio_ids_owner_ids)



    def get_unfilled_orders_by_cognito_user_id(
        self,
        cognito_user_id: str,
    ) -> List[Dict[str, Any]]:
        """Load all unfilled orders belonging to a Cognito user.

        The lookup queries the ``cognito_user_id_portfolio_id_index`` global
        secondary index and filters the normalized results by order status.

        Args:
            cognito_user_id: Cognito user ID whose orders should be loaded.

        Returns:
            List[Dict[str, Any]]: Normalized orders whose status is not FILLED.
                Returns an empty list when the user has no orders.

        Raises:
            OrderBadGatewayError: If DynamoDB fails while querying the user.
            OrderUnprocessableEntityError: If an order record cannot be parsed.
        """
        try:
            orders = self.order_table_client.query(
                key_condition=Key("cognito_user_id").eq(str(cognito_user_id)),
                IndexName="cognito_user_id_portfolio_id_index",
            )
        except DynamoDBClientError as error:
            raise OrderBadGatewayError(
                operation=f"loading unfilled orders for Cognito user '{cognito_user_id}'",
                cause=error,
            ) from error

        normalized_orders = self._norm_data_types(orders=orders)
        return [
            order
            for order in normalized_orders
            if str(order.get("status", "")).upper() != "FILLED"
        ]

    def get_unfilled_orders_by_portfolio_id(
        self,
        portfolio_id: str,
    ) -> List[Dict[str, Any]]:
        """Load all unfilled orders associated with a portfolio ID.

        The current order table has no index partitioned by ``portfolio_id``,
        so this lookup uses a DynamoDB scan filtered by portfolio ID.

        Args:
            portfolio_id: Portfolio ID whose orders should be loaded.

        Returns:
            List[Dict[str, Any]]: Normalized orders whose status is not FILLED.
                Returns an empty list when the portfolio has no orders.

        Raises:
            OrderBadGatewayError: If DynamoDB fails while scanning orders.
            OrderUnprocessableEntityError: If an order record cannot be parsed.
        """
        try:
            orders = self.order_table_client.scan(
                filter_expression=Attr("portfolio_id").eq(str(portfolio_id)),
            )
        except DynamoDBClientError as error:
            raise OrderBadGatewayError(
                operation="loading unfilled orders",
                portfolio_id=portfolio_id,
                cause=error,
            ) from error

        normalized_orders = self._norm_data_types(orders=orders)
        return [
            order
            for order in normalized_orders
            if str(order.get("status", "")).upper() != "FILLED"
        ]

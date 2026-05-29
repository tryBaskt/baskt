# backend/repository/order_repository.py

# Python imports
from __future__ import annotations
from typing import List, Dict, Any
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Baskt imports
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError
from alpaca.trading.models import Order
#from clients.alpaca_client import AlpacaClient
from clients.alpaca_broker_client import AlpacaBrokerClient
from core.timeutils import to_utc_from_iso


class OrderInternalServerError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "ORDER_INTERNAL_SERVER_ERROR"


class OrderBadGatewayError(OrderInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_FOLLOWER_BAD_GATEWAY",
        )


class OrderUnprocessableEntityError(OrderInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="ORDER_UNPROCESSABLE_ENTITY",
        )


class OrderNotFoundError(OrderInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="ORDER_NOT_FOUND",
        )



class OrderRepository:
    def __init__(
            self,
            alpaca_broker_client: AlpacaBrokerClient,
            dynamodb_client: DynamoDBClient
        ):
        self.alpaca_broker_client = alpaca_broker_client
        self.order_table_client = dynamodb_client

    def _norm_data_types(self, orders: List[Dict[str, Any]]):
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
                message=f"Failed to parse order records: {e}."
            )


    def put_orders(self, portfolio_id: str, cognito_user_id: str, portfolio_owner_cognito_user_id: str, transaction_id: str, orders: List[Order]):
        if not portfolio_id:
            raise OrderUnprocessableEntityError("portfolio_id is required.")
        if not cognito_user_id:
            raise OrderUnprocessableEntityError("cognito_user_id is required.")
        if not transaction_id:
            raise OrderUnprocessableEntityError("transaction_id is required.")

        items = [
            {"transaction_id": transaction_id,
             "order_id": str(order.id),
             "cognito_user_id": cognito_user_id,
             "portfolio_id": portfolio_id,
             "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
             "created_at": str(order.created_at.isoformat()),
             "updated_at": str(order.updated_at.isoformat()) if order.updated_at else None,
             "filled_at": str(order.filled_at.isoformat()) if order.filled_at else None,
             "symbol": str(order.symbol),
             "notional": str(order.notional) if order.notional else None,         
             "qty": Decimal(str(order.qty)),
             "filled_qty": Decimal(str(order.filled_qty)) if order.filled_qty else None,
             "filled_avg_price": Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
             "side": str(order.side.name),
             "status": str(order.status.name)
            } 
            for order in orders
        ]

        try:
            with self.order_table_client.table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
        except DynamoDBClientError as e:
            raise OrderBadGatewayError(
                message=f"Upstream DynamoDB client failed while persisting orders for transaction '{transaction_id}': {e}."
            )

        return len(items)

    def get_orders_by_transaction(self, transaction_id: str) -> List[Dict]:
        try:
            orders = self.order_table_client.query(
                key_condition=Key("transaction_id").eq(str(transaction_id))
            )
        except DynamoDBClientError as e:
            raise OrderBadGatewayError(
                message=f"Upstream DynamoDB client failed while loading orders for transaction '{transaction_id}': {e}."
            )

        if not orders:
            raise OrderNotFoundError(
                message=f"Orders not found for transaction '{transaction_id}'."
            )
        return self._norm_data_types(orders=orders)
    
    def get_orders_by_portfolio(self, cognito_user_id: str, portfolio_id: str) -> List[Dict]:
        if not cognito_user_id:
            raise OrderUnprocessableEntityError("cognito_user_id is required.")
        if not portfolio_id:
            raise OrderUnprocessableEntityError("portfolio_id is required.")
        
        try:
            orders = self.order_table_client.query(
                key_condition=Key("cognito_user_id").eq(str(cognito_user_id)) & Key("portfolio_id").eq(str(portfolio_id)),
                IndexName="cognito_user_id_portfolio_id_index"
            )
        except DynamoDBClientError as e:
            raise OrderBadGatewayError(
                message=f"Upstream DynamoDB client failed while loading orders for portfolio '{portfolio_id}': {e}."
            )

        if not orders:
            raise OrderNotFoundError(
                message=f"Orders not found for portfolio '{portfolio_id}'."
            )
        return self._norm_data_types(orders=orders)
    
    def get_unfilled_orders_by_transaction(self, transaction_id: str):
        orders = self.get_orders_by_transaction(transaction_id)
        return [
            order for order in orders if str(order.get("status", "")).upper() != "FILLED"
        ]
    

    
    def delete_orders_by_portfolio_id(self, cognito_user_id: str, portfolio_id: str):
        if not cognito_user_id:
            raise OrderUnprocessableEntityError("cognito_user_id is required.")
        if not portfolio_id:
            raise OrderUnprocessableEntityError("portfolio_id is required.")
        
        try:
            orders = self.order_table_client.query(
                key_condition=Key("cognito_user_id").eq(str(cognito_user_id)) & Key("portfolio_id").eq(str(portfolio_id)),
                IndexName="cognito_user_id_portfolio_id_index"
            )
        except DynamoDBClientError as e:
            raise OrderBadGatewayError(
                message=f"Upstream DynamoDB client failed while querying orders for portfolio '{portfolio_id}': {e}."
            )

        if not orders:
            return 0

        try:
            with self.order_table_client.table.batch_writer() as batch:
                for order in orders:
                    batch.delete_item(
                        Key={
                            "transaction_id": order["transaction_id"],
                            "order_id": order["order_id"]
                        }
                    )
        except DynamoDBClientError as e:
            raise OrderBadGatewayError(
                message=f"Upstream DynamoDB client failed while deleting orders for portfolio '{portfolio_id}': {e}."
            )

        return len(orders)
        
        

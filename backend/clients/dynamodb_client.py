# backend/clients/dynamodb.py

# Python imports
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


def to_dynamodb_value(value: Any) -> Any:
    """Recursively convert Python domain values into boto3-compatible values."""
    if isinstance(value, Enum):
        enum_value = value.value
        if isinstance(enum_value, str):
            return enum_value.upper()
        return to_dynamodb_value(enum_value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return to_dynamodb_value(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): to_dynamodb_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [to_dynamodb_value(item) for item in value]
    return value


def dataclass_to_dynamodb_item(value: Any) -> Dict[str, Any]:
    """Convert a dataclass instance into a DynamoDB-ready item dictionary."""
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("value must be a dataclass instance")
    return to_dynamodb_value(asdict(value))


class DynamoDBClientError(Exception):
    """Raised when DynamoDB client operations fail."""

    def __init__(self, message: str, code: str = "DYNAMODB_CLIENT_ERROR"):
        """
        Initialize a DynamoDB client exception with a message and code.

        Args:
            message: Human-readable error details.
            code: Stable application error code identifying the failed operation.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code


class DynamoDBClient:
    """
    Client for interacting with DynamoDB tables.
    """

    def __init__(self, table) -> None:
        """
        Initialize a DynamoDB client wrapper around a table resource.

        Args:
            table: Boto3 DynamoDB Table resource.

        Returns:
            None.
        """

        self.table = table

    def put_item(self, item: Dict[str, Any]) -> None:
        """
        Insert or replace an item in the DynamoDB table.

        Args:
            item: Full DynamoDB item payload to write.

        Returns:
            None.
        """
        try:
            self.table.put_item(Item=item)
        except Exception as e:
            raise DynamoDBClientError(
                message=f"Failed to put item into DynamoDB: {e}",
                code="DYNAMODB_PUT_ITEM_FAILED",
            )

    def item_exists(self, key: Dict[str, Any], consistent_read: bool = False) -> bool:
        """
        Check whether an item exists for the provided primary key.

        Args:
            key: DynamoDB primary key map for the item to check.
            consistent_read: Whether DynamoDB should use a strongly consistent
                read.

        Returns:
            bool: True if the item exists, otherwise False.
        """
        try:
            response = self.table.get_item(
                Key=key,
                ConsistentRead=consistent_read
            )
        except Exception as e:
            raise DynamoDBClientError(
                message=f"Failed to check item existence in DynamoDB: {e}",
                code="DYNAMODB_ITEM_EXISTS_FAILED",
            )
        return "Item" in response

    def get_item(
        self,
        key: Dict[str, Any],
        projection_expression: Optional[str] = None,
        consistent_read: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single item by primary key.

        Args:
            key: DynamoDB primary key map for the item to retrieve.
            projection_expression: Optional DynamoDB projection expression
                limiting which attributes are returned.
            consistent_read: Whether DynamoDB should use a strongly consistent
                read.

        Returns:
            Optional[Dict[str, Any]]: The item if found, otherwise None.
        """
        try:
            if projection_expression:
                response = self.table.get_item(
                    Key=key,
                    ProjectionExpression=projection_expression,
                    ConsistentRead=consistent_read,
                )
            else:
                response = self.table.get_item(
                    Key=key,
                    ConsistentRead=consistent_read,
                )
        except Exception as e:
            raise DynamoDBClientError(
                message=f"Failed to get item from DynamoDB: {e}",
                code="DYNAMODB_GET_ITEM_FAILED",
            )
        return response.get("Item")

    def query(self, key_condition, **kwargs) -> List[Dict[str, Any]]:
        """
        Query table items using a key condition expression.

        Args:
            key_condition: DynamoDB KeyConditionExpression.
            **kwargs: Additional boto3 query parameters.

        Returns:
            List[Dict[str, Any]]: Matching items for the query.
        """
        try:
            response = self.table.query(KeyConditionExpression=key_condition, **kwargs)
        except Exception as e:
            raise DynamoDBClientError(
                message=f"Failed to query DynamoDB: {e}",
                code="DYNAMODB_QUERY_FAILED",
            )
        return response.get("Items", [])

    def scan(self, filter_expression=None, **kwargs) -> List[Dict[str, Any]]:
        """
        Scan table items with an optional filter expression.

        Args:
            filter_expression: Optional DynamoDB FilterExpression.
            **kwargs: Additional boto3 scan parameters.

        Returns:
            List[Dict[str, Any]]: Items returned by the scan operation.
        """
        try:
            if filter_expression is None:
                response = self.table.scan(**kwargs)
            else:
                response = self.table.scan(FilterExpression=filter_expression, **kwargs)
        except Exception as e:
            raise DynamoDBClientError(
                message=f"Failed to scan DynamoDB: {e}",
                code="DYNAMODB_SCAN_FAILED",
            )
        return response.get("Items", [])
    
    def delete_item(self, key: Dict[str, Any]) -> None:
        """
        Delete an item by primary key.

        Args:
            key: DynamoDB primary key map for the item to delete.

        Returns:
            None.
        """
        try:
            self.table.delete_item(Key=key)
        except Exception as e:
            raise DynamoDBClientError(
                message=f"Failed to delete item from DynamoDB: {e}",
                code="DYNAMODB_DELETE_ITEM_FAILED",
            )

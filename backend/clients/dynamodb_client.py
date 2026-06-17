# backend/clients/dynamodb.py

# Python imports
from __future__ import annotations
from typing import Any, Dict, List, Optional


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

    def get_item(self, key: Dict[str, Any], projection_expression: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single item by primary key.

        Args:
            key: DynamoDB primary key map for the item to retrieve.
            projection_expression: Optional DynamoDB projection expression
                limiting which attributes are returned.

        Returns:
            Optional[Dict[str, Any]]: The item if found, otherwise None.
        """
        try:
            if projection_expression:
                response = self.table.get_item(Key=key, ProjectionExpression=projection_expression)
            else:
                response = self.table.get_item(Key=key)
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

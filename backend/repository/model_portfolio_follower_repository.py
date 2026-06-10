# backend/repository/model_portfolio_follower_repository.py

# Python imports
from __future__ import annotations
from typing import List
from boto3.dynamodb.conditions import Key

# Baskt imports
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError
from clients.alpaca_broker_client import AlpacaBrokerClient

class ModelPortfolioFollowerInternalServerError(Exception):
    def __init__(self, message: str, code: str = "MODEL_PORTFOLIO_FOLLOWER_INTERNAL_SERVER_ERROR") -> None:
        """
        Initialize a model portfolio follower repository exception.

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


class ModelPortfolioFollowerBadGatewayError(ModelPortfolioFollowerInternalServerError):
    def __init__(
        self,
        operation: str,
        *,
        cognito_user_id: str | None = None,
        portfolio_id: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize an upstream dependency failure for follower operations.

        Args:
            operation: Description of the follower operation that failed.
            cognito_user_id: Optional follower Cognito user ID involved in the
                operation.
            portfolio_id: Optional model portfolio ID involved in the operation.
            cause: Optional upstream exception that caused the failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        context = []
        if cognito_user_id:
            context.append(f"cognito_user_id '{cognito_user_id}'")
        if portfolio_id:
            context.append(f"portfolio_id '{portfolio_id}'")

        message = f"Upstream DynamoDB client failed while {operation}"
        if context:
            message = f"{message} for {', '.join(context)}"
        if cause:
            message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_FOLLOWER_BAD_GATEWAY",
        )


class ModelPortfolioFollowerNotFoundError(ModelPortfolioFollowerInternalServerError):
    def __init__(self, portfolio_id: str) -> None:
        """
        Initialize a missing followers exception for a model portfolio.

        Args:
            portfolio_id: Model portfolio ID whose followers were not found.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"Followers not found for model portfolio '{portfolio_id}'.",
            code="MODEL_PORTFOLIO_FOLLOWER_NOT_FOUND",
        )


class ModelPortfolioFollowerUnprocessableEntityError(ModelPortfolioFollowerInternalServerError):
    def __init__(
        self,
        *,
        field_name: str | None = None,
        operation: str | None = None,
        portfolio_id: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize an invalid follower request or parse failure exception.

        Args:
            field_name: Optional required field name that was missing.
            operation: Optional operation that failed to process valid data.
            portfolio_id: Optional model portfolio ID involved in the failure.
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
            if portfolio_id:
                message = f"{message} for model portfolio '{portfolio_id}'"
            if cause:
                message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_FOLLOWER_UNPROCESSABLE_ENTITY",
        )




class ModelPortfolioFollowerRepository:
    """
    Repository for managing model portfolio follower records in DynamoDB.
    """

    def __init__(self, dynamodb_client: DynamoDBClient, alpaca_broker_client: AlpacaBrokerClient) -> None:
        """
        Initialize follower repository dependencies.

        Args:
            dynamodb_client: DynamoDB client wrapper for follower persistence.
            alpaca_broker_client: Alpaca client dependency (reserved for related workflows).

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        self.dynamodb = dynamodb_client
        self.alpaca_broker_client = alpaca_broker_client

    def is_model_portfolio_follower(self, cognito_user_id: str, portfolio_id: str) -> bool:
        """
        Check whether a user currently follows a specific model portfolio.

        Args:
            cognito_user_id: Identifier of the follower user.
            portfolio_id: Identifier of the model portfolio.

        Returns:
            bool: True when a follower record exists, otherwise False.

        Raises:
            ModelPortfolioFollowerBadGatewayError: If DynamoDB fails while
            checking the follower relationship.
        """
        try:
            key = {"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id}
            item = self.dynamodb.get_item(key=key)
            return item is not None
        except DynamoDBClientError as e:
            raise ModelPortfolioFollowerBadGatewayError(
                operation="checking follower relationship",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

    def put_model_portfolio_follower(self, cognito_user_id: str, portfolio_id: str, portfolio_owner_cognito_user_id: str) -> None:
        """
        Create a follower relation when one does not already exist.

        Args:
            cognito_user_id: Identifier of the follower user.
            portfolio_id: Identifier of the followed model portfolio.
            portfolio_owner_cognito_user_id: Identifier of the portfolio owner.

        Returns:
            None.

        Raises:
            ModelPortfolioFollowerBadGatewayError: If DynamoDB fails while
            checking or creating the follower relationship.
        """
        try:
            if self.is_model_portfolio_follower(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id):
                return
            item = {
                "cognito_user_id": cognito_user_id,
                "portfolio_id": portfolio_id,
                "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id
            }
            self.dynamodb.put_item(item=item)
        except DynamoDBClientError as e:
            raise ModelPortfolioFollowerBadGatewayError(
                operation="creating follower relationship",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

    def get_model_portfolio_followers(self, portfolio_id: str) -> List[str]:
        """
        Retrieve follower user IDs for a portfolio using the portfolio_id index.

        Args:
            portfolio_id: Identifier of the portfolio to query followers for.

        Returns:
            List[str]: User IDs that currently follow the portfolio.

        Raises:
            ModelPortfolioFollowerUnprocessableEntityError: If follower records
            cannot be parsed.
            ModelPortfolioFollowerBadGatewayError: If DynamoDB fails while
            fetching followers.
            ModelPortfolioFollowerNotFoundError: If no followers are found for
            the portfolio.
        """
        try:
            items = self.dynamodb.query(
                key_condition=Key("portfolio_id").eq(portfolio_id),
                IndexName="portfolio_id_index",
            )
        except DynamoDBClientError as e:
            raise ModelPortfolioFollowerBadGatewayError(
                operation="getting followers",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

        if not items:
            raise ModelPortfolioFollowerNotFoundError(
                portfolio_id=portfolio_id
            )
        
        try:
            return [item["cognito_user_id"] for item in items if "cognito_user_id" in item]
        except Exception as e:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                operation="parse followers",
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

    def delete_model_portfolio_follower(self, cognito_user_id: str, portfolio_id: str) -> None:
        """
        Delete an existing follower relation between a user and a portfolio.

        Args:
            cognito_user_id: Identifier of the follower user.
            portfolio_id: Identifier of the followed model portfolio.

        Returns:
            None.

        Raises:
            ModelPortfolioFollowerBadGatewayError: If DynamoDB fails while
            checking or deleting the follower relationship.
        """
        try:
            if not self.is_model_portfolio_follower(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id):
                return
            key = {"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id}
            self.dynamodb.delete_item(key=key)
        except DynamoDBClientError as e:
            raise ModelPortfolioFollowerBadGatewayError(
                operation="deleting follower relationship",
                cognito_user_id=cognito_user_id,
                portfolio_id=portfolio_id,
                cause=e,
            ) from e

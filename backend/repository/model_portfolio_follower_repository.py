# backend/repository/model_portfolio_repository.py

# Python imports
from __future__ import annotations
from typing import List
from boto3.dynamodb.conditions import Key

# Baskt imports
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError
from clients.alpaca_client import AlpacaClient


class ModelPortfolioFollowerInternalServerError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "MODEL_PORTFOLIO_FOLLOWER_INTERNAL_SERVER_ERROR"


class ModelPortfolioFollowerBadGatewayError(ModelPortfolioFollowerInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_FOLLOWER_BAD_GATEWAY",
        )


class ModelPortfolioFollowerNotFoundError(ModelPortfolioFollowerInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_FOLLOWER_NOT_FOUND",
        )


class ModelPortfolioFollowerUnprocessableEntityError(ModelPortfolioFollowerInternalServerError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_FOLLOWER_UNPROCESSABLE_ENTITY",
        )




class ModelPortfolioFollowerRepository:
    """
    Service for managing model portfolios in DynamoDB.
    """

    def __init__(self, dynamodb_client: DynamoDBClient, alpaca_client: AlpacaClient):
        """
        Initialize follower repository dependencies.

        Args:
            dynamodb_client: DynamoDB client wrapper for follower persistence.
            alpaca_client: Alpaca client dependency (reserved for related workflows).

        Returns:
            None.
        """
        self.dynamodb = dynamodb_client
        self.alpaca_client = alpaca_client

    def is_model_portfolio_follower(self, cognito_user_id: str, portfolio_id: str) -> bool:
        """
        Check whether a user currently follows a specific model portfolio.

        Args:
            cognito_user_id: Identifier of the follower user.
            portfolio_id: Identifier of the model portfolio.

        Returns:
            bool: True when a follower record exists, otherwise False.
        """
        if not cognito_user_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="cognito_user_id is required."
            )
        if not portfolio_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="portfolio_id is required."
            )
        try:
            key = {"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id}
            item = self.dynamodb.get_item(key=key)
            return item is not None
        except DynamoDBClientError as e:
            raise ModelPortfolioFollowerBadGatewayError(
                message=f"Upstream DynamoDB client failed while checking follower relationship for user '{cognito_user_id}' and portfolio '{portfolio_id}': {e}."
            )

    def put_model_portfolio_follower(self, cognito_user_id: str, portfolio_id: str, portfolio_owner_cognito_user_id: str):
        """
        Create a follower relation when one does not already exist.

        Args:
            cognito_user_id: Identifier of the follower user.
            portfolio_id: Identifier of the followed model portfolio.
            portfolio_owner_cognito_user_id: Identifier of the portfolio owner.

        Returns:
            None.
        """
        if not cognito_user_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="cognito_user_id is required."
            )
        if not portfolio_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="portfolio_id is required."
            )
        if not portfolio_owner_cognito_user_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="portfolio_owner_cognito_user_id is required."
            )
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
                message=f"Upstream DynamoDB client failed while creating follower relationship for user '{cognito_user_id}' and portfolio '{portfolio_id}': {e}."
            )

    def get_model_portfolio_followers(self, portfolio_id: str) -> List[str]:
        """
        Retrieve follower user IDs for a portfolio using the portfolio_id index.

        Args:
            portfolio_id: Identifier of the portfolio to query followers for.

        Returns:
            List[str]: User IDs that currently follow the portfolio.
        """
        if not portfolio_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="portfolio_id is required."
            )
        try:
            items = self.dynamodb.query(
                key_condition=Key("portfolio_id").eq(portfolio_id),
                IndexName="portfolio_id-index",
            )
        except DynamoDBClientError as e:
            raise ModelPortfolioFollowerBadGatewayError(
                message=f"Upstream DynamoDB client failed while fetching followers for portfolio '{portfolio_id}': {e}."
            )

        if not items:
            raise ModelPortfolioFollowerNotFoundError(
                message=f"Followers not found for model portfolio '{portfolio_id}'."
            )
        
        try:
            return [item["cognito_user_id"] for item in items if "cognito_user_id" in item]
        except Exception as e:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message=f"Failed to parse followers for model portfolio '{portfolio_id}': {e}"
            )

    def delete_model_portfolio_follower(self, cognito_user_id: str, portfolio_id: str) -> None:
        """
        Delete an existing follower relation between a user and a portfolio.

        Args:
            cognito_user_id: Identifier of the follower user.
            portfolio_id: Identifier of the followed model portfolio.

        Returns:
            None.
        """
        if not cognito_user_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="cognito_user_id is required."
            )
        if not portfolio_id:
            raise ModelPortfolioFollowerUnprocessableEntityError(
                message="portfolio_id is required."
            )
        try:
            if not self.is_model_portfolio_follower(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id):
                return
            key = {"cognito_user_id": cognito_user_id, "portfolio_id": portfolio_id}
            self.dynamodb.delete_item(key=key)
        except DynamoDBClientError as e:
            raise ModelPortfolioFollowerBadGatewayError(
                message=f"Upstream DynamoDB client failed while deleting follower relationship for user '{cognito_user_id}' and portfolio '{portfolio_id}': {e}."
            )
    

# backend/repository/user_trade_lock_repository.py

# Python imports
from __future__ import annotations
from typing import Any, Dict

# AWS imports
from boto3.dynamodb.conditions import Key

# Baskt imports
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError

class UserAccountInternalServerError(Exception):
    def __init__(
        self,
        message: str | None = None,
        code: str = "USER_ACCOUNT_INTERNAL_SERVER_ERROR",
        *,
        field_name: str | None = None,
        operation: str | None = None,
        identifier: str | None = None,
        identifier_type: str | None = None,
        cause: Exception | None = None,
    ):
        """
        Initialize a user account repository exception.

        Args:
            message: Optional human-readable error details.
            code: Stable application error code identifying the failed operation.
            field_name: Optional required field name that was missing.
            operation: Optional operation that failed unexpectedly.
            identifier: Optional identifier involved in the failure.
            identifier_type: Optional type of identifier, such as
                "cognito_user_id" or "email_address".
            cause: Optional exception that caused the failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        if message is None:
            if field_name:
                message = f"{field_name} is required."
            else:
                message = f"Unexpected error while {operation}"
                if identifier and identifier_type:
                    message = f"{message} for {identifier_type} '{identifier}'"
                if cause:
                    message = f"{message}: {cause}"
        super().__init__(message)
        self.code = code

class UserAccountBadGatewayError(UserAccountInternalServerError):
    def __init__(self, operation: str, *, identifier: str | None = None, identifier_type: str | None = None, cause: Exception | None = None):
        """
        Initialize an upstream dependency failure for user account operations.

        Args:
            operation: Description of the user account operation that failed.
            identifier: Optional identifier involved in the failure.
            identifier_type: Optional type of identifier, such as
                "cognito_user_id" or "email_address".
            cause: Optional upstream exception that caused the failure.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        message = f"Upstream DynamoDB client failed while {operation}"
        if identifier and identifier_type:
            message = f"{message} for {identifier_type} '{identifier}'"
        if cause:
            message = f"{message}: {cause}"
        super().__init__(message=message, code="USER_ACCOUNT_BAD_GATEWAY")

class UserAcountNotFoundError(UserAccountInternalServerError):
    def __init__(self, identifier: str, identifier_type: str):
        """
        Initialize a missing user account exception.

        Args:
            identifier: Identifier used to look up the missing account.
            identifier_type: Type of identifier, such as "cognito_user_id" or
                "email_address".

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"No user account for {identifier_type} '{identifier}'",
            code="USER_ACCOUNT_NOT_FOUND",
        )


class UserAccountRepository:
    def __init__(self, client: DynamoDBClient):
        """
        Initialize the user account repository.

        Args:
            client: DynamoDB client wrapper for user-account persistence.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        self.client = client

    def create_user_account(
        self,
        cognito_user_id: str,
        alpaca_account_id: str,
        alpaca_account_number: str,
        account_data: Dict[str, Any],
    ) -> bool:
        """
        Persist a user account mapping.

        Args:
            cognito_user_id: Cognito user ID for the account.
            alpaca_account_id: Alpaca account ID for the account.
            alpaca_account_number: Alpaca account number for the account.
            account_data: Account payload containing contact.email_address.

        Returns:
            bool: True when the account mapping is persisted.

        Raises:
            UserAccountBadGatewayError: If DynamoDB fails while creating the
            account mapping.
            UserAccountInternalServerError: If account data is malformed or an
            unexpected error occurs.
        """
        contact_data: Dict[str, str] = account_data["contact"]
        item = {
            "cognito_user_id": cognito_user_id,
            "alpaca_account_id": alpaca_account_id,
            "alpaca_account_number": alpaca_account_number,
            "email_address": contact_data["email_address"],
        }

        try:
            self.client.put_item(item=item)
            return True
        except DynamoDBClientError as e:
            raise UserAccountBadGatewayError(
                operation="creating user account",
                identifier=cognito_user_id,
                identifier_type="cognito_user_id",
                cause=e,
            ) from e
        except Exception as e:
            raise UserAccountInternalServerError(
                message=(
                    "Unexpected error while creating user account "
                    f"for cognito_user_id '{cognito_user_id}': {e}."
                )
            ) from e
        
    def get_user_account_by_cognito_user_id(self, cognito_user_id: str) -> Dict[str, str]:
        """
        Load a user account mapping by Cognito user ID.

        Args:
            cognito_user_id: Cognito user ID to look up.

        Returns:
            Dict[str, str]: User account mapping.

        Raises:
            UserAccountInternalServerError: If cognito_user_id is missing,
            multiple accounts are found, or an unexpected error occurs.
            UserAcountNotFoundError: If no account is found for the user.
            UserAccountBadGatewayError: If DynamoDB fails while querying.
        """
        if not cognito_user_id:
            raise UserAccountInternalServerError(field_name="cognito_user_id")

        try:
            items = self.client.query(
                key_condition=Key("cognito_user_id").eq(cognito_user_id),
                IndexName="cognito_user_id_index",
                Limit=1,
            )

            if (items is None) or ("cognito_user_id" not in items[0]):
                raise UserAcountNotFoundError(identifier=cognito_user_id, identifier_type="cognito_user_id")
            if len(items) > 1:
                raise UserAccountInternalServerError(
                    operation="querying user account",
                    identifier=cognito_user_id,
                    identifier_type="cognito_user_id",
                )
            return items[0]
        except DynamoDBClientError as e:
            raise UserAccountBadGatewayError(
                operation="querying user account",
                identifier=cognito_user_id,
                identifier_type="cognito_user_id",
                cause=e,
            ) from e
        except Exception as e:
            raise UserAccountInternalServerError(
                message=f"Unexpected error querying user account by cognito_user_id '{cognito_user_id}': {e}."
            ) from e
        
    def get_user_account_by_email_address(self, email_address: str) -> Dict[str, str]:
        """
        Load a user account mapping by email address.

        Args:
            email_address: Email address to look up.

        Returns:
            Dict[str, str]: User account mapping.

        Raises:
            UserAccountInternalServerError: If email_address is missing,
            multiple accounts are found, or an unexpected error occurs.
            UserAcountNotFoundError: If no account is found for the email.
            UserAccountBadGatewayError: If DynamoDB fails while querying.
        """
        if not email_address:
            raise UserAccountInternalServerError(field_name="email_address")

        try:
            items = self.client.query(
                key_condition=Key("email_address").eq(email_address),
                IndexName="email_address_index",
                Limit=1,
            )

            if (items is None) or ("email_address" not in items[0]):
                raise UserAcountNotFoundError(identifier=email_address, identifier_type="email_address")
            if len(items) > 1:
                raise UserAccountInternalServerError(
                    operation="querying user account",
                    identifier=email_address,
                    identifier_type="email_address",
                )
            return items[0]
        except DynamoDBClientError as e:
            raise UserAccountBadGatewayError(
                operation="querying user account",
                identifier=email_address,
                identifier_type="email_address",
                cause=e,
            ) from e
        except Exception as e:
            raise UserAccountInternalServerError(
                message=f"Unexpected error querying user account by email_address '{email_address}': {e}."
            ) from e

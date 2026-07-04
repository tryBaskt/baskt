"""Persistence operations for Baskt accounts."""

from __future__ import annotations

from typing import Any, Optional

from botocore.exceptions import ClientError

from clients.dynamodb_client import (
    DynamoDBClient,
    DynamoDBClientError,
    dataclass_to_dynamodb_item,
    to_dynamodb_value,
)
from domain.baskt_account_domain import (
    BasktAccount,
    DisclosureData,
    ContactData,
    IdentityData,
    AgreementData
)


class BasktAccountRepositoryError(Exception):
    """Base exception for Baskt account persistence failures."""

    def __init__(
        self,
        message: str,
        code: str = "BASKT_ACCOUNT_REPOSITORY_ERROR",
    ) -> None:
        super().__init__(message)
        self.code = code


class BasktAccountBadGatewayError(BasktAccountRepositoryError):
    """Raised when the DynamoDB dependency fails."""

    def __init__(
        self,
        operation: str,
        cognito_user_id: str,
        *,
        cause: Optional[Exception] = None,
    ) -> None:
        message = (
            f"DynamoDB failed while {operation} for Baskt account "
            f"'{cognito_user_id}'"
        )
        if cause:
            message = f"{message}: {cause}"
        super().__init__(message, code="BASKT_ACCOUNT_BAD_GATEWAY")


class BasktAccountUnprocessableEntityError(BasktAccountRepositoryError):
    """Raised when a Baskt account cannot be persisted safely."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="BASKT_ACCOUNT_UNPROCESSABLE_ENTITY",
        )


class BasktAccountNotFoundError(BasktAccountRepositoryError):
    """Raised when a Baskt account not found."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="BASKT_ACCOUNT_NOT_FOUND_ERROR",
        )


class BasktAccountRepository:
    """Repository for Baskt account records stored in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient) -> None:
        self.dynamodb = dynamodb_client

    def write_baskt_account(self, baskt_account: BasktAccount) -> None:
        """Write the complete Baskt account as one DynamoDB item.

        This is an upsert. If an item with the same ``cognito_user_id`` exists,
        DynamoDB replaces it with the newly serialized account.

        Args:
            baskt_account: Complete account domain object to persist.

        Raises:
            BasktAccountUnprocessableEntityError: If the partition key is
                empty or the domain object cannot be serialized.
            BasktAccountBadGatewayError: If DynamoDB rejects the write.
        """
        cognito_user_id = str(baskt_account.cognito_user_id).strip()
        if not cognito_user_id:
            raise BasktAccountUnprocessableEntityError(
                "cognito_user_id is required to write a Baskt account"
            )

        try:
            item = dataclass_to_dynamodb_item(baskt_account)
        except (TypeError, ValueError) as error:
            raise BasktAccountUnprocessableEntityError(
                f"Failed to serialize Baskt account '{cognito_user_id}': {error}"
            ) from error

        try:
            self.dynamodb.put_item(item=item)
        except DynamoDBClientError as error:
            raise BasktAccountBadGatewayError(
                operation="writing account",
                cognito_user_id=cognito_user_id,
                cause=error,
            ) from error


    def get_baskt_account(self, cognito_user_id: str) -> BasktAccount:
        """Get a Baskt account by Cognito user ID.

        Args:
            cognito_user_id: Cognito user ID used as the DynamoDB partition key.

        Returns:
            The matching BasktAccount.

        Raises:
            BasktAccountUnprocessableEntityError: If cognito_user_id is empty.
            BasktAccountBadGatewayError: If DynamoDB rejects the read.
            BasktAccountNotFoundError: If the account does not exist.
        """

        try:
            item = self.dynamodb.get_item(
                key={"cognito_user_id": cognito_user_id}
            )
        except DynamoDBClientError as error:
            raise BasktAccountBadGatewayError(
                operation="getting account",
                cognito_user_id=cognito_user_id,
                cause=error,
            ) from error

        if not item:
            raise BasktAccountNotFoundError(
                f"Baskt account '{cognito_user_id}' was not found"
            )

        try:
            return BasktAccount(
                cognito_user_id=item["cognito_user_id"],
                display_name=item["display_name"],
                alpaca_account_id=item["alpaca_account_id"],
                alpaca_account_number=item["alpaca_account_number"],
                agreements_data=[
                    AgreementData(**agreement)
                    for agreement in item.get("agreements_data", [])
                ],
                disclosure_data=DisclosureData(**item["disclosure_data"]),
                identity_data=IdentityData(**item["identity_data"]),
                contact_data=ContactData(**item["contact_data"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BasktAccountUnprocessableEntityError(
                f"Failed to deserialize Baskt account "
                f"'{cognito_user_id}': {error}"
            ) from error
        

    def _update_account_attribute(
        self,
        cognito_user_id: str,
        attribute_name: str,
        attribute_value: Any,
    ) -> None:
        """Update a single top-level account attribute in DynamoDB."""
        if not cognito_user_id:
            raise BasktAccountUnprocessableEntityError(
                "cognito_user_id is required to update a Baskt account"
            )
        try:
            self.dynamodb.table.update_item(
                Key={"cognito_user_id": cognito_user_id},
                UpdateExpression=f"SET {attribute_name} = :attribute_value",
                ConditionExpression="attribute_exists(cognito_user_id)",
                ExpressionAttributeValues={
                    ":attribute_value": to_dynamodb_value(attribute_value)
                },
            )


        except ClientError as error:
            raise BasktAccountBadGatewayError(
                operation=f"updating {attribute_name}",
                cognito_user_id=cognito_user_id,
                cause=error,
            ) from error
        except Exception as error:
            raise BasktAccountBadGatewayError(
                operation=f"updating {attribute_name}",
                cognito_user_id=cognito_user_id,
                cause=error,
            ) from error

    def update_contact_data(
        self,
        cognito_user_id: str,
        contact_data: ContactData,
    ) -> None:
        """Update only the ``contact_data`` field for one account.

        This performs a partial DynamoDB update against the existing item
        identified by ``cognito_user_id``. The rest of the account record is
        left unchanged.

        Args:
            cognito_user_id: Cognito user ID used as the DynamoDB partition
                key.
            contact_data: New contact data to store for the account.

        Raises:
            BasktAccountUnprocessableEntityError: If the user ID is empty or
                the contact data is not a dataclass instance.
            BasktAccountBadGatewayError: If DynamoDB rejects the update.
        """
        self._update_account_attribute(
            cognito_user_id=cognito_user_id,
            attribute_name="contact_data",
            attribute_value=contact_data,
        )


    def update_disclosure_data(
        self,
        cognito_user_id: str,
        disclosure_data: DisclosureData,
    ) -> None:
        """Update only the ``disclosure_data`` field for one account.

        This performs a partial DynamoDB update against the existing item
        identified by ``cognito_user_id``. The rest of the account record is
        left unchanged.

        Args:
            cognito_user_id: Cognito user ID used as the DynamoDB partition
                key.
            disclosure_data: New disclosure data to store for the account.

        Raises:
            BasktAccountUnprocessableEntityError: If the user ID is empty or
                the disclosure data is not a dataclass instance.
            BasktAccountBadGatewayError: If DynamoDB rejects the update.
        """
        self._update_account_attribute(
            cognito_user_id=cognito_user_id,
            attribute_name="disclosure_data",
            attribute_value=disclosure_data,
        )

    def update_identity_data(
        self,
        cognito_user_id: str,
        identity_data: IdentityData,
    ) -> None:
        """Update only the ``identity_data`` field for one account.

        This performs a partial DynamoDB update against the existing item
        identified by ``cognito_user_id``. The rest of the account record is
        left unchanged.

        Args:
            cognito_user_id: Cognito user ID used as the DynamoDB partition
                key.
            identity_data: New identity data to store for the account.

        Raises:
            BasktAccountUnprocessableEntityError: If the user ID is empty or
                the identity data is not a dataclass instance.
            BasktAccountBadGatewayError: If DynamoDB rejects the update.
        """
        self._update_account_attribute(
            cognito_user_id=cognito_user_id,
            attribute_name="identity_data",
            attribute_value=identity_data,
        )

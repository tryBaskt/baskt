# backend/repository/user_trade_lock_repository.py

# Python imports
from __future__ import annotations
from typing import Any, Dict

# AWS imports
from boto3.dynamodb.conditions import Key

# Baskt imports
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError
from domain.baskt import BasktAccount

class UserAccountInternalServerError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "USER_ACCOUNT_INTERNAL_SERVER_ERROR"

class UserAccountBadGatewayError(UserAccountInternalServerError):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "USER_ACCOUNT_BAD_GATEWAY"

class UserAcountNotFoundError(UserAccountInternalServerError):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "USER_ACCOUNT_NOT_FOUND"


class UserAccountRepository:
    def __init__(self, client: DynamoDBClient):
        self.client = client

    def create_user_account(
        self,
        cognito_user_id: str,
        alpaca_account_id: str,
        alpaca_account_number: str,
        account_data: Dict[str, Any],
    ) -> bool:
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
                message=(
                    "Upstream DynamoDB client failed while creating user account "
                    f"for cognito_user_id '{cognito_user_id}': {e}."
                )
            ) from e
        except Exception as e:
            raise UserAccountInternalServerError(
                message=(
                    "Unexpected error while creating user account "
                    f"for cognito_user_id '{cognito_user_id}': {e}."
                )
            ) from e
        
    def get_user_account_by_email_address(self, email_address: str) -> Dict[str, str]:
        if not email_address:
            raise UserAccountInternalServerError("email_address is required.")

        try:
            items = self.client.query(
                key_condition=Key("email_address").eq(email_address),
                IndexName="email_address-index",
                Limit=1,
            )

            if (items is None) or ("email_address" not in items[0]):
                raise UserAcountNotFoundError(message=f"No user account for email address '{email_address}'")
            if len(items) > 1:
                raise UserAccountInternalServerError(message=f"Multiple accounts under email '{email_address}'")
            return items[0]
        except DynamoDBClientError as e:
            raise UserAccountBadGatewayError(
                message=f"Failed querying user account by email_address '{email_address}': {e}."
            ) from e
        except Exception as e:
            raise UserAccountInternalServerError(
                message=f"Unexpected error querying user account by email_address '{email_address}': {e}."
            ) from e
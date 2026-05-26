# backend/clients/cognito.py

from __future__ import annotations

import secrets
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError
    

class CognitoClientError(Exception):
    """Raised when Cognito client operations fail."""

    def __init__(self, message: str, code: str = "COGNITO_CLIENT_ERROR"):
        super().__init__(message)
        self.code = code


class CognitoClient:
    """
    Minimal Cognito client wrapper for retrieving User Pool metadata (JWKS).
    Keep this narrowly scoped; token verification lives in core/security.py.
    """

    def __init__(
        self,
        *,
        env: str,
        region: str,
        user_pool_id: str,
        app_client_id: str,
    ) -> None:
        self.env = env
        self.region = region
        self.user_pool_id = user_pool_id
        self.app_client_id = app_client_id
        self.cognito_client = boto3.client("cognito-idp", region_name=region)

    def get_user_existence_status(self, email_address: str) -> Dict[str, Any]:
        """
        Return whether a Cognito user exists and, when present, the enable and
        confirmation status.
        """
        try:
            response = self.cognito_client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=email_address,
            )
            return {
                "exists": True,
                "enabled": bool(response.get("Enabled", False)),
                "confirmation_status": response.get("UserStatus"),
            }
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "UserNotFoundException":
                return {
                    "exists": False,
                    "enabled": None,
                    "confirmation_status": None,
                }

            raise CognitoClientError(
                message=f"Failed checking Cognito user existence: {err}",
                code="COGNITO_GET_USER_FAILED",
            ) from err


    def create_cognito_user(self, account_data: Dict[str, Any], password: str | None = None) -> str:
        """
        Create user in AWS Cognito
        """
        contact_data: Dict[str, str] = account_data["contact"]
        identity_data: Dict[str, str] = account_data["identity"]

        email_address = contact_data["email_address"]

        user_attributes = [
            {"Name": "email", "Value": email_address},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "given_name", "Value": identity_data["given_name"]},
            {"Name": "family_name", "Value": identity_data["family_name"]},
        ]

        # Make this operation idempotent for retries from API clients.
        try:
            self.cognito_client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=email_address,
            )
            return email_address
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") != "UserNotFoundException":
                raise CognitoClientError(
                    message=f"Failed checking Cognito user existence: {err}",
                    code="COGNITO_GET_USER_FAILED",
                ) from err
            

        if self.env.lower() == "dev":

            try:
                self.cognito_client.admin_create_user(
                    UserPoolId=self.user_pool_id,
                    Username=email_address,
                    UserAttributes=user_attributes,
                    MessageAction="SUPPRESS",
                    TemporaryPassword=password,
                )

                self.cognito_client.admin_set_user_password(
                    UserPoolId=self.user_pool_id,
                    Username=email_address,
                    Password=password,
                    Permanent=True,
                )

                self.cognito_client.admin_update_user_attributes(
                    UserPoolId=self.user_pool_id,
                    Username=email_address,
                    UserAttributes=user_attributes,
                )

                self.cognito_client.admin_enable_user(
                    UserPoolId=self.user_pool_id,
                    Username=email_address,
                )

                return email_address
            except ClientError as err:
                if err.response.get("Error", {}).get("Code") == "UsernameExistsException":
                    return email_address

                raise CognitoClientError(
                    message=f"Failed to create Cognito user: {err}",
                    code="COGNITO_CREATE_USER_FAILED",
                ) from err
            

    def get_cognito_user(self, cognito_user_id: str) -> Dict[str, Any] | None:
        """
        Fetch Cognito user data by Cognito username/user id.

        Returns:
            A normalized user payload when found, otherwise None.
        """
        try:
            response = self.cognito_client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=cognito_user_id,
            )

            print("cognito user: ", response)

            attributes = {
                attr.get("Name"): attr.get("Value")
                for attr in response.get("UserAttributes", [])
                if attr.get("Name")
            }

            return {
                "username": response.get("Username"),
                "status": bool(response.get("Enabled", False)),
                "user_status": response.get("UserStatus"),
                "created_at": response.get("UserCreateDate"),
                "updated_at": response.get("UserLastModifiedDate"),
                "attributes": attributes,
            }
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "UserNotFoundException":
                return None

            raise CognitoClientError(
                message=f"Failed fetching Cognito user '{cognito_user_id}': {err}",
                code="COGNITO_GET_USER_FAILED",
            ) from err



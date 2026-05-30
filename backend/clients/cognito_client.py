# backend/clients/cognito.py

from __future__ import annotations

from typing import Any, Dict

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError
    

class CognitoClientError(Exception):
    """Raised when Cognito client operations fail."""

    def __init__(self, message: str, code: str = "COGNITO_CLIENT_ERROR"):
        """
        Initialize a Cognito client exception with a message and code.

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


class CognitoClientUserAlreadyExists(CognitoClientError):
    """Raised when a Cognito user already exists for the requested identifier."""

    def __init__(self, identifier: str, identifier_type: str):
        """
        Initialize a duplicate Cognito user exception.

        Args:
            identifier: Email address or Cognito user ID that matched an
                existing user.
            identifier_type: Type of identifier passed in, such as
                "email_address" or "cognito_user_id".

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"Cognito user already exists for {identifier_type} '{identifier}'",
            code="COGNITO_USER_ALREADY_EXISTS",
        )


class CognitoClientCognitoUserNotFound(CognitoClientError):
    """Raised when a Cognito user is not found."""

    def __init__(self, identifier: str, identifier_type: str):
        """
        Initialize a missing Cognito user exception.

        Args:
            identifier: Email address or Cognito user ID used to look up the
                missing user.
            identifier_type: Type of identifier passed in, such as
                "email_address" or "cognito_user_id".

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        super().__init__(
            message=f"Cognito user not found for {identifier_type} '{identifier}'",
            code="COGNITO_USER_NOT_FOUND",
        )

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
        """
        Initialize the Cognito client wrapper.

        Args:
            env: Runtime environment name, such as "dev".
            region: AWS region where the Cognito user pool is hosted.
            user_pool_id: Cognito user pool ID.
            app_client_id: Cognito app client ID associated with this service.

        Returns:
            None.

        Raises:
            Any exception raised by boto3.client if the Cognito Identity
            Provider client cannot be initialized.
        """
        self.env = env
        self.region = region
        self.user_pool_id = user_pool_id
        self.app_client_id = app_client_id
        self.cognito_client = boto3.client("cognito-idp", region_name=region)

    def get_user_existence_status(self, email_address: str) -> Dict[str, Any]:
        """
        Return whether a Cognito user exists and, when present, the enable and
        confirmation status.

        Args:
            email_address: Email address used as the Cognito username.

        Returns:
            Dict[str, Any]: User existence payload with exists, enabled, and
            confirmation_status fields.

        Raises:
            CognitoClientError: If Cognito fails while checking user existence
            or the request cannot be sent.
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
                message=f"Failed to get user existence status for email address '{email_address}': {err}",
                code="COGNITO_GET_USER_EXISTENCE_STATUS_FAILED",
            ) from err
        except (BotoCoreError, ParamValidationError) as err:
            raise CognitoClientError(
                message=f"Failed to get user existence status for email address '{email_address}': {err}",
                code="COGNITO_GET_USER_EXISTENCE_STATUS_FAILED",
            ) from err


    def create_cognito_user(self, account_data: Dict[str, Any], password: str | None = None) -> str:
        """
        Create a user in AWS Cognito.

        Args:
            account_data: Account payload containing contact.email_address and
                identity.given_name/family_name.
            password: Optional password used when creating a dev Cognito user.

        Returns:
            str: Cognito username, currently the user's email address.

        Raises:
            CognitoClientError: If required account data is missing, the
            current environment is unsupported for user creation, Cognito fails
            while creating the user, or the request cannot be sent.
            CognitoClientUserAlreadyExists: If a user already exists with the
            requested email address.
        """
        try:
            contact_data: Dict[str, str] = account_data["contact"]
            identity_data: Dict[str, str] = account_data["identity"]

            email_address = contact_data["email_address"]

            user_attributes = [
                {"Name": "email", "Value": email_address},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "given_name", "Value": identity_data["given_name"]},
                {"Name": "family_name", "Value": identity_data["family_name"]},
            ]
        except KeyError as err:
            raise CognitoClientError(
                message=f"Missing required account data for Cognito user creation: {err}",
                code="COGNITO_CREATE_USER_INVALID_ACCOUNT_DATA",
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
                    raise CognitoClientUserAlreadyExists(
                        identifier=email_address,
                        identifier_type="email_address",
                    ) from err

                raise CognitoClientError(
                    message=f"Failed to create cognito user: {err}",
                    code="COGNITO_CREATE_USER_FAILED",
                ) from err
            except (BotoCoreError, ParamValidationError) as err:
                raise CognitoClientError(
                    message=f"Failed to create cognito user: {err}",
                    code="COGNITO_CREATE_USER_FAILED",
                ) from err

        raise CognitoClientError(
            message=f"Cognito user creation is not supported for environment '{self.env}'",
            code="COGNITO_CREATE_USER_UNSUPPORTED_ENV",
        )
            

    def get_cognito_user(self, cognito_user_id: str) -> Dict[str, Any]:
        """
        Fetch Cognito user data by Cognito username/user id.

        Args:
            cognito_user_id: Cognito username/user ID to fetch.

        Returns:
            Dict[str, Any]: Normalized Cognito user payload with user ID,
            enabled status, confirmation status, timestamps, and attributes.

        Raises:
            CognitoClientCognitoUserNotFound: If the Cognito user does not
            exist.
            CognitoClientError: If Cognito fails while fetching the user or the
            request cannot be sent.
        """
        try:
            response = self.cognito_client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=cognito_user_id,
            )

            attributes = {
                attr.get("Name"): attr.get("Value")
                for attr in response.get("UserAttributes", [])
                if attr.get("Name")
            }

            return {
                "cognito_user_id": response.get("Username"),
                "cognito_enabled_status": bool(response.get("Enabled", False)),
                "cognito_confirmation_status": response.get("UserStatus"),
                "created_at": response.get("UserCreateDate"),
                "updated_at": response.get("UserLastModifiedDate"),
                "attributes": attributes,
            }
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "UserNotFoundException":
                raise CognitoClientCognitoUserNotFound(
                    identifier=cognito_user_id,
                    identifier_type="cognito_user_id",
                ) from err

            raise CognitoClientError(
                message=f"Failed to get cognito user id '{cognito_user_id}': {err}",
                code="COGNITO_GET_COGNITO_USER_FAILED",
            ) from err
        except (BotoCoreError, ParamValidationError) as err:
            raise CognitoClientError(
                message=f"Failed to get cognito user id '{cognito_user_id}': {err}",
                code="COGNITO_GET_COGNITO_USER_FAILED",
            ) from err
        
    def disable_cognito_user(self, cognito_user_id: str) -> bool:
        """
        Disable a Cognito user.

        Args:
            cognito_user_id: Cognito username/user ID to disable.

        Returns:
            bool: True when Cognito returns HTTP 200, otherwise False.

        Raises:
            CognitoClientCognitoUserNotFound: If the Cognito user does not
            exist.
            CognitoClientError: If Cognito fails while disabling the user, the
            response is malformed, or the request cannot be sent.
        """
        try:
            response = self.cognito_client.admin_disable_user(
                UserPoolId=self.user_pool_id,
                Username=cognito_user_id
            )
            response_metadata = response["ResponseMetadata"]
            http_status_code = response_metadata["HTTPStatusCode"]
            return http_status_code == 200
        except ClientError as err:
            error_code = err.response.get("Error", {}).get("Code")
            if error_code == "UserNotFoundException":
                raise CognitoClientCognitoUserNotFound(
                    identifier=cognito_user_id,
                    identifier_type="cognito_user_id",
                ) from err
            raise CognitoClientError(
                message=f"Failed to disable Cognito user '{cognito_user_id}': {err}",
                code="COGNITO_DISABLE_USER_FAILED",
            ) from err
        except (BotoCoreError, KeyError, ParamValidationError) as err:
            raise CognitoClientError(
                message=f"Failed to disable Cognito user '{cognito_user_id}': {err}",
                code="COGNITO_DISABLE_USER_FAILED",
            ) from err

# backend/clients/cognito.py

# Python imports
from __future__ import annotations
from typing import Any, Dict, Optional

# AWS imports
from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError
    

class CognitoClientError(Exception):
    """Raised when Cognito client operations fail."""

    def __init__(self, message: str, code: str = "COGNITO_CLIENT_ERROR") -> None:
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

    def __init__(self, identifier: str, identifier_type: str) -> None:
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

    def __init__(self, identifier: str, identifier_type: str) -> None:
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
    Cognito Identity Provider client wrapper for Baskt user lifecycle lookups
    and admin user creation. Token verification lives in core/security.py.
    """

    def __init__(
        self,
        *,
        env: str,
        region: str,
        user_pool_id: str,
        app_client_id: str,
        cognito_client: Any,
    ) -> None:
        """
        Initialize the Cognito client wrapper.

        Args:
            env: Runtime environment name, such as "dev".
            region: AWS region where the Cognito user pool is hosted.
            user_pool_id: Cognito user pool ID.
            app_client_id: Cognito app client ID associated with this service.
            cognito_client: boto3 Cognito Identity Provider client configured
                with the application's AWS credentials.

        Returns:
            None.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        self.env = env
        self.region = region
        self.user_pool_id = user_pool_id
        self.app_client_id = app_client_id
        self.cognito_client = cognito_client

    def _format_cognito_user_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a Cognito admin_get_user response.

        Args:
            response: Raw Cognito admin_get_user response.

        Returns:
            Dict[str, Any]: Normalized Cognito user payload with Cognito,
            Alpaca, status, timestamp, email, and raw attribute data.

        Raises:
            No exceptions are intentionally raised by this method.
        """
        attributes = {
            attr.get("Name"): attr.get("Value")
            for attr in response.get("UserAttributes", [])
        }

        return {
            "cognito_user_id": response.get("Username"),
            "alpaca_account_id": attributes.get("custom:alpaca_acct_id"),
            "alpaca_account_number": attributes.get("custom:alpaca_acct_num"),
            "email_address": attributes.get("email"),
            "cognito_enabled_status": bool(response.get("Enabled", False)),
            "cognito_confirmation_status": response.get("UserStatus"),
            "created_at": response.get("UserCreateDate"),
            "updated_at": response.get("UserLastModifiedDate"),
            "attributes": attributes,
        }


    def create_cognito_user(
        self, 
        account_data: Dict[str, Any], 
        alpaca_account_id: str, 
        alpaca_account_number: str, 
        password: Optional[str] = None
    ) -> str:
        """
        Create a user in AWS Cognito.

        Args:
            account_data: Account payload containing contact.email_address and
                identity.given_name/family_name.
            alpaca_account_id: Alpaca broker account ID to store as a Cognito
                custom attribute.
            alpaca_account_number: Alpaca broker account number to store as a
                Cognito custom attribute.
            password: Password used when creating a Cognito user and setting
                the user's permanent password.

        Returns:
            str: Cognito user ID/sub.

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
                {"Name": "custom:alpaca_acct_id", "Value": alpaca_account_id},
                {"Name": "custom:alpaca_acct_num", "Value": alpaca_account_number}
            ]
        except KeyError as err:
            raise CognitoClientError(
                message=f"Missing required account data for Cognito user creation: {err}",
                code="COGNITO_CREATE_USER_INVALID_ACCOUNT_DATA",
            ) from err

        # supported_creation_envs = {"dev", "test"}
        # if self.env.lower() not in supported_creation_envs:
        #     raise CognitoClientError(
        #         message=f"Cognito user creation is not supported for environment '{self.env}'",
        #         code="COGNITO_CREATE_USER_UNSUPPORTED_ENV",
        #     )

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

            created_user = self.get_cognito_user_by_email_address(email_address=email_address)
            return created_user["cognito_user_id"]

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

    def delete_cognito_user(
        self,
        cognito_user_id: str
    ) -> None:
        """Delete a user from the configured Cognito user pool.

        Args:
            cognito_user_id: Cognito username/user ID to delete.

        Returns:
            None.

        Raises:
            CognitoClientCognitoUserNotFound: If the Cognito user does not
                exist.
            CognitoClientError: If Cognito rejects the deletion or the request
                cannot be sent.
        """
        try:
            self.cognito_client.admin_delete_user(
                UserPoolId=self.user_pool_id,
                Username=cognito_user_id,
            )
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "UserNotFoundException":
                raise CognitoClientCognitoUserNotFound(
                    identifier=cognito_user_id,
                    identifier_type="cognito_user_id",
                ) from err

            raise CognitoClientError(
                message=f"Failed to delete Cognito user '{cognito_user_id}': {err}",
                code="COGNITO_DELETE_USER_FAILED",
            ) from err
        except (BotoCoreError, ParamValidationError) as err:
            raise CognitoClientError(
                message=f"Failed to delete Cognito user '{cognito_user_id}': {err}",
                code="COGNITO_DELETE_USER_FAILED",
            ) from err

    def is_exists_cognito_user(self, cognito_user_id: str) -> bool:
        """Return whether a user exists in the configured Cognito user pool.

        Args:
            cognito_user_id: Cognito username/user ID to look up.

        Returns:
            bool: True when the user exists, otherwise False.

        Raises:
            CognitoClientError: If Cognito fails for a reason other than the
                user not existing, or the request cannot be sent.
        """
        try:
            self.cognito_client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=cognito_user_id,
            )
            return True
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "UserNotFoundException":
                return False

            raise CognitoClientError(
                message=f"Failed to check whether Cognito user '{cognito_user_id}' exists: {err}",
                code="COGNITO_USER_EXISTS_CHECK_FAILED",
            ) from err
        except (BotoCoreError, ParamValidationError) as err:
            raise CognitoClientError(
                message=f"Failed to check whether Cognito user '{cognito_user_id}' exists: {err}",
                code="COGNITO_USER_EXISTS_CHECK_FAILED",
            ) from err

    def get_cognito_user_by_cognito_user_id(self, cognito_user_id: str) -> Dict[str, Any]:
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
                Username=cognito_user_id
            )

            return self._format_cognito_user_response(response)
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

    def get_cognito_user_by_email_address(self, email_address: str) -> Dict[str, Any]:
        """
        Fetch Cognito user data by email address.

        Args:
            email_address: Email address to look up in the Cognito user pool.

        Returns:
            Dict[str, Any]: Normalized Cognito user payload with user ID,
            Alpaca account ID/number, email address, enabled status,
            confirmation status, timestamps, and attributes.

        Raises:
            CognitoClientCognitoUserNotFound: If no Cognito user exists for the
            email address.
            CognitoClientError: If Cognito fails while fetching the user or
            the request cannot be sent.
        """

        try:
            users = self.cognito_client.list_users(
                UserPoolId=self.user_pool_id,
                Filter=f'email = "{email_address}"',
                Limit=1,
            ).get("Users", [])

            if not users:
                raise CognitoClientCognitoUserNotFound(
                    identifier=email_address,
                    identifier_type="email_address",
                )

            response = self.cognito_client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=users[0]["Username"],
            )

            return self._format_cognito_user_response(response)
        except CognitoClientCognitoUserNotFound:
            raise
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "UserNotFoundException":
                raise CognitoClientCognitoUserNotFound(
                    identifier=email_address,
                    identifier_type="email_address",
                ) from err

            raise CognitoClientError(
                message=f"Failed to get cognito user for email address '{email_address}': {err}",
                code="COGNITO_GET_COGNITO_USER_BY_EMAIL_FAILED",
            ) from err
        except (BotoCoreError, KeyError, ParamValidationError) as err:
            raise CognitoClientError(
                message=f"Failed to get cognito user for email address '{email_address}': {err}",
                code="COGNITO_GET_COGNITO_USER_BY_EMAIL_FAILED",
            ) from err

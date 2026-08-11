"""Persistence operations for model portfolio access grants."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
from uuid import uuid4

from boto3.dynamodb.conditions import Key

from clients.cognito_client import (
    CognitoClient,
    CognitoClientCognitoUserNotFound,
    CognitoClientError,
)
from clients.dynamodb_client import (
    DynamoDBClient,
    DynamoDBClientError,
    to_dynamodb_value,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerBadGatewayError,
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockBadGatewayError,
    ModelPortfolioUpdateLockInternalServerError,
    ModelPortfolioUpdateLockRepository,
)

LOCK_LEASE_SECONDS = 30
READ_LOCK_POLL_SECONDS = 0.25


class ModelPortfolioAccessRepositoryError(Exception):
    """Base exception for model portfolio access persistence failures."""

    def __init__(
        self,
        message: str,
        code: str = "MODEL_PORTFOLIO_ACCESS_REPOSITORY_ERROR",
    ) -> None:
        super().__init__(message)
        self.code = code


class ModelPortfolioAccessBadGatewayError(ModelPortfolioAccessRepositoryError):
    """Raised when an upstream dependency fails."""

    def __init__(
        self,
        operation: str,
        *,
        portfolio_id: Optional[str] = None,
        shared_with_cognito_user_id: Optional[str] = None,
        portfolio_owner_cognito_user_id: Optional[str] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        context = []
        if portfolio_id:
            context.append(f"portfolio_id '{portfolio_id}'")
        if shared_with_cognito_user_id:
            context.append(
                f"shared_with_cognito_user_id '{shared_with_cognito_user_id}'"
            )
        if portfolio_owner_cognito_user_id:
            context.append(
                f"portfolio_owner_cognito_user_id '{portfolio_owner_cognito_user_id}'"
            )

        message = f"Upstream dependency failed while {operation}"
        if context:
            message = f"{message} for {', '.join(context)}"
        if cause:
            message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_ACCESS_BAD_GATEWAY",
        )


class ModelPortfolioAccessUnprocessableEntityError(ModelPortfolioAccessRepositoryError):
    """Raised when an access request is missing required data."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_ACCESS_UNPROCESSABLE_ENTITY",
        )


class ModelPortfolioAccessLockedError(ModelPortfolioAccessRepositoryError):
    """Raised when portfolio access cannot proceed because the portfolio is locked."""

    def __init__(
        self,
        portfolio_id: str,
        operation: str,
        *,
        cause: Optional[Exception] = None,
    ) -> None:
        message = f"Failed to {operation} for model portfolio '{portfolio_id}' access"
        if cause:
            message = f"{message}: {cause}"

        super().__init__(
            message=message,
            code="MODEL_PORTFOLIO_ACCESS_UPDATE_LOCK_ERROR",
        )


class ModelPortfolioAccessUserNotFoundError(ModelPortfolioAccessRepositoryError):
    """Raised when a requested shared user does not exist in Cognito."""

    def __init__(self, identifier: str, identifier_type: str) -> None:
        super().__init__(
            message=(
                f"Cognito user not found for {identifier_type} '{identifier}'"
            ),
            code="MODEL_PORTFOLIO_ACCESS_USER_NOT_FOUND",
        )


class ModelPortfolioAccessNotFoundError(ModelPortfolioAccessRepositoryError):
    """Raised when access cannot be removed because the access for the user does not exist."""

    def __init__(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> None:
        super().__init__(
            message=(
                "Access does not exist "
                f"for portfolio_id '{portfolio_id}', "
                f"shared_with_cognito_user_id '{shared_with_cognito_user_id}'"
            ),
            code="MODEL_PORTFOLIO_ACCESS_NOT_FOUND",
        )


class ModelPortfolioAccessUserIsFollowerError(ModelPortfolioAccessRepositoryError):
    """Raised when access cannot be removed because the user is invested."""

    def __init__(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> None:
        super().__init__(
            message=(
                "Cannot remove access for a user invested in this Baskt "
                f"for portfolio_id '{portfolio_id}', "
                f"shared_with_cognito_user_id '{shared_with_cognito_user_id}'"
            ),
            code="MODEL_PORTFOLIO_ACCESS_USER_IS_FOLLOWER",
        )


class ModelPortfolioAccessRepository:
    """Repository for model portfolio access grants stored in DynamoDB."""

    SHARED_WITH_COGNITO_USER_ID_INDEX = "shared_with_cognito_user_id_index"
    PORTFOLIO_OWNER_COGNITO_USER_ID_INDEX = (
        "portfolio_owner_cognito_user_id_index"
    )

    def __init__(
        self,
        dynamodb_client: DynamoDBClient,
        cognito_client: CognitoClient,
        model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
        model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    ) -> None:
        self.dynamodb = dynamodb_client
        self.cognito_client = cognito_client
        self.model_portfolio_follower_repository = (
            model_portfolio_follower_repository
        )
        self.model_portfolio_update_lock_repository = (
            model_portfolio_update_lock_repository
        )

    def _wait_until_portfolio_update_lock_is_released(
        self,
        *,
        portfolio_id: str,
        wait_seconds: float = LOCK_LEASE_SECONDS,
    ) -> None:
        """Block portfolio-scoped reads while an active update lock exists."""
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        while True:
            try:
                lock = self.model_portfolio_update_lock_repository.get_lock(
                    portfolio_id=portfolio_id
                )
            except ModelPortfolioUpdateLockBadGatewayError as error:
                raise ModelPortfolioAccessBadGatewayError(
                    operation="checking model portfolio update lock",
                    portfolio_id=portfolio_id,
                    cause=error,
                ) from error
            except ModelPortfolioUpdateLockInternalServerError as error:
                raise ModelPortfolioAccessLockedError(
                    portfolio_id=portfolio_id,
                    operation="check update lock",
                    cause=error,
                ) from error

            if not lock:
                return

            expires_at = int(lock.get("expires_at"))
            now = int(time.time())
            if expires_at <= now:
                return

            remaining_wait_seconds = deadline - time.monotonic()
            if remaining_wait_seconds <= 0:
                raise ModelPortfolioAccessLockedError(
                    portfolio_id=portfolio_id,
                    operation="wait for update lock because portfolio is locked",
                )

            sleep_seconds = min(
                READ_LOCK_POLL_SECONDS,
                remaining_wait_seconds,
                max(0.0, float(expires_at - now)),
            )
            time.sleep(sleep_seconds)

    def _acquire_model_portfolio_update_lock(self, *, portfolio_id: str) -> str:
        owner_token = str(uuid4())
        try:
            lock_acquired = self.model_portfolio_update_lock_repository.acquire_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
                lease_seconds=LOCK_LEASE_SECONDS,
            )
        except ModelPortfolioUpdateLockBadGatewayError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="acquiring model portfolio update lock",
                portfolio_id=portfolio_id,
                cause=error,
            ) from error
        except ModelPortfolioUpdateLockInternalServerError as error:
            raise ModelPortfolioAccessLockedError(
                portfolio_id=portfolio_id,
                operation="acquire update lock",
                cause=error,
            ) from error

        if not lock_acquired:
            raise ModelPortfolioAccessLockedError(
                portfolio_id=portfolio_id,
                operation="acquire update lock because portfolio is locked",
            )
        return owner_token

    def _release_model_portfolio_update_lock(
        self,
        *,
        portfolio_id: str,
        owner_token: str,
    ) -> None:
        try:
            self.model_portfolio_update_lock_repository.release_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )
        except ModelPortfolioUpdateLockBadGatewayError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="releasing model portfolio update lock",
                portfolio_id=portfolio_id,
                cause=error,
            ) from error
        except ModelPortfolioUpdateLockInternalServerError as error:
            raise ModelPortfolioAccessLockedError(
                portfolio_id=portfolio_id,
                operation="release update lock",
                cause=error,
            ) from error

    def add_access_for_user(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        shared_with_email: str,
    ) -> None:
        """Grant a user access to a model portfolio."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        portfolio_owner_cognito_user_id = self._required_string(
            "portfolio_owner_cognito_user_id",
            portfolio_owner_cognito_user_id,
        )
        shared_with_email = self._required_string(
            "shared_with_email",
            shared_with_email,
        )

        owner_token = self._acquire_model_portfolio_update_lock(
            portfolio_id=portfolio_id
        )
        try:
            try:
                shared_with_cognito_user_dict = (
                    self.cognito_client.get_cognito_user_by_email_address(
                        email_address=shared_with_email
                    )
                )
            except CognitoClientCognitoUserNotFound as error:
                raise ModelPortfolioAccessUserNotFoundError(
                    identifier=shared_with_email,
                    identifier_type="email_address",
                ) from error
            except CognitoClientError as error:
                raise ModelPortfolioAccessBadGatewayError(
                    operation="looking up shared user by email address",
                    portfolio_id=portfolio_id,
                    portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                    cause=error,
                ) from error

            self._write_access_item(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                shared_with_cognito_user_id=shared_with_cognito_user_dict[
                    "cognito_user_id"
                ],
                shared_with_email=shared_with_email,
            )
        finally:
            self._release_model_portfolio_update_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )

    def add_access_for_user_by_cognito_user_id(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        shared_with_cognito_user_id: str,
    ) -> None:
        """Grant access by Cognito user ID after loading the user's email."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        portfolio_owner_cognito_user_id = self._required_string(
            "portfolio_owner_cognito_user_id",
            portfolio_owner_cognito_user_id,
        )
        shared_with_cognito_user_id = self._required_string(
            "shared_with_cognito_user_id",
            shared_with_cognito_user_id,
        )

        owner_token = self._acquire_model_portfolio_update_lock(
            portfolio_id=portfolio_id
        )
        try:
            try:
                shared_with_cognito_user_dict = (
                    self.cognito_client.get_cognito_user_by_cognito_user_id(
                        cognito_user_id=shared_with_cognito_user_id
                    )
                )
            except CognitoClientCognitoUserNotFound as error:
                raise ModelPortfolioAccessUserNotFoundError(
                    identifier=shared_with_cognito_user_id,
                    identifier_type="cognito_user_id",
                ) from error
            except CognitoClientError as error:
                raise ModelPortfolioAccessBadGatewayError(
                    operation="looking up shared user by Cognito user ID",
                    portfolio_id=portfolio_id,
                    shared_with_cognito_user_id=shared_with_cognito_user_id,
                    portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                    cause=error,
                ) from error

            shared_with_email = shared_with_cognito_user_dict.get("email_address")
            if not shared_with_email:
                raise ModelPortfolioAccessUnprocessableEntityError(
                    "email_address is required on the shared Cognito user"
                )

            self._write_access_item(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                shared_with_email=shared_with_email,
            )
        finally:
            self._release_model_portfolio_update_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )

    def write_access_item_without_lock_by_cognito_user_id(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        shared_with_cognito_user_id: str,
    ) -> None:
        """Write access by Cognito user ID when the caller already owns the lock."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        portfolio_owner_cognito_user_id = self._required_string(
            "portfolio_owner_cognito_user_id",
            portfolio_owner_cognito_user_id,
        )
        shared_with_cognito_user_id = self._required_string(
            "shared_with_cognito_user_id",
            shared_with_cognito_user_id,
        )

        try:
            shared_with_cognito_user_dict = (
                self.cognito_client.get_cognito_user_by_cognito_user_id(
                    cognito_user_id=shared_with_cognito_user_id
                )
            )
        except CognitoClientCognitoUserNotFound as error:
            raise ModelPortfolioAccessUserNotFoundError(
                identifier=shared_with_cognito_user_id,
                identifier_type="cognito_user_id",
            ) from error
        except CognitoClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="looking up shared user by Cognito user ID",
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                cause=error,
            ) from error

        shared_with_email = shared_with_cognito_user_dict.get("email_address")
        if not shared_with_email:
            raise ModelPortfolioAccessUnprocessableEntityError(
                "email_address is required on the shared Cognito user"
            )

        self._write_access_item(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            shared_with_cognito_user_id=shared_with_cognito_user_id,
            shared_with_email=shared_with_email,
        )

    def remove_access_for_user(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> None:
        """Remove a user's access grant for a model portfolio."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        shared_with_cognito_user_id = self._required_string(
            "shared_with_cognito_user_id",
            shared_with_cognito_user_id,
        )

        owner_token = self._acquire_model_portfolio_update_lock(
            portfolio_id=portfolio_id
        )
        try:
            try:
                if self.model_portfolio_follower_repository.is_model_portfolio_follower(
                    cognito_user_id=shared_with_cognito_user_id,
                    portfolio_id=portfolio_id,
                ):
                    raise ModelPortfolioAccessUserIsFollowerError(
                        portfolio_id=portfolio_id,
                        shared_with_cognito_user_id=shared_with_cognito_user_id,
                    )

                try:
                    access_item = self.dynamodb.get_item(
                        key={
                            "portfolio_id": portfolio_id,
                            "shared_with_cognito_user_id": shared_with_cognito_user_id,
                        }
                    )
                except DynamoDBClientError as error:
                    raise ModelPortfolioAccessBadGatewayError(
                        operation="checking model portfolio access before removing access",
                        portfolio_id=portfolio_id,
                        shared_with_cognito_user_id=shared_with_cognito_user_id,
                        cause=error,
                    ) from error

                if access_item is None:
                    raise ModelPortfolioAccessNotFoundError(
                        portfolio_id=portfolio_id,
                        shared_with_cognito_user_id=shared_with_cognito_user_id,
                    )
            except ModelPortfolioFollowerBadGatewayError as error:
                raise ModelPortfolioAccessBadGatewayError(
                    operation="checking follower relationship before removing access",
                    portfolio_id=portfolio_id,
                    shared_with_cognito_user_id=shared_with_cognito_user_id,
                    cause=error,
                ) from error

            try:
                self.dynamodb.delete_item(
                    key={
                        "portfolio_id": portfolio_id,
                        "shared_with_cognito_user_id": shared_with_cognito_user_id,
                    }
                )
            except DynamoDBClientError as error:
                raise ModelPortfolioAccessBadGatewayError(
                    operation="removing model portfolio access",
                    portfolio_id=portfolio_id,
                    shared_with_cognito_user_id=shared_with_cognito_user_id,
                    cause=error,
                ) from error
        finally:
            self._release_model_portfolio_update_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )

    def has_access(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> bool:
        """Return whether a user has an active access grant."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        shared_with_cognito_user_id = self._required_string(
            "shared_with_cognito_user_id",
            shared_with_cognito_user_id,
        )
        self._wait_until_portfolio_update_lock_is_released(
            portfolio_id=portfolio_id
        )

        try:
            item = self.dynamodb.get_item(
                key={
                    "portfolio_id": portfolio_id,
                    "shared_with_cognito_user_id": shared_with_cognito_user_id,
                }
            )
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="checking model portfolio access",
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                cause=error,
            ) from error

        return bool(item is not None)

    def get_accesses_for_portfolio(
        self,
        *,
        portfolio_id: str,
        wait_for_lock: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return all access grants for one model portfolio."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        if wait_for_lock:
            self._wait_until_portfolio_update_lock_is_released(
                portfolio_id=portfolio_id
            )

        try:
            return self.dynamodb.query(
                key_condition=Key("portfolio_id").eq(portfolio_id),
            )
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="getting model portfolio access grants",
                portfolio_id=portfolio_id,
                cause=error,
            ) from error

    def get_accesses_shared_with_user(
        self,
        *,
        shared_with_cognito_user_id: str,
    ) -> List[Dict[str, Any]]:
        """Return portfolio access grants shared with one user."""
        shared_with_cognito_user_id = self._required_string(
            "shared_with_cognito_user_id",
            shared_with_cognito_user_id,
        )

        try:
            return self.dynamodb.query(
                key_condition=Key("shared_with_cognito_user_id").eq(
                    shared_with_cognito_user_id
                ),
                IndexName=self.SHARED_WITH_COGNITO_USER_ID_INDEX,
            )
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="getting model portfolio access grants shared with user",
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                cause=error,
            ) from error

    def get_accesses_granted_by_owner(
        self,
        *,
        portfolio_owner_cognito_user_id: str,
    ) -> List[Dict[str, Any]]:
        """Return portfolio access grants created by one portfolio owner."""
        portfolio_owner_cognito_user_id = self._required_string(
            "portfolio_owner_cognito_user_id",
            portfolio_owner_cognito_user_id,
        )

        try:
            return self.dynamodb.query(
                key_condition=Key("portfolio_owner_cognito_user_id").eq(
                    portfolio_owner_cognito_user_id
                ),
                IndexName=self.PORTFOLIO_OWNER_COGNITO_USER_ID_INDEX,
            )
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="getting model portfolio access grants by owner",
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                cause=error,
            ) from error

    def _required_string(self, field_name: str, value: str) -> str:
        normalized_value = str(value).strip()
        if not normalized_value:
            raise ModelPortfolioAccessUnprocessableEntityError(
                f"{field_name} is required"
            )
        return normalized_value

    def _write_access_item(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        shared_with_cognito_user_id: str,
        shared_with_email: str,
    ) -> None:
        item = {
            "portfolio_id": portfolio_id,
            "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
            "shared_with_cognito_user_id": shared_with_cognito_user_id,
            "shared_with_cognito_user_email": shared_with_email.strip().lower(),
            "granted_access_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self.dynamodb.put_item(item=to_dynamodb_value(item))
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="granting model portfolio access",
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                cause=error,
            ) from error

"""Persistence operations for model portfolio access grants."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
from uuid import uuid4
from core.timeutils import to_utc_from_iso

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
from domain.model_portfolio_domain import (
    ModelPortfolioAccessRecord,
    ModelPortfolioAccessRemovalResult,
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


    def _required_string(self, field_name: str, value: str) -> str:
        if value is None:
            raise ModelPortfolioAccessUnprocessableEntityError(
                f"{field_name} is required"
            )
        normalized_value = str(value).strip()
        if not normalized_value:
            raise ModelPortfolioAccessUnprocessableEntityError(
                f"{field_name} is required"
            )
        return normalized_value


    def _write_access_record(
        self,
        access_record: ModelPortfolioAccessRecord,
    ) -> None:
        """Persist a normalized model portfolio access record."""
        portfolio_id = self._required_string("portfolio_id",access_record.portfolio_id)
        portfolio_owner_cognito_user_id = self._required_string("portfolio_owner_cognito_user_id",access_record.portfolio_owner_cognito_user_id)
        shared_with_cognito_user_id = self._required_string("shared_with_cognito_user_id",access_record.shared_with_cognito_user_id)
        shared_with_email = self._required_string("shared_with_email",access_record.shared_with_email)
        granted_access_by = self._required_string("granted_access_by",access_record.granted_access_by)
        status = self._required_string("status", access_record.status)
        if granted_access_by not in {"ALLOCATION", "PORTFOLIO_OWNER"}:
            raise ModelPortfolioAccessUnprocessableEntityError(
                "granted_access_by must be ALLOCATION or PORTFOLIO_OWNER"
            )
        if status not in {"ACTIVE", "TO_BE_DELETED"}:
            raise ModelPortfolioAccessUnprocessableEntityError(
                "status must be ACTIVE or TO_BE_DELETED"
            )

        existing_access_record = self.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=shared_with_cognito_user_id,
        )
        if (
            existing_access_record is not None
            and existing_access_record.granted_access_by == "PORTFOLIO_OWNER"
            and granted_access_by == "ALLOCATION"
        ):
            return

        item = {
            "portfolio_id": portfolio_id,
            "portfolio_owner_cognito_user_id": portfolio_owner_cognito_user_id,
            "shared_with_cognito_user_id": shared_with_cognito_user_id,
            "shared_with_email": shared_with_email.strip().lower(),
            "granted_access_at": access_record.granted_access_at.isoformat(),
            "granted_access_by": granted_access_by,
            "status": status,
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


    def batch_update_access_record(
        self,
        *,
        portfolio_id: str,
        conditional_attributes: Dict[str, Any],
        value_attributes: Dict[str, Any],
        wait_for_lock: bool = True,
    ) -> int:
        """Batch rewrite access records matching attribute equality conditions."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        if not conditional_attributes:
            raise ModelPortfolioAccessUnprocessableEntityError(
                "conditional_attributes is required"
            )
        if not value_attributes:
            raise ModelPortfolioAccessUnprocessableEntityError(
                "value_attributes is required"
            )
        blocked_update_fields = {"portfolio_id", "shared_with_cognito_user_id"}
        if blocked_update_fields & set(value_attributes):
            raise ModelPortfolioAccessUnprocessableEntityError(
                "Access record key fields cannot be updated"
            )

        access_records = self.get_accesses_for_portfolio(
            portfolio_id=portfolio_id,
            wait_for_lock=wait_for_lock,
        )
        updated_items = []
        for access_record in access_records:
            access_item = {
                "portfolio_id": access_record.portfolio_id,
                "portfolio_owner_cognito_user_id": access_record.portfolio_owner_cognito_user_id,
                "shared_with_cognito_user_id": access_record.shared_with_cognito_user_id,
                "shared_with_email": access_record.shared_with_email.strip().lower(),
                "granted_access_at": access_record.granted_access_at.isoformat(),
                "granted_access_by": access_record.granted_access_by,
                "status": access_record.status,
            }
            if any(
                access_item.get(attribute_name) != expected_value
                for attribute_name, expected_value in conditional_attributes.items()
            ):
                continue

            updated_item = {**access_item, **value_attributes}
            updated_items.append(
                to_dynamodb_value(updated_item)
            )

        try:
            self.dynamodb.batch_put_items(items=updated_items)
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="batch updating model portfolio access records",
                portfolio_id=portfolio_id,
                cause=error,
            ) from error

        return len(updated_items)


    def get_access_record(self, portfolio_id: str, shared_with_cognito_user_id: str) -> Optional[ModelPortfolioAccessRecord]:
        portfolio_id = self._required_string("portfolio_id",portfolio_id)
        shared_with_cognito_user_id = self._required_string("shared_with_cognito_user_id",shared_with_cognito_user_id)

        try:
            item = self.dynamodb.get_item(key={"portfolio_id": portfolio_id, "shared_with_cognito_user_id": shared_with_cognito_user_id})
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="getting model portfolio access record",
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                cause=error,
            ) from error

        if item is None:
            return None

        try:
            access_record = ModelPortfolioAccessRecord(
                portfolio_id=item["portfolio_id"],
                portfolio_owner_cognito_user_id=item["portfolio_owner_cognito_user_id"],
                shared_with_cognito_user_id=item["shared_with_cognito_user_id"],
                shared_with_email=item["shared_with_email"],
                granted_access_at=to_utc_from_iso(item["granted_access_at"]),
                granted_access_by=item["granted_access_by"],
                status=item["status"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ModelPortfolioAccessUnprocessableEntityError(
                "Stored model portfolio access record is invalid "
                f"for portfolio_id '{portfolio_id}' and "
                f"shared_with_cognito_user_id '{shared_with_cognito_user_id}': {error}"
            ) from error

        return access_record


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

    def add_access_via_email(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        shared_with_email: str,
        granted_access_by: str
    ) -> None:
        """Grant a user access to a model portfolio."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        portfolio_owner_cognito_user_id = self._required_string("portfolio_owner_cognito_user_id",portfolio_owner_cognito_user_id)
        shared_with_email = self._required_string("shared_with_email",shared_with_email)

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
            shared_with_cognito_user_id = shared_with_cognito_user_dict["cognito_user_id"]
            access_record = ModelPortfolioAccessRecord(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                shared_with_email=shared_with_email,
                granted_access_at=datetime.now(timezone.utc),
                granted_access_by=granted_access_by,
                status="ACTIVE"
            )
            self._write_access_record(access_record=access_record)
        finally:
            self._release_model_portfolio_update_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )

    def add_access_via_cognito_user_id(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        shared_with_cognito_user_id: str,
        granted_access_by: str
    ) -> None:
        """Grant access by Cognito user ID after loading the user's email."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        portfolio_owner_cognito_user_id = self._required_string("portfolio_owner_cognito_user_id",portfolio_owner_cognito_user_id)
        shared_with_cognito_user_id = self._required_string("shared_with_cognito_user_id",shared_with_cognito_user_id)

        owner_token = self._acquire_model_portfolio_update_lock(
            portfolio_id=portfolio_id
        )
        try:
            try:
                shared_with_cognito_user_dict = self.cognito_client.get_cognito_user_by_cognito_user_id(cognito_user_id=shared_with_cognito_user_id)
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

            shared_with_email = shared_with_cognito_user_dict["email_address"]
            if not shared_with_email:
                raise ModelPortfolioAccessUnprocessableEntityError(
                    "email_address is required on the shared Cognito user"
                )

            access_record = ModelPortfolioAccessRecord(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                shared_with_email=shared_with_email,
                granted_access_at=datetime.now(timezone.utc),
                granted_access_by=granted_access_by,
                status="ACTIVE"
            )

            self._write_access_record(access_record=access_record)
        finally:
            self._release_model_portfolio_update_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )

    def add_access_via_cognito_user_id_without_lock(
        self,
        *,
        portfolio_id: str,
        portfolio_owner_cognito_user_id: str,
        shared_with_cognito_user_id: str,
        granted_access_by: str
    ) -> None:
        """Write access by Cognito user ID when the caller already owns the lock."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        portfolio_owner_cognito_user_id = self._required_string("portfolio_owner_cognito_user_id",portfolio_owner_cognito_user_id)
        shared_with_cognito_user_id = self._required_string("shared_with_cognito_user_id",shared_with_cognito_user_id)

        try:
            shared_with_cognito_user_dict = self.cognito_client.get_cognito_user_by_cognito_user_id(cognito_user_id=shared_with_cognito_user_id)
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

        shared_with_email = shared_with_cognito_user_dict["email_address"]
        if not shared_with_email:
            raise ModelPortfolioAccessUnprocessableEntityError(
                "email_address is required on the shared Cognito user"
            )

        access_record = ModelPortfolioAccessRecord(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            shared_with_cognito_user_id=shared_with_cognito_user_id,
            shared_with_email=shared_with_email,
            granted_access_at=datetime.now(timezone.utc),
            granted_access_by=granted_access_by,
            status="ACTIVE",
        )

        self._write_access_record(access_record=access_record)

    def remove_access_via_cognito_user_id(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> ModelPortfolioAccessRemovalResult:
        """Remove a user's access grant for a model portfolio."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        shared_with_cognito_user_id = self._required_string("shared_with_cognito_user_id",shared_with_cognito_user_id)

        owner_token = self._acquire_model_portfolio_update_lock(
            portfolio_id=portfolio_id
        )
        try:
            try:
                access_record = self.get_access_record(portfolio_id=portfolio_id, shared_with_cognito_user_id=shared_with_cognito_user_id)
                if not access_record:
                    raise ModelPortfolioAccessNotFoundError(
                        portfolio_id=portfolio_id,
                        shared_with_cognito_user_id=shared_with_cognito_user_id
                    )

                if not self.model_portfolio_follower_repository.is_model_portfolio_follower(cognito_user_id=shared_with_cognito_user_id, portfolio_id=portfolio_id):
                    self.dynamodb.delete_item(
                        key={"portfolio_id": portfolio_id, "shared_with_cognito_user_id": shared_with_cognito_user_id}
                    )
                    return ModelPortfolioAccessRemovalResult(
                        removed=True,
                        pending_removal=False,
                    )

                access_record.status = "TO_BE_DELETED"
                self._write_access_record(access_record=access_record)
                return ModelPortfolioAccessRemovalResult(
                    removed=False,
                    pending_removal=True,
                    message=(
                        "User is currently following this model portfolio. "
                        "Access will be removed after they withdraw all their money."
                    ),
                )

            except ModelPortfolioFollowerBadGatewayError as error:
                raise ModelPortfolioAccessBadGatewayError(
                    operation="checking follower relationship before removing access",
                    portfolio_id=portfolio_id,
                    shared_with_cognito_user_id=shared_with_cognito_user_id,
                    cause=error,
                ) from error

        finally:
            self._release_model_portfolio_update_lock(
                portfolio_id=portfolio_id,
                owner_token=owner_token,
            )

    def has_non_allocation_access(
        self,
        portfolio_id: str,
        shared_with_cognito_user_id: str
    ):
        access_record = self.get_access_record(portfolio_id=portfolio_id, shared_with_cognito_user_id=shared_with_cognito_user_id)
        if not access_record:
            return False

        return access_record.status == "ACTIVE" and access_record.granted_access_by == "PORTFOLIO_OWNER"
    
    def has_access(
        self,
        *,
        portfolio_id: str,
        shared_with_cognito_user_id: str,
    ) -> bool:
        """Return whether a user has an active access grant."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        shared_with_cognito_user_id = self._required_string("shared_with_cognito_user_id",shared_with_cognito_user_id)

        self._wait_until_portfolio_update_lock_is_released(
            portfolio_id=portfolio_id
        )

        try:
            return self.dynamodb.item_exists(
                key={"portfolio_id": portfolio_id, "shared_with_cognito_user_id": shared_with_cognito_user_id}
            )

        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="checking model portfolio access",
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                cause=error,
            ) from error


    def get_accesses_for_portfolio(
        self,
        *,
        portfolio_id: str,
        wait_for_lock: bool = True,
    ) -> List[ModelPortfolioAccessRecord]:
        """Return all access grants for one model portfolio."""
        portfolio_id = self._required_string("portfolio_id", portfolio_id)
        if wait_for_lock:
            self._wait_until_portfolio_update_lock_is_released(
                portfolio_id=portfolio_id
            )

        try:
            items = self.dynamodb.query(
                key_condition=Key("portfolio_id").eq(portfolio_id),
            )

            return [
                ModelPortfolioAccessRecord(
                    portfolio_id=item["portfolio_id"],
                    portfolio_owner_cognito_user_id=item["portfolio_owner_cognito_user_id"],
                    shared_with_cognito_user_id=item["shared_with_cognito_user_id"],
                    shared_with_email=item["shared_with_email"],
                    granted_access_at=to_utc_from_iso(item["granted_access_at"]),
                    granted_access_by=item["granted_access_by"],
                    status=item["status"]
                )
                for item in items
            ]

        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="getting model portfolio access grants",
                portfolio_id=portfolio_id,
                cause=error,
            ) from error

    def get_accesses_for_shared_with_user(
        self,
        *,
        shared_with_cognito_user_id: str,
    ) -> List[ModelPortfolioAccessRecord]:
        """Return portfolio access grants shared with one user."""
        shared_with_cognito_user_id = self._required_string("shared_with_cognito_user_id",shared_with_cognito_user_id)

        try:
            items = self.dynamodb.query(
                key_condition=Key("shared_with_cognito_user_id").eq(
                    shared_with_cognito_user_id
                ),
                IndexName=self.SHARED_WITH_COGNITO_USER_ID_INDEX,
            )

            return [
                ModelPortfolioAccessRecord(
                    portfolio_id=item["portfolio_id"],
                    portfolio_owner_cognito_user_id=item["portfolio_owner_cognito_user_id"],
                    shared_with_cognito_user_id=item["shared_with_cognito_user_id"],
                    shared_with_email=item["shared_with_email"],
                    granted_access_at=to_utc_from_iso(item["granted_access_at"]),
                    granted_access_by=item["granted_access_by"],
                    status=item["status"]
                )
                for item in items
            ]
        except DynamoDBClientError as error:
            raise ModelPortfolioAccessBadGatewayError(
                operation="getting model portfolio access grants shared with user",
                shared_with_cognito_user_id=shared_with_cognito_user_id,
                cause=error,
            ) from error

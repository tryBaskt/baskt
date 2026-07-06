# backend/repository/user_trade_lock_repository.py

# Python imports
from __future__ import annotations
import time
from typing import Any, Dict, Optional
from botocore.exceptions import ClientError

# Baskt imports
from clients.dynamodb_client import (
	DynamoDBClient,
	DynamoDBClientError,
	to_dynamodb_value,
)


class UserTradeLockInternalServerError(Exception):
	def __init__(self, message: str, code: str = "USER_TRADE_LOCK_INTERNAL_SERVER_ERROR") -> None:
		"""
		Initialize a user trade lock repository exception.

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


class UserTradeLockBadGatewayError(UserTradeLockInternalServerError):
	def __init__(self, operation: str, cognito_user_id: str, *, source: str, cause: Optional[Exception] = None) -> None:
		"""
		Initialize an upstream dependency failure for user trade lock operations.

		Args:
			operation: Description of the lock operation that failed.
			cognito_user_id: Cognito user ID involved in the failure.
			source: Upstream dependency that failed.
			cause: Optional upstream exception that caused the failure.

		Returns:
			None.

		Raises:
			No exceptions are intentionally raised by this method.
		"""
		message = f"Upstream {source} client failed while {operation} for user '{cognito_user_id}'"
		if cause:
			message = f"{message}: {cause}"
		super().__init__(
			message=message,
			code="USER_TRADE_LOCK_BAD_GATEWAY",
		)


class UserTradeLockUnprocessableEntityError(UserTradeLockInternalServerError):
	def __init__(self, field_name: str, constraint: str) -> None:
		"""
		Initialize an invalid user trade lock request exception.

		Args:
			field_name: Required or constrained field name.
			constraint: Validation requirement that the field failed.

		Returns:
			None.

		Raises:
			No exceptions are intentionally raised by this method.
		"""
		super().__init__(
			message=f"{field_name} {constraint}",
			code="USER_TRADE_LOCK_UNPROCESSABLE_ENTITY",
		)




class UserTradeLockRepository:
	"""
	Lease-based distributed lock for user trade mutations.

	Table schema:
	  - Partition key: cognito_user_id (S)
	  - No sort key
	"""

	def __init__(self, dynamodb_client: DynamoDBClient) -> None:
		"""
		Initialize the user trade lock repository.

		Args:
			dynamodb_client: DynamoDB client wrapper used for lock storage.

		Returns:
			None.

		Raises:
			No exceptions are intentionally raised by this method.
		"""
		self.lock_table_client = dynamodb_client

	def get_lock(self, cognito_user_id: str) -> Optional[Dict[str, Any]]:
		"""
		Fetch the current trade lock for a Cognito user.

		Args:
			cognito_user_id: Cognito user ID whose lock should be fetched.

		Returns:
			Optional[Dict[str, Any]]: Lock item when present, otherwise None.

		Raises:
			UserTradeLockBadGatewayError: If DynamoDB fails while loading the
			lock.
		"""

		try:
			return self.lock_table_client.get_item(key={"cognito_user_id": str(cognito_user_id)})
		except DynamoDBClientError as e:
			raise UserTradeLockBadGatewayError(
				operation="loading lock",
				cognito_user_id=cognito_user_id,
				source="DynamoDB",
				cause=e,
			) from e

	def acquire_lock(self, cognito_user_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"""
		Acquire lock for a user if absent or expired.

		Args:
			cognito_user_id: Cognito user ID whose lock should be acquired.
			owner_token: Opaque token representing lock ownership.
			lease_seconds: Lease duration in seconds.

		Returns:
			bool: True if acquired, False if another active owner holds the lock.

		Raises:
			UserTradeLockBadGatewayError: If DynamoDB fails while acquiring the
			lock.
			UserTradeLockInternalServerError: If an unexpected error occurs.
		"""
		now = int(time.time())
		expires_at = now + int(lease_seconds)

		item = to_dynamodb_value({
			"cognito_user_id": str(cognito_user_id),
			"owner_token": str(owner_token),
			"created_at": now,
			"updated_at": now,
			"expires_at": expires_at,
		})

		try:
			self.lock_table_client.table.put_item(
				Item=item,
				ConditionExpression="attribute_not_exists(cognito_user_id) OR expires_at < :now",
				ExpressionAttributeValues={":now": now},
			)
			return True
		except ClientError as e:
			if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
				return False
			raise UserTradeLockBadGatewayError(
				operation="acquiring lock",
				cognito_user_id=cognito_user_id,
				source="DynamoDB botocore",
				cause=e,
			) from e
		except Exception as e:
			raise UserTradeLockInternalServerError(
				message=f"Unexpected error acquiring lock for user '{cognito_user_id}': {e}"
			) from e

	def renew_lock(self, cognito_user_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"""
		Extend an active lock lease owned by owner_token.

		Args:
			cognito_user_id: Cognito user ID whose lock should be renewed.
			owner_token: Opaque token that must match current lock ownership.
			lease_seconds: New lease duration in seconds.

		Returns:
			bool: True if renewed, False if lock is not owned by owner_token.

		Raises:
			UserTradeLockBadGatewayError: If DynamoDB fails while renewing the
			lock.
			UserTradeLockInternalServerError: If an unexpected error occurs.
		"""
		now = int(time.time())
		new_expires_at = now + int(lease_seconds)

		try:
			self.lock_table_client.table.update_item(
				Key={"cognito_user_id": str(cognito_user_id)},
				UpdateExpression="SET expires_at = :expires_at, updated_at = :updated_at",
				ConditionExpression="owner_token = :owner_token",
				ExpressionAttributeValues={
					":expires_at": new_expires_at,
					":updated_at": now,
					":owner_token": str(owner_token),
				},
			)
			return True
		except ClientError as e:
			if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
				return False
			raise UserTradeLockBadGatewayError(
				operation="renewing lock",
				cognito_user_id=cognito_user_id,
				source="DynamoDB botocore",
				cause=e,
			) from e
		except Exception as e:
			raise UserTradeLockInternalServerError(
				message=f"Unexpected error renewing lock for user '{cognito_user_id}': {e}",
			) from e

	def release_lock(self, cognito_user_id: str, owner_token: str) -> bool:
		"""
		Release a lock only if it is currently owned by owner_token.

		Args:
			cognito_user_id: Cognito user ID whose lock should be released.
			owner_token: Opaque token that must match current lock ownership.

		Returns:
			bool: True if released, False if lock is missing or owned by someone
			else.

		Raises:
			UserTradeLockBadGatewayError: If DynamoDB fails while releasing the
			lock.
			UserTradeLockInternalServerError: If an unexpected error occurs.
		"""
		try:
			self.lock_table_client.table.delete_item(
				Key={"cognito_user_id": str(cognito_user_id)},
				ConditionExpression="owner_token = :owner_token",
				ExpressionAttributeValues={":owner_token": str(owner_token)},
			)
			return True
		except ClientError as e:
			if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
				return False
			raise UserTradeLockBadGatewayError(
				operation="releasing lock",
				cognito_user_id=cognito_user_id,
				source="DynamoDB botocore",
				cause=e,
			) from e
		except Exception as e:
			raise UserTradeLockInternalServerError(
				message=f"Unexpected error releasing lock for user '{cognito_user_id}': {e}",
			) from e
		

# backend/repository/model_portfolio_update_lock_repository.py

# Python imports
from __future__ import annotations
import time
from typing import Any, Dict, Optional
from botocore.exceptions import ClientError

# Baskt imports
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError


class ModelPortfolioUpdateLockInternalServerError(Exception):
	def __init__(self, message: str, code: str = "MODEL_PORTFOLIO_UPDATE_LOCK_INTERNAL_SERVER_ERROR") -> None:
		"""
		Initialize a model portfolio update lock repository exception.

		Args:
			message: Human-readable error description.
			code: Stable error code for programmatic handling.

		Returns:
			None.

		Raises:
			No exceptions are intentionally raised by this method.
		"""
		super().__init__(message)
		self.code = code


class ModelPortfolioUpdateLockBadGatewayError(ModelPortfolioUpdateLockInternalServerError):
	def __init__(self, operation: str, portfolio_id: str, *, source: str, cause: Optional[Exception] = None) -> None:
		"""
		Initialize an upstream dependency failure for lock operations.

		Args:
			operation: Description of the lock operation that failed.
			portfolio_id: Model portfolio ID involved in the failure.
			source: Upstream dependency that failed.
			cause: Optional upstream exception that caused the failure.

		Returns:
			None.

		Raises:
			No exceptions are intentionally raised by this method.
		"""
		message = f"Upstream {source} client failed while {operation} for portfolio '{portfolio_id}'"
		if cause:
			message = f"{message}: {cause}"
		super().__init__(message=message, code="MODEL_PORTFOLIO_UPDATE_LOCK_BAD_GATEWAY")


class ModelPortfolioUpdateLockUnprocessableEntityError(ModelPortfolioUpdateLockInternalServerError):
	def __init__(self, field_name: str, constraint: str) -> None:
		"""
		Initialize an unprocessable error for model portfolio lock.

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
			code="MODEL_PORTFOLIO_UPDATE_LOCK_UNPROCESSABLE_ERROR",
		)


class ModelPortfolioUpdateLockRepository:
	"""
	Lease-based distributed lock for model portfolio update operations.

	Table schema:
	  - Partition key: portfolio_id (S)
	  - No sort key
	"""

	def __init__(self, dynamodb_client: DynamoDBClient) -> None:
		"""
		Initialize lock repository with DynamoDB client dependency.

		Args:
			dynamodb_client: DynamoDB client wrapper used for lock storage operations.

		Returns:
			None.

		Raises:
			No exceptions are intentionally raised by this method.
		"""
		self.lock_table_client = dynamodb_client

	def get_lock(self, portfolio_id: str) -> Optional[Dict[str, Any]]:
		"""
		Fetch the current lock record for a portfolio.

		Args:
			portfolio_id: Identifier of the portfolio lock to retrieve.

		Returns:
			Optional[Dict[str, Any]]: Lock item when present, otherwise None.

		Raises:
			ModelPortfolioUpdateLockBadGatewayError: If DynamoDB fails while
			loading the lock.
		"""
		try:
			return self.lock_table_client.get_item(key={"portfolio_id": str(portfolio_id)})
		except DynamoDBClientError as e:
			raise ModelPortfolioUpdateLockBadGatewayError(
				operation="loading lock",
				portfolio_id=portfolio_id,
				source="DynamoDB",
				cause=e,
			) from e

	def acquire_lock(self, portfolio_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"""
		Acquire lock for a portfolio if absent or expired.

		Args:
			portfolio_id: Identifier of the portfolio to lock.
			owner_token: Opaque token representing lock ownership.
			lease_seconds: Lease duration in seconds.

		Returns:
			bool: True if acquired, False if another active owner holds the lock.

		Raises:
			ModelPortfolioUpdateLockBadGatewayError: If DynamoDB fails while
			acquiring the lock.
			ModelPortfolioUpdateLockInternalServerError: If an unexpected error
			occurs.
		"""

		now = int(time.time())
		expires_at = now + int(lease_seconds)

		item = {
			"portfolio_id": str(portfolio_id),
			"owner_token": str(owner_token),
			"created_at": now,
			"updated_at": now,
			"expires_at": expires_at
		}

		try:
			self.lock_table_client.table.put_item(
				Item=item,
				ConditionExpression="attribute_not_exists(portfolio_id) OR expires_at < :now",
				ExpressionAttributeValues={":now": now},
			)
			return True
		except ClientError as e:
			if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
				return False
			raise ModelPortfolioUpdateLockBadGatewayError(
				operation="acquiring lock",
				portfolio_id=portfolio_id,
				source="DynamoDB botocore",
				cause=e,
			) from e
		except Exception as e:
			raise ModelPortfolioUpdateLockInternalServerError(
				message=f"Unexpected error acquiring lock for portfolio '{portfolio_id}': {e}"
			) from e

	def renew_lock(self, portfolio_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"""
		Extend an active lock lease owned by owner_token.

		Args:
			portfolio_id: Identifier of the portfolio whose lock is renewed.
			owner_token: Opaque token that must match current lock owner.
			lease_seconds: New lease duration in seconds.

		Returns:
			bool: True if renewed, False if lock is not owned by owner_token.

		Raises:
			ModelPortfolioUpdateLockBadGatewayError: If DynamoDB fails while
			renewing the lock.
			ModelPortfolioUpdateLockInternalServerError: If an unexpected error
			occurs.
		"""
		now = int(time.time())
		new_expires_at = now + int(lease_seconds)

		try:
			self.lock_table_client.table.update_item(
				Key={"portfolio_id": str(portfolio_id)},
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
			raise ModelPortfolioUpdateLockBadGatewayError(
				operation="renewing lock",
				portfolio_id=portfolio_id,
				source="DynamoDB botocore",
				cause=e,
			) from e
		except Exception as e:
			raise ModelPortfolioUpdateLockInternalServerError(
				message=f"Unexpected error renewing lock for portfolio '{portfolio_id}': {e}",
			) from e

	def release_lock(self, portfolio_id: str, owner_token: str) -> bool:
		"""
		Release a lock only if it is currently owned by owner_token.

		Args:
			portfolio_id: Identifier of the portfolio lock to release.
			owner_token: Opaque token that must match current lock owner.

		Returns:
			bool: True if released, False if lock is missing or owned by someone
			else.

		Raises:
			ModelPortfolioUpdateLockBadGatewayError: If DynamoDB fails while
			releasing the lock.
			ModelPortfolioUpdateLockInternalServerError: If an unexpected error
			occurs.
		"""

		try:
			self.lock_table_client.table.delete_item(
				Key={"portfolio_id": str(portfolio_id)},
				ConditionExpression="owner_token = :owner_token",
				ExpressionAttributeValues={":owner_token": str(owner_token)},
			)
			return True
		except ClientError as e:
			if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
				return False
			raise ModelPortfolioUpdateLockBadGatewayError(
				operation="releasing lock",
				portfolio_id=portfolio_id,
				source="DynamoDB botocore",
				cause=e,
			) from e
		except Exception as e:
			raise ModelPortfolioUpdateLockInternalServerError(
				message=f"Unexpected error releasing lock for portfolio '{portfolio_id}': {e}",
			) from e

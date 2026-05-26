# backend/repository/model_portfolio_update_lock_repository.py

# Python imports
from __future__ import annotations
import time
from typing import Any, Dict, Optional
from botocore.exceptions import ClientError

# Baskt imports
from clients.dynamodb_client import DynamoDBClient, DynamoDBClientError


class ModelPortfolioUpdateLockInternalServerError(Exception):
	def __init__(self, message: str):
		"""
		Initialize a lock repository error with a message and optional code.

		Args:
			message: Human-readable error description.
			code: Stable error code for programmatic handling.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = "MODEL_PORTFOLIO_UPDATE_LOCK_INTERNAL_SERVER_ERROR"


class ModelPortfolioUpdateLockBadGatewayError(ModelPortfolioUpdateLockInternalServerError):
	def __init__(self, message: str):
		super().__init__(message=message)
		self.code = "MODEL_PORTFOLIO_UPDATE_LOCK_BAD_GATEWAY"


class ModelPortfolioUpdateLockUnprocessableEntityError(ModelPortfolioUpdateLockInternalServerError):
	def __init__(self, message: str):
		"""
		Initialize an unprocessable error for model portfolio lock.

		Args:
			message: Validation failure details.

		Returns:
			None.
		"""
		super().__init__(message=message)
		self.code = "MODEL_PORTFOLIO_UPDATE_LOCK_UNPROCESSABLE_ERROR"


class ModelPortfolioUpdateLockRepository:
	"""
	Lease-based distributed lock for model portfolio update operations.

	Table schema:
	  - Partition key: portfolio_id (S)
	  - No sort key
	"""

	def __init__(self, dynamodb_client: DynamoDBClient):
		"""
		Initialize lock repository with DynamoDB client dependency.

		Args:
			dynamodb_client: DynamoDB client wrapper used for lock storage operations.

		Returns:
			None.
		"""
		self.lock_table_client = dynamodb_client

	def _validate_inputs(self, portfolio_id: str, owner_token: str, lease_seconds: Optional[int] = None) -> None:
		"""
		Validate lock operation inputs before executing lock table operations.

		Args:
			portfolio_id: Identifier of the portfolio being locked.
			owner_token: Opaque token identifying the lock owner.
			lease_seconds: Optional lease duration in seconds.

		Returns:
			None.
		"""
		if not portfolio_id:
			raise ModelPortfolioUpdateLockUnprocessableEntityError("portfolio_id is required")
		if not owner_token:
			raise ModelPortfolioUpdateLockUnprocessableEntityError("owner_token is required")
		if lease_seconds is not None and lease_seconds <= 0:
			raise ModelPortfolioUpdateLockUnprocessableEntityError("lease_seconds must be > 0")

	def get_lock(self, portfolio_id: str) -> Optional[Dict[str, Any]]:
		"""
		Fetch the current lock record for a portfolio.

		Args:
			portfolio_id: Identifier of the portfolio lock to retrieve.

		Returns:
			Optional[Dict[str, Any]]: Lock item when present, otherwise None.
		"""
		if not portfolio_id:
			raise ModelPortfolioUpdateLockUnprocessableEntityError("portfolio_id is required")
		try:
			return self.lock_table_client.get_item(key={"portfolio_id": str(portfolio_id)})
		except DynamoDBClientError as e:
			raise ModelPortfolioUpdateLockBadGatewayError(
				message=f"Upstream DynamoDB client failed while loading lock for portfolio '{portfolio_id}': {e}.",
			)

	def acquire_lock(self, portfolio_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"""
		Acquire lock for a portfolio if absent or expired.

		Args:
			portfolio_id: Identifier of the portfolio to lock.
			owner_token: Opaque token representing lock ownership.
			lease_seconds: Lease duration in seconds.

		Returns:
			True if acquired, False if another active owner holds the lock.
		"""
		self._validate_inputs(portfolio_id=portfolio_id, owner_token=owner_token, lease_seconds=lease_seconds)

		now = int(time.time())
		expires_at = now + int(lease_seconds)

		item = {
			"portfolio_id": str(portfolio_id),
			"owner_token": str(owner_token),
			"created_at": now,
			"updated_at": now,
			"expires_at": expires_at,
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
				message=f"Upstream DynamoDB botocore client failed while acquiring lock for portfolio '{portfolio_id}': {e}.",
			)
		except Exception as e:
			raise ModelPortfolioUpdateLockInternalServerError(
				message=f"Unexpected error acquiring lock for portfolio '{portfolio_id}': {e}"
			)

	def renew_lock(self, portfolio_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"TODO: Fix update_item"
		"""
		Extend an active lock lease owned by owner_token.

		Args:
			portfolio_id: Identifier of the portfolio whose lock is renewed.
			owner_token: Opaque token that must match current lock owner.
			lease_seconds: New lease duration in seconds.

		Returns:
			True if renewed, False if lock is not owned by owner_token.
		"""
		self._validate_inputs(portfolio_id=portfolio_id, owner_token=owner_token, lease_seconds=lease_seconds)

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
				message=f"Upstream DynamoDB botocore client failed while renewing lock for portfolio '{portfolio_id}': {e}.",
			)
		except Exception as e:
			raise ModelPortfolioUpdateLockInternalServerError(
				message=f"Unexpected error renewing lock for portfolio '{portfolio_id}': {e}",
			)

	def release_lock(self, portfolio_id: str, owner_token: str) -> bool:
		"TODO: delete item fix"
		"""
		Release a lock only if it is currently owned by owner_token.

		Args:
			portfolio_id: Identifier of the portfolio lock to release.
			owner_token: Opaque token that must match current lock owner.

		Returns:
			True if released, False if lock is missing or owned by someone else.
		"""
		self._validate_inputs(portfolio_id=portfolio_id, owner_token=owner_token)

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
				message=f"Upstream DynamoDB botocore client failed while releasing lock for portfolio '{portfolio_id}': {e}.",
			)
		except Exception as e:
			raise ModelPortfolioUpdateLockInternalServerError(
				message=f"Unexpected error releasing lock for portfolio '{portfolio_id}': {e}",
			)

	def delete_lock(self, portfolio_id: str) -> bool:
		"""
		Delete a lock record by portfolio_id without ownership checks.

		Args:
			portfolio_id: Identifier of the portfolio lock to delete.

		Returns:
			True if delete call succeeds.
		"""
		if not portfolio_id:
			raise ModelPortfolioUpdateLockUnprocessableEntityError("portfolio_id is required")

		try:
			self.lock_table_client.delete_item(key={"portfolio_id": str(portfolio_id)})
			return True
		except DynamoDBClientError as e:
			raise ModelPortfolioUpdateLockBadGatewayError(
				message=f"Upstream DynamoDB client failed while deleting lock for portfolio '{portfolio_id}': {e}.",
			)
		except ClientError as e:
			raise ModelPortfolioUpdateLockBadGatewayError(
				message=f"Upstream DynamoDB botocore client failed while deleting lock for portfolio '{portfolio_id}': {e}.",
			)
		except Exception as e:
			raise ModelPortfolioUpdateLockInternalServerError(
				message=f"Unexpected error deleting lock for portfolio '{portfolio_id}': {e}",
			)

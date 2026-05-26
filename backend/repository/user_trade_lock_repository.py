# backend/repository/user_trade_lock_repository.py

# Python imports
from __future__ import annotations
import time
from typing import Any, Dict, Optional
from botocore.exceptions import ClientError

# Baskt imports
from clients.dynamodb_client import DynamoDBClient


class UserTradeLockInternalServerError(Exception):
	def __init__(self, message: str):
		super().__init__(message)
		self.code = "USER_TRADE_LOCK_INTERNAL_SERVER_ERROR"


class UserTradeLockBadGatewayError(UserTradeLockInternalServerError):
	def __init__(self, message: str):
		super().__init__(
			message=message,
			code="USER_TRADE_LOCK_BAD_GATEWAY",
		)


class UserTradeLockUnprocessableEntityError(UserTradeLockInternalServerError):
	def __init__(self, message: str):
		super().__init__(
			message=message,
			code="USER_TRADE_LOCK_UNPROCESSABLE_ENTITY",
		)




class UserTradeLockRepository:
	"""
	Lease-based distributed lock for user trade mutations.

	Table schema:
	  - Partition key: user_id (S)
	  - No sort key
	"""

	def __init__(self, dynamodb_client: DynamoDBClient):
		self.lock_table_client = dynamodb_client

	def _validate_inputs(self, user_id: str, owner_token: str, lease_seconds: Optional[int] = None) -> None:
		if not user_id:
			raise UserTradeLockUnprocessableEntityError("user_id is required.")
		if not owner_token:
			raise UserTradeLockUnprocessableEntityError("owner_token is required.")
		if lease_seconds is not None and lease_seconds <= 0:
			raise UserTradeLockUnprocessableEntityError("lease_seconds must be greater than 0.")

	def get_lock(self, user_id: str) -> Optional[Dict[str, Any]]:
		if not user_id:
			raise UserTradeLockUnprocessableEntityError("user_id is required.")
		try:
			return self.lock_table_client.get_item(key={"user_id": str(user_id)})
		except ClientError as e:
			raise UserTradeLockBadGatewayError(
				message=f"Upstream DynamoDB botocore client failed while loading lock for user '{user_id}': {e}."
			)

	def acquire_lock(self, user_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"""
		Acquire lock for a user if absent or expired.

		Returns:
			True if acquired, False if another active owner holds the lock.
		"""
		self._validate_inputs(user_id=user_id, owner_token=owner_token, lease_seconds=lease_seconds)

		now = int(time.time())
		expires_at = now + int(lease_seconds)

		item = {
			"user_id": str(user_id),
			"owner_token": str(owner_token),
			"created_at": now,
			"updated_at": now,
			"expires_at": expires_at,
		}

		try:
			self.lock_table_client.table.put_item(
				Item=item,
				ConditionExpression="attribute_not_exists(user_id) OR expires_at < :now",
				ExpressionAttributeValues={":now": now},
			)
			return True
		except ClientError as e:
			if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
				return False
			raise UserTradeLockBadGatewayError(
				message=f"Upstream DynamoDB botocore client failed while acquiring lock for user '{user_id}': {e}."
			)

	def renew_lock(self, user_id: str, owner_token: str, lease_seconds: int = 30) -> bool:
		"""
		Extend an active lock lease owned by owner_token.

		Returns:
			True if renewed, False if lock is not owned by owner_token.
		"""
		self._validate_inputs(user_id=user_id, owner_token=owner_token, lease_seconds=lease_seconds)

		now = int(time.time())
		new_expires_at = now + int(lease_seconds)

		try:
			self.lock_table_client.table.update_item(
				Key={"user_id": str(user_id)},
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
				message=f"Upstream DynamoDB botocore client failed while renewing lock for user '{user_id}': {e}."
			)

	def release_lock(self, user_id: str, owner_token: str) -> bool:
		"""
		Release a lock only if it is currently owned by owner_token.

		Returns:
			True if released, False if lock is missing or owned by someone else.
		"""
		self._validate_inputs(user_id=user_id, owner_token=owner_token)

		try:
			self.lock_table_client.table.delete_item(
				Key={"user_id": str(user_id)},
				ConditionExpression="owner_token = :owner_token",
				ExpressionAttributeValues={":owner_token": str(owner_token)},
			)
			return True
		except ClientError as e:
			if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
				return False
			raise UserTradeLockBadGatewayError(
				message=f"Upstream DynamoDB botocore client failed while releasing lock for user '{user_id}': {e}."
			)
		
	def delete_lock(self, user_id: str) -> bool:
		"""
		Delete a lock record by user_id without ownership checks.

		Returns:
			True if delete call succeeds.
		"""
		if not user_id:
			raise UserTradeLockUnprocessableEntityError("user_id is required.")

		try:
			self.lock_table_client.delete_item(key={"user_id": str(user_id)})
			return True
		except ClientError as e:
			raise UserTradeLockBadGatewayError(
				message=f"Upstream DynamoDB botocore client failed while deleting lock for user '{user_id}': {e}."
			)



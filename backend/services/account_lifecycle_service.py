# backend/services/account_lifecycle_service.py

# Python imports
from __future__ import annotations
from typing import Any, Dict
from uuid import UUID

# Alpaca imports
from alpaca.broker.enums import BankAccountType, FeePaymentMethod, TransferDirection, TransferTiming
from alpaca.broker.models import ACHRelationship, Transfer

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from clients.cognito_client import CognitoClient, CognitoClientError
from repository.user_account_repository import UserAccountRepository, UserAccountInternalServerError, UserAccountBadGatewayError
from domain.baskt import BasktAccount

class AccountLifecycleServiceError(Exception):
	def __init__(self, message: str, code: str = "ACCOUNT_LIFECYCLE_SERVICE_ERROR"):
		super().__init__(message)
		self.code = code

class AccountLifecycleServiceBasktAccountDisabled(AccountLifecycleServiceError):
	def __init__(self, message: str, code: str = "ACCOUNT_LIFECYCLE_SERVICE_BASKT_ACCOUNT_DISABLED_ERROR"):
		super().__init__(message)
		self.code = code



class AccountLifecycleService:
	def __init__(
		self,
		alpaca_broker_client: AlpacaBrokerClient,
		cognito_client: CognitoClient,
		user_account_repository: UserAccountRepository,
	) -> None:
		self.alpaca_broker_client = alpaca_broker_client
		self.cognito_client = cognito_client
		self.user_account_repository = user_account_repository

	def create_baskt_account(self, account_data: Dict[str, Any], password: str | None = None) -> Dict[str, str]:

		try:
			cognito_user_id = self.cognito_client.create_cognito_user(account_data=account_data, password=password)
		except CognitoClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create Alpaca account and Cognito User: {err}",
				code="ACCOUNT_LIFECYCLE_COGNITO_CREATE_FAILED",
			) from err

		try:
			alpaca_account_data = self.alpaca_broker_client.create_alpaca_account(account_data=account_data)
			alpaca_account_id = alpaca_account_data["alpaca_account_id"]
			alpaca_account_number = alpaca_account_data["alpaca_account_number"]
			email_address = alpaca_account_data["email_address"]
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create Alpaca account and Cognito User: {err}",
				code="ACCOUNT_LIFECYCLE_ALPACA_CREATE_FAILED",
			) from err

		try:
			self.user_account_repository.create_user_account(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				alpaca_account_number=alpaca_account_number,
				account_data=account_data
			)
		except UserAccountBadGatewayError as err:
			raise AccountLifecycleServiceError(
				message=f"Created Alpaca/Cognito account but failed to persist user-account mapping: {err}",
				code="ACCOUNT_LIFECYCLE_USER_ACCOUNT_BAD_GATEWAY",
			) from err
		except UserAccountInternalServerError as err:
			raise AccountLifecycleServiceError(
				message=f"Created Alpaca/Cognito account but encountered internal repository error: {err}",
				code="ACCOUNT_LIFECYCLE_USER_ACCOUNT_INTERNAL_ERROR",
			) from err
		except Exception as err:
			raise AccountLifecycleServiceError(
				message=f"Created Alpaca/Cognito account but failed to persist user-account mapping: {err}",
				code="ACCOUNT_LIFECYCLE_USER_ACCOUNT_PERSIST_FAILED",
			) from err
		
		return {
			"alpaca_account_id": alpaca_account_id,
			"cognito_user_id": cognito_user_id,
			"email_address": email_address
		}

	def create_ach_relationship(
		self,
		*,
		alpaca_account_id: str,
		account_owner_name: str,
		bank_account_type: BankAccountType | str,
		bank_account_number: str,
		bank_routing_number: str,
		nickname: str | None = None,
		cognito_user_id: str | None = None,
	) -> ACHRelationship | Dict[str, Any]:
		"""
		Create an ACH bank relationship for an Alpaca broker account.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the ACH
				relationship.
			account_owner_name: Legal name of the external bank account owner.
			bank_account_type: External bank account type.
			bank_account_number: External bank account number.
			bank_routing_number: External bank routing number.
			nickname: Optional nickname for the ACH relationship.
			cognito_user_id: Optional Cognito user ID used for error context.

		Returns:
			ACHRelationship | Dict[str, Any]: Alpaca ACH relationship response.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to create the ACH
			relationship.
		"""
		try:
			return self.alpaca_broker_client.create_ach_relationship(
				alpaca_account_id=alpaca_account_id,
				account_owner_name=account_owner_name,
				bank_account_type=bank_account_type,
				bank_account_number=bank_account_number,
				bank_routing_number=bank_routing_number,
				nickname=nickname,
				cognito_user_id=cognito_user_id,
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create ACH relationship for Alpaca account '{alpaca_account_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_ACH_RELATIONSHIP_FAILED",
			) from err

	def create_ach_transfer_request(
		self,
		*,
		alpaca_account_id: str,
		relationship_id: str | UUID,
		amount: str | float,
		direction: TransferDirection | str = TransferDirection.INCOMING,
		timing: TransferTiming | str = TransferTiming.IMMEDIATE,
		fee_payment_method: FeePaymentMethod | str | None = None,
		cognito_user_id: str | None = None,
	) -> Transfer | Dict[str, Any]:
		"""
		Create an ACH transfer request for an Alpaca broker account.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the transfer.
			relationship_id: ACH relationship ID to use for the transfer.
			amount: Transfer amount.
			direction: Transfer direction.
			timing: Transfer timing.
			fee_payment_method: Optional fee payment method.
			cognito_user_id: Optional Cognito user ID used for error context.

		Returns:
			Transfer | Dict[str, Any]: Alpaca ACH transfer response.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to create the ACH
			transfer request.
		"""
		try:
			return self.alpaca_broker_client.create_ach_transfer(
				alpaca_account_id=alpaca_account_id,
				relationship_id=relationship_id,
				amount=amount,
				direction=direction,
				timing=timing,
				fee_payment_method=fee_payment_method,
				cognito_user_id=cognito_user_id,
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create ACH transfer request for Alpaca account '{alpaca_account_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_ACH_TRANSFER_REQUEST_FAILED",
			) from err
	
	def get_baskt_account_by_email_address(self, email_address: str, active_only: bool = True) -> BasktAccount:
		try:
			user_account_dict = self.user_account_repository.get_user_account_by_email_address(email_address=email_address)
			cognito_role_dict = self.cognito_client.get_cognito_user(cognito_user_id=user_account_dict["cognito_user_id"])
			alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
				account_id=user_account_dict["alpaca_account_id"],
				cognito_user_id=user_account_dict["cognito_user_id"],
			)
		except Exception as e:
			raise AccountLifecycleServiceError(
				message=f"Failed to get Baskt account for email address '{email_address}': {e}",
				code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT"
			)
		
		baskt_account = BasktAccount(
			cognito_user_id=cognito_role_dict["cognito_user_id"],
			alpaca_account_id=str(alpaca_account.id),
			alpaca_account_number=alpaca_account.account_number,
			email_address=user_account_dict["email_address"],
			cognito_confirmation_status=cognito_role_dict["cognito_confirmation_status"],
			cognito_enabled_status=cognito_role_dict["cognito_enabled_status"],
			alpaca_account_status=alpaca_account.status
		)

		if active_only and (not (baskt_account.cognito_enabled_status and baskt_account.alpaca_account_status.name in ["ACTIVE", "SUBMITTED"])):
			raise AccountLifecycleServiceBasktAccountDisabled(
				message=f"Baskt account is disabled. Cognito user: {baskt_account.cognito_enabled_status}, Alpaca account: {baskt_account.alpaca_account_status.name}"
			)
		
		return baskt_account
	

	def get_baskt_account_by_cognito_user_id(self, cognito_user_id: str, active_only: bool = True) -> BasktAccount:
		try:
			user_account_dict = self.user_account_repository.get_user_account_by_cognito_user_id(cognito_user_id=cognito_user_id)
			cognito_role_dict = self.cognito_client.get_cognito_user(cognito_user_id=user_account_dict["cognito_user_id"])
			alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
				account_id=user_account_dict["alpaca_account_id"],
				cognito_user_id=user_account_dict["cognito_user_id"],
			)
		except Exception as e:
			raise AccountLifecycleServiceError(
				message=f"Failed to get Baskt account for cognito user id '{cognito_user_id}': {e}",
				code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT"
			)
		
		baskt_account = BasktAccount(
			cognito_user_id=cognito_role_dict["cognito_user_id"],
			alpaca_account_id=str(alpaca_account.id),
			alpaca_account_number=alpaca_account.account_number,
			email_address=user_account_dict["email_address"],
			cognito_confirmation_status=cognito_role_dict["cognito_confirmation_status"],
			cognito_enabled_status=cognito_role_dict["cognito_enabled_status"],
			alpaca_account_status=alpaca_account.status
		)

		if active_only and (not (baskt_account.cognito_enabled_status and baskt_account.alpaca_account_status.name in ["ACTIVE", "SUBMITTED"])):
			raise AccountLifecycleServiceBasktAccountDisabled(
				message=f"Baskt account is disabled. Cognito user: {baskt_account.cognito_enabled_status}, Alpaca account: {baskt_account.alpaca_account_status.name}"
			)
		
		return baskt_account

	def deactivate_baskt_account(self, email_address) -> bool:
		"""
		Disables cognito user, close alpaca account
		"""
		try:
			user_account_dict = self.user_account_repository.get_user_account_by_email_address(email_address=email_address)
			self.cognito_client.disable_cognito_user(cognito_user_id=user_account_dict["cognito_user_id"])
			self.alpaca_broker_client.close_alpaca_account(
				account_id=user_account_dict["alpaca_account_id"],
				cognito_user_id=user_account_dict["cognito_user_id"],
			)
			return True
		except Exception:
			raise AccountLifecycleServiceError(
				message=f"Failed to deactivate baskt account for email address '{email_address}'",
				code="ACCOUNT_LIFECYCLE_SERVICE_DEACTIVATE_BASKT_ACCOUNT"
			)

		
		
	





		

	
		

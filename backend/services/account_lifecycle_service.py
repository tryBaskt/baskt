# backend/services/account_lifecycle_service.py

# Python imports
from __future__ import annotations
from typing import Any, Dict

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
			cognito_user_id = self.cognito_client.create_cognito_user(account_data=account_data, password=password)
		except CognitoClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Alpaca account created, but Cognito user creation failed: {err}",
				code="ACCOUNT_LIFECYCLE_COGNITO_CREATE_FAILED",
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
	
	def get_baskt_account_by_email_address(self, email_address: str, active_only: bool = True) -> BasktAccount:
		try:
			user_account_dict = self.user_account_repository.get_user_account_by_email_address(email_address=email_address)
			cognito_role_dict = self.cognito_client.get_cognito_user(cognito_user_id=user_account_dict["cognito_user_id"])
			alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(account_id=user_account_dict["alpaca_account_id"])
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
			alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(account_id=user_account_dict["alpaca_account_id"])
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
			self.alpaca_broker_client.close_alpaca_account(account_id=user_account_dict["alpaca_account_id"])
			return True
		except Exception:
			raise AccountLifecycleServiceError(
				message=f"Failed to deactivate baskt account for email address '{email_address}'",
				code="ACCOUNT_LIFECYCLE_SERVICE_DEACTIVATE_BASKT_ACCOUNT"
			)

		
		
	





		

	
		
# backend/services/account_lifecycle_service.py

# Python imports
from __future__ import annotations
from typing import Any, Dict, List

# Alpaca imports
from alpaca.broker.enums import BankAccountType, FeePaymentMethod, TransferDirection, TransferTiming
from alpaca.broker.models import ACHRelationship, Transfer, Bank

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from clients.cognito_client import CognitoClient, CognitoClientError
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
	) -> None:
		self.alpaca_broker_client = alpaca_broker_client
		self.cognito_client = cognito_client

	def create_baskt_account(self, account_data: Dict[str, Any], password: str | None = None) -> Dict[str, str]:

		try:
			alpaca_account_data = self.alpaca_broker_client.create_alpaca_account(account_data=account_data)
			alpaca_account_id = alpaca_account_data["alpaca_account_id"]
			alpaca_account_number = alpaca_account_data["alpaca_account_number"]
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create Alpaca account and Cognito User: {err}",
				code="ACCOUNT_LIFECYCLE_ALPACA_CREATE_FAILED",
			) from err

		try:
			cognito_user_id = self.cognito_client.create_cognito_user(account_data=account_data, password=password, alpaca_account_id=alpaca_account_id, alpaca_account_number=alpaca_account_number)
		except CognitoClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create Alpaca account and Cognito User: {err}",
				code="ACCOUNT_LIFECYCLE_COGNITO_CREATE_FAILED",
			) from err

		return {
			"alpaca_account_id": alpaca_account_id,
			"alpaca_account_number": alpaca_account_number,
			"cognito_user_id": cognito_user_id,
			"email_address": account_data["contact"]["email_address"],
		}

	def _get_baskt_account_helper(self, cognito_role_dict, active_only = True):
		alpaca_account_id=cognito_role_dict["alpaca_account_id"]
		cognito_user_id=cognito_role_dict["cognito_user_id"]
		try:
			alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
				account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
			)
		except Exception as e:
			raise AccountLifecycleServiceError(
				message=f"Failed to get Alpaca account for account id '{alpaca_account_id}': {e}",
				code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT_HELPER"
			)
		
		baskt_account = BasktAccount(
			cognito_user_id=cognito_role_dict["cognito_user_id"],
			alpaca_account_id=str(alpaca_account.id),
			alpaca_account_number=alpaca_account.account_number,
			email_address=str(alpaca_account.contact.email_address),
			cognito_confirmation_status=cognito_role_dict["cognito_confirmation_status"],
			cognito_enabled_status=cognito_role_dict["cognito_enabled_status"],
			alpaca_account_status=alpaca_account.status
		)

		if active_only and (not (baskt_account.cognito_enabled_status and baskt_account.alpaca_account_status.name in ["ACTIVE", "SUBMITTED"])):
			raise AccountLifecycleServiceBasktAccountDisabled(
				message=f"Baskt account is disabled. Cognito user: {baskt_account.cognito_enabled_status}, Alpaca account: {baskt_account.alpaca_account_status.name}"
			)
		
		return baskt_account

	
	def get_baskt_account_by_email_address(self, email_address: str, active_only: bool = True) -> BasktAccount:
		try:
			cognito_role_dict = self.cognito_client.get_cognito_user_by_email_address(email_address=email_address)
			return self._get_baskt_account_helper(cognito_role_dict=cognito_role_dict, active_only=active_only)
		except Exception as e:
			raise AccountLifecycleServiceError(
				message=f"Failed to get Baskt account for email address '{email_address}': {e}",
				code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT"
			)
	

	def get_baskt_account_by_cognito_user_id(self, cognito_user_id: str, active_only: bool = True) -> BasktAccount:
		try:
			cognito_role_dict = self.cognito_client.get_cognito_user_by_cognito_user_id(cognito_user_id=cognito_user_id)
			return self._get_baskt_account_helper(cognito_role_dict=cognito_role_dict, active_only=active_only)
		except Exception as e:
			raise AccountLifecycleServiceError(
				message=f"Failed to get Baskt account for cognito user id '{cognito_user_id}': {e}",
				code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT"
			)

	def create_direct_ach_relationship(
		self,
		*,
		alpaca_account_id: str,
		cognito_user_id: str,
		account_owner_name: str,
		bank_account_type: str,
		bank_account_number: str,
		bank_routing_number: str,
		nickname: str | None = None
	) -> ACHRelationship:
		"""
		Create a direct ACH relationship for an Alpaca broker account.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the ACH
				relationship.
			cognito_user_id: Cognito user ID used for error context.
			account_owner_name: Name of the bank account owner.
			bank_account_type: Bank account type, such as CHECKING or SAVINGS.
			bank_account_number: External bank account number.
			bank_routing_number: External bank routing number.
			nickname: Optional nickname for the ACH relationship.

		Returns:
			ACHRelationship: Alpaca ACH relationship response.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to create the ACH
			relationship.
		"""
		try:
			return self.alpaca_broker_client.create_direct_ach_relationship(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				account_owner_name=account_owner_name,
				bank_account_type=bank_account_type,
				bank_account_number=bank_account_number,
				bank_routing_number=bank_routing_number,
				nickname=nickname
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create ACH relationship for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_ACH_RELATIONSHIP_FAILED",
			) from err
		
	def create_plaid_ach_relationship(
		self,
		*,
		alpaca_account_id: str,
		cognito_user_id: str,
		processor_token: str
	) -> ACHRelationship:
		"""
		Create an ACH relationship from a Plaid processor token.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the ACH
				relationship.
			cognito_user_id: Cognito user ID used for error context.
			processor_token: Plaid processor token created for Alpaca.

		Returns:
			ACHRelationship: Alpaca ACH relationship response.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to create the Plaid ACH
			relationship.
		"""
		try:
			return self.alpaca_broker_client.create_plaid_ach_relationship(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				processor_token=processor_token
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create Plaid ACH relationship for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_PLAID_ACH_RELATIONSHIP_FAILED",
			) from err


	def get_ach_relationships(
		self,
		*,
		cognito_user_id: str,
		alpaca_account_id: str
	) -> List[ACHRelationship]:
		"""
		Get ACH bank relationships for an Alpaca broker account.

		Args:
			cognito_user_id: Cognito user ID used for error context.
			alpaca_account_id: Alpaca broker account ID whose ACH
				relationships should be fetched.

		Returns:
			List[ACHRelationship]: ACH relationships returned by Alpaca.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to fetch ACH
			relationships.
		"""
		try:
			return self.alpaca_broker_client.get_ach_relationships(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to get ACH relationships for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_GET_ACH_RELATIONSHIPS_FAILED",
			) from err
		
	def delete_ach_relationship(
		self,
		alpaca_account_id: str,
		cognito_user_id: str,
		ach_relationship_id: str
	) -> None: 
		"""
		Delete an ACH relationship from an Alpaca broker account.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the ACH
				relationship.
			cognito_user_id: Cognito user ID used for error context.
			ach_relationship_id: ACH relationship ID to delete.

		Returns:
			None.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to delete the ACH
			relationship.
		"""
		try:
			self.alpaca_broker_client.delete_ach_relationship(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				ach_relationship_id=ach_relationship_id
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to delete ach relationship '{ach_relationship_id}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_DELETE_ACH_RELATIONSHIP_FAILED"
			) from err
		
	def create_ach_transfer(
		self,
		*,
		alpaca_account_id: str,
		cognito_user_id: str,
		amount: str,
		direction: str,
		timing: str,
		relationship_id: str,
		fee_payment_method: str | None = None,
	) -> Transfer | Dict[str, Any]:
		"""
		Create a direct ACH transfer for an Alpaca broker account.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the transfer.
			cognito_user_id: Cognito user ID used for error context.
			amount: Transfer amount.
			direction: Transfer direction, such as INCOMING or OUTGOING.
			timing: Transfer timing, such as IMMEDIATE.
			relationship_id: ACH relationship ID to use for the transfer.
			fee_payment_method: Optional fee payment method, such as USER or
				INVOICE.

		Returns:
			Transfer | Dict[str, Any]: Alpaca transfer response.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to create the ACH
			transfer.
		"""
		try:
			return self.alpaca_broker_client.create_ach_transfer(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				amount=amount,
				direction=direction,
				timing=timing,
				relationship_id=relationship_id,
				fee_payment_method=fee_payment_method
			)
		
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create ach transfer request for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_ACH_TRANSFER_REQUEST_FAILED",
			) from err

	def create_bank(
		self,
		*,
		cognito_user_id: str,
		alpaca_account_id: str,
		name: str,
		bank_code_type: str,
		bank_code: str,
		account_number: str,
		country: str | None = None,
		state_province: str | None = None,
		postal_code: str | None = None,
		city: str | None = None,
		street_address: str | None = None
	)-> Bank:
		"""
		Create a bank relationship for an Alpaca broker account.

		Args:
			cognito_user_id: Cognito user ID used for error context.
			alpaca_account_id: Alpaca broker account ID that owns the bank
				relationship.
			name: Bank name.
			bank_code_type: Bank identifier type, such as ABA or BIC.
			bank_code: Bank identifier value. For ABA, this is the routing
				number.
			account_number: External bank account number.
			country: Optional bank country.
			state_province: Optional bank state or province.
			postal_code: Optional bank postal code.
			city: Optional bank city.
			street_address: Optional bank street address.

		Returns:
			Bank: Alpaca bank relationship response.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to create the bank
			relationship.
		"""
		try:
			return self.alpaca_broker_client.create_bank(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				name=name,
				bank_code_type=bank_code_type,
				bank_code=bank_code,
				account_number=account_number,
				country=country,
				state_province=state_province,
				postal_code=postal_code,
				city=city,
				street_address=street_address
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create bank request for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_BANK_REQUEST_FAILED",
			) from err

	def get_banks(
		self,
		*,
		cognito_user_id: str,
		alpaca_account_id: str
	) -> List[Bank]:
		"""
		Get bank relationships for an Alpaca broker account.

		Args:
			cognito_user_id: Cognito user ID used for error context.
			alpaca_account_id: Alpaca broker account ID whose bank
				relationships should be fetched.

		Returns:
			List[Bank]: Bank relationships returned by Alpaca.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to fetch bank
			relationships.
		"""
		try:
			return self.alpaca_broker_client.get_banks(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to get banks for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_GET_BANKS_FAILED",
			) from err
		
	def delete_bank(
		self,
		alpaca_account_id: str,
		cognito_user_id: str,
		bank_id: str
	) -> None:
		"""
		Delete a bank relationship from an Alpaca broker account.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the bank
				relationship.
			cognito_user_id: Cognito user ID used for error context.
			bank_id: Bank relationship ID to delete.

		Returns:
			None.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to delete the bank
			relationship.
		"""
		try:
			self.alpaca_broker_client.delete_bank(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				bank_id=bank_id
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to delete bank '{bank_id}' for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_DELETE_BANKS_FAILED"
			) from err
		

	def create_bank_transfer(
		self,
		*,
		alpaca_account_id: str,
		cognito_user_id: str,
		amount: str,
		direction: str,
		timing: str,
		bank_id: str,
		fee_payment_method: str | None = None,
		additional_information: str | None = None
	) -> Transfer | Dict[str, Any]:
		"""
		Create a wire transfer for an Alpaca broker account.

		Args:
			alpaca_account_id: Alpaca broker account ID that owns the transfer.
			cognito_user_id: Cognito user ID used for error context.
			amount: Transfer amount.
			direction: Transfer direction, such as INCOMING or OUTGOING.
			timing: Transfer timing, such as IMMEDIATE.
			bank_id: Bank relationship ID to use for the wire transfer.
			fee_payment_method: Optional fee payment method, such as USER or
				INVOICE.
			additional_information: Optional wire transfer instructions.

		Returns:
			Transfer | Dict[str, Any]: Alpaca transfer response.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to create the wire
			transfer.
		"""
		try:
			return self.alpaca_broker_client.create_bank_transfer(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				amount=amount,
				direction=direction,
				timing=timing,
				bank_id=bank_id,
				fee_payment_method=fee_payment_method,
				additional_information=additional_information
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to create bank transfer request for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_BANK_TRANSFER_REQUEST_FAILED",
			) from err

	def get_transfers(
		self,
		*,
		cognito_user_id: str,
		alpaca_account_id: str,
		limit: int | None = None,
		offset: int = 0,
	) -> List[Transfer]:
		"""
		Get all transfers for an Alpaca broker account.

		Args:
			cognito_user_id: Cognito user ID used for error context.
			alpaca_account_id: Alpaca broker account ID whose transfers should
				be fetched.
			limit: Optional maximum number of transfer records to fetch.
			offset: Number of transfer records to skip before returning
				results.

		Returns:
			List[Transfer]: Transfer records returned by Alpaca for the broker
			account.

		Raises:
			AccountLifecycleServiceError: If Alpaca fails to fetch transfers.
		"""
		try:
			return self.alpaca_broker_client.get_transfers(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				limit=limit,
				offset=offset,
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleServiceError(
				message=f"Failed to get transfers for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_GET_TRANSFERS_FAILED",
			) from err
			
			

		

		
		
	





		

	
		

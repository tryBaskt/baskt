# backend/services/account_lifecycle_service.py

# Python imports
from __future__ import annotations
from typing import Any, Dict, List, Optional

# Alpaca imports
from alpaca.broker.models import ACHRelationship, Transfer, Bank, TradeAccount

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from clients.cognito_client import CognitoClient, CognitoClientError
from repository.baskt_account_repository import BasktAccountRepository
from domain.baskt_account_domain import (
	BasktAccount,
	DisclosureData,
	ContactData,
	IdentityData,
	AgreementData
)
# from domain.baskt_domain import BasktAccount

class AccountLifecycleInternalServerError(Exception):
	def __init__(self, message: str, code: str = "ACCOUNT_LIFECYCLE_SERVICE_ERROR") -> None:
		"""
		Initialize an account lifecycle service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class AccountLifecycleServiceBasktAccountDisabled(AccountLifecycleInternalServerError):
	def __init__(self, message: str, code: str = "ACCOUNT_LIFECYCLE_SERVICE_BASKT_ACCOUNT_DISABLED") -> None:
		"""
		Initialize a disabled Baskt account exception.

		Args:
			message: Human-readable disabled account details.
			code: Stable error code identifying the disabled account state.

		Returns:
			None.
		"""
		super().__init__(message=message, code=code)

class AccountLifecycleService:
	def __init__(
		self,
		alpaca_broker_client: AlpacaBrokerClient,
		cognito_client: CognitoClient,
		baskt_account_repository: BasktAccountRepository
	) -> None:
		"""
		Initialize account lifecycle service dependencies.

		Args:
			alpaca_broker_client: Client used for Alpaca broker operations.
			cognito_client: Client used for Cognito user operations.
			baskt_account_repository: Repository used to persist Baskt account data.

		Returns:
			None.
		"""
		self.alpaca_broker_client = alpaca_broker_client
		self.cognito_client = cognito_client
		self.baskt_account_repository = baskt_account_repository

	def create_baskt_account(self, account_data: Dict[str, Any], password: Optional[str] = None) -> Dict[str, str]:
		"""
		Create matching Alpaca, Cognito, and persisted Baskt accounts.

		Args:
			account_data: Account creation payload containing contact, identity,
				disclosures, agreements, and optional account fields.
			password: Optional initial Cognito password.

		Returns:
			Dict[str, str]: Created Alpaca account ID, Alpaca account number,
			Cognito user ID, and email address.

		Raises:
			AccountLifecycleInternalServerError: If Alpaca account creation or Cognito
			user creation fails.
		"""

		try:
			alpaca_account_data = self.alpaca_broker_client.create_alpaca_account(account_data=account_data)
			alpaca_account_id = alpaca_account_data["alpaca_account_id"]
			alpaca_account_number = alpaca_account_data["alpaca_account_number"]
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to create Alpaca account: {err}",
				code="ACCOUNT_LIFECYCLE_ALPACA_CREATE_FAILED",
			) from err

		try:
			cognito_user_id = self.cognito_client.create_cognito_user(account_data=account_data, password=password, alpaca_account_id=alpaca_account_id, alpaca_account_number=alpaca_account_number)
		except CognitoClientError as err:
			raise AccountLifecycleInternalServerError(
				message=f"Alpaca account created, but Cognito user creation failed: {err}",
				code="ACCOUNT_LIFECYCLE_COGNITO_CREATE_FAILED",
			) from err

		try:
			baskt_account = BasktAccount(
				cognito_user_id=cognito_user_id,
				display_name=account_data["display_name"],
				alpaca_account_id=alpaca_account_id,
				alpaca_account_number=alpaca_account_number,
				agreements_data=[
					AgreementData(**agreement_data)
					for agreement_data in account_data["agreements"]
				],
				disclosure_data=DisclosureData(**account_data["disclosures"]),
				identity_data=IdentityData(**account_data["identity"]),
				contact_data=ContactData(**account_data["contact"]),
			)

			self.baskt_account_repository.write_baskt_account(
				baskt_account=baskt_account
			)
		except Exception as err:
			raise AccountLifecycleInternalServerError(
				message=f"Cognito user and alpaca account created, but failed to persist baskt account details: {err}",
				code="ACCOUNT_LIFECYCLE_BASKT_ACCOUNT_PERSIST_FAILED",
			) from err



		return {
			"alpaca_account_id": alpaca_account_id,
			"alpaca_account_number": alpaca_account_number,
			"cognito_user_id": cognito_user_id,
			"email_address": account_data["contact"]["email_address"],
		}

	# def _get_baskt_account_helper(self, cognito_role_dict: Dict[str, Any], active_only: bool = True) -> BasktAccount:
	# 	"""
	# 	Build a Baskt account aggregate from Cognito attributes and Alpaca data.

	# 	Args:
	# 		cognito_role_dict: Cognito user attributes containing Alpaca account
	# 			IDs and Cognito status fields.
	# 		active_only: When True, reject disabled Cognito users or inactive
	# 			Alpaca accounts.

	# 	Returns:
	# 		BasktAccount: Combined Baskt account domain object.

	# 	Raises:
	# 		AccountLifecycleInternalServerError: If Alpaca account lookup fails.
	# 		AccountLifecycleServiceBasktAccountDisabled: If active_only is True
	# 		and the account is not enabled/submitted/active.
	# 	"""
	# 	alpaca_account_id=cognito_role_dict["alpaca_account_id"]
	# 	cognito_user_id=cognito_role_dict["cognito_user_id"]
	# 	try:
	# 		alpaca_account = self.alpaca_broker_client.get_alpaca_account_by_id(
	# 			account_id=alpaca_account_id,
	# 			cognito_user_id=cognito_user_id,
	# 		)
	# 	except AlpacaBrokerClientError as err:
	# 		raise AccountLifecycleInternalServerError(
	# 			message=f"Failed to get Alpaca account for account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
	# 			code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT_HELPER"
	# 		) from err
		
	# 	baskt_account = BasktAccount(
	# 		cognito_user_id=cognito_role_dict["cognito_user_id"],
	# 		alpaca_account_id=str(alpaca_account.id),
	# 		alpaca_account_number=alpaca_account.account_number,
	# 		email_address=str(alpaca_account.contact.email_address),
	# 		cognito_confirmation_status=cognito_role_dict["cognito_confirmation_status"],
	# 		cognito_enabled_status=cognito_role_dict["cognito_enabled_status"],
	# 		alpaca_account_status=alpaca_account.status
	# 	)

	# 	if active_only and (not (baskt_account.cognito_enabled_status and baskt_account.alpaca_account_status.name in ["ACTIVE", "SUBMITTED"])):
	# 		# We do actually want an account disabled exception
	# 		raise AccountLifecycleServiceBasktAccountDisabled(
	# 			message=f"Baskt account is disabled. Cognito user: {baskt_account.cognito_enabled_status}, Alpaca account: {baskt_account.alpaca_account_status.name}"
	# 		)
		
	# 	return baskt_account

	
	# def get_baskt_account_by_email_address(self, email_address: str, active_only: bool = True) -> BasktAccount:
	# 	"""
	# 	Get a Baskt account by Cognito email address.

	# 	Args:
	# 		email_address: Email address used to find the Cognito user.
	# 		active_only: When True, reject disabled Cognito users or inactive
	# 			Alpaca accounts.

	# 	Returns:
	# 		BasktAccount: Combined Baskt account domain object.

	# 	Raises:
	# 		AccountLifecycleInternalServerError: If Cognito or Alpaca lookup fails.
	# 	"""
	# 	try:
	# 		cognito_role_dict = self.cognito_client.get_cognito_user_by_email_address(email_address=email_address)
	# 		return self._get_baskt_account_helper(cognito_role_dict=cognito_role_dict, active_only=active_only)
	# 	# Propagate disabled account errors so the route can map them correctly.
	# 	except AccountLifecycleServiceBasktAccountDisabled:
	# 		raise
	# 	# Other service-layer errors should remain AccountLifecycleInternalServerError.
	# 	except AccountLifecycleInternalServerError:
	# 		raise
	# 	except CognitoClientError as err:
	# 		raise AccountLifecycleInternalServerError(
	# 			message=f"Failed to get Baskt account for email address '{email_address}': {err}",
	# 			code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT"
	# 		) from err
	

	# def get_baskt_account_by_cognito_user_id(self, cognito_user_id: str, active_only: bool = True) -> BasktAccount:
	# 	"""
	# 	Get a Baskt account by Cognito user ID.

	# 	Args:
	# 		cognito_user_id: Cognito user ID used to find account metadata.
	# 		active_only: When True, reject disabled Cognito users or inactive
	# 			Alpaca accounts.

	# 	Returns:
	# 		BasktAccount: Combined Baskt account domain object.

	# 	Raises:
	# 		AccountLifecycleInternalServerError: If Cognito or Alpaca lookup fails.
	# 	"""
	# 	try:
	# 		cognito_role_dict = self.cognito_client.get_cognito_user_by_cognito_user_id(cognito_user_id=cognito_user_id)
	# 		return self._get_baskt_account_helper(cognito_role_dict=cognito_role_dict, active_only=active_only)
		
	# 	# Propagate disabled account errors so the route can map them correctly.
	# 	except AccountLifecycleServiceBasktAccountDisabled:
	# 		raise
	# 	# Other service-layer errors should remain AccountLifecycleInternalServerError.
	# 	except AccountLifecycleInternalServerError:
	# 		raise
	# 	except CognitoClientError as err:
	# 		raise AccountLifecycleInternalServerError(
	# 			message=f"Failed to get Baskt account for cognito user id '{cognito_user_id}': {err}",
	# 			code="ACCOUNT_LIFECYCLE_SERVICE_GET_BASKT_ACCOUNT"
	# 		) from err

	def create_direct_ach_relationship(
		self,
		*,
		alpaca_account_id: str,
		cognito_user_id: str,
		account_owner_name: str,
		bank_account_type: str,
		bank_account_number: str,
		bank_routing_number: str,
		nickname: Optional[str] = None
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
			AccountLifecycleInternalServerError: If Alpaca fails to create the ACH
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
			raise AccountLifecycleInternalServerError(
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
			AccountLifecycleInternalServerError: If Alpaca fails to create the Plaid ACH
			relationship.
		"""
		try:
			return self.alpaca_broker_client.create_plaid_ach_relationship(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				processor_token=processor_token
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
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
			AccountLifecycleInternalServerError: If Alpaca fails to fetch ACH
			relationships.
		"""
		try:
			return self.alpaca_broker_client.get_ach_relationships(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
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
			AccountLifecycleInternalServerError: If Alpaca fails to delete the ACH
			relationship.
		"""
		try:
			self.alpaca_broker_client.delete_ach_relationship(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				ach_relationship_id=ach_relationship_id
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to delete ACH relationship '{ach_relationship_id}' for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_DELETE_ACH_RELATIONSHIP_FAILED"
			) from err
		
	def get_trade_account(
		self,
		alpaca_account_id: str,
		cognito_user_id: str,
	) -> TradeAccount:
		"""
		Get an Alpaca trade account for a broker account ID.

		Args:
			alpaca_account_id: Alpaca broker account ID.
			cognito_user_id: Cognito user ID used for error context.

		Returns:
			TradeAccount: Alpaca trade account details.

		Raises:
			AccountLifecycleInternalServerError: If Alpaca fails to fetch the trade
			account.
		"""
		try:
			return self.alpaca_broker_client.get_trade_account(
				account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id
			)
		except AlpacaBrokerClientError as e:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to get trade account for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
				code="ACCOUNT_LIFECYCLE_GET_TRADE_ACCOUNT_FAILED"
			) from e

		
		
	def create_ach_transfer(
		self,
		*,
		alpaca_account_id: str,
		cognito_user_id: str,
		amount: str,
		direction: str,
		timing: str,
		relationship_id: str,
		fee_payment_method: Optional[str] = None,
	) -> Transfer:
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
			Transfer: Alpaca transfer response.

		Raises:
			AccountLifecycleInternalServerError: If Alpaca fails to create the ACH
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
			raise AccountLifecycleInternalServerError(
				message=f"Failed to create ACH transfer request for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
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
		country: Optional[str] = None,
		state_province: Optional[str] = None,
		postal_code: Optional[str] = None,
		city: Optional[str] = None,
		street_address: Optional[str] = None
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
			AccountLifecycleInternalServerError: If Alpaca fails to create the bank
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
			raise AccountLifecycleInternalServerError(
				message=f"Failed to create bank relationship for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
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
			AccountLifecycleInternalServerError: If Alpaca fails to fetch bank
			relationships.
		"""
		try:
			return self.alpaca_broker_client.get_banks(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
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
			AccountLifecycleInternalServerError: If Alpaca fails to delete the bank
			relationship.
		"""
		try:
			self.alpaca_broker_client.delete_bank(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				bank_id=bank_id
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to delete bank '{bank_id}' for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_DELETE_BANK_FAILED"
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
		fee_payment_method: Optional[str] = None,
		additional_information: Optional[str] = None
	) -> Transfer:
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
			Transfer: Alpaca transfer response.

		Raises:
			AccountLifecycleInternalServerError: If Alpaca fails to create the wire
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
			raise AccountLifecycleInternalServerError(
				message=f"Failed to create bank transfer request for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CREATE_BANK_TRANSFER_REQUEST_FAILED",
			) from err

	def get_transfers(
		self,
		*,
		cognito_user_id: str,
		alpaca_account_id: str,
		limit: Optional[int] = None,
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
			AccountLifecycleInternalServerError: If Alpaca fails to fetch transfers.
		"""
		try:
			return self.alpaca_broker_client.get_transfers(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				limit=limit,
				offset=offset,
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to get transfers for Alpaca account '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_GET_TRANSFERS_FAILED",
			) from err
			
			

		

		
		
	





		

	
		

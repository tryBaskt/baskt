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
	DisclosuresData,
	ContactData,
	IdentityData,
	AgreementData
)

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


class AccountLifecycleDisplayNameTakenError(AccountLifecycleInternalServerError):
	"""Raised when a requested display name is already in use."""

	def __init__(self, display_name: str) -> None:
		super().__init__(
			message=f"Display name '{display_name}' is already taken",
			code="ACCOUNT_LIFECYCLE_DISPLAY_NAME_TAKEN",
		)

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

	#############################
	####### BASKT ACCOUNT #######
	#############################

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

		display_name = str(account_data.get("display_name", "")).strip()
		if not display_name:
			raise AccountLifecycleInternalServerError(
				message="display_name is required to create a Baskt account",
				code="ACCOUNT_LIFECYCLE_DISPLAY_NAME_INVALID",
			)
		if self.is_exists_display_name(display_name):
			raise AccountLifecycleDisplayNameTakenError(display_name)
		account_data["display_name"] = display_name

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
				disclosures_data=DisclosuresData(**account_data["disclosures"]),
				identity_data=IdentityData(
					**{
						key: value
						for key, value in account_data["identity"].items()
						if key != "tax_id"
					}
				),
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

	def is_exists_display_name(self, display_name: str) -> bool:
		"""Return whether a normalized display name is already in use."""
		display_name = str(display_name).strip()
		if not display_name:
			raise AccountLifecycleInternalServerError(
				message="display_name is required to check availability",
				code="ACCOUNT_LIFECYCLE_DISPLAY_NAME_INVALID",
			)
		try:
			return self.baskt_account_repository.is_exists_display_name(display_name)
		except AccountLifecycleInternalServerError:
			raise
		except Exception as err:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to check display name availability: {err}",
				code="ACCOUNT_LIFECYCLE_DISPLAY_NAME_CHECK_FAILED",
			) from err

	def permanently_close_baskt_account(
		self,
		*,
		cognito_user_id: str,
		alpaca_account_id: str
	) -> None:
		self.alpaca_broker_client.close_alpaca_account(alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
		self.cognito_client.delete_cognito_user(cognito_user_id=cognito_user_id)


	def update_display_name(
		self,
		cognito_user_id: str,
		display_name: str,
	) -> None:
		"""Update the user-facing display name stored by Baskt."""
		display_name = str(display_name).strip()
		if not display_name:
			raise AccountLifecycleInternalServerError(
				message="display_name is required to update a Baskt account",
				code="ACCOUNT_LIFECYCLE_UPDATE_DISPLAY_NAME_INVALID",
			)
		try:
			self.baskt_account_repository.update_display_name(
				cognito_user_id=cognito_user_id,
				display_name=display_name,
			)
		except Exception as err:
			raise AccountLifecycleInternalServerError(
				message=(
					"Failed to update display name for Cognito user "
					f"'{cognito_user_id}': {err}"
				),
				code="ACCOUNT_LIFECYCLE_UPDATE_DISPLAY_NAME_FAILED"
			) from err

	def update_description(self, cognito_user_id: str, description: str) -> None:
		"""Update the user-facing profile description stored by Baskt."""
		try:
			self.baskt_account_repository.update_description(
				cognito_user_id=cognito_user_id,
				description=str(description).strip(),
			)
		except Exception as err:
			raise AccountLifecycleInternalServerError(
				message=(
					"Failed to update description for Cognito user "
					f"'{cognito_user_id}': {err}"
				),
				code="ACCOUNT_LIFECYCLE_UPDATE_DESCRIPTION_FAILED",
			) from err

	def update_baskt_account(
		self,
		cognito_user_id: str,
		alpaca_account_id: str,
		updated_data: ContactData | IdentityData | DisclosuresData
	):

		try:
			self.alpaca_broker_client.update_alpaca_account(
				alpaca_account_id=alpaca_account_id,
				cognito_user_id=cognito_user_id,
				updated_data=updated_data
			)

		except Exception as err:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to update baskt account in alpaca for alpaca account '{alpaca_account_id}' and cognito user '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_UPDATE_BASKT_ACCOUNT_FAILED"
			) from err

		try:
			self.baskt_account_repository.update_baskt_account(
				cognito_user_id=cognito_user_id,
				updated_data=updated_data
			)

		except Exception as err:
			raise AccountLifecycleInternalServerError(
				message=f"Succeeded to update baskt account in alpaca, but failed to update in dynamodb for alpaca account '{alpaca_account_id}' and cognito user '{cognito_user_id}': {err}",
				code="ACCOUNT_LIFECYCLE_UPDATE_BASKT_ACCOUNT_FAILED"
			) from err

	def get_baskt_account(self, cognito_user_id: str) -> BasktAccount:
		"""Return the persisted Baskt account for an authenticated user."""
		try:
			return self.baskt_account_repository.get_baskt_account(
				cognito_user_id=cognito_user_id
			)
		except Exception as err:
			raise AccountLifecycleInternalServerError(
				message=(
					"Failed to get persisted Baskt account for Cognito user "
					f"'{cognito_user_id}': {err}"
				),
				code="ACCOUNT_LIFECYCLE_GET_BASKT_ACCOUNT_FAILED",
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

	#################################
	########## ACH & BANK ###########
	#################################

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


	def cancel_transfer(
		self,
		*,
		cognito_user_id: str,
		alpaca_account_id: str,
		transfer_id: str
	) -> None:
		"""Cancel an Alpaca transfer owned by the supplied broker account."""
		try:
			self.alpaca_broker_client.cancel_transfer(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				transfer_id=transfer_id
			)
		except AlpacaBrokerClientError as err:
			raise AccountLifecycleInternalServerError(
				message=f"Failed to cancel transfer '{transfer_id}' for cognito user '{cognito_user_id}' and alpaca account '{alpaca_account_id}': {err}",
				code="ACCOUNT_LIFECYCLE_CANCEL_TRANSFER_FAILED"
			) from err
			
			

		

		
		
	





		

	
		

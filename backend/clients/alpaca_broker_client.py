# backend/clients/alpaca_broker_client.py

# Python imports
from __future__ import annotations
from typing import Any, List, Dict

# Alpaca imports
from alpaca.broker.client import BrokerClient
from alpaca.broker.requests import CreateAccountRequest, CreateACHRelationshipRequest, CreateACHTransferRequest, CreateBankRequest, CreateBankTransferRequest, CreatePlaidRelationshipRequest, GetTransfersRequest
from alpaca.broker.enums import AccountType, BankAccountType, TransferDirection, TransferTiming, FeePaymentMethod, AccountSubType, IdentifierType
from alpaca.broker.models import (
    Contact, Identity, Disclosures, Agreement, Account, ACHRelationship, Bank, Transfer, TradeAccount, 
    AccountDocument, TaxIdType, VisaType, FundingSource, EmploymentStatus, AgreementType
)
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.models import Asset, Order, AccountConfiguration, PortfolioHistory
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.requests import GetPortfolioHistoryRequest

# Baskt imports
from domain.baskt import BasktPosition


class AlpacaBrokerClientError(Exception):
    """Raised when Alpaca Broker client operations fail."""

    def __init__(self, message: str, code: str):
        """
        Initialize an Alpaca broker client exception with a message and code.

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

class AlpacaBrokerClient:
    """Client wrapper for Alpaca Broker account lifecycle operations."""

    def __init__(
        self,
        *,
        alpaca_broker_api_key: str,
        alpaca_broker_api_secret: str,
        alpaca_env: str
    ) -> None:
        """
        Initialize trading and market-data clients for Alpaca.

        Args:
            alpaca_broker_api_key: Alpaca API key.
            alpaca_broker_api_secret: Alpaca API secret.

        Returns:
            None.

        Raises:
            Any exception raised by Alpaca's BrokerClient or
            StockHistoricalDataClient constructors if the clients cannot be
            initialized.
        """
        is_sandbox = alpaca_env.lower() == "sandbox"
        self.client = BrokerClient(
            api_key=alpaca_broker_api_key,
            secret_key=alpaca_broker_api_secret,
            sandbox=is_sandbox,
        )
        self.data_client = StockHistoricalDataClient(
            api_key=alpaca_broker_api_key,
            secret_key=alpaca_broker_api_secret,
            sandbox=is_sandbox,
        )

    def get_tradeable_fractionable_US_assets(self) -> List[Asset]:
        """
        Fetch all Alpaca assets and filter to tradable, fractionable US equities.

        Args:
            None.

        Returns:
            List[Asset]: Assets where tradable=True, fractionable=True,
            and asset_class is US_EQUITY.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the assets request,
            the network request fails, or any unexpected error occurs while
            fetching assets.
        """
        try:
            filter = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
            assets = self.client.get_all_assets(filter=filter)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to fetch tradable, fractionable US Alpaca assets: {e}",
                code="ALPACA_BROKER_GET_TRADEABLE_FRACTIONABLE_US_ASSETS_FAILED",
            )

        tradeable = []
        for asset in assets:
            asset_class = getattr(asset.asset_class, "name", asset.asset_class)
            if asset.tradable and asset_class in {"US_EQUITY", "us_equity"} and asset.fractionable:
                tradeable.append(asset)

        return tradeable
    
    def create_alpaca_account(self, account_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Create a broker account from Alpaca account payload sections.

        Args:
            account_data: Alpaca account payload sections. Required top-level
                keys are contact, identity, disclosures, and agreements.
                Optional top-level keys include account_type, account_sub_type,
                currency, enabled_assets, trusted_contact, and documents.

        Returns:
            Dict[str, str]: Created Alpaca account identifiers and the email
            address used to create the account.

        Raises:
            AlpacaBrokerClientError: If required payload fields are missing,
            invalid, Alpaca rejects the create-account request, the returned
            account does not include an id, or any unexpected error occurs.
        """
        try:
            contact_data: Dict[str,str] = account_data["contact"]
            identity_data: Dict[str, str] = account_data["identity"]
            disclosures_data: Dict[str, str] = account_data["disclosures"]
            agreements_data: List[Dict[str, str]] = account_data["agreements"]

            email_address = contact_data.get("email_address")
            if not email_address:
                raise ValueError("contact.email_address is required to create Cognito user")

            contact = Contact(
                email_address=contact_data["email_address"],
                phone_number=contact_data.get("phone_number"),
                street_address=contact_data["street_address"],
                unit=contact_data.get("unit"),
                city=contact_data["city"],
                state=contact_data.get("state"),
                postal_code=contact_data.get("postal_code", contact_data.get("postal")),
                country=contact_data.get("country"),
            )

            identity = Identity(
                given_name=identity_data["given_name"],
                middle_name=identity_data.get("middle_name"),
                family_name=identity_data["family_name"],
                date_of_birth=identity_data.get("date_of_birth"),
                tax_id=identity_data.get("tax_id"),
                tax_id_type=TaxIdType(identity_data.get("tax_id_type")),
                country_of_citizenship=identity_data.get("country_of_citizenship"),
                country_of_birth=identity_data.get("country_of_birth"),
                country_of_tax_residence=identity_data["country_of_tax_residence"],
                visa_type=VisaType(identity_data.get("visa_type")) if "visa_type" in identity_data else None,
                visa_expiration_date=identity_data.get("visa_expiration_date") if "visa_type" in identity_data else None,
                date_of_departure_from_usa=identity_data.get("date_of_departure_from_usa") if "visa_type" in identity_data else None,
                permanent_resident=identity_data.get("permanent_resident"),
                funding_source=[FundingSource(source) for source in identity_data.get("funding_source")],
                annual_income_min=identity_data.get("annual_income_min"),
                annual_income_max=identity_data.get("annual_income_max"),
                liquid_net_worth_min=identity_data.get("liquid_net_worth_min"),
                liquid_net_worth_max=identity_data.get("liquid_net_worth_max"),
                total_net_worth_min=identity_data.get("total_net_worth_min"),
                total_net_worth_max=identity_data.get("total_net_worth_max"),
            )

            disclosures = Disclosures(
                is_control_person=disclosures_data.get("is_control_person"),
                is_affiliated_exchange_or_finra=disclosures_data.get("is_affiliated_exchange_or_finra"),
                is_politically_exposed=disclosures_data.get("is_politically_exposed"),
                immediate_family_exposed=disclosures_data["immediate_family_exposed"],
                employment_status=EmploymentStatus(disclosures_data.get("employment_status")),
                employer_name=disclosures_data.get("employer_name"),
                employer_address=disclosures_data.get("employer_address"),
                employment_position=disclosures_data.get("employment_position"),
            )

            agreements = [
                Agreement(
                    agreement=AgreementType(agreement["agreement"]),
                    signed_at=agreement["signed_at"],
                    ip_address=agreement["ip_address"],
                    revision=agreement.get("revision"),
                )
                for agreement in agreements_data
            ]

            request = CreateAccountRequest(
                account_type=account_data.get("account_type", AccountType.TRADING),
                contact=contact,
                identity=identity,
                disclosures=disclosures,
                agreements=agreements,
                trusted_contact=account_data.get("trusted_contact"),
                documents=account_data.get("documents"),
                currency=account_data.get("currency"),
                enabled_assets=account_data.get("enabled_assets"),
            )
            alpaca_account = self.client.create_account(request)
            alpaca_account_id = str(getattr(alpaca_account, "id", None))
            alpaca_account_number = str(getattr(alpaca_account, "account_number", None))

            if not (alpaca_account_id and alpaca_account_id):
                raise AlpacaBrokerClientError(
                    message=f"Request to create alpaca account failed for user '{email_address}'",
                    code="ALPACA_BROKER_CREATE_ALPACA_ACCOUNT_FAILED"
                )
            
            return {
                "alpaca_account_id": alpaca_account_id,
                "alpaca_account_number": alpaca_account_number,
            }
        
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create Alpaca account: {e}",
                code="ALPACA_BROKER_CREATE_ALPACA_ACCOUNT_FAILED"
            )
        
    def get_alpaca_account_by_id(self, account_id: str, cognito_user_id: str) -> Account:
        """
        Fetch an Alpaca broker account by account ID.

        Args:
            account_id: Alpaca broker account ID to fetch.

        Returns:
            Account: Alpaca account model returned by the broker API.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the account lookup,
            the account does not exist or is inaccessible, the network request
            fails, or any unexpected error occurs.
        """
        try:
            return self.client.get_account_by_id(account_id=account_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get alpaca account by id for alpaca account id '{account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_ALPACA_ACCOUNT_BY_ID_FAILED"
            )
    
    
    def close_alpaca_account(self, account_id: str, cognito_user_id: str):
        """
        Close an Alpaca broker account.

        Args:
            account_id: Alpaca broker account ID to close.

        Returns:
            None.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the close-account
            request, the account does not exist or cannot be closed, the
            network request fails, or any unexpected error occurs.
        """
        try:
            self.client.close_account(account_id=account_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to close alpaca account for alpaca account id '{account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CLOSE_ALPACA_ACCOUNT_FAILED"
            )
        
    def get_alpaca_trade_account_by_id(self, account_id: str, cognito_user_id: str) -> TradeAccount:
        """
        Get the trade broker account
        """

        try:
            trade_account = self.client.get_trade_account_by_id(account_id=account_id)
            return trade_account
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get alpaca trade account for alpaca account id '{account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_TRADE_ACCOUNT_FAILED"
            )

    def create_direct_ach_relationship(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
        account_owner_name: str,
        bank_account_type: str,
        bank_account_number: str,
        bank_routing_number: str,
        nickname: str | None = None
    ) -> ACHRelationship:
        """
        Create a direct ACH relationship for an Alpaca broker account.

        Args:
            cognito_user_id: Cognito user ID used for error context.
            alpaca_account_id: Alpaca broker account ID that owns the ACH
                relationship.
            account_owner_name: Name of the bank account owner.
            bank_account_type: Bank account type, such as CHECKING or SAVINGS.
            bank_account_number: External bank account number.
            bank_routing_number: External bank routing number.
            nickname: Optional nickname for the ACH relationship.

        Returns:
            ACHRelationship: Alpaca ACH relationship response.

        Raises:
            AlpacaBrokerClientError: If required input is missing, enum values
            are invalid, Alpaca rejects the ACH relationship request, the
            network request fails, or any unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if not account_owner_name:
                raise ValueError("account_owner_name is required")
            if not bank_account_type:
                raise ValueError("bank_account_type is required")
            if not bank_account_number:
                raise ValueError("bank_account_number is required")
            if not bank_routing_number:
                raise ValueError("bank_routing_number is required")

            request = CreateACHRelationshipRequest(
                account_owner_name=account_owner_name,
                bank_account_type=BankAccountType(bank_account_type.upper()),
                bank_account_number=bank_account_number,
                bank_routing_number=bank_routing_number,
                nickname=nickname,
            )

            return self.client.create_ach_relationship_for_account(
                account_id=alpaca_account_id,
                ach_data=request,
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create ACH relationship for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CREATE_ACH_RELATIONSHIP_FAILED",
            ) from e
        

    def create_plaid_ach_relationship(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
        processor_token: str
    ) -> ACHRelationship:
        """
        Create an ACH relationship from a Plaid processor token.

        Args:
            cognito_user_id: Cognito user ID used for error context.
            alpaca_account_id: Alpaca broker account ID that owns the ACH
                relationship.
            processor_token: Plaid processor token created for Alpaca.

        Returns:
            ACHRelationship: Alpaca ACH relationship response.

        Raises:
            AlpacaBrokerClientError: If required input is missing, Alpaca
            rejects the Plaid ACH relationship request, the network request
            fails, or any unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if not processor_token:
                raise ValueError("processor_token is required")

            request = CreatePlaidRelationshipRequest(
                processor_token=processor_token
            )

            return self.client.create_ach_relationship_for_account(
                account_id=alpaca_account_id,
                ach_data=request
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create Plaid ACH relationship for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CREATE_PLAID_ACH_RELATIONSHIP_FAILED",
            ) from e
        

    def get_ach_relationships(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str
    ) -> List[ACHRelationship]:
        """
        Get ACH relationships for an Alpaca broker account.

        Args:
            cognito_user_id: Cognito user ID used for error context.
            alpaca_account_id: Alpaca broker account ID whose ACH
                relationships should be fetched.

        Returns:
            List[ACHRelationship]: ACH relationships returned by Alpaca.

        Raises:
            AlpacaBrokerClientError: If alpaca_account_id is missing, Alpaca
            rejects the lookup, the network request fails, or any unexpected
            error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")

            return self.client.get_ach_relationships_for_account(
                account_id=alpaca_account_id
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get ACH relationships for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_ACH_RELATIONSHIPS_FAILED",
            ) from e
        
    def delete_ach_relationship(
        self,
        cognito_user_id: str,
        alpaca_account_id: str,
        ach_relationship_id: str
    ) -> None:
        """
        Delete an ACH relationship from an Alpaca broker account.

        Args:
            cognito_user_id: Cognito user ID used for error context.
            alpaca_account_id: Alpaca broker account ID that owns the ACH
                relationship.
            ach_relationship_id: ACH relationship ID to delete.

        Returns:
            None.

        Raises:
            AlpacaBrokerClientError: If required input is missing, Alpaca
            rejects the delete request, the network request fails, or any
            unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if not ach_relationship_id:
                raise ValueError("ach_relationship_id is required")

            self.client.delete_ach_relationship_for_account(
                account_id=alpaca_account_id,
                ach_relationship_id=ach_relationship_id
            )
        
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to delete ACH Relationship '{ach_relationship_id}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_DELETE_ACH_RELATIONSHIP_FAILED"
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
        fee_payment_method: str | None = None,
    ) -> Transfer:
        """
        Create a direct ACH transfer for an Alpaca broker account.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the transfer.
            cognito_user_id: Cognito user ID used for error context.
            amount: Transfer amount. Converted to a string for Alpaca.
            direction: Transfer direction, such as INCOMING or OUTGOING.
            timing: Transfer timing, such as IMMEDIATE.
            relationship_id: ACH relationship ID to use for the transfer.
            fee_payment_method: Optional fee payment method, such as USER or
                INVOICE.

        Returns:
            Transfer | Dict[str, Any]: Alpaca transfer response.

        Raises:
            AlpacaBrokerClientError: If required input is missing, enum values
            are invalid, Alpaca rejects the transfer request, the network
            request fails, or any unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if amount is None:
                raise ValueError("amount is required")
            if not direction:
                raise ValueError("direction is required")
            if not timing:
                raise ValueError("timing is required")
            if not relationship_id:
                raise ValueError("relationship_id is required")

            request = CreateACHTransferRequest(
                amount=str(amount),
                direction=TransferDirection(direction.upper()),
                timing=TransferTiming(timing.lower()),
                fee_payment_method=FeePaymentMethod(fee_payment_method.lower()) if fee_payment_method else None,
                relationship_id=relationship_id,
            )

            return self.client.create_transfer_for_account(
                account_id=alpaca_account_id,
                transfer_data=request
            )
        
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create ach transfer for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CREATE_ACH_TRANSFER_FAILED",
            ) from e
        
    
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
    ) -> Bank:
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
            AlpacaBrokerClientError: If required input is missing, enum values
            are invalid, Alpaca rejects the bank request, the network request
            fails, or any unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if not name:
                raise ValueError("name is required")
            if not bank_code_type:
                raise ValueError("bank_code_type is required")
            if not bank_code:
                raise ValueError("bank_code is required")
            if not account_number:
                raise ValueError("account_number is required")

            request = CreateBankRequest(
                name=name,
                bank_code_type=IdentifierType(bank_code_type.upper()),
                bank_code=bank_code,
                account_number=account_number,
                country=country,
                state_province=state_province,
                postal_code=postal_code,
                city=city,
                street_address=street_address
            )

            return self.client.create_bank_for_account(
                account_id=alpaca_account_id,
                bank_data=request,
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create bank request for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CREATE_BANK_REQUEST_FAILED",
            ) from e
        

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
            AlpacaBrokerClientError: If alpaca_account_id is missing, Alpaca
            rejects the lookup, the network request fails, or any unexpected
            error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")

            return self.client.get_banks_for_account(
                account_id=alpaca_account_id
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get banks for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_BANKS_FAILED",
            ) from e
        

    def delete_bank(
        self,
        cognito_user_id: str,
        alpaca_account_id: str,
        bank_id: str
    ) -> None:
        """
        Delete a bank relationship from an Alpaca broker account.

        Args:
            cognito_user_id: Cognito user ID used for error context.
            alpaca_account_id: Alpaca broker account ID that owns the bank
                relationship.
            bank_id: Bank relationship ID to delete.

        Returns:
            None.

        Raises:
            AlpacaBrokerClientError: If required input is missing, Alpaca
            rejects the delete request, the network request fails, or any
            unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if not bank_id:
                raise ValueError("bank_id is required")

            self.client.delete_bank_for_account(
                account_id=alpaca_account_id,
                bank_id=bank_id
            )
        
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to delete bank '{bank_id}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_DELETE_BANK_FAILED"
            ) from e

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
    ) -> Transfer:
        """
        Create a wire transfer for an Alpaca broker account.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the transfer.
            cognito_user_id: Cognito user ID used for error context.
            amount: Transfer amount. Converted to a string for Alpaca.
            direction: Transfer direction, such as INCOMING or OUTGOING.
            timing: Transfer timing, such as IMMEDIATE.
            bank_id: Bank relationship ID to use for the wire transfer.
            fee_payment_method: Optional fee payment method, such as USER or
                INVOICE.
            additional_information: Optional wire transfer instructions.

        Returns:
            Transfer | Dict[str, Any]: Alpaca transfer response.

        Raises:
            AlpacaBrokerClientError: If required input is missing, enum values
            are invalid, Alpaca rejects the transfer request, the network
            request fails, or any unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if amount is None:
                raise ValueError("amount is required")
            if not direction:
                raise ValueError("direction is required")
            if not timing:
                raise ValueError("timing is required")
            if not bank_id:
                raise ValueError("bank_id is required")

            request = CreateBankTransferRequest(
                amount=str(amount),
                direction=TransferDirection(direction.upper()),
                timing=TransferTiming(timing.lower()),
                fee_payment_method=FeePaymentMethod(fee_payment_method.lower()) if fee_payment_method else None,
                bank_id=bank_id,
                additional_information=additional_information
            )

            return self.client.create_transfer_for_account(
                account_id=alpaca_account_id,
                transfer_data=request
            )
        
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create bank transfer for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CREATE_BANK_TRANSFER_FAILED",
            ) from e
        

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
            AlpacaBrokerClientError: If alpaca_account_id is missing, Alpaca
            rejects the lookup, the network request fails, or any unexpected
            error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if limit is not None and limit < 1:
                raise ValueError("limit must be greater than 0")
            if offset < 0:
                raise ValueError("offset must be greater than or equal to 0")

            transfers_filter = GetTransfersRequest(limit=limit, offset=offset)

            return self.client.get_transfers_for_account(
                account_id=alpaca_account_id,
                transfers_filter=transfers_filter,
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get transfers for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_TRANSFERS_FAILED",
            ) from e
            
        

    

    def execute_close_position(self, symbol: str, alpaca_account_id: str, cognito_user_id) -> Order:
        """
        Submit an order request to close an open position for a symbol.

        Args:
            symbol: Ticker symbol or asset identifier to close.
            alpaca_account_id: Alpaca broker account ID that owns the position.
            cognito_user_id: Cognito user ID used for error context.

        Returns:
            Order: Alpaca order response for the close-position request.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the close-position
            request, the position does not exist or is inaccessible, the
            network request fails, or any unexpected error occurs.
        """

        try:
            return self.client.close_position_for_account(account_id=alpaca_account_id, symbol_or_asset_id=symbol)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to close Alpaca position '{symbol}' for alpaca account {alpaca_account_id} and cognito user id {cognito_user_id}: {e}",
                code="ALPACA_BROKER_EXECUTE_CLOSE_POSITION_FAILED",
            )
        

    def execute_close_all_position(self, alpaca_account_id: str, cognito_user_id) -> Order:
        """
        Submit an order request to close all open positions for a broker account.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the position.
            cognito_user_id: Cognito user ID used for error context.

        Returns:
            Order: Alpaca order response for the close-position request.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the close-position
            request, the position does not exist or is inaccessible, the
            network request fails, or any unexpected error occurs.
        """

        try:
            return self.client.close_all_positions_for_account(account_id=alpaca_account_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to close all open positions for alpaca account {alpaca_account_id} and cognito user id {cognito_user_id}: {e}",
                code="ALPACA_BROKER_EXECUTE_CLOSE_ALL_POSITION_FAILED",
            )



    def execute_quantity_buy(self, symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id) -> Order:
        """
        Submit a market buy order for a specific quantity for a broker account.

        Args:
            symbol: Ticker symbol to buy.
            quantity: Number of shares to buy.
            alpaca_account_id: Alpaca broker account ID.
            cognito_user_id: Cognito user ID (for logging/tracking).

        Returns:
            Order: Alpaca order response for the buy request.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the buy order, the
            request is invalid, the account is inaccessible, the network
            request fails, or any unexpected error occurs.
        """
        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        try:
            return self.client.submit_order_for_account(account_id=alpaca_account_id, order_data=order_req)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to submit buy order for '{symbol}' for alpacaa account id '{alpaca_account_id}' and cognito_user_id '{cognito_user_id}'): {e}",
                code="ALPACA_BROKER_EXECUTE_QUANTITY_BUY_FAILED",
            )



    def execute_quantity_fractional_sell(self, symbol: str, quantity, alpaca_account_id: str, cognito_user_id) -> List[Order | None]:
        """
        Reduce a position using a two-step order flow for fractional quantities for a broker account.

        The method first sells ceil(quantity) shares, then optionally buys back
        the overage to land on the exact fractional reduction.

        Args:
            symbol: Ticker symbol to sell.
            quantity: Quantity to reduce from the position; may be fractional.
            alpaca_account_id: Alpaca broker account ID.
            cognito_user_id: Cognito user ID (for logging/tracking).

        Returns:
            List[Order | None]: The initial sell order and an optional
            buy-back order. The second item is None when no buy-back is needed.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the initial sell order
            or the optional buy-back order, the request is invalid, the account
            is inaccessible, the network request fails, or any unexpected
            error occurs while submitting either order.
        """
        from math import ceil
        from time import sleep

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=ceil(quantity),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        try:
            order1 = self.client.submit_order_for_account(account_id=alpaca_account_id, order_data=order_req)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to submit initial fractional sell for '{symbol}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_FRACTIONAL_SELL_FAILED",
            )

        if ceil(quantity) - quantity <= 0:
            return [order1, None]

        order1_id = order1.id
        while self.get_order_by_id(order1_id).status.name != "FILLED":
            sleep(0.25)

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=ceil(quantity) - quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )

        try:
            order2 = self.client.submit_order_for_account(account_id=alpaca_account_id, order_data=order_req)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to submit fractional buy-back for '{symbol}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_FRACTIONAL_BUYBACK_FAILED",
            )
        return [order1, order2]



    def execute_quantity_sell(self, symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id) -> Order:
        """
        Submit a market sell order for a specific quantity for a broker account.

        Args:
            symbol: Ticker symbol to sell.
            quantity: Number of shares to sell.
            alpaca_account_id: Alpaca broker account ID.
            cognito_user_id: Cognito user ID (for logging/tracking).

        Returns:
            Order: Alpaca order response for the sell request.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the sell order, the
            request is invalid, the account is inaccessible, the network
            request fails, or any unexpected error occurs.
        """
        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        try:
            return self.client.submit_order_for_account(account_id=alpaca_account_id, order_data=order_req)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to submit sell order for '{symbol}' for alpaca account id {alpaca_account_id} and cognito_user_id {cognito_user_id}: {e}",
                code="ALPACA_BROKER_SELL_ORDER_FAILED",
            )
        
    def get_latest_price(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch latest trade prices for each requested symbol.

        Args:
            symbols: List of ticker symbols.

        Returns:
            Dict[str, float]: Mapping of symbol to latest price.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the latest-price
            request, the network request fails, no latest price is returned
            for a requested symbol, or any unexpected error occurs while
            fetching prices.
        """
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = self.data_client.get_stock_latest_trade(request)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to fetch latest prices for symbols {symbols}: {e}",
                code="ALPACA_BROKER_GET_LATEST_PRICE_FAILED",
            )
        result = {}
        for symbol in symbols:
            if symbol not in quotes:
                raise AlpacaBrokerClientError(
                    message=f"Latest price missing for symbol '{symbol}': {e}",
                    code="ALPACA_BROKER_MISSING_LATEST_PRICE",
                )
            result[symbol] = quotes[symbol].price 

        return result
    

    def get_baskt_positions_dict(self, alpaca_account_id: str, cognito_user_id: str) -> Dict[str, BasktPosition]:
        """
        Fetch all positions for an Alpaca account and convert them to Baskt positions.

        Args:
            alpaca_account_id: Alpaca broker account ID whose positions should
                be fetched.

        Returns:
            Dict[str, BasktPosition]: Mapping of ticker symbol to BasktPosition.

        Raises:
            Any exception raised by Alpaca's get_all_positions_for_account call
            if the account is inaccessible, the network request fails, or
            Alpaca rejects the positions request. Exceptions may also be raised
            while constructing BasktPosition values from malformed Alpaca
            position data.
        """
        try:
            positions = self.client.get_all_positions_for_account(account_id=alpaca_account_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get baskt positions as dict for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="GET_BASKT_POSITIONS_DICT_FAILED"
            )
        return {
            position.symbol: BasktPosition(
                symbol=position.symbol, 
                filled_avg_price=float(position.avg_entry_price), 
                filled_quantity=float(position.qty),
                direction=1 if position.side.name == "LONG" else -1
            )
            for position in positions
        }
    
    def get_order_by_id(self, alpaca_account_id: str, cognito_user_id: str, order_id: str):
        """
        Fetch an Alpaca order by account ID and order ID.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the order.
            order_id: Alpaca order ID to fetch.

        Returns:
            Order: Alpaca order model returned by the broker API.

        Raises:
            Any exception raised by Alpaca's get_order_for_account_by_id call
            if the order does not exist, the account is inaccessible, the
            network request fails, or Alpaca rejects the order lookup.
        """
        try:
            return self.client.get_order_for_account_by_id(account_id=alpaca_account_id, order_id=order_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get order by id for alpaca account id '{alpaca_account_id}', cognito_user_id '{cognito_user_id}', and order id '{order_id}': {e}",
                code = "ALPACA_BROKER_GET_ORDER_BY_ID_FAILED"
            )
        
    def get_account_performance(self, alpaca_account_id: str) -> Dict[str, Dict[str, Any]]:
        try:
            periods_and_timeframes = [
                ["1D","5Min"],
                ["1W", "1H"],
                ["1M", "1D"],
                ["3M", "1D"],
                ["1A", "1D"]
            ]

            account_performance = {}

            for period, timeframe in periods_and_timeframes:

                portfolio_history = self.client.get_portfolio_history_for_account(
                    account_id=alpaca_account_id,
                    history_filter=GetPortfolioHistoryRequest(
                        period=period,
                        timeframe=timeframe
                    )
                )

                account_performance[period] = {
                    "equity": portfolio_history.equity,
                    "timestamp": portfolio_history.timestamp,
                    "profit_loss": portfolio_history.profit_loss,
                    "profit_loss_pct": portfolio_history.profit_loss_pct,
                    "base_value": portfolio_history.base_value
                }

            return account_performance

        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get account performance for alpaca account id '{alpaca_account_id}': {e}",
                code="ALPACA_BROKER_GET_ACCOUNT_PERFORMANCE_FAILED"
            ) from e







    

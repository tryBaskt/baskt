# backend/clients/alpaca_broker_client.py

# Python imports
from __future__ import annotations
from typing import Any, List, Dict, Optional
from datetime import date, datetime, timezone, timedelta
from uuid import UUID
from dataclasses import asdict, is_dataclass

# Pandas imports
import pandas as pd

# Alpaca imports
from alpaca.broker.client import BrokerClient
from alpaca.broker.requests import (
    CreateAccountRequest,
    CreateACHRelationshipRequest,
    CreateACHTransferRequest,
    CreateBankRequest,
    CreateBankTransferRequest,
    CreatePlaidRelationshipRequest,
    GetTransfersRequest,
    UpdatableContact,
    UpdatableDisclosures,
    UpdatableIdentity,
    UpdatableTrustedContact,
    UpdateAccountRequest
)
from alpaca.broker.enums import AccountType, BankAccountType, TransferDirection, TransferTiming, FeePaymentMethod, IdentifierType
from alpaca.broker.models import (
    Contact, Identity, Disclosures, Agreement, Account, ACHRelationship, Bank, Transfer, TradeAccount, 
    TaxIdType, VisaType, FundingSource, EmploymentStatus, AgreementType
)
from alpaca.trading.requests import GetAssetsRequest, GetCalendarRequest, MarketOrderRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import AssetClass, AssetStatus, OrderSide, TimeInForce
from alpaca.trading.models import Asset, Calendar, Order, FailedClosePositionDetails, PortfolioHistory
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.common.exceptions import APIError

# Baskt imports
from domain.baskt_domain import BasktPosition
from domain.stock_domain import Stock
from domain.baskt_account_domain import ContactData, IdentityData, DisclosuresData


CRYPTO_ELIGIBLE_US_STATES = frozenset(
    {
        "AZ", "ARIZONA", "CA", "CALIFORNIA", "CT", "CONNECTICUT",
        "GA", "GEORGIA", "ID", "IDAHO", "IL", "ILLINOIS", "IN", "INDIANA",
        "IA", "IOWA", "KS", "KANSAS", "KY", "KENTUCKY", "ME", "MAINE",
        "MD", "MARYLAND", "MA", "MASSACHUSETTS", "MI", "MICHIGAN",
        "MS", "MISSISSIPPI", "MO", "MISSOURI", "MT", "MONTANA",
        "NE", "NEBRASKA", "NC", "NORTH CAROLINA", "ND", "NORTH DAKOTA",
        "OH", "OHIO", "RI", "RHODE ISLAND", "SC", "SOUTH CAROLINA",
        "SD", "SOUTH DAKOTA", "UT", "UTAH", "VT", "VERMONT",
        "WA", "WASHINGTON", "WV", "WEST VIRGINIA",
    }
)


class AlpacaBrokerClientError(Exception):
    """Raised when Alpaca Broker client operations fail."""

    def __init__(self, message: str, code: str) -> None:
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
            alpaca_env: Alpaca environment name. Use "sandbox" for sandbox
                broker API calls; any other value creates a live client.

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

    ###########################
    ######## BACKTEST #########
    ###########################

    def get_tradeable_fractionable_US_assets(self) -> List[Asset]:
        """
        Fetch active US equity assets and filter to tradable, fractionable
        securities.

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
            # GetAssetsRequest does not expose tradable/fractionable fields in
            # this SDK version, so those checks are applied below.
            asset_filter = GetAssetsRequest(
                status=AssetStatus.ACTIVE,
                asset_class=AssetClass.US_EQUITY,
            )
            assets = self.client.get_all_assets(filter=asset_filter)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to fetch tradable, fractionable US Alpaca assets: {e}",
                code="ALPACA_BROKER_GET_TRADEABLE_FRACTIONABLE_US_ASSETS_FAILED",
            )

        tradeable: List[Asset] = []
        for asset in assets:
            asset_class = getattr(asset.asset_class, "name", asset.asset_class)
            if getattr(asset, "tradable", False) and asset_class in {"US_EQUITY", "us_equity"} and getattr(asset, "fractionable", False):
                tradeable.append(asset)

        return tradeable
    
    ######################################
    ######## ACCOUNT LIFECYCLE ###########
    ######################################
    
    def create_alpaca_account(self, account_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Create a broker account from Alpaca account payload sections.

        Args:
            account_data: Alpaca account payload sections. Required top-level
                keys are contact, identity, disclosures, and agreements.
                Optional top-level keys include account_type, account_sub_type,
                currency, enabled_assets, trusted_contact, documents, and
                trading_configurations.

        Returns:
            Dict[str, str]: Created Alpaca account identifiers.

        Raises:
            AlpacaBrokerClientError: If required payload fields are missing,
            invalid, Alpaca rejects the create-account request, the returned
            account does not include an id, or any unexpected error occurs.
        """
        try:
            contact_data: Dict[str, str] = account_data["contact"]
            identity_data: Dict[str, str] = account_data["identity"]
            disclosures_data: Dict[str, str] = account_data["disclosures"]
            agreements_data: List[Dict[str, str]] = account_data["agreements"]

            email_address = contact_data["email_address"]

            contact = Contact(
                email_address=email_address,
                phone_number=contact_data.get("phone_number"),
                street_address=contact_data["street_address"],
                unit=contact_data.get("unit"),
                city=contact_data["city"],
                state=contact_data.get("state"),
                postal_code=contact_data.get("postal_code"),
                country=contact_data.get("country"),
            )

            funding_source = None
            funding_source_data = identity_data.get("funding_source")
            if isinstance(funding_source_data, str):
                funding_source = [FundingSource(funding_source_data)]
            elif funding_source_data:
                funding_source = [FundingSource(source) for source in funding_source_data]

            identity = Identity(
                given_name=identity_data["given_name"],
                middle_name=identity_data.get("middle_name"),
                family_name=identity_data["family_name"],
                date_of_birth=identity_data.get("date_of_birth"),
                tax_id=identity_data.get("tax_id"),
                tax_id_type=TaxIdType(identity_data.get("tax_id_type")) if "tax_id_type" in identity_data else None,
                country_of_citizenship=identity_data.get("country_of_citizenship"),
                country_of_birth=identity_data.get("country_of_birth"),
                country_of_tax_residence=identity_data["country_of_tax_residence"],
                visa_type=VisaType(identity_data.get("visa_type")) if "visa_type" in identity_data else None,
                visa_expiration_date=identity_data.get("visa_expiration_date") if "visa_type" in identity_data else None,
                date_of_departure_from_usa=identity_data.get("date_of_departure_from_usa") if "visa_type" in identity_data else None,
                permanent_resident=identity_data.get("permanent_resident"),
                funding_source=funding_source,
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
                employment_status=EmploymentStatus(disclosures_data.get("employment_status")) if "employment_status" in disclosures_data else None,
                employer_name=disclosures_data.get("employer_name"),
                employer_address=disclosures_data.get("employer_address"),
                employment_position=disclosures_data.get("employment_position"),
            )

            country = str(contact_data.get("country", "")).strip().upper()
            state = str(contact_data.get("state", "")).strip().upper()
            is_crypto_eligible = country == "USA" and state in CRYPTO_ELIGIBLE_US_STATES

            agreements: List[Agreement] = []
            for agreement_data in agreements_data:
                agreement_type = AgreementType(agreement_data["agreement"])
                if agreement_type == AgreementType.CRYPTO and not is_crypto_eligible:
                    continue
                agreements.append(
                    Agreement(
                        agreement=agreement_type,
                        signed_at=agreement_data["signed_at"],
                        ip_address=agreement_data["ip_address"],
                        revision=agreement_data.get("revision"),
                    )
                )

            trading_configurations = account_data.get(
                "trading_configurations",
                {
                    "max_margin_multiplier": "2",
                    "no_shorting": False,
                    "disable_overnight_trading": False,
                    "fractional_trading": True,
                },
            )

            request = CreateAccountRequest(
                account_type=AccountType(account_data.get("account_type")) if "account_type" in account_data else None,
                contact=contact,
                identity=identity,
                disclosures=disclosures,
                agreements=agreements
            )
            request_payload = request.to_request_fields()
            request_payload["trading_configurations"] = trading_configurations

            alpaca_account = self.client.post("/accounts", request_payload)
            alpaca_account_id = str(alpaca_account.get("id"))
            alpaca_account_number = str(alpaca_account.get("account_number"))


            if not alpaca_account_id or alpaca_account_id == "None" or not alpaca_account_number or alpaca_account_number == "None":
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
        
    def update_alpaca_account(self, alpaca_account_id: str, cognito_user_id: str, updated_data: ContactData|IdentityData|DisclosuresData):

        try:
            update_account_request = None
            updated_data_type = type(updated_data).__name__

            if is_dataclass(updated_data) and updated_data_type == "ContactData":
                update_account_request = UpdateAccountRequest(
                    contact=asdict(updated_data)
                )
            elif is_dataclass(updated_data) and updated_data_type == "IdentityData":
                identity_update_data = asdict(updated_data)
                identity_update_data.pop("tax_id_type", None)
                if str(
                    identity_update_data.get("country_of_citizenship", "")
                ).upper() == "USA":
                    identity_update_data.pop("permanent_resident", None)
                update_account_request = UpdateAccountRequest(
                    identity=identity_update_data
                )
            elif (
                is_dataclass(updated_data)
                and updated_data_type == "DisclosuresData"
            ):
                update_account_request = UpdateAccountRequest(
                    disclosures=asdict(updated_data)
                )
            else:
                raise AlpacaBrokerClientError(
                    message=(
                        "Updated data not one of "
                        "(contact, identity, disclosures); received "
                        f"{type(updated_data).__module__}."
                        f"{updated_data_type}"
                    ),
                    code="ALPACA_BROKER_UPDATE_ALPACA_ACCOUNT_FAILED",
                )

            self.client.update_account(account_id=alpaca_account_id, update_data=update_account_request)

        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to update alpaca account for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_UPDATE_ALPACA_ACCOUNT_FAILED"
            )

    def get_alpaca_account_by_id(self, account_id: str, cognito_user_id: str) -> Account:
        """
        Fetch an Alpaca broker account by account ID.

        Args:
            account_id: Alpaca broker account ID to fetch.
            cognito_user_id: Cognito user ID used for error context.

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

    
    def close_alpaca_account(self, alpaca_account_id: str, cognito_user_id: str) -> None:
        """
        Close an Alpaca broker account.

        Args:
            account_id: Alpaca broker account ID to close.
            cognito_user_id: Cognito user ID used for error context.

        Returns:
            None.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the close-account
            request, the account does not exist or cannot be closed, the
            network request fails, or any unexpected error occurs.
        """
        try:
            self.client.close_account(account_id=alpaca_account_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to close alpaca account for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CLOSE_ALPACA_ACCOUNT_FAILED"
            )

    def get_trade_account(self, account_id: str, cognito_user_id: str) -> TradeAccount:
        """
        Fetch a trade account from Alpaca by broker account ID.

        Args:
            account_id: Alpaca broker account ID whose trade account should be
            retrieved.
            cognito_user_id: Cognito user ID associated with the account. Used
            for error context and logging.

        Returns:
            TradeAccount: Alpaca trade account model containing trading status,
            buying power, cash, equity, margin, and transferability fields.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the request, the account
            does not exist or cannot be accessed, the network request fails, or
            any unexpected error occurs while fetching the trade account.
        """

        try:
            validated_account_id = UUID(str(account_id))
            trade_account_data = self.client.get(
                f"/trading/accounts/{validated_account_id}/account"
            )
            trade_account_data.setdefault("last_daytrading_buying_power", None)
            trade_account_data.setdefault("last_daytrade_count", None)
            return TradeAccount(**trade_account_data)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get alpaca trade account for alpaca account id '{account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_TRADE_ACCOUNT_FAILED"
            ) from e

    def create_direct_ach_relationship(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
        account_owner_name: str,
        bank_account_type: str,
        bank_account_number: str,
        bank_routing_number: str,
        nickname: Optional[str] = None
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
                message=f"Failed to create direct ACH relationship for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
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
        fee_payment_method: Optional[str] = None,
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
            Transfer: Alpaca transfer response.

        Raises:
            AlpacaBrokerClientError: If required input is missing, enum values
            are invalid, Alpaca rejects the transfer request, the network
            request fails, or any unexpected error occurs.
        """
        try:
            request = CreateACHTransferRequest(
                amount=amount,
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
        country: Optional[str] = None,
        state_province: Optional[str] = None,
        postal_code: Optional[str] = None,
        city: Optional[str] = None,
        street_address: Optional[str] = None
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
        fee_payment_method: Optional[str] = None,
        additional_information: Optional[str] = None
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
            Transfer: Alpaca transfer response.

        Raises:
            AlpacaBrokerClientError: If required input is missing, enum values
            are invalid, Alpaca rejects the transfer request, the network
            request fails, or any unexpected error occurs.
        """
        try:

            request = CreateBankTransferRequest(
                amount=amount,
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
            AlpacaBrokerClientError: If alpaca_account_id is missing, Alpaca
            rejects the lookup, the network request fails, or any unexpected
            error occurs.
        """
        try:
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


    def cancel_transfer(
        self,
        *,
        cognito_user_id: str,
        alpaca_account_id: str,
        transfer_id: str
    ) -> None:
        """Cancel a transfer for an Alpaca broker account.

        Alpaca retains the transfer record and changes its status after a
        successful cancellation.
        """
        try:
            self.client.cancel_transfer_for_account(
                account_id=alpaca_account_id,
                transfer_id=transfer_id
            )
        except Exception as err:
            raise AlpacaBrokerClientError(
                message=f"Failed to cancel transfer '{transfer_id}' for cognito user '{cognito_user_id}' and alpaca account '{alpaca_account_id}': {err}",
                code="ALPACA_BROKER_CANCEL_TRANSFER_FAILED"
            ) from err
            
    ##############################
    ###### TRADE EXECUTION #######
    ##############################

    def _wait_for_filled_order(
        self,
        order: Order,
        alpaca_account_id: str,
        cognito_user_id: str,
    ) -> None:
        """Wait until an accepted broker order fills or reaches a terminal state."""
        from time import monotonic, sleep

        order_id = str(order.id)
        timeout_seconds = 30.0
        poll_interval_seconds = 0.25
        deadline = monotonic() + timeout_seconds
        latest_status = "UNKNOWN"
        while monotonic() < deadline:
            latest_order = self.get_order_by_id(
                alpaca_account_id=alpaca_account_id,
                cognito_user_id=cognito_user_id,
                order_id=order_id,
            )
            latest_status = str(
                getattr(latest_order.status, "name", latest_order.status)
            ).upper()
            if latest_status == "FILLED":
                return
            if latest_status in {"CANCELED", "EXPIRED", "REJECTED", "REPLACED"}:
                raise AlpacaBrokerClientError(
                    message=(
                        f"Order '{order_id}' for '{order.symbol}' reached terminal "
                        f"status '{latest_status}' before filling for Alpaca account "
                        f"'{alpaca_account_id}' and Cognito user '{cognito_user_id}'."
                    ),
                    code="ALPACA_BROKER_ORDER_NOT_FILLED",
                )
            sleep(poll_interval_seconds)

        raise AlpacaBrokerClientError(
            message=(
                f"Timed out waiting for order '{order_id}' for '{order.symbol}' "
                f"to fill for Alpaca account '{alpaca_account_id}' and Cognito "
                f"user '{cognito_user_id}'. Last status: {latest_status}."
            ),
            code="ALPACA_BROKER_ORDER_FILL_TIMEOUT",
        )

    def execute_close_all_position(self, alpaca_account_id: str, cognito_user_id: str) -> List[Order | FailedClosePositionDetails]:
        """
        Submit an order request to close all open positions for a broker account.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the position.
            cognito_user_id: Cognito user ID used for error context.

        Returns:
            List[Order | FailedClosePositionDetails]: One response body for
            each attempted close-position request.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the close-position
            request, the position does not exist or is inaccessible, the
            network request fails, or any unexpected error occurs.
        """

        try:
            close_positions_response = self.client.close_all_positions_for_account(account_id=alpaca_account_id)
            return [
                close_position.body for close_position in close_positions_response
            ]
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to close all open positions for alpaca account {alpaca_account_id} and cognito user id {cognito_user_id}: {e}",
                code="ALPACA_BROKER_EXECUTE_CLOSE_ALL_POSITION_FAILED",
            )
        

    def execute_close_position(self, symbol: str, alpaca_account_id: str, cognito_user_id: str) -> Order:
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


    def execute_long_to_short_sell(
        self,
        symbol: str,
        quantity: float,
        curr_quantity: float,
        alpaca_account_id: str,
        cognito_user_id: str,
    ) -> List[Order]:
        """Close a long position, then open the requested residual short."""
        if quantity <= curr_quantity:
            raise AlpacaBrokerClientError(
                message=(
                    f"Long-to-short quantity '{quantity}' must exceed current "
                    f"quantity '{curr_quantity}' for '{symbol}'."
                ),
                code="ALPACA_BROKER_LONG_TO_SHORT_QUANTITY_INVALID",
            )

        close_order = self.execute_close_position(
            symbol=symbol,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        self._wait_for_filled_order(
            order=close_order,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        short_orders = self.execute_quantity_fractional_sell(
            symbol=symbol,
            quantity=quantity - curr_quantity,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        return [close_order] + [order for order in short_orders if order is not None]


    def execute_short_to_long_buy(
        self,
        symbol: str,
        quantity: float,
        curr_quantity: float,
        alpaca_account_id: str,
        cognito_user_id: str,
    ) -> List[Order]:
        """Close a short position, then open the requested residual long."""
        if quantity <= curr_quantity:
            raise AlpacaBrokerClientError(
                message=(
                    f"Short-to-long quantity '{quantity}' must exceed current "
                    f"quantity '{curr_quantity}' for '{symbol}'."
                ),
                code="ALPACA_BROKER_SHORT_TO_LONG_QUANTITY_INVALID",
            )

        close_order = self.execute_close_position(
            symbol=symbol,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        self._wait_for_filled_order(
            order=close_order,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        buy_order = self.execute_quantity_buy(
            symbol=symbol,
            quantity=quantity - curr_quantity,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        return [close_order, buy_order]



    def execute_quantity_buy(self, symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str) -> Order:
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
        print("random print statement in execute quantity buy")
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
                message=f"Failed to submit buy order for '{symbol}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_EXECUTE_QUANTITY_BUY_FAILED",
            )


    def execute_quantity_sell(self, symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str) -> Order:
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

    def execute_quantity_fractional_sell(self, symbol: str, quantity: float, alpaca_account_id: str, cognito_user_id: str) -> List[Optional[Order]]:
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
            List[Optional[Order]]: The initial sell order and an optional
            buy-back order. The second item is None when no buy-back is needed.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the initial sell order
            or the optional buy-back order, the request is invalid, the account
            is inaccessible, the network request fails, or any unexpected
            error occurs while submitting either order.
        """
        from math import ceil

        try:
            order1 = self.execute_quantity_sell(symbol=symbol, quantity=ceil(quantity), alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to submit initial fractional sell for '{symbol}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_FRACTIONAL_SELL_FAILED",
            )

        if ceil(quantity) - quantity <= 0:
            return [order1, None]

        self._wait_for_filled_order(order=order1, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)

        try:
            order2 = self.execute_quantity_buy(symbol=symbol, quantity=ceil(quantity)-quantity, alpaca_account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to submit fractional buy-back for '{symbol}' for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_FRACTIONAL_BUYBACK_FAILED",
            )
        return [order1, order2]
        
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
        if not symbols:
            return {}
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = self.data_client.get_stock_latest_trade(request)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to fetch latest prices for symbols {symbols}: {e}",
                code="ALPACA_BROKER_GET_LATEST_PRICE_FAILED",
            )
        result: Dict[str, float] = {}
        for symbol in symbols:
            if symbol not in quotes:
                raise AlpacaBrokerClientError(
                    message=f"Latest price missing for symbol '{symbol}'",
                    code="ALPACA_BROKER_MISSING_LATEST_PRICE",
                )
            result[symbol] = float(quotes[symbol].price)

        return result
    
    def get_baskt_positions_dict(self, alpaca_account_id: str, cognito_user_id: str) -> Dict[str, BasktPosition]:
        """
        Fetch all positions for an Alpaca account and convert them to Baskt positions.

        Args:
            alpaca_account_id: Alpaca broker account ID whose positions should
                be fetched.
            cognito_user_id: Cognito user ID used for error context.

        Returns:
            Dict[str, BasktPosition]: Mapping of ticker symbol to BasktPosition.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects the positions request,
            the account is inaccessible, the network request fails, or any
            unexpected error occurs while fetching positions.
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
                filled_quantity=abs(float(position.qty)),
                direction=1 if position.side.name == "LONG" else -1
            )
            for position in positions
        }
    
    def get_order_by_id(self, alpaca_account_id: str, cognito_user_id: str, order_id: str) -> Order:
        """
        Fetch an Alpaca order by account ID and order ID.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the order.
            cognito_user_id: Cognito user ID used for error context.
            order_id: Alpaca order ID to fetch.

        Returns:
            Order: Alpaca order model returned by the broker API.

        Raises:
            AlpacaBrokerClientError: If the order does not exist, the account
            is inaccessible, the network request fails, Alpaca rejects the
            order lookup, or any unexpected error occurs.
        """
        try:
            return self.client.get_order_for_account_by_id(account_id=alpaca_account_id, order_id=order_id)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get order by id for alpaca account id '{alpaca_account_id}', cognito_user_id '{cognito_user_id}', and order id '{order_id}': {e}",
                code = "ALPACA_BROKER_GET_ORDER_BY_ID_FAILED"
            )
        
    def get_position_by_asset_id(self, alpaca_account_id: str, cognito_user_id: str, asset_id: str, error_if_no_position: bool = False) -> BasktPosition | None:
        try:
            position = self.client.get_open_position_for_account(
                account_id=alpaca_account_id,
                symbol_or_asset_id=asset_id,
            )
        except APIError as e:
            if e.status_code == 404 and not error_if_no_position:
                return None
            raise AlpacaBrokerClientError(
                message=f"Failed to get Alpaca position for asset id '{asset_id}', alpaca account id '{alpaca_account_id}', and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_POSITION_BY_ASSET_ID_FAILED",
            ) from e

        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get Alpaca position for asset id '{asset_id}', alpaca account id '{alpaca_account_id}', and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_GET_POSITION_BY_ASSET_ID_FAILED",
            ) from e

        side = getattr(position.side, "name", str(position.side)).upper()
        return BasktPosition(
            symbol=position.symbol,
            filled_avg_price=float(position.avg_entry_price),
            filled_quantity=abs(float(position.qty)),
            direction=1 if side == "LONG" else -1,
        )

    #############################   
    #### ACCOUNT ANALYTICS ####
    #############################
        
    def get_portfolio_history(self, alpaca_account_id: str) -> Dict[str, PortfolioHistory]:
        """
        Fetch Alpaca portfolio history for the standard portfolio history
        periods, including all available history at daily resolution.

        Args:
            alpaca_account_id: Alpaca broker account ID whose portfolio history
                should be fetched.

        Returns:
            Dict[str, Dict[str, Any]]: Portfolio history data keyed by period. Each
            period contains equity, timestamp, profit_loss, profit_loss_pct,
            and base_value values returned by Alpaca.

        Raises:
            AlpacaBrokerClientError: If Alpaca rejects a portfolio-history
            request, the account is inaccessible, the network request fails,
            or any unexpected error occurs.
        """
        try:
            periods_and_timeframes = [
                ("1D", "1D", "5Min"),
                ("1W", "1W", "1H"),
                ("1M", "1M", "1D"),
                ("3M", "3M", "1D"),
                ("1A", "1A", "1D"),
                ("ALL", "all", "1D"),
            ]

            portfolio_history_dict = {}

            for period_key, alpaca_period, timeframe in periods_and_timeframes:

                portfolio_history = self.client.get_portfolio_history_for_account(
                    account_id=alpaca_account_id,
                    history_filter=GetPortfolioHistoryRequest(
                        period=alpaca_period,
                        timeframe=timeframe
                    )
                )

                portfolio_history_dict[period_key] = portfolio_history

            return portfolio_history_dict

        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get portfolio_history for alpaca account id '{alpaca_account_id}': {e}",
                code="ALPACA_BROKER_GET_PORTFOLIO_HISTORY_FAILED"
            ) from e

    ###########################
    ####### DATA CLIENT #######
    ###########################

    def get_stock_market_calendar(
        self,
        start_date: date,
        end_date: date,
    ) -> List[Calendar]:
        """Get US stock-market sessions for an inclusive date range.

        Args:
            start_date: Inclusive first calendar date to query.
            end_date: Inclusive last calendar date to query.

        Returns:
            List[Calendar]: Alpaca market sessions, including each session's
            opening and closing datetimes.

        Raises:
            AlpacaBrokerClientError: If the date range is invalid or Alpaca
            fails to return the market calendar.
        """
        try:
            if start_date > end_date:
                raise AlpacaBrokerClientError(
                    message=(
                        f"Calendar start date '{start_date.isoformat()}' must "
                        f"not be after end date '{end_date.isoformat()}'"
                    ),
                    code="ALPACA_BROKER_MARKET_CALENDAR_INVALID_RANGE",
                )

            sessions = self.client.get_calendar(
                GetCalendarRequest(start=start_date, end=end_date)
            )
            return list(sessions)
        except AlpacaBrokerClientError:
            raise
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=(
                    "Failed to get stock market calendar from "
                    f"'{start_date.isoformat()}' through "
                    f"'{end_date.isoformat()}': {e}"
                ),
                code="ALPACA_BROKER_GET_MARKET_CALENDAR_FAILED",
            ) from e

    def get_stock_prices_over_time(
        self,
        symbols: List[str],
        start_datetime: datetime,
        end_datetime: datetime,
        timeframe: str
    ) -> pd.DataFrame:
        """
        Fetch stock close prices over time as a wide pandas DataFrame.

        Args:
            symbols: Ticker symbols to fetch prices for.
            start_datetime: Inclusive timezone-aware start datetime. The value
                is converted to UTC before the price bars request.
            end_datetime: Exclusive timezone-aware end datetime. The value is
                converted to UTC before the price bars request.
            timeframe: Bar timeframe string. Supported values are 1Min, 5Min,
                1H, and 1D.

        Returns:
            pd.DataFrame: DataFrame indexed by UTC timestamps with one column
            per symbol. Cell values are bar close prices.

        Raises:
            AlpacaBrokerClientError: If either datetime is timezone-naive, the
            timeframe is unsupported, Alpaca rejects the bars request, the
            network request fails, or an unexpected error occurs.
        """
        try:
            if start_datetime.tzinfo is None or start_datetime.utcoffset() is None:
                raise AlpacaBrokerClientError(
                    message="start_datetime must be timezone-aware",
                    code="ALPACA_BROKER_STOCK_PRICES_START_TIMEZONE_REQUIRED",
                )
            if end_datetime.tzinfo is None or end_datetime.utcoffset() is None:
                raise AlpacaBrokerClientError(
                    message="end_datetime must be timezone-aware",
                    code="ALPACA_BROKER_STOCK_PRICES_END_TIMEZONE_REQUIRED",
                )

            start_datetime_utc = start_datetime.astimezone(timezone.utc)
            end_datetime_utc = end_datetime.astimezone(timezone.utc)

            normalized_timeframe = timeframe.lower()
            if normalized_timeframe in {"1min", "1m"}:
                alpaca_timeframe = TimeFrame(1, TimeFrameUnit.Minute)
            elif normalized_timeframe in {"5min", "5m"}:
                alpaca_timeframe = TimeFrame(5, TimeFrameUnit.Minute)
            elif normalized_timeframe in {"1h", "1hour", "hour"}:
                alpaca_timeframe = TimeFrame.Hour
            elif normalized_timeframe in {"1d", "1day", "day"}:
                alpaca_timeframe = TimeFrame.Day
            else:
                raise ValueError(f"Unsupported stock prices timeframe '{timeframe}'")

            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                start=start_datetime_utc,
                end=end_datetime_utc,
                timeframe=alpaca_timeframe,
                feed=DataFeed.IEX,
            )
            bars_response = self.data_client.get_stock_bars(request)
            bars_data = getattr(bars_response, "data", {})

            price_series_by_symbol: Dict[str, pd.Series] = {}
            for symbol in symbols:
                close_prices: Dict[datetime, float] = {}
                for bar in bars_data.get(symbol, []):
                    close_prices[bar.timestamp] = float(bar.close)

                price_series_by_symbol[symbol] = pd.Series(
                    close_prices,
                    dtype="float64",
                )

            prices_df = pd.DataFrame(price_series_by_symbol)
            prices_df = prices_df.sort_index()
            if not prices_df.empty:
                prices_df.index = pd.to_datetime(prices_df.index, utc=True)
            prices_df.index.name = "timestamp"

            return prices_df
        except AlpacaBrokerClientError:
            raise
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to fetch stock prices over time for symbols {symbols}: {e}",
                code="ALPACA_BROKER_GET_STOCK_PRICES_OVER_TIME_FAILED",
            ) from e

    def get_stock_prices_at_time(
        self,
        symbols: List[str],
        timestamp: datetime,
    ) -> Dict[str, float]:
        """
        Fetch stock prices at or immediately before a specific timestamp.

        Args:
            symbols: Ticker symbols to fetch prices for.
            timestamp: Timezone-aware target timestamp. The value is converted
                to UTC before the price lookup.

        Returns:
            Dict[str, float]: Mapping of symbol to the latest 1-minute bar close
            at or before timestamp.

        Raises:
            AlpacaBrokerClientError: If timestamp is timezone-naive, Alpaca
            rejects the bars request, no bar is found for a requested symbol,
            the network request fails, or an unexpected error occurs.
        """
        try:
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise AlpacaBrokerClientError(
                    message="timestamp must be timezone-aware",
                    code="ALPACA_BROKER_STOCK_PRICE_TIMEZONE_REQUIRED",
                )

            timestamp_utc = timestamp.astimezone(timezone.utc)
            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                start=timestamp_utc - timedelta(days=5),
                end=timestamp_utc,
                timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                feed=DataFeed.IEX,
                limit=10000,
            )
            bars_response = self.data_client.get_stock_bars(request)
            bars_data = getattr(bars_response, "data", {})
            bars_by_symbol = {
                symbol: [
                    {
                        "timestamp": bar.timestamp,
                        "close": float(bar.close),
                    }
                    for bar in bars_data.get(symbol, [])
                ]
                for symbol in symbols
            }

            prices: Dict[str, float] = {}
            for symbol in symbols:
                bars = [
                    bar
                    for bar in bars_by_symbol.get(symbol, [])
                    if bar["timestamp"] <= timestamp_utc
                ]
                if not bars:
                    raise AlpacaBrokerClientError(
                        message=f"No stock price bar found at or before '{timestamp_utc.isoformat()}' for symbol '{symbol}'",
                        code="ALPACA_BROKER_STOCK_PRICE_AT_TIME_MISSING",
                    )

                prices[symbol] = float(bars[-1]["close"])

            return prices
        
        except AlpacaBrokerClientError:
            raise
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to fetch stock prices at time '{timestamp}' for symbols {symbols}: {e}",
                code="ALPACA_BROKER_GET_STOCKS_PRICES_AT_TIME_FAILED",
            ) from e
        
    ##############################
    ######## STOCK SEARCH ########
    ##############################

    def get_stock_by_symbol(
        self,
        *,
        symbol: str
    ) -> Optional[Stock]:
        """Get an Alpaca asset by its exact stock symbol.

        Args:
            symbol: Exact stock ticker symbol to retrieve.

        Returns:
            Stock: Matching Alpaca asset, or None when the symbol
            does not exist.

        Raises:
            AlpacaBrokerClientError: If the symbol is empty or Alpaca fails
                for a reason other than the asset not existing.
        """
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise AlpacaBrokerClientError(
                message="Stock symbol cannot be empty",
                code="ALPACA_BROKER_STOCK_SYMBOL_REQUIRED",
            )

        try:
            asset =  self.client.get_asset(symbol_or_asset_id=normalized_symbol)
            return Stock(
                symbol=str(asset.symbol),
                tradable=bool(asset.tradable),
                fractionable=bool(asset.fractionable),
                shortable=bool(asset.shortable),
                marginable=bool(asset.marginable),
                stock_id=str(asset.id),
                stock_class=str(asset.asset_class.name.upper())
            )
        except APIError as error:
            if error.status_code == 404:
                return None
        except Exception as error:
            raise AlpacaBrokerClientError(
                message=f"Failed to get stock for symbol '{normalized_symbol}': {error}",
                code="ALPACA_BROKER_GET_STOCK_BY_SYMBOL_FAILED",
            ) from error
        

    def get_stock_by_asset_id(
        self,
        *,
        asset_id: str
    ) -> Stock:
        """Get an Alpaca asset by its exact stock asset_id.

        Args:
            asset_id: Exact stock asset_id symbol to retrieve.

        Returns:
            Stock: Matching Alpaca asset, or None when the symbol
            does not exist.

        Raises:
            AlpacaBrokerClientError: If the symbol is empty or Alpaca fails
                for a reason other than the asset not existing.
        """

        try:
            asset = self.client.get_asset(symbol_or_asset_id=asset_id)
            return Stock(
                symbol=str(asset.symbol),
                tradable=bool(asset.tradable),
                fractionable=bool(asset.fractionable),
                shortable=bool(asset.shortable),
                marginable=bool(asset.marginable),
                stock_id=str(asset.id),
                stock_class=str(asset.asset_class.name.upper())
            )
        except Exception as error:
            raise AlpacaBrokerClientError(
                message=f"Failed to get stock for asset id '{asset_id}': {error}",
                code="ALPACA_BROKER_GET_STOCK_BY_ASSET_ID_FAILED",
            ) from error

    def get_symbol_by_asset_id(
            self,
            *,
            asset_id: str
        ) -> str:
            """
            Get the ticker symbol for an Alpaca asset ID.

            Args:
                asset_id: Exact Alpaca asset ID to look up.

            Returns:
                str: Ticker symbol associated with the asset ID.

            Raises:
                AlpacaBrokerClientError: If Alpaca fails to load the asset or
                the asset response cannot be converted into a symbol.
            """
            try:
                asset = self.client.get_asset(symbol_or_asset_id=asset_id)
                return str(asset.symbol.upper())
            except Exception as error:
                raise AlpacaBrokerClientError(
                    message=f"Failed to get symbol for asset id '{asset_id}': {error}",
                    code="ALPACA_BROKER_GET_SYMBOL_BY_ASSET_ID_FAILED",
                ) from error
    

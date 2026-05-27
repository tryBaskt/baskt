# backend/clients/alpaca_broker_client.py

# Python imports
from __future__ import annotations
from typing import Any, List, Dict

# Alpaca imports
from alpaca.broker.client import BrokerClient
from alpaca.broker.requests import CreateAccountRequest
from alpaca.broker.enums import AccountType, AccountSubType
from alpaca.broker.models import Contact, Identity, Disclosures, Agreement, Account
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.models import Position, Asset
from alpaca.trading.models import Order

# Pandas imports
import pandas as pd

# Baskt imports
from domain.baskt import BasktPosition


class AlpacaBrokerClientError(Exception):
    """Raised when Alpaca Broker client operations fail."""

    def __init__(self, message: str, code: str = "ALPACA_BROKER_CLIENT_ERROR"):
        super().__init__(message)
        self.code = code

class AlpacaBrokerClient:
    """Client wrapper for Alpaca Broker account lifecycle operations."""

    def __init__(
        self,
        *,
        alpaca_broker_api_key: str,
        alpaca_broker_api_secret: str,
    ) -> None:
        """
        Initialize trading and market-data clients for Alpaca.

        Args:
            alpaca_broker_api_key: Alpaca API key.
            alpaca_broker_api_secret: Alpaca API secret.

        Returns:
            None.
        """
        self.client = BrokerClient(api_key=alpaca_broker_api_key, secret_key=alpaca_broker_api_secret)

    def get_tradeable_fractionable_US_assets(self) -> List[Asset]:
        """
        Fetch all Alpaca assets and filter to tradable, fractionable US equities.

        Args:
            None.

        Returns:
            List[Asset]: Assets where tradable=True, fractionable=True,
            and asset_class is US_EQUITY.
        """
        try:
            filter = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
            assets = self.client.get_all_assets(filter=filter)
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to fetch tradable, fractionable US Alpaca assets: {e}",
                code="ALPACA_BROKER_GET_ASSETS_FAILED",
            )

        tradeable = []
        for asset in assets:
            asset_class = getattr(asset.asset_class, "name", asset.asset_class)
            if asset.tradable and asset_class in {"US_EQUITY", "us_equity"} and asset.fractionable:
                tradeable.append(asset)

        return tradeable
    
    def create_alpaca_account(self, account_data: Dict[str, Any]) -> str:
        """
        Create a broker account from Alpaca account payload sections.

        Required top-level keys: contact, identity, disclosures, agreements.
        Optional top-level keys: account_type, account_sub_type, currency, enabled_assets, trusted_contact, documents.
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
                tax_id_type=identity_data.get("tax_id_type"),
                country_of_citizenship=identity_data.get("country_of_citizenship"),
                country_of_birth=identity_data.get("country_of_birth"),
                country_of_tax_residence=identity_data["country_of_tax_residence"],
                visa_type=identity_data.get("visa_type"),
                visa_expiration_date=identity_data.get("visa_expiration_date"),
                date_of_departure_from_usa=identity_data.get("date_of_departure_from_usa"),
                permanent_resident=identity_data.get("permanent_resident"),
                funding_source=identity_data.get("funding_source"),
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
                employment_status=disclosures_data.get("employment_status"),
                employer_name=disclosures_data.get("employer_name"),
                employer_address=disclosures_data.get("employer_address"),
                employment_position=disclosures_data.get("employment_position"),
            )

            agreements = [
                Agreement(
                    agreement=agreement["agreement"],
                    signed_at=agreement["signed_at"],
                    ip_address=agreement["ip_address"],
                    revision=agreement.get("revision"),
                )
                for agreement in agreements_data
            ]

            request = CreateAccountRequest(
                account_type=account_data.get("account_type", AccountType.TRADING),
                # account_sub_type=account_data.get("account_sub_type", AccountSubType.TRADITIONAL),
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
            alpaca_account_number = str(getattr(alpaca_account, "number", None))

            if not (alpaca_account_id and alpaca_account_id):
                raise AlpacaBrokerClientError(
                    message=f"Failed to create Alpaca account for user '{email_address}'",
                    code="ALPACA_BROKER_CREATE_ACCOUNT_FAILED"
                )
            
            return {
                "alpaca_account_id": alpaca_account_id,
                "alpaca_account_number": alpaca_account_number,
                "email_address": email_address
            }
        
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create Alpaca account: {e}",
                code="ALPACA_BROKER_CREATE_ACCOUNT_FAILED",
            )
        
    def get_alpaca_account_by_id(self, account_id) -> Account:
        alpaca_account = self.client.get_account_by_id(account_id=account_id)
        if not alpaca_account:
            return None
        
        return alpaca_account





    
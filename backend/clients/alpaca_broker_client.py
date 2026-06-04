# backend/clients/alpaca_broker_client.py

# Python imports
from __future__ import annotations
from typing import Any, List, Dict
from uuid import UUID

# Alpaca imports
from alpaca.broker.client import BrokerClient
from alpaca.broker.requests import CreateAccountRequest, CreateACHRelationshipRequest, CreateACHTransferRequest
from alpaca.broker.enums import AccountType, BankAccountType, TransferDirection, TransferTiming, FeePaymentMethod, AccountSubType
from alpaca.broker.models import (
    Contact, Identity, Disclosures, Agreement, Account, ACHRelationship, Transfer, TradeAccount, 
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
    ) -> ACHRelationship:
        """
        Create an ACH bank relationship for an Alpaca broker account.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the ACH
                relationship.
            account_owner_name: Legal name of the owner of the external bank
                account.
            bank_account_type: External bank account type. Accepts a
                BankAccountType enum value or a string such as "CHECKING" or
                "SAVINGS".
            bank_account_number: External bank account number.
            bank_routing_number: External bank routing number.
            nickname: Optional nickname for the ACH relationship.
            cognito_user_id: Optional Cognito user ID used for error context.

        Returns:
            ACHRelationship: Alpaca ACH relationship response
            returned by the broker API.

        Raises:
            AlpacaBrokerClientError: If required input is missing, the bank
            account type is invalid, Alpaca rejects the ACH relationship
            request, the network request fails, or any unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if not account_owner_name:
                raise ValueError("account_owner_name is required")
            if not bank_account_number:
                raise ValueError("bank_account_number is required")
            if not bank_routing_number:
                raise ValueError("bank_routing_number is required")

            if isinstance(bank_account_type, str):
                bank_account_type = BankAccountType(bank_account_type.upper())

            request = CreateACHRelationshipRequest(
                account_owner_name=account_owner_name,
                bank_account_type=bank_account_type,
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
            )

    def create_ach_transfer(
        self,
        *,
        alpaca_account_id: str,
        relationship_id: str | UUID,
        amount: str | float,
        direction: TransferDirection | str = TransferDirection.INCOMING,
        timing: TransferTiming | str = TransferTiming.IMMEDIATE,
        fee_payment_method: FeePaymentMethod | str | None = None,
        cognito_user_id: str | None = None,
    ) -> Transfer:
        """
        Create an ACH transfer request for an Alpaca broker account.

        Args:
            alpaca_account_id: Alpaca broker account ID that owns the ACH
                transfer.
            relationship_id: ACH relationship ID to use for the transfer.
            amount: Transfer amount. Alpaca expects a string amount; floats are
                converted to strings.
            direction: Transfer direction. Accepts a TransferDirection enum
                value or a string such as "INCOMING" or "OUTGOING".
            timing: Transfer timing. Accepts a TransferTiming enum value or a
                string such as "immediate".
            fee_payment_method: Optional fee payment method. Accepts a
                FeePaymentMethod enum value or a string such as "user" or
                "invoice".
            cognito_user_id: Optional Cognito user ID used for error context.

        Returns:
            Transfer: Alpaca transfer response returned by the
            broker API.

        Raises:
            AlpacaBrokerClientError: If required input is missing, enum or UUID
            values are invalid, Alpaca rejects the ACH transfer request, the
            network request fails, or any unexpected error occurs.
        """
        try:
            if not alpaca_account_id:
                raise ValueError("alpaca_account_id is required")
            if not relationship_id:
                raise ValueError("relationship_id is required")
            if amount is None or str(amount) == "":
                raise ValueError("amount is required")

            if isinstance(relationship_id, str):
                relationship_id = UUID(relationship_id)
            if isinstance(direction, str):
                direction = TransferDirection(direction.upper())
            if isinstance(timing, str):
                timing = TransferTiming(timing.lower())
            if isinstance(fee_payment_method, str):
                fee_payment_method = FeePaymentMethod(fee_payment_method.lower())

            request = CreateACHTransferRequest(
                amount=str(amount),
                direction=direction,
                timing=timing,
                fee_payment_method=fee_payment_method,
                relationship_id=relationship_id,
            )

            return self.client.create_transfer_for_account(
                account_id=alpaca_account_id,
                transfer_data=request,
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to create ACH transfer for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {e}",
                code="ALPACA_BROKER_CREATE_ACH_TRANSFER_FAILED",
            )
    

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
        
    def get_portfolio_history_for_account(self, alpaca_account_id: str) -> PortfolioHistory:
        try:
            return self.client.get_portfolio_history_for_account(
                account_id=alpaca_account_id,
                history_filter=GetPortfolioHistoryRequest(
                    period="1D",
                    timeframe="5Min"
                )
            )
        except Exception as e:
            raise AlpacaBrokerClientError(
                message=f"Failed to get portfolio history for alpaca account id '{alpaca_account_id}': {e}",
                code="ALPACA_BROKER_GET_PORTFOLIO_HISTORY_FAILED",
            ) from e







    

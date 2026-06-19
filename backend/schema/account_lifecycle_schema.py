from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AlpacaTradingConfigurations(BaseModel):
    max_margin_multiplier: Optional[str] = None
    no_shorting: Optional[bool] = None
    disable_overnight_trading: Optional[bool] = None
    fractional_trading: Optional[bool] = None


class CreateBasktAccountLifecycleRequest(BaseModel):
    contact: Dict[str, Any]
    identity: Dict[str, Any]
    disclosures: Dict[str, Any]
    agreements: List[Dict[str, str]]
    trading_configurations: Optional[AlpacaTradingConfigurations] = None
    account_type: Optional[str] = None
    password: Optional[str] = None


class CreateBasktACHRelationshipRequest(BaseModel):
    account_owner_name: str
    bank_account_type: str
    bank_account_number: str
    bank_routing_number: str
    nickname: Optional[str] = None


class CreateBasktPlaidRelationshipRequest(BaseModel):
    processor_token: str


class CreateBasktBankRequest(BaseModel):
    name: str
    bank_code_type: str
    bank_code: str
    account_number: str
    country: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    street_address: Optional[str] = None


class CreateBasktTransferRequest(BaseModel):
    amount: str
    direction: str
    funding_source_type: str
    relationship_id: Optional[str] = None
    bank_id: Optional[str] = None
    timing: str
    fee_payment_method: Optional[str] = None
    additional_information: Optional[str] = None


class BasktTradeAccountResponse(BaseModel):
    cash_withdrawable: Optional[str]
    cash_transferable: Optional[str]
    previous_close: Optional[str]
    last_long_market_value: Optional[str]
    last_short_market_value: Optional[str]
    last_cash: Optional[str]
    last_initial_margin: Optional[str]
    last_regt_buying_power: Optional[str]
    last_daytrading_buying_power: Optional[str]
    last_daytrade_count: Optional[str]
    last_buying_power: Optional[str]
    clearing_broker: Optional[str]


class BasktACHRelationshipResponse(BaseModel):
    relationship_id: str # UUID
    alpaca_account_id: str #UUID
    created_at: str #datetime
    updated_at: Optional[str] = None #datetime
    status: str #ACHRelationshipStatus
    account_owner_name: str
    bank_account_type: str #BankAccountType
    bank_account_number: str
    bank_routing_number: str
    nickname: Optional[str] = None
    processor_token: Optional[str] = None


class BasktListACHRelationshipResponse(BaseModel):
    list_ach_relationship: List[BasktACHRelationshipResponse]

class BasktBankResponse(BaseModel):
    bank_id: str # UUID
    alpaca_account_id: str # UUID
    created_at: str # datetime
    updated_at: Optional[str] = None # datetime
    name: str
    status: str #BankStatus
    country: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    street_address: Optional[str] = None
    alpaca_account_number: str
    bank_code: str
    bank_code_type: str #IdentifierType

class BasktListBankResponse(BaseModel):
    list_banks: List[BasktBankResponse]

class BasktOneTransferResponse(BaseModel):
    alpaca_account_id: str # UUID
    created_at: str # datetime
    updated_at: Optional[str] = None # Optional[datetime] = None
    expires_at: Optional[str] = None # Optional[datetime] = None
    relationship_id: Optional[str] = None # Optional[UUID] = None
    bank_id: Optional[str] = None # Optional[UUID] = None
    amount: str
    type: str #TransferType
    status: str #TransferStatus
    direction: str #TransferDirection
    reason: Optional[str] = None
    requested_amount: Optional[str] = None
    fee: Optional[str] = None
    fee_payment_method: Optional[str] = None # Optional[FeePaymentMethod] = None
    additional_information: Optional[str] = None

class BasktTransferResponse(BaseModel):
    items: List[BasktOneTransferResponse]
    limit: int
    offset: int
    has_next: bool
    has_previous: bool

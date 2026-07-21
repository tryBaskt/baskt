# backend/schema/account_lifecycle_schema/py


from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, RootModel


class AlpacaTradingConfigurations(BaseModel):
    max_margin_multiplier: Optional[str] = None
    no_shorting: Optional[bool] = None
    disable_overnight_trading: Optional[bool] = None
    fractional_trading: Optional[bool] = None


class CreateBasktAccountLifecycleRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)
    contact: Dict[str, Any]
    identity: Dict[str, Any]
    disclosures: Dict[str, Any]
    agreements: List[Dict[str, str]]
    trading_configurations: Optional[AlpacaTradingConfigurations] = None
    account_type: Optional[str] = None
    password: Optional[str] = None

class BasktDisplayName(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)

class BasktDescription(BaseModel):
    description: str = Field(max_length=500)

class GetIsExistsDisplayNameResponse(BaseModel):
    is_exists: bool

class BasktContactData(BaseModel):
    email_address: str
    phone_number: Optional[str] = None
    street_address: str | List[str]
    unit: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class BasktIdentityData(BaseModel):
    given_name: str
    family_name: str
    country_of_tax_residence: str
    middle_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    tax_id_type: Optional[str] = None
    country_of_citizenship: Optional[str] = None
    country_of_birth: Optional[str] = None
    visa_type: Optional[str] = None
    visa_expiration_date: Optional[str] = None
    date_of_departure_from_usa: Optional[str] = None
    permanent_resident: Optional[bool] = None
    funding_source: Optional[str | List[str]] = None
    annual_income_min: Optional[int | float | str] = None
    annual_income_max: Optional[int | float | str] = None
    liquid_net_worth_min: Optional[int | float | str] = None
    liquid_net_worth_max: Optional[int | float | str] = None
    total_net_worth_min: Optional[int | float | str] = None
    total_net_worth_max: Optional[int | float | str] = None


class BasktDisclosuresData(BaseModel):
    immediate_family_exposed: bool
    is_control_person: Optional[bool] = None
    is_affiliated_exchange_or_finra: Optional[bool] = None
    is_politically_exposed: Optional[bool] = None
    employment_status: Optional[str] = None
    employer_name: Optional[str] = None
    employer_address: Optional[str] = None
    employment_position: Optional[str] = None


class BasktAgreementData(BaseModel):
    agreement: str
    signed_at: str
    ip_address: str
    revision: Optional[str] = None


class BasktAccountDetailsResponse(BaseModel):
    display_name: str
    description: Optional[str] = None
    contact: BasktContactData
    identity: BasktIdentityData
    disclosures: BasktDisclosuresData
    agreements: List[BasktAgreementData]


class UpdateBasktContactRequest(BasktContactData):
    pass


class UpdateBasktIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    given_name: Optional[str] = None
    family_name: Optional[str] = None
    country_of_tax_residence: Optional[str] = None
    middle_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    country_of_citizenship: Optional[str] = None
    country_of_birth: Optional[str] = None
    visa_type: Optional[str] = None
    visa_expiration_date: Optional[str] = None
    date_of_departure_from_usa: Optional[str] = None
    permanent_resident: Optional[bool] = None
    funding_source: Optional[str | List[str]] = None
    annual_income_min: Optional[int | float | str] = None
    annual_income_max: Optional[int | float | str] = None
    liquid_net_worth_min: Optional[int | float | str] = None
    liquid_net_worth_max: Optional[int | float | str] = None
    total_net_worth_min: Optional[int | float | str] = None
    total_net_worth_max: Optional[int | float | str] = None


class UpdateBasktDisclosuresRequest(BasktDisclosuresData):
    pass


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
    equity: Optional[str]
    cash_withdrawable: Optional[str]
    cash_transferable: Optional[str]
    previous_close: Optional[str]
    multiplier: Optional[str]
    shorting_enabled: Optional[bool]
    trading_blocked: Optional[bool]
    account_blocked: Optional[bool]
    status: Optional[str]
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


class BasktACHRelationshipsResponse(RootModel[List[BasktACHRelationshipResponse]]):
    pass


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


class BasktBanksResponse(RootModel[List[BasktBankResponse]]):
    pass


class BasktTransferResponse(BaseModel):
    transfer_id: str # UUID
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


class BasktTransfersResponse(BaseModel):
    items: List[BasktTransferResponse]
    limit: int
    offset: int
    has_next: bool
    has_previous: bool

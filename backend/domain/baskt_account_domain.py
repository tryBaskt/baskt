# backend/domain/baskt_account_domain.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ContactData:
    email_address: str
    phone_number: Optional[str]
    street_address: str
    unit: Optional[str]
    city: str
    state: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]


@dataclass
class IdentityData:
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


@dataclass
class DisclosuresData:
    immediate_family_exposed: bool
    is_control_person: Optional[bool] = None
    is_affiliated_exchange_or_finra: Optional[bool] = None
    is_politically_exposed: Optional[bool] = None
    employment_status: Optional[str] = None
    employer_name: Optional[str] = None
    employer_address: Optional[str] = None
    employment_position: Optional[str] = None


@dataclass
class AgreementData:
    agreement: str
    signed_at: str
    ip_address: str
    revision: Optional[str] = None



@dataclass
class BasktAccount:
    """
    Baskt Account
    """
    cognito_user_id: str
    display_name: str
    alpaca_account_id: str
    alpaca_account_number: str
    agreements_data: List[AgreementData]
    disclosures_data: DisclosuresData
    identity_data: IdentityData
    contact_data: ContactData


@dataclass
class UpdateBasktAccount:
    cognito_user_id: str
    alpaca_account_id: str
    updated_data: DisclosuresData | IdentityData | ContactData
    

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CreateBasktAccountLifecycleRequest(BaseModel):
    contact: Dict[str, str]
    identity: Dict[str, str]
    disclosures: Dict[str, str]
    agreements: List[Dict[str, str]]

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
    fee_payment_method: Optional[str]

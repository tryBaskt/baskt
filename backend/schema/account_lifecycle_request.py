from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CreateBasktAccountLifecycleRequest(BaseModel):
    contact: Dict[str, Any]
    identity: Dict[str, Any]
    disclosures: Dict[str, Any]
    agreements: List[Dict[str, Any]]

    account_type: Optional[str] = None
    account_sub_type: Optional[str] = None
    currency: Optional[str] = None
    enabled_assets: Optional[List[str]] = None
    trusted_contact: Optional[Dict[str, Any]] = None
    documents: Optional[List[Dict[str, Any]]] = None

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
    timing: str = "IMMEDIATE"
    fee_payment_method: Optional[str] = "USER"

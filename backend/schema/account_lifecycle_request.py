from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CreateAccountLifecycleRequest(BaseModel):
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


class CreateAccountLifecycleResponse(BaseModel):
    alpaca_account_id: str
    cognito_username: str

# backend/schema/baskt_account_schema.py


from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, RootModel

from schema.model_portfolio_schema import ModelPortfoliosMetadataResponse


class BasktAccountMetadataResponse(BaseModel):
    cognito_user_id: str
    display_name: str
    description: Optional[str] = None


class BasktAccountProfileResponse(BaseModel):
    baskt_account: BasktAccountMetadataResponse
    model_portfolios: ModelPortfoliosMetadataResponse

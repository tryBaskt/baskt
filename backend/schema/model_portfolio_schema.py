# backend/schema/model_portfolio_schema.py

# Python imports
from __future__ import annotations
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, RootModel
from datetime import datetime


class ModelPortfolioPositionRequest(BaseModel):
    symbol: str = Field(min_length=1)
    target_weight: float = Field(ge=0, le=1)
    direction: Literal[1, -1]
    leverage: Literal[1]


class CreateModelPortfolioRequest(BaseModel):
    name: str = Field(min_length=1)
    positions: List[ModelPortfolioPositionRequest]
    description: Optional[str] = None
    visibility: Literal["PUBLIC", "PRIVATE"]


class UpdateModelPortfolioRequest(BaseModel):
    positions: List[ModelPortfolioPositionRequest]
    description: Optional[str] = None
    visibility: Literal["PUBLIC", "PRIVATE"]


class AddAccessModelPortfolioRequest(BaseModel):
    email_address: str = Field(min_length=1)

class RemoveAccessModelPortfolioRequest(BaseModel):
    cognito_user_id: str = Field(min_length=1)

class RemoveAccessModelPortfolioResponse(BaseModel):
    removed: bool
    pending_removal: bool
    message: Optional[str] = None

class SharedWithUserModelPortfolioResponse(BaseModel):
    cognito_user_id: str = Field(min_length=1)
    email_address: str = Field(min_length=1)

class SharedWithUsersModelPortfolioResponse(RootModel[List[SharedWithUserModelPortfolioResponse]]):
    pass

class ModelPortfolioPositionResponse(BaseModel):
    symbol: str
    target_weight: float
    direction: int
    leverage: float


class ModelPortfolioSnapshotResponse(BaseModel):
    snapshot_id: str
    positions: List[ModelPortfolioPositionResponse]
    timestamp: str


class ModelPortfolioResponse(BaseModel):
    portfolio_id: str
    portfolio_owner_cognito_user_id: str
    portfolio_owner_display_name: Optional[str] = None
    portfolio_name: str
    description: Optional[str] = None
    visibility: str
    position_history: List[ModelPortfolioSnapshotResponse]
    created_at: str
    updated_at: str
    positions_current_weight: Dict[str, float]
    positions_current_percent_price_change: Dict[str, float]
    has_access: bool = True


class ModelPortfolioAnalyticsPeriodResponse(BaseModel):
    timeframe: str
    timestamp: List[datetime]
    cumulative_returns: List[float]
    final_cumulative_return: float
    cagr: Optional[float] = None
    annualized_volatility: Optional[float] = None
    leverage_adjusted_direction: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    maximum_drawdown: Optional[float] = None
    maximum_drawdown_duration: Optional[float] = None


class ModelPortfolioAnalyticsResponse(RootModel[Dict[str, ModelPortfolioAnalyticsPeriodResponse]]):
    pass


class ModelPortfolioMetadataResponse(BaseModel):
    portfolio_id: str
    portfolio_owner_cognito_user_id: str
    portfolio_owner_display_name: Optional[str] = None
    portfolio_name: str
    created_at: str
    updated_at: str
    description: Optional[str] = None
    visibility: Optional[str] = None


class ModelPortfoliosMetadataResponse(RootModel[List[ModelPortfolioMetadataResponse]]):
    pass

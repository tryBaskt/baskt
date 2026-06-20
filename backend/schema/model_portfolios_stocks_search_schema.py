"""Request and response schemas for model portfolio and stock search routes."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ModelPortfolioSearchResultResponse(BaseModel):
    """Metadata for one model portfolio returned by search."""

    portfolio_id: str
    portfolio_name: str
    description: Optional[str] = None
    portfolio_owner_cognito_user_id: str
    created_at: str
    updated_at: str
    visibility: Optional[str] = None
    score: Optional[float] = None


class ModelPortfoliosSearchResponse(BaseModel):
    """Paginated collection of model portfolio search results."""

    model_portfolios: List[ModelPortfolioSearchResultResponse]
    total: int
    limit: int
    offset: int

"""Request and response schemas for model portfolio and stock search routes."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, RootModel


class ModelPortfolioOpenSearchResultResponse(BaseModel):
    """Metadata for one model portfolio returned by search."""
    portfolio_id: str
    portfolio_name: str
    description: Optional[str] = None
    portfolio_owner_cognito_user_id: str
    portfolio_owner_display_name: Optional[str] = None
    created_at: str
    updated_at: str
    visibility: Optional[str] = None
    score: Optional[float] = None


class ModelPortfoliosOpenSearchResultResponse(BaseModel):
    """Paginated collection of model portfolio search results."""
    model_portfolios: List[ModelPortfolioOpenSearchResultResponse]
    total: int
    limit: int
    offset: int


class StockSearchResultResponse(BaseModel):
    """Stock metadata returned by an exact symbol search."""
    symbol: str
    tradable: bool
    fractionable: bool
    shortable: bool
    marginable: bool
    stock_id: str
    stock_class: str


class StocksSearchResultResponse(RootModel[List[StockSearchResultResponse]]):
    pass


class BasktAccountOpenSearchResultResponse(BaseModel):
    cognito_user_id: str
    display_name: str
    description: Optional[str] = None
    profile_image: Optional[str] = None
    visibility: Optional[str] = None
    score: Optional[float] = None

class BasktAccountsOpenSearchResultResponse(BaseModel):
    baskt_accounts: List[BasktAccountOpenSearchResultResponse]
    total: int
    limit: int
    offset: int




class ExploreSearchOpenSearchResponse(BaseModel):
    """Combined model portfolio and stock search response."""
    model_portfolios: ModelPortfoliosOpenSearchResultResponse
    stocks: StocksSearchResultResponse
    baskt_accounts: BasktAccountsOpenSearchResultResponse

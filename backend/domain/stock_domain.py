# backend/domain/stock_domain

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

@dataclass(frozen=True)
class Stock:
    symbol: str
    tradable: bool
    fractionable: bool
    shortable: bool
    marginable: bool
    stock_id: str
    stock_class: str


@dataclass(frozen=True)
class StockSearchResult:
    """Searchable stock metadata returned to callers."""
    stock_id: str
    symbol: str
    tradable: bool
    marginable: bool
    shortable: bool
    fractionable: bool
    stock_class: str


StocksSearchResult = List[StockSearchResult]
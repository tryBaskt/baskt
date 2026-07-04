# backend/domain/baskt_position

# Python imports
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class BasktPosition:
    """
    A filled position 
    """
    symbol: str
    filled_quantity: float 
    filled_avg_price: float 
    direction: int


@dataclass(frozen=True)
class DeltaPosition:
    symbol: str
    quantity: float
    direction: int  # +1 long, -1 short
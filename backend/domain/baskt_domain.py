# backend/domain/baskt_position

# Python imports
from __future__ import annotations
from dataclasses import dataclass

# Alpaca imports
from alpaca.trading.enums import AccountStatus

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


@dataclass(frozen=True)
class BasktAccount:
    """
    Baskt Account
    """
    cognito_user_id: str
    alpaca_account_id: str
    alpaca_account_number: str
    email_address: str
    cognito_confirmation_status: str 
    cognito_enabled_status: bool 
    alpaca_account_status: AccountStatus

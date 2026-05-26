# backend/domain/baskt_position
from __future__ import annotations
from dataclasses import dataclass
from alpaca.trading.enums import AccountStatus



@dataclass(frozen=True)
class BasktPosition:
    """
    A filled position through Alpaca
    """
    symbol: str
    filled_quantity: float 
    filled_avg_price: float 
    direction: int

@dataclass
class BasktAccount:
    """
    Baskt Account
    """
    cognito_user_id: str
    alpaca_account_id: str
    alpaca_account_number: str
    email_address: str
    cognito_confirmation_status: str | None = None
    cognito_status: bool | None = None
    alpaca_account_status: AccountStatus | None = None

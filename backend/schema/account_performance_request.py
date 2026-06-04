from pydantic import BaseModel

class EquityGraphRequest(BaseModel):
    alpaca_account_id: str
    cognito_username: str
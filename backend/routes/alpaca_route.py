# backend/api/routes/alpaca_route.py

# Python imports
from __future__ import annotations
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, ConfigDict

# Alpaca imports
from alpaca.trading.models import Asset

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR, HTTP_502_BAD_GATEWAY

# Baskt imports
from core.deps import get_alpaca_client, get_current_user
from clients.alpaca_client import AlpacaClient, AlpacaClientError
from backend.domain.baskt import BasktPosition

router = APIRouter(tags=["alpaca"])

class BasktAsset(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str
    shortable: Optional[bool] = None
    tradable: Optional[bool] = None
    fractionable: Optional[bool] = None
    asset_class: Optional[str] = None

def to_baskt_asset(asset: Asset) -> BasktAsset:
    """
    Convert an Alpaca Asset object into the API response model.

    Args:
        asset: Raw Alpaca Asset model returned by the trading client.

    Returns:
        BasktAsset: Serialized response object with normalized asset class.
    """
    raw_asset_class = getattr(asset, "asset_class", None)
    asset_class = getattr(raw_asset_class, "name", raw_asset_class)

    return BasktAsset(
        symbol=asset.symbol,
        shortable=getattr(asset, "shortable", None),
        tradable=getattr(asset, "tradable", None),
        fractionable=getattr(asset, "fractionable", None),
        asset_class=asset_class
    )

@router.get("/get_tradeable_fractionable_US_baskt_assets")
def get_tradeable_fractionable_US_baskt_assets(
    alpaca_client: AlpacaClient = Depends(get_alpaca_client), 
    user=Depends(get_current_user)
    ) -> Dict[str,List[BasktAsset]]:
    """
    Retrieve all tradeable, fractionable US equity assets from Alpaca.

    Args:
        alpaca_client: Injected Alpaca client dependency used to fetch assets.
        user: Authenticated user claims from Cognito token verification.

    Returns:
        Dict: JSON payload with key `baskt_assets`, containing a sorted list
        of serialized BasktAsset objects.
    """
    try:
        assets = alpaca_client.get_tradeable_fractionable_US_assets()
        baskt_assets = [to_baskt_asset(asset) for asset in assets]
        return {"baskt_assets": sorted(baskt_assets, key=lambda baskt_asset: baskt_asset.symbol)}
    except AlpacaClientError as e:
        raise HTTPException(status_code=HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected Alpaca Error: {str(e)}")
    


@router.get("/baskt-positions")
def get_baskt_positions(
    alpaca_client: AlpacaClient = Depends(get_alpaca_client),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = user["sub"]
    try:
        baskt_positions_dict: Dict[str, BasktPosition] = alpaca_client.get_baskt_positions_dict()

        if not baskt_positions_dict:
            return {"positions": []}
        
        return {
            "positions": [
                {"symbol": p.symbol, "quantity": p.filled_quantity, "direction": p.direction}
                for p in baskt_positions_dict.values()
            ]
        }
    except AlpacaClientError as e:
        raise HTTPException(status_code=HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected Alpaca Error: {str(e)}")
# backend/routes/alpaca_route.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from starlette import status

from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from core.deps import get_alpaca_broker_client, get_current_user


router = APIRouter(prefix="/alpaca-broker", tags=["alpaca-broker"])


def _raise_alpaca_broker_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    if isinstance(err, AlpacaBrokerClientError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(err)) from err

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected Alpaca broker error: {err}",
    ) from err


class BasktAsset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    shortable: Optional[bool] = None
    tradable: Optional[bool] = None
    fractionable: Optional[bool] = None
    asset_class: Optional[str] = None


def _to_baskt_asset(asset: Any) -> BasktAsset:
    raw_asset_class = getattr(asset, "asset_class", None)
    asset_class = getattr(raw_asset_class, "name", raw_asset_class)

    return BasktAsset(
        symbol=asset.symbol,
        shortable=getattr(asset, "shortable", None),
        tradable=getattr(asset, "tradable", None),
        fractionable=getattr(asset, "fractionable", None),
        asset_class=asset_class,
    )


@router.get("/assets/tradeable-fractionable-us", response_model=Dict[str, List[BasktAsset]])
def get_tradeable_fractionable_us_baskt_assets(
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, List[BasktAsset]]:
    _ = user["sub"]
    try:
        assets = alpaca_broker_client.get_tradeable_fractionable_US_assets()
        baskt_assets = [_to_baskt_asset(asset) for asset in assets]
        return {
            "baskt_assets": sorted(
                baskt_assets,
                key=lambda baskt_asset: baskt_asset.symbol,
            )
        }
    except Exception as err:
        _raise_alpaca_broker_http_exception(err)

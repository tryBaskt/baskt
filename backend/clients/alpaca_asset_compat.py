"""Accept TXSE assets until the released Alpaca SDK includes that exchange."""

from typing import Literal
from uuid import UUID

from alpaca.broker.client import BrokerClient
from alpaca.common.utils import validate_symbol_or_asset_id
from alpaca.trading.enums import AssetExchange
from alpaca.trading.models import Asset
from alpaca.trading.requests import GetAssetsRequest
from pydantic import TypeAdapter


class BrokerAsset(Asset):
    """Preserve SDK validation while accepting Alpaca's TXSE exchange value."""

    exchange: AssetExchange | Literal["TXSE"]


class AssetCompatibleBrokerClient(BrokerClient):
    """Use the extended asset model for both list and individual lookups."""

    def get_all_assets(self, filter: GetAssetsRequest | None = None):
        params = filter.to_request_fields() if filter is not None else {}
        response = self.get("/assets", params)
        if self._use_raw_data:
            return response
        return TypeAdapter(list[BrokerAsset]).validate_python(response)

    def get_asset(self, symbol_or_asset_id: UUID | str):
        identifier = validate_symbol_or_asset_id(symbol_or_asset_id)
        response = self.get(f"/assets/{identifier}")
        if self._use_raw_data:
            return response
        return BrokerAsset.model_validate(response)

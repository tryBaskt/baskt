"""Exercise real asset validation using mocked HTTP responses."""

from unittest.mock import Mock

import pytest
from alpaca.trading.enums import AssetClass, AssetExchange, AssetStatus
from alpaca.trading.requests import GetAssetsRequest
from pydantic import ValidationError

from backend.clients.alpaca_asset_compat import AssetCompatibleBrokerClient


def asset_payload(exchange="TXSE"):
    return {
        "id": "ef62a404-6f8d-4f33-a064-bcc8a41eec99",
        "class": "us_equity",
        "exchange": exchange,
        "symbol": "TEST",
        "status": "active",
        "tradable": True,
        "marginable": True,
        "shortable": False,
        "easy_to_borrow": False,
        "fractionable": True,
    }


def client_with_response(response, *, raw_data=False):
    client = AssetCompatibleBrokerClient("test-key", "test-secret", raw_data=raw_data)
    client.get = Mock(return_value=response)
    return client


def test_asset_list_accepts_txse_and_preserves_existing_exchanges_and_filters():
    client = client_with_response([asset_payload("NASDAQ"), asset_payload()])
    filters = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
    assets = client.get_all_assets(filter=filters)
    assert len(assets) == 2
    assert assets[0].exchange == AssetExchange.NASDAQ
    assert assets[1].exchange == "TXSE"
    assert assets[1].fractionable is True
    client.get.assert_called_once_with("/assets", filters.to_request_fields())


def test_single_txse_asset_lookup():
    client = client_with_response(asset_payload())
    assert client.get_asset("TEST").exchange == "TXSE"
    client.get.assert_called_once_with("/assets/TEST")


@pytest.mark.parametrize("change", [{"exchange": "INVALID"}, {"id": "invalid-uuid"}])
def test_invalid_asset_data_still_fails_validation(change):
    client = client_with_response([asset_payload() | change])
    with pytest.raises(ValidationError):
        client.get_all_assets()


def test_raw_data_mode_is_preserved():
    payload = [asset_payload()]
    client = client_with_response(payload, raw_data=True)
    assert client.get_all_assets() is payload

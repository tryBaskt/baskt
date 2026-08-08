from __future__ import annotations

from routes.backtest_route import router as backtest_router


def test_tradeable_fractionable_assets_route_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(backtest_router)

    with client_for_app(app) as client:
        response = client.get("/backtest/tradeable-fractionable-us-baskt-assets")

    assert response.status_code == 200, response.text
    assets = response.json()
    assert isinstance(assets, list)
    assert assets
    assert {"symbol", "stock_id", "tradable", "fractionable"} <= set(assets[0])

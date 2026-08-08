from __future__ import annotations

from core import deps as app_deps
from routes.stock_route import router as stock_router


def test_stock_route_get_stock_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(stock_router)
    stock = app_deps.get_alpaca_broker_client().get_stock_by_symbol(symbol="AAPL")

    with client_for_app(app) as client:
        response = client.get(f"/stocks/{stock.stock_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["stock_id"] == stock.stock_id
    assert body["tradable"] is True
    assert body["fractionable"] is True
    assert "shortable" in body
    assert "marginable" in body
    assert body["stock_class"]


def test_stock_route_analytics_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(stock_router)

    with client_for_app(app) as client:
        response = client.get("/stock-analytics/AAPL")

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    assert body

from __future__ import annotations

from routes.explore_search_route import router as explore_search_router


def test_explore_search_route_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(explore_search_router)

    with client_for_app(app) as client:
        response = client.get("/search", params={"query": "AAPL"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"model_portfolios", "stocks", "baskt_accounts"}

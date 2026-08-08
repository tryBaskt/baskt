from __future__ import annotations

from routes.allocation_analytics_route import router as allocation_analytics_router


def test_allocation_analytics_route_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(allocation_analytics_router)

    with client_for_app(app) as client:
        response = client.get("/allocation_analytics")

    assert response.status_code == 200, response.text
    body = response.json()
    assert {"cash", "equity", "equity_graph", "allocations"} <= set(body)

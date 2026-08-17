from __future__ import annotations

from conftest import OTHER_USER_ID
from routes.account_lifecycle_route import router as account_lifecycle_router


def test_account_details_route_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(account_lifecycle_router)

    with client_for_app(app) as client:
        response = client.get("/accounts/account-details")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contact"]
    assert body["identity"]
    assert body["disclosures"]


def test_display_name_exists_route_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(account_lifecycle_router)

    with client_for_app(app) as client:
        response = client.get(
            "/accounts/is-exists-display-name",
            params={"display_name": f"display-{OTHER_USER_ID}"},
        )

    assert response.status_code == 200, response.text
    assert "is_exists" in response.json()

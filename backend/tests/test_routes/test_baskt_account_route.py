from __future__ import annotations

from conftest import OWNER_USER_ID
from routes.baskt_account_route import router as baskt_account_router


def test_get_baskt_account_profile_uses_real_dependencies(
    app_factory,
    client_for_app,
) -> None:
    app = app_factory(baskt_account_router)

    with client_for_app(app) as client:
        response = client.get(f"/baskt-accounts/{OWNER_USER_ID}/profile")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["baskt_account"]["cognito_user_id"] == OWNER_USER_ID
    assert "model_portfolios" in body

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parents[2]
repo_root = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from core.authentication import (
    get_current_alpaca_account,
    get_current_baskt_account,
    get_current_user,
)
from domain.baskt_account_domain import (
    AgreementData,
    BasktAccount,
    ContactData,
    DisclosuresData,
    IdentityData,
)


OWNER_USER_ID = "owner-user"
OTHER_USER_ID = "other-user"
OWNER_ALPACA_ACCOUNT_ID = "owner-alpaca-account"
OTHER_ALPACA_ACCOUNT_ID = "other-alpaca-account"


class FakeAccountStatus:
    def __init__(self, name: str = "ACTIVE") -> None:
        self.name = name


class FakeAlpacaAccount:
    def __init__(
        self,
        *,
        alpaca_account_id: str = OTHER_ALPACA_ACCOUNT_ID,
        status: str = "ACTIVE",
    ) -> None:
        self.id = alpaca_account_id
        self.status = FakeAccountStatus(status)


def fake_baskt_account(
    *,
    cognito_user_id: str = OTHER_USER_ID,
    alpaca_account_id: str = OTHER_ALPACA_ACCOUNT_ID,
) -> BasktAccount:
    return BasktAccount(
        cognito_user_id=cognito_user_id,
        display_name=f"display-{cognito_user_id}",
        alpaca_account_id=alpaca_account_id,
        alpaca_account_number=f"number-{alpaca_account_id}",
        agreements_data=[
            AgreementData(
                agreement="customer_agreement",
                signed_at=datetime.now(timezone.utc).isoformat(),
                ip_address="127.0.0.1",
            )
        ],
        disclosures_data=DisclosuresData(immediate_family_exposed=False),
        identity_data=IdentityData(
            given_name="Route",
            family_name="Tester",
            country_of_tax_residence="USA",
        ),
        contact_data=ContactData(
            email_address=f"{cognito_user_id}@example.com",
            phone_number=None,
            street_address="123 Test St",
            unit=None,
            city="San Francisco",
            state="CA",
            postal_code="94105",
            country="USA",
        ),
    )


@pytest.fixture
def app_factory():
    def build_app(*routers):
        app = FastAPI()
        for router in routers:
            app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: {
            "sub": OTHER_USER_ID,
            "custom:alpaca_acct_id": OTHER_ALPACA_ACCOUNT_ID,
        }
        app.dependency_overrides[get_current_baskt_account] = lambda: fake_baskt_account()
        app.dependency_overrides[get_current_alpaca_account] = lambda: FakeAlpacaAccount()
        return app

    return build_app


@pytest.fixture
def client_for_app():
    def build_client(app: FastAPI) -> TestClient:
        return TestClient(app)

    return build_client

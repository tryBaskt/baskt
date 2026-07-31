from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import OTHER_ALPACA_ACCOUNT_ID, OTHER_USER_ID, fake_baskt_account
from core.deps import get_account_lifecycle_service
from routes.account_lifecycle_route import router as account_lifecycle_router
from services.account_lifecycle_service import (
    AccountLifecycleDisplayNameTakenError,
    AccountLifecycleInternalServerError,
)


class FakeLifecycleService:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.account = fake_baskt_account()

    def _record(self, action: str, **kwargs: Any) -> None:
        self.calls.append((action, kwargs))
        if self.fail:
            raise self.fail

    def is_exists_display_name(self, display_name: str) -> bool:
        self._record("is_exists_display_name", display_name=display_name)
        return display_name == "taken"

    def create_baskt_account(self, **kwargs: Any) -> None:
        self._record("create_baskt_account", **kwargs)

    def get_baskt_account(self, cognito_user_id: str):
        self._record("get_baskt_account", cognito_user_id=cognito_user_id)
        return self.account

    def update_display_name(self, **kwargs: Any) -> None:
        self._record("update_display_name", **kwargs)
        self.account.display_name = kwargs["display_name"]

    def update_description(self, **kwargs: Any) -> None:
        self._record("update_description", **kwargs)
        self.account.description = kwargs["description"]

    def update_baskt_account(self, **kwargs: Any) -> None:
        self._record("update_baskt_account", **kwargs)
        updated_data = kwargs["updated_data"]
        if hasattr(updated_data, "email_address"):
            self.account.contact_data = updated_data
        elif hasattr(updated_data, "country_of_tax_residence"):
            self.account.identity_data = updated_data
        else:
            self.account.disclosures_data = updated_data

    def get_trade_account(self, **kwargs: Any):
        self._record("get_trade_account", **kwargs)
        return SimpleNamespace(
            equity="1000.00",
            cash_withdrawable="250.00",
            cash_transferable="250.00",
            previous_close="990.00",
            multiplier="1",
            shorting_enabled=False,
            trading_blocked=False,
            account_blocked=False,
            status=SimpleNamespace(name="ACTIVE"),
            last_long_market_value="900.00",
            last_short_market_value="0.00",
            last_cash="100.00",
            last_initial_margin="0.00",
            last_regt_buying_power="250.00",
            last_daytrading_buying_power="250.00",
            last_daytrade_count="0",
            last_buying_power="250.00",
            clearing_broker=SimpleNamespace(name="VELOX"),
        )

    def create_direct_ach_relationship(self, **kwargs: Any) -> None:
        self._record("create_direct_ach_relationship", **kwargs)

    def create_plaid_ach_relationship(self, **kwargs: Any) -> None:
        self._record("create_plaid_ach_relationship", **kwargs)

    def delete_ach_relationship(self, **kwargs: Any) -> None:
        self._record("delete_ach_relationship", **kwargs)

    def get_ach_relationships(self, **kwargs: Any):
        self._record("get_ach_relationships", **kwargs)
        now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            SimpleNamespace(
                id="ach-1",
                created_at=now,
                updated_at=None,
                status=SimpleNamespace(name="APPROVED"),
                account_owner_name="Route Tester",
                bank_account_type=SimpleNamespace(name="CHECKING"),
                bank_account_number="1234",
                bank_routing_number="121000358",
                nickname="Primary",
                processor_token=None,
            )
        ]

    def create_bank(self, **kwargs: Any) -> None:
        self._record("create_bank", **kwargs)

    def delete_bank(self, **kwargs: Any) -> None:
        self._record("delete_bank", **kwargs)

    def get_banks(self, **kwargs: Any):
        self._record("get_banks", **kwargs)
        now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            SimpleNamespace(
                id="bank-1",
                created_at=now,
                updated_at=None,
                name="Primary Bank",
                status=SimpleNamespace(name="ACTIVE"),
                country="USA",
                state_province="CA",
                postal_code="94105",
                city="San Francisco",
                street_address="123 Test St",
                account_number="000123",
                bank_code="121000358",
                bank_code_type=SimpleNamespace(name="ABA"),
            )
        ]

    def get_transfers(self, **kwargs: Any):
        self._record("get_transfers", **kwargs)
        now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [
            SimpleNamespace(
                id="transfer-1",
                created_at=now,
                updated_at=None,
                expires_at=now + timedelta(days=1),
                relationship_id="ach-1",
                bank_id=None,
                amount="25.00",
                type=SimpleNamespace(name="ACH"),
                status=SimpleNamespace(name="QUEUED"),
                direction=SimpleNamespace(name="INCOMING"),
                reason=None,
                requested_amount="25.00",
                fee=None,
                fee_payment_method=None,
                additional_information=None,
            )
        ]

    def create_ach_transfer(self, **kwargs: Any) -> None:
        self._record("create_ach_transfer", **kwargs)

    def create_bank_transfer(self, **kwargs: Any) -> None:
        self._record("create_bank_transfer", **kwargs)

    def cancel_transfer(self, **kwargs: Any) -> None:
        self._record("cancel_transfer", **kwargs)


@pytest.fixture
def account_lifecycle_app(app_factory):
    app = app_factory(account_lifecycle_router)
    service = FakeLifecycleService()
    app.dependency_overrides[get_account_lifecycle_service] = lambda: service
    return {"app": app, "service": service}


@pytest.fixture
def account_lifecycle_client(account_lifecycle_app, client_for_app):
    with client_for_app(account_lifecycle_app["app"]) as client:
        yield client


def test_display_name_lookup_trims_input(
    account_lifecycle_client,
    account_lifecycle_app,
) -> None:
    response = account_lifecycle_client.get(
        "/accounts/is-exists-display-name",
        params={"display_name": "  taken  "},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"is_exists": True}
    assert account_lifecycle_app["service"].calls == [
        ("is_exists_display_name", {"display_name": "taken"})
    ]


def test_create_baskt_account_removes_password_from_account_payload(
    account_lifecycle_client,
    account_lifecycle_app,
) -> None:
    response = account_lifecycle_client.post(
        "/accounts/create-baskt-account",
        json={
            "display_name": "Route Tester",
            "contact": {"email_address": "route@example.com"},
            "identity": {"given_name": "Route"},
            "disclosures": {"immediate_family_exposed": False},
            "agreements": [{"agreement": "customer", "signed_at": "now", "ip_address": "127.0.0.1"}],
            "password": "secret",
        },
    )

    assert response.status_code == 201, response.text
    action, kwargs = account_lifecycle_app["service"].calls[-1]
    assert action == "create_baskt_account"
    assert kwargs["password"] == "secret"
    assert "password" not in kwargs["account_data"]


def test_account_details_and_profile_updates_return_refreshed_account(
    account_lifecycle_client,
    account_lifecycle_app,
) -> None:
    details = account_lifecycle_client.get("/accounts/account-details")
    assert details.status_code == 200, details.text
    assert details.json()["display_name"] == f"display-{OTHER_USER_ID}"

    display_name = account_lifecycle_client.put(
        "/accounts/profile/display-name",
        json={"display_name": "New Name"},
    )
    description = account_lifecycle_client.put(
        "/accounts/profile/description",
        json={"description": "Updated profile"},
    )

    assert display_name.status_code == 200, display_name.text
    assert display_name.json()["display_name"] == "New Name"
    assert description.status_code == 200, description.text
    assert description.json()["description"] == "Updated profile"
    assert ("update_display_name", {"cognito_user_id": OTHER_USER_ID, "display_name": "New Name"}) in account_lifecycle_app["service"].calls


def test_identity_update_rejects_permanent_resident_for_us_citizens(
    account_lifecycle_client,
) -> None:
    response = account_lifecycle_client.put(
        "/accounts/account-details/identity",
        json={"country_of_citizenship": "USA", "permanent_resident": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PERMANENT_RESIDENT_UPDATE_NOT_ALLOWED"


def test_contact_and_disclosure_updates_require_authenticated_alpaca_account(
    account_lifecycle_client,
    account_lifecycle_app,
) -> None:
    contact = account_lifecycle_client.put(
        "/accounts/account-details/contact",
        json={
            "email_address": "new@example.com",
            "street_address": "456 New St",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
    )
    disclosures = account_lifecycle_client.put(
        "/accounts/account-details/disclosures",
        json={"immediate_family_exposed": True},
    )

    assert contact.status_code == 200, contact.text
    assert contact.json()["contact"]["email_address"] == "new@example.com"
    assert disclosures.status_code == 200, disclosures.text
    assert disclosures.json()["disclosures"]["immediate_family_exposed"] is True
    update_calls = [
        kwargs
        for action, kwargs in account_lifecycle_app["service"].calls
        if action == "update_baskt_account"
    ]
    assert update_calls[0]["alpaca_account_id"] == OTHER_ALPACA_ACCOUNT_ID


def test_trade_account_route_returns_sdk_account_fields(account_lifecycle_client) -> None:
    response = account_lifecycle_client.get("/accounts/trade-account")

    assert response.status_code == 200, response.text
    assert response.json()["equity"] == "1000.00"
    assert response.json()["status"] == "ACTIVE"


def test_ach_and_bank_relationship_routes_convert_sdk_models(
    account_lifecycle_client,
) -> None:
    ach = account_lifecycle_client.get("/accounts/ach-relationships")
    bank = account_lifecycle_client.get("/accounts/banks")

    assert ach.status_code == 200, ach.text
    assert ach.json()[0]["relationship_id"] == "ach-1"
    assert ach.json()[0]["alpaca_account_id"] == OTHER_ALPACA_ACCOUNT_ID
    assert bank.status_code == 200, bank.text
    assert bank.json()[0]["bank_id"] == "bank-1"
    assert bank.json()[0]["bank_code_type"] == "ABA"


def test_create_and_update_funding_relationships_call_scoped_service_methods(
    account_lifecycle_client,
    account_lifecycle_app,
) -> None:
    direct_ach = {
        "account_owner_name": "Route Tester",
        "bank_account_type": "CHECKING",
        "bank_account_number": "1234",
        "bank_routing_number": "121000358",
        "nickname": "Primary",
    }
    bank = {
        "name": "Primary Bank",
        "bank_code_type": "ABA",
        "bank_code": "121000358",
        "account_number": "000123",
        "country": "USA",
    }

    assert account_lifecycle_client.post("/accounts/ach-relationship", json=direct_ach).status_code == 201
    assert account_lifecycle_client.put("/accounts/ach-relationship", json={"processor_token": "processor-token"}).status_code == 201
    assert account_lifecycle_client.post("/accounts/bank", json=bank).status_code == 201
    assert account_lifecycle_client.put("/accounts/bank", json=bank).status_code == 201

    actions = [action for action, _ in account_lifecycle_app["service"].calls]
    assert "create_direct_ach_relationship" in actions
    assert "delete_ach_relationship" in actions
    assert "create_plaid_ach_relationship" in actions
    assert "delete_bank" in actions
    assert "create_bank" in actions


def test_transfer_routes_list_create_and_cancel_scoped_transfers(
    account_lifecycle_client,
    account_lifecycle_app,
) -> None:
    list_response = account_lifecycle_client.get(
        "/accounts/transfers",
        params={"limit": 1, "offset": 1},
    )
    ach_create = account_lifecycle_client.post(
        "/accounts/transfer",
        json={
            "amount": "25.00",
            "direction": "INCOMING",
            "funding_source_type": "ACH",
            "relationship_id": "ach-1",
            "timing": "IMMEDIATE",
        },
    )
    bank_create = account_lifecycle_client.post(
        "/accounts/transfer",
        json={
            "amount": "25.00",
            "direction": "OUTGOING",
            "funding_source_type": "BANK",
            "bank_id": "bank-1",
            "timing": "IMMEDIATE",
        },
    )
    cancel = account_lifecycle_client.delete("/accounts/transfers/transfer-1")

    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["items"][0]["transfer_id"] == "transfer-1"
    assert list_response.json()["has_next"] is True
    assert list_response.json()["has_previous"] is True
    assert ach_create.status_code == 201, ach_create.text
    assert bank_create.status_code == 201, bank_create.text
    assert cancel.status_code == 204
    assert account_lifecycle_app["service"].calls[-1] == (
        "cancel_transfer",
        {
            "cognito_user_id": OTHER_USER_ID,
            "alpaca_account_id": OTHER_ALPACA_ACCOUNT_ID,
            "transfer_id": "transfer-1",
        },
    )


def test_transfer_route_rejects_unsupported_funding_source(
    account_lifecycle_client,
) -> None:
    response = account_lifecycle_client.post(
        "/accounts/transfer",
        json={
            "amount": "25.00",
            "direction": "INCOMING",
            "funding_source_type": "WIRE",
            "timing": "IMMEDIATE",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ACCOUNT_LIFECYCLE_UNSUPPORTED_TRANSFER_SOURCE"


def test_lifecycle_route_maps_service_errors(
    account_lifecycle_client,
    account_lifecycle_app,
) -> None:
    account_lifecycle_app["app"].dependency_overrides[get_account_lifecycle_service] = (
        lambda: FakeLifecycleService(fail=AccountLifecycleDisplayNameTakenError("taken"))
    )

    conflict = account_lifecycle_client.get(
        "/accounts/is-exists-display-name",
        params={"display_name": "taken"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "ACCOUNT_LIFECYCLE_DISPLAY_NAME_TAKEN"

    account_lifecycle_app["app"].dependency_overrides[get_account_lifecycle_service] = (
        lambda: FakeLifecycleService(
            fail=AccountLifecycleInternalServerError(
                "bad request",
                code="ACCOUNT_LIFECYCLE_INVALID_REQUEST",
            )
        )
    )

    invalid = account_lifecycle_client.get(
        "/accounts/is-exists-display-name",
        params={"display_name": "bad"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "ACCOUNT_LIFECYCLE_INVALID_REQUEST"

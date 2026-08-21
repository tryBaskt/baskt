"""
Coverage / scenarios:
- is_exists_display_name(): existing and unused display names return the
  expected boolean response; blank query values return 422.
- create_baskt_account(): creates real Alpaca, Cognito, and DynamoDB records,
  rejects duplicate display names with 409, and rejects invalid payloads.
- account-details: authenticated users can fetch their persisted profile;
  missing auth, missing Baskt accounts, token Alpaca-account mismatches, and
  unknown token Cognito user ids are rejected.
- profile/display-name and profile/description: authenticated users can update
  profile fields and receive refreshed account details; duplicate and blank
  display names are rejected.
- account-details/contact, account-details/identity, and
  account-details/disclosures: authenticated users with active Alpaca accounts
  can update each account section, and the response, DynamoDB record, and
  Alpaca account all reflect the change. US citizens cannot update permanent
  resident status through the identity route.
- trade-account: authenticated users receive a shaped Alpaca trade account
  response and auth mismatch cases are rejected.
- ach-relationship, ach-relationships, transfer, transfers, and transfer
  cancellation: a fresh account creates one direct ACH relationship and at most
  one transfer, verifies list responses and pagination metadata, cancels the
  transfer, and cleans up the relationship/account.
- Bank and Plaid routes are intentionally not covered here because those flows
  are not available for these integrated tests.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from time import monotonic, sleep
from typing import Any, Mapping
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from core import authentication as auth
from core.authentication import get_current_user
from core.deps import (
    get_account_lifecycle_service,
    get_alpaca_broker_client,
    get_baskt_account_repository,
)
from domain.baskt_account_domain import BasktAccount
from repository.baskt_account_repository import BasktAccountRepository
from routes import account_lifecycle_route
from services.account_lifecycle_service import AccountLifecycleService


pytestmark = pytest.mark.integration


def _account_payload(*, unique: str) -> dict[str, Any]:
    return {
        "display_name": f"tests-v2-route-{unique[:12]}",
        "password": f"Test_9aA{unique[:16]}",
        "contact": {
            "email_address": f"tests_v2_route_{unique}@example.com",
            "phone_number": "+15555551234",
            "street_address": ["123 Market St"],
            "unit": "9A",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        "identity": {
            "given_name": "Workflow",
            "middle_name": "Q",
            "family_name": "Tester",
            "date_of_birth": "1990-01-01",
            "tax_id": "999-99-1234",
            "tax_id_type": "USA_SSN",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income", "savings"],
            "annual_income_min": 50000,
            "annual_income_max": 120000,
            "liquid_net_worth_min": 10000,
            "liquid_net_worth_max": 50000,
            "total_net_worth_min": 50000,
            "total_net_worth_max": 200000,
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
            "employment_status": "EMPLOYED",
            "employer_name": "Baskt Route Test Employer",
            "employer_address": "123 Market St, San Francisco, CA 94105",
            "employment_position": "Software Engineer",
        },
        "agreements": [
            {
                "agreement": agreement,
                "signed_at": datetime.now(timezone.utc).isoformat(),
                "ip_address": "127.0.0.1",
            }
            for agreement in (
                "account_agreement",
                "customer_agreement",
                "margin_agreement",
                "crypto_agreement",
            )
        ],
    }


def _claims_for_ids(*, cognito_user_id: str, alpaca_account_id: str) -> dict[str, str]:
    return {
        "sub": cognito_user_id,
        "custom:alpaca_acct_id": alpaca_account_id,
    }


def _claims_for_account(account: BasktAccount) -> dict[str, str]:
    return _claims_for_ids(
        cognito_user_id=account.cognito_user_id,
        alpaca_account_id=account.alpaca_account_id,
    )


def _claims_for_test_user(test_user: Any) -> dict[str, str]:
    return _claims_for_ids(
        cognito_user_id=test_user.cognito_user_id,
        alpaca_account_id=test_user.alpaca_account_id,
    )


def _claims_without_baskt_account() -> dict[str, str]:
    unique = uuid4()
    return _claims_for_ids(
        cognito_user_id=f"tests-v2-no-baskt-account-{unique}",
        alpaca_account_id=f"tests-v2-no-baskt-alpaca-{unique}",
    )


def _claims_with_mismatched_alpaca_account(test_user: Any) -> dict[str, str]:
    return _claims_for_ids(
        cognito_user_id=test_user.cognito_user_id,
        alpaca_account_id=f"tests-v2-wrong-alpaca-{uuid4()}",
    )


def _claims_with_mismatched_cognito_user_id(test_user: Any) -> dict[str, str]:
    return _claims_for_ids(
        cognito_user_id=f"tests-v2-wrong-cognito-{uuid4()}",
        alpaca_account_id=test_user.alpaca_account_id,
    )


def _client_for_claims(
    *,
    claims: dict[str, str] | None,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
) -> TestClient:
    app = FastAPI()
    app.include_router(account_lifecycle_route.router)
    if claims is not None:
        app.dependency_overrides[get_current_user] = lambda: claims
    app.dependency_overrides[get_account_lifecycle_service] = (
        lambda: account_lifecycle_service
    )
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[get_alpaca_broker_client] = (
        lambda: alpaca_broker_client
    )
    app.dependency_overrides[auth._get_alpaca_broker_client] = (
        lambda: alpaca_broker_client
    )
    return TestClient(app)


def _unauthenticated_client(
    *,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
) -> TestClient:
    return _client_for_claims(
        claims=None,
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )


def _client_for_test_user(
    *,
    test_user: Any,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
) -> TestClient:
    return _client_for_claims(
        claims=_claims_for_test_user(test_user),
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )


def _client_for_baskt_account(
    *,
    baskt_account: BasktAccount,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
) -> TestClient:
    return _client_for_claims(
        claims=_claims_for_account(baskt_account),
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )


def _created_account_from_email(
    *,
    email_address: str,
    cognito_client: CognitoClient,
    baskt_account_repository: BasktAccountRepository,
) -> BasktAccount:
    cognito_user = cognito_client.get_cognito_user_by_email_address(
        email_address=email_address,
    )
    return baskt_account_repository.get_baskt_account(
        cognito_user_id=cognito_user["cognito_user_id"],
    )


def _create_account_through_route(
    *,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
) -> tuple[BasktAccount, dict[str, Any]]:
    payload = _account_payload(unique=uuid4().hex)
    client = _unauthenticated_client(
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    response = client.post("/accounts/create-baskt-account", json=payload)
    assert response.status_code == 201
    return (
        _created_account_from_email(
            email_address=payload["contact"]["email_address"],
            cognito_client=cognito_client,
            baskt_account_repository=baskt_account_repository,
        ),
        payload,
    )


def _permanently_close_account_if_exists(
    *,
    account_lifecycle_service: AccountLifecycleService,
    baskt_account: BasktAccount | None,
) -> None:
    if baskt_account is None:
        return
    try:
        account_lifecycle_service.permanently_close_baskt_account(
            cognito_user_id=baskt_account.cognito_user_id,
            alpaca_account_id=baskt_account.alpaca_account_id,
        )
    except Exception:
        pass


def _object_id(value: Any) -> str:
    return str(getattr(value, "id"))


def _object_status_name(value: Any) -> str:
    status = getattr(value, "status", None)
    return str(getattr(status, "name", status)).upper()


def _wait_until(predicate, *, description: str, timeout_seconds: float = 15) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.5)
    raise AssertionError(f"Timed out waiting for {description}")


def _cancel_transfer_if_active(
    *,
    account_lifecycle_service: AccountLifecycleService,
    cognito_user_id: str,
    alpaca_account_id: str,
    transfer_id: str | None,
) -> None:
    if transfer_id is None:
        return
    try:
        transfers = account_lifecycle_service.get_transfers(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
        )
        transfer = next(
            (item for item in transfers if _object_id(item) == transfer_id),
            None,
        )
        if transfer is not None and _object_status_name(transfer) in {
            "QUEUED",
            "APPROVAL_PENDING",
            "PENDING",
        }:
            account_lifecycle_service.cancel_transfer(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                transfer_id=transfer_id,
            )
    except Exception:
        pass


def _delete_ach_relationship_if_exists(
    *,
    account_lifecycle_service: AccountLifecycleService,
    cognito_user_id: str,
    alpaca_account_id: str,
    relationship_id: str | None,
) -> None:
    if relationship_id is None:
        return
    try:
        account_lifecycle_service.delete_ach_relationship(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            ach_relationship_id=relationship_id,
        )
    except Exception:
        pass


def _assert_expected_fields(
    expected: Mapping[str, Any],
    actual: Any,
    *,
    path: str,
) -> None:
    if is_dataclass(actual) and not isinstance(actual, type):
        actual_data = asdict(actual)
    elif hasattr(actual, "model_dump"):
        actual_data = actual.model_dump()
    elif hasattr(actual, "dict"):
        actual_data = actual.dict()
    else:
        actual_data = actual
    assert isinstance(actual_data, Mapping), f"{path} is not an object"

    for key, expected_value in expected.items():
        field_path = f"{path}.{key}"
        assert key in actual_data, f"Missing {field_path}"
        actual_value = actual_data[key]
        if isinstance(expected_value, Mapping):
            _assert_expected_fields(
                expected_value,
                actual_value,
                path=field_path,
            )
            continue
        if isinstance(expected_value, (list, tuple)):
            expected_items = list(expected_value)
            actual_items = list(actual_value)
            assert len(actual_items) == len(expected_items)
            for expected_item, actual_item in zip(expected_items, actual_items):
                if isinstance(expected_item, Enum):
                    expected_item = expected_item.value
                if isinstance(actual_item, Enum):
                    actual_item = actual_item.value
                assert str(expected_item) == str(actual_item)
            continue
        if isinstance(expected_value, Enum):
            expected_value = expected_value.value
        if isinstance(actual_value, Enum):
            actual_value = actual_value.value
        values_match = expected_value == actual_value
        if not values_match and not isinstance(
            expected_value,
            bool,
        ) and not isinstance(actual_value, bool):
            try:
                values_match = Decimal(str(expected_value)) == Decimal(
                    str(actual_value)
                )
            except (InvalidOperation, ValueError):
                values_match = str(expected_value) == str(actual_value)
        assert values_match, (
            f"{field_path} differs: expected {expected_value!r}, "
            f"received {actual_value!r}"
        )


def test_account_lifecycle_route_display_name_exists_variants(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    test_user_1: Any,
) -> None:
    client = _client_for_test_user(
        test_user=test_user_1,
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    account = account_lifecycle_service.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id,
    )

    existing_response = client.get(
        "/accounts/is-exists-display-name",
        params={"display_name": account.display_name},
    )
    assert existing_response.status_code == 200
    assert existing_response.json() == {"is_exists": True}

    unused_response = client.get(
        "/accounts/is-exists-display-name",
        params={"display_name": f"tests-v2-unused-123"},
    )
    assert unused_response.status_code == 200
    assert unused_response.json() == {"is_exists": False}

    blank_response = client.get(
        "/accounts/is-exists-display-name",
        params={"display_name": "   "},
    )
    assert blank_response.status_code == 422


def test_account_lifecycle_route_create_baskt_account_happy_path_and_duplicate(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
) -> None:
    payload = _account_payload(unique=uuid4().hex)
    created_account = None
    client = _unauthenticated_client(
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )

    try:
        create_response = client.post("/accounts/create-baskt-account", json=payload)
        assert create_response.status_code == 201
        created_account = _created_account_from_email(
            email_address=payload["contact"]["email_address"],
            cognito_client=cognito_client,
            baskt_account_repository=baskt_account_repository,
        )
        assert created_account.display_name == payload["display_name"]
        assert created_account.contact_data.email_address == payload["contact"][
            "email_address"
        ]

        cognito_user = cognito_client.get_cognito_user_by_cognito_user_id(
            cognito_user_id=created_account.cognito_user_id,
        )
        assert cognito_user["alpaca_account_id"] == created_account.alpaca_account_id

        alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
            account_id=created_account.alpaca_account_id,
            cognito_user_id=created_account.cognito_user_id,
        )
        assert str(alpaca_account.id) == created_account.alpaca_account_id

        duplicate_payload = _account_payload(unique=uuid4().hex)
        duplicate_payload["display_name"] = payload["display_name"]
        duplicate_response = client.post(
            "/accounts/create-baskt-account",
            json=duplicate_payload,
        )
        assert duplicate_response.status_code == 409
    finally:
        _permanently_close_account_if_exists(
            account_lifecycle_service=account_lifecycle_service,
            baskt_account=created_account,
        )


def test_account_lifecycle_route_create_baskt_account_rejects_invalid_payload(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
) -> None:
    client = _unauthenticated_client(
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    payload = _account_payload(unique=uuid4().hex)
    payload["display_name"] = ""

    response = client.post("/accounts/create-baskt-account", json=payload)

    assert response.status_code == 422


def test_account_lifecycle_route_account_details_auth_cases(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    test_user_1: Any,
) -> None:
    account = account_lifecycle_service.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id,
    )
    client = _client_for_test_user(
        test_user=test_user_1,
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )

    response = client.get("/accounts/account-details")
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == account.display_name
    assert body["contact"]["email_address"] == account.contact_data.email_address

    unauthenticated = _unauthenticated_client(
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    assert unauthenticated.get("/accounts/account-details").status_code == 401

    no_baskt = _client_for_claims(
        claims=_claims_without_baskt_account(),
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    assert no_baskt.get("/accounts/account-details").status_code == 403

    mismatched_alpaca = _client_for_claims(
        claims=_claims_with_mismatched_alpaca_account(test_user_1),
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    assert mismatched_alpaca.get("/accounts/account-details").status_code == 403

    mismatched_cognito = _client_for_claims(
        claims=_claims_with_mismatched_cognito_user_id(test_user_1),
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    assert mismatched_cognito.get("/accounts/account-details").status_code == 403


def test_account_lifecycle_route_updates_profile_display_name_and_description(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    test_user_1: Any,
) -> None:
    created_account = None
    try:
        created_account, payload = _create_account_through_route(
            account_lifecycle_service=account_lifecycle_service,
            baskt_account_repository=baskt_account_repository,
            alpaca_broker_client=alpaca_broker_client,
            cognito_client=cognito_client,
        )
        client = _client_for_baskt_account(
            baskt_account=created_account,
            account_lifecycle_service=account_lifecycle_service,
            baskt_account_repository=baskt_account_repository,
            alpaca_broker_client=alpaca_broker_client,
        )

        new_display_name = f"tests-v2-route-updated-{uuid4().hex[:12]}"
        display_response = client.put(
            "/accounts/profile/display-name",
            json={"display_name": new_display_name},
        )
        assert display_response.status_code == 200
        assert display_response.json()["display_name"] == new_display_name
        assert not account_lifecycle_service.is_exists_display_name(
            payload["display_name"],
        )
        assert account_lifecycle_service.is_exists_display_name(new_display_name)

        existing_account = account_lifecycle_service.get_baskt_account(
            cognito_user_id=test_user_1.cognito_user_id,
        )
        duplicate_response = client.put(
            "/accounts/profile/display-name",
            json={"display_name": existing_account.display_name},
        )
        assert duplicate_response.status_code == 409

        blank_response = client.put(
            "/accounts/profile/display-name",
            json={"display_name": ""},
        )
        assert blank_response.status_code == 422

        new_description = f"Updated route description {uuid4()}"
        description_response = client.put(
            "/accounts/profile/description",
            json={"description": new_description},
        )
        assert description_response.status_code == 200
        assert description_response.json()["description"] == new_description
        persisted = account_lifecycle_service.get_baskt_account(
            cognito_user_id=created_account.cognito_user_id,
        )
        assert persisted.description == new_description
    finally:
        _permanently_close_account_if_exists(
            account_lifecycle_service=account_lifecycle_service,
            baskt_account=created_account,
        )


def test_account_lifecycle_route_updates_account_detail_sections(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
) -> None:
    created_account = None
    try:
        created_account, payload = _create_account_through_route(
            account_lifecycle_service=account_lifecycle_service,
            baskt_account_repository=baskt_account_repository,
            alpaca_broker_client=alpaca_broker_client,
            cognito_client=cognito_client,
        )
        client = _client_for_baskt_account(
            baskt_account=created_account,
            account_lifecycle_service=account_lifecycle_service,
            baskt_account_repository=baskt_account_repository,
            alpaca_broker_client=alpaca_broker_client,
        )

        contact_payload = {
            **payload["contact"],
            "phone_number": "+15555559876",
            "street_address": ["456 Mission St"],
            "unit": "12B",
        }
        contact_response = client.put(
            "/accounts/account-details/contact",
            json=contact_payload,
        )
        assert contact_response.status_code == 200
        assert contact_response.json()["contact"]["phone_number"] == "+15555559876"
        persisted = account_lifecycle_service.get_baskt_account(
            cognito_user_id=created_account.cognito_user_id,
        )
        assert persisted.contact_data.phone_number == "+15555559876"

        identity_payload = {
            "middle_name": "Updated",
            "annual_income_min": 60000,
            "annual_income_max": 130000,
            "liquid_net_worth_min": 20000,
            "liquid_net_worth_max": 60000,
            "total_net_worth_min": 60000,
            "total_net_worth_max": 210000,
        }
        identity_response = client.put(
            "/accounts/account-details/identity",
            json=identity_payload,
        )
        assert identity_response.status_code == 200
        assert identity_response.json()["identity"]["middle_name"] == "Updated"

        permanent_resident_response = client.put(
            "/accounts/account-details/identity",
            json={"permanent_resident": True},
        )
        assert permanent_resident_response.status_code == 422

        disclosures_payload = {
            "immediate_family_exposed": False,
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "employment_status": "EMPLOYED",
            "employer_name": "Updated Baskt Route Test Employer",
            "employer_address": "456 Mission St, San Francisco, CA 94105",
            "employment_position": "Senior Software Engineer",
        }
        disclosures_response = client.put(
            "/accounts/account-details/disclosures",
            json=disclosures_payload,
        )
        assert disclosures_response.status_code == 200
        assert disclosures_response.json()["disclosures"]["employer_name"] == (
            "Updated Baskt Route Test Employer"
        )

        persisted = account_lifecycle_service.get_baskt_account(
            cognito_user_id=created_account.cognito_user_id,
        )
        assert persisted.contact_data.phone_number == "+15555559876"
        assert persisted.identity_data.middle_name == "Updated"
        assert persisted.disclosures_data.employer_name == (
            "Updated Baskt Route Test Employer"
        )

        alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
            account_id=created_account.alpaca_account_id,
            cognito_user_id=created_account.cognito_user_id,
        )
        _assert_expected_fields(contact_payload, alpaca_account.contact, path="contact")
        _assert_expected_fields(
            {
                **{
                    key: value
                    for key, value in payload["identity"].items()
                    if key != "tax_id"
                },
                **identity_payload,
            },
            alpaca_account.identity,
            path="identity",
        )
        _assert_expected_fields(
            disclosures_payload,
            alpaca_account.disclosures,
            path="disclosures",
        )
    finally:
        _permanently_close_account_if_exists(
            account_lifecycle_service=account_lifecycle_service,
            baskt_account=created_account,
        )


def test_account_lifecycle_route_trade_account_auth_cases(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    test_user_1: Any,
) -> None:
    client = _client_for_test_user(
        test_user=test_user_1,
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )

    response = client.get("/accounts/trade-account")
    assert response.status_code == 200
    body = response.json()
    assert "equity" in body
    assert "cash_withdrawable" in body
    assert "status" in body

    unauthenticated = _unauthenticated_client(
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    assert unauthenticated.get("/accounts/trade-account").status_code == 401

    mismatched = _client_for_claims(
        claims=_claims_with_mismatched_alpaca_account(test_user_1),
        account_lifecycle_service=account_lifecycle_service,
        baskt_account_repository=baskt_account_repository,
        alpaca_broker_client=alpaca_broker_client,
    )
    assert mismatched.get("/accounts/trade-account").status_code == 403


def test_account_lifecycle_route_direct_ach_and_transfer_lifecycle(
    account_lifecycle_service: AccountLifecycleService,
    baskt_account_repository: BasktAccountRepository,
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
) -> None:
    created_account = None
    relationship_id = None
    transfer_id = None

    try:
        created_account, _ = _create_account_through_route(
            account_lifecycle_service=account_lifecycle_service,
            baskt_account_repository=baskt_account_repository,
            alpaca_broker_client=alpaca_broker_client,
            cognito_client=cognito_client,
        )
        client = _client_for_baskt_account(
            baskt_account=created_account,
            account_lifecycle_service=account_lifecycle_service,
            baskt_account_repository=baskt_account_repository,
            alpaca_broker_client=alpaca_broker_client,
        )

        empty_relationships = client.get("/accounts/ach-relationships")
        assert empty_relationships.status_code == 200
        assert empty_relationships.json() == []

        relationship_response = client.post(
            "/accounts/ach-relationship",
            json={
                "account_owner_name": "Baskt Route Test User",
                "bank_account_type": "CHECKING",
                "bank_account_number": "123456789",
                "bank_routing_number": "011000015",
                "nickname": f"tests-v2-route-ach-{uuid4().hex[:8]}",
            },
        )
        assert relationship_response.status_code == 201

        relationships_response = client.get("/accounts/ach-relationships")
        assert relationships_response.status_code == 200
        relationships = relationships_response.json()
        assert len(relationships) == 1
        relationship = relationships[0]
        relationship_id = relationship["relationship_id"]
        assert relationship["alpaca_account_id"] == created_account.alpaca_account_id
        assert relationship["account_owner_name"] == "Baskt Route Test User"
        assert relationship["bank_account_type"] == "CHECKING"

        transfer_response = client.post(
            "/accounts/transfer",
            json={
                "amount": "1.00",
                "direction": "INCOMING",
                "funding_source_type": "ACH",
                "relationship_id": relationship_id,
                "timing": "IMMEDIATE",
                "fee_payment_method": "USER",
            },
        )
        assert transfer_response.status_code == 201

        transfers_response = client.get(
            "/accounts/transfers",
            params={"limit": 1, "offset": 0},
        )
        assert transfers_response.status_code == 200
        transfers_body = transfers_response.json()
        assert transfers_body["limit"] == 1
        assert transfers_body["offset"] == 0
        assert transfers_body["has_previous"] is False
        assert len(transfers_body["items"]) == 1
        transfer = transfers_body["items"][0]
        transfer_id = transfer["transfer_id"]
        assert transfer["alpaca_account_id"] == created_account.alpaca_account_id
        assert transfer["relationship_id"].upper() == relationship_id.upper()
        assert Decimal(transfer["amount"]) == Decimal("1.00")
        assert transfer["direction"] == "INCOMING"

        invalid_limit = client.get("/accounts/transfers", params={"limit": 0})
        assert invalid_limit.status_code == 422
        invalid_offset = client.get("/accounts/transfers", params={"offset": -1})
        assert invalid_offset.status_code == 422

        cancel_response = client.delete(f"/accounts/transfers/{transfer_id}")
        assert cancel_response.status_code == 204

        canceled_transfer = None

        def transfer_is_canceled() -> bool:
            nonlocal canceled_transfer
            transfer_items = client.get("/accounts/transfers").json()["items"]
            canceled_transfer = next(
                (
                    item
                    for item in transfer_items
                    if item["transfer_id"] == transfer_id
                ),
                None,
            )
            return (
                canceled_transfer is not None
                and canceled_transfer["status"] == "CANCELED"
            )

        _wait_until(
            transfer_is_canceled,
            description=f"transfer '{transfer_id}' to be canceled",
        )
        assert canceled_transfer is not None
        assert canceled_transfer["status"] == "CANCELED"
    finally:
        if created_account is not None:
            _cancel_transfer_if_active(
                account_lifecycle_service=account_lifecycle_service,
                cognito_user_id=created_account.cognito_user_id,
                alpaca_account_id=created_account.alpaca_account_id,
                transfer_id=transfer_id,
            )
            _delete_ach_relationship_if_exists(
                account_lifecycle_service=account_lifecycle_service,
                cognito_user_id=created_account.cognito_user_id,
                alpaca_account_id=created_account.alpaca_account_id,
                relationship_id=relationship_id,
            )
        _permanently_close_account_if_exists(
            account_lifecycle_service=account_lifecycle_service,
            baskt_account=created_account,
        )

"""
Coverage / scenarios:
- create_baskt_account(): create a real Alpaca account, Cognito user, and
  persisted Baskt account from one account payload.
- create_baskt_account(): verify the created account exists in Cognito,
  Alpaca, DynamoDB, and that get_trade_account() returns successfully.
- is_exists_display_name(): return true for the created display name.
- update_display_name(): update the persisted display name, then verify the
  old display name no longer exists and the new display name does exist.
- update_description(): update the persisted profile description and verify it
  in DynamoDB.
- update_baskt_account(): update ContactData, IdentityData, and
  DisclosuresData one at a time through the service, then verify each
  replacement in DynamoDB and Alpaca.
- permanently_close_baskt_account(): close the created Alpaca account, delete
  the Cognito user, and delete the persisted Baskt account in cleanup.
- create_baskt_account(): reject duplicate and blank display names.
- is_exists_display_name() and update_display_name(): reject blank display
  names.
- get_baskt_account(): return an env-backed test account and wrap missing
  account failures.
- get_trade_account(): wrap missing Alpaca trade account failures.
- create_ach_transfer(): wrap malformed ACH transfer requests.
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

from clients.alpaca_broker_client import AlpacaBrokerClient
from clients.cognito_client import CognitoClient
from domain.baskt_account_domain import ContactData, DisclosuresData, IdentityData
from repository.baskt_account_repository import (
    BasktAccountNotFoundError,
    BasktAccountRepository,
)
from services.account_lifecycle_service import (
    AccountLifecycleDisplayNameTakenError,
    AccountLifecycleInternalServerError,
    AccountLifecycleService,
)


pytestmark = pytest.mark.integration


def _account_data(*, unique: str) -> dict:
    return {
        "display_name": f"tests-v2-lifecycle-{unique[:12]}",
        "contact": {
            "email_address": f"tests_v2_lifecycle_{unique}@example.com",
            "phone_number": "+15555551234",
            "street_address": ["123 Market St"],
            "unit": "9A",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        "identity": {
            "given_name": "Lifecycle",
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
            "employer_name": "Baskt Lifecycle Test Employer",
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
        elif isinstance(expected_value, (list, tuple)):
            expected_items = list(expected_value)
            actual_items = list(actual_value)
            assert len(actual_items) == len(expected_items), (
                f"{field_path} length differs: expected {len(expected_items)}, "
                f"received {len(actual_items)}"
            )
            for index, (expected_item, actual_item) in enumerate(
                zip(expected_items, actual_items)
            ):
                item_path = f"{field_path}[{index}]"
                if isinstance(expected_item, Mapping):
                    _assert_expected_fields(
                        expected_item,
                        actual_item,
                        path=item_path,
                    )
                    continue
                if isinstance(expected_item, Enum):
                    expected_item = expected_item.value
                if isinstance(actual_item, Enum):
                    actual_item = actual_item.value
                assert str(expected_item) == str(actual_item), (
                    f"{item_path} differs: expected {expected_item!r}, "
                    f"received {actual_item!r}"
                )
        else:
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


def _permanently_close_created_account(
    *,
    account_lifecycle_service: AccountLifecycleService,
    created_account: dict[str, str] | None,
) -> None:
    if created_account is None:
        return
    account_lifecycle_service.permanently_close_baskt_account(
        cognito_user_id=created_account["cognito_user_id"],
        alpaca_account_id=created_account["alpaca_account_id"],
    )


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
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            ach_relationship_id=relationship_id,
        )
    except Exception:
        pass


def test_account_lifecycle_service_create_update_and_permanently_close_account(
    account_lifecycle_service: AccountLifecycleService,
    alpaca_broker_client: AlpacaBrokerClient,
    cognito_client: CognitoClient,
    baskt_account_repository: BasktAccountRepository,
) -> None:
    unique = uuid4().hex
    account_data = _account_data(unique=unique)
    created_account = None

    try:
        created_account = account_lifecycle_service.create_baskt_account(
            account_data=account_data,
            password=f"Test_9aA{unique[:16]}",
        )

        cognito_user_id = created_account["cognito_user_id"]
        alpaca_account_id = created_account["alpaca_account_id"]

        assert created_account["alpaca_account_id"]
        assert created_account["alpaca_account_number"]
        assert created_account["cognito_user_id"]
        assert (
            created_account["email_address"]
            == account_data["contact"]["email_address"]
        )

        cognito_user = cognito_client.get_cognito_user_by_cognito_user_id(
            cognito_user_id=cognito_user_id,
        )
        assert cognito_user["cognito_user_id"] == cognito_user_id
        assert cognito_user["email_address"] == account_data["contact"][
            "email_address"
        ]
        assert cognito_user["alpaca_account_id"] == alpaca_account_id

        alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        assert str(alpaca_account.id) == alpaca_account_id

        trade_account = account_lifecycle_service.get_trade_account(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        assert trade_account is not None
        assert hasattr(trade_account, "cash")
        assert hasattr(trade_account, "buying_power")

        baskt_account = baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id,
        )
        assert baskt_account.cognito_user_id == cognito_user_id
        assert baskt_account.alpaca_account_id == alpaca_account_id
        assert baskt_account.display_name == account_data["display_name"]
        assert baskt_account.contact_data.email_address == account_data["contact"][
            "email_address"
        ]
        assert baskt_account.identity_data.given_name == "Lifecycle"
        assert baskt_account.disclosures_data.employer_name == (
            "Baskt Lifecycle Test Employer"
        )

        assert account_lifecycle_service.is_exists_display_name(
            account_data["display_name"]
        )

        old_display_name = account_data["display_name"]
        new_display_name = f"tests-v2-lifecycle-updated-{unique[:12]}"
        account_lifecycle_service.update_display_name(
            cognito_user_id=cognito_user_id,
            display_name=new_display_name,
        )
        assert not account_lifecycle_service.is_exists_display_name(old_display_name)
        assert account_lifecycle_service.is_exists_display_name(new_display_name)
        assert (
            baskt_account_repository.get_baskt_account(
                cognito_user_id=cognito_user_id
            ).display_name
            == new_display_name
        )

        new_description = f"Updated lifecycle description {unique}"
        account_lifecycle_service.update_description(
            cognito_user_id=cognito_user_id,
            description=new_description,
        )
        assert (
            baskt_account_repository.get_baskt_account(
                cognito_user_id=cognito_user_id
            ).description
            == new_description
        )

        contact_data = ContactData(
            email_address=account_data["contact"]["email_address"],
            phone_number="+15555559876",
            street_address=["456 Mission St"],
            unit="12B",
            city="San Francisco",
            state="CA",
            postal_code="94105",
            country="USA",
        )
        account_lifecycle_service.update_baskt_account(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            updated_data=contact_data,
        )
        persisted = baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id,
        )
        assert persisted.contact_data == contact_data
        alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        _assert_expected_fields(
            asdict(contact_data),
            alpaca_account.contact,
            path="alpaca.contact",
        )

        identity_data = IdentityData(
            given_name="Lifecycle",
            middle_name="Updated",
            family_name="Tester",
            date_of_birth="1990-01-01",
            tax_id_type="USA_SSN",
            country_of_citizenship="USA",
            country_of_birth="USA",
            country_of_tax_residence="USA",
            funding_source=["employment_income", "savings"],
            annual_income_min=60000,
            annual_income_max=130000,
            liquid_net_worth_min=20000,
            liquid_net_worth_max=60000,
            total_net_worth_min=60000,
            total_net_worth_max=210000,
        )
        account_lifecycle_service.update_baskt_account(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            updated_data=identity_data,
        )
        persisted = baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id,
        )
        assert persisted.identity_data == identity_data
        alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        _assert_expected_fields(
            asdict(identity_data),
            alpaca_account.identity,
            path="alpaca.identity",
        )

        disclosures_data = DisclosuresData(
            immediate_family_exposed=False,
            is_control_person=False,
            is_affiliated_exchange_or_finra=False,
            is_politically_exposed=False,
            employment_status="EMPLOYED",
            employer_name="Updated Baskt Lifecycle Test Employer",
            employer_address="456 Mission St, San Francisco, CA 94105",
            employment_position="Senior Software Engineer",
        )
        account_lifecycle_service.update_baskt_account(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            updated_data=disclosures_data,
        )
        persisted = baskt_account_repository.get_baskt_account(
            cognito_user_id=cognito_user_id,
        )
        assert persisted.disclosures_data == disclosures_data
        alpaca_account = alpaca_broker_client.get_alpaca_account_by_id(
            account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
        _assert_expected_fields(
            asdict(disclosures_data),
            alpaca_account.disclosures,
            path="alpaca.disclosures",
        )
    finally:
        if created_account is not None:
            account_lifecycle_service.permanently_close_baskt_account(
                cognito_user_id=created_account["cognito_user_id"],
                alpaca_account_id=created_account["alpaca_account_id"],
            )
            with pytest.raises(BasktAccountNotFoundError):
                baskt_account_repository.get_baskt_account(
                    cognito_user_id=created_account["cognito_user_id"],
                )


def test_account_lifecycle_service_create_baskt_account_rejects_duplicate_display_name(
    account_lifecycle_service: AccountLifecycleService,
) -> None:
    unique = uuid4().hex
    account_data = _account_data(unique=unique)
    created_account = None

    try:
        created_account = account_lifecycle_service.create_baskt_account(
            account_data=account_data,
            password=f"Test_9aA{unique[:16]}",
        )

        duplicate_payload = _account_data(unique=uuid4().hex)
        duplicate_payload["display_name"] = account_data["display_name"]

        with pytest.raises(AccountLifecycleDisplayNameTakenError):
            account_lifecycle_service.create_baskt_account(
                account_data=duplicate_payload,
                password=f"Test_9aA{uuid4().hex[:16]}",
            )
    finally:
        _permanently_close_created_account(
            account_lifecycle_service=account_lifecycle_service,
            created_account=created_account,
        )


def test_account_lifecycle_service_create_baskt_account_rejects_blank_display_name(
    account_lifecycle_service: AccountLifecycleService,
) -> None:
    account_data = _account_data(unique=uuid4().hex)
    account_data["display_name"] = "   "

    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        account_lifecycle_service.create_baskt_account(account_data=account_data)

    assert exc_info.value.code == "ACCOUNT_LIFECYCLE_DISPLAY_NAME_INVALID"


def test_account_lifecycle_service_is_exists_display_name_rejects_blank_input(
    account_lifecycle_service: AccountLifecycleService,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        account_lifecycle_service.is_exists_display_name("   ")

    assert exc_info.value.code == "ACCOUNT_LIFECYCLE_DISPLAY_NAME_INVALID"


def test_account_lifecycle_service_update_display_name_rejects_blank_input(
    account_lifecycle_service: AccountLifecycleService,
    test_user_1: Any,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        account_lifecycle_service.update_display_name(
            cognito_user_id=test_user_1.cognito_user_id,
            display_name="   ",
        )

    assert exc_info.value.code == "ACCOUNT_LIFECYCLE_UPDATE_DISPLAY_NAME_INVALID"


def test_account_lifecycle_service_get_baskt_account_success_and_missing_account(
    account_lifecycle_service: AccountLifecycleService,
    test_user_1: Any,
) -> None:
    account = account_lifecycle_service.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id,
    )
    assert account.cognito_user_id == test_user_1.cognito_user_id
    assert account.alpaca_account_id == test_user_1.alpaca_account_id

    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        account_lifecycle_service.get_baskt_account(
            cognito_user_id=f"missing-tests-v2-{uuid4()}",
        )

    assert exc_info.value.code == "ACCOUNT_LIFECYCLE_GET_BASKT_ACCOUNT_FAILED"


def test_account_lifecycle_service_get_trade_account_wraps_missing_account(
    account_lifecycle_service: AccountLifecycleService,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        account_lifecycle_service.get_trade_account(
            alpaca_account_id=str(uuid4()),
            cognito_user_id=f"missing-tests-v2-{uuid4()}",
        )

    assert exc_info.value.code == "ACCOUNT_LIFECYCLE_GET_TRADE_ACCOUNT_FAILED"


def test_account_lifecycle_service_create_ach_transfer_wraps_malformed_request(
    account_lifecycle_service: AccountLifecycleService,
    test_user_1: Any,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        account_lifecycle_service.create_ach_transfer(
            alpaca_account_id=test_user_1.alpaca_account_id,
            cognito_user_id=test_user_1.cognito_user_id,
            amount="1.00",
            direction="NOT_A_DIRECTION",
            timing="IMMEDIATE",
            relationship_id=str(uuid4()),
            fee_payment_method="USER",
        )

    assert (
        exc_info.value.code
        == "ACCOUNT_LIFECYCLE_CREATE_ACH_TRANSFER_REQUEST_FAILED"
    )

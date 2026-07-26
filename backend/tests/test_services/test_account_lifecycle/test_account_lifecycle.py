"""Integration tests for the account lifecycle flow."""

from datetime import datetime, timezone
from time import monotonic, sleep
import uuid

import pytest

from .conftest import (
    TestEngine,
)
from backend.domain.baskt_account_domain import (
    ContactData,
    DisclosuresData,
    IdentityData,
)
from services.account_lifecycle_service import (
    AccountLifecycleDisplayNameTakenError,
    AccountLifecycleInternalServerError,
    AccountLifecycleServiceBasktAccountDisabled,
)


def _assert_service_error(exc_info: pytest.ExceptionInfo, code: str) -> None:
    assert exc_info.value.code == code


def _unique_account_payload() -> dict:
    unique_suffix = uuid.uuid4().hex
    return {
        "display_name": f"Service Test {unique_suffix[:12]}",
        "contact": {
            "email_address": f"baskt_service_test_{unique_suffix}@example.com",
            "phone_number": "+15555551234",
            "street_address": ["123 Market St"],
            "unit": "9A",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        "identity": {
            "given_name": "Service",
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
            "employer_name": "Baskt Service Test Employer",
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


@pytest.fixture(scope="module")
def created_baskt_account(test_engine: TestEngine):
    """Create one account shared by the independent section-update tests."""
    unique_suffix = uuid.uuid4().hex
    test_account_data = {
        "display_name": f"Lifecycle Test {unique_suffix[:8]}",
        "contact": {
            "email_address": f"baskt_test_{unique_suffix}@example.com",
            "phone_number": "+15555551234",
            "street_address": ["123 Market St"],
            "unit": "9A",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        "identity": {
            "given_name": "Jane",
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
            "employer_name": "Baskt Test Employer",
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
                "crypto_agreement"
            )
        ],
    }
    response = test_engine.test_create_baskt_account(
        test_account_data=test_account_data,
        password=f"Test_9aA{unique_suffix[:16]}",
    )
    yield {
        "response": response,
        "account_data": test_account_data,
    }

    test_engine._clean_up_achs_banks_baskt_account(
        cognito_user_id=response["cognito_user_id"],
        alpaca_account_id=response["alpaca_account_id"],
    )


def test_create_baskt_account(created_baskt_account):
    """Create an account and verify its Alpaca and DynamoDB representations."""
    response = created_baskt_account["response"]
    account_data = created_baskt_account["account_data"]

    assert response["cognito_user_id"]
    assert response["alpaca_account_id"]
    assert response["alpaca_account_number"]
    assert response["email_address"] == account_data["contact"]["email_address"]



def test_update_identity_data(
    test_engine: TestEngine,
    created_baskt_account,
):
    """Update identity data and verify the change in Alpaca and DynamoDB."""
    response = created_baskt_account["response"]
    identity_data = IdentityData(
        given_name="Jane",
        middle_name="Q",
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

    test_engine.test_update_identity_data(
        cognito_user_id=response["cognito_user_id"],
        alpaca_account_id=response["alpaca_account_id"],
        identity_data=identity_data,
    )


def test_update_contact_data(
    test_engine: TestEngine,
    created_baskt_account,
):
    """Update contact data and verify the change in Alpaca and DynamoDB."""
    response = created_baskt_account["response"]
    original_contact = created_baskt_account["account_data"]["contact"]
    contact_data = ContactData(
        email_address=original_contact["email_address"],
        phone_number="+15555559876",
        street_address=["456 Mission St"],
        unit="12B",
        city="San Francisco",
        state="CA",
        postal_code="94105",
        country="USA",
    )

    test_engine.test_update_contact_data(
        cognito_user_id=response["cognito_user_id"],
        alpaca_account_id=response["alpaca_account_id"],
        contact_data=contact_data,
    )


def test_update_disclosures_data(
    test_engine: TestEngine,
    created_baskt_account,
):
    """Update disclosures and verify the change in Alpaca and DynamoDB."""
    response = created_baskt_account["response"]
    disclosures_data = DisclosuresData(
        immediate_family_exposed=False,
        is_control_person=False,
        is_affiliated_exchange_or_finra=False,
        is_politically_exposed=False,
        employment_status="EMPLOYED",
        employer_name="Updated Baskt Test Employer",
        employer_address="456 Mission St, San Francisco, CA 94105",
        employment_position="Senior Software Engineer",
    )

    test_engine.test_update_disclosures_data(
        cognito_user_id=response["cognito_user_id"],
        alpaca_account_id=response["alpaca_account_id"],
        disclosures_data=disclosures_data,
    )


@pytest.mark.integration
def test_create_and_delete_ach_relationship(
    test_engine: TestEngine,
    created_baskt_account,
):
    """Create, retrieve, delete, and verify removal of an ACH relationship."""
    response = created_baskt_account["response"]
    alpaca_account_id = response["alpaca_account_id"]
    cognito_user_id = response["cognito_user_id"]

    created_relationship = test_engine.test_create_direct_ach_relationship(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        account_owner_name="Jane Q Tester",
        bank_account_type="CHECKING",
        bank_account_number="123456789",
        bank_routing_number="011000015",
        nickname=f"Lifecycle Test {uuid.uuid4().hex[:8]}",
    )
    relationship_id = str(created_relationship.id)

    relationships = test_engine.test_get_ach_relationships(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
    )
    assert any(str(relationship.id) == relationship_id for relationship in relationships)

    test_engine.test_delete_ach_relationship(
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        ach_relationship_id=relationship_id,
    )


@pytest.mark.integration
def test_create_and_cancel_ach_transfer_for_funded_account(
    test_engine: TestEngine,
):
    """Create an ACH transfer and verify that Alpaca marks it canceled."""
    relationships = test_engine.test_get_ach_relationships(
        alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
        cognito_user_id=test_engine.funded_50000_cognito_user_id,
    )
    assert relationships, "The funded test account must have an ACH relationship"

    transfer = test_engine.test_create_ach_transfer(
        alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
        cognito_user_id=test_engine.funded_50000_cognito_user_id,
        amount="1.00",
        direction="INCOMING",
        timing="IMMEDIATE",
        fee_payment_method="USER",
        relationship_id=str(relationships[0].id),
    )
    transfer_id = str(transfer.id)

    test_engine.account_lifecycle_service.cancel_transfer(
        cognito_user_id=test_engine.funded_50000_cognito_user_id,
        alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
        transfer_id=transfer_id,
    )

    deadline = monotonic() + 15
    canceled_transfer = None
    while monotonic() < deadline:
        transfers = test_engine.account_lifecycle_service.get_transfers(
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
        )
        canceled_transfer = next(
            (item for item in transfers if str(item.id) == transfer_id),
            None,
        )
        if canceled_transfer is not None:
            status = str(
                getattr(canceled_transfer.status, "name", canceled_transfer.status)
            ).upper()
            if status == "CANCELED":
                break
        sleep(0.5)

    assert canceled_transfer is not None
    assert str(
        getattr(canceled_transfer.status, "name", canceled_transfer.status)
    ).upper() == "CANCELED"


def test_account_lifecycle_error_classes_set_codes() -> None:
    error = AccountLifecycleInternalServerError("failed", code="CUSTOM_CODE")
    assert str(error) == "failed"
    assert error.code == "CUSTOM_CODE"

    disabled_error = AccountLifecycleServiceBasktAccountDisabled("disabled")
    assert disabled_error.code == "ACCOUNT_LIFECYCLE_SERVICE_BASKT_ACCOUNT_DISABLED"


def test_create_baskt_account_rejects_blank_display_name(
    test_engine: TestEngine,
) -> None:
    payload = _unique_account_payload()
    payload["display_name"] = "   "

    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        test_engine.account_lifecycle_service.create_baskt_account(payload)

    _assert_service_error(exc_info, "ACCOUNT_LIFECYCLE_DISPLAY_NAME_INVALID")


@pytest.mark.integration
def test_create_baskt_account_rejects_duplicate_display_name(
    test_engine: TestEngine,
    created_baskt_account,
) -> None:
    existing_account_data = created_baskt_account["account_data"]
    duplicate_payload = _unique_account_payload()
    duplicate_payload["display_name"] = existing_account_data["display_name"]

    with pytest.raises(AccountLifecycleDisplayNameTakenError) as exc_info:
        test_engine.account_lifecycle_service.create_baskt_account(
            duplicate_payload,
            password=f"Test_9aA{uuid.uuid4().hex[:16]}",
        )

    _assert_service_error(exc_info, "ACCOUNT_LIFECYCLE_DISPLAY_NAME_TAKEN")


@pytest.mark.integration
def test_create_baskt_account_wraps_real_alpaca_create_failure(
    test_engine: TestEngine,
) -> None:
    payload = _unique_account_payload()
    payload["identity"]["tax_id"] = "not-a-valid-tax-id"

    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        test_engine.account_lifecycle_service.create_baskt_account(
            payload,
            password=f"Test_9aA{uuid.uuid4().hex[:16]}",
        )

    _assert_service_error(exc_info, "ACCOUNT_LIFECYCLE_ALPACA_CREATE_FAILED")


def test_is_exists_display_name_rejects_blank_display_name(
    test_engine: TestEngine,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        test_engine.account_lifecycle_service.is_exists_display_name("   ")

    _assert_service_error(exc_info, "ACCOUNT_LIFECYCLE_DISPLAY_NAME_INVALID")


@pytest.mark.integration
def test_is_exists_display_name_uses_real_repository(
    test_engine: TestEngine,
    created_baskt_account,
) -> None:
    account_data = created_baskt_account["account_data"]

    assert test_engine.account_lifecycle_service.is_exists_display_name(
        account_data["display_name"]
    )
    assert not test_engine.account_lifecycle_service.is_exists_display_name(
        f"Missing Service Test {uuid.uuid4().hex}"
    )


def test_update_display_name_rejects_blank_display_name(
    test_engine: TestEngine,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        test_engine.account_lifecycle_service.update_display_name(
            "cognito-user-id",
            "  ",
        )

    _assert_service_error(exc_info, "ACCOUNT_LIFECYCLE_UPDATE_DISPLAY_NAME_INVALID")


@pytest.mark.integration
def test_profile_update_success_paths_use_real_repository(
    test_engine: TestEngine,
    created_baskt_account,
) -> None:
    response = created_baskt_account["response"]
    display_name = f"Updated Service Test {uuid.uuid4().hex[:12]}"
    description = f"Updated service description {uuid.uuid4().hex}"

    test_engine.account_lifecycle_service.update_display_name(
        response["cognito_user_id"],
        f"  {display_name}  ",
    )
    test_engine.account_lifecycle_service.update_description(
        response["cognito_user_id"],
        f"  {description}  ",
    )

    updated_account = test_engine.account_lifecycle_service.get_baskt_account(
        response["cognito_user_id"]
    )
    assert updated_account.display_name == display_name
    assert updated_account.description == description


@pytest.mark.integration
def test_update_baskt_account_real_alpaca_failure_is_translated(
    test_engine: TestEngine,
    created_baskt_account,
) -> None:
    response = created_baskt_account["response"]
    contact_data = ContactData(
        email_address="not-an-email",
        phone_number="not-a-phone-number",
        street_address=["123 Market St"],
        unit=None,
        city="San Francisco",
        state="CA",
        postal_code="94105",
        country="NOT_A_COUNTRY",
    )

    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        test_engine.account_lifecycle_service.update_baskt_account(
            cognito_user_id=response["cognito_user_id"],
            alpaca_account_id=response["alpaca_account_id"],
            updated_data=contact_data,
        )

    _assert_service_error(exc_info, "ACCOUNT_LIFECYCLE_UPDATE_BASKT_ACCOUNT_FAILED")


@pytest.mark.integration
def test_get_baskt_account_real_repository_failure_is_translated(
    test_engine: TestEngine,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        test_engine.account_lifecycle_service.get_baskt_account(
            f"missing-{uuid.uuid4().hex}"
        )

    _assert_service_error(exc_info, "ACCOUNT_LIFECYCLE_GET_BASKT_ACCOUNT_FAILED")


@pytest.mark.integration
@pytest.mark.parametrize(
    ("call_service", "expected_code"),
    [
        (
            lambda engine: engine.account_lifecycle_service.create_direct_ach_relationship(
                alpaca_account_id=engine.funded_50000_alpaca_account_id,
                cognito_user_id=engine.funded_50000_cognito_user_id,
                account_owner_name="Test User",
                bank_account_type="CHECKING",
                bank_account_number="123",
                bank_routing_number="021000021",
            ),
            "ACCOUNT_LIFECYCLE_CREATE_ACH_RELATIONSHIP_FAILED",
        ),
        (
            lambda engine: engine.account_lifecycle_service.create_plaid_ach_relationship(
                alpaca_account_id=engine.funded_50000_alpaca_account_id,
                cognito_user_id=engine.funded_50000_cognito_user_id,
                processor_token="processor-token",
            ),
            "ACCOUNT_LIFECYCLE_CREATE_PLAID_ACH_RELATIONSHIP_FAILED",
        ),
        (
            lambda engine: engine.account_lifecycle_service.delete_ach_relationship(
                engine.funded_50000_alpaca_account_id,
                engine.funded_50000_cognito_user_id,
                str(uuid.uuid4()),
            ),
            "ACCOUNT_LIFECYCLE_DELETE_ACH_RELATIONSHIP_FAILED",
        ),
        (
            lambda engine: engine.account_lifecycle_service.create_ach_transfer(
                alpaca_account_id=engine.funded_50000_alpaca_account_id,
                cognito_user_id=engine.funded_50000_cognito_user_id,
                amount="10.00",
                direction="INCOMING",
                timing="IMMEDIATE",
                relationship_id=str(uuid.uuid4()),
            ),
            "ACCOUNT_LIFECYCLE_CREATE_ACH_TRANSFER_REQUEST_FAILED",
        ),
        (
            lambda engine: engine.account_lifecycle_service.get_transfers(
                alpaca_account_id=engine.funded_50000_alpaca_account_id,
                cognito_user_id=engine.funded_50000_cognito_user_id,
                offset=-1,
            ),
            "ACCOUNT_LIFECYCLE_GET_TRANSFERS_FAILED",
        ),
        (
            lambda engine: engine.account_lifecycle_service.cancel_transfer(
                alpaca_account_id=engine.funded_50000_alpaca_account_id,
                cognito_user_id=engine.funded_50000_cognito_user_id,
                transfer_id=str(uuid.uuid4()),
            ),
            "ACCOUNT_LIFECYCLE_CANCEL_TRANSFER_FAILED",
        ),
    ],
)
def test_real_alpaca_wrapper_errors_are_translated(
    test_engine: TestEngine,
    call_service,
    expected_code: str,
) -> None:
    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        call_service(test_engine)

    _assert_service_error(exc_info, expected_code)

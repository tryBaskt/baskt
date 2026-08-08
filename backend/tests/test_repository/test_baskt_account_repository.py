from uuid import uuid4

import pytest

from domain.baskt_account_domain import (
    AgreementData,
    BasktAccount,
    ContactData,
    DisclosuresData,
    IdentityData,
)
from repository.baskt_account_repository import BasktAccountRepository
from repository.baskt_account_repository import (
    BasktAccountBadGatewayError,
    BasktAccountNotFoundError,
    BasktAccountUnprocessableEntityError,
)


def _account(test_user) -> BasktAccount:
    unique_suffix = uuid4().hex
    return BasktAccount(
        cognito_user_id=test_user.cognito_user_id,
        display_name=f"Repository User {unique_suffix[:8]}",
        description="Original description",
        alpaca_account_id=test_user.alpaca_account_id,
        alpaca_account_number="ABC123",
        agreements_data=[
            AgreementData(
                agreement="customer_agreement",
                signed_at="2024-01-01T00:00:00+00:00",
                ip_address="127.0.0.1",
            )
        ],
        disclosures_data=DisclosuresData(immediate_family_exposed=False),
        identity_data=IdentityData(
            given_name="Repo",
            family_name="User",
            country_of_tax_residence="USA",
        ),
        contact_data=ContactData(
            email_address=f"repo_{unique_suffix}@example.com",
            phone_number=None,
            street_address=["1 Test St"],
            unit=None,
            city="New York",
            state="NY",
            postal_code="10001",
            country="USA",
        ),
    )


@pytest.mark.integration
def test_baskt_account_repository_write_get_update_and_delete(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    account = _account(test_user_1)
    cognito_user_id = account.cognito_user_id
    original_item = baskt_account_repository.dynamodb.get_item(
        key={"cognito_user_id": cognito_user_id}
    )

    try:
        baskt_account_repository.write_baskt_account(account)

        assert (
            baskt_account_repository.is_exists_display_name(account.display_name)
            is True
        )
        loaded = baskt_account_repository.get_baskt_account(cognito_user_id)
        assert loaded.display_name == account.display_name
        assert loaded.contact_data.email_address == account.contact_data.email_address
        assert baskt_account_repository.get_display_name(cognito_user_id) == (
            account.display_name
        )

        updated_display_name = f"Updated Repo User {uuid4().hex[:8]}"
        updated_email = f"updated_{uuid4().hex}@example.com"
        baskt_account_repository.update_display_name(
            cognito_user_id,
            updated_display_name,
        )
        baskt_account_repository.update_description(
            cognito_user_id,
            "Updated description",
        )
        baskt_account_repository.update_baskt_account(
            cognito_user_id,
            ContactData(
                email_address=updated_email,
                phone_number=None,
                street_address=["2 Test St"],
                unit=None,
                city="Boston",
                state="MA",
                postal_code="02108",
                country="USA",
            ),
        )
        updated = baskt_account_repository.get_baskt_account(cognito_user_id)
        assert updated.display_name == updated_display_name
        assert updated.description == "Updated description"
        assert updated.contact_data.email_address == updated_email
    finally:
        if original_item is None:
            baskt_account_repository.delete_baskt_account(cognito_user_id)
        else:
            baskt_account_repository.dynamodb.put_item(original_item)

    if original_item is None:
        assert (
            baskt_account_repository.dynamodb.get_item(
                key={"cognito_user_id": cognito_user_id}
            )
            is None
        )
    else:
        restored = baskt_account_repository.dynamodb.get_item(
            key={"cognito_user_id": cognito_user_id}
        )
        assert restored == original_item


@pytest.mark.integration
def test_baskt_account_repository_missing_and_invalid_paths(
    baskt_account_repository: BasktAccountRepository,
) -> None:
    missing_cognito_user_id = f"missing-repository-user-{uuid4()}"

    with pytest.raises(BasktAccountNotFoundError):
        baskt_account_repository.get_baskt_account(missing_cognito_user_id)

    with pytest.raises(BasktAccountNotFoundError):
        baskt_account_repository.get_display_name(missing_cognito_user_id)

    with pytest.raises(BasktAccountUnprocessableEntityError):
        baskt_account_repository.is_exists_display_name("   ")

    with pytest.raises(BasktAccountUnprocessableEntityError):
        baskt_account_repository.update_baskt_account(
            missing_cognito_user_id,
            {"not": "a supported dataclass"},
        )

    with pytest.raises(BasktAccountBadGatewayError):
        baskt_account_repository.update_display_name(
            missing_cognito_user_id,
            f"Missing User {uuid4().hex[:8]}",
        )

    with pytest.raises(BasktAccountBadGatewayError):
        baskt_account_repository.update_description(
            missing_cognito_user_id,
            "missing account description",
        )


@pytest.mark.integration
def test_baskt_account_repository_deserialization_errors_are_wrapped(
    baskt_account_repository: BasktAccountRepository,
) -> None:
    malformed_cognito_user_id = f"malformed-repository-user-{uuid4()}"
    blank_display_name_cognito_user_id = f"blank-display-repository-user-{uuid4()}"

    try:
        baskt_account_repository.dynamodb.put_item(
            {
                "cognito_user_id": malformed_cognito_user_id,
                "display_name": "Malformed Repository User",
            }
        )
        with pytest.raises(BasktAccountUnprocessableEntityError):
            baskt_account_repository.get_baskt_account(malformed_cognito_user_id)

        baskt_account_repository.dynamodb.put_item(
            {
                "cognito_user_id": blank_display_name_cognito_user_id,
                "display_name": "   ",
            }
        )
        with pytest.raises(BasktAccountUnprocessableEntityError):
            baskt_account_repository.get_display_name(
                blank_display_name_cognito_user_id
            )
    finally:
        for cognito_user_id in (
            malformed_cognito_user_id,
            blank_display_name_cognito_user_id,
        ):
            baskt_account_repository.dynamodb.delete_item(
                key={"cognito_user_id": cognito_user_id}
            )

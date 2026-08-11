from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from domain.baskt_account_domain import ContactData, DisclosuresData, IdentityData
from repository.baskt_account_repository import (
    BasktAccountNotFoundError,
    BasktAccountRepository,
    BasktAccountUnprocessableEntityError,
)


"""
These tests exercise the non-mocked BasktAccountRepository paths against the
configured test DynamoDB table.

Coverage goals:
- is_exists_display_name(): query the display_name index for both an existing
  account display name and a unique missing display name.
- get_baskt_account(): load the env-backed test account successfully, then
  assert a missing Cognito user ID raises BasktAccountNotFoundError.
- get_display_name(): fetch only the display_name projection for an existing
  account, then assert a missing account raises BasktAccountNotFoundError.
- update_display_name(): update and read back display_name successfully, then
  assert an empty display name raises BasktAccountUnprocessableEntityError.
- update_description(): update and read back description successfully.
- update_baskt_account(): replace ContactData, IdentityData, and
  DisclosuresData successfully, then pass an unserializable value for each
  section to assert BasktAccountUnprocessableEntityError.

The update tests save the original env-backed account before writing and restore
it in finally blocks so the shared integration account is left as it was found.
"""


@pytest.mark.integration
def test_baskt_account_repository_is_exists_display_name_true_and_false(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Return true for an existing display name and false for a missing one."""
    account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )

    assert baskt_account_repository.is_exists_display_name(account.display_name)
    assert not baskt_account_repository.is_exists_display_name(
        f"missing-display-name-{uuid4()}"
    )


@pytest.mark.integration
def test_baskt_account_repository_get_baskt_account_success_and_error(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Return an existing Baskt account and raise for a missing account."""
    account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )

    assert account.cognito_user_id == test_user_1.cognito_user_id
    assert account.alpaca_account_id == test_user_1.alpaca_account_id
    with pytest.raises(BasktAccountNotFoundError):
        baskt_account_repository.get_baskt_account(
            cognito_user_id=f"missing-baskt-account-{uuid4()}"
        )


@pytest.mark.integration
def test_baskt_account_repository_get_display_name_success_and_error(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Return an existing display name and raise for a missing account."""
    account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )

    assert (
        baskt_account_repository.get_display_name(
            cognito_user_id=test_user_1.cognito_user_id
        )
        == account.display_name
    )
    with pytest.raises(BasktAccountNotFoundError):
        baskt_account_repository.get_display_name(
            cognito_user_id=f"missing-display-name-account-{uuid4()}"
        )


@pytest.mark.integration
def test_baskt_account_repository_update_display_name_success_and_unprocessable(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Update display_name successfully and reject an empty display name."""
    original_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    new_display_name = f"tests-v2-display-{uuid4().hex[:12]}"

    try:
        baskt_account_repository.update_display_name(
            cognito_user_id=test_user_1.cognito_user_id,
            display_name=new_display_name,
        )
        assert (
            baskt_account_repository.get_display_name(
                cognito_user_id=test_user_1.cognito_user_id
            )
            == new_display_name
        )

        with pytest.raises(BasktAccountUnprocessableEntityError):
            baskt_account_repository.update_display_name(
                cognito_user_id=test_user_1.cognito_user_id,
                display_name=" ",
            )
    finally:
        baskt_account_repository.write_baskt_account(original_account)


@pytest.mark.integration
def test_baskt_account_repository_update_description_success(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Update description successfully for an existing Baskt account."""
    original_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    new_description = f"tests-v2-description-{uuid4().hex[:12]}"

    try:
        baskt_account_repository.update_description(
            cognito_user_id=test_user_1.cognito_user_id,
            description=new_description,
        )
        assert (
            baskt_account_repository.get_baskt_account(
                cognito_user_id=test_user_1.cognito_user_id
            ).description
            == new_description
        )
    finally:
        baskt_account_repository.write_baskt_account(original_account)


@pytest.mark.integration
def test_baskt_account_repository_update_contact_data_success_and_unprocessable(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Update ContactData successfully and reject unserializable ContactData."""
    original_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    updated_contact_data = replace(
        original_account.contact_data,
        city=f"tests-v2-city-{uuid4().hex[:8]}",
    )
    invalid_contact_data = ContactData(
        email_address=object(),
        phone_number=original_account.contact_data.phone_number,
        street_address=original_account.contact_data.street_address,
        unit=original_account.contact_data.unit,
        city=original_account.contact_data.city,
        state=original_account.contact_data.state,
        postal_code=original_account.contact_data.postal_code,
        country=original_account.contact_data.country,
    )

    try:
        baskt_account_repository.update_baskt_account(
            cognito_user_id=test_user_1.cognito_user_id,
            updated_data=updated_contact_data,
        )
        assert (
            baskt_account_repository.get_baskt_account(
                cognito_user_id=test_user_1.cognito_user_id
            ).contact_data.city
            == updated_contact_data.city
        )

        with pytest.raises(BasktAccountUnprocessableEntityError):
            baskt_account_repository.update_baskt_account(
                cognito_user_id=test_user_1.cognito_user_id,
                updated_data=invalid_contact_data,
            )
    finally:
        baskt_account_repository.write_baskt_account(original_account)


@pytest.mark.integration
def test_baskt_account_repository_update_identity_data_success_and_unprocessable(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Update IdentityData successfully and reject unserializable IdentityData."""
    original_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    updated_identity_data = replace(
        original_account.identity_data,
        given_name=f"tests-v2-given-{uuid4().hex[:8]}",
    )
    invalid_identity_data = IdentityData(
        given_name=object(),
        family_name=original_account.identity_data.family_name,
        country_of_tax_residence=(
            original_account.identity_data.country_of_tax_residence
        ),
    )

    try:
        baskt_account_repository.update_baskt_account(
            cognito_user_id=test_user_1.cognito_user_id,
            updated_data=updated_identity_data,
        )
        assert (
            baskt_account_repository.get_baskt_account(
                cognito_user_id=test_user_1.cognito_user_id
            ).identity_data.given_name
            == updated_identity_data.given_name
        )

        with pytest.raises(BasktAccountUnprocessableEntityError):
            baskt_account_repository.update_baskt_account(
                cognito_user_id=test_user_1.cognito_user_id,
                updated_data=invalid_identity_data,
            )
    finally:
        baskt_account_repository.write_baskt_account(original_account)


@pytest.mark.integration
def test_baskt_account_repository_update_disclosures_data_success_and_unprocessable(
    baskt_account_repository: BasktAccountRepository,
    test_user_1,
) -> None:
    """Update DisclosuresData successfully and reject unserializable DisclosuresData."""
    original_account = baskt_account_repository.get_baskt_account(
        cognito_user_id=test_user_1.cognito_user_id
    )
    updated_disclosures_data = replace(
        original_account.disclosures_data,
        immediate_family_exposed=(
            not original_account.disclosures_data.immediate_family_exposed
        ),
    )
    invalid_disclosures_data = DisclosuresData(
        immediate_family_exposed=object(),
        is_control_person=original_account.disclosures_data.is_control_person,
        is_affiliated_exchange_or_finra=(
            original_account.disclosures_data.is_affiliated_exchange_or_finra
        ),
        is_politically_exposed=(
            original_account.disclosures_data.is_politically_exposed
        ),
        employment_status=original_account.disclosures_data.employment_status,
        employer_name=original_account.disclosures_data.employer_name,
        employer_address=original_account.disclosures_data.employer_address,
        employment_position=original_account.disclosures_data.employment_position,
    )

    try:
        baskt_account_repository.update_baskt_account(
            cognito_user_id=test_user_1.cognito_user_id,
            updated_data=updated_disclosures_data,
        )
        assert (
            baskt_account_repository.get_baskt_account(
                cognito_user_id=test_user_1.cognito_user_id
            ).disclosures_data.immediate_family_exposed
            == updated_disclosures_data.immediate_family_exposed
        )

        with pytest.raises(BasktAccountUnprocessableEntityError):
            baskt_account_repository.update_baskt_account(
                cognito_user_id=test_user_1.cognito_user_id,
                updated_data=invalid_disclosures_data,
            )
    finally:
        baskt_account_repository.write_baskt_account(original_account)

from __future__ import annotations

import os
from pathlib import Path
import sys
import uuid

from dotenv import load_dotenv
import pytest

repo_root = Path(__file__).resolve().parents[4]
backend_dir = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from clients.cognito_client import (
    CognitoClient,
    CognitoClientCognitoUserNotFound,
    CognitoClientError,
    CognitoClientUserAlreadyExists,
)
from core import deps as app_deps
from core.config import get_settings

load_dotenv(repo_root / ".env")
get_settings.cache_clear()


def _test_user_alpaca_account_id(number: int) -> str:
    variable_name = f"{get_settings().env.upper()}_TEST_USER_{number}_ALPACA_ACCOUNT_ID"
    value = os.getenv(variable_name, "").strip()
    if not value:
        raise RuntimeError(f"{variable_name} is required for Cognito client tests.")
    return value


def _test_user_cognito_user_id(number: int) -> str:
    variable_name = f"{get_settings().env.upper()}_TEST_USER_{number}_COGNITO_USER_ID"
    value = os.getenv(variable_name, "").strip()
    if not value:
        raise RuntimeError(f"{variable_name} is required for Cognito client tests.")
    return value


def _unique_account_data() -> dict:
    unique_suffix = uuid.uuid4().hex
    return {
        "contact": {
            "email_address": f"baskt_cognito_client_test_{unique_suffix}@example.com",
        },
        "identity": {
            "given_name": "Cognito",
            "family_name": "Tester",
        },
    }


def _password() -> str:
    return f"Test_9aA{uuid.uuid4().hex[:16]}"


@pytest.fixture(scope="module")
def cognito_client() -> CognitoClient:
    app_deps.get_boto3_session.cache_clear()
    app_deps.get_cognito_idp_client_cached.cache_clear()
    app_deps.get_cognito_client.cache_clear()
    return app_deps.get_cognito_client()


@pytest.fixture()
def created_cognito_user(cognito_client: CognitoClient):
    account_data = _unique_account_data()
    cognito_user_id = cognito_client.create_cognito_user(
        account_data=account_data,
        alpaca_account_id=str(uuid.uuid4()),
        alpaca_account_number=f"ACCT{uuid.uuid4().hex[:8].upper()}",
        password=_password(),
    )
    yield cognito_user_id, account_data

    try:
        cognito_client.delete_cognito_user(cognito_user_id=cognito_user_id)
    except CognitoClientCognitoUserNotFound:
        pass


def test_cognito_client_formats_cognito_user_response(
    cognito_client: CognitoClient,
) -> None:
    """Format a real AWS Cognito admin_get_user response."""
    cognito_user_id = _test_user_cognito_user_id(1)
    alpaca_account_id = _test_user_alpaca_account_id(1)

    raw_response = cognito_client.cognito_client.admin_get_user(
        UserPoolId=cognito_client.user_pool_id,
        Username=cognito_user_id,
    )
    formatted = cognito_client._format_cognito_user_response(raw_response)

    assert formatted["cognito_user_id"] == raw_response["Username"]
    assert formatted["alpaca_account_id"] == alpaca_account_id
    assert formatted["alpaca_account_number"]
    assert formatted["email_address"]
    assert formatted["cognito_enabled_status"] == bool(raw_response["Enabled"])
    assert formatted["cognito_confirmation_status"] == raw_response["UserStatus"]
    assert formatted["created_at"] == raw_response["UserCreateDate"]
    assert formatted["updated_at"] == raw_response["UserLastModifiedDate"]
    assert formatted["attributes"]["email"] == formatted["email_address"]


def test_cognito_client_create_user_rejects_missing_account_data(
    cognito_client: CognitoClient,
) -> None:
    """Reject Cognito user creation before AWS when required account fields are missing."""
    with pytest.raises(CognitoClientError) as exc_info:
        cognito_client.create_cognito_user(
            account_data={"contact": {}},
            alpaca_account_id=str(uuid.uuid4()),
            alpaca_account_number="ABC123",
            password=_password(),
        )

    assert exc_info.value.code == "COGNITO_CREATE_USER_INVALID_ACCOUNT_DATA"


@pytest.mark.integration
def test_cognito_client_create_get_exists_duplicate_and_delete_user(
    cognito_client: CognitoClient,
) -> None:
    """Create, fetch, detect duplicate, and delete a real AWS Cognito user."""
    account_data = _unique_account_data()
    email_address = account_data["contact"]["email_address"]
    cognito_user_id = None

    try:
        cognito_user_id = cognito_client.create_cognito_user(
            account_data=account_data,
            alpaca_account_id=str(uuid.uuid4()),
            alpaca_account_number=f"ACCT{uuid.uuid4().hex[:8].upper()}",
            password=_password(),
        )

        assert cognito_user_id
        assert cognito_client.is_exists_cognito_user(cognito_user_id) is True

        user_by_id = cognito_client.get_cognito_user_by_cognito_user_id(
            cognito_user_id=cognito_user_id,
        )
        user_by_email = cognito_client.get_cognito_user_by_email_address(
            email_address=email_address,
        )

        assert user_by_id["cognito_user_id"] == cognito_user_id
        assert user_by_email["cognito_user_id"] == cognito_user_id
        assert user_by_id["email_address"] == email_address
        assert user_by_email["email_address"] == email_address

        with pytest.raises(CognitoClientUserAlreadyExists) as duplicate_error:
            cognito_client.create_cognito_user(
                account_data=account_data,
                alpaca_account_id=str(uuid.uuid4()),
                alpaca_account_number=f"ACCT{uuid.uuid4().hex[:8].upper()}",
                password=_password(),
            )
        assert duplicate_error.value.code == "COGNITO_USER_ALREADY_EXISTS"

        cognito_client.delete_cognito_user(cognito_user_id=cognito_user_id)
        assert cognito_client.is_exists_cognito_user(cognito_user_id) is False
        cognito_user_id = None
    finally:
        if cognito_user_id:
            try:
                cognito_client.delete_cognito_user(cognito_user_id=cognito_user_id)
            except CognitoClientCognitoUserNotFound:
                pass


@pytest.mark.integration
def test_cognito_client_not_found_paths_use_real_cognito(
    cognito_client: CognitoClient,
) -> None:
    """Verify real AWS Cognito not-found behavior for lookup, existence, and delete."""
    missing_cognito_user_id = f"missing-cognito-{uuid.uuid4().hex}"
    missing_email = f"missing_cognito_{uuid.uuid4().hex}@example.com"

    assert cognito_client.is_exists_cognito_user(missing_cognito_user_id) is False

    with pytest.raises(CognitoClientCognitoUserNotFound) as id_error:
        cognito_client.get_cognito_user_by_cognito_user_id(
            cognito_user_id=missing_cognito_user_id,
        )
    assert id_error.value.code == "COGNITO_USER_NOT_FOUND"

    with pytest.raises(CognitoClientCognitoUserNotFound) as email_error:
        cognito_client.get_cognito_user_by_email_address(email_address=missing_email)
    assert email_error.value.code == "COGNITO_USER_NOT_FOUND"

    with pytest.raises(CognitoClientCognitoUserNotFound) as delete_error:
        cognito_client.delete_cognito_user(cognito_user_id=missing_cognito_user_id)
    assert delete_error.value.code == "COGNITO_USER_NOT_FOUND"

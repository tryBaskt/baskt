from __future__ import annotations

from datetime import datetime, timezone
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


def test_cognito_client_error_classes_set_codes() -> None:
    error = CognitoClientError("failed", code="CUSTOM_COGNITO_CODE")
    assert str(error) == "failed"
    assert error.code == "CUSTOM_COGNITO_CODE"

    duplicate_error = CognitoClientUserAlreadyExists(
        identifier="duplicate@example.com",
        identifier_type="email_address",
    )
    assert duplicate_error.code == "COGNITO_USER_ALREADY_EXISTS"

    not_found_error = CognitoClientCognitoUserNotFound(
        identifier="missing-user",
        identifier_type="cognito_user_id",
    )
    assert not_found_error.code == "COGNITO_USER_NOT_FOUND"


def test_cognito_client_formats_cognito_user_response(
    cognito_client: CognitoClient,
) -> None:
    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    updated_at = datetime(2024, 1, 2, tzinfo=timezone.utc)

    formatted = cognito_client._format_cognito_user_response(
        {
            "Username": "cognito-user-id",
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": created_at,
            "UserLastModifiedDate": updated_at,
            "UserAttributes": [
                {"Name": "email", "Value": "user@example.com"},
                {"Name": "custom:alpaca_acct_id", "Value": "alpaca-id"},
                {"Name": "custom:alpaca_acct_num", "Value": "ABC123"},
            ],
        }
    )

    assert formatted["cognito_user_id"] == "cognito-user-id"
    assert formatted["alpaca_account_id"] == "alpaca-id"
    assert formatted["alpaca_account_number"] == "ABC123"
    assert formatted["email_address"] == "user@example.com"
    assert formatted["cognito_enabled_status"] is True
    assert formatted["cognito_confirmation_status"] == "CONFIRMED"
    assert formatted["created_at"] == created_at
    assert formatted["updated_at"] == updated_at
    assert formatted["attributes"]["email"] == "user@example.com"


def test_cognito_client_create_user_rejects_missing_account_data(
    cognito_client: CognitoClient,
) -> None:
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

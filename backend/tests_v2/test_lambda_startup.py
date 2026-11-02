"""Cold-start secret resolution tests; no AWS or broker calls."""

import os
from unittest.mock import Mock, patch

import pytest

from deployables.backend_lambda import lambda_startup


def secret_environment():
    return {
        f"{key}_SECRET_ARN": f"arn:example:{key}"
        for key in lambda_startup.SECRET_ENVIRONMENT_KEYS
    }


def test_startup_resolves_secrets_before_replacing_process():
    environ = secret_environment()
    client = Mock()
    client.get_secret_value.side_effect = [
        {"SecretString": "test-key"},
        {"SecretString": "test-secret"},
    ]

    def check_exec(command, args):
        assert environ["SANDBOX_ALPACA_BROKER_API_KEY"] == "test-key"
        assert environ["SANDBOX_ALPACA_BROKER_API_SECRET"] == "test-secret"
        assert command == "uvicorn"
        assert args == ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

    with patch.object(os, "environ", environ), \
         patch.object(lambda_startup.boto3, "client", return_value=client), \
         patch.object(os, "execvp", side_effect=check_exec) as execvp:
        lambda_startup.main()

    execvp.assert_called_once()
    assert [call.kwargs["SecretId"] for call in client.get_secret_value.call_args_list] == [
        environ[f"{key}_SECRET_ARN"] for key in lambda_startup.SECRET_ENVIRONMENT_KEYS
    ]


@pytest.mark.parametrize("second_value", [None, "", "  ", b"binary-secret"])
def test_invalid_secret_does_not_start_api_or_partially_load_environment(second_value):
    environ = secret_environment()
    original = dict(environ)
    client = Mock()
    client.get_secret_value.side_effect = [
        {"SecretString": "test-key"},
        {"SecretString": second_value},
    ]
    with patch.object(os, "environ", environ), \
         patch.object(lambda_startup.boto3, "client", return_value=client), \
         patch.object(os, "execvp") as execvp:
        with pytest.raises(RuntimeError, match="nonempty string"):
            lambda_startup.main()
    assert environ == original
    execvp.assert_not_called()


def test_secret_fetch_failure_does_not_start_api():
    environ = secret_environment()
    client = Mock()
    client.get_secret_value.side_effect = RuntimeError("secret unavailable")
    with patch.object(os, "environ", environ), \
         patch.object(lambda_startup.boto3, "client", return_value=client), \
         patch.object(os, "execvp") as execvp:
        with pytest.raises(RuntimeError, match="secret unavailable"):
            lambda_startup.main()
    execvp.assert_not_called()

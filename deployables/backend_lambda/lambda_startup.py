"""Resolve runtime secrets before starting FastAPI in the Lambda container.

Only secret ARNs are stored in Lambda configuration. Values are fetched using
the execution role at cold start and never written to stdout or the image.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from typing import Any

import boto3
from botocore.config import Config


SECRET_ENVIRONMENT_KEYS = (
    "SANDBOX_ALPACA_BROKER_API_KEY",
    "SANDBOX_ALPACA_BROKER_API_SECRET",
)


def load_runtime_secrets(
    environ: MutableMapping[str, str], client: Any,
) -> None:
    """Load the two required plain-string secrets, failing closed on errors."""
    values = {}
    for key in SECRET_ENVIRONMENT_KEYS:
        secret_arn = environ[f"{key}_SECRET_ARN"]
        response = client.get_secret_value(SecretId=secret_arn)
        value = response.get("SecretString")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Runtime secret for {key} must be a nonempty string")
        values[key] = value
    # Don't leave a partially configured environment if the second fetch fails.
    environ.update(values)


def main() -> None:
    client = boto3.client(
        "secretsmanager",
        config=Config(
            connect_timeout=2,
            read_timeout=3,
            retries={"total_max_attempts": 2, "mode": "standard"},
        ),
    )
    load_runtime_secrets(os.environ, client)
    os.execvp(
        "uvicorn",
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
    )


if __name__ == "__main__":
    main()

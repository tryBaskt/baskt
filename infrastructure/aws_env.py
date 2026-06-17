"""Utilities for loading AWS credentials from the workspace .env file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_AWS_ENV_KEYS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_DEFAULT_REGION",
    "AWS_REGION",
)


def _find_workspace_env(start: Path) -> Optional[Path]:
    for parent in [start, *start.parents]:
        candidate = parent / ".env"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        values[key] = value
    return values


def load_aws_env() -> None:
    """Load AWS-related environment variables from the nearest workspace .env file."""
    env_path = _find_workspace_env(Path(__file__).resolve())
    if env_path is None:
        return

    env_values = _parse_dotenv(env_path)
    for key in _AWS_ENV_KEYS:
        if key in env_values and env_values[key] != "":
            os.environ[key] = env_values[key]

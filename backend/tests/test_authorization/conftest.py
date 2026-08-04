from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

backend_dir = Path(__file__).resolve().parents[2]
repo_root = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from core.config import get_settings
from core.logging_config import configure_audit_console_logging, configure_cloudwatch_logging


def pytest_configure(config) -> None:
    config.option.log_cli = True
    config.option.log_cli_level = "WARNING"
    config.option.log_cli_format = "%(asctime)s %(levelname)s %(name)s %(message)s"
    config.option.log_cli_date_format = "%Y-%m-%dT%H:%M:%S%z"
    configure_audit_console_logging(level=logging.WARNING, stream=sys.__stderr__)
    load_dotenv(repo_root / ".env")
    get_settings.cache_clear()
    settings = get_settings()
    configure_cloudwatch_logging(settings)

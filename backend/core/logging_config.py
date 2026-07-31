# backend/core/logging_config.py

from __future__ import annotations

import logging
import os
import socket
import sys
from typing import Any, Optional

from core.config import Settings


AUDIT_LOGGER_NAME = "baskt.audit"


class CloudWatchLogsHandler(logging.Handler):
    """Minimal CloudWatch Logs handler for local/backend runtime logs."""

    def __init__(
        self,
        *,
        log_group_name: str,
        log_stream_name: str,
        logs_client: Any,
    ) -> None:
        super().__init__()
        self.log_group_name = log_group_name
        self.log_stream_name = log_stream_name
        self.logs_client = logs_client
        self.sequence_token: Optional[str] = None
        self._ensure_log_stream()

    def _ensure_log_stream(self) -> None:
        try:
            self.logs_client.create_log_stream(
                logGroupName=self.log_group_name,
                logStreamName=self.log_stream_name,
            )
        except self.logs_client.exceptions.ResourceAlreadyExistsException:
            pass

        response = self.logs_client.describe_log_streams(
            logGroupName=self.log_group_name,
            logStreamNamePrefix=self.log_stream_name,
            limit=1,
        )
        streams = response.get("logStreams", [])
        if streams and streams[0].get("logStreamName") == self.log_stream_name:
            self.sequence_token = streams[0].get("uploadSequenceToken")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event = {
                "timestamp": int(record.created * 1000),
                "message": self.format(record),
            }
            kwargs: dict[str, Any] = {
                "logGroupName": self.log_group_name,
                "logStreamName": self.log_stream_name,
                "logEvents": [event],
            }
            if self.sequence_token:
                kwargs["sequenceToken"] = self.sequence_token

            response = self.logs_client.put_log_events(**kwargs)
            self.sequence_token = response.get("nextSequenceToken")
        except Exception as err:
            error_response = getattr(err, "response", {})
            if error_response.get("Error", {}).get("Code") == "InvalidSequenceTokenException":
                self._ensure_log_stream()
                self.emit(record)
                return
            self.handleError(record)


def _build_logs_client(settings: Settings) -> Any:
    import boto3

    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs.update(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.client("logs", **kwargs)


def _default_log_stream_name(settings: Settings, suffix: str) -> str:
    host = socket.gethostname()
    process_id = os.getpid()
    return f"{settings.app_name}/{host}/{process_id}/{suffix}"


def _log_stream_name(settings: Settings, suffix: str) -> str:
    if settings.cloudwatch_log_stream_name:
        return f"{settings.cloudwatch_log_stream_name}/{suffix}"
    return _default_log_stream_name(settings, suffix)


def _has_cloudwatch_handler(logger: logging.Logger, log_group_name: str) -> bool:
    return any(
        isinstance(handler, CloudWatchLogsHandler)
        and handler.log_group_name == log_group_name
        for handler in logger.handlers
    )


def _has_audit_console_handler(logger: logging.Logger) -> bool:
    return any(getattr(handler, "_baskt_audit_console_handler", False) for handler in logger.handlers)


def configure_audit_console_logging(
    *,
    level: int = logging.INFO,
    stream: Any = sys.stderr,
) -> None:
    """Make Baskt audit logs visible in local processes and focused tests."""
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    logger.setLevel(min(logger.level or level, level))

    if _has_audit_console_handler(logger):
        return

    handler = logging.StreamHandler(stream)
    handler._baskt_audit_console_handler = True  # type: ignore[attr-defined]
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)


def _attach_cloudwatch_handler(
    *,
    logger: logging.Logger,
    settings: Settings,
    logs_client: Any,
    log_group_name: str,
    stream_suffix: str,
    level: int,
) -> None:
    if _has_cloudwatch_handler(logger, log_group_name):
        return

    handler = CloudWatchLogsHandler(
        log_group_name=log_group_name,
        log_stream_name=_log_stream_name(settings, stream_suffix),
        logs_client=logs_client,
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)


def configure_cloudwatch_logging(settings: Settings) -> None:
    """
    Attach CloudWatch delivery for local/backend logs when explicitly enabled.

    AWS-hosted ECS/Lambda runtimes usually ship stdout/stderr via platform log
    drivers. This handler is for local/dev or non-ECS process logging.
    """
    configure_audit_console_logging()

    if not settings.cloudwatch_logs_enabled:
        return

    logs_client = _build_logs_client(settings)

    for logger_name in ("uvicorn.error", "uvicorn.access"):
        _attach_cloudwatch_handler(
            logger=logging.getLogger(logger_name),
            settings=settings,
            logs_client=logs_client,
            log_group_name=settings.backend_application_log_group_name,
            stream_suffix=logger_name.replace(".", "-"),
            level=logging.INFO,
        )

    _attach_cloudwatch_handler(
        logger=logging.getLogger("baskt.audit"),
        settings=settings,
        logs_client=logs_client,
        log_group_name=settings.backend_audit_log_group_name,
        stream_suffix="audit",
        level=logging.INFO,
    )

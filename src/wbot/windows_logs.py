from __future__ import annotations

import logging
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path


def redact(text: str, secrets: Iterable[str]) -> str:
    sanitized = text
    values = sorted({secret for secret in secrets if secret}, key=len, reverse=True)
    for secret in values:
        sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized


class _RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), self._secrets)
        record.args = ()
        return True


def configure_rotating_log(
    path: Path,
    secrets: Iterable[str],
    *,
    logger_name: str = "wbot.windows",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if backup_count < 0:
        raise ValueError("backup_count must not be negative")
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for existing in tuple(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(_RedactingFilter(secrets))
    logger.addHandler(handler)
    return logger

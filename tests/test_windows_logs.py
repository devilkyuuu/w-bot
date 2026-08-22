from __future__ import annotations

import logging
from pathlib import Path

from wbot.windows_logs import configure_rotating_log, redact


def test_redact_removes_exact_secrets_and_bot_api_urls() -> None:
    token = "dummy-token-value-that-must-not-leak"
    api_hash = "0123456789abcdef0123456789abcdef"
    text = (
        f"POST https://api.telegram.org/bot{token}/logOut "
        f"hash={api_hash} chat_id=-100123"
    )

    sanitized = redact(text, (token, api_hash))

    assert token not in sanitized
    assert api_hash not in sanitized
    assert sanitized == (
        "POST https://api.telegram.org/bot[REDACTED]/logOut "
        "hash=[REDACTED] chat_id=-100123"
    )


def test_rotating_logger_redacts_message_arguments_and_bounds_files(tmp_path: Path) -> None:
    token = "dummy-token-value-that-must-not-leak"
    api_hash = "0123456789abcdef0123456789abcdef"
    path = tmp_path / "controller.log"
    logger = configure_rotating_log(
        path,
        (token, api_hash),
        logger_name="wbot.test.rotating",
        max_bytes=180,
        backup_count=2,
    )

    for index in range(30):
        logger.info("attempt=%d token=%s hash=%s", index, token, api_hash)
    for handler in logger.handlers:
        handler.flush()

    log_files = sorted(tmp_path.glob("controller.log*"))
    combined = "".join(item.read_text(encoding="utf-8") for item in log_files)
    assert 1 <= len(log_files) <= 3
    assert token not in combined
    assert api_hash not in combined
    assert "[REDACTED]" in combined


def test_reconfiguring_same_logger_does_not_duplicate_output(tmp_path: Path) -> None:
    path = tmp_path / "controller.log"
    first = configure_rotating_log(path, (), logger_name="wbot.test.single")
    second = configure_rotating_log(path, (), logger_name="wbot.test.single")

    assert first is second
    assert len(second.handlers) == 1
    second.log(logging.INFO, "one line")
    second.handlers[0].flush()
    assert path.read_text(encoding="utf-8").count("one line") == 1

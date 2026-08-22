from collections.abc import Mapping

import pytest

from wbot.config import ConfigError, Settings


def complete_env() -> dict[str, str]:
    return {
        "BOT_TOKEN": "123456:secret-token",
        "TELEGRAM_API_ID": "12345",
        "TELEGRAM_API_HASH": "api-hash-secret",
        "OWNER_USER_ID": "987654321",
    }


def test_required_values_are_parsed_without_changing_secrets() -> None:
    settings = Settings.from_env(complete_env())

    assert settings.bot_token == "123456:secret-token"
    assert settings.telegram_api_id == 12345
    assert settings.telegram_api_hash == "api-hash-secret"
    assert settings.owner_user_id == 987654321
    assert settings.database_path.as_posix() == "/home/container/wbot.sqlite3"


def test_resource_defaults_match_the_agreed_limits() -> None:
    settings = Settings.from_env(complete_env())

    assert settings.local_api_base_url == "http://telegram-api:8081"
    assert settings.max_download_bytes == 1_000_000_000
    assert settings.max_video_seconds == 300
    assert settings.media_tmp_root.as_posix().endswith("/tmp/wbot-media")


@pytest.mark.parametrize(
    "missing_name",
    ["BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "OWNER_USER_ID"],
)
def test_each_required_value_is_rejected_when_missing(missing_name: str) -> None:
    env: Mapping[str, str] = {k: v for k, v in complete_env().items() if k != missing_name}

    with pytest.raises(ConfigError, match=missing_name):
        Settings.from_env(env)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TELEGRAM_API_ID", "not-a-number"),
        ("TELEGRAM_API_ID", "0"),
        ("OWNER_USER_ID", "-1"),
        ("MAX_DOWNLOAD_BYTES", "0"),
        ("MAX_VIDEO_SECONDS", "301"),
    ],
)
def test_invalid_numeric_configuration_is_rejected(name: str, value: str) -> None:
    env = complete_env()
    env[name] = value

    with pytest.raises(ConfigError, match=name):
        Settings.from_env(env)


def test_local_api_url_must_be_internal_http_without_credentials() -> None:
    env = complete_env()
    env["TELEGRAM_LOCAL_API_BASE_URL"] = "https://user:password@example.com"

    with pytest.raises(ConfigError, match="TELEGRAM_LOCAL_API_BASE_URL"):
        Settings.from_env(env)


def test_database_path_can_be_overridden_for_local_deployment() -> None:
    env = complete_env()
    env["DATABASE_PATH"] = "/tmp/custom.sqlite3"

    settings = Settings.from_env(env)

    assert settings.database_path.as_posix() == "/tmp/custom.sqlite3"

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when required runtime configuration is unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    telegram_api_id: int
    telegram_api_hash: str
    owner_user_id: int
    database_url: str
    local_api_base_url: str
    media_tmp_root: Path
    max_download_bytes: int
    max_video_seconds: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        bot_token = _required(env, "BOT_TOKEN")
        telegram_api_id = _positive_int(env, "TELEGRAM_API_ID")
        telegram_api_hash = _required(env, "TELEGRAM_API_HASH")
        owner_user_id = _positive_int(env, "OWNER_USER_ID")
        database_url = _required(env, "DATABASE_URL")

        local_api_base_url = env.get(
            "TELEGRAM_LOCAL_API_BASE_URL", "http://telegram-api:8081"
        ).strip()
        _validate_local_api_url(local_api_base_url)

        media_tmp_root = Path(env.get("MEDIA_TMP_ROOT", "/tmp/wbot-media").strip())
        if not str(media_tmp_root):
            raise ConfigError("MEDIA_TMP_ROOT must not be empty")

        max_download_bytes = _positive_int(
            env, "MAX_DOWNLOAD_BYTES", default=1_000_000_000
        )
        max_video_seconds = _positive_int(env, "MAX_VIDEO_SECONDS", default=300)
        if max_video_seconds > 300:
            raise ConfigError("MAX_VIDEO_SECONDS must not exceed 300")

        return cls(
            bot_token=bot_token,
            telegram_api_id=telegram_api_id,
            telegram_api_hash=telegram_api_hash,
            owner_user_id=owner_user_id,
            database_url=database_url,
            local_api_base_url=local_api_base_url.rstrip("/"),
            media_tmp_root=media_tmp_root,
            max_download_bytes=max_download_bytes,
            max_video_seconds=max_video_seconds,
        )


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _positive_int(env: Mapping[str, str], name: str, *, default: int | None = None) -> int:
    raw = env.get(name)
    if raw is None and default is not None:
        return default
    if raw is None or not raw.strip():
        raise ConfigError(f"{name} is required")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _validate_local_api_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("TELEGRAM_LOCAL_API_BASE_URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or port is None
    ):
        raise ConfigError(
            "TELEGRAM_LOCAL_API_BASE_URL must be an internal HTTP origin with an explicit port"
        )

from __future__ import annotations

import base64
import ctypes
import hmac
import json
import os
import sys
from ctypes import wintypes
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol

from wbot.config import Settings

SETTINGS_VERSION = 1
MAX_DOWNLOAD_BYTES = 700_000_000
MAX_VIDEO_SECONDS = 300
LOCAL_API_BASE_URL = "http://127.0.0.1:8081"
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class WindowsConfigError(ValueError):
    """A sanitized portable-Windows configuration failure."""


@dataclass(frozen=True, slots=True)
class PackagePaths:
    root: Path
    app: Path
    telegram_api: Path
    tools: Path
    data: Path
    logs: Path
    temp: Path
    settings_file: Path
    database: Path
    runtime_file: Path
    stop_file: Path
    ready_file: Path

    @classmethod
    def from_root(cls, root: Path) -> PackagePaths:
        data = root / "data"
        return cls(
            root=root,
            app=root / "app",
            telegram_api=root / "telegram-api",
            tools=root / "tools",
            data=data,
            logs=root / "logs",
            temp=root / "temp",
            settings_file=data / "settings.json",
            database=data / "wbot.sqlite3",
            runtime_file=data / "runtime.json",
            stop_file=data / "stop.signal",
            ready_file=data / "ready.signal",
        )

    def ensure_runtime_directories(self) -> None:
        for directory in (
            self.data,
            self.logs,
            self.temp,
            self.data / "telegram-api",
            self.temp / "telegram-api",
            self.temp / "media",
        ):
            directory.mkdir(parents=True, exist_ok=True)


class SecretProtector(Protocol):
    def protect(self, value: str) -> str: ...

    def unprotect(self, value: str) -> str: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class DpapiProtector:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise WindowsConfigError("Windows secret protection is unavailable")
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    def protect(self, value: str) -> str:
        protected = self._transform(value.encode("utf-8"), protect=True)
        return base64.b64encode(protected).decode("ascii")

    def unprotect(self, value: str) -> str:
        try:
            protected = base64.b64decode(value, validate=True)
        except (ValueError, UnicodeError):
            raise WindowsConfigError("Secret data is invalid") from None
        try:
            return self._transform(protected, protect=False).decode("utf-8")
        except UnicodeDecodeError:
            raise WindowsConfigError("Secret data is invalid") from None

    def _transform(self, value: bytes, *, protect: bool) -> bytes:
        buffer = ctypes.create_string_buffer(value)
        source = _DataBlob(
            len(value),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        result = _DataBlob()
        function = (
            self._crypt32.CryptProtectData
            if protect
            else self._crypt32.CryptUnprotectData
        )
        if not function(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(result),
        ):
            action = "protect" if protect else "read"
            raise WindowsConfigError(f"Windows could not {action} the secret")
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            self._kernel32.LocalFree(ctypes.cast(result.pbData, wintypes.HLOCAL))


@dataclass(frozen=True, slots=True)
class StoredSettings:
    version: int
    telegram_api_id: int
    protected_api_hash: str
    owner_user_id: int
    protected_bot_token: str
    cloud_logout_complete: bool
    max_download_bytes: int
    max_video_seconds: int


class SettingsStore:
    def __init__(self, paths: PackagePaths, protector: SecretProtector) -> None:
        self.paths = paths
        self.protector = protector

    def save(
        self,
        *,
        api_id: int,
        api_hash: str,
        owner_id: int,
        bot_token: str,
    ) -> None:
        _require_positive(api_id, "Telegram API ID")
        _require_positive(owner_id, "Owner user ID")
        clean_hash = _require_secret(api_hash, "Telegram API hash")
        clean_token = _require_secret(bot_token, "Bot token")

        handover_complete = False
        if self.paths.settings_file.exists():
            previous = self._load_stored()
            previous_token = self.protector.unprotect(previous.protected_bot_token)
            if hmac.compare_digest(previous_token, clean_token):
                handover_complete = previous.cloud_logout_complete

        settings = StoredSettings(
            version=SETTINGS_VERSION,
            telegram_api_id=api_id,
            protected_api_hash=self.protector.protect(clean_hash),
            owner_user_id=owner_id,
            protected_bot_token=self.protector.protect(clean_token),
            cloud_logout_complete=handover_complete,
            max_download_bytes=MAX_DOWNLOAD_BYTES,
            max_video_seconds=MAX_VIDEO_SECONDS,
        )
        self._write(settings)

    def load_runtime(self) -> Settings:
        stored = self._load_stored()
        return Settings(
            bot_token=self.protector.unprotect(stored.protected_bot_token),
            telegram_api_id=stored.telegram_api_id,
            telegram_api_hash=self.protector.unprotect(stored.protected_api_hash),
            owner_user_id=stored.owner_user_id,
            database_path=self.paths.database,
            local_api_base_url=LOCAL_API_BASE_URL,
            media_tmp_root=self.paths.temp / "media",
            max_download_bytes=stored.max_download_bytes,
            max_video_seconds=stored.max_video_seconds,
        )

    def cloud_logout_complete(self) -> bool:
        return self._load_stored().cloud_logout_complete

    def mark_cloud_logout_complete(self) -> None:
        self._write(replace(self._load_stored(), cloud_logout_complete=True))

    def _load_stored(self) -> StoredSettings:
        try:
            document = json.loads(self.paths.settings_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise WindowsConfigError("Setup is required. Run Setup Bot.cmd first.") from None
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise WindowsConfigError("Saved settings are invalid. Run setup again.") from None
        if not isinstance(document, dict):
            raise WindowsConfigError("Saved settings are invalid. Run setup again.")
        try:
            stored = StoredSettings(
                version=_exact_int(document["version"]),
                telegram_api_id=_positive_document_int(document["telegram_api_id"]),
                protected_api_hash=_document_string(document["protected_api_hash"]),
                owner_user_id=_positive_document_int(document["owner_user_id"]),
                protected_bot_token=_document_string(document["protected_bot_token"]),
                cloud_logout_complete=_document_bool(document["cloud_logout_complete"]),
                max_download_bytes=_positive_document_int(document["max_download_bytes"]),
                max_video_seconds=_positive_document_int(document["max_video_seconds"]),
            )
        except (KeyError, TypeError, ValueError):
            raise WindowsConfigError("Saved settings are invalid. Run setup again.") from None
        if stored.version != SETTINGS_VERSION:
            raise WindowsConfigError("Saved settings use an unsupported version. Run setup again.")
        if (
            stored.max_download_bytes != MAX_DOWNLOAD_BYTES
            or stored.max_video_seconds != MAX_VIDEO_SECONDS
        ):
            raise WindowsConfigError("Saved settings contain unsupported limits. Run setup again.")
        return stored

    def _write(self, settings: StoredSettings) -> None:
        self.paths.ensure_runtime_directories()
        temporary = self.paths.settings_file.with_name(f"{self.paths.settings_file.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(asdict(settings), handle, ensure_ascii=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.paths.settings_file)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise WindowsConfigError("Settings could not be saved") from None


def _require_positive(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WindowsConfigError(f"{label} must be a positive integer")


def _require_secret(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WindowsConfigError(f"{label} is required")
    return value.strip()


def _exact_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _positive_document_int(value: object) -> int:
    parsed = _exact_int(value)
    if parsed <= 0:
        raise ValueError
    return parsed


def _document_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError
    return value


def _document_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError
    return value

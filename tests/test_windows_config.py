from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wbot.windows_config import (
    DpapiProtector,
    PackagePaths,
    SettingsStore,
    WindowsConfigError,
)


class FakeProtector:
    def protect(self, value: str) -> str:
        return f"protected:{value[::-1]}"

    def unprotect(self, value: str) -> str:
        if not value.startswith("protected:"):
            raise WindowsConfigError("Secret data is invalid")
        return value.removeprefix("protected:")[::-1]


def _save_valid(store: SettingsStore, *, token: str = "123456:valid_token_value") -> None:
    store.save(
        api_id=12345,
        api_hash="0123456789abcdef0123456789abcdef",
        owner_id=98765,
        bot_token=token,
    )


def test_package_paths_are_derived_from_a_root_containing_spaces(tmp_path: Path) -> None:
    root = tmp_path / "My Portable W Bot"

    paths = PackagePaths.from_root(root)
    paths.ensure_runtime_directories()

    assert paths.app == root / "app"
    assert paths.telegram_api == root / "telegram-api"
    assert paths.tools == root / "tools"
    assert paths.settings_file == root / "data" / "settings.json"
    assert paths.database == root / "data" / "wbot.sqlite3"
    assert paths.runtime_file == root / "data" / "runtime.json"
    assert paths.stop_file == root / "data" / "stop.signal"
    assert paths.ready_file == root / "data" / "ready.signal"
    assert paths.data.is_dir()
    assert paths.logs.is_dir()
    assert paths.temp.is_dir()
    assert (paths.data / "telegram-api").is_dir()
    assert (paths.temp / "telegram-api").is_dir()
    assert (paths.temp / "media").is_dir()


def test_settings_are_encrypted_and_load_as_runtime_settings(tmp_path: Path) -> None:
    paths = PackagePaths.from_root(tmp_path / "W Bot")
    store = SettingsStore(paths, FakeProtector())

    _save_valid(store)

    raw = paths.settings_file.read_text(encoding="utf-8")
    document = json.loads(raw)
    assert document == {
        "version": 1,
        "telegram_api_id": 12345,
        "protected_api_hash": "protected:fedcba9876543210fedcba9876543210",
        "owner_user_id": 98765,
        "protected_bot_token": "protected:eulav_nekot_dilav:654321",
        "cloud_logout_complete": False,
        "max_download_bytes": 700_000_000,
        "max_video_seconds": 300,
    }
    assert "123456:valid_token_value" not in raw
    assert "0123456789abcdef0123456789abcdef" not in raw

    runtime = store.load_runtime()
    assert runtime.bot_token == "123456:valid_token_value"
    assert runtime.telegram_api_id == 12345
    assert runtime.telegram_api_hash == "0123456789abcdef0123456789abcdef"
    assert runtime.owner_user_id == 98765
    assert runtime.database_path == paths.database
    assert runtime.local_api_base_url == "http://127.0.0.1:8081"
    assert runtime.media_tmp_root == paths.temp / "media"
    assert runtime.max_download_bytes == 700_000_000
    assert runtime.max_video_seconds == 300


@pytest.mark.parametrize("name", ["api_id", "owner_id"])
@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_numeric_settings_are_rejected(
    tmp_path: Path,
    name: str,
    value: int,
) -> None:
    store = SettingsStore(PackagePaths.from_root(tmp_path), FakeProtector())
    values = {
        "api_id": 12345,
        "api_hash": "hash",
        "owner_id": 98765,
        "bot_token": "token",
    }
    values[name] = value

    with pytest.raises(WindowsConfigError, match="positive integer"):
        store.save(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["api_hash", "bot_token"])
def test_blank_secrets_are_rejected(tmp_path: Path, name: str) -> None:
    store = SettingsStore(PackagePaths.from_root(tmp_path), FakeProtector())
    values = {
        "api_id": 12345,
        "api_hash": "hash",
        "owner_id": 98765,
        "bot_token": "token",
    }
    values[name] = "  "

    with pytest.raises(WindowsConfigError, match="required"):
        store.save(**values)  # type: ignore[arg-type]


def test_malformed_settings_fail_without_echoing_file_content(tmp_path: Path) -> None:
    paths = PackagePaths.from_root(tmp_path)
    paths.ensure_runtime_directories()
    paths.settings_file.write_text('{"protected_bot_token":"top-secret"', encoding="utf-8")
    store = SettingsStore(paths, FakeProtector())

    with pytest.raises(WindowsConfigError) as caught:
        store.load_runtime()

    assert "top-secret" not in str(caught.value)


def test_handover_marker_is_preserved_only_for_the_same_bot_token(tmp_path: Path) -> None:
    paths = PackagePaths.from_root(tmp_path)
    store = SettingsStore(paths, FakeProtector())
    _save_valid(store)
    store.mark_cloud_logout_complete()
    assert store.cloud_logout_complete()

    _save_valid(store)
    assert store.cloud_logout_complete()

    _save_valid(store, token="999999:different_token_value")
    assert not store.cloud_logout_complete()


def test_failed_atomic_replace_preserves_previous_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PackagePaths.from_root(tmp_path)
    store = SettingsStore(paths, FakeProtector())
    _save_valid(store)
    original = paths.settings_file.read_bytes()

    def fail_replace(self: Path, target: Path) -> Path:
        del self, target
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(WindowsConfigError, match="could not be saved"):
        _save_valid(store, token="999999:different_token_value")

    assert paths.settings_file.read_bytes() == original


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI test")
def test_dpapi_round_trip_is_bound_to_windows_and_not_plaintext() -> None:
    protector = DpapiProtector()
    plaintext = "bot secret ☃"

    protected = protector.protect(plaintext)

    assert plaintext not in protected
    assert protector.unprotect(protected) == plaintext

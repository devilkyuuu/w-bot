from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-windows-package.yml"


def _workflow() -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    raw = WORKFLOW.read_text(encoding="utf-8")
    document = cast(dict[str, Any], yaml.load(raw, Loader=yaml.BaseLoader))
    jobs = cast(dict[str, Any], document["jobs"])
    build = cast(dict[str, Any], jobs["build"])
    steps = cast(list[dict[str, Any]], build["steps"])
    return raw, document, steps


def test_workflow_is_manual_read_only_and_uses_immutable_actions() -> None:
    _raw, document, steps = _workflow()

    assert document["name"] == "Build Portable Windows Package"
    assert set(document["on"]) == {"workflow_dispatch"}
    assert document["permissions"] == {"contents": "read"}
    assert document["jobs"]["build"]["runs-on"] == "windows-2022"

    uses = [step["uses"] for step in steps if "uses" in step]
    assert uses == [
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/cache@5a3ec84eff668545956fd18022155c47e93e2684",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ]
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", use) for use in uses)


def test_workflow_pins_sources_and_never_accepts_telegram_credentials() -> None:
    raw, document, _steps = _workflow()
    build = document["jobs"]["build"]

    assert build["env"]["TELEGRAM_BOT_API_COMMIT"] == ("adfd7f6a8e990272851777eeb3ae0def4216f161")
    assert build["env"]["FFMPEG_URL"] == (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
        "autobuild-2026-02-28-12-59/"
        "ffmpeg-n8.0.1-66-g27b8d1a017-win64-lgpl-8.0.zip"
    )
    assert build["env"]["FFMPEG_SHA256"] == (
        "EF2B1179F226C7A953675623BFF13E38ECD806A425F6F229E44660ABDCD0C077"
    )
    lowered = raw.lower()
    assert "secrets." not in lowered
    assert "bot_token" not in lowered
    assert "telegram_api_hash" not in lowered
    assert "telegram_api_id" not in lowered
    assert "owner_user_id" not in lowered


def test_workflow_verifies_every_layer_before_uploading_one_zip() -> None:
    raw, _document, steps = _workflow()
    names = [step.get("name") for step in steps]

    gates = [
        "Run non-live tests",
        "Run Ruff",
        "Run strict mypy",
        "Verify Telegram source commit",
        "Verify FFmpeg archive",
        "Verify portable package",
        "Create ZIP and checksum",
        "Upload portable package",
    ]
    indexes = [names.index(name) for name in gates]
    assert indexes == sorted(indexes)
    assert "git rev-parse HEAD" in raw
    assert "Get-FileHash" in raw
    assert "verify-package.ps1" in raw

    upload = steps[indexes[-1]]
    assert upload["with"] == {
        "name": "w-bot-windows-x64",
        "path": ".windows-build/artifacts/w-bot-windows-x64.zip",
        "retention-days": "30",
        "if-no-files-found": "error",
    }

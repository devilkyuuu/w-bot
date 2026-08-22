from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WINDOWS = ROOT / "packaging" / "windows"
ASSEMBLE = WINDOWS / "assemble-package.ps1"
VERIFY = WINDOWS / "verify-package.ps1"
MANIFEST = WINDOWS / "package-manifest.json"
SPEC = WINDOWS / "w-bot.spec"


def _powershell(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *arguments,
        ),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_stub_executable(path: Path) -> None:
    source = "public static class Program { public static int Main(string[] args) { return 0; } }"
    escaped_path = str(path).replace("'", "''")
    escaped_source = source.replace("'", "''")
    result = subprocess.run(
        (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Add-Type -TypeDefinition '{escaped_source}' "
            f"-OutputAssembly '{escaped_path}' -OutputType ConsoleApplication",
        ),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def package_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    bot_dist = tmp_path / "bot-dist"
    telegram_api = tmp_path / "telegram" / "telegram-bot-api.exe"
    ffmpeg_root = tmp_path / "ffmpeg"
    output = tmp_path / "output"
    bot_dist.mkdir()
    telegram_api.parent.mkdir()
    ffmpeg_root.mkdir()
    stub = tmp_path / "stub.exe"
    _make_stub_executable(stub)
    shutil.copy2(stub, bot_dist / "w-bot.exe")
    (bot_dist / "_internal").mkdir()
    (bot_dist / "_internal" / "python312.dll").write_bytes(b"runtime")
    shutil.copy2(stub, telegram_api)
    shutil.copy2(stub, ffmpeg_root / "ffmpeg.exe")
    shutil.copy2(stub, ffmpeg_root / "ffprobe.exe")
    (ffmpeg_root / "avcodec.dll").write_bytes(b"dll")
    (ffmpeg_root / "LICENSE.txt").write_text("LGPL test fixture", encoding="utf-8")
    return bot_dist, telegram_api, ffmpeg_root, output


def _assemble(inputs: tuple[Path, Path, Path, Path]) -> subprocess.CompletedProcess[str]:
    bot_dist, telegram_api, ffmpeg_root, output = inputs
    return _powershell(
        ASSEMBLE,
        "-BotDist",
        str(bot_dist),
        "-TelegramApi",
        str(telegram_api),
        "-FfmpegRoot",
        str(ffmpeg_root),
        "-Output",
        str(output),
    )


def test_manifest_is_the_single_package_contract() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert set(manifest["required_files"]) == {
        "Setup Bot.cmd",
        "Start Bot.cmd",
        "Stop Bot.cmd",
        "Bot Status.cmd",
        "Show Bot Logs.cmd",
        "Create Desktop Shortcuts.cmd",
        "app/w-bot.exe",
        "telegram-api/telegram-bot-api.exe",
        "tools/ffmpeg.exe",
        "tools/ffprobe.exe",
        "scripts/create-shortcuts.ps1",
        "README-WINDOWS.txt",
        "THIRD-PARTY-NOTICES.txt",
    }
    assert set(manifest["forbidden_names"]) == {
        "settings.json",
        "runtime.json",
        ".env",
        "wbot.sqlite3",
    }
    assert manifest["token_pattern"] == "[0-9]{6,12}:[A-Za-z0-9_-]{30,}"
    assert manifest["smoke_checks"] == [
        {"path": "app/w-bot.exe", "arguments": ["--version"]},
        {"path": "telegram-api/telegram-bot-api.exe", "arguments": ["--version"]},
        {"path": "tools/ffmpeg.exe", "arguments": ["-version"]},
        {"path": "tools/ffprobe.exe", "arguments": ["-version"]},
    ]


def test_pyinstaller_spec_collects_dynamic_runtime_without_user_data() -> None:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert {"yt_dlp", "telegram", "certifi"} <= constants
    assert {"scripts", "windows_entry.py", "src", "w-bot"} <= constants
    assert any(
        isinstance(node, ast.keyword)
        and node.arg == "console"
        and isinstance(node.value, ast.Constant)
        and node.value.value is True
        for node in ast.walk(tree)
    )
    assert (
        not {
            "settings.json",
            "runtime.json",
            ".env",
            "data",
            "logs",
            "temp",
        }
        & constants
    )


def test_assembly_copies_only_portable_inputs(
    package_inputs: tuple[Path, Path, Path, Path],
) -> None:
    result = _assemble(package_inputs)
    assert result.returncode == 0, result.stderr
    package = package_inputs[3] / "W-Bot"

    for relative in json.loads(MANIFEST.read_text(encoding="utf-8"))["required_files"]:
        assert (package / Path(relative)).is_file(), relative
    assert (package / "app" / "_internal" / "python312.dll").is_file()
    assert (package / "tools" / "avcodec.dll").is_file()
    assert (package / "licenses" / "ffmpeg" / "LICENSE.txt").is_file()
    assert not (package / "data").exists()
    assert not (package / "logs").exists()
    assert not (package / "temp").exists()


def test_verifier_executes_smoke_checks(
    package_inputs: tuple[Path, Path, Path, Path],
) -> None:
    assert _assemble(package_inputs).returncode == 0
    package = package_inputs[3] / "W-Bot"

    result = _powershell(VERIFY, "-PackageRoot", str(package))

    assert result.returncode == 0, result.stderr
    assert "Portable package verified." in result.stdout


@pytest.mark.parametrize("unsafe_kind", ["settings", "token"])
def test_verifier_rejects_credentials_and_user_state(
    package_inputs: tuple[Path, Path, Path, Path],
    unsafe_kind: str,
) -> None:
    assert _assemble(package_inputs).returncode == 0
    package = package_inputs[3] / "W-Bot"
    if unsafe_kind == "settings":
        unsafe = package / "data" / "settings.json"
        unsafe.parent.mkdir()
        unsafe.write_text("{}", encoding="utf-8")
    else:
        unsafe = package / "README-UNSAFE.txt"
        unsafe.write_text("123456:" + ("A" * 30), encoding="utf-8")

    result = _powershell(VERIFY, "-PackageRoot", str(package))

    assert result.returncode != 0
    assert "unsafe" in (result.stdout + result.stderr).lower()

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).parents[1]
WINDOWS = ROOT / "packaging" / "windows"


def _meaningful_lines(path: Path) -> Sequence[str]:
    return [
        line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()
    ]


def test_command_wrappers_have_one_safe_executable_boundary() -> None:
    expected = {
        "Setup Bot.cmd": "setup",
        "Start Bot.cmd": "start",
        "Stop Bot.cmd": "stop",
        "Bot Status.cmd": "status",
        "Show Bot Logs.cmd": "logs",
        "Create Desktop Shortcuts.cmd": "create-shortcuts",
    }

    for filename, command in expected.items():
        lines = _meaningful_lines(WINDOWS / filename)
        assert lines == [
            "@echo off",
            f'"%~dp0app\\w-bot.exe" {command}',
            "if errorlevel 1 pause",
        ]
        assert not any(name in "\n".join(lines) for name in ("BOT_TOKEN", "API_HASH"))


def test_shortcut_script_declares_only_the_four_public_shortcuts() -> None:
    script = (WINDOWS / "scripts" / "create-shortcuts.ps1").read_text(encoding="utf-8")

    expected = {
        "Start W Bot.lnk": "Start Bot.cmd",
        "Stop W Bot.lnk": "Stop Bot.cmd",
        "W Bot Status.lnk": "Bot Status.cmd",
        "W Bot Logs.lnk": "Show Bot Logs.cmd",
    }
    for shortcut, target in expected.items():
        assert f"'{shortcut}' = '{target}'" in script
    assert script.count(".lnk'") == 4
    assert "[Environment]::GetFolderPath('Desktop')" in script
    assert "$WshShell.CreateShortcut(" in script
    assert "$Shortcut.TargetPath = $Target" in script
    assert "$Shortcut.WorkingDirectory = $ResolvedRoot" in script
    assert "$Shortcut.Save()" in script


def test_create_shortcuts_passes_root_as_a_separate_process_argument(tmp_path: Path) -> None:
    from wbot.windows_cli import create_shortcuts
    from wbot.windows_config import PackagePaths

    calls: list[tuple[Sequence[str], bool]] = []

    def runner(arguments: Sequence[str], *, check: bool) -> None:
        calls.append((arguments, check))

    paths = PackagePaths.from_root(tmp_path / "Package With Spaces")
    create_shortcuts(paths, runner=runner)

    arguments, check = calls[0]
    assert arguments == (
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(paths.root / "scripts" / "create-shortcuts.ps1"),
        "-PackageRoot",
        str(paths.root),
    )
    assert check is True

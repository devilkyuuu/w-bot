from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_readme_leads_with_complete_no_docker_windows_flow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    windows = readme.index("## Recommended: portable Windows package")
    telegram = readme.index("## Telegram setup")

    assert windows < telegram
    for instruction in (
        "Open the repository's **Actions** tab.",
        "Select **Build Portable Windows Package**.",
        "Choose **Run workflow**.",
        "Download **w-bot-windows-x64**",
        "double-click **Setup Bot.cmd**",
        "Start W Bot",
        "Stop W Bot",
        "Bot Status.cmd",
        "Show Bot Logs.cmd",
        "Create Desktop Shortcuts.cmd",
    ):
        assert instruction in readme

    assert "Windows 10 or Windows 11" in readme
    assert "Docker is not required" in readme
    assert "No port forwarding" in readme
    assert "awake, online, and logged in" in readme
    assert "Windows DPAPI" in readme
    assert "back up `data/`" in readme
    assert "never share `data/settings.json`" in readme
    assert "cloud Bot API" in readme
    assert "Local Bot API" in readme
    assert "GitHub never receives" in readme
    assert "Optional legacy hosting" in readme
    assert "wispbyte/README.md" in readme


def test_readme_explains_safe_folder_moves_and_upgrades() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    prose = " ".join(readme.split())

    assert "Stop the bot before moving" in prose
    assert "copy the old `data/` folder" in prose
    assert "another computer or Windows user" in prose
    assert "run setup again" in prose
    assert "127.0.0.1:8081" in prose


def test_documentation_uses_bare_links_and_disables_group_privacy() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    windows_readme = (ROOT / "packaging/windows/README-WINDOWS.txt").read_text(
        encoding="utf-8"
    )

    for document in (readme, windows_readme):
        assert "/setprivacy" in document
        assert "Disable" in document
        assert "approved groups" in document
        assert "ordinary" in document
        assert not re.search(r"/w(?:@[A-Za-z0-9_]+)?\s+https://", document)

    assert "https://www.tiktok.com/..." in readme
    assert "https://www.amiami.com/eng/detail?gcode=..." in readme

    northflank = (ROOT / "northflank" / "README.md").read_text(encoding="utf-8")
    assert "/setprivacy` is **Disabled**" in northflank
    assert "the six commands shown in the root README" in northflank
    assert "w - Show content" not in readme


def test_env_example_is_value_free_and_labeled_for_legacy_containers() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert example.startswith("# Optional legacy container deployment only.")
    assert "not used by the portable Windows package" in example
    assert "BOT_TOKEN=\n" in example
    assert "TELEGRAM_API_HASH=\n" in example
    assert not re.search(r"[0-9]{6,12}:[A-Za-z0-9_-]{30,}", example)

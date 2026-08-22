from pathlib import Path
from typing import Any

from wbot.wispbyte import build_bot_api_command, load_env_file, run_bot_with_local_api


def test_local_bot_api_command_is_private_and_uses_local_mode(tmp_path: Path) -> None:
    binary = tmp_path / "telegram-bot-api"
    command = build_bot_api_command(
        binary=binary,
        data_dir=tmp_path / "bot-api-data",
        temp_dir=tmp_path / "bot-api-temp",
    )

    assert command == [
        str(binary),
        "--local",
        "--http-ip-address=127.0.0.1",
        "--http-port=8081",
        f"--dir={tmp_path / 'bot-api-data'}",
        f"--temp-dir={tmp_path / 'bot-api-temp'}",
    ]


def test_launcher_stops_local_api_after_bot_exits(tmp_path: Path) -> None:
    events: list[object] = []
    binary = tmp_path / "telegram-bot-api"
    binary.touch()

    class FakeProcess:
        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> int:
            events.append(("wait", timeout))
            return 0

        def kill(self) -> None:
            events.append("kill")

    def start_process(command: list[str]) -> Any:
        events.append(command)
        return FakeProcess()

    run_bot_with_local_api(
        binary=binary,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        start_process=start_process,
        wait_until_ready=lambda: events.append("ready"),
        run_bot=lambda: events.append("bot"),
    )

    assert events[1:] == ["ready", "bot", "terminate", ("wait", 10)]


def test_env_loader_reads_values_without_overwriting_process_environment(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# secrets\nBOT_TOKEN='123:secret'\nOWNER_USER_ID=42\nEMPTY=\n",
        encoding="utf-8",
    )
    target = {"OWNER_USER_ID": "99"}

    load_env_file(env_file, target)

    assert target == {"BOT_TOKEN": "123:secret", "OWNER_USER_ID": "99", "EMPTY": ""}

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Protocol

from wbot.app import main as run_application


class ManagedProcess(Protocol):
    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


def build_bot_api_command(*, binary: Path, data_dir: Path, temp_dir: Path) -> list[str]:
    return [
        str(binary),
        "--local",
        "--http-ip-address=127.0.0.1",
        "--http-port=8081",
        f"--dir={data_dir}",
        f"--temp-dir={temp_dir}",
    ]


def wait_for_local_api(*, timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 8081), timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("Telegram Local Bot API did not become ready")


def load_env_file(path: Path, target: MutableMapping[str, str]) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        target.setdefault(key, value)


def run_bot_with_local_api(
    *,
    binary: Path,
    data_dir: Path,
    temp_dir: Path,
    start_process: Callable[[list[str]], ManagedProcess] | None = None,
    wait_until_ready: Callable[[], object] | None = None,
    run_bot: Callable[[], object] | None = None,
) -> None:
    if not binary.is_file():
        raise RuntimeError(f"Telegram Local Bot API binary is missing: {binary}")
    data_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    command = build_bot_api_command(binary=binary, data_dir=data_dir, temp_dir=temp_dir)
    launcher = start_process or _start_process
    process = launcher(command)
    try:
        (wait_until_ready or wait_for_local_api)()
        (run_bot or run_application)()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _start_process(command: list[str]) -> ManagedProcess:
    return subprocess.Popen(command)


def main() -> None:
    home = Path(os.environ.get("WISPBOT_HOME", "/home/container"))
    load_env_file(home / ".env", os.environ)
    run_bot_with_local_api(
        binary=Path(os.environ.get("TELEGRAM_BOT_API_BINARY", str(home / "telegram-bot-api"))),
        data_dir=home / ".telegram-bot-api",
        temp_dir=Path(os.environ.get("TELEGRAM_BOT_API_TEMP", "/tmp/telegram-bot-api")),
    )


if __name__ == "__main__":
    main()

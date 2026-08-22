from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from wbot.windows_config import (
    DpapiProtector,
    PackagePaths,
    SecretProtector,
    SettingsStore,
    WindowsConfigError,
)
from wbot.windows_logs import configure_rotating_log, redact
from wbot.windows_process import RuntimeStateStore
from wbot.windows_service import ServiceStatus, WindowsServiceController, WindowsServiceError

InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]
SleepFunction = Callable[[float], None]
ShortcutCreator = Callable[[PackagePaths], None]
ProcessRunner = Callable[..., object]


class ServiceController(Protocol):
    def start(self) -> ServiceStatus: ...

    def stop(self) -> ServiceStatus: ...

    def status(self) -> ServiceStatus: ...

    def run_bot_child(self) -> None: ...


def _package_version() -> str:
    try:
        return version("telegram-w-media-bot")
    except PackageNotFoundError:
        return "0.1.0"


def _default_package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="w-bot.exe")
    parser.add_argument("--version", action="version", version=f"W Bot {_package_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "setup",
        "start",
        "stop",
        "status",
        "logs",
        "run-bot",
        "create-shortcuts",
    ):
        subparsers.add_parser(command)
    return parser


def create_shortcuts(
    paths: PackagePaths,
    *,
    runner: ProcessRunner = subprocess.run,
) -> None:
    script = paths.root / "scripts" / "create-shortcuts.ps1"
    runner(
        (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-PackageRoot",
            str(paths.root),
        ),
        check=True,
    )


def read_positive_int(
    prompt: str,
    *,
    input_fn: InputFunction,
    output_fn: OutputFunction,
) -> int:
    while True:
        try:
            value = int(input_fn(prompt).strip())
        except ValueError:
            value = 0
        if value > 0:
            return value
        output_fn("Enter a positive whole number.")


def _setup(
    paths: PackagePaths,
    store: SettingsStore,
    *,
    input_fn: InputFunction,
    secret_fn: InputFunction,
    output_fn: OutputFunction,
    shortcut_creator: ShortcutCreator,
) -> int:
    bot_token = secret_fn("Bot token: ").strip()
    api_id = read_positive_int("Telegram API ID: ", input_fn=input_fn, output_fn=output_fn)
    api_hash = secret_fn("Telegram API hash: ").strip()
    owner_id = read_positive_int("Owner Telegram user ID: ", input_fn=input_fn, output_fn=output_fn)
    store.save(
        api_id=api_id,
        api_hash=api_hash,
        owner_id=owner_id,
        bot_token=bot_token,
    )
    paths.ensure_runtime_directories()
    shortcut_creator(paths)
    output_fn("Setup complete.")
    return 0


def _status(controller: ServiceController, output_fn: OutputFunction) -> int:
    status = controller.status()
    output_fn(status.value)
    if status is ServiceStatus.SETUP_REQUIRED:
        output_fn("Run Setup Bot.cmd first.")
        return 1
    if status is ServiceStatus.PARTIAL:
        output_fn("Run Stop Bot.cmd, then Start Bot.cmd.")
        return 1
    return 0


def _tail_lines(path: Path, count: int = 100) -> tuple[list[str], int]:
    if not path.is_file():
        return [], 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = list(deque(handle, maxlen=count))
        position = handle.tell()
    return [line.rstrip("\r\n") for line in lines], position


def _show_logs(
    paths: PackagePaths,
    *,
    output_fn: OutputFunction,
    sleep_fn: SleepFunction,
) -> int:
    log_paths = (
        paths.logs / "controller.log",
        paths.logs / "bot.log",
        paths.logs / "telegram-api.log",
    )
    positions: dict[Path, int] = {}
    for path in log_paths:
        lines, position = _tail_lines(path)
        positions[path] = position
        if lines:
            output_fn(f"=== {path.name} ===")
            for line in lines:
                output_fn(line)
    try:
        while True:
            sleep_fn(0.5)
            for path in log_paths:
                if not path.is_file():
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    size = path.stat().st_size
                    if size < positions[path]:
                        positions[path] = 0
                    handle.seek(positions[path])
                    for line in handle:
                        output_fn(line.rstrip("\r\n"))
                    positions[path] = handle.tell()
    except KeyboardInterrupt:
        output_fn("Log viewer closed. The bot is still running.")
        return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    package_root: Path | None = None,
    input_fn: InputFunction = input,
    secret_fn: InputFunction = getpass.getpass,
    output_fn: OutputFunction = print,
    protector: SecretProtector | None = None,
    controller: ServiceController | None = None,
    shortcut_creator: ShortcutCreator | None = None,
    sleep_fn: SleepFunction | None = None,
) -> int:
    arguments = _parser().parse_args(argv)
    paths = PackagePaths.from_root((package_root or _default_package_root()).resolve())
    secrets: tuple[str, ...] = ()
    logger = configure_rotating_log(paths.logs / "controller.log", secrets)
    try:
        secret_protector = protector or DpapiProtector()
        store = SettingsStore(paths, secret_protector)
        try:
            saved = store.load_runtime()
        except WindowsConfigError:
            pass
        else:
            secrets = (saved.bot_token, saved.telegram_api_hash)
            logger = configure_rotating_log(paths.logs / "controller.log", secrets)
        active_controller = controller or WindowsServiceController(
            paths,
            store,
            state_store=RuntimeStateStore(paths.runtime_file),
        )
        command = arguments.command
        if command == "setup":
            result = _setup(
                paths,
                store,
                input_fn=input_fn,
                secret_fn=secret_fn,
                output_fn=output_fn,
                shortcut_creator=shortcut_creator or create_shortcuts,
            )
            logger.info("command=setup result=complete")
            return result
        if command == "start":
            active_controller.start()
            logger.info("command=start result=running")
            output_fn("W Bot is running.")
            return 0
        if command == "stop":
            active_controller.stop()
            logger.info("command=stop result=stopped")
            output_fn("W Bot is stopped.")
            return 0
        if command == "status":
            result = _status(active_controller, output_fn)
            logger.info("command=status result=shown")
            return result
        if command == "logs":
            return _show_logs(
                paths,
                output_fn=output_fn,
                sleep_fn=sleep_fn or time.sleep,
            )
        if command == "run-bot":
            active_controller.run_bot_child()
            return 0
        if command == "create-shortcuts":
            (shortcut_creator or create_shortcuts)(paths)
            output_fn("Desktop shortcuts created.")
            return 0
        raise WindowsServiceError("Unknown command.")
    except (WindowsConfigError, WindowsServiceError) as exc:
        safe_message = redact(str(exc), secrets)
        logger.error(
            "command=%s error=%s message=%s",
            arguments.command,
            type(exc).__name__,
            safe_message,
        )
        output_fn(safe_message)
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("command=%s error=%s", arguments.command, type(exc).__name__)
        output_fn("The Windows command could not be completed.")
        return 1

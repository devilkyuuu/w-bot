from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Protocol

import httpx

from wbot.service import run_service
from wbot.windows_config import PackagePaths, SettingsStore, WindowsConfigError
from wbot.windows_logs import configure_rotating_log
from wbot.windows_process import (
    ProcessIdentity,
    ProcessManager,
    RuntimeState,
    RuntimeStateStore,
    WindowsProcessError,
)


class WindowsServiceError(RuntimeError):
    """A sanitized Windows service-control failure."""


class ServiceStatus(Enum):
    SETUP_REQUIRED = "Setup required"
    STOPPED = "Stopped"
    PARTIAL = "Partially running"
    RUNNING = "Running"


class ProcessController(Protocol):
    def start(
        self,
        executable: Path,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> ProcessIdentity: ...

    def matches(self, identity: ProcessIdentity) -> bool: ...

    def wait(self, identity: ProcessIdentity, timeout: float) -> bool: ...

    def terminate_verified(self, identity: ProcessIdentity, timeout: float) -> bool: ...


class Handover(Protocol):
    def log_out_cloud(self, bot_token: str) -> None: ...

    def probe_local(self, bot_token: str) -> None: ...


class HandoverClient:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=20, trust_env=False)

    def log_out_cloud(self, bot_token: str) -> None:
        self._request(
            f"https://api.telegram.org/bot{bot_token}/logOut",
            "Telegram handover failed. Try Start Bot again.",
        )

    def probe_local(self, bot_token: str) -> None:
        self._request(
            f"http://127.0.0.1:8081/bot{bot_token}/getMe",
            "The local Telegram service did not accept the bot.",
        )

    def _request(self, url: str, error: str) -> None:
        try:
            response = self._http.post(url)
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise WindowsServiceError(error) from None
        if (
            response.status_code != 200
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
        ):
            raise WindowsServiceError(error)


class WindowsServiceController:
    def __init__(
        self,
        paths: PackagePaths,
        settings_store: SettingsStore,
        *,
        process_manager: ProcessController | None = None,
        state_store: RuntimeStateStore | None = None,
        handover: Handover | None = None,
        port_is_free: Callable[[], bool] | None = None,
        wait_for_api: Callable[[float], bool] | None = None,
        wait_for_ready: Callable[[Path, float], bool] | None = None,
    ) -> None:
        self.paths = paths
        self.settings_store = settings_store
        self.process_manager = process_manager or ProcessManager()
        self.state_store = state_store or RuntimeStateStore(paths.runtime_file)
        self.handover = handover or HandoverClient()
        self._port_is_free = port_is_free or _port_is_free
        self._wait_for_api = wait_for_api or _wait_for_api
        self._wait_for_ready = wait_for_ready or _wait_for_file

    def status(self) -> ServiceStatus:
        if not self.paths.settings_file.is_file():
            return ServiceStatus.SETUP_REQUIRED
        state = self.state_store.load()
        api_running = state.api is not None and self.process_manager.matches(state.api)
        bot_running = state.bot is not None and self.process_manager.matches(state.bot)
        if api_running and bot_running:
            try:
                self.handover.probe_local(self.settings_store.load_runtime().bot_token)
            except (WindowsConfigError, WindowsServiceError):
                return ServiceStatus.PARTIAL
            return ServiceStatus.RUNNING
        if api_running or bot_running:
            return ServiceStatus.PARTIAL
        return ServiceStatus.STOPPED

    def start(self) -> ServiceStatus:
        try:
            settings = self.settings_store.load_runtime()
        except WindowsConfigError as exc:
            raise WindowsServiceError(str(exc)) from None
        self.paths.ensure_runtime_directories()
        state = self.state_store.load()
        api_running = state.api is not None and self.process_manager.matches(state.api)
        bot_running = state.bot is not None and self.process_manager.matches(state.bot)
        if api_running and bot_running:
            self.handover.probe_local(settings.bot_token)
            return ServiceStatus.RUNNING
        if api_running or bot_running:
            self._stop_state(state)

        if not self._port_is_free():
            raise WindowsServiceError(
                "Port 8081 is already in use. Close the other program and try again."
            )

        current = RuntimeState()
        try:
            api = self.process_manager.start(
                self.paths.telegram_api / "telegram-bot-api.exe",
                self._api_arguments(),
                cwd=self.paths.root,
                environment=self._api_environment(
                    settings.telegram_api_id,
                    settings.telegram_api_hash,
                ),
                stdout_path=self.paths.logs / "telegram-api.out.log",
                stderr_path=self.paths.logs / "telegram-api.err.log",
            )
            current = RuntimeState(api=api)
            self.state_store.save(current)
            if not self._wait_for_api(30) or not self.process_manager.matches(api):
                raise WindowsServiceError("The local Telegram service could not start.")

            if not self.settings_store.cloud_logout_complete():
                self.handover.log_out_cloud(settings.bot_token)
                self.settings_store.mark_cloud_logout_complete()
            self._probe_local_until_ready(settings.bot_token, timeout=30)

            bot = self.process_manager.start(
                self.paths.app / "w-bot.exe",
                ("run-bot",),
                cwd=self.paths.root,
                environment=self._bot_environment(),
                stdout_path=self.paths.logs / "bot.out.log",
                stderr_path=self.paths.logs / "bot.err.log",
            )
            current = RuntimeState(api=api, bot=bot)
            self.state_store.save(current)
            if (
                not self._wait_for_ready(self.paths.ready_file, 30)
                or not self.process_manager.matches(bot)
            ):
                raise WindowsServiceError("The bot could not start. Open W Bot Logs for details.")
            return ServiceStatus.RUNNING
        except WindowsServiceError:
            self._stop_state(current)
            raise
        except (OSError, WindowsConfigError, WindowsProcessError):
            self._stop_state(current)
            raise WindowsServiceError(
                "The bot could not start. Open W Bot Logs for details."
            ) from None

    def stop(self) -> ServiceStatus:
        self._stop_state(self.state_store.load())
        return ServiceStatus.STOPPED

    def run_bot_child(self) -> None:
        settings = self.settings_store.load_runtime()
        configure_rotating_log(
            self.paths.logs / "bot.log",
            (settings.bot_token, settings.telegram_api_hash),
            logger_name="",
        )
        run_service(settings, self.paths.stop_file, self.paths.ready_file)

    def _stop_state(self, state: RuntimeState) -> None:
        bot = state.bot
        if bot is not None and self.process_manager.matches(bot):
            self.paths.stop_file.unlink(missing_ok=True)
            self.paths.stop_file.touch()
            if not self.process_manager.wait(bot, timeout=15):
                self.process_manager.terminate_verified(bot, timeout=5)
        api = state.api
        if api is not None and self.process_manager.matches(api):
            self.process_manager.terminate_verified(api, timeout=10)
        self.state_store.clear()
        self.paths.stop_file.unlink(missing_ok=True)
        self.paths.ready_file.unlink(missing_ok=True)

    def _probe_local_until_ready(self, bot_token: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.handover.probe_local(bot_token)
                return
            except WindowsServiceError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)

    def _api_arguments(self) -> tuple[str, ...]:
        return (
            "--local",
            "--http-ip-address=127.0.0.1",
            "--http-port=8081",
            f"--dir={self.paths.data / 'telegram-api'}",
            f"--temp-dir={self.paths.temp / 'telegram-api'}",
            f"--log={self.paths.logs / 'telegram-api.log'}",
            "--log-max-file-size=10000000",
            "--verbosity=0",
        )

    @staticmethod
    def _api_environment(api_id: int, api_hash: str) -> dict[str, str]:
        environment = dict(os.environ)
        environment["TELEGRAM_API_ID"] = str(api_id)
        environment["TELEGRAM_API_HASH"] = api_hash
        return environment

    def _bot_environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        for name in ("BOT_TOKEN", "TELEGRAM_API_HASH", "TELEGRAM_API_ID", "OWNER_USER_ID"):
            environment.pop(name, None)
        environment["PATH"] = os.pathsep.join(
            (str(self.paths.tools), environment.get("PATH", ""))
        ).rstrip(os.pathsep)
        return environment


def _port_is_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", 8081))
        except OSError:
            return False
    return True


def _wait_for_api(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex(("127.0.0.1", 8081)) == 0:
                return True
        time.sleep(0.1)
    return False


def _wait_for_file(path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False

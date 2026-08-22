from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx
import pytest

from wbot.windows_config import PackagePaths, SettingsStore, WindowsConfigError
from wbot.windows_process import (
    ProcessIdentity,
    RuntimeState,
    RuntimeStateStore,
)
from wbot.windows_service import (
    HandoverClient,
    ServiceStatus,
    WindowsServiceController,
    WindowsServiceError,
)

TOKEN = "dummy-token-value-that-must-not-leak"
API_HASH = "0123456789abcdef0123456789abcdef"


class FakeProtector:
    def protect(self, value: str) -> str:
        return f"protected:{value[::-1]}"

    def unprotect(self, value: str) -> str:
        if not value.startswith("protected:"):
            raise WindowsConfigError("invalid protected value")
        return value.removeprefix("protected:")[::-1]


class FakeProcessManager:
    def __init__(self) -> None:
        self.alive: dict[int, ProcessIdentity] = {}
        self.starts: list[dict[str, object]] = []
        self.events: list[str] = []
        self._next_pid = 100

    def start(
        self,
        executable: Path,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> ProcessIdentity:
        self._next_pid += 1
        identity = ProcessIdentity(self._next_pid, executable, float(self._next_pid))
        self.alive[identity.pid] = identity
        self.starts.append(
            {
                "identity": identity,
                "executable": executable,
                "arguments": tuple(arguments),
                "cwd": cwd,
                "environment": dict(environment),
                "stdout_path": stdout_path,
                "stderr_path": stderr_path,
            }
        )
        self.events.append(f"start:{executable.name}")
        return identity

    def matches(self, identity: ProcessIdentity) -> bool:
        return self.alive.get(identity.pid) == identity

    def wait(self, identity: ProcessIdentity, timeout: float) -> bool:
        del timeout
        self.events.append(f"wait:{identity.executable.name}")
        if identity.executable.name == "w-bot.exe" and self.matches(identity):
            self.alive.pop(identity.pid)
            return True
        return identity.pid not in self.alive

    def terminate_verified(self, identity: ProcessIdentity, timeout: float) -> bool:
        del timeout
        self.events.append(f"terminate:{identity.executable.name}")
        if not self.matches(identity):
            return False
        self.alive.pop(identity.pid)
        return True


class FakeHandover:
    def __init__(self, *, fail_logout: bool = False, probe_failures: int = 0) -> None:
        self.fail_logout = fail_logout
        self.probe_failures = probe_failures
        self.logout_tokens: list[str] = []
        self.probe_tokens: list[str] = []

    def log_out_cloud(self, bot_token: str) -> None:
        self.logout_tokens.append(bot_token)
        if self.fail_logout:
            raise WindowsServiceError("Telegram handover failed. Try Start Bot again.")

    def probe_local(self, bot_token: str) -> None:
        self.probe_tokens.append(bot_token)
        if self.probe_failures > 0:
            self.probe_failures -= 1
            raise WindowsServiceError("The local Telegram service did not accept the bot.")


def _configured_controller(
    tmp_path: Path,
    *,
    manager: FakeProcessManager | None = None,
    handover: FakeHandover | None = None,
    port_is_free: bool = True,
) -> tuple[
    WindowsServiceController,
    PackagePaths,
    SettingsStore,
    FakeProcessManager,
    FakeHandover,
]:
    paths = PackagePaths.from_root(tmp_path / "Portable W Bot")
    paths.ensure_runtime_directories()
    paths.app.mkdir(parents=True)
    paths.telegram_api.mkdir(parents=True)
    (paths.app / "w-bot.exe").touch()
    (paths.telegram_api / "telegram-bot-api.exe").touch()
    store = SettingsStore(paths, FakeProtector())
    store.save(api_id=12345, api_hash=API_HASH, owner_id=98765, bot_token=TOKEN)
    selected_manager = manager or FakeProcessManager()
    selected_handover = handover or FakeHandover()
    controller = WindowsServiceController(
        paths,
        store,
        process_manager=selected_manager,
        state_store=RuntimeStateStore(paths.runtime_file),
        handover=selected_handover,
        port_is_free=lambda: port_is_free,
        wait_for_api=lambda timeout: timeout == 30,
        wait_for_ready=lambda path, timeout: path == paths.ready_file and timeout == 30,
    )
    return controller, paths, store, selected_manager, selected_handover


def test_handover_client_uses_cloud_and_local_endpoints_without_leaking_failures() -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    handover = HandoverClient(client)

    handover.log_out_cloud(TOKEN)
    handover.probe_local(TOKEN)

    assert [(item.method, str(item.url)) for item in requested] == [
        ("POST", f"https://api.telegram.org/bot{TOKEN}/logOut"),
        ("POST", f"http://127.0.0.1:8081/bot{TOKEN}/getMe"),
    ]

    failing = HandoverClient(
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    )
    with pytest.raises(WindowsServiceError) as caught:
        failing.log_out_cloud(TOKEN)
    assert TOKEN not in str(caught.value)


def test_first_start_hands_over_then_starts_both_services(tmp_path: Path) -> None:
    controller, paths, store, manager, handover = _configured_controller(tmp_path)

    assert controller.start() is ServiceStatus.RUNNING

    assert handover.logout_tokens == [TOKEN]
    assert handover.probe_tokens == [TOKEN]
    assert store.cloud_logout_complete()
    assert len(manager.starts) == 2
    api_start, bot_start = manager.starts
    assert api_start["executable"] == paths.telegram_api / "telegram-bot-api.exe"
    assert api_start["arguments"] == (
        "--local",
        "--http-ip-address=127.0.0.1",
        "--http-port=8081",
        f"--dir={paths.data / 'telegram-api'}",
        f"--temp-dir={paths.temp / 'telegram-api'}",
        f"--log={paths.logs / 'telegram-api.log'}",
        "--log-max-file-size=10000000",
        "--verbosity=0",
    )
    assert TOKEN not in " ".join(api_start["arguments"])
    assert API_HASH not in " ".join(api_start["arguments"])
    api_environment = api_start["environment"]
    assert isinstance(api_environment, dict)
    assert api_environment["TELEGRAM_API_ID"] == "12345"
    assert api_environment["TELEGRAM_API_HASH"] == API_HASH
    assert bot_start["executable"] == paths.app / "w-bot.exe"
    assert bot_start["arguments"] == ("run-bot",)
    bot_environment = bot_start["environment"]
    assert isinstance(bot_environment, dict)
    assert bot_environment["PATH"].split(os.pathsep)[0] == str(paths.tools)
    assert RuntimeStateStore(paths.runtime_file).load().api is not None
    assert RuntimeStateStore(paths.runtime_file).load().bot is not None

    assert controller.start() is ServiceStatus.RUNNING
    assert len(manager.starts) == 2
    assert handover.logout_tokens == [TOKEN]


def test_failed_cloud_logout_rolls_back_and_retries_later(tmp_path: Path) -> None:
    handover = FakeHandover(fail_logout=True)
    controller, paths, store, manager, _ = _configured_controller(
        tmp_path, handover=handover
    )

    with pytest.raises(WindowsServiceError, match="handover failed") as caught:
        controller.start()

    assert TOKEN not in str(caught.value)
    assert not store.cloud_logout_complete()
    assert manager.alive == {}
    assert RuntimeStateStore(paths.runtime_file).load() == RuntimeState()


def test_start_retries_local_probe_while_api_finishes_initializing(tmp_path: Path) -> None:
    handover = FakeHandover(probe_failures=2)
    controller, _, _, _, _ = _configured_controller(tmp_path, handover=handover)

    assert controller.start() is ServiceStatus.RUNNING

    assert handover.probe_tokens == [TOKEN, TOKEN, TOKEN]


def test_occupied_unowned_port_is_left_untouched(tmp_path: Path) -> None:
    controller, _, _, manager, handover = _configured_controller(
        tmp_path, port_is_free=False
    )

    with pytest.raises(WindowsServiceError, match="Port 8081 is already in use"):
        controller.start()

    assert manager.starts == []
    assert manager.events == []
    assert handover.logout_tokens == []


def test_stop_waits_for_bot_then_terminates_verified_api(tmp_path: Path) -> None:
    controller, paths, _, manager, _ = _configured_controller(tmp_path)
    assert controller.start() is ServiceStatus.RUNNING
    manager.events.clear()

    assert controller.stop() is ServiceStatus.STOPPED

    assert manager.events == [
        "wait:w-bot.exe",
        "terminate:telegram-bot-api.exe",
    ]
    assert manager.alive == {}
    assert RuntimeStateStore(paths.runtime_file).load() == RuntimeState()
    assert not paths.stop_file.exists()
    assert not paths.ready_file.exists()


def test_status_distinguishes_setup_stopped_partial_and_running(tmp_path: Path) -> None:
    paths = PackagePaths.from_root(tmp_path / "missing")
    missing = WindowsServiceController(
        paths,
        SettingsStore(paths, FakeProtector()),
        process_manager=FakeProcessManager(),
        state_store=RuntimeStateStore(paths.runtime_file),
        handover=FakeHandover(),
    )
    assert missing.status() is ServiceStatus.SETUP_REQUIRED

    controller, paths, _, manager, _ = _configured_controller(tmp_path / "configured")
    assert controller.status() is ServiceStatus.STOPPED
    api = manager.start(
        paths.telegram_api / "telegram-bot-api.exe",
        (),
        cwd=paths.root,
        environment={},
        stdout_path=paths.logs / "api.out.log",
        stderr_path=paths.logs / "api.err.log",
    )
    RuntimeStateStore(paths.runtime_file).save(RuntimeState(api=api))
    assert controller.status() is ServiceStatus.PARTIAL

    assert controller.start() is ServiceStatus.RUNNING
    assert controller.status() is ServiceStatus.RUNNING

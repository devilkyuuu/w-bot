from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

from wbot.windows_process import (
    ProcessIdentity,
    ProcessManager,
    RuntimeState,
    RuntimeStateStore,
)


def test_started_process_uses_requested_environment_cwd_and_logs(tmp_path: Path) -> None:
    manager = ProcessManager()
    stdout = tmp_path / "logs" / "stdout.log"
    stderr = tmp_path / "logs" / "stderr.log"
    environment = dict(os.environ)
    environment["WBOT_PROCESS_PROBE"] = "expected-value"
    command = (
        "import os, time; "
        "print(os.environ['WBOT_PROCESS_PROBE']); "
        "print(os.getcwd()); "
        "time.sleep(0.2)"
    )

    identity = manager.start(
        Path(sys.executable),
        ("-c", command),
        cwd=tmp_path,
        environment=environment,
        stdout_path=stdout,
        stderr_path=stderr,
    )

    assert manager.wait(identity, timeout=5)
    assert stdout.read_text(encoding="utf-8").splitlines() == [
        "expected-value",
        str(tmp_path),
    ]
    assert stderr.read_text(encoding="utf-8") == ""


def test_verified_termination_refuses_reused_or_changed_process_identity(
    tmp_path: Path,
) -> None:
    manager = ProcessManager()
    identity = manager.start(
        Path(sys.executable),
        ("-c", "import time; time.sleep(30)"),
        cwd=tmp_path,
        environment=os.environ,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )

    try:
        assert manager.matches(identity)
        assert not manager.matches(
            replace(identity, executable=tmp_path / "different.exe")
        )
        assert not manager.matches(replace(identity, create_time=identity.create_time + 10))
        assert not manager.terminate_verified(
            replace(identity, create_time=identity.create_time + 10),
            timeout=0.1,
        )
        assert manager.matches(identity)
        assert manager.terminate_verified(identity, timeout=5)
        assert manager.wait(identity, timeout=0.1)
    finally:
        manager.terminate_verified(identity, timeout=1)


def test_runtime_state_round_trips_process_identities(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "data" / "runtime.json")
    state = RuntimeState(
        api=ProcessIdentity(101, Path("C:/W Bot/telegram-api.exe"), 123.5),
        bot=ProcessIdentity(202, Path("C:/W Bot/w-bot.exe"), 456.75),
    )

    store.save(state)

    assert store.load() == state
    store.clear()
    assert store.load() == RuntimeState()


def test_malformed_runtime_state_is_discarded_instead_of_trusted(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text('{"api":{"pid":123}', encoding="utf-8")
    store = RuntimeStateStore(path)

    assert store.load() == RuntimeState()
    assert not path.exists()

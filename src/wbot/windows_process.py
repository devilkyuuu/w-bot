from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

import psutil

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class WindowsProcessError(RuntimeError):
    """A sanitized Windows child-process management failure."""


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    executable: Path
    create_time: float


@dataclass(frozen=True, slots=True)
class RuntimeState:
    api: ProcessIdentity | None = None
    bot: ProcessIdentity | None = None


class ProcessManager:
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
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_handle: TextIO | None = None
        stderr_handle: TextIO | None = None
        try:
            stdout_handle = stdout_path.open("a", encoding="utf-8")
            stderr_handle = stderr_path.open("a", encoding="utf-8")
            child = subprocess.Popen(
                (str(executable), *arguments),
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            process = psutil.Process(child.pid)
            return ProcessIdentity(
                pid=child.pid,
                executable=Path(process.exe()),
                create_time=process.create_time(),
            )
        except (OSError, psutil.Error):
            raise WindowsProcessError("A background process could not be started") from None
        finally:
            if stdout_handle is not None:
                stdout_handle.close()
            if stderr_handle is not None:
                stderr_handle.close()

    def matches(self, identity: ProcessIdentity) -> bool:
        try:
            process = psutil.Process(identity.pid)
            return _same_path(Path(process.exe()), identity.executable) and abs(
                process.create_time() - identity.create_time
            ) <= 0.01
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def wait(self, identity: ProcessIdentity, timeout: float) -> bool:
        try:
            process = psutil.Process(identity.pid)
        except psutil.NoSuchProcess:
            return True
        except (psutil.AccessDenied, psutil.ZombieProcess):
            return False
        if not self.matches(identity):
            return False
        try:
            process.wait(timeout=timeout)
            return True
        except psutil.TimeoutExpired:
            return False
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        except psutil.AccessDenied:
            return False

    def terminate_verified(self, identity: ProcessIdentity, timeout: float) -> bool:
        if not self.matches(identity):
            return False
        try:
            process = psutil.Process(identity.pid)
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                if not self.matches(identity):
                    return False
                process.kill()
                process.wait(timeout=timeout)
            return True
        except psutil.NoSuchProcess:
            return True
        except (psutil.AccessDenied, psutil.ZombieProcess, psutil.TimeoutExpired):
            return False


class RuntimeStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RuntimeState:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError
            return RuntimeState(
                api=_identity_from_document(document.get("api")),
                bot=_identity_from_document(document.get("bot")),
            )
        except FileNotFoundError:
            return RuntimeState()
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self.clear()
            return RuntimeState()

    def save(self, state: RuntimeState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        document = {
            "api": _identity_document(state.api),
            "bot": _identity_document(state.bot),
        }
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, ensure_ascii=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise WindowsProcessError("Runtime state could not be saved") from None

    def clear(self) -> None:
        with suppress(OSError):
            self.path.unlink(missing_ok=True)


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _identity_document(identity: ProcessIdentity | None) -> dict[str, object] | None:
    if identity is None:
        return None
    document = asdict(identity)
    document["executable"] = str(identity.executable)
    return document


def _identity_from_document(value: object) -> ProcessIdentity | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError
    pid = value.get("pid")
    executable = value.get("executable")
    create_time = value.get("create_time")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError
    if not isinstance(executable, str) or not executable:
        raise ValueError
    if isinstance(create_time, bool) or not isinstance(create_time, int | float):
        raise ValueError
    if create_time <= 0:
        raise ValueError
    return ProcessIdentity(pid, Path(executable), float(create_time))


if sys.platform != "win32" and (CREATE_NO_WINDOW or CREATE_NEW_PROCESS_GROUP):
    raise RuntimeError("unexpected non-Windows process flags")

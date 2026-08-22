from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from wbot.windows_config import PackagePaths, SettingsStore, WindowsConfigError
from wbot.windows_service import ServiceStatus, WindowsServiceError


class FakeProtector:
    def protect(self, value: str) -> str:
        return f"protected:{value[::-1]}"

    def unprotect(self, value: str) -> str:
        return value.removeprefix("protected:")[::-1]


class FakeController:
    def __init__(
        self,
        *,
        start_result: ServiceStatus = ServiceStatus.RUNNING,
        stop_result: ServiceStatus = ServiceStatus.STOPPED,
        status_result: ServiceStatus = ServiceStatus.STOPPED,
        error: Exception | None = None,
    ) -> None:
        self.start_result = start_result
        self.stop_result = stop_result
        self.status_result = status_result
        self.error = error
        self.run_bot_calls = 0

    def start(self) -> ServiceStatus:
        if self.error is not None:
            raise self.error
        return self.start_result

    def stop(self) -> ServiceStatus:
        if self.error is not None:
            raise self.error
        return self.stop_result

    def status(self) -> ServiceStatus:
        if self.error is not None:
            raise self.error
        return self.status_result

    def run_bot_child(self) -> None:
        if self.error is not None:
            raise self.error
        self.run_bot_calls += 1


def _run(
    tmp_path: Path,
    argv: Sequence[str],
    *,
    controller: FakeController | None = None,
    inputs: Sequence[str] = (),
    secrets: Sequence[str] = (),
    shortcut: Callable[[PackagePaths], None] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> tuple[int, list[str], list[str]]:
    from wbot.windows_cli import main

    visible = iter(inputs)
    hidden = iter(secrets)
    output: list[str] = []
    secret_prompts: list[str] = []

    def get_secret(prompt: str) -> str:
        secret_prompts.append(prompt)
        return next(hidden)

    code = main(
        argv,
        package_root=tmp_path,
        input_fn=lambda _prompt: next(visible),
        secret_fn=get_secret,
        output_fn=output.append,
        protector=FakeProtector(),
        controller=controller,
        shortcut_creator=shortcut,
        sleep_fn=sleep,
    )
    return code, output, secret_prompts


def test_setup_hides_secrets_retries_ids_and_creates_shortcuts(tmp_path: Path) -> None:
    token = "dummy-bot-token-value-for-testing-only"
    api_hash = "0123456789abcdef0123456789abcdef"
    shortcut_roots: list[Path] = []

    code, output, secret_prompts = _run(
        tmp_path,
        ["setup"],
        inputs=["no", "12345", "0", "98765"],
        secrets=[token, api_hash],
        shortcut=lambda paths: shortcut_roots.append(paths.root),
    )

    assert code == 0
    assert output == [
        "Enter a positive whole number.",
        "Enter a positive whole number.",
        "Setup complete.",
    ]
    assert secret_prompts == ["Bot token: ", "Telegram API hash: "]
    assert shortcut_roots == [tmp_path]
    settings_text = (tmp_path / "data" / "settings.json").read_text(encoding="utf-8")
    assert token not in settings_text
    assert api_hash not in settings_text
    assert token not in "\n".join(output)
    assert api_hash not in "\n".join(output)


@pytest.mark.parametrize(
    ("command", "status", "expected_code", "expected"),
    [
        ("start", ServiceStatus.RUNNING, 0, ["W Bot is running."]),
        ("stop", ServiceStatus.STOPPED, 0, ["W Bot is stopped."]),
        ("status", ServiceStatus.RUNNING, 0, ["Running"]),
        ("status", ServiceStatus.STOPPED, 0, ["Stopped"]),
        (
            "status",
            ServiceStatus.SETUP_REQUIRED,
            1,
            ["Setup required", "Run Setup Bot.cmd first."],
        ),
        (
            "status",
            ServiceStatus.PARTIAL,
            1,
            ["Partially running", "Run Stop Bot.cmd, then Start Bot.cmd."],
        ),
    ],
)
def test_service_commands_have_stable_messages_and_exit_codes(
    tmp_path: Path,
    command: str,
    status: ServiceStatus,
    expected_code: int,
    expected: list[str],
) -> None:
    controller = FakeController(
        start_result=status,
        stop_result=status,
        status_result=status,
    )

    code, output, _ = _run(tmp_path, [command], controller=controller)

    assert code == expected_code
    assert output == expected


def test_errors_are_short_and_do_not_echo_supplied_secrets(tmp_path: Path) -> None:
    secret = "dummy-bot-token-value-for-testing-only"
    controller = FakeController(error=WindowsServiceError("The bot could not start."))

    code, output, _ = _run(tmp_path, ["start"], controller=controller)

    assert code == 1
    assert output == ["The bot could not start."]
    assert secret not in "\n".join(output)


def test_controller_error_output_and_log_are_redacted_from_saved_secrets(
    tmp_path: Path,
) -> None:
    token = "dummy-token-that-must-not-leak"
    api_hash = "dummy-hash-that-must-not-leak"
    paths = PackagePaths.from_root(tmp_path)
    SettingsStore(paths, FakeProtector()).save(
        api_id=12345,
        api_hash=api_hash,
        owner_id=98765,
        bot_token=token,
    )
    controller = FakeController(
        error=WindowsServiceError(f"failed token={token} hash={api_hash}")
    )

    code, output, _ = _run(tmp_path, ["start"], controller=controller)

    assert code == 1
    assert output == ["failed token=[REDACTED] hash=[REDACTED]"]
    log = (paths.logs / "controller.log").read_text(encoding="utf-8")
    assert "WindowsServiceError" in log
    assert token not in log
    assert api_hash not in log


def test_run_bot_refuses_direct_use_before_setup(tmp_path: Path) -> None:
    controller = FakeController(
        error=WindowsConfigError("Setup is required. Run Setup Bot.cmd first.")
    )

    code, output, _ = _run(tmp_path, ["run-bot"], controller=controller)

    assert code == 1
    assert output == ["Setup is required. Run Setup Bot.cmd first."]


def test_logs_print_tail_and_ctrl_c_does_not_touch_controller(tmp_path: Path) -> None:
    paths = PackagePaths.from_root(tmp_path)
    paths.ensure_runtime_directories()
    (paths.logs / "controller.log").write_text(
        "".join(f"controller {number}\n" for number in range(105)),
        encoding="utf-8",
    )
    (paths.logs / "bot.log").write_text("bot one\nbot two\n", encoding="utf-8")
    controller = FakeController()

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    code, output, _ = _run(
        tmp_path,
        ["logs"],
        controller=controller,
        sleep=interrupt,
    )

    assert code == 0
    assert output[:2] == ["=== controller.log ===", "controller 5"]
    assert "controller 104" in output
    assert "=== bot.log ===" in output
    assert output[-1] == "Log viewer closed. The bot is still running."
    assert controller.run_bot_calls == 0

# Native Windows Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable Windows x64 ZIP that runs the existing private Telegram `/w` bot and Telegram Local Bot API through safe double-click controls without Docker or preinstalled development tools.

**Architecture:** Keep the existing extraction and Telegram-command code unchanged, add a small Windows-only controller around it, and package that controller with PyInstaller. GitHub Actions compiles the pinned official Telegram Bot API, verifies a pinned FFmpeg archive, assembles the portable folder, tests it, and uploads a credential-free ZIP.

**Tech Stack:** Python 3.12, python-telegram-bot 22.x, httpx, psutil 7.x, Windows DPAPI via `ctypes`, PyInstaller 6.16, PowerShell 5.1-compatible shortcut script, CMake/MSVC/vcpkg, GitHub Actions, Telegram Bot API 10.2, FFmpeg 8.0.1.

**Spec:** `docs/superpowers/specs/2026-08-22-native-windows-package-design.md`

## Global Constraints

- Target Windows 10 or Windows 11 on x64 hardware only.
- The package must run without Docker, a system Python, Visual Studio, CMake, or a separate FFmpeg installation.
- Preserve the existing `/w`, `/approve`, `/revoke`, privacy-mode, five-minute, 1080p, 700,000,000-byte, album, caption, and short-error behavior.
- Bind Telegram Local Bot API to `127.0.0.1:8081`; do not open an inbound public port.
- Never place Telegram credentials in GitHub Actions, command-line arguments, logs, or the artifact.
- Protect `BOT_TOKEN` and `TELEGRAM_API_HASH` with current-user Windows DPAPI at rest.
- Keep `data/wbot.sqlite3` and `data/telegram-api/` across normal starts, stops, upgrades, and whole-folder moves.
- Delete per-request media under `temp/` after success, failure, cancellation, or stale-startup cleanup.
- Do not delete or modify the WispByte server or its remote files.
- Do not perform live Telegram handover or media-upload tests in CI.
- Use `work/repo.git` as `GIT_DIR` and the workspace root as `GIT_WORK_TREE`; the top-level `.git` is an accidental later repository and must not be deleted during this plan.

## Repository Preflight

Run every Git command in this plan in this form until the metadata is reconciled outside this scope:

```powershell
git --git-dir=work/repo.git --work-tree=. <command>
```

Verify the preserved baseline before editing:

```powershell
git --git-dir=work/repo.git --work-tree=. status --short
git --git-dir=work/repo.git --work-tree=. log -2 --oneline
```

Expected: clean status; `a31812c docs: design native Windows bot package` above `3de0eaa`.

---

### Task 1: Controlled Bot-Service Lifecycle

**Files:**
- Create: `src/wbot/service.py`
- Modify: `src/wbot/app.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `build_application(settings: Settings)` from `wbot.app`.
- Produces: `async run_until_stopped(application, stop_file: Path, ready_file: Path, poll_seconds: float = 0.25) -> None` and `run_service(settings: Settings, stop_file: Path, ready_file: Path) -> None`.

- [ ] **Step 1: Write lifecycle-order and cleanup tests**

Create a fake application/updater that records calls and a test that starts the runner, waits for
`ready_file`, creates `stop_file`, and asserts this order:

```python
events == [
    "initialize",
    "post_init",
    "updater.start_polling",
    "application.start",
    "updater.stop",
    "application.stop",
    "post_stop",
    "application.shutdown",
    "post_shutdown",
]
```

Add a second test whose fake `application.start()` raises. Assert that `ready_file` is never
created, initialized resources are shut down, and the original exception propagates. Add a third
test asserting stale `ready_file` and `stop_file` markers are removed before startup.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
python -m pytest tests/test_service.py -v
```

Expected: FAIL because `wbot.service` does not exist.

- [ ] **Step 3: Implement the explicit polling lifecycle**

Implement the runner with the same lifecycle order documented by python-telegram-bot's
`run_polling`, but wait on a package-local stop marker:

```python
async def run_until_stopped(
    application: Application[Any, Any, Any, Any, Any, Any],
    stop_file: Path,
    ready_file: Path,
    poll_seconds: float = 0.25,
) -> None:
    stop_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    initialized = started = polling = False
    try:
        await application.initialize()
        initialized = True
        if application.post_init is not None:
            await application.post_init(application)
        if application.updater is None:
            raise RuntimeError("polling updater is unavailable")
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        polling = True
        await application.start()
        started = True
        ready_file.touch(exist_ok=False)
        while not stop_file.exists():
            await asyncio.sleep(poll_seconds)
    finally:
        ready_file.unlink(missing_ok=True)
        if polling and application.updater is not None:
            await application.updater.stop()
        if started:
            await application.stop()
            if application.post_stop is not None:
                await application.post_stop(application)
        if initialized:
            await application.shutdown()
            if application.post_shutdown is not None:
                await application.post_shutdown(application)
```

`run_service` must call `asyncio.run(run_until_stopped(build_application(settings), ...))`.
Keep the existing `main()` and `run_polling()` path intact for legacy Linux/WispByte execution.

- [ ] **Step 4: Run lifecycle and regression tests**

Run:

```powershell
python -m pytest tests/test_service.py tests/test_access.py tests/test_publisher.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the lifecycle unit**

```powershell
git --git-dir=work/repo.git --work-tree=. add src/wbot/service.py src/wbot/app.py tests/test_service.py
git --git-dir=work/repo.git --work-tree=. commit -m "feat: add controlled bot service lifecycle"
```

---

### Task 2: Encrypted Portable Settings

**Files:**
- Create: `src/wbot/windows_config.py`
- Modify: `pyproject.toml`
- Test: `tests/test_windows_config.py`

**Interfaces:**
- Produces `PackagePaths.from_root(root: Path) -> PackagePaths` with `app`, `telegram_api`, `tools`, `data`, `logs`, `temp`, `settings_file`, `database`, `runtime_file`, `stop_file`, and `ready_file` paths, plus `ensure_runtime_directories() -> None`.
- Produces `SecretProtector` protocol with `protect(value: str) -> str` and `unprotect(value: str) -> str`.
- Produces `DpapiProtector`, `StoredSettings`, and `SettingsStore.load_runtime() -> Settings`.
- Produces `SettingsStore.save(api_id: int, api_hash: str, owner_id: int, bot_token: str) -> None`, `cloud_logout_complete() -> bool`, and `mark_cloud_logout_complete() -> None`.

- [ ] **Step 1: Write settings, path, encryption, and atomic-write tests**

Use a reversible fake protector so normal tests run on every platform:

```python
class FakeProtector:
    def protect(self, value: str) -> str:
        return f"protected:{value[::-1]}"

    def unprotect(self, value: str) -> str:
        assert value.startswith("protected:")
        return value.removeprefix("protected:")[::-1]
```

Cover these exact cases:

- A root containing spaces derives only package-relative paths.
- `save` writes version `1`, encrypted secrets, numeric IDs, the fixed five-minute and
  700,000,000-byte limits, and no plaintext token/hash.
- `load_runtime` returns the existing `Settings` object with loopback URL, SQLite path, and temp
  root under the package.
- Invalid non-positive IDs, blank/whitespace credentials, and malformed JSON fail with a sanitized
  `WindowsConfigError`.
- Re-saving configuration preserves `cloud_logout_complete` only when the bot token is unchanged;
  changing the token resets it to `false`.
- A simulated `Path.replace` failure leaves the previous settings file intact.
- On Windows only, a DPAPI round-trip returns the original Unicode secret and stored ciphertext
  does not contain the plaintext.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
python -m pytest tests/test_windows_config.py -v
```

Expected: FAIL because `wbot.windows_config` does not exist.

- [ ] **Step 3: Implement paths, JSON schema, and injectable protection**

Use these core types:

```python
@dataclass(frozen=True, slots=True)
class PackagePaths:
    root: Path
    app: Path
    telegram_api: Path
    tools: Path
    data: Path
    logs: Path
    temp: Path
    settings_file: Path
    database: Path
    runtime_file: Path
    stop_file: Path
    ready_file: Path

@dataclass(frozen=True, slots=True)
class StoredSettings:
    version: int
    telegram_api_id: int
    protected_api_hash: str
    owner_user_id: int
    protected_bot_token: str
    cloud_logout_complete: bool

class SecretProtector(Protocol):
    def protect(self, value: str) -> str: ...
    def unprotect(self, value: str) -> str: ...
```

Implement DPAPI with `CryptProtectData`/`CryptUnprotectData` via `ctypes`, current-user scope, no
optional entropy, and base64 for JSON storage. On non-Windows, constructing `DpapiProtector` must
raise `WindowsConfigError("Windows secret protection is unavailable")` rather than failing at
module import time.

Write JSON through `settings.json.tmp`, flush and `os.fsync`, then atomically replace the target.
Never include secret values in exception messages.

- [ ] **Step 4: Add the Windows process dependency**

Add to project dependencies:

```toml
"psutil>=7.0,<8; platform_system == 'Windows'",
```

Add `types-psutil>=7.0,<8` to `dev` if mypy requires it; otherwise keep the dependency list minimal.

- [ ] **Step 5: Run config and static checks**

```powershell
python -m pytest tests/test_windows_config.py tests/test_config.py -v
python -m ruff check src/wbot/windows_config.py tests/test_windows_config.py
python -m mypy src/wbot/windows_config.py
```

Expected: all PASS.

- [ ] **Step 6: Commit the settings unit**

```powershell
git --git-dir=work/repo.git --work-tree=. add pyproject.toml src/wbot/windows_config.py tests/test_windows_config.py
git --git-dir=work/repo.git --work-tree=. commit -m "feat: protect portable Windows settings"
```

---

### Task 3: Safe Process Identity, State, and Redacted Logs

**Files:**
- Create: `src/wbot/windows_process.py`
- Create: `src/wbot/windows_logs.py`
- Test: `tests/test_windows_process.py`
- Test: `tests/test_windows_logs.py`

**Interfaces:**
- Produces `ProcessIdentity(pid: int, executable: Path, create_time: float)` and `RuntimeState(api: ProcessIdentity | None, bot: ProcessIdentity | None)`.
- Produces `ProcessManager.start(...) -> ProcessIdentity`, `matches(identity) -> bool`, `wait(identity, timeout) -> bool`, and `terminate_verified(identity, timeout) -> bool`.
- Produces `RuntimeStateStore.load()`, `save(state)`, and `clear()`.
- Produces `redact(text: str, secrets: Iterable[str]) -> str` and `configure_rotating_log(path: Path, secrets: Iterable[str]) -> logging.Logger`.

- [ ] **Step 1: Write PID-reuse and process-ownership tests**

Use an injectable psutil adapter and fake `Popen` factory. Cover:

- Matching requires the same PID, normalized absolute executable path, and creation time within
  `0.01` seconds.
- A stale PID, changed executable, or changed creation time returns false.
- `terminate_verified` refuses to signal a mismatched process.
- `start` uses `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, a package root working directory,
  redirected append-mode logs, and a copied environment.
- Runtime JSON round-trips both identities, is atomically replaced, and malformed JSON is treated as
  stale state rather than trusted process ownership.

- [ ] **Step 2: Write redaction and log-rotation tests**

Assert that the exact token, exact API hash, and a Bot API URL containing the token are replaced by
`[REDACTED]`. Assert unrelated numeric chat IDs and normal exception class names remain. Configure a
logger with `RotatingFileHandler(maxBytes=5_000_000, backupCount=5, encoding="utf-8")` and verify its
filter redacts both messages and string arguments before formatting.

- [ ] **Step 3: Run focused tests and verify failure**

```powershell
python -m pytest tests/test_windows_process.py tests/test_windows_logs.py -v
```

Expected: FAIL because the modules do not exist.

- [ ] **Step 4: Implement process inspection without name-wide kills**

The process boundary must be explicit:

```python
@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    executable: Path
    create_time: float

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
    ) -> ProcessIdentity: ...

    def matches(self, identity: ProcessIdentity) -> bool: ...
    def wait(self, identity: ProcessIdentity, timeout: float) -> bool: ...
    def terminate_verified(self, identity: ProcessIdentity, timeout: float) -> bool: ...
```

Use `psutil.Process(pid).exe()` and `.create_time()` for verification. Catch only the documented
`NoSuchProcess`, `AccessDenied`, and `ZombieProcess` exceptions and fail closed. `terminate_verified`
must call `terminate`, wait, then `kill` only after re-verifying the same identity.

- [ ] **Step 5: Implement secret-aware rotating logs**

Create a logging `Filter` that rewrites `record.msg` to a preformatted, redacted string and clears
`record.args`. The controller logger may record component, action, sanitized exception class, and
exit code, but no source URL, Telegram text, downloaded filename, token, or hash.

- [ ] **Step 6: Run focused and static checks**

```powershell
python -m pytest tests/test_windows_process.py tests/test_windows_logs.py -v
python -m ruff check src/wbot/windows_process.py src/wbot/windows_logs.py tests/test_windows_process.py tests/test_windows_logs.py
python -m mypy src/wbot/windows_process.py src/wbot/windows_logs.py
```

Expected: all PASS.

- [ ] **Step 7: Commit the process-safety unit**

```powershell
git --git-dir=work/repo.git --work-tree=. add src/wbot/windows_process.py src/wbot/windows_logs.py tests/test_windows_process.py tests/test_windows_logs.py
git --git-dir=work/repo.git --work-tree=. commit -m "feat: manage Windows bot processes safely"
```

---

### Task 4: Local API Handover and Service Orchestration

**Files:**
- Create: `src/wbot/windows_service.py`
- Test: `tests/test_windows_service.py`

**Interfaces:**
- Consumes: `PackagePaths`, `SettingsStore`, `ProcessManager`, `RuntimeStateStore`, and `run_service`.
- Produces `ServiceStatus` enum with `SETUP_REQUIRED`, `STOPPED`, `PARTIAL`, and `RUNNING`.
- Produces `HandoverClient.log_out_cloud(bot_token: str) -> None` and `probe_local(bot_token: str) -> None`.
- Produces `WindowsServiceController.start()`, `stop()`, `status()`, and `run_bot_child()`.

- [ ] **Step 1: Write orchestration decision tests with fakes**

Cover these state-machine cases without opening a real socket or calling Telegram:

1. Missing settings returns `SETUP_REQUIRED` and starts nothing.
2. Both verified children plus a successful local probe make `start` idempotent.
3. A free port starts the API with `--local`, `--http-ip-address=127.0.0.1`,
   `--http-port=8081`, package `--dir`, and package `--temp-dir`.
4. The API ID/hash are inherited environment variables and are absent from arguments.
5. First start calls cloud `logOut` once, marks completion only after success, probes local, starts
   the bot child, and waits for `ready_file` before returning `RUNNING`.
6. Cloud failure leaves the marker false and stops only children created by that call.
7. A completed handover skips cloud logout on later starts.
8. Port 8081 occupied by an unowned process raises the exact short error without signaling it.
9. Stop creates the bot stop marker, waits up to 15 seconds, uses verified termination only as a
   fallback, stops API second, and clears runtime markers.
10. A stale or half-running state reports `PARTIAL`; `start` cleans only verified recorded children
    before one recovery attempt.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
python -m pytest tests/test_windows_service.py -v
```

Expected: FAIL because `wbot.windows_service` does not exist.

- [ ] **Step 3: Implement sanitized Telegram handover HTTP calls**

Use a dedicated `httpx.Client(timeout=20, trust_env=False)` and never log the URL or response body:

```python
class HandoverClient:
    def log_out_cloud(self, bot_token: str) -> None:
        response = self._http.post(f"https://api.telegram.org/bot{bot_token}/logOut")
        if response.status_code != 200 or response.json().get("ok") is not True:
            raise WindowsServiceError("Telegram handover failed. Try Start Bot again.")

    def probe_local(self, bot_token: str) -> None:
        response = self._http.post(f"http://127.0.0.1:8081/bot{bot_token}/getMe")
        if response.status_code != 200 or response.json().get("ok") is not True:
            raise WindowsServiceError("The local Telegram service did not accept the bot.")
```

Catch HTTP and JSON errors and replace them with those sanitized errors. The HTTP client must not
have event hooks that log requests.

- [ ] **Step 4: Implement start, readiness, status, and stop**

Build the Telegram API arguments from package paths, never secrets:

```python
api_args = (
    "--local",
    "--http-ip-address=127.0.0.1",
    "--http-port=8081",
    f"--dir={paths.data / 'telegram-api'}",
    f"--temp-dir={paths.temp / 'telegram-api'}",
    f"--log={paths.logs / 'telegram-api.log'}",
    "--log-max-file-size=10000000",
    "--verbosity=0",
)
```

Pass `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` only in the copied child environment. Start the bot
child as `app/w-bot.exe run-bot`; that child reloads/decrypts its own package settings and calls
`run_service` with the stop/ready paths. Ensure `tools/` is prepended only to the child `PATH` so
yt-dlp finds the bundled FFmpeg.

Wait up to 30 seconds for the API port, up to 30 seconds for local `getMe`, and up to 30 seconds for
the bot ready marker. On any exception, run one verified rollback and preserve the sanitized cause
in `controller.log`.

Before `run_bot_child` calls `run_service`, configure the process root logger with the redacting
rotating handler from Task 3. Telegram API verbosity remains zero so its own file does not contain
per-request paths carrying the bot token.

- [ ] **Step 5: Run orchestration and regression tests**

```powershell
python -m pytest tests/test_windows_service.py tests/test_service.py tests/test_workspace.py -v
python -m ruff check src/wbot/windows_service.py tests/test_windows_service.py
python -m mypy src/wbot/windows_service.py
```

Expected: all PASS.

- [ ] **Step 6: Commit the orchestration unit**

```powershell
git --git-dir=work/repo.git --work-tree=. add src/wbot/windows_service.py tests/test_windows_service.py
git --git-dir=work/repo.git --work-tree=. commit -m "feat: orchestrate local Telegram services on Windows"
```

---

### Task 5: One-Click CLI, Command Files, and Desktop Shortcuts

**Files:**
- Create: `src/wbot/windows_cli.py`
- Create: `scripts/windows_entry.py`
- Create: `packaging/windows/Setup Bot.cmd`
- Create: `packaging/windows/Start Bot.cmd`
- Create: `packaging/windows/Stop Bot.cmd`
- Create: `packaging/windows/Bot Status.cmd`
- Create: `packaging/windows/Show Bot Logs.cmd`
- Create: `packaging/windows/Create Desktop Shortcuts.cmd`
- Create: `packaging/windows/scripts/create-shortcuts.ps1`
- Test: `tests/test_windows_cli.py`
- Test: `tests/test_windows_controls.py`

**Interfaces:**
- Produces `windows_cli.main(argv: Sequence[str] | None = None) -> int` with `setup`, `start`, `stop`, `status`, `logs`, `run-bot`, `create-shortcuts`, and `--version`.
- Produces `create_shortcuts(paths: PackagePaths) -> None`, which invokes the packaged script with a separate root argument.
- `.cmd` wrappers invoke only `app\w-bot.exe <subcommand>` resolved from `%~dp0`.

- [ ] **Step 1: Write CLI tests with injected console and controller**

Cover hidden `getpass` entry for token/hash, positive-integer retry for IDs, sanitized setup errors,
status exit codes, idempotent start/stop messages, `KeyboardInterrupt` in log following, and
`run-bot` refusing direct use before setup. Assert no captured output contains supplied secrets.

- [ ] **Step 2: Write static control-file tests**

Read the packaging templates and assert:

- Every wrapper uses quoted `%~dp0app\w-bot.exe` and the correct one-word subcommand.
- Error paths use `if errorlevel 1 pause`.
- No wrapper contains a credential placeholder.
- The shortcut script creates exactly `Start W Bot.lnk`, `Stop W Bot.lnk`, `W Bot Status.lnk`, and
  `W Bot Logs.lnk` on `[Environment]::GetFolderPath('Desktop')`.
- Shortcut targets are the package `.cmd` files and `WorkingDirectory` is the package root.
- The PowerShell script uses `$WshShell.CreateShortcut(...)` and overwrites only those exact paths.

- [ ] **Step 3: Run focused tests and verify failure**

```powershell
python -m pytest tests/test_windows_cli.py tests/test_windows_controls.py -v
```

Expected: FAIL because the CLI/templates do not exist.

- [ ] **Step 4: Implement the CLI and local setup flow**

Use `argparse` subparsers and dependency injection for tests. Setup must:

```python
bot_token = getpass.getpass("Bot token: ").strip()
api_id = read_positive_int("Telegram API ID: ")
api_hash = getpass.getpass("Telegram API hash: ").strip()
owner_id = read_positive_int("Owner Telegram user ID: ")
store.save(api_id=api_id, api_hash=api_hash, owner_id=owner_id, bot_token=bot_token)
paths.ensure_runtime_directories()
create_shortcuts(paths)
```

Print `Setup complete.` only after the atomic settings save and shortcut helper succeed. `start`
prints `W Bot is running.` only for `RUNNING`. `stop` prints `W Bot is stopped.`. `status` prints
exactly one status plus at most one remediation line.

For `logs`, print the last 100 lines of `controller.log`, `bot.log`, and `telegram-api.log`, then
poll for appended lines until Ctrl+C. Closing this foreground viewer must not signal services.

- [ ] **Step 5: Implement wrappers and shortcuts**

Each wrapper follows this exact shape:

```bat
@echo off
"%~dp0app\w-bot.exe" start
if errorlevel 1 pause
```

Substitute only the command for other files. `Create Desktop Shortcuts.cmd` uses
`create-shortcuts`; the executable invokes the packaged PowerShell file with
`powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File`, passing the root as a
separate argument rather than interpolating it into script source.

- [ ] **Step 6: Run CLI/static checks**

```powershell
python -m pytest tests/test_windows_cli.py tests/test_windows_controls.py -v
python -m ruff check src/wbot/windows_cli.py scripts/windows_entry.py tests/test_windows_cli.py tests/test_windows_controls.py
python -m mypy src/wbot/windows_cli.py
```

Expected: all PASS.

- [ ] **Step 7: Commit the control surface**

```powershell
git --git-dir=work/repo.git --work-tree=. add src/wbot/windows_cli.py scripts/windows_entry.py packaging/windows tests/test_windows_cli.py tests/test_windows_controls.py
git --git-dir=work/repo.git --work-tree=. commit -m "feat: add one-click Windows bot controls"
```

---

### Task 6: PyInstaller and Portable-Folder Assembly

**Files:**
- Create: `packaging/windows/w-bot.spec`
- Create: `packaging/windows/assemble-package.ps1`
- Create: `packaging/windows/verify-package.ps1`
- Create: `packaging/windows/README-WINDOWS.txt`
- Create: `packaging/windows/THIRD-PARTY-NOTICES.txt`
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Test: `tests/test_windows_package.py`

**Interfaces:**
- `assemble-package.ps1 -BotDist <dir> -TelegramApi <exe> -FfmpegRoot <dir> -Output <dir>` creates exactly one `W-Bot` tree.
- `verify-package.ps1 -PackageRoot <dir>` exits nonzero on a missing/extra-sensitive file or failed executable smoke test.

- [ ] **Step 1: Write package-manifest tests**

Assert the assembly script requires and copies:

```text
Setup Bot.cmd
Start Bot.cmd
Stop Bot.cmd
Bot Status.cmd
Show Bot Logs.cmd
Create Desktop Shortcuts.cmd
app/w-bot.exe
telegram-api/telegram-bot-api.exe
tools/ffmpeg.exe
tools/ffprobe.exe
scripts/create-shortcuts.ps1
README-WINDOWS.txt
THIRD-PARTY-NOTICES.txt
```

Assert it rejects an output tree containing `settings.json`, `runtime.json`, `.env`, `*.sqlite3`,
or a token-shaped string. Assert the verifier runs `w-bot.exe --version`,
`telegram-bot-api.exe --version`, `ffmpeg.exe -version`, and `ffprobe.exe -version`.

- [ ] **Step 2: Run package tests and verify failure**

```powershell
python -m pytest tests/test_windows_package.py -v
```

Expected: FAIL because the spec and assembly scripts do not exist.

- [ ] **Step 3: Add constrained build dependencies and PyInstaller spec**

Add this optional dependency group:

```toml
windows-build = [
  "pyinstaller==6.16.0",
]
```

The PyInstaller spec must use `collect_all("yt_dlp")`, collect necessary `telegram` and `certifi`
data, use `scripts/windows_entry.py` as the entry script, set `console=True`, and produce one-folder
`w-bot`. Do not embed settings, `data/`, `logs/`, `temp/`, `.env`, tests, WispByte material, or Docker
material.

- [ ] **Step 4: Implement deterministic assembly and verification**

The assembly script uses `Copy-Item -LiteralPath`, creates only the specified directories, copies
all FFmpeg runtime DLLs if present, and copies license files alongside notices. Before zipping, scan
text-like files for these forbidden names and token pattern:

```powershell
$ForbiddenNames = @('settings.json', 'runtime.json', '.env', 'wbot.sqlite3')
$TokenPattern = '[0-9]{6,12}:[A-Za-z0-9_-]{30,}'
```

The verifier fails if `data`, `logs`, or `temp` already contains user files. Empty runtime folders
may be absent because setup creates them.

- [ ] **Step 5: Write Windows user documentation and notices**

`README-WINDOWS.txt` must explain extract, setup, start, stop, status, logs, shortcut recreation,
whole-folder moves, sleep/offline behavior, local disk use, upgrades that preserve `data`, and the
warning never to share `data/settings.json`. It must state that moving to another Windows user or
computer requires setup again.

`THIRD-PARTY-NOTICES.txt` must name and link the exact Telegram Bot API commit, Python packages,
PyInstaller, psutil, and the exact FFmpeg asset/license. Include copied license texts required by
the built components in adjacent `licenses/` folders.

- [ ] **Step 6: Run package/static checks**

```powershell
python -m pytest tests/test_windows_package.py tests/test_windows_controls.py -v
python -m ruff check .
python -m mypy src/wbot
```

Expected: all PASS.

- [ ] **Step 7: Commit portable assembly**

```powershell
git --git-dir=work/repo.git --work-tree=. add pyproject.toml .gitignore packaging/windows tests/test_windows_package.py
git --git-dir=work/repo.git --work-tree=. commit -m "build: assemble portable Windows bot package"
```

---

### Task 7: Windows GitHub Actions Build

**Files:**
- Create: `.github/workflows/build-windows-package.yml`
- Test: `tests/test_windows_workflow.py`

**Interfaces:**
- Manual `workflow_dispatch` creates artifact `w-bot-windows-x64` containing only `w-bot-windows-x64.zip` for 30 days.

- [ ] **Step 1: Write workflow-policy tests**

Parse the workflow as text/YAML and assert:

- `workflow_dispatch` only; `permissions: contents: read`; `runs-on: windows-2022`.
- Checkout, setup-python, cache, and upload-artifact use full 40-character action SHAs.
- Telegram source commit is exactly `adfd7f6a8e990272851777eeb3ae0def4216f161` and is verified
  with `git rev-parse HEAD`.
- FFmpeg URL is exactly
  `https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-02-28-12-59/ffmpeg-n8.0.1-66-g27b8d1a017-win64-lgpl-8.0.zip`.
- FFmpeg SHA-256 is exactly
  `EF2B1179F226C7A953675623BFF13E38ECD806A425F6F229E44660ABDCD0C077`.
- No `secrets.`, `BOT_TOKEN`, `TELEGRAM_API_HASH`, `TELEGRAM_API_ID`, or `OWNER_USER_ID` expression is
  present.
- Tests, Ruff, mypy, packaged smoke checks, ZIP checksum, and artifact upload all precede success.

- [ ] **Step 2: Run workflow test and verify failure**

```powershell
python -m pytest tests/test_windows_workflow.py -v
```

Expected: FAIL because the workflow does not exist.

- [ ] **Step 3: Implement the credential-free Windows build**

Pin these stable action revisions:

```yaml
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
- uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
- uses: actions/cache@5a3ec84eff668545956fd18022155c47e93e2684
- uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
```

Use Python `3.12`, install `.[dev,windows-build]`, and run:

```powershell
python -m pytest -m "not live"
python -m ruff check .
python -m mypy src/wbot
```

Build Telegram Bot API with the Windows runner's MSVC, CMake, and vcpkg using
`x64-windows-static`. Fetch only the pinned commit, verify it, initialize recursive submodules, add
vcpkg's gperf tools directory to `PATH`, then run these dependency and build commands:

```powershell
& "$env:VCPKG_INSTALLATION_ROOT\vcpkg.exe" install `
  gperf:x64-windows `
  openssl:x64-windows-static `
  zlib:x64-windows-static
$env:PATH = "$env:VCPKG_INSTALLATION_ROOT\installed\x64-windows\tools\gperf;$env:PATH"
cmake -S telegram-bot-api-source -B telegram-bot-api-build -A x64 `
  -DCMAKE_TOOLCHAIN_FILE="$env:VCPKG_INSTALLATION_ROOT/scripts/buildsystems/vcpkg.cmake" `
  -DVCPKG_TARGET_TRIPLET=x64-windows-static `
  -DCMAKE_INSTALL_PREFIX="$pwd/telegram-bot-api-install"
cmake --build telegram-bot-api-build --config Release --target install --parallel 2
```

Download FFmpeg to a temporary build directory, verify with `Get-FileHash -Algorithm SHA256`, and
fail before extraction on any mismatch. Build PyInstaller from `packaging/windows/w-bot.spec`, call
the assembly and verifier scripts, compress `W-Bot` to `w-bot-windows-x64.zip`, and print its SHA-256.

- [ ] **Step 4: Run workflow and complete local regression checks**

```powershell
python -m pytest tests/test_windows_workflow.py tests/test_windows_package.py -v
python -m pytest -m "not live"
python -m ruff check .
python -m mypy src/wbot
```

Expected: all PASS; existing live probe remains unexecuted.

- [ ] **Step 5: Commit the Windows build workflow**

```powershell
git --git-dir=work/repo.git --work-tree=. add .github/workflows/build-windows-package.yml tests/test_windows_workflow.py
git --git-dir=work/repo.git --work-tree=. commit -m "ci: build portable Windows bot package"
```

---

### Task 8: Primary Documentation, Final Verification, and Artifact Handoff

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Test: `tests/test_windows_documentation.py`

**Interfaces:**
- Main README directs ordinary Windows users to Actions → Build Portable Windows Package → Run workflow → download artifact.
- Legacy WispByte documentation remains available but is labeled optional/legacy.

- [ ] **Step 1: Write documentation contract tests**

Assert README includes: Windows prerequisites, Actions download steps, setup/start/stop/status/log
names, shortcut behavior, PC awake/online requirement, no port forwarding, DPAPI explanation,
`data/` backup warning, upgrade instructions, no-Docker statement, and Local Bot API first-start
handover. Assert `.env.example` remains explicitly for container/legacy deployment and contains no
real credential.

- [ ] **Step 2: Run documentation tests and verify failure**

```powershell
python -m pytest tests/test_windows_documentation.py -v
```

Expected: FAIL because README does not yet describe the Windows package.

- [ ] **Step 3: Update the main documentation**

Lead README with the Windows package as the recommended home-hosting path. Include this user flow:

```text
1. Open the repository's Actions tab.
2. Select “Build Portable Windows Package”.
3. Choose “Run workflow”.
4. Download “w-bot-windows-x64” after the green run completes.
5. Extract the ZIP and double-click “Setup Bot.cmd”.
6. Use the Desktop “Start W Bot” and “Stop W Bot” shortcuts.
```

Explain that GitHub receives no credentials; setup prompts locally. Warn not to use
`docker compose down -v` only in the legacy Docker section, not as part of the Windows flow.

- [ ] **Step 4: Run the complete non-live verification suite**

```powershell
python -m pytest -m "not live"
python -m ruff check .
python -m mypy src/wbot
git --git-dir=work/repo.git --work-tree=. diff --check
```

Expected: every test passes, Ruff and mypy emit no errors, and `diff --check` is empty.

- [ ] **Step 5: Review secret and package boundaries**

Run:

```powershell
rg -n "BOT_TOKEN=.+|TELEGRAM_API_HASH=.+|[0-9]{6,12}:[A-Za-z0-9_-]{30,}" . `
  -g '!work/**' -g '!docs/superpowers/plans/**'
```

Expected: no real secret assignment or token-shaped value. Inspect every match manually; examples
and variable names are allowed only when value-free.

- [ ] **Step 6: Commit documentation and verification contract**

```powershell
git --git-dir=work/repo.git --work-tree=. add README.md .env.example tests/test_windows_documentation.py
git --git-dir=work/repo.git --work-tree=. commit -m "docs: make Windows package the primary setup"
```

- [ ] **Step 7: Publish and build without credentials**

Verify `https://github.com/devilkyuuu/w-bot.git` is the intended repository, add it as `origin` to
`work/repo.git` only if that remote is absent, fetch `main`, and prove the push is fast-forward with:

```powershell
git --git-dir=work/repo.git --work-tree=. merge-base --is-ancestor origin/main HEAD
git --git-dir=work/repo.git --work-tree=. push origin HEAD:main
```

Do not push if the ancestry check fails; report the divergence instead of rebasing or forcing.
Using the already authenticated GitHub session, trigger `build-windows-package.yml` manually, wait
for the run, inspect all failed steps if any, and download the artifact. Verify the downloaded ZIP
SHA-256 matches the workflow output and rerun `packaging/windows/verify-package.ps1` against the
extracted folder.

Expected: a green GitHub Actions run and a verified `w-bot-windows-x64.zip`. Do not run
`Setup Bot.cmd`, call Telegram `logOut`, or start the production bot during automated verification.

- [ ] **Step 8: Final handoff**

Give the user a direct link to the successful Actions run/artifact page plus these exact next
actions: download, extract to a local non-synchronized folder, run setup once, then use the Desktop
start/stop shortcuts. State that the first Start performs the Telegram cloud-to-local handover and
that the PC must remain awake and online.

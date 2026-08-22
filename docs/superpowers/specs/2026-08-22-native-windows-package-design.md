# Native Windows Package Design

## Purpose

Create a portable Windows x64 distribution of the private Telegram `/w` media bot. The user
downloads one ZIP produced by their own GitHub repository, extracts the folder, runs setup once,
and controls the bot through double-clickable command files or Desktop shortcuts. Docker, Python,
Visual Studio, CMake, and a separately installed FFmpeg are not required on the user's computer.

The bot's Telegram behavior does not change: approved groups use `/w <link>`, the bot sends only
the useful result or a short error, videos are limited to five minutes and at most 1080p, product
galleries contain at most five images, and Telegram Group Privacy Mode remains enabled.

## Supported Environment

- Windows 10 or Windows 11 on x64 hardware.
- One interactive Windows user owns and operates the package.
- The PC must be powered on, awake, and online while the bot is available.
- The package uses outbound HTTPS connections and a loopback-only HTTP connection. It opens no
  inbound port on the router and needs no public hostname.
- The extracted package folder can live at any writable local path, including a path containing
  spaces. Network shares and folders synchronized by cloud-storage clients are unsupported because
  they make process state, SQLite locking, and secret storage less predictable.

## Distribution Architecture

The repository gains a manually triggered GitHub Actions workflow that runs on a pinned Windows
x64 runner image and produces `w-bot-windows-x64.zip`. The ZIP contains four runtime layers:

1. A PyInstaller one-folder build of the Python bot and a Windows controller executable named
   `w-bot.exe`. One-folder mode is chosen over PyInstaller one-file mode to avoid repeated temporary
   extraction, slow startup, and additional antivirus false positives.
2. `telegram-bot-api.exe` and its required DLLs, compiled in the workflow from the official TDLib
   `telegram-bot-api` repository at commit
   `adfd7f6a8e990272851777eeb3ae0def4216f161`. The server always runs with `--local` and listens only
   on `127.0.0.1:8081`.
3. `ffmpeg.exe`, `ffprobe.exe`, and their required DLLs from a Windows build provider linked by the
   official FFmpeg download page. The workflow downloads an immutable x64 build asset and verifies
   it against the SHA-256 checksum published for that asset before packaging it.
4. Small `.cmd` wrappers and a PowerShell shortcut helper. The wrappers resolve the package root
   from `%~dp0`, so the whole extracted folder can be moved. The `.cmd` files themselves remain in
   that folder; Desktop shortcuts may be moved, renamed, or pinned normally.

The workflow contains no Telegram credentials. GitHub Actions logs and artifacts therefore cannot
contain the bot token, Telegram API hash, or owner identity supplied during local setup.

## Package Layout

The extracted directory has this stable layout:

```text
W-Bot/
  Setup Bot.cmd
  Start Bot.cmd
  Stop Bot.cmd
  Bot Status.cmd
  Show Bot Logs.cmd
  Create Desktop Shortcuts.cmd
  app/
    w-bot.exe
    ...PyInstaller runtime files...
  telegram-api/
    telegram-bot-api.exe
    ...required DLLs and licenses...
  tools/
    ffmpeg.exe
    ffprobe.exe
    ...required DLLs and licenses...
  scripts/
    create-shortcuts.ps1
  data/                 created by setup
    settings.json
    wbot.sqlite3        created on first bot start
    runtime.json        present only while processes are owned by the controller
    telegram-api/       Telegram Local Bot API persistent working data
  logs/                 created by setup
  temp/                 created by setup; job contents are disposable
  README-WINDOWS.txt
  THIRD-PARTY-NOTICES.txt
```

`data/`, `logs/`, and `temp/` are never included in a build artifact with user content. Replacing
the application files for an upgrade must preserve `data/`.

## Windows Controller

The packaged `w-bot.exe` exposes these public subcommands, which are called by the matching command
files:

- `setup`: collect and validate configuration, create runtime directories, protect secrets, and
  create or refresh Desktop shortcuts.
- `start`: start the Telegram Local Bot API and bot in the background, or report that both are
  already running.
- `stop`: request a graceful bot shutdown, then stop the Telegram API process started by this
  package.
- `status`: report `Running`, `Partially running`, `Stopped`, or `Setup required`, with a short
  remediation when applicable.
- `logs`: print the most recent bot and Telegram API log lines and continue following them until the
  log window is closed or Ctrl+C is pressed.
- `run-bot`: internal service entry point used only by `start`.

Every `.cmd` wrapper keeps its console window open when an error occurs so the user can read the
message. Start and stop are idempotent. Starting twice does not create duplicate processes, and
stopping an already stopped package succeeds without killing unrelated processes.

The controller records each child PID, executable path, and process creation time in
`data/runtime.json`. Before signaling or terminating a PID, it verifies all three values to defend
against Windows PID reuse. It never uses a broad process-name kill.

The bot service watches a package-local stop signal and shuts down Telegram polling and its HTTP
client before exiting. `stop` waits for that graceful exit for a bounded interval. Only if the bot
does not exit does the controller terminate that verified child process. The Telegram API process
is stopped after the bot and is also constrained to the verified recorded process.

## Configuration and Secret Handling

`setup` prompts locally for:

- `BOT_TOKEN`, entered without echo.
- `TELEGRAM_API_ID`, validated as a positive integer.
- `TELEGRAM_API_HASH`, entered without echo.
- `OWNER_USER_ID`, validated as a positive integer.

The bot token and API hash are encrypted with Windows Data Protection API using current-user scope
before being stored in `data/settings.json`. The plaintext values exist only in the setup process
and the environments or memory of the two running child processes. Another Windows account, or the
same files copied to another computer, cannot decrypt them; running setup again is the recovery
path after such a move. The non-secret numeric IDs and runtime limits remain plaintext.

The controller passes Telegram credentials to child processes through inherited environment
variables, never command-line arguments. It redacts tokens and hashes from exceptions and logs.
Neither the bot nor the controller logs Telegram message text, source URLs, downloaded filenames,
or credentials.

The fixed local settings are:

```text
DATABASE_PATH=<package>\data\wbot.sqlite3
TELEGRAM_LOCAL_API_BASE_URL=http://127.0.0.1:8081
MEDIA_TMP_ROOT=<package>\temp\media
MAX_DOWNLOAD_BYTES=700000000
MAX_VIDEO_SECONDS=300
```

## First Start and Telegram Handover

The bot must be moved from Telegram's cloud Bot API to the Local Bot API exactly once. The first
successful `start` performs this sequence:

1. Validate that setup is complete and that port 8081 is free.
2. Start the package's Telegram Local Bot API bound to `127.0.0.1:8081` with its persistent working
   directory under `data/telegram-api/` and a disposable temporary directory under `temp/`.
3. Call Telegram's cloud `logOut` method without logging the request URL or response body.
4. Mark cloud logout complete only after Telegram confirms success.
5. Initialize the bot token against the local endpoint and start the bot polling process.

If cloud logout or local initialization fails, `start` stops the processes it created, leaves a
short redacted diagnostic in the local log, and reports a short actionable error. A failed cloud
logout is retried on the next start. After successful handover, future starts skip the cloud call.
The package never calls cloud `close` and never moves the bot back to the cloud API automatically.

## Media Storage and Cleanup

Each `/w` job receives a random child directory under `temp/`. The existing workspace abstraction
removes that directory after success, failure, or cancellation. Startup also removes stale job
directories left by a crash. Telegram Local Bot API working data remains under
`data/telegram-api/`; it is persistent application state, not part of the per-job media allowance.

The controller does not delete `data/wbot.sqlite3`, so group approvals survive normal starts,
stops, upgrades, and application-folder moves. There is no reset or uninstall command in this
version. The documentation identifies which folders may be manually removed and warns that deleting
`data/` loses configuration and approvals.

## Desktop Shortcuts and Folder Moves

Setup creates four Desktop shortcuts for the current user:

- Start W Bot
- Stop W Bot
- W Bot Status
- W Bot Logs

Each shortcut targets its corresponding `.cmd` file and starts in the current package directory.
Running `Create Desktop Shortcuts.cmd` or `Setup Bot.cmd` replaces only shortcuts with those exact
names and points them at the package's current location. If the whole folder is moved, setup can
refresh the shortcuts without changing saved configuration. Moving an individual `.cmd` outside
the package is unsupported; copying or moving a shortcut is supported.

## Build Provenance and Release Safety

The Windows workflow is manual (`workflow_dispatch`) and has read-only repository permissions. It
performs these gates before uploading the ZIP:

- Run the existing Python test suite, Ruff, and strict mypy checks.
- Build the Telegram Local Bot API from the pinned official source commit and verify the checked-out
  commit before compilation.
- Install Python build dependencies at constrained versions and create the PyInstaller one-folder
  application.
- Verify the downloaded FFmpeg archive checksum before extraction.
- Run Windows controller unit tests, a packaged-executable smoke test, and a package-layout test.
- Generate `THIRD-PARTY-NOTICES.txt` and include the licenses shipped with Telegram Bot API,
  PyInstaller dependencies, and FFmpeg.
- Upload only `w-bot-windows-x64.zip`, retaining the artifact for 30 days.

GitHub Actions used by the workflow are pinned to full commit SHAs rather than floating version
tags. The workflow prints source versions and final artifact SHA-256 values without printing
secrets. Live Telegram credentials are deliberately absent, so the workflow does not perform a real
Telegram handover or media upload.

The existing WispByte/Linux build workflow and deployment notes remain in the repository as legacy
material, but the main README points Windows users to the portable package. They are not executed by
the Windows workflow.

## Error Handling

User-facing controller errors are short and concrete, for example:

- `Setup is required. Run Setup Bot.cmd first.`
- `Port 8081 is already in use. Close the other program and try again.`
- `The bot could not start. Open W Bot Logs for details.`
- `This package was configured by another Windows user. Run setup again.`

Detailed local logs include timestamps, component names, exit codes, and redacted exception text.
Logs rotate by size so an unattended bot cannot consume the disk indefinitely. At most five recent
files per component are kept. Start never claims success until both child processes are alive and
the local Bot API responds successfully.

Runtime failures inside Telegram retain the existing behavior: no progress message, only the
functional result or the existing short chat error. Windows controller errors are never posted to a
Telegram group.

## Testing and Acceptance Criteria

Unit tests must cover:

- Windows path derivation when the package path contains spaces.
- Settings validation plus DPAPI encryption/decryption boundaries using an injectable protector.
- Redaction of the token and API hash from errors and logs.
- Runtime-state validation, stale PID handling, and refusal to stop an unrelated reused PID.
- Idempotent start and stop decisions.
- First-start handover state: mark only after confirmed cloud logout, retry after failure, and skip
  after success.
- Command-wrapper mapping and required package layout.
- Shortcut generation using the current package location.

The GitHub Actions artifact is accepted when all of these are true on a clean Windows x64 account:

1. The ZIP extracts and setup completes without Docker, Python, FFmpeg, Visual Studio, or CMake
   installed.
2. Setup creates working Desktop shortcuts and never echoes either secret.
3. Start launches both services without visible background console windows; status reports
   `Running`.
4. The owner can approve a Telegram group and `/w` continues to produce the previously specified
   media and product outputs.
5. Stop shuts down only this package's recorded processes; status reports `Stopped`.
6. Restart preserves approved groups.
7. Moving the whole stopped package folder and recreating shortcuts preserves configuration and
   approvals.
8. Closing the logs window does not stop either service.
9. No credential, Telegram message text, source URL, or downloaded filename appears in GitHub logs
   or local application logs.

Real Telegram handover and media-source checks are manual acceptance tests because CI must not hold
production credentials. The automated suite remains fully offline except for dependency and source
acquisition performed by the build workflow.

## Explicit Non-Goals

- Running continuously while the Windows PC is off, asleep, or disconnected.
- Windows ARM64, macOS, or Linux desktop packages.
- Automatic startup at Windows sign-in or Task Scheduler integration.
- A graphical settings application, tray icon, installer, Windows service, or automatic updater.
- Multiple independent bot configurations in one extracted folder.
- Publishing Telegram credentials as GitHub Secrets.
- Automatically deleting or modifying the abandoned WispByte server.

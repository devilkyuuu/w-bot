# Telegram media bot

This bot replies when a supported link is sent by itself, with no progress chatter.

Supported sources:

- TikTok and public Facebook videos: playable MP4, up to five minutes and 1080p.
- Public X posts: text, up to four photos, video.
- AmiAmi and Nin-Nin Game products: up to five product images plus name, manufacturer, yen price,
  and approximate euro price from the ECB reference rate. AmiAmi Global links are resolved through
  the matching Japanese product page and include a best-effort English title translation.

## Recommended: portable Windows package

The simplest home-hosting option is the portable package for 64-bit Windows 10 or Windows 11.
Docker is not required, and the package already contains Python, FFmpeg, and Telegram's Local Bot
API. No port forwarding or public inbound port is needed: the local service binds only to
`127.0.0.1:8081`.

### Build and download

1. Open the repository's **Actions** tab.
2. Select **Build Portable Windows Package**.
3. Choose **Run workflow**. Wait for the build to finish.
4. Download **w-bot-windows-x64** from the completed workflow's artifacts.

GitHub never receives the bot token, Telegram API hash, owner ID, approved group IDs, or local
configuration: the workflow builds only the public program files.

### Installation

1. Extract the ZIP to a local folder.
2. In the extracted `W-Bot` folder, double-click **Setup Bot.cmd** once.

Setup asks locally for the BotFather token, Telegram API ID, Telegram API hash, and owner user ID.
The token and API hash are encrypted at rest with current-user
Windows DPAPI; another computer or Windows user cannot decrypt them and must run setup again.

Setup creates four Desktop shortcuts: **Start W Bot**, **Stop W Bot**, **W Bot Status**, and
**W Bot Logs**. The package also keeps its direct controls:

- `Start Bot.cmd` starts both background services and is safe to use when they are already running.
- `Stop Bot.cmd` gracefully stops the bot, then stops its recorded Local Bot API process.
- `Bot Status.cmd` reports running, stopped, partial, or setup-required state.
- `Show Bot Logs.cmd` follows local diagnostic logs; closing it does not stop the bot.
- `Create Desktop Shortcuts.cmd` refreshes shortcuts after the package folder moves.

The PC must remain awake, online, and logged in while the bot should respond. Sleep, shutdown,
sign-out, or loss of internet makes it temporarily unavailable.

### First start, files, and upgrades

The first successful Start transfers the bot from Telegram's cloud Bot API to the package's Local
Bot API. A failed handover is retried on the next Start; later successful starts do not repeat the
cloud logout.

Configuration, approved group IDs, and persistent Local Bot API state are under `data/`. Always
back up `data/` before an upgrade, and never share `data/settings.json`. Temporary downloads live
under `temp/` and are deleted after each request.

Stop the bot before moving the entire `W-Bot` folder, then run `Create Desktop Shortcuts.cmd` from
its new location. For an upgrade, stop both services, extract the new package separately, and copy
the old `data/` folder into the new stopped package. When moving to another computer or Windows
user, copy approvals only if appropriate and run setup again so its secrets are protected for that
user and machine.

## Telegram setup

1. Create the bot with `@BotFather` and keep the token private.
2. In BotFather, run `/setprivacy`, select the bot, and choose **Disable**. Telegram must deliver
   ordinary group messages so the bot can recognize links that are not commands.
3. Run `/setcommands` and enter:

   ```text
   approve - Allow this group (owner only)
   revoke - Remove this group (owner only)
   ```

4. Add the bot to a group as an ordinary member. Never grant administrator rights.
5. The owner sends `/approve` in that group once. `/revoke` disables it again.

Telegram delivers ordinary group text to the bot after Privacy Mode is disabled. The bot checks
locally for one supported standalone link, silently ignores everything else, and does not log
message text. It also ignores unapproved groups and other users' private chats. It stores only
approved numeric group IDs in a small local SQLite database.

## Supported link messages

```text
https://www.tiktok.com/...
https://www.facebook.com/...
https://x.com/.../status/...
https://www.amiami.com/eng/detail?gcode=...
https://www.nin-nin-game.com/en/...html
```

The message must contain only one HTTPS URL. Unsupported links and ordinary conversation are
silent. A supported link that cannot be retrieved receives one short error reply.

## Optional legacy hosting

The portable Windows package is the recommended route. `wispbyte/README.md` documents the earlier
single-server container deployment, and `northflank/` contains the older Northflank packaging.
Those paths require Docker-compatible hosting and environment variables; they are optional legacy
alternatives, not part of the Windows setup.

### Legacy runtime configuration

Never commit real values. Configure these as encrypted runtime values:

```text
BOT_TOKEN
TELEGRAM_API_ID
TELEGRAM_API_HASH
OWNER_USER_ID
```

Configuration:

```text
DATABASE_PATH=/home/container/wbot.sqlite3
TELEGRAM_LOCAL_API_BASE_URL=http://127.0.0.1:8081
MEDIA_TMP_ROOT=/tmp/wbot-media
MAX_DOWNLOAD_BYTES=700000000
MAX_VIDEO_SECONDS=300
```

`TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are the application credentials created under **API
development tools** at `my.telegram.org`; they are not the BotFather token.

## Privacy and operational behavior

- Both services use long polling, so the bot needs no public web endpoint.
- The Local Bot API port must be private.
- Downloads use a random per-request directory and are removed after success, error, or cancellation.
- Only one media request is processed at a time to bound memory and disk use.
- The bot does not log Telegram message text, source URLs, filenames, or credentials.
- Version 1 supports public pages only and uses no account cookies.

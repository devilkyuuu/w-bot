# Private Telegram `/w` media bot

This bot replies to `/w <one supported link>` with the useful content itself. It sends no progress
message. In an approved group, any member can invoke it with a command, while ordinary messages
remain hidden from the bot by Telegram Group Privacy Mode.

Supported sources:

- TikTok and public Facebook videos: playable MP4, up to five minutes and 1080p.
- Public X posts: text, up to four photos, or a video.
- AmiAmi and Nin-Nin Game products: up to five product images plus name, manufacturer, yen price,
  and approximate euro price from the ECB reference rate.

## Telegram setup

1. Create the bot with `@BotFather` and keep the token private.
2. In BotFather, run `/setprivacy`, select the bot, and choose **Enable**.
3. Run `/setcommands` and enter:

   ```text
   w - Show content from a supported link
   approve - Allow this group (owner only)
   revoke - Remove this group (owner only)
   ```

4. Add the bot to a group as an ordinary member. Never grant administrator rights.
5. The owner sends `/approve` in that group once. `/revoke` disables it again.

The bot intentionally ignores unapproved groups, other users' private chats, and non-command group
messages. It stores only approved numeric group IDs in a small local SQLite database.

## Commands

```text
/w https://www.tiktok.com/...
/w https://www.facebook.com/...
/w https://x.com/.../status/...
/w https://www.amiami.com/eng/detail?gcode=...
/w https://www.nin-nin-game.com/en/...html
```

Only one HTTPS URL is accepted. Short retrieval failures receive one short error reply; there is no
“getting the video” message.

## Runtime configuration

Never commit real values. Configure these as encrypted runtime secrets:

```text
BOT_TOKEN
TELEGRAM_API_ID
TELEGRAM_API_HASH
OWNER_USER_ID
```

Non-secret configuration:

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

See `wispbyte/README.md` for the free single-server deployment. The earlier Northflank packaging
remains available under `northflank/`.

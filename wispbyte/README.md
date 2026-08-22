# WispByte deployment

The free WispByte server runs the Python bot and Telegram Local Bot API in one container. The bot
uses SQLite for its small approved-group list, so no separate database server is required.

## Server limits used by this deployment

- Python 3.11 image (`ghcr.io/parkervcp/yolks:python_3.11`)
- 0.5 GiB memory, 1 GiB storage, and one public port
- `ffmpeg` supplied by the selected image
- One media request at a time
- Temporary media capped at 700 MB and deleted after each request

The public port is not used because Telegram polling and the Local Bot API both stay inside the
container.

## Startup

Set the public Git repository address, enable automatic updates, and use this command:

```sh
chmod 700 telegram-bot-api && python -m pip install --no-cache-dir --prefix .local . && python -m wbot.wispbyte
```

Upload the `telegram-bot-api` artifact produced by the repository's
`Build Telegram Bot API for WispByte` GitHub Action to `/home/container/telegram-bot-api` and keep
it executable.

Create `/home/container/.env` through WispByte's Environment editor. Required values are listed in
`.env.example`; never commit real credentials.

Before the first Local Bot API start, log the bot out from Telegram's hosted Bot API as documented
by Telegram. This must be done only after the Local Bot API binary and environment are ready.

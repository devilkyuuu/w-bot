# Northflank deployment

The project runs as two private services plus one PostgreSQL addon:

```text
Telegram ──outbound── bot service ──private HTTP── telegram-api service
                         │
                         └──private PostgreSQL── approved groups
```

The bot uses long polling. Neither service needs a public HTTP route.

## 1. Put the project in a Git repository

Create a repository containing this project and connect it to Northflank. A public repository is
fine if that is your preference, because no credentials belong in the files. All real values go into
Northflank runtime secrets.

## 2. Create PostgreSQL

Create a PostgreSQL addon named `wbot-db`. It does not need public access. Link its `POSTGRES_URI`
connection value to the bot service with the alias `DATABASE_URL`.

The bot creates its two small tables automatically when it starts.

## 3. Create the Local Bot API service

Create a combined service named exactly `telegram-api` from the repository:

- Build type: Dockerfile
- Build context: `/docker/telegram-api`
- Dockerfile: `/docker/telegram-api/Dockerfile`
- Instances: 1
- Runtime port: `8081`, protocol HTTP, **private only**
- Ephemeral storage: use the largest free allowance available, ideally 2 GB
- Runtime secret `TELEGRAM_API_ID`: value from `my.telegram.org`
- Runtime secret `TELEGRAM_API_HASH`: value from `my.telegram.org`

Do not add `BOT_TOKEN` to this service. Do not create a public route or domain.

## 4. Migrate the bot to the Local Bot API

Telegram requires a bot to log out of the hosted Bot API before the local server becomes its active
API server. In a private browser tab, visit the following URL once, replacing the placeholder
locally:

```text
https://api.telegram.org/botYOUR_BOT_TOKEN/logOut
```

Close that browser tab afterward and do not share or screenshot the URL. Start only one Local Bot
API service for this bot.

## 5. Create the bot service

Create another combined service named `wbot`:

- Build type: Dockerfile
- Build context: repository root `/`
- Dockerfile: `/Dockerfile`
- Instances: 1
- Public ports: none
- Ephemeral storage: ideally 2 GB

Add these encrypted runtime variables:

| Name | Value |
|---|---|
| `BOT_TOKEN` | BotFather token |
| `TELEGRAM_API_ID` | Application ID from `my.telegram.org` |
| `TELEGRAM_API_HASH` | Application hash from `my.telegram.org` |
| `OWNER_USER_ID` | Your numeric Telegram user ID |
| `DATABASE_URL` | Linked PostgreSQL `POSTGRES_URI` |
| `TELEGRAM_LOCAL_API_BASE_URL` | `http://telegram-api:8081` |
| `MEDIA_TMP_ROOT` | `/tmp/wbot-media` |
| `MAX_DOWNLOAD_BYTES` | `1000000000` |
| `MAX_VIDEO_SECONDS` | `300` |

The application credentials are currently validated by the bot configuration as well as used by
the Local API service, so add them to both encrypted environments. They are never logged.

Deploy `telegram-api` first. When its logs say the Bot API server has started, deploy `wbot`.

## 6. Configure Telegram

In BotFather:

1. Confirm `/setprivacy` is **Disabled** so Telegram delivers bare group links to the bot.
2. Set `/setcommands` to the two commands shown in the root README.
3. Add the bot to the intended group as a normal member, without administrator rights.
4. As the owner, send `/approve` once in the group.
5. Send one supported public HTTPS link by itself.

The normal result is a direct reply containing the playable video, X content, or product album.
There is no progress message.

## 7. Storage and cold starts

The bot deletes its downloaded file immediately after Telegram accepts the upload, including on
failure and cancellation. The Local Bot API also uses a separate temporary directory. A cold start
can delay the first command; the command may need to be sent again if Northflank terminates an idle
service before polling resumes.

If Northflank reports that a free-plan resource is unavailable, keep the same containers and run
them locally or on another container host. Do not expose port 8081 publicly to work around private
networking.

# Telegram Local Bot API feasibility gate

This gate is completed before any site extractor is connected to the bot. It tests whether the
chosen Northflank tier can stream large files reliably, keep the Telegram API private, and return
temporary storage to its starting level.

## Secrets and service boundary

- [ ] Create `telegram-api` from `docker/telegram-api/Dockerfile`.
- [ ] Do **not** create a public route for `telegram-api`; expose port 8081 only to the private
      project network.
- [ ] Add `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` as encrypted service secrets. These are the
      application credentials from `my.telegram.org` → **API development tools**, not the bot
      token from BotFather.
- [ ] Create a separate probe/bot service on the same private network.
- [ ] Add `BOT_TOKEN`, `OWNER_USER_ID`, and `TELEGRAM_LOCAL_API_BASE_URL` as encrypted secrets to
      that service. The internal URL should be similar to `http://telegram-api:8081`.
- [ ] Confirm neither service prints secret values, source URLs, Telegram messages, or filenames.
- [ ] Keep Telegram Group Privacy Mode enabled and do not make the bot a group administrator.

Before the first local-server test, migrate the bot from Telegram's hosted Bot API by calling
`logOut` once against `https://api.telegram.org`. After that point, all bot calls—including long
polling—must use the private local server. Do not run the same bot simultaneously against multiple
Local Bot API servers.

## Baseline

Record values from Northflank metrics immediately before each test.

| Measurement | 60 MiB | 200 MiB | largest safe probe |
|---|---:|---:|---:|
| Date/time (UTC) |  |  |  |
| Probe size (MiB) | 60 | 200 |  |
| Bot-service free disk before (MiB) |  |  |  |
| API-service free disk before (MiB) |  |  |  |
| Bot-service peak memory (MiB) |  |  |  |
| API-service peak memory (MiB) |  |  |  |
| Bot-service peak disk (MiB) |  |  |  |
| API-service peak disk (MiB) |  |  |  |
| Upload duration (seconds) |  |  |  |
| Container restarts |  |  |  |
| Bot-service free disk after 2 min (MiB) |  |  |  |
| API-service free disk after 2 min (MiB) |  |  |  |
| Attachment received in Telegram |  |  |  |
| Probe removed locally |  |  |  |

## Probe sequence

Run only one probe at a time. Set `PROBE_SIZE_MIB` to 60, then 200, then to the largest value that
leaves at least 250 MiB headroom below the measured disk ceiling. The command is:

```text
python scripts/large_upload_probe.py
```

The synthetic `.bin` file tests the large streaming path without pretending to be a valid video.
After the 200 MiB transport probe passes, send one real short MP4 through `Publisher.send_video` to
confirm Telegram displays it as a playable in-chat video.

For each run:

- [ ] The Telegram document arrives and its displayed size matches the probe size.
- [ ] The bot process does not hold roughly the entire file in memory.
- [ ] Neither service restarts or is killed.
- [ ] The probe script reports that its local data was removed.
- [ ] Temporary disk usage returns close to the baseline within two minutes.
- [ ] Logs contain no bot token, API hash, chat text, source URL, or local filename.

## Pass/fail decision

Northflank passes only if:

- [ ] The 60 MiB and 200 MiB transport probes both succeed.
- [ ] A real MP4 is playable in the Telegram chat.
- [ ] Neither service exceeds its memory allowance or restarts.
- [ ] Temporary storage returns to the pre-test level.
- [ ] The services remain private and the logs remain free of sensitive values.

If a criterion fails twice, stop the Northflank route. Repeat the same test locally with Docker
Desktop; do not weaken group privacy, expose the Local Bot API publicly, or add cookies to work
around a hosting limitation.

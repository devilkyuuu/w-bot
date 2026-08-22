# Telegram `/w` Bot — Project Plan

## The finished bot

In an approved Telegram group, a user sends:

```text
/w <link>
```

The bot replies to that message with only the useful result:

- TikTok or Facebook: a playable video.
- X: post text and available photos or video.
- AmiAmi or Nin-Nin Game: up to five product images with product name, manufacturer, yen price, and approximate euro price.
- Failure: one short error reply.

There are no progress messages. Telegram Privacy Mode remains enabled, the bot is not made a group administrator, and ordinary group conversation is not delivered to it.

## Stage 1 — Prepare the private accounts

### You will

1. Create the bot through Telegram's official BotFather.
2. Choose its display name and username.
3. Keep Group Privacy Mode enabled and allow the bot to be added to groups.
4. Create Telegram application credentials through `my.telegram.org` for the Local Bot API.
5. Create or keep your Northflank Developer Sandbox account.
6. Prepare a private test group and add the bot without administrator rights.
7. Select one public test link for TikTok, Facebook, X text, X photos, and X video. The two agreed shop links will be used for AmiAmi and Nin-Nin Game.

You will not send the bot token, Telegram API hash, or passwords in this chat. When required, you will paste them directly into protected secret fields on Northflank.

### I will

1. Prepare the private project structure and exact setup instructions.
2. Provide a safe way to obtain the stable numeric Telegram owner ID.
3. Label every secret field clearly so credentials never enter the code or its history.
4. Give you short, screen-by-screen instructions for BotFather and Northflank when we reach them.

## Stage 2 — Northflank feasibility test

This test happens before the website features are built. It prevents us from spending time on a host that cannot support the essential large-video workflow.

### I will

1. Prepare the smallest possible bot and a private Telegram Local Bot API service.
2. Configure them so neither has a public webpage or public port.
3. Create a temporary test attachment larger than 50 MB.
4. Send it to the owner's test chat through the Local Bot API.
5. Repeat with progressively larger safe files while watching memory and disk use.
6. Confirm that test files disappear after both successful and failed sends.
7. Confirm that logs contain no tokens, links, messages, or filenames.

### You will

1. Enter the secret values directly into Northflank.
2. Confirm that the test attachment arrives and plays in Telegram.
3. Tell me whether the Northflank dashboard reports a quota or billing warning.

### Decision

Northflank passes if a file of at least 200 MB is sent without a service restart, temporary storage returns to normal, and no sensitive content appears in logs.

If it fails twice, we stop testing Northflank. We run the same containers on your Windows computer instead. Nothing built afterward is tied permanently to Northflank, so a future move to a small VPS remains possible.

## Stage 3 — Privacy, approved groups, and `/w`

### I will build

1. Recognition of exactly one command format: `/w <one link>`.
2. Owner-only group approval and revocation.
3. Silent ignoring of unapproved groups.
4. A safeguard that refuses to operate if the bot is granted administrator rights.
5. One-at-a-time media processing so the free server cannot be flooded.
6. Short, consistent errors with no technical details.
7. Automatic cleanup after success, failure, cancellation, restart, and interrupted download.

### We will verify

1. An ordinary conversation message is not received by the bot.
2. `/w <link>` works in the approved group.
3. The same command receives no response in an unapproved group.
4. Only you can approve or revoke a group.

## Stage 4 — TikTok and Facebook videos

### I will build

1. Public-link metadata inspection before downloading.
2. Rejection of videos longer than five minutes.
3. A maximum resolution of 1080p, with no upscaling.
4. Selection of Telegram-playable MP4/H.264/AAC whenever available.
5. A lower-resolution fallback if 1080p would be incompatible or too large.
6. A hard initial file cap of 1 GB, adjusted downward if the feasibility test reveals a safer Northflank ceiling.
7. Immediate deletion after Telegram accepts or rejects the upload.

### You will verify

1. One public TikTok example.
2. One public Facebook example.
3. One deliberately over-five-minute example.
4. Playback on the Telegram devices you normally use.

Private, login-only, age-restricted, subscriber-only, and cookie-dependent posts are not included in version 1.

## Stage 5 — AmiAmi and Nin-Nin Game products

I will create a separate reader for each shop because their pages use different layouts.

For each supported product, the bot will send no more than five ordered gallery images. The first image will contain:

```text
Product Name (bold)
Manufacturer
¥ price
≈ € price
```

The manufacturer will have no `Maker:` label. The euro value will use the latest available European Central Bank JPY reference rate, with a saved last-known rate as a temporary fallback if the ECB is unavailable.

We will verify the agreed AmiAmi and Nin-Nin Game examples, image order, manufacturer, yen price, and euro calculation.

## Stage 6 — X posts

### I will build

1. Text-only output containing author, handle, and copyable post text.
2. Photo albums capped at four photos.
3. Playable video output following the same five-minute and 1080p rules.
4. Post text as the media caption when it fits, or as a separate message when it is too long for a Telegram caption.
5. A generic short retrieval error when neither text nor media can be retrieved.

X will use public-page extraction without paid API access or account cookies. Because X changes its pages frequently, this will be treated as the most fragile integration and kept separate so it cannot break the other websites.

## Stage 7 — Security and failure testing

I will test:

- Misleading domains and maliciously formatted URLs.
- Multiple links in one command.
- Removed or unavailable pages.
- Oversized and over-five-minute videos.
- Network timeouts and interrupted downloads.
- Telegram upload failures.
- Restart cleanup.
- HTML escaping for product names and X text.
- Non-root containers and private service networking.
- Logs and database contents for accidental private-data retention.

The database will retain only approved numeric group IDs, approval timestamps, and the last known exchange rate. It will not retain messages, source links, media, product pages, or X post text.

## Stage 8 — Final test and observation

Together we will run every supported source in the private test group. After that, the Northflank deployment will be observed for seven days for restarts, quota warnings, disk use, memory use, and source failures—without recording message content.

If stable, you can approve the real groups. If Northflank is unreliable, the exact same bot will be moved locally rather than rewritten.

## Division of responsibility

### You are responsible for

- Owning the Telegram, Northflank, and Telegram application accounts.
- Keeping credentials private and entering them only into secret fields.
- Choosing the bot's public name and username.
- Choosing which groups are approved.
- Supplying public test links and confirming Telegram playback.
- Making the final decision about Northflank versus local hosting after the feasibility evidence.

### I am responsible for

- Architecture, implementation, tests, containers, and documentation.
- Privacy Mode and approved-group enforcement.
- Source-specific extraction and output formatting.
- File-size, duration, resolution, concurrency, and cleanup safeguards.
- Secret-safe deployment instructions.
- Diagnosing failures and keeping website breakage isolated.
- Reporting honestly when a free-host limitation or website restriction cannot be solved safely.

## First action when implementation begins

You create the Telegram bot through BotFather, but do not post its token here. I then build only the Northflank feasibility probe. The complete bot begins only after that probe passes or we select the local fallback.

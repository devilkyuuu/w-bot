# Telegram `/w` Media Bot Specification

## Purpose

Build a private Telegram bot for an owner-approved set of group chats. A user sends `/w <link>` and the bot replies to that command with the useful content from the link, without progress chatter.

## Privacy and access

- Telegram Group Privacy Mode stays enabled.
- The bot is never a group administrator.
- The only normal user command is `/w <link>`.
- The bot processes `/w` only in owner-approved groups and in the owner's private chat for testing.
- Unapproved groups receive no response.
- Owner-only approval and revocation commands may send a one-line administrative acknowledgement.
- Ordinary group conversation is not logged or stored.
- Secrets never enter source control or application logs.

## Supported links and output

### TikTok and Facebook

- Public video links only; no account cookies or login automation in version 1.
- Maximum duration: 5 minutes (300 seconds).
- Maximum resolution: 1080p; never upscale.
- Prefer a Telegram-playable MP4 containing H.264 video and AAC audio.
- Prefer 1080p, then select a lower resolution when required for compatibility or file size.
- Initial hard download cap: 1 GB, subject to the Northflank feasibility test.
- Reply with the playable video and no progress message.

### X (Twitter)

- Public posts only; no paid X API and no account cookies in version 1.
- Preserve author display name, handle, and post text.
- Text-only posts produce a copyable Telegram text message.
- Photo posts produce an album of up to 4 photos with text on the first item.
- Video or animated posts produce a Telegram-playable video with the post text.
- Apply the same 5-minute, 1080p, compatibility, and size rules as other videos.
- If neither retrievable text nor retrievable media exists, send a short generic retrieval error rather than a special "no media" error.

### AmiAmi and Nin-Nin Game

- Use a separate extractor for each site.
- Send the product gallery as a Telegram album capped at 5 images.
- Put the caption on the first image using this shape:

  ```text
  <b>Product Name</b>
  Manufacturer
  ¥12,345
  ≈ €76.54
  ```

- Do not prefix the manufacturer with `Maker:` or `Manufacturer:`.
- Use the displayed Japanese-yen product price.
- Convert JPY to EUR with the latest available European Central Bank reference rate and mark the result as approximate.
- If manufacturer extraction fails, send the useful gallery and prices without inventing a manufacturer.

## Interaction and errors

- Supported syntax: `/w <one URL>`.
- A missing, malformed, multiple, or unsupported URL receives a short error reply.
- Source failures receive a short error reply.
- The bot replies to the command message so the result retains context.
- No `Getting the video…`, progress update, success acknowledgement, or explanatory footer.

## Storage and processing

- Process one media job at a time per deployment.
- Use bounded downloads and timeouts.
- Delete temporary files after success, after failure, and during startup recovery.
- Do not retain downloaded videos, images, post text, or original URLs.
- Persist only owner-approved group IDs, minimal administrative audit timestamps, and a cached ECB exchange rate.
- Escape all external text before using Telegram HTML formatting.

## Hosting

- First candidate: Northflank Developer Sandbox.
- Run the Python bot and Telegram Local Bot API as private services; expose no public HTTP endpoint.
- Use Northflank's free database allowance for approved-group state and the last known ECB rate.
- The feasibility gate must prove a file larger than Telegram's normal 50 MB cloud-bot upload limit can be sent and cleaned up within the free resource limits.
- If Northflank fails the gate, use the local Windows computer as the immediate fallback; consider a small VPS only if 24/7 operation later becomes necessary.

## Acceptance criteria

- Privacy Mode is visibly enabled and the bot is not an administrator.
- `/w <link>` works in an approved test group and is silent in an unapproved group.
- A public video over 50 MB and at most 5 minutes is posted as a playable Telegram video.
- Videos over 5 minutes are rejected before the full download whenever metadata permits.
- AmiAmi and Nin-Nin sample products each return up to 5 ordered gallery images with the required caption.
- X text-only, photo, and video examples each produce the specified output.
- Forced failures leave no temporary media behind and do not leak messages or secrets into logs.

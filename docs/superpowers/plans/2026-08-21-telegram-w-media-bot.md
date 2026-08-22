# Telegram `/w` Media Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a privacy-preserving Telegram group bot that turns `/w <link>` requests into playable social videos, X posts, or five-image product galleries in owner-approved groups.

**Architecture:** A Python long-polling bot routes a single `/w` command through strict URL validation to source-specific extractors. A private Telegram Local Bot API service handles large uploads, PostgreSQL stores the allowlist and cached exchange rate, and an isolated temporary workspace is erased on every exit path.

**Tech Stack:** Python 3.12, python-telegram-bot 22.x, PostgreSQL 16, psycopg 3, HTTPX, Beautiful Soup 4, yt-dlp, FFmpeg/ffprobe, pytest, Ruff, mypy, Docker, Telegram Local Bot API, Northflank Developer Sandbox.

**Spec:** `docs/specs/telegram-media-bot-spec.md`

## Global Constraints

- Telegram Group Privacy Mode remains enabled.
- The bot must not be a group administrator and must expose no public HTTP port.
- Normal syntax is exactly `/w <one URL>`.
- Only owner-approved group IDs and the owner's private chat are processed.
- Video duration is at most 300 seconds; resolution is at most 1080p; initial download limit is 1,000,000,000 bytes.
- Prefer MP4/H.264/AAC and fall back to a lower resolution before considering remuxing; do not perform heavy cloud transcoding.
- Product albums contain at most 5 ordered images; X photo albums contain at most 4.
- No progress messages; only functional output or one short error reply.
- Temporary media is deleted on success, failure, cancellation, and startup.
- Public pages only in version 1; no user cookies, login automation, or paid X API.
- Never log message text, source URLs, Telegram tokens, Telegram API credentials, or downloaded filenames.

## Planned file map

- `pyproject.toml`: runtime dependencies, test tooling, linting, typing, and entry point.
- `.env.example`: secret names and non-secret limits, with no values.
- `src/wbot/app.py`: application bootstrap, long polling, lifecycle cleanup.
- `src/wbot/config.py`: validated environment configuration.
- `src/wbot/domain.py`: shared request, result, media, product, and post types.
- `src/wbot/commands.py`: `/w`, `/approve`, and `/revoke` handlers.
- `src/wbot/access.py`: owner and approved-chat decisions, including non-admin enforcement.
- `src/wbot/database.py`: PostgreSQL allowlist and ECB-rate repository.
- `src/wbot/url_policy.py`: exact host allowlist and safe URL parsing.
- `src/wbot/workspace.py`: per-job directories, byte limits, and guaranteed cleanup.
- `src/wbot/extractors/video.py`: TikTok/Facebook metadata and bounded download.
- `src/wbot/extractors/x_post.py`: X author/text/photo/video extraction.
- `src/wbot/extractors/amiami.py`: AmiAmi product extraction.
- `src/wbot/extractors/nin_nin.py`: Nin-Nin Game product extraction.
- `src/wbot/exchange.py`: ECB JPY/EUR conversion and last-known-good cache.
- `src/wbot/publisher.py`: Telegram text, album, and large-video sending.
- `src/wbot/errors.py`: internal error taxonomy mapped to exact short replies.
- `db/001_init.sql`: approved-chat and exchange-rate tables.
- `docker/telegram-api/Dockerfile`: reproducible Telegram Local Bot API build from official source.
- `Dockerfile`: non-root bot runtime with FFmpeg and yt-dlp.
- `northflank/README.md`: exact two-service, one-database deployment procedure.
- `tests/`: focused unit tests, sanitized page fixtures, integration checks, and cleanup/security tests.

---

### Task 1: Establish the typed core and `/w` request parser

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/wbot/__init__.py`
- Create: `src/wbot/domain.py`
- Create: `src/wbot/config.py`
- Create: `src/wbot/url_policy.py`
- Test: `tests/test_config.py`
- Test: `tests/test_url_policy.py`

**Interfaces:**
- Produces: `Settings.from_env(env: Mapping[str, str]) -> Settings`
- Produces: `parse_w_request(text: str) -> SupportedUrl`
- Produces: `SourceKind`, `SupportedUrl`, `MediaAsset`, `VideoResult`, `ProductResult`, and `PostResult`

- [x] **Step 1: Write failing configuration and URL-policy tests**

  Cover one URL only, whitespace, Telegram's `/w@BotName` form, all supported canonical/subdomains, deceptive suffixes such as `amiami.com.evil.test`, credentials in URLs, non-HTTPS input, private-IP literals, and missing limits.

  ```python
  def test_parses_single_tiktok_url() -> None:
      result = parse_w_request("/w https://www.tiktok.com/@alice/video/123")
      assert result.kind is SourceKind.TIKTOK

  @pytest.mark.parametrize("text", ["/w", "/w https://x.com/a/status/1 https://x.com/b/status/2"])
  def test_rejects_missing_or_multiple_urls(text: str) -> None:
      with pytest.raises(RequestSyntaxError):
          parse_w_request(text)
  ```

- [x] **Step 2: Run the focused tests and verify failure**

  Run: `python -m pytest tests/test_config.py tests/test_url_policy.py -q`

  Expected: collection fails because `wbot.config` and `wbot.url_policy` do not exist.

- [x] **Step 3: Implement immutable domain objects and exact host routing**

  Use `urllib.parse`, IDNA-normalized lowercase hostnames, and explicit host sets. Do not fetch a URL during parsing and do not accept user information, fragments used as credentials, IP literals, or arbitrary redirector domains.

  ```python
  @dataclass(frozen=True, slots=True)
  class SupportedUrl:
      original: str
      normalized: str
      kind: SourceKind

  Result = VideoResult | ProductResult | PostResult
  ```

- [x] **Step 4: Run parser, lint, and type checks**

  Run: `python -m pytest tests/test_config.py tests/test_url_policy.py -q`

  Run: `python -m ruff check src/wbot tests`

  Run: `python -m mypy src/wbot`

  Expected: all pass.

- [x] **Step 5: Commit the independently testable parser core**

  ```bash
  git add pyproject.toml .env.example src/wbot tests/test_config.py tests/test_url_policy.py
  git commit -m "feat: add typed configuration and safe w request parsing"
  ```

### Task 2: Add owner-controlled group approval and persistent state

**Files:**
- Create: `db/001_init.sql`
- Create: `src/wbot/database.py`
- Create: `src/wbot/access.py`
- Test: `tests/test_access.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: `Settings.owner_user_id`
- Produces: `Repository.approve_chat(chat_id: int, approved_by: int) -> None`
- Produces: `Repository.revoke_chat(chat_id: int) -> None`
- Produces: `Repository.is_chat_approved(chat_id: int) -> bool`
- Produces: `AccessDecision.evaluate(user_id: int, chat_id: int, chat_type: str, bot_is_admin: bool) -> Decision`

- [x] **Step 1: Write failing authorization and repository tests**

  Include owner DM, approved group, unapproved group, non-owner approval attempt, revoked group, and bot-as-admin denial.

  ```python
  def test_unapproved_group_is_silent() -> None:
      decision = policy.evaluate(user_id=12, chat_id=-1005, chat_type="supergroup", bot_is_admin=False)
      assert decision is Decision.IGNORE
  ```

- [x] **Step 2: Verify the tests fail before implementation**

  Run: `python -m pytest tests/test_access.py tests/test_database.py -q`

  Expected: imports fail for the new modules.

- [x] **Step 3: Implement the migration and async repository**

  Store only `chat_id`, `approved_by`, `approved_at`, plus a single ECB-rate row. Use parameterized SQL exclusively and make approval idempotent.

  ```sql
  CREATE TABLE approved_chats (
      chat_id BIGINT PRIMARY KEY,
      approved_by BIGINT NOT NULL,
      approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  ```

- [x] **Step 4: Implement fail-closed access decisions**

  Owner private chat is allowed; an approved group is allowed only when the bot is not an administrator; everything else is ignored. Administrative commands additionally require `user_id == owner_user_id`.

- [x] **Step 5: Run database and access tests**

  Run: `python -m pytest tests/test_access.py tests/test_database.py -q`

  Expected: all pass against an isolated test database.

- [x] **Step 6: Commit access control and persistence**

  ```bash
  git add db src/wbot/database.py src/wbot/access.py tests/test_access.py tests/test_database.py
  git commit -m "feat: persist approved groups and enforce private access"
  ```

### Task 3: Guarantee bounded temporary storage and single-job execution

**Files:**
- Create: `src/wbot/workspace.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Produces: `JobWorkspace.create(root: Path, byte_limit: int) -> JobWorkspace`
- Produces: `JobWorkspace.reserve(expected_bytes: int | None) -> None`
- Produces: `JobWorkspace.cleanup() -> None`
- Produces: `MediaGate.run(job: Callable[[], Awaitable[Result]]) -> Result`

- [x] **Step 1: Write failing cleanup and concurrency tests**

  Test normal completion, raised exception, cancellation, stale startup directories, file growth above the byte limit, and two simultaneous jobs.

  ```python
  async def test_exception_still_removes_workspace(tmp_path: Path) -> None:
      with pytest.raises(RuntimeError):
          async with JobWorkspace.create(tmp_path, 1_000_000) as job:
              (job.path / "partial.mp4").write_bytes(b"partial")
              raise RuntimeError("download failed")
      assert list(tmp_path.iterdir()) == []
  ```

- [x] **Step 2: Run the test and confirm the cleanup contract is absent**

  Run: `python -m pytest tests/test_workspace.py -q`

  Expected: import failure.

- [x] **Step 3: Implement context-managed workspaces and an async semaphore of one**

  Create random per-job directories under one configured root, reject predicted oversize files before download, check actual bytes while downloading, and remove stale child directories at startup without following symlinks.

- [x] **Step 4: Verify storage and cancellation behavior**

  Run: `python -m pytest tests/test_workspace.py -q`

  Expected: all pass and the test root is empty.

- [x] **Step 5: Commit the resource boundary**

  ```bash
  git add src/wbot/workspace.py tests/test_workspace.py
  git commit -m "feat: add bounded media workspace and cleanup guarantees"
  ```

### Task 4: Prove Telegram Local Bot API uploads before building extractors

**Files:**
- Create: `docker/telegram-api/Dockerfile`
- Create: `docker/telegram-api/entrypoint.sh`
- Create: `src/wbot/publisher.py`
- Create: `scripts/large_upload_probe.py`
- Test: `tests/test_publisher.py`
- Create: `northflank/feasibility-checklist.md`

**Interfaces:**
- Produces: `Publisher.send_video(chat_id: int, reply_to: int, asset: MediaAsset, caption: str | None) -> None`
- Produces: `Publisher.send_photos(chat_id: int, reply_to: int, assets: Sequence[MediaAsset], caption_html: str) -> None`
- Produces: `Publisher.send_text(chat_id: int, reply_to: int, text_html: str) -> None`

- [x] **Step 1: Write failing publisher tests with a fake Bot API transport**

  Assert the local base URL is used, video is sent as a file upload, replies target the `/w` message, albums respect their caps, and file handles close after errors.

- [ ] **Step 2: Build Telegram's server from a pinned official source tag**

  The Dockerfile must fetch the source from `github.com/tdlib/telegram-bot-api`, verify the pinned commit, compile in a builder stage, and run the binary as a non-root user in the final stage with `--local` and an internal-only port.

- [x] **Step 3: Implement the publisher and a synthetic large-file probe**

  Generate a 60 MiB zero-filled test file locally without committing it, upload it as a document/video to the owner's test chat through the local API, and delete it in a `finally` block.

  ```python
  probe_path.write_bytes(b"\0" * (60 * 1024 * 1024))
  try:
      await publisher.send_video(chat_id, 0, MediaAsset(probe_path, "video/mp4"), None)
  finally:
      probe_path.unlink(missing_ok=True)
  ```

- [ ] **Step 4: Deploy only the Local API and probe to Northflank**

  Configure private networking, 1 GB ephemeral storage per service, Telegram `API_ID`, `API_HASH`, and bot token as Northflank secrets, and no public route.

- [ ] **Step 5: Run the feasibility sequence**

  Send 60 MiB, 200 MiB, and then the largest safe synthetic file below the measured disk ceiling. Record upload time, peak memory, peak disk use, restarts, and post-send free space in `northflank/feasibility-checklist.md`.

  Pass criteria:

  - At least the 200 MiB upload succeeds as a playable Telegram attachment.
  - Neither service restarts or exceeds its memory allowance.
  - Temporary storage returns to its pre-test level.
  - Secrets and filenames are absent from logs.

- [ ] **Step 6: Stop here if Northflank fails**

  If any pass criterion fails twice, do not build around the failure. Repeat the same probe locally on Windows with Docker Desktop. Keep Northflank only if the gate passes without disabling Privacy Mode or increasing the agreed budget.

- [ ] **Step 7: Commit the proven transport**

  ```bash
  git add docker src/wbot/publisher.py scripts/large_upload_probe.py tests/test_publisher.py northflank/feasibility-checklist.md
  git commit -m "feat: prove large Telegram uploads through local bot api"
  ```

### Task 5: Implement Facebook and TikTok video extraction

**Files:**
- Create: `src/wbot/errors.py`
- Create: `src/wbot/extractors/__init__.py`
- Create: `src/wbot/extractors/video.py`
- Test: `tests/test_video_extractor.py`

**Interfaces:**
- Consumes: `SupportedUrl`, `JobWorkspace`
- Produces: `VideoExtractor.inspect(url: SupportedUrl) -> VideoMetadata`
- Produces: `VideoExtractor.download(url: SupportedUrl, workspace: JobWorkspace) -> VideoResult`

- [ ] **Step 1: Write metadata and format-selection tests**

  Use saved yt-dlp JSON fixtures to cover 301 seconds, exactly 300 seconds, 2160p-only input, 1080p MP4, portrait 1080x1920, missing duration, estimated oversize, and 720p fallback.

- [ ] **Step 2: Verify the format rules fail before implementation**

  Run: `python -m pytest tests/test_video_extractor.py -q`

- [ ] **Step 3: Implement metadata-first inspection and bounded download**

  Invoke yt-dlp without a shell, pass the URL as a discrete argument, prefer `height<=1080`, H.264/AAC/MP4, and reject known durations over 300 seconds before downloading. Enforce the byte limit during and after download and use ffprobe to verify the produced file.

- [ ] **Step 4: Add public live checks outside the default test suite**

  Run one user-supplied public TikTok URL and one public Facebook URL. Verify reply threading, resolution, duration, playability, and cleanup. Mark live tests with `@pytest.mark.live` so ordinary CI never depends on third-party availability.

- [ ] **Step 5: Commit the two video sources**

  ```bash
  git add src/wbot/errors.py src/wbot/extractors tests/test_video_extractor.py
  git commit -m "feat: extract bounded Facebook and TikTok videos"
  ```

### Task 6: Implement product galleries and ECB conversion

**Files:**
- Create: `src/wbot/extractors/amiami.py`
- Create: `src/wbot/extractors/nin_nin.py`
- Create: `src/wbot/exchange.py`
- Create: `tests/fixtures/amiami_product.html`
- Create: `tests/fixtures/nin_nin_product.html`
- Create: `tests/fixtures/ecb_rates.xml`
- Test: `tests/test_amiami.py`
- Test: `tests/test_nin_nin.py`
- Test: `tests/test_exchange.py`

**Interfaces:**
- Produces: `AmiAmiExtractor.extract(url: SupportedUrl, workspace: JobWorkspace) -> ProductResult`
- Produces: `NinNinExtractor.extract(url: SupportedUrl, workspace: JobWorkspace) -> ProductResult`
- Produces: `ExchangeService.jpy_to_eur(price_jpy: Decimal) -> Decimal`

- [ ] **Step 1: Capture minimal sanitized fixtures from the two agreed sample products**

  Retain only markup necessary for title, manufacturer, yen price, and ordered gallery URLs. The fixtures must not include analytics scripts, customer data, or full copyrighted page content.

- [ ] **Step 2: Write failing per-site extraction tests**

  Assert AmiAmi and Nin-Nin use independent selectors, deduplicate thumbnails, preserve gallery order, cap at five, parse comma-separated yen prices, and never invent a missing maker.

- [ ] **Step 3: Write failing ECB conversion and cache tests**

  For a fixture rate of `JPY=161.50`, assert `JPY 16,150 -> EUR 100.00`, rounded to two decimals. Test fresh cache, stale-cache refresh, failed refresh with last-known-good fallback, and unavailable initial rate.

- [ ] **Step 4: Implement the normalized product and exchange adapters**

  Fetch with bounded HTTPX timeouts, a descriptive user agent, maximum response size, exact-domain redirect validation, and HTML parsing without executing JavaScript. Download at most the first five distinct full-size images.

- [ ] **Step 5: Verify exact caption rendering**

  Assert the first album caption is bold escaped product name, raw escaped manufacturer on its own line without a label, yen price, and approximate euro price prefixed by `≈`.

- [ ] **Step 6: Run fixture tests and one live check per shop**

  Run: `python -m pytest tests/test_amiami.py tests/test_nin_nin.py tests/test_exchange.py -q`

  Expected: all fixture tests pass; live checks produce no more than five images and leave no files.

- [ ] **Step 7: Commit both separate shop adapters**

  ```bash
  git add src/wbot/extractors/amiami.py src/wbot/extractors/nin_nin.py src/wbot/exchange.py tests
  git commit -m "feat: add product galleries and ECB euro conversion"
  ```

### Task 7: Implement X post text, photos, and video

**Files:**
- Create: `src/wbot/extractors/x_post.py`
- Create: `tests/fixtures/x_text_post.html`
- Create: `tests/fixtures/x_photo_post.html`
- Create: `tests/fixtures/x_video_metadata.json`
- Test: `tests/test_x_post.py`

**Interfaces:**
- Produces: `XPostExtractor.extract(url: SupportedUrl, workspace: JobWorkspace) -> PostResult`

- [ ] **Step 1: Write failing text, photo, and video tests**

  Cover display name, handle, Unicode text, HTML escaping, text-only output, four-photo cap, duplicate photo variants, video duration/format rules, missing media with valid text, and fully unavailable posts.

- [ ] **Step 2: Implement public-page extraction with a bounded strategy chain**

  Read public Open Graph and embedded structured data for author/text/photos; use yt-dlp metadata for video. Do not add cookies or a paid API. Make each strategy return `Unavailable` rather than leaking source-specific exception details to Telegram.

- [ ] **Step 3: Handle Telegram text limits without losing post text**

  Put author, handle, and text in the media caption when it fits. If the escaped caption exceeds Telegram's caption limit, send the complete text as a separate reply immediately before the media; cap a text-only message to Telegram's message limit with a visible ellipsis.

- [ ] **Step 4: Run fixture and live checks**

  Run: `python -m pytest tests/test_x_post.py -q`

  Then test one public text-only post, photo post, and short video post supplied by the owner. Record failures as source fragility, not as a reason to weaken privacy or introduce account cookies.

- [ ] **Step 5: Commit X support**

  ```bash
  git add src/wbot/extractors/x_post.py tests/fixtures/x_* tests/test_x_post.py
  git commit -m "feat: publish public X post text and media"
  ```

### Task 8: Wire commands, routing, exact errors, and lifecycle

**Files:**
- Create: `src/wbot/commands.py`
- Create: `src/wbot/app.py`
- Modify: `src/wbot/errors.py`
- Test: `tests/test_commands.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: all extractors, `Publisher`, `Repository`, `AccessDecision`, and `MediaGate`
- Produces: `build_application(settings: Settings) -> Application`

- [ ] **Step 1: Write end-to-end handler tests with fake services**

  Assert `/w` routes each source, only one URL is accepted, results reply to the command, unapproved groups are silent, owner-only approval works, non-owner approval is silent, no progress message exists, and each exception maps to one short reply.

- [ ] **Step 2: Define exact user-visible error copy**

  ```python
  ERROR_TEXT = {
      ErrorCode.BAD_REQUEST: "Send one supported link after /w.",
      ErrorCode.UNSUPPORTED: "That link isn't supported.",
      ErrorCode.TOO_LONG: "That video is longer than 5 minutes.",
      ErrorCode.TOO_LARGE: "That file is too large to send.",
      ErrorCode.RETRIEVAL: "I couldn't retrieve that content.",
  }
  ```

- [ ] **Step 3: Implement handlers and the extractor registry**

  Register `/w`, owner-only `/approve`, and owner-only `/revoke`; do not register a catch-all text handler. Check bot membership status before processing and refuse groups where the bot is an administrator.

- [ ] **Step 4: Implement lifecycle cleanup and sanitized logging**

  Run stale-workspace cleanup before polling, use structured event names with random correlation IDs, and log only source kind, elapsed time, byte count, and success/error class. Add a logging test that injects a recognizable secret and URL and asserts neither appears.

- [ ] **Step 5: Run the complete local test suite**

  Run: `python -m pytest -m "not live" -q`

  Run: `python -m ruff check src/wbot tests`

  Run: `python -m mypy src/wbot`

  Expected: all pass.

- [ ] **Step 6: Commit the complete bot behavior**

  ```bash
  git add src/wbot/commands.py src/wbot/app.py src/wbot/errors.py tests/test_commands.py tests/test_app.py
  git commit -m "feat: wire private w command workflow"
  ```

### Task 9: Package and document the Northflank deployment

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `northflank/README.md`
- Create: `README.md`
- Test: `tests/test_container_contract.py`

**Interfaces:**
- Produces: bot container command `python -m wbot.app`
- Produces: private Local Bot API endpoint consumed through `TELEGRAM_LOCAL_API_BASE_URL`

- [ ] **Step 1: Write a container-contract test**

  Assert the runtime user is non-root, no secret is copied into either image, writable paths are limited to the configured temporary directory, health checks do not expose credentials, and the bot image contains FFmpeg/ffprobe.

- [ ] **Step 2: Build the bot image reproducibly**

  Pin the Python base image by digest during implementation, install locked dependencies, copy only runtime files, create the non-root user, and set the temporary directory ownership explicitly.

- [ ] **Step 3: Write exact Northflank setup instructions**

  Document one private bot service, one private Local Bot API service, one PostgreSQL addon, the internal hostname/port, ephemeral storage settings, migration command, liveness checks, and these secret names only: `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `OWNER_USER_ID`, `DATABASE_URL`.

- [ ] **Step 4: Document Telegram setup without exposing secrets**

  Include BotFather creation, `/setprivacy` enabled, `/setcommands` entry `w - Show content from a supported link`, group-add permission, warning not to grant admin rights, and owner approval procedure.

- [ ] **Step 5: Build and scan both images**

  Run: `docker build -t wbot:test .`

  Run: `docker build -t wbot-telegram-api:test docker/telegram-api`

  Run the available local vulnerability scanner and fail on known critical runtime vulnerabilities unless a written, source-backed exception exists.

- [ ] **Step 6: Commit packaging and operator documentation**

  ```bash
  git add Dockerfile .dockerignore README.md northflank tests/test_container_contract.py
  git commit -m "docs: package and document Northflank deployment"
  ```

### Task 10: Run privacy, failure, and acceptance verification

**Files:**
- Create: `tests/acceptance/checklist.md`
- Create: `tests/acceptance/test_failure_cleanup.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the deployed bot, private Local Bot API, database, and owner-supplied public test links
- Produces: signed-off acceptance checklist and documented known source limitations

- [ ] **Step 1: Verify Telegram privacy and group access**

  Confirm Privacy Mode is visible as enabled, the bot is not an admin, an ordinary group message is absent from application logs/updates, `/w` works in the approved group, and the same request is silent in an unapproved group.

- [ ] **Step 2: Verify each agreed content path**

  Exercise TikTok video, Facebook video, X text, X photos, X video, the agreed AmiAmi product, and the agreed Nin-Nin product. Check reply relationship, album caps, caption shape, 5-minute enforcement, 1080p ceiling, and approximate ECB conversion.

- [ ] **Step 3: Force every material failure path**

  Test invalid URL, unsupported site, removed post, video over 5 minutes, download over byte cap, network timeout, Local API failure, Telegram send failure, and process cancellation. After each, assert one short error at most and zero leftover job files.

- [ ] **Step 4: Inspect logs and persistent data**

  Search exported logs and database rows for test URLs, message text, bot token fragments, Telegram API credentials, local filenames, and downloaded content. The only allowed persistent user-derived values are approved numeric chat IDs and approval timestamps.

- [ ] **Step 5: Observe the free deployment for seven days**

  Record unexpected restarts, disk high-water mark, memory high-water mark, average upload time, extractor failures by source kind, and Northflank quota warnings. Do not retain message contents while collecting these metrics.

- [ ] **Step 6: Make the hosting decision**

  Keep Northflank if large uploads, cleanup, privacy, and resource use remain within the gate. Otherwise deploy the same containers locally; move to a small VPS later only if the owner chooses paid 24/7 availability.

- [ ] **Step 7: Run final verification and commit the acceptance record**

  Run: `python -m pytest -q`

  Run: `python -m ruff check src/wbot tests`

  Run: `python -m mypy src/wbot`

  Expected: all automated checks pass and every applicable line in `tests/acceptance/checklist.md` is checked.

  ```bash
  git add tests/acceptance README.md
  git commit -m "test: verify privacy cleanup and supported sources"
  ```

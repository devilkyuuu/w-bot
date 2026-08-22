from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass
from decimal import Decimal

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from wbot.access import AccessPolicy, Decision
from wbot.config import Settings
from wbot.database import ApprovalRepository
from wbot.domain import PostResult, ProductResult, SourceKind, SupportedUrl
from wbot.errors import ERROR_TEXT, BotError, ErrorCode
from wbot.exchange import ExchangeService
from wbot.extractors.amiami import AmiAmiExtractor
from wbot.extractors.nin_nin import NinNinExtractor
from wbot.extractors.video import VideoExtractor
from wbot.extractors.x_post import XPostExtractor
from wbot.publisher import Publisher, PublishError
from wbot.url_policy import RequestSyntaxError, UnsupportedUrlError, parse_w_request
from wbot.workspace import JobWorkspace, MediaGate

LOGGER = logging.getLogger("wbot")
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


@dataclass(slots=True)
class BotServices:
    settings: Settings
    access: AccessPolicy
    repository: ApprovalRepository
    publisher: Publisher
    video: VideoExtractor
    amiami: AmiAmiExtractor
    nin_nin: NinNinExtractor
    x_post: XPostExtractor
    exchange: ExchangeService
    gate: MediaGate[None]


class Commands:
    def __init__(self, services: BotServices) -> None:
        self.services = services

    async def w(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        if message is None or user is None or chat is None or not message.text:
            return

        decision = await self._access_decision(user.id, chat.id, chat.type, context)
        if decision is Decision.IGNORE:
            return
        if decision is Decision.BOT_MUST_NOT_BE_ADMIN:
            await message.reply_text("Remove my admin rights before using me.")
            return

        try:
            supported = parse_w_request(message.text)
        except RequestSyntaxError:
            await message.reply_text(ERROR_TEXT[ErrorCode.BAD_REQUEST])
            return
        except UnsupportedUrlError:
            await message.reply_text(ERROR_TEXT[ErrorCode.UNSUPPORTED])
            return

        started = time.monotonic()

        async def job() -> None:
            async with JobWorkspace.create(
                self.services.settings.media_tmp_root,
                self.services.settings.max_download_bytes,
            ) as workspace:
                await self._extract_and_publish(
                    supported,
                    chat_id=chat.id,
                    reply_to=message.message_id,
                    workspace=workspace,
                )

        try:
            await self.services.gate.run(job)
        except BotError as exc:
            LOGGER.info(
                "media_job_failed source=%s error=%s elapsed_ms=%d",
                supported.kind.value,
                exc.code.value,
                round((time.monotonic() - started) * 1000),
            )
            await message.reply_text(ERROR_TEXT[exc.code])
        except PublishError:
            LOGGER.info(
                "media_job_failed source=%s error=publish elapsed_ms=%d",
                supported.kind.value,
                round((time.monotonic() - started) * 1000),
            )
            await message.reply_text(ERROR_TEXT[ErrorCode.RETRIEVAL])
        except Exception as exc:
            LOGGER.warning(
                "media_job_failed source=%s error_class=%s elapsed_ms=%d",
                supported.kind.value,
                type(exc).__name__,
                round((time.monotonic() - started) * 1000),
            )
            await message.reply_text(ERROR_TEXT[ErrorCode.RETRIEVAL])
        else:
            LOGGER.info(
                "media_job_succeeded source=%s elapsed_ms=%d",
                supported.kind.value,
                round((time.monotonic() - started) * 1000),
            )

    async def approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        if message is None or user is None or chat is None:
            return
        if not self.services.access.can_manage(user.id) or chat.type not in {"group", "supergroup"}:
            return
        await self.services.repository.approve_chat(chat.id, user.id)
        await message.reply_text("Approved.")

    async def revoke(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        if message is None or user is None or chat is None:
            return
        if not self.services.access.can_manage(user.id) or chat.type not in {"group", "supergroup"}:
            return
        await self.services.repository.revoke_chat(chat.id)
        await message.reply_text("Revoked.")

    async def _access_decision(
        self,
        user_id: int,
        chat_id: int,
        chat_type: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> Decision:
        preliminary = await self.services.access.evaluate(
            user_id=user_id,
            chat_id=chat_id,
            chat_type=chat_type,
            bot_is_admin=False,
        )
        if preliminary is not Decision.ALLOW or chat_type == "private":
            return preliminary
        try:
            member = await context.bot.get_chat_member(chat_id, context.bot.id)
        except Exception:
            return Decision.IGNORE
        is_admin = member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
        return await self.services.access.evaluate(
            user_id=user_id,
            chat_id=chat_id,
            chat_type=chat_type,
            bot_is_admin=is_admin,
        )

    async def _extract_and_publish(
        self,
        url: SupportedUrl,
        *,
        chat_id: int,
        reply_to: int,
        workspace: JobWorkspace,
    ) -> None:
        if url.kind in {SourceKind.TIKTOK, SourceKind.FACEBOOK}:
            result = await self.services.video.download(url, workspace)
            await self.services.publisher.send_video(chat_id, reply_to, result.asset, None)
            return
        if url.kind is SourceKind.AMIAMI:
            product = await self.services.amiami.extract(url, workspace)
            await self._publish_product(product, chat_id, reply_to)
            return
        if url.kind is SourceKind.NIN_NIN:
            product = await self.services.nin_nin.extract(url, workspace)
            await self._publish_product(product, chat_id, reply_to)
            return
        if url.kind is SourceKind.X:
            post = await self.services.x_post.extract(url, workspace)
            await self._publish_post(post, chat_id, reply_to)
            return
        raise BotError(ErrorCode.UNSUPPORTED)

    async def _publish_product(
        self,
        product: ProductResult,
        chat_id: int,
        reply_to: int,
    ) -> None:
        euros = await self.services.exchange.jpy_to_eur(product.price_jpy)
        lines = [f"<b>{html.escape(product.name)}</b>"]
        if product.manufacturer:
            lines.append(html.escape(product.manufacturer))
        lines.extend([_yen(product.price_jpy), f"≈ €{euros:,.2f}"])
        await self.services.publisher.send_photos(
            chat_id,
            reply_to,
            product.images,
            "\n".join(lines),
        )

    async def _publish_post(self, post: PostResult, chat_id: int, reply_to: int) -> None:
        text = _post_text(post)
        if post.video is not None:
            caption = text if len(text) <= CAPTION_LIMIT else None
            if caption is None:
                await self.services.publisher.send_text(
                    chat_id, reply_to, _limit(text, MESSAGE_LIMIT)
                )
            await self.services.publisher.send_video(chat_id, reply_to, post.video, caption)
            return
        if post.photos:
            caption = text if len(text) <= CAPTION_LIMIT else ""
            if not caption:
                await self.services.publisher.send_text(
                    chat_id, reply_to, _limit(text, MESSAGE_LIMIT)
                )
            await self.services.publisher.send_photos(
                chat_id,
                reply_to,
                post.photos[:4],
                caption,
            )
            return
        await self.services.publisher.send_text(chat_id, reply_to, _limit(text, MESSAGE_LIMIT))


def _post_text(post: PostResult) -> str:
    header = f"<b>{html.escape(post.author_name)}</b> (@{html.escape(post.author_handle)})"
    return f"{header}\n\n{html.escape(post.text)}" if post.text else header


def _limit(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _yen(value: Decimal) -> str:
    return f"¥{value:,.0f}"

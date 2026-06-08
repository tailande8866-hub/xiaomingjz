import logging
from typing import Optional

from sqlalchemy import select
from telegram import InlineKeyboardMarkup, User
from telegram.ext import ContextTypes

from ..models import AdminGlobalConfig, get_db_session
from ..repositories.group_repo import GroupRepo

logger = logging.getLogger(__name__)


class JoinWelcomeService:
    """Send join-welcome messages for authorized groups."""

    async def send_join_welcome(
        self,
        chat_id: int,
        bot_id: str,
        new_user: User,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        async with get_db_session() as db:
            group_repo = GroupRepo(db, bot_id)
            group = await group_repo.get_by_group_id(chat_id)
            if not group:
                logger.info(f"[BOT:{bot_id}] Group {chat_id} not found in DB, skip join welcome")
                return
            if not getattr(group, "is_active", False) or getattr(group, "status", "") not in ("ACTIVE", "active"):
                logger.info(
                    f"[BOT:{bot_id}] Group {chat_id} is not active/authorized "
                    f"(is_active={getattr(group, 'is_active', None)}, status={getattr(group, 'status', None)}), skip join welcome"
                )
                return

            from ..services.global_config_service import global_config_service

            group_has_custom_welcome = bool(
                group.join_welcome_enabled
                and (
                    group.join_welcome_message
                    or group.join_welcome_file_id
                    or group.join_welcome_caption
                )
            )
            group_has_any_welcome_config = bool(
                group.join_welcome_message
                or group.join_welcome_file_id
                or group.join_welcome_caption
            )

            if group_has_custom_welcome:
                is_enabled = bool(group.join_welcome_enabled)
                msg_text = group.join_welcome_message or ""
                welcome_type = group.join_welcome_type or "text"
                media_file_id = group.join_welcome_file_id or None
                buttons_text = None
                list_items = []
                parse_mode = group.join_welcome_parse_mode or ("HTML" if msg_text else None)
                logger.info(
                    f"[BOT:{bot_id}] group join welcome config found for group {chat_id}, "
                    f"enabled={is_enabled}, type={welcome_type}, has_media={bool(media_file_id)}"
                )
            else:
                if group_has_any_welcome_config and not group.join_welcome_enabled:
                    logger.info(
                        f"[BOT:{bot_id}] group welcome config exists but disabled for group {chat_id}; "
                        "falling back to global join welcome"
                    )
                enabled_value = await global_config_service.get_config(db, bot_id, "welcome_ad_enabled")
                is_enabled = bool(enabled_value) if isinstance(enabled_value, bool) else False
                logger.info(f"[BOT:{bot_id}] welcome_ad_enabled={enabled_value}, is_enabled={is_enabled}")
                if not is_enabled:
                    logger.info(f"[BOT:{bot_id}] Global join welcome disabled, skip for group {chat_id}")
                    return

                welcome_message = await global_config_service.get_config(db, bot_id, "welcome_message")
                welcome_type = await global_config_service.get_config(db, bot_id, "welcome_type")
                welcome_media = await global_config_service.get_config(db, bot_id, "welcome_media_file_id")
                welcome_buttons = await global_config_service.get_config(db, bot_id, "welcome_buttons")
                welcome_message_list = await global_config_service.get_config(db, bot_id, "welcome_message_list")

                msg_text = welcome_message if isinstance(welcome_message, str) and welcome_message else ""
                welcome_type = welcome_type if isinstance(welcome_type, str) and welcome_type else "text"
                media_file_id = welcome_media if isinstance(welcome_media, str) and welcome_media else None
                buttons_text = welcome_buttons if isinstance(welcome_buttons, str) and welcome_buttons else None
                list_items = welcome_message_list if isinstance(welcome_message_list, list) else []
                parse_mode = "HTML" if msg_text else None

            logger.info(
                f"[BOT:{bot_id}] Welcome config: msg_text='{msg_text[:50] if msg_text else ''}...', "
                f"type={welcome_type}, has_media={bool(media_file_id)}, has_buttons={bool(buttons_text)}, "
                f"list_count={len(list_items)}"
            )

            if not list_items and not msg_text and not media_file_id:
                logger.info(f"[BOT:{bot_id}] No welcome content configured for group {chat_id}")
                return

            delete_last_enabled = await self._is_delete_last_enabled(bot_id, db)
            welcome_delete_minutes = await global_config_service.get_config(db, bot_id, "welcome_delete_minutes")
            auto_delete_minutes = welcome_delete_minutes if isinstance(welcome_delete_minutes, int) else 0
            reply_markup = self._parse_buttons(buttons_text) if buttons_text else None

            def render_text(raw_text: str) -> str:
                text_value = raw_text or ""
                text_value = text_value.replace(
                    "@username",
                    f"<a href='tg://user?id={new_user.id}'>{new_user.username or new_user.first_name or '新朋友'}</a>",
                )
                text_value = text_value.replace("{username}", new_user.username or new_user.first_name or "新朋友")
                text_value = text_value.replace("{group_name}", group.group_name or "本群")
                text_value = text_value.replace("{{name}}", new_user.first_name or "新朋友")
                text_value = text_value.replace(
                    "{{mention}}",
                    f"<a href='tg://user?id={new_user.id}'>{new_user.first_name or '新朋友'}</a>",
                )
                text_value = text_value.replace("{{groupname}}", group.group_name or "本群")
                return text_value

            async def send_entry(entry: dict):
                entry_type = entry.get("type") if isinstance(entry, dict) else "text"
                raw_text = entry.get("text") if isinstance(entry, dict) and entry_type == "text" else (
                    entry.get("caption") if isinstance(entry, dict) else msg_text
                ) or ""
                entry_text = render_text(raw_text)
                entry_file_id = entry.get("file_id") if isinstance(entry, dict) else media_file_id

                if entry_type == "photo" and entry_file_id:
                    return await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=entry_file_id,
                        caption=entry_text or None,
                        parse_mode=parse_mode if entry_text else None,
                        reply_markup=reply_markup,
                    )
                if entry_type == "video" and entry_file_id:
                    return await context.bot.send_video(
                        chat_id=chat_id,
                        video=entry_file_id,
                        caption=entry_text or None,
                        parse_mode=parse_mode if entry_text else None,
                        reply_markup=reply_markup,
                    )
                if entry_type == "animation" and entry_file_id:
                    return await context.bot.send_animation(
                        chat_id=chat_id,
                        animation=entry_file_id,
                        caption=entry_text or None,
                        parse_mode=parse_mode if entry_text else None,
                        reply_markup=reply_markup,
                    )
                if entry_type == "document" and entry_file_id:
                    return await context.bot.send_document(
                        chat_id=chat_id,
                        document=entry_file_id,
                        caption=entry_text or None,
                        parse_mode=parse_mode if entry_text else None,
                        reply_markup=reply_markup,
                    )
                if entry_type == "sticker" and entry_file_id:
                    return await context.bot.send_sticker(
                        chat_id=chat_id,
                        sticker=entry_file_id,
                        reply_markup=reply_markup,
                    )
                return await context.bot.send_message(
                    chat_id=chat_id,
                    text=entry_text or render_text(msg_text),
                    parse_mode=parse_mode or "HTML",
                    reply_markup=reply_markup,
                )

            sent_messages = []
            try:
                if list_items:
                    for entry in list_items:
                        sent_message = await send_entry(entry)
                        if sent_message:
                            sent_messages.append(sent_message)
                else:
                    single_entry = {
                        "type": welcome_type,
                        "text": msg_text,
                        "file_id": media_file_id,
                        "caption": msg_text,
                    }
                    sent_message = await send_entry(single_entry)
                    if sent_message:
                        sent_messages.append(sent_message)

                if not sent_messages:
                    logger.info(f"[BOT:{bot_id}] Welcome content configured but nothing was sent for group {chat_id}")
                    return

                logger.info(
                    f"[BOT:{bot_id}] Sent join welcome to user {new_user.id} in group {chat_id}, "
                    f"count={len(sent_messages)}"
                )

                if delete_last_enabled:
                    await self._delete_last_welcome_message(context, chat_id, bot_id)
                    for sent_message in sent_messages:
                        await self._record_last_welcome_message(chat_id, bot_id, sent_message.message_id)
                elif auto_delete_minutes > 0:
                    for sent_message in sent_messages:
                        await self._schedule_welcome_deletion(
                            context,
                            chat_id,
                            bot_id,
                            sent_message.message_id,
                            auto_delete_minutes,
                        )
            except Exception:
                logger.exception(f"[BOT:{bot_id}] Failed to send join welcome")

    async def _is_delete_last_enabled(self, bot_id: str, db) -> bool:
        from ..services.global_config_service import global_config_service

        welcome_delete_prev = await global_config_service.get_config(db, bot_id, "welcome_delete_prev")
        return bool(welcome_delete_prev) if isinstance(welcome_delete_prev, bool) else False

    async def _delete_last_welcome_message(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, bot_id: str):
        cache_key = f"last_welcome_msg_{bot_id}_{chat_id}"
        last_message_id = None

        if hasattr(self, "_welcome_message_cache"):
            last_message_id = self._welcome_message_cache.get(cache_key)

        if last_message_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=last_message_id)
                logger.info(f"[BOT:{bot_id}] Deleted last welcome message {last_message_id} in group {chat_id}")
                self._welcome_message_cache.pop(cache_key, None)
            except Exception as e:
                logger.warning(f"[BOT:{bot_id}] Failed to delete last welcome message: {e}")

    async def _record_last_welcome_message(self, chat_id: int, bot_id: str, message_id: int):
        cache_key = f"last_welcome_msg_{bot_id}_{chat_id}"
        if not hasattr(self, "_welcome_message_cache"):
            self._welcome_message_cache = {}
        self._welcome_message_cache[cache_key] = message_id
        logger.debug(f"[BOT:{bot_id}] Recorded last welcome message {message_id} for group {chat_id}")

    async def _schedule_welcome_deletion(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        bot_id: str,
        message_id: int,
        minutes: int,
    ):
        import asyncio

        async def delete_after_delay():
            await asyncio.sleep(minutes * 60)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info(f"[BOT:{bot_id}] Auto-deleted welcome message {message_id} after {minutes} minutes")
            except Exception as e:
                logger.warning(f"[BOT:{bot_id}] Failed to auto-delete welcome message: {e}")

        asyncio.create_task(delete_after_delay())
        logger.debug(f"[BOT:{bot_id}] Scheduled welcome message {message_id} for deletion in {minutes} minutes")

    def _parse_buttons(self, buttons_text: str) -> Optional[InlineKeyboardMarkup]:
        if not buttons_text:
            return None

        from telegram import InlineKeyboardButton

        keyboard = []
        lines = buttons_text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            row = []
            for btn_text in [btn.strip() for btn in line.split("&&")]:
                if btn_text.startswith("#p"):
                    btn_text = btn_text[2:]
                elif btn_text.startswith("#r"):
                    btn_text = btn_text[2:]
                elif btn_text.startswith("#g"):
                    btn_text = btn_text[2:]

                if "-" in btn_text:
                    parts = btn_text.rsplit("-", 1)
                    name = parts[0].strip()
                    url = parts[1].strip()
                    if name and url:
                        row.append(InlineKeyboardButton(name, url=url))
            if row:
                keyboard.append(row)

        return InlineKeyboardMarkup(keyboard) if keyboard else None


join_welcome_service = JoinWelcomeService()

"""
话题模式 Handler - 完整实现

功能：
1. 话题模式设置页面（UI与设计图一致）
2. 群组检测和确认开启流程
3. 用户私聊 → 群组话题转发（支持所有消息类型）
4. 管理员群组话题回复 → 用户私聊
5. 群组失效自动降级到私聊客服模式
6. 私聊客服模式（切换/禁言/拉黑/查看信息）
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatType, ParseMode
from sqlalchemy import select, and_

from ..models import get_db_session
from ..models.enums import GroupStatus
from ..models.group import Group
from ..models.topic_mode import TopicModeSettings, UserTopic, UserActiveTarget, UserBlock
from ..models.group import TopicForwardMap
from ..repositories.topic_mode_repo import (
    TopicModeSettingsRepo, UserTopicRepo, UserActiveTargetRepo, UserBlockRepo
)
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import get_user_role, UserRole

logger = logging.getLogger(__name__)

SUPER_ADMIN_ID = 7862093562


def _reason_priority(detail: str) -> int:
    if "未授权" in detail:
        return 60
    if "未开启话题模式" in detail:
        return 50
    if "不是管理员" in detail:
        return 40
    if "没有管理话题权限" in detail:
        return 30
    if "不是 supergroup" in detail:
        return 20
    if "校验群组时发生异常" in detail:
        return 10
    return 0


async def _save_topic_mode_settings(bot_id: str, user_id: int, group_id: int, group_title: str):
    async with get_db_session() as db:
        repo = TopicModeSettingsRepo(db, bot_id)
        await repo.upsert(
            enabled=True,
            group_id=group_id,
            group_title=group_title,
            created_by=user_id,
        )


async def _answer_and_refresh(query, text: str, show_alert: bool, refresh_coro=None):
    await query.answer(text, show_alert=show_alert)
    if refresh_coro is not None:
        await asyncio.sleep(0.35)
        await refresh_coro


async def _validate_topic_group(context, group: Group):
    group_id = group.group_id
    group_title = group.group_name or str(group_id)
    group_status = getattr(group.status, "value", group.status)

    if group_status != GroupStatus.ACTIVE.value:
        logger.info(
            "[TopicMode] validate group failed group_id=%s group_title=%s reason=%s",
            group_id,
            group_title,
            "群组未授权",
        )
        return False, "群组未授权"

    if group.group_type != ChatType.SUPERGROUP:
        logger.info(
            "[TopicMode] validate group failed group_id=%s group_title=%s group_type=%s reason=%s",
            group_id,
            group_title,
            group.group_type,
            "群组不是 supergroup",
        )
        return False, "群组不是 supergroup"

    chat_info = await context.bot.get_chat(group_id)
    if not getattr(chat_info, "is_forum", False):
        logger.info(
            "[TopicMode] validate group failed group_id=%s group_title=%s chat_type=%s is_forum=%s reason=%s",
            group_id,
            getattr(chat_info, "title", None) or group_title,
            getattr(chat_info, "type", None),
            getattr(chat_info, "is_forum", False),
            "群组未开启话题模式",
        )
        return False, "群组未开启话题模式"

    bot_member = await context.bot.get_chat_member(group_id, context.bot.id)
    if bot_member.status not in ("administrator", "creator"):
        logger.info(
            "[TopicMode] validate group failed group_id=%s group_title=%s bot_member_status=%s reason=%s",
            group_id,
            getattr(chat_info, "title", None) or group_title,
            bot_member.status,
            "Bot 不是管理员",
        )
        return False, "Bot 不是管理员"

    can_manage_topics = getattr(bot_member, "can_manage_topics", False)
    if bot_member.status != "creator" and not can_manage_topics:
        logger.info(
            "[TopicMode] validate group failed group_id=%s group_title=%s bot_member_status=%s can_manage_topics=%s reason=%s",
            group_id,
            getattr(chat_info, "title", None) or group_title,
            bot_member.status,
            can_manage_topics,
            "Bot 没有管理话题权限",
        )
        return False, "Bot 没有管理话题权限"

    group_title = chat_info.title or group.group_name or str(group_id)
    logger.info(
        "[TopicMode] validate group success group_id=%s group_title=%s chat_type=%s is_forum=%s bot_member_status=%s",
        group_id,
        group_title,
        getattr(chat_info, "type", None),
        getattr(chat_info, "is_forum", False),
        bot_member.status,
    )
    return True, group_title

async def handle_topic_enable(query, context):
    """从私聊设置页直接开启话题模式。"""
    bot_id = get_current_bot_id(context)
    user = query.from_user
    bot_username = context.bot.username or ""

    try:
        user_role = await get_user_role(user.id, bot_id=bot_id)
        if user.id != SUPER_ADMIN_ID and user_role not in (UserRole.SUPER_ADMIN, UserRole.BOT_OWNER):
            await _answer_and_refresh(query, "⚠️ 只有超级管理员或Bot创建者可以开启话题模式", True)
            return

        logger.info(
            "[TopicMode] topic:enable clicked callback_data=%s user_id=%s bot_id=%s bot_username=%s handler_file=%s handler_func=%s",
            getattr(query, "data", ""),
            user.id,
            bot_id,
            bot_username,
            __file__,
            "handle_topic_enable",
        )

        async with get_db_session() as db:
            result = await db.execute(
                select(Group).where(
                    and_(
                        Group.bot_id == bot_id,
                        Group.status == GroupStatus.ACTIVE.value,
                        Group.is_active.is_(True),
                    )
                ).order_by(Group.id.desc())
            )
            groups = result.scalars().all()

        logger.info(
            "[TopicMode] candidate groups for enable bot_id=%s user_id=%s count=%s group_ids=%s",
            bot_id,
            user.id,
            len(groups),
            [g.group_id for g in groups],
        )

        if not groups:
            await _answer_and_refresh(
                query,
                '请先点击“拉我进群”，把机器人加入群组并授权后再开启',
                True,
                show_topic_settings_page(query, context, notice='⚠️ 开启失败：请先点击“拉我进群”，把机器人加入群组并授权后再开启'),
            )
            return

        best_error = None
        for group in groups:
            try:
                ok, detail = await _validate_topic_group(context, group)
            except Exception:
                logger.exception(
                    "[TopicMode] Failed to validate group group_id=%s bot_id=%s",
                    group.group_id,
                    bot_id,
                )
                detail = "校验群组时发生异常"
                if best_error is None or _reason_priority(detail) > _reason_priority(best_error):
                    best_error = detail
                continue

            if ok:
                await _save_topic_mode_settings(bot_id, user.id, group.group_id, detail)
                logger.info(
                    "[TopicMode] topic mode enabled bot_id=%s user_id=%s group_id=%s group_title=%s",
                    bot_id,
                    user.id,
                    group.group_id,
                    detail,
                )
                await _answer_and_refresh(
                    query,
                    "✅ 话题模式已开启",
                    False,
                    show_topic_settings_page(query, context, notice=f"✅ 已开启：{detail}"),
                )
                return

            if best_error is None or _reason_priority(detail) > _reason_priority(best_error):
                best_error = detail

        logger.info(
            "[TopicMode] no eligible group for topic mode bot_id=%s user_id=%s chosen_reason=%s",
            bot_id,
            user.id,
            best_error,
        )
        final_error = best_error or "没有可用群组可开启话题模式"
        await _answer_and_refresh(
            query,
            final_error,
            True,
            show_topic_settings_page(query, context, notice=f"⚠️ 开启失败：{final_error}"),
        )

    except Exception:
        logger.exception("[TopicMode] Failed to enable topic mode bot_id=%s user_id=%s", bot_id, user.id)
        await _answer_and_refresh(
            query,
            "开启话题模式失败",
            True,
            show_topic_settings_page(query, context, notice="❌ 开启失败，请查看日志"),
        )

# ============================================================================
# 一、话题模式设置页面
# ============================================================================

async def show_topic_settings_page(query, context, notice: str | None = None):
    """显示话题模式设置页面（区分未开启/已开启两种状态）"""
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        repo = TopicModeSettingsRepo(db, bot_id)
        settings = await repo.get_settings()
        enabled = settings.enabled if settings else False
        group_title = settings.group_title if settings else None

    bot_username = context.bot.username

    if not enabled:
        # ========== 未开启状态 ==========
        text = (
            "📌 <b>群组话题模式</b>\n\n"
            "用户与机器人对话时，会在群内创建独立话题窗口，管理员可直接在话题内回复用户。\n\n"
            "⚙️ <b>开启步骤：</b>\n\n"
            "1. 创建私人群组\n"
            "2. 开启群组「话题模式(Topics)」\n"
            "3. 点击按钮邀请机器人入群\n"
            "4. 授予机器人全部权限\n"
            "5. 在群内发送「确认开启」\n\n"
            "当前状态：⭕ 未开启\n\n"
            "💡 开启后仅支持通过话题回复用户；群组失效时会自动切回机器人私聊模式，消息不会遗漏。"
        )
        if notice:
            text += f"\n\n{html.escape(notice)}"

        keyboard = [
            [InlineKeyboardButton("➡️ 拉我进群", url=f"https://t.me/{bot_username}?startgroup=topic_mode"),
             InlineKeyboardButton("✅ 开启话题模式", callback_data="topic:enable")],
            [InlineKeyboardButton("⬅️ 返回", callback_data="settings:main")],
        ]
    else:
        # ========== 已开启状态 ==========
        text = (
            "📌 <b>群组话题模式</b>\n\n"
            "用户与机器人对话时，会在群内创建独立话题窗口，管理员可直接在话题内回复用户。\n\n"
            f"当前状态：🟢 已开启\n"
            f"转发群组：{html.escape(group_title) if group_title else '未设置'}\n\n"
            "💡 已通过话题模式处理用户对话；群组失效时会自动切回机器人私聊模式，消息不会遗漏。"
        )
        if notice:
            text += f"\n\n{html.escape(notice)}"

        keyboard = [
            [InlineKeyboardButton("🚪 退出话题模式", callback_data="topic:disable"),
             InlineKeyboardButton("👥 查看绑定群组", callback_data="topic:view_group")],
            [InlineKeyboardButton("⬅️ 返回", callback_data="settings:main")],
        ]

    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        logger.error(f"[TopicMode] 编辑设置页面失败: {e}", exc_info=True)


# ============================================================================
# 二、群组检测和确认开启流程
# ============================================================================

async def handle_topic_view_group(query, context):
    """查看绑定群组"""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        repo = TopicModeSettingsRepo(db, bot_id)
        settings = await repo.get_settings()

    if not settings or not settings.enabled:
        await query.answer("话题模式未开启", show_alert=True)
        return

    group_title = settings.group_title or "未命名群组"
    group_id = settings.group_id

    text = (
        f"👥 <b>绑定群组信息</b>\n\n"
        f"群组名称：{html.escape(group_title)}\n"
        f"群组ID：<code>{group_id}</code>\n\n"
        "点击下方按钮直接进入群组："
    )

    keyboard = [
        [InlineKeyboardButton("📢 进入群组", url=f"https://t.me/c/{abs(group_id) // 1000000000}_{group_id % 1000000000}")],
        [InlineKeyboardButton("⬅️ 返回", callback_data="topic:settings")]
    ]

    await query.answer()
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def handle_topic_disable(query, context):
    """退出话题模式"""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    bot_id = get_current_bot_id(context)
    user_id = query.from_user.id

    async with get_db_session() as db:
        repo = TopicModeSettingsRepo(db, bot_id)
        await repo.disable_topic_mode()
        await repo.log_action(user_id, "disable", "用户手动关闭")

    text = (
        "🚪 <b>话题模式已关闭</b>\n\n"
        "系统已切回机器人私聊模式，用户可以通过私聊直接与机器人对话。"
    )

    keyboard = [
        [InlineKeyboardButton("⬅️ 返回", callback_data="topic:settings")]
    ]

    await query.answer("话题模式已关闭")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def handle_topic_group_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    机器人被拉入群组后自动检测。
    通过 /start topic_mode 参数触发。
    """
    if not update.message or not update.effective_chat:
        return

    chat = update.effective_chat
    bot_id = get_current_bot_id(context)

    # 只处理 supergroup
    if chat.type != ChatType.SUPERGROUP:
        return

    group_id = chat.id
    group_title = chat.title or str(group_id)

    logger.info(f"[TopicMode] Bot被拉入群组: group_id={group_id}, title={group_title}, bot_id={bot_id}")

    try:
        # 检查群组是否开启了 Topics
        chat_info = await context.bot.get_chat(group_id)
        is_forum = getattr(chat_info, 'is_forum', False)

        if not is_forum:
            await context.bot.send_message(
                chat_id=group_id,
                text=(
                    "⚠️ <b>群组未开启话题模式</b>\n\n"
                    "请按以下步骤操作：\n"
                    "1. 打开群组设置\n"
                    "2. 找到「话题」选项并开启\n"
                    "3. 然后将机器人踢出并重新邀请"
                ),
                parse_mode="HTML"
            )
            return

        # 检查 bot 是否是管理员
        bot_member = await context.bot.get_chat_member(group_id, context.bot.id)
        if bot_member.status not in ("administrator", "creator"):
            await context.bot.send_message(
                chat_id=group_id,
                text="⚠️ 请先将机器人设为管理员，并授予管理话题权限",
                parse_mode="HTML"
            )
            return

        # 检查是否可以管理话题
        can_manage_topics = getattr(bot_member, 'can_manage_topics', False)
        if not can_manage_topics:
            await context.bot.send_message(
                chat_id=group_id,
                text="⚠️ 请给机器人「管理话题」权限",
                parse_mode="HTML"
            )
            return

        # 所有检查通过，发送确认按钮
        keyboard = [
            [InlineKeyboardButton("✅ 确认开启话题模式", callback_data=f"topic:confirm_enable:{group_id}")]
        ]
        await context.bot.send_message(
            chat_id=group_id,
            text="✅ <b>群组话题模式已准备就绪</b>\n请点击下方按钮确认开启",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"[TopicMode] 群组检测失败: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=f"❌ 检测失败：{html.escape(str(e))}",
                parse_mode="HTML"
            )
        except Exception:
            pass


async def handle_topic_confirm_enable(query, context, group_id: int):
    """确认开启话题模式"""
    bot_id = get_current_bot_id(context)
    user = query.from_user

    # 权限检查
    user_role = await get_user_role(user.id, bot_id=bot_id)
    if user.id != SUPER_ADMIN_ID and user_role not in (UserRole.SUPER_ADMIN, UserRole.BOT_OWNER):
        await query.answer("⚠️ 只有超级管理员或Bot创建者可以开启话题模式", show_alert=True)
        return

    group_title = "未知群组"
    try:
        chat_info = await context.bot.get_chat(group_id)
        group_title = chat_info.title or str(group_id)
    except Exception:
        pass

    async with get_db_session() as db:
        repo = TopicModeSettingsRepo(db, bot_id)
        settings = await repo.upsert(
            enabled=True,
            group_id=group_id,
            group_title=group_title,
            created_by=user.id,
        )

    await query.answer("✅ 话题模式已开启", show_alert=False)

    # 更新群内消息
    try:
        await query.edit_message_text(
            "✅ <b>群组话题模式已开启</b>\n\n"
            f"群组：{html.escape(group_title)}\n"
            "用户私聊机器人的消息将自动转发到此群组的话题中",
            parse_mode="HTML"
        )
    except Exception:
        pass

    # 私聊通知创建者
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=f"✅ <b>群组话题模式开启成功</b>\n\n群组：{html.escape(group_title)}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[TopicMode] 通知创建者失败: {e}", exc_info=True)


# ============================================================================
# 三、用户私聊 → 群组话题转发
# ============================================================================

async def handle_topic_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    处理用户私聊消息，转发到群组话题。
    支持所有消息类型：文本、图片、视频、文件、语音、表情、贴纸。
    返回 True 表示消息已被处理。
    """
    if not update.message or not update.effective_user:
        return False
    if update.effective_chat.type != ChatType.PRIVATE:
        return False

    user = update.effective_user
    bot_id = get_current_bot_id(context)

    # 管理员和bot owner的消息不转发
    user_role = await get_user_role(user.id, bot_id=bot_id)
    if user.id == SUPER_ADMIN_ID or user_role in (UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN):
        return False

    # 检查是否被封禁
    async with get_db_session() as db:
        block_repo = UserBlockRepo(db, bot_id)
        if await block_repo.is_blocked(user.id):
            await update.message.reply_text("⚠️ 你暂时无法发送消息")
            return True

        # 检查话题模式是否开启
        settings_repo = TopicModeSettingsRepo(db, bot_id)
        settings = await settings_repo.get_settings()
        if not settings or not settings.enabled or not settings.group_id:
            return False

        group_id = settings.group_id

    # 获取或创建用户话题
    topic_id = await _ensure_user_topic(context, bot_id, user.id, group_id, user.username, user.first_name)

    if topic_id is None:
        # 话题创建失败，降级到私聊客服模式
        logger.warning(f"[TopicMode] 话题创建失败，降级到私聊客服模式: user={user.id}")
        await _fallback_to_private_cs(update, context, bot_id, user, group_id)
        return True

    # 转发消息到话题
    try:
        copied = await context.bot.copy_message(
            chat_id=group_id,
            from_chat_id=user.id,
            message_id=update.message.message_id,
            message_thread_id=topic_id,
        )

        # 写入映射
        async with get_db_session() as db:
            db.add(TopicForwardMap(
                bot_id=bot_id,
                target_group_id=group_id,
                group_message_id=copied.message_id,
                user_id=user.id,
                username=user.username,
            ))
            await db.flush()

            # 更新最后消息时间
            topic_repo = UserTopicRepo(db, bot_id)
            await topic_repo.update_last_message(user.id)

        return True

    except Exception as e:
        error_str = str(e).lower()
        logger.error(f"[TopicMode] 转发消息到话题失败: {e}", exc_info=True)

        # 检查是否需要降级
        if any(kw in error_str for kw in [
            "bot was kicked", "chat not found",
            "message thread not found", "bad request",
            "forbidden", "not enough rights"
        ]):
            await _fallback_to_private_cs(update, context, bot_id, user, group_id)
            return True

        return False


async def _ensure_user_topic(context, bot_id: str, user_id: int,
                               group_id: int, username: str = None,
                               first_name: str = None) -> Optional[int]:
    """确保用户有话题，没有则自动创建"""
    async with get_db_session() as db:
        topic_repo = UserTopicRepo(db, bot_id)
        existing = await topic_repo.get_by_user(user_id)

        if existing and existing.topic_id and existing.active:
            # 验证话题是否仍然存在
            try:
                await context.bot.get_chat(group_id)
                return existing.topic_id
            except Exception:
                # 群组可能失效
                existing.active = False
                existing.topic_id = None
                await db.flush()

        # 创建新话题
        display_name = first_name or username or str(user_id)
        topic_name = f"{display_name} {user_id}"

        try:
            topic = await context.bot.create_forum_topic(
                chat_id=group_id,
                name=topic_name,
            )
            topic_id = topic.message_thread_id

            # 保存绑定
            await topic_repo.get_or_create(
                user_id=user_id,
                group_id=group_id,
                topic_id=topic_id,
                username=username,
                first_name=first_name,
            )

            logger.info(f"[TopicMode] 创建话题: user={user_id}, topic={topic_id}, group={group_id}")
            return topic_id

        except Exception as e:
            logger.error(f"[TopicMode] 创建话题失败: {e}", exc_info=True)
            return None


# ============================================================================
# 四、管理员群组话题回复 → 用户私聊
# ============================================================================

async def handle_topic_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    管理员在群组话题中回复消息时，转发到用户私聊。
    """
    if not update.message or not update.effective_chat:
        return False
    if not update.message.reply_to_message:
        return False

    bot_id = get_current_bot_id(context)
    chat_id = update.effective_chat.id
    reply_msg = update.message.reply_to_message
    reply_id = reply_msg.message_id

    async with get_db_session() as db:
        settings_repo = TopicModeSettingsRepo(db, bot_id)
        settings = await settings_repo.get_settings()
        if not settings or not settings.enabled or not settings.group_id:
            return False
        if settings.group_id != chat_id:
            return False

        # 查找映射
        stmt = select(TopicForwardMap).where(
            and_(
                TopicForwardMap.bot_id == bot_id,
                TopicForwardMap.target_group_id == chat_id,
                TopicForwardMap.group_message_id == reply_id,
            )
        )
        result = await db.execute(stmt)
        mapping = result.scalar_one_or_none()

    if not mapping:
        return False

    try:
        await context.bot.copy_message(
            chat_id=mapping.user_id,
            from_chat_id=chat_id,
            message_id=update.message.message_id,
        )
        await update.message.reply_text("✅ 回复已发送")
        return True
    except Exception as e:
        error_str = str(e).lower()
        logger.error(f"[TopicMode] 回复用户失败: {e}", exc_info=True)

        if "blocked" in error_str or "cannot send" in error_str:
            await update.message.reply_text("❌ 用户无法接收消息")
        else:
            await update.message.reply_text(f"❌ 回复失败：{html.escape(str(e)[:100])}")
        return True


# ============================================================================
# 五、群组失效自动降级
# ============================================================================

async def _fallback_to_private_cs(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   bot_id: str, user, group_id: int):
    """降级到私聊客服模式"""
    logger.warning(f"[TopicMode] 降级到私聊客服模式: bot_id={bot_id}, user={user.id}, group={group_id}")

    # 标记话题模式为失效
    async with get_db_session() as db:
        settings_repo = TopicModeSettingsRepo(db, bot_id)
        settings = await settings_repo.get_settings()
        if settings:
            settings.enabled = False
            await db.flush()

        # 停用所有话题
        topic_repo = UserTopicRepo(db, bot_id)
        await topic_repo.deactivate_all()

    # 通知管理员
    try:
        async with get_db_session() as db:
            from ..models.admin import Admin
            stmt = select(Admin).where(Admin.bot_id == bot_id)
            result = await db.execute(stmt)
            admins = result.scalars().all()

        for admin in admins:
            try:
                await context.bot.send_message(
                    chat_id=admin.user_id,
                    text=(
                        f"⚠️ <b>话题模式已自动降级</b>\n\n"
                        f"群组 {group_id} 已失效\n"
                        f"用户 {user.first_name or user.username or user.id} 的消息将通过私聊客服模式处理"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[TopicMode] 通知管理员失败: {e}", exc_info=True)

    # 通知用户
    try:
        await update.message.reply_text(
            "⚠️ 当前客服繁忙，您的消息已收到，请稍等回复",
            parse_mode="HTML"
        )
    except Exception:
        pass

    # 转发消息给管理员（私聊客服模式）
    await _forward_to_admin_private_cs(update, context, bot_id, user)


# ============================================================================
# 六、私聊客服模式
# ============================================================================

async def _forward_to_admin_private_cs(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                         bot_id: str, user):
    """将用户消息转发给管理员（私聊客服模式）"""
    async with get_db_session() as db:
        from ..models.admin import Admin
        stmt = select(Admin).where(Admin.bot_id == bot_id)
        result = await db.execute(stmt)
        admins = result.scalars().all()

    if not admins:
        logger.warning(f"[TopicMode] 没有管理员可以转发: bot_id={bot_id}")
        return

    user_display = user.first_name or user.username or str(user.id)

    for admin in admins:
        try:
            # 转发用户消息
            await context.bot.forward_message(
                chat_id=admin.user_id,
                from_chat_id=user.id,
                message_id=update.message.message_id,
            )

            # 发送提示
            keyboard = _build_cs_keyboard(bot_id, user.id, user_display)
            await context.bot.send_message(
                chat_id=admin.user_id,
                text=f"转发自 {html.escape(user_display)}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            break  # 只发给第一个管理员
        except Exception as e:
            logger.error(f"[TopicMode] 转发给管理员失败: {e}", exc_info=True)


def _build_cs_keyboard(bot_id: str, user_id: int, user_display: str) -> InlineKeyboardMarkup:
    """构建私聊客服模式按钮"""
    keyboard = [
        [InlineKeyboardButton(f"↩️切换至：{user_display}", callback_data=f"topic_cs:switch:{user_id}")],
        [
            InlineKeyboardButton("🚫1天", callback_data=f"topic_cs:block:{user_id}:1"),
            InlineKeyboardButton("🚫1周", callback_data=f"topic_cs:block:{user_id}:7"),
            InlineKeyboardButton("🚫1月", callback_data=f"topic_cs:block:{user_id}:30"),
            InlineKeyboardButton("🚫永久", callback_data=f"topic_cs:block:{user_id}:0"),
        ],
        [InlineKeyboardButton("👀查看信息", callback_data=f"topic_cs:info:{user_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_admin_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    管理员私聊bot时，自动转发给当前 active_chat_target。
    """
    if not update.message or not update.effective_user:
        return False
    if update.effective_chat.type != ChatType.PRIVATE:
        return False

    admin = update.effective_user
    bot_id = get_current_bot_id(context)

    # 检查是否是管理员
    user_role = await get_user_role(admin.id, bot_id=bot_id)
    if admin.id != SUPER_ADMIN_ID and user_role not in (UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN):
        return False

    async with get_db_session() as db:
        target_repo = UserActiveTargetRepo(db, bot_id)
        target = await target_repo.get_target(admin.id)

    if not target or not target.target_user_id:
        return False

    # 检查回复的消息是否来自其他用户（自动切换目标）
    if update.message.reply_to_message:
        replied_msg = update.message.reply_to_message
        if replied_msg.forward_from:
            new_target_id = replied_msg.forward_from.id
            if new_target_id != target.target_user_id:
                # 自动切换目标
                async with get_db_session() as db:
                    await target_repo.set_target(admin.id, new_target_id)
                target.target_user_id = new_target_id

    # 转发消息给目标用户
    try:
        await context.bot.copy_message(
            chat_id=target.target_user_id,
            from_chat_id=admin.id,
            message_id=update.message.message_id,
        )
        return True
    except Exception as e:
        logger.error(f"[TopicMode] 管理员转发给用户失败: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ 发送失败：{html.escape(str(e)[:100])}")
        except Exception:
            pass
        return True


# ============================================================================
# 七、私聊客服回调处理
# ============================================================================

async def handle_cs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊客服模式的所有回调"""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("topic_cs:"):
        return

    parts = query.data.split(":")
    if len(parts) < 3:
        return

    action = parts[1]

    if action == "switch":
        await _handle_cs_switch(query, context, int(parts[2]))
    elif action == "block":
        user_id = int(parts[2])
        days = int(parts[3])
        permanent = (days == 0)
        await _handle_cs_block(query, context, user_id, days, permanent)
    elif action == "info":
        await _handle_cs_info(query, context, int(parts[2]))


async def _handle_cs_switch(query, context, target_user_id: int):
    """切换聊天目标"""
    bot_id = get_current_bot_id(context)
    admin_id = query.from_user.id

    async with get_db_session() as db:
        target_repo = UserActiveTargetRepo(db, bot_id)
        await target_repo.set_target(admin_id, target_user_id)

        # 获取用户信息
        try:
            user = await context.bot.get_chat(target_user_id)
            user_display = user.first_name or user.username or str(target_user_id)
        except Exception:
            user_display = str(target_user_id)

    await query.answer(f"✅ 已切换到：{user_display}", show_alert=False)


async def _handle_cs_block(query, context, user_id: int, days: int, permanent: bool):
    """禁言/拉黑用户"""
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        block_repo = UserBlockRepo(db, bot_id)
        duration_text = "永久" if permanent else f"{days}天"
        await block_repo.block_user(user_id, duration_days=days if not permanent else None, permanent=permanent)

    await query.answer(f"🚫 已禁言 {duration_text}", show_alert=True)


async def _handle_cs_info(query, context, user_id: int):
    """查看用户信息"""
    bot_id = get_current_bot_id(context)

    try:
        user = await context.bot.get_chat(user_id)
        username = user.username or "未设置"
        first_name = user.first_name or "未知"
    except Exception:
        username = "未知"
        first_name = "未知"

    # 检查封禁状态
    block_text = "❌ 未封禁"
    async with get_db_session() as db:
        block_repo = UserBlockRepo(db, bot_id)
        block = await block_repo.get_block(user_id)
        if block:
            if block.permanent:
                block_text = "🚫 永久封禁"
            elif block.blocked_until and block.blocked_until > datetime.utcnow():
                remaining = (block.blocked_until - datetime.utcnow()).days
                block_text = f"🚫 封禁中（剩余{remaining}天）"

    text = (
        f"👤 <b>用户信息</b>\n\n"
        f"用户ID：<code>{user_id}</code>\n"
        f"昵称：{html.escape(first_name)}\n"
        f"用户名：@{html.escape(username)}\n"
        f"状态：{block_text}"
    )

    try:
        await query.edit_message_text(text, parse_mode="HTML")
    except Exception:
        await query.answer(text, show_alert=True)


# ============================================================================
# 八、话题模式关闭
# ============================================================================

async def handle_topic_disable(query, context):
    """关闭话题模式"""
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        repo = TopicModeSettingsRepo(db, bot_id)
        settings = await repo.get_settings()
        if settings:
            settings.enabled = False
            await db.flush()

        # 停用所有话题
        topic_repo = UserTopicRepo(db, bot_id)
        await topic_repo.deactivate_all()

    await query.answer("✅ 话题模式已关闭", show_alert=False)
    await show_topic_settings_page(query, context)


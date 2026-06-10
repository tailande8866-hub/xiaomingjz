import html
import logging
import os
import re
import traceback
from datetime import datetime, timedelta

from sqlalchemy import and_, desc, select
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import config
from ..models import BotCreation, Subscription, get_db_session
from ..repositories.super_admin_repo import (
    ClosedUserRepo,
    GlobalForwardBlacklistRepo,
    PendingProvisionRepo,
    SuperAdminMessageStateRepo,
    SuperAdminSettingsRepo,
)
from ..services.manual_provision_service import manual_provision_service
from ..services.token_check_service import TOKEN_PATTERN
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.state_manager import clear_state
from ..utils.token_encryptor import token_encryptor

logger = logging.getLogger(__name__)

SUPER_ADMIN_ID = 7862093562
SUPER_ADMIN_SCOPE_BOT_ID = "main_bot"
SA_STATE_KEY = "sa_v2_state"
SA_TARGET_USER_ID_KEY = "sa_v2_target_user_id"
SA_TARGET_USERNAME_KEY = "sa_v2_target_username"
SA_TARGET_DAYS_KEY = "sa_v2_target_days"
SA_REPLY_SOURCE_BOT_ID_KEY = "sa_v2_reply_source_bot_id"
SA_REPLY_SOURCE_BOT_USERNAME_KEY = "sa_v2_reply_source_bot_username"

STATE_PROVISION_WAIT_USER = "provision_wait_user"
STATE_PROVISION_WAIT_DAYS = "provision_wait_days"
STATE_PROVISION_WAIT_TOKEN = "provision_wait_token"
STATE_CLOSE_WAIT_USER = "close_wait_user"
STATE_UNBLOCK_WAIT_USER = "unblock_wait_user"

USER_SEND_TOKEN_GUIDE = (
    "🎉 恭喜！您的使用时长已开通成功\n"
    "🤖 机器人只差一步激活，按下面操作即可：\n\n"
    "1️⃣ 点击 @BotFather 进入对话\n"
    "2️⃣ 发送 /newbot 创建机器人\n"
    "3️⃣ 复制生成的 API Token\n"
    "4️⃣ 发送 Token 给我，激活全功能\n\n"
    "🔒 温馨提示：Token 请勿泄露，仅用于绑定您的机器人"
)

BLACKLIST_DURATION_MAP = {
    "1d": ("1天", 1, False),
    "1w": ("1周", 7, False),
    "1m": ("1月", 30, False),
    "perm": ("永久", None, True),
}


def _is_super_admin(user_id: int) -> bool:
    return int(user_id or 0) == SUPER_ADMIN_ID


def _mask_token(token: str) -> str:
    if not token:
        return "<empty>"
    if ":" not in token:
        return f"{token[:3]}***"
    prefix, suffix = token.split(":", 1)
    return f"{prefix}:***{suffix[-4:]}" if len(suffix) > 4 else f"{prefix}:***"


def _truncate_name(name: str | None, limit: int = 16) -> str:
    raw = (name or "").strip()
    if not raw:
        return "无"
    if len(raw) <= limit:
        return raw
    return raw[:limit]


def _clear_super_admin_flow_state(context: ContextTypes.DEFAULT_TYPE):
    clear_state(
        context,
        SA_STATE_KEY,
        SA_TARGET_USER_ID_KEY,
        SA_TARGET_USERNAME_KEY,
        SA_TARGET_DAYS_KEY,
        SA_REPLY_SOURCE_BOT_ID_KEY,
        SA_REPLY_SOURCE_BOT_USERNAME_KEY,
    )


def _is_test_runtime(current_bot_id: str | None) -> bool:
    return current_bot_id == "test_bot" or os.environ.get("INSTANCE_ID") == "test_bot"


def _is_super_admin_scope_runtime(current_bot_id: str | None) -> bool:
    is_main_runtime = os.environ.get("IS_MAIN_BOT", "true").lower() == "true"
    return is_main_runtime or current_bot_id == SUPER_ADMIN_SCOPE_BOT_ID or _is_test_runtime(current_bot_id)


def _format_run_status(status: str | None) -> str:
    return {
        "running": "✅ 正常运行",
        "stopped": "❌ 未运行",
        "failed": "⚠️ 启动失败",
        "restarting": "🔄 重启中",
        "disconnected": "➖ 已断开",
        "creating": "🔄 创建中",
        "error": "⚠️ 异常",
    }.get(status or "", f"⚠️ {status or '未知'}")


def _format_token_status(status: str | None) -> str:
    return {
        "normal": "✅ 正常",
        "invalid": "❌ 已失效",
        "checking": "🔄 检测中",
        "error": "⚠️ 检测失败",
        "disabled": "➖ 已停用",
    }.get(status or "", f"⚠️ {status or '未知'}")


def _build_created_bot_success_payload(bot_creation: BotCreation, expire_time: datetime) -> tuple[str, InlineKeyboardMarkup]:
    from .bot_management_handler import _build_bot_manage_scene_text, render_bot_manage_buttons
    if expire_time and not getattr(bot_creation, "expire_time", None):
        bot_creation.expire_time = expire_time
    text = _build_bot_manage_scene_text(bot_creation, "created_success")
    keyboard = render_bot_manage_buttons(bot_creation.instance_id, bot_creation.telegram_id, "created_success")
    return text, keyboard


async def _send_created_bot_success_card(bot, chat_id: int, bot_creation: BotCreation, expire_time: datetime):
    text, reply_markup = _build_created_bot_success_payload(bot_creation, expire_time)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def _resolve_target_user(identifier: str) -> tuple[int | None, str | None]:
    raw = (identifier or "").strip()
    if not raw:
        return None, None
    resolved = await manual_provision_service.resolve_user_id(raw)
    if not resolved:
        return None, None
    username = raw[1:] if raw.startswith("@") else None
    return resolved, username


async def _answer_or_reply(update: Update, text: str, show_alert: bool = False):
    query = update.callback_query
    if query:
        await query.answer(text, show_alert=show_alert)
    elif update.message:
        await update.message.reply_text(text)


async def _require_super_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, main_bot_only: bool = False) -> bool:
    try:
        user = update.effective_user
        if not user or not _is_super_admin(user.id):
            await _answer_or_reply(update, "叮咚！仅超级管理员可使用该功能。", show_alert=True)
            return False

        if main_bot_only and get_current_bot_id(context) != SUPER_ADMIN_SCOPE_BOT_ID:
            await _answer_or_reply(update, "该功能仅可在主 Bot 私聊中使用。", show_alert=True)
            return False
        return True
    except Exception:
        traceback.print_exc()
        return False


def _get_forward_back_callback(source_bot_id: str, source_bot_username: str, user_id: int) -> str:
    return f"sa:forward:back:{source_bot_id}:{source_bot_username}:{user_id}"


def _build_forward_card_text(source_bot_username: str, user_id: int, username: str | None, message_text: str) -> str:
    safe_username = f"@{html.escape(username)}" if username else "@无"
    return (
        f"来源：@{html.escape(source_bot_username)}\n"
        f"用户ID：<code>{user_id}</code>\n"
        f"用户名：{safe_username}\n"
        f"消息内容：{html.escape(message_text or '非文本消息')}"
    )


async def _get_main_bot_sender(context: ContextTypes.DEFAULT_TYPE):
    current_bot_id = get_current_bot_id(context)
    if _is_super_admin_scope_runtime(current_bot_id):
        return context.bot
    try:
        async with get_db_session() as db:
            result = await db.execute(select(BotCreation).where(BotCreation.instance_id == SUPER_ADMIN_SCOPE_BOT_ID))
            main_bot = result.scalar_one_or_none()
            if main_bot and main_bot.bot_token:
                try:
                    return Bot(token=token_encryptor.decrypt_from_base64(main_bot.bot_token))
                except Exception:
                    return Bot(token=main_bot.bot_token)
    except Exception:
        traceback.print_exc()
        logger.error("failed to load main bot token for forwarding", exc_info=True)
    return Bot(token=config.BOT_TOKEN)


def _forward_cache_key(user_id: int) -> str:
    return f"sa_v2_forward_text:{user_id}"


SA_LAST_PRIVATE_MESSAGE_ID_KEY = "sa_v2_last_private_message_id"




async def _edit_or_reply(update: Update, text: str, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)


async def _get_dnd_enabled() -> bool:
    async with get_db_session() as db:
        repo = SuperAdminSettingsRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        return await repo.is_do_not_disturb()


async def _set_dnd_enabled(enabled: bool):
    async with get_db_session() as db:
        repo = SuperAdminSettingsRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        await repo.set_do_not_disturb(enabled)
        await db.commit()


async def _is_forward_blocked(user_id: int) -> bool:
    async with get_db_session() as db:
        repo = GlobalForwardBlacklistRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        return await repo.is_blocked(user_id)


async def _set_forward_block(user_id: int, duration_key: str):
    label, duration_days, permanent = BLACKLIST_DURATION_MAP[duration_key]
    async with get_db_session() as db:
        repo = GlobalForwardBlacklistRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        await repo.block_user(
            user_id=user_id,
            blocked_by=SUPER_ADMIN_ID,
            duration_days=duration_days,
            permanent=permanent,
            reason=f"super_admin_{duration_key}",
        )
        await db.commit()
    return label


async def _unblock_forward_user(user_id: int) -> bool:
    async with get_db_session() as db:
        repo = GlobalForwardBlacklistRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        success = await repo.unblock_user(user_id)
        await db.commit()
        return success


async def _create_or_extend_full_subscription(user_id: int, username: str | None, duration_days: int):
    now = datetime.utcnow()
    async with get_db_session() as db:
        result = await db.execute(select(Subscription).where(Subscription.telegram_id == user_id))
        subscription = result.scalar_one_or_none()
        base_time = now
        if subscription and subscription.expire_date and subscription.expire_date > now:
            base_time = subscription.expire_date
        expire_time = base_time + timedelta(days=duration_days)

        if subscription:
            subscription.username = username
            subscription.plan_id = max(subscription.plan_id or 0, 1)
            subscription.plan_name = "全功能版"
            subscription.status = "active"
            subscription.start_date = subscription.start_date or now
            subscription.expire_date = expire_time
            subscription.updated_at = now
        else:
            subscription = Subscription(
                telegram_id=user_id,
                username=username,
                plan_id=1,
                plan_name="全功能版",
                status="active",
                start_date=now,
                expire_date=expire_time,
                auto_renew=False,
                bots_created=0,
                total_groups=0,
            )
            db.add(subscription)

        await db.flush()
        await db.commit()
        return expire_time


async def _create_pending_provision(user_id: int, username: str | None, duration_days: int, mode: str):
    expire_time = await _create_or_extend_full_subscription(user_id, username, duration_days)
    async with get_db_session() as db:
        repo = PendingProvisionRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        await repo.create_pending(
            user_id=user_id,
            username=username,
            provisioned_by=SUPER_ADMIN_ID,
            duration_days=duration_days,
            expire_time=expire_time,
            mode=mode,
        )
        await db.commit()
    return expire_time


async def _find_user_bot(user_id: int) -> BotCreation | None:
    now = datetime.utcnow()

    def _is_usable(bot: BotCreation) -> bool:
        lifecycle_status = (getattr(bot, "lifecycle_status", "") or "").upper()
        status = (getattr(bot, "status", "") or "").lower()
        expire_time = getattr(bot, "expire_time", None)
        token_status = (getattr(bot, "token_status", "") or "normal").lower()

        if lifecycle_status == "DELETED":
            return False
        if expire_time and expire_time <= now:
            return False
        if token_status == "invalid":
            return False
        return status in {"creating", "running", "stopped", "error"} or lifecycle_status in {"", "ACTIVE", "SUSPENDED", "ARCHIVED"}

    async with get_db_session() as db:
        result = await db.execute(
            select(BotCreation)
            .where(BotCreation.telegram_id == user_id)
            .order_by(desc(BotCreation.created_at))
        )
        bots = result.scalars().all()
        usable_bot = next((bot for bot in bots if _is_usable(bot)), None)
        return usable_bot or (bots[0] if bots else None)


async def _update_bot_expire_time(user_id: int, expire_time: datetime):
    async with get_db_session() as db:
        result = await db.execute(
            select(BotCreation)
            .where(BotCreation.telegram_id == user_id)
            .order_by(desc(BotCreation.created_at))
        )
        bot = result.scalars().first()
        if bot:
            bot.expire_time = expire_time
            bot.lifecycle_status = "ACTIVE"
            bot.status = "running"
            bot.token_status = bot.token_status or "normal"
            await db.commit()
        return bot


def _build_user_closed_notice(bot: BotCreation | None) -> str:
    bot_name = getattr(bot, "bot_name", None) or getattr(bot, "bot_username", None) or "专属记账机器人"
    return (
        "🔒【服务停用通知】\n"
        "停用机器人：" + html.escape(str(bot_name)) + "\n"
        "提示：当前机器人已关停，续费套餐即可自动恢复服务；\n"
        "可选方案：①联系主 Bot 客服 ②自主购买套餐\n\n"
        "🛒 立即选购套餐"
    )


def _build_user_closed_notice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 立即选购套餐", callback_data="billing:self_renew")],
    ])


async def _close_user_and_stop_bot(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    from ..services.saas_auto_service import saas_auto_service

    async with get_db_session() as db:
        sub_result = await db.execute(select(Subscription).where(Subscription.telegram_id == user_id))
        subscription = sub_result.scalar_one_or_none()
        expire_backup = subscription.expire_date if subscription else None
        if subscription:
            subscription.status = "expired"
            subscription.expire_date = datetime.utcnow()

        bot_result = await db.execute(
            select(BotCreation)
            .where(BotCreation.telegram_id == user_id)
            .order_by(desc(BotCreation.created_at))
        )
        bot = bot_result.scalars().first()
        username = subscription.username if subscription else None

        if bot:
            bot.expire_time = datetime.utcnow()
            bot.lifecycle_status = "SUSPENDED"
            bot.status = "stopped"
            bot.last_activity_at = datetime.utcnow()
            username = username or bot.bot_username

        try:
            main_bot = await _get_main_bot_sender(context)
            await main_bot.send_message(
                chat_id=user_id,
                text=_build_user_closed_notice(bot),
                parse_mode="HTML",
                reply_markup=_build_user_closed_notice_keyboard(),
            )
        except Exception:
            traceback.print_exc()
            logger.error("[SA_V2] failed to send close notice to user %s", user_id, exc_info=True)

        closed_repo = ClosedUserRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        await closed_repo.close_user(
            user_id=user_id,
            username=username,
            closed_by=SUPER_ADMIN_ID,
            original_expire_time=expire_backup,
            reason="super_admin_close",
        )
        await db.commit()

    if bot:
        try:
            await saas_auto_service.stop_bot_instance(bot.instance_id)
        except Exception:
            traceback.print_exc()
    return bot


async def _reopen_user_subscription(user_id: int, extra_days: int = 30):
    now = datetime.utcnow()
    async with get_db_session() as db:
        closed_repo = ClosedUserRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        closed_user = await closed_repo.get_closed_user(user_id)

        sub_result = await db.execute(select(Subscription).where(Subscription.telegram_id == user_id))
        subscription = sub_result.scalar_one_or_none()
        if subscription:
            subscription.status = "active"
            target_expire = closed_user.original_expire_time if closed_user and closed_user.original_expire_time else now + timedelta(days=extra_days)
            subscription.expire_date = target_expire if target_expire > now else now + timedelta(days=extra_days)
        if closed_user:
            await closed_repo.reopen_user(user_id)

        bot_result = await db.execute(
            select(BotCreation)
            .where(BotCreation.telegram_id == user_id)
            .order_by(desc(BotCreation.created_at))
        )
        bot = bot_result.scalars().first()
        if bot:
            bot.expire_time = subscription.expire_date if subscription else now + timedelta(days=extra_days)
            bot.lifecycle_status = "ACTIVE"
            bot.status = "running"
        await db.commit()
        return bot


async def _show_blacklist_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1, notice: str | None = None):
    page_size = 5
    async with get_db_session() as db:
        repo = GlobalForwardBlacklistRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        total = await repo.count_blocked()
        page = max(1, page)
        items = await repo.get_blocked_list(limit=page_size, offset=(page - 1) * page_size)
        usernames: dict[int, str] = {}
        if items:
            user_ids = [item.user_id for item in items]
            sub_result = await db.execute(select(Subscription).where(Subscription.telegram_id.in_(user_ids)))
            for sub in sub_result.scalars().all():
                usernames[sub.telegram_id] = sub.username or ""

    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)

    text = "📋 <b>拉黑管理</b>\n\n"
    if not items:
        text += "ℹ️ 当前暂无拉黑用户"
    else:
        for item in items:
            username = usernames.get(item.user_id) or "无"
            duration = "永久" if item.permanent else (
                "已到期" if item.blocked_until and item.blocked_until <= datetime.utcnow() else
                ("1天/1周/1月" if not item.permanent else "永久")
            )
            if item.permanent:
                unblock_time = "永久"
            elif item.blocked_until:
                unblock_time = item.blocked_until.strftime("%Y-%m-%d %H:%M")
            else:
                unblock_time = "永久"
            text += (
                f"用户ID：<code>{item.user_id}</code>\n"
                f"用户名：@{html.escape(username)}\n"
                f"拉黑时长：{duration}\n"
                f"解除时间：{unblock_time}\n\n"
            )
    if notice:
        text += f"\n{notice}"

    keyboard = []
    for item in items:
        keyboard.append([InlineKeyboardButton(f"✅ 解除拉黑 {item.user_id}", callback_data=f"sa:blacklist:unblock:{item.user_id}:{page}")])

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"sa:blacklist:list:{page - 1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"sa:blacklist:list:{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data="sa:message_center")])
    await _edit_or_reply(update, text, InlineKeyboardMarkup(keyboard))


async def _show_closed_users_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1, notice: str | None = None):
    page_size = 5
    async with get_db_session() as db:
        repo = ClosedUserRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        items = await repo.get_closed_list(limit=page_size, offset=(page - 1) * page_size)

    text = "📋 <b>已关闭用户</b>\n\n"
    if not items:
        text += "ℹ️ 当前暂无已关闭用户"
    else:
        for item in items:
            username = f"@{html.escape(item.username)}" if item.username else "无"
            close_time = item.closed_at.strftime("%Y-%m-%d %H:%M") if item.closed_at else "未知"
            text += (
                f"用户ID：<code>{item.user_id}</code>\n"
                f"用户名：{username}\n"
                f"关闭时间：{close_time}\n\n"
            )
    if notice:
        text += f"\n{notice}"

    keyboard = []
    for item in items:
        keyboard.append([InlineKeyboardButton(f"🔓 再次开通 {item.user_id}", callback_data=f"sa:closed:reopen:{item.user_id}:{page}")])
    if page > 1:
        keyboard.append([InlineKeyboardButton("⬅️ 上一页", callback_data=f"sa:closed:list:{page - 1}")])
    if len(items) == page_size:
        keyboard.append([InlineKeyboardButton("➡️ 下一页", callback_data=f"sa:closed:list:{page + 1}")])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data="sa:panel")])
    await _edit_or_reply(update, text, InlineKeyboardMarkup(keyboard))




async def _show_provision_day_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    text = (
        "🔹 <b>开通用户</b>\n\n"
        f"目标用户：<code>{user_id}</code>\n"
        "请选择开通天数，或直接发送 1-100 的数字："
    )
    keyboard = [
        [
            InlineKeyboardButton("1天", callback_data="sa:provision:days:1"),
            InlineKeyboardButton("3天", callback_data="sa:provision:days:3"),
            InlineKeyboardButton("7天", callback_data="sa:provision:days:7"),
            InlineKeyboardButton("30天", callback_data="sa:provision:days:30"),
        ],
        [InlineKeyboardButton("100天", callback_data="sa:provision:days:100")],
        [InlineKeyboardButton("⬅️ 返回", callback_data="sa:panel")],
    ]
    await _edit_or_reply(update, text, InlineKeyboardMarkup(keyboard))


async def _show_provision_mode_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, days: int):
    text = (
        "🔹 <b>开通用户</b>\n\n"
        f"目标用户：<code>{user_id}</code>\n"
        f"开通时长：{days} 天\n\n"
        "请选择 Token 模式："
    )
    keyboard = [
        [
            InlineKeyboardButton("🖥 超管代发Token", callback_data="sa:provision:mode:admin_send"),
            InlineKeyboardButton("👤 用户自发Token", callback_data="sa:provision:mode:user_send"),
        ],
        [InlineKeyboardButton("⬅️ 返回", callback_data="sa:panel")],
    ]
    await _edit_or_reply(update, text, InlineKeyboardMarkup(keyboard))


async def _provision_or_create_bot(
    *,
    target_user_id: int,
    username: str | None,
    days: int,
    token: str,
) -> tuple[bool, str, BotCreation | None, datetime | None]:
    logger.info("[SA_V2] provisioning bot token=%s", _mask_token(token))
    from telegram import Bot

    bot = Bot(token=token)
    me = await bot.get_me()
    expire_time = await _create_or_extend_full_subscription(target_user_id, username, days)
    existing_bot = await _find_user_bot(target_user_id)

    if existing_bot:
        bot_creation = await _update_bot_expire_time(target_user_id, expire_time)
        if bot_creation:
            try:
                from ..services.bot_instance_manager import bot_instance_manager
                await bot_instance_manager.start_bot_instance(bot_creation)
            except Exception:
                traceback.print_exc()
        return True, "extended", bot_creation, expire_time

    success, create_message, bot_creation = await manual_provision_service.manual_create_bot(
        telegram_id=target_user_id,
        username=username or f"user_{target_user_id}",
        bot_token=token,
        bot_username=me.username or "",
        bot_name=me.first_name or me.username or "Bot",
        operator_id=SUPER_ADMIN_ID,
    )
    if not success:
        return False, create_message, None, None

    bot_creation = await _update_bot_expire_time(target_user_id, expire_time)
    if bot_creation:
        try:
            from ..services.bot_instance_manager import bot_instance_manager
            await bot_instance_manager.start_bot_instance(bot_creation)
        except Exception:
            traceback.print_exc()
    return True, "created", bot_creation, expire_time


async def handle_super_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    try:
        data = query.data or ""
        if not await _require_super_admin(update, context, main_bot_only=True):
            return

        if data.startswith("sa:created:noop:"):
            await query.answer("请先进入专属机器人后，再使用这些管理按钮。", show_alert=True)
            return

        if data == "sa:panel":
            await show_super_admin_panel(update, context)
            return
        if data == "sa:message_center":
            await show_message_center(update, context)
            return
        if data == "sa:dnd:on":
            await _set_dnd_enabled(True)
            await query.answer("🔕已开启免打扰", show_alert=True)
            await show_message_center(update, context)
            return
        if data == "sa:dnd:off":
            await _set_dnd_enabled(False)
            await query.answer("🔔已关闭免打扰", show_alert=True)
            await show_message_center(update, context)
            return
        if data.startswith("sa:blacklist:list:"):
            await _show_blacklist_page(update, context, int(data.split(":")[-1]))
            return
        if data.startswith("sa:blacklist:unblock:"):
            parts = data.split(":")
            target_user_id = int(parts[3])
            page = int(parts[4])
            success = await _unblock_forward_user(target_user_id)
            notice = f"✅ 用户{target_user_id}已解除拉黑" if success else f"⚠️ 用户{target_user_id}未在拉黑列表中"
            await _show_blacklist_page(update, context, page, notice)
            return
        if data.startswith("sa:forward:"):
            await _handle_forward_action(update, context, data.split(":"))
            return
        if data == "sa:provision:start":
            _clear_super_admin_flow_state(context)
            context.user_data[SA_STATE_KEY] = STATE_PROVISION_WAIT_USER
            await query.edit_message_text(
                "🔹 <b>开通用户</b>\n\n请输入需要开通的用户ID或 @用户名。",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data="sa:panel")]]),
            )
            return
        if data.startswith("sa:provision:days:"):
            days = int(data.split(":")[-1])
            target_user_id = int(context.user_data.get(SA_TARGET_USER_ID_KEY) or 0)
            if not target_user_id:
                await query.answer("开通状态已过期，请重新开始。", show_alert=True)
                await show_super_admin_panel(update, context)
                return
            context.user_data[SA_TARGET_DAYS_KEY] = days
            await _show_provision_mode_picker(update, context, target_user_id, days)
            return
        if data.startswith("sa:provision:mode:"):
            mode = data.split(":")[-1]
            target_user_id = int(context.user_data.get(SA_TARGET_USER_ID_KEY) or 0)
            days = int(context.user_data.get(SA_TARGET_DAYS_KEY) or 0)
            username = context.user_data.get(SA_TARGET_USERNAME_KEY)
            if not target_user_id or not days:
                await query.answer("开通状态已过期，请重新开始。", show_alert=True)
                await show_super_admin_panel(update, context)
                return

            if mode == "user_send":
                expire_time = await _create_pending_provision(target_user_id, username, days, "user_send")
                try:
                    await context.bot.send_message(chat_id=target_user_id, text=USER_SEND_TOKEN_GUIDE)
                except Exception:
                    traceback.print_exc()
                _clear_super_admin_flow_state(context)
                await query.edit_message_text(
                    "已为该用户开通时长，系统将自动引导用户发送Token。\n\n"
                    f"用户ID：<code>{target_user_id}</code>\n"
                    f"到期时间：{expire_time.strftime('%Y-%m-%d %H:%M')}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data="sa:panel")]]),
                )
                return

            context.user_data[SA_STATE_KEY] = STATE_PROVISION_WAIT_TOKEN
            await query.edit_message_text(
                "请发送该用户提供的机器人Token",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data="sa:panel")]]),
            )
            return
        if data == "sa:close:start":
            _clear_super_admin_flow_state(context)
            context.user_data[SA_STATE_KEY] = STATE_CLOSE_WAIT_USER
            await query.edit_message_text(
                "🔒 <b>关闭用户</b>\n\n请输入需要关闭的用户ID或 @用户名。",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data="sa:panel")]]),
            )
            return
        if data.startswith("sa:closed:list:"):
            await _show_closed_users_page(update, context, int(data.split(":")[-1]))
            return
        if data.startswith("sa:closed:reopen:"):
            parts = data.split(":")
            target_user_id = int(parts[3])
            page = int(parts[4])
            await _reopen_user_subscription(target_user_id)
            await _show_closed_users_page(update, context, page, f"✅ 用户{target_user_id}已重新开通")
            return
    except Exception:
        traceback.print_exc()
        logger.error("handle_super_admin_callback failed", exc_info=True)
        try:
            await query.answer("处理超管操作失败", show_alert=True)
        except Exception:
            traceback.print_exc()


async def handle_super_admin_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or message.chat.type != "private":
        return

    try:
        user = update.effective_user
        user_id = user.id if user else 0
        text = (message.text or "").strip()
        current_bot_id = get_current_bot_id(context)

        if _is_super_admin(user_id):
            state = context.user_data.get(SA_STATE_KEY)

            if state == STATE_PROVISION_WAIT_USER:
                target_user_id, parsed_username = await _resolve_target_user(text)
                if not target_user_id:
                    await message.reply_text("请输入正确的用户ID或 @用户名。")
                    return
                context.user_data[SA_TARGET_USER_ID_KEY] = target_user_id
                if parsed_username:
                    context.user_data[SA_TARGET_USERNAME_KEY] = parsed_username
                context.user_data[SA_STATE_KEY] = STATE_PROVISION_WAIT_DAYS
                await _show_provision_day_picker(update, context, target_user_id)
                return

            if state == STATE_PROVISION_WAIT_DAYS:
                if not text.isdigit() or not (1 <= int(text) <= 100):
                    await message.reply_text("请输入 1-100 之间的天数。")
                    return
                days = int(text)
                context.user_data[SA_TARGET_DAYS_KEY] = days
                await _show_provision_mode_picker(update, context, int(context.user_data[SA_TARGET_USER_ID_KEY]), days)
                return

            if state == STATE_PROVISION_WAIT_TOKEN:
                if not TOKEN_PATTERN.match(text):
                    await message.reply_text("Token 格式不正确，请重新发送。")
                    return
                target_user_id = int(context.user_data.get(SA_TARGET_USER_ID_KEY) or 0)
                days = int(context.user_data.get(SA_TARGET_DAYS_KEY) or 0)
                username = context.user_data.get(SA_TARGET_USERNAME_KEY)
                if not target_user_id or not days:
                    _clear_super_admin_flow_state(context)
                    await message.reply_text("开通状态已失效，请重新开始。")
                    return

                success, create_message, bot_creation, expire_time = await _provision_or_create_bot(
                    target_user_id=target_user_id,
                    username=username,
                    days=days,
                    token=text,
                )
                if not success or not bot_creation or not expire_time:
                    await message.reply_text(f"❌ 创建失败\n\n{create_message}")
                    return

                _clear_super_admin_flow_state(context)
                await message.reply_text(
                    "✅ 创建成功\n"
                    f"用户ID：{target_user_id}\n"
                    "套餐类型：全功能版\n"
                    f"到期时间：{expire_time.strftime('%Y-%m-%d %H:%M')}\n"
                    "该机器人已归属对应用户，权限已刷新。"
                )
                try:
                    await _send_created_bot_success_card(context.bot, target_user_id, bot_creation, expire_time)
                except Exception:
                    traceback.print_exc()
                return

            if state == STATE_CLOSE_WAIT_USER:
                target_user_id, _ = await _resolve_target_user(text)
                if not target_user_id:
                    await message.reply_text("请输入正确的用户ID或 @用户名。")
                    return
                await _close_user_and_stop_bot(target_user_id, context)
                _clear_super_admin_flow_state(context)
                await message.reply_text(f"🔒用户{target_user_id}已强制到期，已移入已关闭用户列表。")
                return

            if state == STATE_UNBLOCK_WAIT_USER:
                target_user_id, _ = await _resolve_target_user(text)
                if not target_user_id:
                    await message.reply_text("请输入正确的用户ID或 @用户名。")
                    return
                success = await _unblock_forward_user(target_user_id)
                _clear_super_admin_flow_state(context)
                await message.reply_text(
                    f"✅ 用户{target_user_id}已解除拉黑" if success else f"⚠️ 用户{target_user_id}未在拉黑列表中"
                )
                return

            async with get_db_session() as db:
                msg_repo = SuperAdminMessageStateRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
                reply_state = await msg_repo.get_state(SUPER_ADMIN_ID)
                if reply_state:
                    target_user_id = reply_state.target_user_id
                    try:
                        if message.text:
                            await context.bot.send_message(chat_id=target_user_id, text=message.text)
                        else:
                            await context.bot.copy_message(
                                chat_id=target_user_id,
                                from_chat_id=message.chat_id,
                                message_id=message.message_id,
                            )
                        await msg_repo.clear_state(SUPER_ADMIN_ID)
                        await db.commit()
                        _clear_super_admin_flow_state(context)
                        await message.reply_text(f"✅ 消息已发送给用户 {target_user_id}")
                    except Exception:
                        traceback.print_exc()
                        await message.reply_text("❌ 消息发送失败")
                    return

            if text:
                open_match = re.match(r"^开通用户[\s+]+(@?[A-Za-z0-9_]+)[\s+]+(\d+)$", text)
                if open_match:
                    target_identifier = open_match.group(1)
                    days = int(open_match.group(2))
                    if not 1 <= days <= 100:
                        await message.reply_text("请输入 1-100 天。")
                        return
                    target_user_id, parsed_username = await _resolve_target_user(target_identifier)
                    if not target_user_id:
                        await message.reply_text("请输入正确的用户ID或 @用户名。")
                        return
                    context.user_data[SA_TARGET_USER_ID_KEY] = target_user_id
                    context.user_data[SA_TARGET_DAYS_KEY] = days
                    if parsed_username:
                        context.user_data[SA_TARGET_USERNAME_KEY] = parsed_username
                    await _show_provision_mode_picker(update, context, target_user_id, days)
                    return

                unblock_match = re.match(r"^解除拉黑[\s+]+(\d+)$", text)
                if unblock_match:
                    target_user_id = int(unblock_match.group(1))
                    success = await _unblock_forward_user(target_user_id)
                    await message.reply_text(
                        f"✅ 用户{target_user_id}已解除拉黑" if success else f"⚠️ 用户{target_user_id}未在拉黑列表中"
                    )
                    return

            return

        async with get_db_session() as db:
            repo = PendingProvisionRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
            pending = await repo.get_pending(user_id)
            if pending and pending.mode == "user_send" and not pending.completed:
                logger.info(
                    "[SA_V2] pending user_send token received user_id=%s current_bot_id=%s token_like=%s",
                    user_id,
                    current_bot_id,
                    bool(message.text and TOKEN_PATTERN.match(message.text.strip())),
                )
                if not message.text or not TOKEN_PATTERN.match(message.text.strip()):
                    await message.reply_text("您的Token已失效/过期，请重新发送新Token激活")
                    return

                success, create_message, bot_creation, expire_time = await _provision_or_create_bot(
                    target_user_id=user_id,
                    username=pending.username or (user.username if user else None),
                    days=pending.duration_days,
                    token=message.text.strip(),
                )
                if not success or not bot_creation or not expire_time:
                    logger.error(
                        "[SA_V2] pending user_send create failed user_id=%s current_bot_id=%s message=%s",
                        user_id,
                        current_bot_id,
                        create_message,
                    )
                    await message.reply_text(f"❌ 创建失败\n\n{create_message}")
                    return

                await repo.receive_token(user_id, token_encryptor.encrypt_to_base64(message.text.strip()))
                await repo.complete_provision(user_id)
                await db.commit()
                await _send_created_bot_success_card(context.bot, user_id, bot_creation, expire_time)
                try:
                    await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=f"✅ 用户{user_id}已自主完成Token创建")
                except Exception:
                    traceback.print_exc()
                return
    except Exception:
        traceback.print_exc()
        logger.error("handle_super_admin_private_message failed", exc_info=True)


async def _require_super_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, main_bot_only: bool = False) -> bool:
    try:
        user = update.effective_user
        if not user or not _is_super_admin(user.id):
            await _answer_or_reply(update, "叮咚！仅超级管理员可使用该功能。", show_alert=True)
            return False

        if update.effective_chat and update.effective_chat.type != "private":
            await _answer_or_reply(update, "该功能仅可在 Bot 私聊中使用。", show_alert=True)
            return False

        current_bot_id = ""
        try:
            current_bot_id = get_current_bot_id(context)
        except Exception:
            traceback.print_exc()

        is_test_runtime = current_bot_id == "test_bot" or os.environ.get("INSTANCE_ID") == "test_bot"
        is_main_runtime = os.environ.get("IS_MAIN_BOT", "true").lower() == "true"

        if main_bot_only and current_bot_id != SUPER_ADMIN_SCOPE_BOT_ID and not is_test_runtime and not is_main_runtime:
            await _answer_or_reply(update, "该功能仅可在主BOT私聊中使用。", show_alert=True)
            return False

        return True
    except Exception:
        traceback.print_exc()
        return False

async def _legacy_handle_forward_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]):
    return None


_legacy_handle_super_admin_callback = handle_super_admin_callback
_legacy_handle_super_admin_private_message = handle_super_admin_private_message


def _build_forward_card_text_from_cache(
    context: ContextTypes.DEFAULT_TYPE,
    source_bot_username: str,
    user_id: int,
    username: str | None,
) -> str:
    cached_text = context.application.bot_data.get(_forward_cache_key(user_id)) or "非文本消息"
    return _build_forward_card_text(
        source_bot_username=source_bot_username,
        user_id=user_id,
        username=username,
        message_text=cached_text,
    )


async def _restore_forward_message_card(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    source_bot_id: str,
    source_bot_username: str,
    user_id: int,
):
    async with get_db_session() as db:
        repo = SuperAdminMessageStateRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
        await repo.clear_state(SUPER_ADMIN_ID)
        await db.commit()
    _clear_super_admin_flow_state(context)
    chat = await context.bot.get_chat(user_id)
    text = _build_forward_card_text_from_cache(context, source_bot_username, user_id, chat.username)
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=_build_forward_card_markup(source_bot_id, source_bot_username, user_id),
    )


async def show_super_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await _require_super_admin(update, context, main_bot_only=True):
            return
        _clear_super_admin_flow_state(context)
        text = "🔐 <b>超管后台</b>\n\n请选择操作："
        keyboard = [
            [
                InlineKeyboardButton("🔹 开通用户", callback_data="sa:provision:start"),
                InlineKeyboardButton("🔒 关闭用户", callback_data="sa:close:start"),
            ],
            [InlineKeyboardButton("📋 已关闭用户", callback_data="sa:closed:list:1")],
            [InlineKeyboardButton("⛔️ 关闭", callback_data="sa:close_menu")],
        ]
        await _edit_or_reply(update, text, InlineKeyboardMarkup(keyboard))
    except Exception:
        traceback.print_exc()
        logger.error("show_super_admin_panel final override failed", exc_info=True)


async def show_message_center(update: Update, context: ContextTypes.DEFAULT_TYPE, notice: str | None = None):
    try:
        if not await _require_super_admin(update, context, main_bot_only=True):
            return
        _clear_super_admin_flow_state(context)
        is_dnd = await _get_dnd_enabled()
        status_text = "🔕 开启免打扰（暂停接收）" if is_dnd else "🔔 关闭免打扰（正常接收）"
        text = "💬 <b>消息中心</b>\n\n请选择消息接收模式：\n" + status_text
        if notice:
            text += f"\n\n{notice}"
        keyboard = [
            [
                InlineKeyboardButton("🔔 关闭免打扰", callback_data="sa:dnd:off"),
                InlineKeyboardButton("🔕 开启免打扰", callback_data="sa:dnd:on"),
            ],
            [InlineKeyboardButton("📋 拉黑管理", callback_data="sa:blacklist:list:1")],
            [InlineKeyboardButton("⛔️ 关闭", callback_data="sa:close_menu")],
        ]
        await _edit_or_reply(update, text, InlineKeyboardMarkup(keyboard))
    except Exception:
        traceback.print_exc()
        logger.error("show_message_center final override failed", exc_info=True)


async def _handle_forward_action(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list[str]):
    query = update.callback_query
    if not query or len(parts) < 6:
        return await _legacy_handle_forward_action(update, context, parts)

    action = parts[2]
    source_bot_id = parts[3]
    source_bot_username = parts[4]
    user_id = int(parts[5])

    try:
        if action == "back":
            await _restore_forward_message_card(query, context, source_bot_id, source_bot_username, user_id)
            return

        if action == "info":
            chat = await context.bot.get_chat(user_id)
            nickname = html.escape(chat.full_name or "无")
            username = f"@{html.escape(chat.username)}" if chat.username else "@无"
            text = (
                "👤 <b>用户信息</b>\n\n"
                f"用户ID：<code>{user_id}</code>\n"
                f"用户昵称：{nickname}\n"
                f"用户名：{username}"
            )
            keyboard = [[InlineKeyboardButton("⏪ 返回", callback_data=_get_forward_back_callback(source_bot_id, source_bot_username, user_id))]]
            _clear_super_admin_flow_state(context)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if action == "reply":
            async with get_db_session() as db:
                repo = SuperAdminMessageStateRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
                await repo.set_target(SUPER_ADMIN_ID, user_id)
                await db.commit()
            context.user_data[SA_REPLY_SOURCE_BOT_ID_KEY] = source_bot_id
            context.user_data[SA_REPLY_SOURCE_BOT_USERNAME_KEY] = source_bot_username
            text = "请输入需要发送的内容（支持文本/图片/媒体），发送后将自动转达给该用户。"
            keyboard = [[InlineKeyboardButton("⏪ 返回", callback_data=_get_forward_back_callback(source_bot_id, source_bot_username, user_id))]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if action == "block" and len(parts) >= 7:
            duration_key = parts[6]
            label = await _set_forward_block(user_id, duration_key)
            await query.answer(f"已拉黑 {label}", show_alert=True)
            return
    except Exception:
        traceback.print_exc()
        await query.answer("处理失败，请稍后重试", show_alert=True)
        return

    await _legacy_handle_forward_action(update, context, parts)


async def handle_super_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    try:
        if data == "sa:close_menu":
            if not await _require_super_admin(update, context, main_bot_only=True):
                return
            _clear_super_admin_flow_state(context)
            try:
                async with get_db_session() as db:
                    repo = SuperAdminMessageStateRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
                    await repo.clear_state(SUPER_ADMIN_ID)
                    await db.commit()
            except Exception:
                traceback.print_exc()
            await query.answer()
            try:
                await query.delete_message()
            except Exception:
                traceback.print_exc()
            return

        if data == "sa:panel":
            if not await _require_super_admin(update, context, main_bot_only=True):
                return
            await query.answer()
            await show_super_admin_panel(update, context)
            return

        if data == "sa:message_center":
            if not await _require_super_admin(update, context, main_bot_only=True):
                return
            await query.answer()
            await show_message_center(update, context)
            return

        if data.startswith("sa:forward:"):
            if not await _require_super_admin(update, context, main_bot_only=True):
                return
            await _handle_forward_action(update, context, data.split(":"))
            return
    except Exception:
        traceback.print_exc()
        logger.error("handle_super_admin_callback final override failed", exc_info=True)
        try:
            await query.answer("处理失败，请稍后重试", show_alert=True)
        except Exception:
            traceback.print_exc()
        return

    await _legacy_handle_super_admin_callback(update, context)


async def handle_super_admin_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or message.chat.type != "private":
        return

    try:
        last_message_id = context.user_data.get(SA_LAST_PRIVATE_MESSAGE_ID_KEY)
        if last_message_id == message.message_id:
            return
        context.user_data[SA_LAST_PRIVATE_MESSAGE_ID_KEY] = message.message_id

        user = update.effective_user
        current_bot_id = ""
        try:
            current_bot_id = get_current_bot_id(context)
        except Exception:
            traceback.print_exc()

        if user and not _is_super_admin(user.id):
            async with get_db_session() as db:
                repo = PendingProvisionRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
                pending = await repo.get_pending(user.id)
                if pending and pending.mode == "user_send" and not pending.completed:
                    existing_bot = await _find_user_bot(user.id)
                    if existing_bot and (existing_bot.token_status or "normal").lower() != "invalid":
                        await repo.complete_provision(user.id)
                        await db.commit()
                        logger.info(
                            "[SA_V2] final override cleared stale pending provision for user_id=%s instance_id=%s current_bot_id=%s",
                            user.id,
                            existing_bot.instance_id,
                            current_bot_id,
                        )
                        return

        if user and _is_super_admin(user.id):
            async with get_db_session() as db:
                msg_repo = SuperAdminMessageStateRepo(db, SUPER_ADMIN_SCOPE_BOT_ID)
                reply_state = await msg_repo.get_state(SUPER_ADMIN_ID)
                if reply_state:
                    target_user_id = reply_state.target_user_id
                    source_bot_id = context.user_data.get(SA_REPLY_SOURCE_BOT_ID_KEY) or SUPER_ADMIN_SCOPE_BOT_ID
                    source_bot_username = context.user_data.get(SA_REPLY_SOURCE_BOT_USERNAME_KEY) or "unknown_bot"
                    try:
                        if message.text:
                            await context.bot.send_message(chat_id=target_user_id, text=message.text)
                        else:
                            await context.bot.copy_message(
                                chat_id=target_user_id,
                                from_chat_id=message.chat_id,
                                message_id=message.message_id,
                            )
                        await msg_repo.clear_state(SUPER_ADMIN_ID)
                        await db.commit()
                        _clear_super_admin_flow_state(context)
                        keyboard = [[InlineKeyboardButton("⏪ 返回", callback_data=_get_forward_back_callback(source_bot_id, source_bot_username, target_user_id))]]
                        await message.reply_text(
                            f"✅ 消息已发送给用户 {target_user_id}",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                        )
                    except Exception:
                        traceback.print_exc()
                        await message.reply_text("❌ 消息发送失败")
                    return
    except Exception:
        traceback.print_exc()
        logger.error("handle_super_admin_private_message final reply override failed", exc_info=True)

    await _legacy_handle_super_admin_private_message(update, context)


async def handle_global_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or message.chat.type != "private":
        return

    try:
        user = update.effective_user
        if not user or _is_super_admin(user.id):
            return

        if message.text and TOKEN_PATTERN.match(message.text.strip()):
            logger.info("[SA_V2] skipped forwarding token-like private message for user_id=%s", user.id)
            return
        if await _get_dnd_enabled():
            return
        if await _is_forward_blocked(user.id):
            return

        source_bot_id = get_current_bot_id(context) or SUPER_ADMIN_SCOPE_BOT_ID
        source_bot_username = context.bot.username or "unknown_bot"
        text_content = message.text or message.caption or "非文本消息"
        context.application.bot_data[_forward_cache_key(user.id)] = text_content

        header_text = _build_forward_card_text(
            source_bot_username=source_bot_username,
            user_id=user.id,
            username=user.username,
            message_text=(message.text or "非文本消息"),
        )
        main_bot = await _get_main_bot_sender(context)
        await main_bot.send_message(
            chat_id=SUPER_ADMIN_ID,
            text=header_text,
            parse_mode="HTML",
            reply_markup=_build_forward_card_markup(source_bot_id, source_bot_username, user.id),
        )
        if not message.text:
            await main_bot.copy_message(
                chat_id=SUPER_ADMIN_ID,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
            )
    except Exception:
        traceback.print_exc()
        logger.error("handle_global_forward final override failed", exc_info=True)


def _build_forward_card_markup(source_bot_id: str, source_bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("拉黑1天", callback_data=f"sa:forward:block:{source_bot_id}:{source_bot_username}:{user_id}:1d"),
            InlineKeyboardButton("拉黑1周", callback_data=f"sa:forward:block:{source_bot_id}:{source_bot_username}:{user_id}:1w"),
            InlineKeyboardButton("拉黑1月", callback_data=f"sa:forward:block:{source_bot_id}:{source_bot_username}:{user_id}:1m"),
            InlineKeyboardButton("永久拉黑", callback_data=f"sa:forward:block:{source_bot_id}:{source_bot_username}:{user_id}:perm"),
        ],
        [
            InlineKeyboardButton("👤查看信息", callback_data=f"sa:forward:info:{source_bot_id}:{source_bot_username}:{user_id}"),
            InlineKeyboardButton("📋拉黑管理", callback_data="sa:blacklist:list:1"),
            InlineKeyboardButton("💬向TA发消息", callback_data=f"sa:forward:reply:{source_bot_id}:{source_bot_username}:{user_id}"),
        ],
    ])

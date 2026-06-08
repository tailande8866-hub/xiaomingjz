"""Guard helpers for the feature settings inline menu."""
import time
import uuid
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..models import Admin, BotCreation, get_db_session
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import UserRole, get_user_role
from ..services.account_status_service import account_status_service
from sqlalchemy import and_, select

SETTINGS_SESSION_PREFIX = "s"
SETTINGS_SESSION_TTL = 600
LOCKED_FEATURE_MESSAGE = (
    "叮咚！功能被锁住啦🔒\n"
    "这是付费开通机器人哦\n"
    "开通权限就能解锁全部功能，点击下方创建续费打造你自己的机器人，告别限制～\n"
    "技术大大 @xiaomingjz"
)
EXPIRED_MESSAGE = "按钮已过期 请点击下方功能设置重新获取"

RESTRICTED_FOR_ADMINS = (
    "topic:",
    "auth:",
    "authgroup:",
    "admin:",
    "timed:",
    "timedmsg:",
    "ad:",
    "keyword:",
    "botjoin:",
)

SETTINGS_CALLBACK_PREFIXES = (
    "topic:",
    "mygroups:",
    "broadcast_users:",
    "v1:group:manage",
    "show_broadcast",
    "botjoin:",
    "daycut:",
    "display:",
    "showname:",
    "welcome:",
    "keyword:",
    "admin:",
    "auth:",
    "authgroup:",
    "rename:",
    "timed:",
    "timedmsg:",
    "ad:",
    "settings:",
    "menu:",
    "menu_back",
)

EDIT_STATE_KEYS = (
    "waiting_bot_join_message",
    "waiting_topic_group_id",
    "waiting_timed_message",
    "waiting_ad_slot",
    "mygroups_waiting_send",
    "waiting_timed_global_interval",
    "waiting_timed_global_content",
    "waiting_broadcast_msg",
    "broadcast_users_waiting_input",
    "waiting_admin_add",
    "pending_admin",
    "waiting_for_group_tag_name",
    "waiting_for_rename_group_tag_name",
    "waiting_for_group_tag",
    "waiting_for_broadcast_group",
    "waiting_for_group_broadcast_message",
    "waiting_for_broadcast_content",
    "ad_state",
    "editing_button_id",
    "temp_button_text",
    "admin_add_user_id",
    "admin_add_username",
    "edit_state",
    "edit_state_data",
    "edit_state_timestamp",
    "waiting_for",
    "settings_fsm_state",
    "waiting_header_text",
    "waiting_header_link",
    "waiting_footer_text",
    "waiting_footer_link",
    "waiting_button_text",
    "waiting_button_url",
    "waiting_edit_button_text",
    "waiting_edit_button_url",
    "pending_button_text",
)


def clear_edit_states(context):
    for key in EDIT_STATE_KEYS:
        context.user_data.pop(key, None)
    for key in list(context.user_data.keys()):
        if key.startswith(("waiting_timed_group_interval:", "waiting_timed_group_content:")):
            context.user_data.pop(key, None)


def is_settings_callback(callback_data: str) -> bool:
    return bool(callback_data) and callback_data.startswith(SETTINGS_CALLBACK_PREFIXES)


def create_settings_session(context) -> str:
    session_id = uuid.uuid4().hex[:10]
    sessions = context.user_data.setdefault("settings_menu_sessions", {})
    sessions[session_id] = time.time()
    return session_id


def wrap_callback_data(callback_data: Optional[str], session_id: str) -> Optional[str]:
    if not callback_data or callback_data.startswith(f"{SETTINGS_SESSION_PREFIX}:"):
        return callback_data
    return f"{SETTINGS_SESSION_PREFIX}:{session_id}:{callback_data}"


def wrap_settings_markup(markup: InlineKeyboardMarkup, session_id: str) -> InlineKeyboardMarkup:
    keyboard = []
    for row in markup.inline_keyboard:
        new_row = []
        for button in row:
            if button.url:
                new_row.append(InlineKeyboardButton(text=button.text, url=button.url))
            else:
                new_row.append(
                    InlineKeyboardButton(
                        text=button.text,
                        callback_data=wrap_callback_data(button.callback_data, session_id),
                    )
                )
        keyboard.append(new_row)
    return InlineKeyboardMarkup(keyboard)


def unwrap_settings_callback(context, callback_data: str):
    if not callback_data or not callback_data.startswith(f"{SETTINGS_SESSION_PREFIX}:"):
        return callback_data, None, True
    parts = callback_data.split(":", 2)
    if len(parts) < 3:
        return callback_data, None, False
    session_id, real_data = parts[1], parts[2]
    created_at = context.user_data.get("settings_menu_sessions", {}).get(session_id)
    if not created_at or time.time() - float(created_at) > SETTINGS_SESSION_TTL:
        return real_data, session_id, False
    return real_data, session_id, True


async def get_settings_identity(user_id: int, bot_id: str):
    user_id = int(user_id)
    role = await get_user_role(user_id, bot_id=bot_id)
    is_trial = False
    account_status = await account_status_service.resolve(user_id, bot_id)
    async with get_db_session() as db:
        admin = (
            await db.execute(
                select(Admin).where(
                    and_(Admin.bot_id == bot_id, Admin.user_id == user_id, Admin.is_active.is_(True))
                )
            )
        ).scalar_one_or_none()
        owned_bots = await account_status_service.get_owned_bots(user_id, db)
        if admin and admin.is_trial:
            is_trial = True

        bot_creation = (
            await db.execute(select(BotCreation).where(BotCreation.instance_id == bot_id))
        ).scalar_one_or_none()
        # 当前模型中子 Bot 创建者实际保存在 bot_creations.super_admin_id。
        owner_id = int(bot_creation.telegram_id) if bot_creation and bot_creation.telegram_id else None
        if owned_bots:
            owner_id = user_id

    if role == UserRole.SUPER_ADMIN:
        return role, "超级管理员", owner_id, is_trial
    if (account_status.tier == "full" or owned_bots) and owner_id and user_id == owner_id:
        return UserRole.BOT_OWNER, "Bot创建者", owner_id, is_trial
    if role == UserRole.ADMIN and is_trial:
        return role, "试用用户", owner_id, is_trial
    if role == UserRole.ADMIN:
        return role, "管理员", owner_id, is_trial
    return role, "普通用户", owner_id, is_trial


async def guard_settings_callback(query, context, callback_data: str) -> bool:
    if not is_settings_callback(callback_data):
        return True
    return True

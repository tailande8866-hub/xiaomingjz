"""
扩展管理功能：
1. 我的群组
2. 授权成功私聊通知面板
3. 机器人进群消息
4. 群组话题模式（私聊 <-> 群组）
"""
import html
import json
import logging
from typing import Any, Optional

from sqlalchemy import and_, delete, desc, func, or_, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from ..models import (
    AdminGlobalConfig,
    Group,
    GroupMemberIndex,
    GroupOperator,
    GroupTag,
    TimedMessageSetting,
    TopicForwardMap,
    Transaction,
    UserConfig,
    get_db_session,
)
from ..models.enums import GroupStatus
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import UserRole, get_user_role
from ..services.timed_message_manager import (
    MIN_INTERVAL_SECONDS,
    cancel_application_timed_message_job,
    refresh_application_timed_message_job,
)

logger = logging.getLogger(__name__)

CFG_BOT_JOIN_MESSAGES = "bot_join_messages"
CFG_TOPIC_MODE_ENABLED = "topic_mode_enabled"
CFG_TOPIC_TARGET_GROUP_ID = "topic_target_group_id"
CFG_TIMED_MESSAGES = "timed_messages"
CFG_AD_SLOT = "ad_slot"
PAGE_SIZE = 8

DEFAULT_BOT_JOIN_MESSAGES = [
    "🎉 欢迎 @username 将 我添加到本群\n\n"
    "✅ 本群已被授权使用\n"
    "✨ 所有功能已启用\n\n"
    "📝 发送 开始 即可开始记账\n"
    "📖 发送 帮助 查看详细指南。\n\n"
    "💡 如果发送 开始 没反应，请到 @BotFather 关闭本机器人的 Group Privacy（群组隐私模式），或将机器人设为群管理员后再测试。"
]


def _enum_value(value: Any) -> str:
    return getattr(value, "value", value)


def _id_query_key(group_id: int) -> str:
    return f"group_id_query_enabled:{group_id}"


def _is_group_usable(group: Group) -> bool:
    return bool(group.is_active) and _enum_value(group.status) == GroupStatus.ACTIVE.value


def _status_text(group: Group) -> str:
    if _is_group_usable(group):
        return "✅ 已授权 / 可用"
    if not group.is_active or _enum_value(group.status) == GroupStatus.DISABLED.value:
        return "❌ 已禁用"
    if _enum_value(group.status) == GroupStatus.UNAUTHORIZED.value:
        return "❌ 未授权"
    if _enum_value(group.status) == GroupStatus.EXPIRED.value:
        return "❌ 已过期"
    return "❌ 不可用"


def _status_icon(group: Group) -> str:
    return "✅" if _is_group_usable(group) else "❌"


def _short_group_name(group: Group, max_len: int = 14) -> str:
    name = (group.group_name or f"群组 {group.group_id}").strip()
    return name if len(name) <= max_len else f"{name[:max_len - 1]}…"


async def _is_owner(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user_id, bot_id=bot_id)
    return role in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER]


async def _deny(query):
    await query.answer("您无权限查看该群组信息", show_alert=True)


async def _can_manage_group(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    group: Group,
    db=None,
) -> bool:
    """
    检查用户是否可以管理该群组
    
    规则：只有【当前用户主动拉机器人进群】才能管理
    - 超级管理员和普通用户都只能管理自己主动添加的群组
    """
    # 只检查是否是该用户邀请的群组
    return group.invited_by == user_id


async def _get_config(db, bot_id: str, key: str, default: Any = None) -> Any:
    result = await db.execute(
        select(AdminGlobalConfig).where(
            and_(
                AdminGlobalConfig.bot_id == bot_id,
                AdminGlobalConfig.config_key == key,
                AdminGlobalConfig.is_active.is_(True),
            )
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        return default
    try:
        return json.loads(config.config_value).get("value", default)
    except Exception:
        return config.config_value or default


async def _set_config(db, bot_id: str, key: str, value: Any, user_id: int, description: str):
    result = await db.execute(
        select(AdminGlobalConfig).where(
            and_(AdminGlobalConfig.bot_id == bot_id, AdminGlobalConfig.config_key == key)
        )
    )
    config = result.scalar_one_or_none()
    payload = json.dumps({"value": value}, ensure_ascii=False)
    if config:
        config.config_value = payload
        config.updated_by = user_id
        config.description = description
        config.is_active = True
    else:
        db.add(
            AdminGlobalConfig(
                bot_id=bot_id,
                config_key=key,
                config_value=payload,
                description=description,
                updated_by=user_id,
                is_active=True,
            )
        )
    await db.flush()


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = context.user_data.get("_settings_unwrapped_callback_data") or query.data or ""

    if data.startswith("mygroups:"):
        await _handle_mygroups_callback(query, context, data)
        return

    if data.startswith("timedmsg:"):
        await _handle_timed_message_callback(query, context, data)
        return

    if not await _is_owner(query.from_user.id, context):
        await query.answer("权限不足，仅超级管理员 / Bot 创建者可用", show_alert=True)
        return

    if data == "botjoin:show":
        await show_bot_join_page(query, context)
    elif data == "botjoin:set":
        context.user_data["waiting_bot_join_message"] = True
        await query.edit_message_text(
            "🤖 <b>机器人进群消息</b>\n\n请输入机器人进群时发送的消息。\n\n"
            "支持多条消息：每条消息用一行 <code>---</code> 分隔。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="botjoin:show")]]),
            parse_mode="HTML",
        )
    elif data == "botjoin:clear":
        async with get_db_session() as db:
            await _set_config(
                db,
                get_current_bot_id(context),
                CFG_BOT_JOIN_MESSAGES,
                DEFAULT_BOT_JOIN_MESSAGES,
                query.from_user.id,
                "机器人进群消息",
            )
        await show_bot_join_page(query, context, notice="✅ 已清空并恢复默认")
    elif data == "topic:show":
        from .topic_mode_handler import show_topic_settings_page
        await show_topic_settings_page(query, context)
    elif data == "topic:enable":
        from .topic_mode_handler import handle_topic_enable
        await handle_topic_enable(query, context)
    elif data == "topic:disable":
        from .topic_mode_handler import handle_topic_disable
        await handle_topic_disable(query, context)
    elif data == "topic:view_group":
        from .topic_mode_handler import handle_topic_view_group
        await handle_topic_view_group(query, context)
    elif data == "topic:settings":
        from .topic_mode_handler import show_topic_settings_page
        await show_topic_settings_page(query, context)
    elif data == "topic:set_group":
        from .topic_mode_handler import show_topic_settings_page
        await query.answer("请使用「拉我进群」按钮开启话题模式", show_alert=True)
        await show_topic_settings_page(query, context)
    elif data.startswith("topic:confirm_enable:"):
        from .topic_mode_handler import handle_topic_confirm_enable
        group_id = int(data.split(":")[-1])
        await handle_topic_confirm_enable(query, context, group_id)
    elif data.startswith("topic_cs:"):
        from .topic_mode_handler import handle_cs_callback
        await handle_cs_callback(update, context)
    elif data == "timed:show":
        await show_timed_messages_page(query, context)
    elif data == "timed:set":
        context.user_data["waiting_timed_message"] = True
        await query.edit_message_text(
            "⏰ <b>定时消息设置</b>\n\n请输入定时消息内容。\n\n"
            "支持多条消息：每条消息用一行 <code>---</code> 分隔。\n"
            "时间格式支持：HH:MM（例如：09:00, 18:30）",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="timed:show")]]),
            parse_mode="HTML",
        )
    elif data == "timed:clear":
        async with get_db_session() as db:
            await _set_config(db, get_current_bot_id(context), CFG_TIMED_MESSAGES, [], query.from_user.id, "定时消息")
        await show_timed_messages_page(query, context, notice="✅ 已清空定时消息")
    elif data == "ad:show":
        await show_ad_slot_page(query, context)
    elif data == "ad:set":
        context.user_data["waiting_ad_slot"] = True
        await query.edit_message_text(
            "📢 <b>广告位设置</b>\n\n请输入广告位内容。\n\n"
            "支持多条消息：每条消息用一行 <code>---</code> 分隔。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="ad:show")]]),
            parse_mode="HTML",
        )
    elif data == "ad:clear":
        async with get_db_session() as db:
            await _set_config(db, get_current_bot_id(context), CFG_AD_SLOT, [], query.from_user.id, "广告位")
        await show_ad_slot_page(query, context, notice="✅ 已清空广告位")


async def _handle_mygroups_callback(query, context: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "show"
    page = 1
    if action == "show":
        await show_my_groups(query, context, page=1)
    elif action == "page":
        await show_my_groups(query, context, page=int(parts[2]))
    elif action == "detail":
        group_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else context.user_data.get("mygroups_page", 1)
        await show_group_detail(query, context, group_id, page=page)
    elif action == "delete_confirm":
        group_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else context.user_data.get("mygroups_page", 1)
        await show_delete_confirm(query, context, group_id, page=page)
    elif action == "delete":
        group_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else context.user_data.get("mygroups_page", 1)
        await delete_group(query, context, group_id, page=page)
    elif action == "toggle_active":
        group_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else context.user_data.get("mygroups_page", 1)
        await toggle_group_active(query, context, group_id, page=page)
    elif action == "toggle_id_query":
        group_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else context.user_data.get("mygroups_page", 1)
        await toggle_id_query(query, context, group_id, page=page)
    elif action == "send_prompt":
        group_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else context.user_data.get("mygroups_page", 1)
        await prompt_group_message(query, context, group_id, page=page)
    else:
        await query.answer("未知操作", show_alert=True)


async def _accessible_group_condition(user_id: int, bot_id: str, owner: bool, db):
    """
    获取当前用户可访问的群组条件
    
    规则：只显示【当前用户主动拉机器人进群】的群组
    - 超级管理员和普通用户都只显示自己主动添加的群组
    - 不显示他人添加的群组
    """
    return [
        Group.bot_id == bot_id,
        Group.invited_by == user_id,
    ]


async def show_my_groups(query, context: ContextTypes.DEFAULT_TYPE, page: int = 1, notice: str = ""):
    bot_id = get_current_bot_id(context)
    user_id = query.from_user.id
    owner = await _is_owner(user_id, context)
    async with get_db_session() as db:
        conditions = await _accessible_group_condition(user_id, bot_id, owner, db)
        total = (await db.execute(select(func.count()).select_from(Group).where(and_(*conditions)))).scalar() or 0
        max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, max_page))
        result = await db.execute(
            select(Group)
            .where(and_(*conditions))
            .order_by(desc(Group.updated_at))
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
        groups = result.scalars().all()

    context.user_data["mygroups_page"] = page
    text = (
        "👥 <b>我的群组</b>\n\n"
        "👉 点击对应群组按钮可以查看详细信息\n\n"
        f"共 <b>{total}</b> 个群组，当前第 <b>{page}/{max_page}</b> 页。"
    )
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard = []
    for group in groups:
        label = f"{_status_icon(group)} {_short_group_name(group)}"
        keyboard.append(
            [
                InlineKeyboardButton(label, callback_data=f"mygroups:detail:{group.group_id}:{page}"),
                InlineKeyboardButton("🗑️ 删除", callback_data=f"mygroups:delete_confirm:{group.group_id}:{page}"),
            ]
        )

    if total > PAGE_SIZE:
        keyboard.append(
            [
                InlineKeyboardButton("⬅️ 上一页", callback_data=f"mygroups:page:{max(1, page - 1)}"),
                InlineKeyboardButton("下一页 ➡️", callback_data=f"mygroups:page:{min(max_page, page + 1)}"),
            ]
        )
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="settings:main")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_group_detail(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    page: int = 1,
    title: str = "🎉 群组授权成功",
    notice: str = "",
):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        group = (
            await db.execute(select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == group_id)))
        ).scalar_one_or_none()
        if not group:
            await query.edit_message_text(
                "❌ 群组不存在或已删除。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"mygroups:page:{page}")]]),
            )
            return
        if not await _can_manage_group(query.from_user.id, context, group, db=db):
            await _deny(query)
            return
        id_query_enabled = bool(await _get_config(db, bot_id, _id_query_key(group_id), False))

    text = build_authorized_group_panel_text(group, title=title, notice=notice)
    keyboard = build_authorized_group_panel_keyboard(
        group,
        page=page,
        id_query_enabled=id_query_enabled,
        back_callback=f"mygroups:page:{page}",
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


def build_authorized_group_panel_text(group: Group, title: str = "🎉 群组授权成功", notice: str = "") -> str:
    admin_name = f"@{group.invited_by_username}" if group.invited_by_username else (str(group.invited_by) if group.invited_by else "未记录")
    timed_status = "✅ 已开启" if group.day_cut_time else "❌ 未设置"
    group_tag = group.group_tag or "默认"
    prefix = f"{notice}\n\n" if notice else ""
    return (
        f"{prefix}{title}\n\n"
        f"群组 ID：<code>{group.group_id}</code>\n"
        f"名称：{html.escape(group.group_name or '未知')}\n"
        f"管理员：{html.escape(admin_name)}\n"
        f"状态：{_status_text(group)}\n"
        f"所在分组：{html.escape(group_tag)}\n"
        f"定时消息状态：{timed_status}"
    )


def build_authorized_group_panel_keyboard(
    group: Group,
    page: int = 1,
    id_query_enabled: bool = False,
    back_callback: str = "settings:main",
) -> InlineKeyboardMarkup:
    group_id = group.group_id
    active_text = "🚫 禁止使用" if _is_group_usable(group) else "✅ 开启"
    query_text = "❌ 关闭ID查询" if id_query_enabled else "🆔 开启ID查询"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(active_text, callback_data=f"mygroups:toggle_active:{group_id}:{page}"),
                InlineKeyboardButton("🗑️ 删除群组", callback_data=f"mygroups:delete_confirm:{group_id}:{page}"),
            ],
            [
                InlineKeyboardButton("📨 发送消息", callback_data=f"mygroups:send_prompt:{group_id}:{page}"),
                InlineKeyboardButton(query_text, callback_data=f"mygroups:toggle_id_query:{group_id}:{page}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
        ]
    )


async def show_delete_confirm(query, context, group_id: int, page: int = 1):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        group = (
            await db.execute(select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == group_id)))
        ).scalar_one_or_none()
        if not group:
            await show_my_groups(query, context, page=page, notice="❌ 群组不存在或已删除")
            return
        if not await _can_manage_group(query.from_user.id, context, group, db=db):
            await _deny(query)
            return
        group_name = group.group_name or f"群组 {group_id}"

    await query.edit_message_text(
        f"⚠️ <b>确认删除群组：{html.escape(group_name)}</b>\n\n"
        "删除后机器人将失去该群组的所有权限，是否继续？",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ 确认删除", callback_data=f"mygroups:delete:{group_id}:{page}")],
                [InlineKeyboardButton("❌ 取消", callback_data=f"mygroups:page:{page}")],
            ]
        ),
        parse_mode="HTML",
    )


async def delete_group(query, context, group_id: int, page: int = 1):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        group = (
            await db.execute(select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == group_id)))
        ).scalar_one_or_none()
        if not group:
            await show_my_groups(query, context, page=page, notice="❌ 群组不存在或已删除")
            return
        if not await _can_manage_group(query.from_user.id, context, group, db=db):
            await _deny(query)
            return

        await db.execute(delete(Transaction).where(and_(Transaction.bot_id == bot_id, Transaction.group_id == group_id)))
        await db.execute(delete(UserConfig).where(and_(UserConfig.bot_id == bot_id, UserConfig.group_id == group_id)))
        await db.execute(delete(GroupOperator).where(and_(GroupOperator.bot_id == bot_id, GroupOperator.group_id == group_id)))
        await db.execute(delete(GroupMemberIndex).where(and_(GroupMemberIndex.bot_id == bot_id, GroupMemberIndex.group_id == group_id)))
        await db.execute(delete(TopicForwardMap).where(and_(TopicForwardMap.bot_id == bot_id, TopicForwardMap.target_group_id == group_id)))
        await db.execute(delete(AdminGlobalConfig).where(and_(AdminGlobalConfig.bot_id == bot_id, AdminGlobalConfig.config_key == _id_query_key(group_id))))
        await db.delete(group)

    try:
        await context.bot.leave_chat(group_id)
    except Exception as exc:
        logger.warning("机器人退群失败 group_id=%s: %s", group_id, exc)

    await query.answer("✅ 群组已删除，机器人退群")
    await show_my_groups(query, context, page=page, notice="✅ 群组已删除  机器人退群")


async def toggle_group_active(query, context, group_id: int, page: int = 1):
    bot_id = get_current_bot_id(context)
    notice = ""
    async with get_db_session() as db:
        group = (
            await db.execute(select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == group_id)))
        ).scalar_one_or_none()
        if not group:
            await show_my_groups(query, context, page=page, notice="❌ 群组不存在或已删除")
            return
        if not await _can_manage_group(query.from_user.id, context, group, db=db):
            await _deny(query)
            return
        if _is_group_usable(group):
            group.is_active = False
            group.status = GroupStatus.DISABLED.value
            notice = "✅ 已禁止该群组使用机器人"
        else:
            group.is_active = True
            group.status = GroupStatus.ACTIVE.value
            notice = "✅ 已允许该群组使用机器人"
        await db.flush()

    await show_group_detail(query, context, group_id, page=page, notice=notice)


async def toggle_id_query(query, context, group_id: int, page: int = 1):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        group = (
            await db.execute(select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == group_id)))
        ).scalar_one_or_none()
        if not group:
            await show_my_groups(query, context, page=page, notice="❌ 群组不存在或已删除")
            return
        if not await _can_manage_group(query.from_user.id, context, group, db=db):
            await _deny(query)
            return
        current = bool(await _get_config(db, bot_id, _id_query_key(group_id), False))
        new_value = not current
        await _set_config(db, bot_id, _id_query_key(group_id), new_value, query.from_user.id, "群组ID查询开关")

    notice = "✅ 已开启ID查询功能" if new_value else "✅ 已关闭ID查询功能"
    await show_group_detail(query, context, group_id, page=page, notice=notice)


async def prompt_group_message(query, context, group_id: int, page: int = 1):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        group = (
            await db.execute(select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == group_id)))
        ).scalar_one_or_none()
        if not group:
            await show_my_groups(query, context, page=page, notice="❌ 群组不存在或已删除")
            return
        if not await _can_manage_group(query.from_user.id, context, group, db=db):
            await _deny(query)
            return

    context.user_data["mygroups_waiting_send"] = {"group_id": group_id, "page": page}
    await query.edit_message_text(
        f"📨 <b>发送消息</b>\n\n请输入要发送到「{html.escape(group.group_name or str(group_id))}」的内容：",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"mygroups:detail:{group_id}:{page}")]]),
        parse_mode="HTML",
    )


async def _get_or_create_timed_setting(db, bot_id: str, scope_type: str, scope_id: Optional[int]):
    conditions = [
        TimedMessageSetting.bot_id == bot_id,
        TimedMessageSetting.scope_type == scope_type,
    ]
    if scope_id is None:
        conditions.append(TimedMessageSetting.group_id.is_(None))
    else:
        conditions.append(TimedMessageSetting.group_id == scope_id)
    setting = (await db.execute(select(TimedMessageSetting).where(and_(*conditions)))).scalar_one_or_none()
    if setting:
        return setting
    setting = TimedMessageSetting(
        bot_id=bot_id,
        scope_type=scope_type,
        group_id=scope_id,
        enabled=False,
        interval_seconds=MIN_INTERVAL_SECONDS,
        content="",
    )
    db.add(setting)
    await db.flush()
    return setting


def _timed_status(setting: TimedMessageSetting) -> str:
    return "已开启" if setting and setting.enabled else "已关闭"


def _timed_content(setting: TimedMessageSetting) -> str:
    content = (setting.content or "").strip() if setting else ""
    return content if content else "未设置"


async def _handle_timed_message_callback(query, context: ContextTypes.DEFAULT_TYPE, data: str):
    if not await _is_owner(query.from_user.id, context):
        await query.answer("无权限访问", show_alert=True)
        return

    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "mode"

    if action == "mode":
        await show_timed_mode_page(query, context, int(parts[2]), int(parts[3]) if len(parts) > 3 else 1)
    elif action == "global":
        await show_timed_global_page(query, context, int(parts[2]), int(parts[3]) if len(parts) > 3 else 1)
    elif action == "groups":
        await show_timed_group_list(query, context, int(parts[2]), int(parts[3]) if len(parts) > 3 else 1)
    elif action == "group":
        await show_timed_group_page(query, context, int(parts[2]), int(parts[3]), int(parts[4]) if len(parts) > 4 else 1)
    elif action in {"global_enable", "global_disable"}:
        await toggle_timed_global(query, context, int(parts[2]), int(parts[3]), enabled=action == "global_enable")
    elif action == "global_interval":
        group_id, page = int(parts[2]), int(parts[3])
        context.user_data["waiting_timed_global_interval"] = {"group_id": group_id, "page": page}
        await query.edit_message_text(
            "⏱️ <b>设置全局定时间隔</b>\n\n请输入发送间隔（秒），最小 300 秒。\n\n输入“取消”返回设置页。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回模式设置页", callback_data=f"timedmsg:global:{group_id}:{page}")]]),
            parse_mode="HTML",
        )
    elif action == "global_content":
        group_id, page = int(parts[2]), int(parts[3])
        context.user_data["waiting_timed_global_content"] = {"group_id": group_id, "page": page}
        await query.edit_message_text(
            "✏️ <b>设置全局定时内容</b>\n\n请输入要发送的文本，支持换行。\n\n输入“取消”返回设置页。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回模式设置页", callback_data=f"timedmsg:global:{group_id}:{page}")]]),
            parse_mode="HTML",
        )
    elif action in {"group_enable", "group_disable"}:
        await toggle_timed_group(query, context, int(parts[2]), int(parts[3]), int(parts[4]), enabled=action == "group_enable")
    elif action == "group_interval":
        tag_id, source_group_id, page = int(parts[2]), int(parts[3]), int(parts[4])
        context.user_data[f"waiting_timed_group_interval:{tag_id}"] = {"tag_id": tag_id, "group_id": source_group_id, "page": page}
        await query.edit_message_text(
            "⏱️ <b>设置分组定时间隔</b>\n\n请输入发送间隔（秒），最小 300 秒。\n\n输入“取消”返回设置页。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回分组设置页", callback_data=f"timedmsg:group:{tag_id}:{source_group_id}:{page}")]]),
            parse_mode="HTML",
        )
    elif action == "group_content":
        tag_id, source_group_id, page = int(parts[2]), int(parts[3]), int(parts[4])
        context.user_data[f"waiting_timed_group_content:{tag_id}"] = {"tag_id": tag_id, "group_id": source_group_id, "page": page}
        await query.edit_message_text(
            "✏️ <b>设置分组定时内容</b>\n\n请输入要发送的文本，支持换行。\n\n输入“取消”返回设置页。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回分组设置页", callback_data=f"timedmsg:group:{tag_id}:{source_group_id}:{page}")]]),
            parse_mode="HTML",
        )
    else:
        await query.answer("未知操作", show_alert=True)


async def show_timed_mode_page(query, context, group_id: int, page: int = 1):
    back_callback = f"mygroups:detail:{group_id}:{page}" if group_id else "settings:main"
    await query.edit_message_text(
        "⏰ <b>定时消息模式</b>\n\n请选择定时消息的生效范围：",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🌍 所有群组生效", callback_data=f"timedmsg:global:{group_id}:{page}"),
                    InlineKeyboardButton("📂 按分组生效", callback_data=f"timedmsg:groups:{group_id}:{page}"),
                ],
                [InlineKeyboardButton("← 返回群组详情页" if group_id else "← 返回", callback_data=back_callback)],
            ]
        ),
        parse_mode="HTML",
    )


async def show_timed_global_page(query, context, group_id: int, page: int = 1, notice: str = ""):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        setting = await _get_or_create_timed_setting(db, bot_id, "global", None)
        status = _timed_status(setting)
        interval = setting.interval_seconds or MIN_INTERVAL_SECONDS
        content = _timed_content(setting)
    text = (
        f"{notice + chr(10) + chr(10) if notice else ''}"
        "🌍 <b>全局定时消息设置</b>\n\n"
        f"当前状态：{status}\n"
        f"发送间隔：{interval} 秒\n"
        f"发送内容：{html.escape(content)}"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🟢 开启定时", callback_data=f"timedmsg:global_enable:{group_id}:{page}"),
                    InlineKeyboardButton("🔴 关闭定时", callback_data=f"timedmsg:global_disable:{group_id}:{page}"),
                ],
                [
                    InlineKeyboardButton("⏱️ 设置间隔", callback_data=f"timedmsg:global_interval:{group_id}:{page}"),
                    InlineKeyboardButton("✏️ 设置内容", callback_data=f"timedmsg:global_content:{group_id}:{page}"),
                ],
                [InlineKeyboardButton("← 返回模式选择页", callback_data=f"timedmsg:mode:{group_id}:{page}")],
            ]
        ),
        parse_mode="HTML",
    )


async def show_timed_group_list(query, context, group_id: int, page: int = 1, notice: str = ""):
    """显示定时消息分组选择页面 - 双列排版，每页10个"""
    bot_id = get_current_bot_id(context)
    
    PER_PAGE = 10  # 每页10个
    COLS = 2       # 一行2个
    
    async with get_db_session() as db:
        result = await db.execute(
            select(GroupTag).where(and_(GroupTag.bot_id == bot_id, GroupTag.is_active.is_(True))).order_by(GroupTag.tag_name)
        )
        tags = list(result.scalars().all())
        
        # 获取每个分组的群组数量
        tag_counts = {}
        total_groups = 0
        for tag in tags:
            count_result = await db.execute(
                select(func.count(Group.id)).where(
                    and_(
                        Group.bot_id == bot_id,
                        Group.group_tag == tag.tag_name,
                        Group.is_active.is_(True),
                    )
                )
            )
            count = count_result.scalar() or 0
            tag_counts[tag.tag_name] = count
            total_groups += count
    
    if not tags:
        await query.edit_message_text(
            f"{notice + chr(10) + chr(10) if notice else ''}暂无分组，请先创建分组。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data=f"timedmsg:mode:{group_id}:{page}")]]),
        )
        return
    
    # 分页计算
    total_pages = max(1, (len(tags) + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    page_tags = tags[start:end]
    
    # 构建按钮 - 双列排版
    keyboard = []
    for i in range(0, len(page_tags), COLS):
        row = []
        for j in range(COLS):
            idx = i + j
            if idx < len(page_tags):
                tag = page_tags[idx]
                count = tag_counts.get(tag.tag_name, 0)
                row.append(InlineKeyboardButton(
                    f"📁 {tag.tag_name} ({count}个群组)",
                    callback_data=f"timedmsg:group:{tag.id}:{group_id}:{page}"
                ))
        if row:
            keyboard.append(row)
    
    # 分页按钮
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"timedmsg:groups:{group_id}:{page - 1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"timedmsg:groups:{group_id}:{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"timedmsg:mode:{group_id}:{page}")])
    
    # 构建文案
    text = f"{notice + chr(10) + chr(10) if notice else ''}"
    text += "📁 <b>选择分组</b>\n\n"
    text += "请选择要设置定时消息的分组：\n\n"
    text += f"当前共有 {len(tags)} 个分组，{total_groups} 个群组"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def show_timed_group_page(query, context, tag_id: int, source_group_id: int, page: int = 1, notice: str = ""):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        tag = await db.get(GroupTag, tag_id)
        if not tag or tag.bot_id != bot_id or not tag.is_active:
            await show_timed_group_list(query, context, source_group_id, page, notice="❌ 分组不存在或已删除")
            return
        setting = await _get_or_create_timed_setting(db, bot_id, "group", tag.id)
        status = _timed_status(setting)
        interval = setting.interval_seconds or MIN_INTERVAL_SECONDS
        content = _timed_content(setting)
        tag_name = tag.tag_name
    text = (
        f"{notice + chr(10) + chr(10) if notice else ''}"
        f"📂 <b>{html.escape(tag_name)} 定时消息设置</b>\n\n"
        "定时消息将仅发送给该分组下的所有群组\n\n"
        f"当前状态：{status}\n"
        f"发送间隔：{interval} 秒\n"
        f"发送内容：{html.escape(content)}"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🟢 开启定时", callback_data=f"timedmsg:group_enable:{tag_id}:{source_group_id}:{page}"),
                    InlineKeyboardButton("🔴 关闭定时", callback_data=f"timedmsg:group_disable:{tag_id}:{source_group_id}:{page}"),
                ],
                [
                    InlineKeyboardButton("⏱️ 设置间隔", callback_data=f"timedmsg:group_interval:{tag_id}:{source_group_id}:{page}"),
                    InlineKeyboardButton("✏️ 设置内容", callback_data=f"timedmsg:group_content:{tag_id}:{source_group_id}:{page}"),
                ],
                [InlineKeyboardButton("← 返回分组列表页", callback_data=f"timedmsg:groups:{source_group_id}:{page}")],
            ]
        ),
        parse_mode="HTML",
    )


async def show_timed_group_list(query, context, group_id: int, page: int = 1, notice: str = ""):
    """新版按分组生效列表页，复用分组管理的两列分页样式。"""
    bot_id = get_current_bot_id(context)
    per_page = 10
    cols = 2

    async with get_db_session() as db:
        tags_result = await db.execute(
            select(GroupTag).where(
                and_(GroupTag.bot_id == bot_id, GroupTag.is_active.is_(True))
            ).order_by(GroupTag.tag_name)
        )
        tags = list(tags_result.scalars().all())

        tag_counts: dict[str, int] = {}
        total_groups = 0
        for tag in tags:
            count_result = await db.execute(
                select(func.count(Group.id)).where(
                    and_(
                        Group.bot_id == bot_id,
                        Group.group_tag == tag.tag_name,
                        Group.is_active.is_(True),
                    )
                )
            )
            count = count_result.scalar() or 0
            tag_counts[tag.tag_name] = count
            total_groups += count

    if not tags:
        text = "📁 <b>选择分组</b>\n\n"
        if notice:
            text += f"{notice}\n\n"
        text += "ℹ️ 暂无分组，请先在「分组管理」中创建分组"
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ 返回", callback_data=f"timedmsg:mode:{group_id}:{page}")]]
            ),
            parse_mode="HTML",
        )
        return

    total_pages = max(1, (len(tags) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    page_tags = tags[(page - 1) * per_page:(page - 1) * per_page + per_page]

    keyboard = []
    for i in range(0, len(page_tags), cols):
        row = []
        for tag in page_tags[i:i + cols]:
            count = tag_counts.get(tag.tag_name, 0)
            row.append(
                InlineKeyboardButton(
                    f"📁 {tag.tag_name} ({count}个群组)",
                    callback_data=f"timedmsg:group:{tag.id}:{group_id}:{page}",
                )
            )
        keyboard.append(row)

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"timedmsg:groups:{group_id}:{page - 1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"timedmsg:groups:{group_id}:{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"timedmsg:mode:{group_id}:{page}")])

    text = "📁 <b>选择分组</b>\n\n"
    text += "✨点分组名即可进入详情页，就能：\n"
    text += "⏰设置定时、✏️修改内容、🔛切换状态\n\n"
    text += f"当前共有 {len(tags)} 个分组，{total_groups} 个群组"
    if notice:
        text += f"\n\n{notice}"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


# ============================================================================
# Unified settings page overrides
# ============================================================================

async def show_my_groups(query, context: ContextTypes.DEFAULT_TYPE, page: int = 1, notice: str = ""):
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    user_id = query.from_user.id
    owner = await _is_owner(user_id, context)
    async with get_db_session() as db:
        conditions = await _accessible_group_condition(user_id, bot_id, owner, db)
        total = (await db.execute(select(func.count()).select_from(Group).where(and_(*conditions)))).scalar() or 0
        max_page = max(1, (total + 4) // 5)
        page = max(1, min(page, max_page))
        groups = list((await db.execute(
            select(Group).where(and_(*conditions)).order_by(desc(Group.updated_at)).offset((page - 1) * 5).limit(5)
        )).scalars().all())

    context.user_data["mygroups_page"] = page
    text = (
        "👥 <b>我的群组</b>\n\n"
        "👉 点击对应群组按钮可以查看详细信息\n\n"
        f"共 <b>{total}</b> 个群组，当前第 <b>{page}/{max_page}</b> 页。"
    )
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for group in groups:
        label = f"{_status_icon(group)} {_short_group_name(group)}"
        row.append(InlineKeyboardButton(label, callback_data=f"mygroups:detail:{group.group_id}:{page}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    pagination_row = ui_renderer.build_pagination_row(
        page,
        max_page,
        f"mygroups:page:{page - 1}" if page > 1 else None,
        f"mygroups:page:{page + 1}" if page < max_page else None,
    )
    if pagination_row:
        keyboard.append(pagination_row)
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_timed_mode_page(query, context, group_id: int, page: int = 1):
    from ..core.ui_renderer import ui_renderer

    text = "⏰ <b>定时消息模式</b>\n\n请选择定时消息的生效范围："
    keyboard = [[
        InlineKeyboardButton("🌍 所有群组生效", callback_data=f"timedmsg:global:{group_id}:{page}"),
        InlineKeyboardButton("📁 按分组生效", callback_data=f"timedmsg:groups:{group_id}:{page}"),
    ]]
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_timed_global_page(query, context, group_id: int, page: int = 1, notice: str = ""):
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        setting = await _get_or_create_timed_setting(db, bot_id, "global", None)
    status = ui_renderer.format_status(enabled=bool(setting.enabled), configured=bool((setting.content or "").strip()))
    text = (
        f"⏰ <b>全局定时消息设置</b>\n\n{notice + chr(10) if notice else ''}"
        f"状态：{status}\n"
        f"发送间隔：{setting.interval_seconds} 秒\n"
        f"消息内容：{(setting.content or '未配置')[:80]}"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏱️ 设置间隔", callback_data=f"timedmsg:set_global_interval:{group_id}:{page}"),
            InlineKeyboardButton("✏️ 设置内容", callback_data=f"timedmsg:set_global_content:{group_id}:{page}"),
        ],
        [
            InlineKeyboardButton("🟢 已开启" if setting.enabled else "开启", callback_data=f"timedmsg:global:enable:{group_id}:{page}"),
            InlineKeyboardButton("⚪ 已关闭" if not setting.enabled else "关闭", callback_data=f"timedmsg:global:disable:{group_id}:{page}"),
        ],
    ]
    ui_renderer.append_standard_footer(keyboard, f"timedmsg:mode:{group_id}:{page}")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_timed_group_page(query, context, tag_id: int, source_group_id: int, page: int = 1, notice: str = ""):
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        tag = await db.get(GroupTag, tag_id)
        setting = await _get_or_create_timed_setting(db, bot_id, "group", tag_id)
    tag_name = getattr(tag, "tag_name", "未知分组")
    status = ui_renderer.format_status(enabled=bool(setting.enabled), configured=bool((setting.content or "").strip()))
    text = (
        f"⏰ <b>{html.escape(tag_name)} 定时消息设置</b>\n\n"
        f"{notice + chr(10) if notice else ''}"
        f"状态：{status}\n"
        f"发送间隔：{setting.interval_seconds} 秒\n"
        f"消息内容：{(setting.content or '未配置')[:80]}"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏱️ 设置间隔", callback_data=f"timedmsg:set_group_interval:{tag_id}:{source_group_id}:{page}"),
            InlineKeyboardButton("✏️ 设置内容", callback_data=f"timedmsg:set_group_content:{tag_id}:{source_group_id}:{page}"),
        ],
        [
            InlineKeyboardButton("🟢 已开启" if setting.enabled else "开启", callback_data=f"timedmsg:group:enable:{tag_id}:{source_group_id}:{page}"),
            InlineKeyboardButton("⚪ 已关闭" if not setting.enabled else "关闭", callback_data=f"timedmsg:group:disable:{tag_id}:{source_group_id}:{page}"),
        ],
    ]
    ui_renderer.append_standard_footer(keyboard, f"timedmsg:groups:{source_group_id}:{page}")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_bot_join_page(query, context, notice: str = ""):
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        messages = await _get_config(db, bot_id, CFG_BOT_JOIN_MESSAGES, DEFAULT_BOT_JOIN_MESSAGES)
    if isinstance(messages, str):
        messages = [messages]
    preview = "\n---\n".join(messages or DEFAULT_BOT_JOIN_MESSAGES)
    text = (
        f"🤖 <b>机器人进群消息</b>\n\n{notice + chr(10) if notice else ''}"
        f"当前内容预览：\n<code>{html.escape(preview[:800])}</code>\n\n"
        "支持多条消息，用分隔线分开即可。"
    )
    keyboard = [[
        InlineKeyboardButton("✏️ 修改内容", callback_data="botjoin:set"),
        InlineKeyboardButton("🗑️ 恢复默认", callback_data="botjoin:clear"),
    ]]
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_topic_page(query, context, notice: str = ""):
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        enabled = bool(await _get_config(db, bot_id, CFG_TOPIC_MODE_ENABLED, False))
        target_group_id = await _get_config(db, bot_id, CFG_TOPIC_TARGET_GROUP_ID)
    text = (
        f"📌 <b>群组话题模式</b>\n\n{notice + chr(10) if notice else ''}"
        f"状态：{ui_renderer.format_status(enabled=enabled)}\n"
        f"目标群组：<code>{target_group_id or '未配置'}</code>"
    )
    keyboard = [
        [
            InlineKeyboardButton("🟢 已开启" if enabled else "开启", callback_data="topic:enable"),
            InlineKeyboardButton("⚪ 已关闭" if not enabled else "关闭", callback_data="topic:disable"),
        ],
        [InlineKeyboardButton("📍 设置转发群组", callback_data="topic:set_group")],
    ]
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_ad_slot_page(query, context, notice: str = ""):
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        messages = await _get_config(db, bot_id, CFG_AD_SLOT, [])
    if isinstance(messages, str):
        messages = [messages]
    preview = "\n---\n".join(messages) if messages else "未配置"
    text = (
        f"📢 <b>广告设置</b>\n\n{notice + chr(10) if notice else ''}"
        f"状态：{ui_renderer.format_status(enabled=bool(messages), configured=bool(messages))}\n\n"
        f"当前内容预览：\n<code>{html.escape(preview[:800])}</code>"
    )
    keyboard = [[
        InlineKeyboardButton("✏️ 修改内容", callback_data="ad:set"),
        InlineKeyboardButton("🗑️ 清空", callback_data="ad:clear"),
    ]]
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def toggle_timed_global(query, context, group_id: int, page: int, enabled: bool):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        setting = await _get_or_create_timed_setting(db, bot_id, "global", None)
        if enabled and not (setting.content or "").strip():
            await query.answer("请先设置发送内容", show_alert=True)
            await show_timed_global_page(query, context, group_id, page)
            return
        setting.enabled = enabled
        setting_id = setting.id
    if enabled:
        await refresh_application_timed_message_job(context.application, setting_id)
    else:
        await cancel_application_timed_message_job(context.application, "global", None)
    await show_timed_global_page(query, context, group_id, page, notice="✅ 已开启定时" if enabled else "✅ 已关闭定时")


async def toggle_timed_group(query, context, tag_id: int, source_group_id: int, page: int, enabled: bool):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        tag = await db.get(GroupTag, tag_id)
        if not tag or tag.bot_id != bot_id or not tag.is_active:
            await show_timed_group_list(query, context, source_group_id, page, notice="❌ 分组不存在或已删除")
            return
        setting = await _get_or_create_timed_setting(db, bot_id, "group", tag_id)
        if enabled and not (setting.content or "").strip():
            await query.answer("请先设置发送内容", show_alert=True)
            await show_timed_group_page(query, context, tag_id, source_group_id, page)
            return
        setting.enabled = enabled
        setting_id = setting.id
    if enabled:
        await refresh_application_timed_message_job(context.application, setting_id)
    else:
        await cancel_application_timed_message_job(context.application, "group", tag_id)
    await show_timed_group_page(query, context, tag_id, source_group_id, page, notice="✅ 已开启定时" if enabled else "✅ 已关闭定时")


async def _handle_timed_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user or not await _is_owner(user.id, context):
        return False

    text = update.message.text if update.message and update.message.text is not None else ""
    bot_id = get_current_bot_id(context)

    if context.user_data.get("waiting_timed_global_interval"):
        state = context.user_data.pop("waiting_timed_global_interval")
        group_id, page = int(state["group_id"]), int(state["page"])
        if text.strip() == "取消":
            await update.message.reply_text(
                "已取消",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:global:{group_id}:{page}")]]),
            )
            return True
        try:
            interval = int(text.strip())
        except ValueError:
            await update.message.reply_text("请输入正确的秒数。")
            context.user_data["waiting_timed_global_interval"] = state
            return True
        if interval < MIN_INTERVAL_SECONDS:
            await update.message.reply_text("发送间隔不能小于5分钟。")
            context.user_data["waiting_timed_global_interval"] = state
            return True
        async with get_db_session() as db:
            setting = await _get_or_create_timed_setting(db, bot_id, "global", None)
            setting.interval_seconds = interval
            setting_id = setting.id
        await refresh_application_timed_message_job(context.application, setting_id)
        await update.message.reply_text(
            "✅ 全局定时间隔已保存",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:global:{group_id}:{page}")]]),
        )
        return True

    if context.user_data.get("waiting_timed_global_content"):
        state = context.user_data.pop("waiting_timed_global_content")
        group_id, page = int(state["group_id"]), int(state["page"])
        if text.strip() == "取消":
            await update.message.reply_text(
                "已取消",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:global:{group_id}:{page}")]]),
            )
            return True
        content = text.strip()
        if not content:
            await update.message.reply_text("发送内容不能为空。")
            context.user_data["waiting_timed_global_content"] = state
            return True
        async with get_db_session() as db:
            setting = await _get_or_create_timed_setting(db, bot_id, "global", None)
            setting.content = content
            setting_id = setting.id
        await refresh_application_timed_message_job(context.application, setting_id)
        await update.message.reply_text(
            "✅ 全局定时内容已保存",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:global:{group_id}:{page}")]]),
        )
        return True

    group_interval_key = next((key for key in context.user_data if key.startswith("waiting_timed_group_interval:")), None)
    if group_interval_key:
        state = context.user_data.pop(group_interval_key)
        tag_id, group_id, page = int(state["tag_id"]), int(state["group_id"]), int(state["page"])
        if text.strip() == "取消":
            await update.message.reply_text(
                "已取消",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:group:{tag_id}:{group_id}:{page}")]]),
            )
            return True
        try:
            interval = int(text.strip())
        except ValueError:
            await update.message.reply_text("请输入正确的秒数。")
            context.user_data[group_interval_key] = state
            return True
        if interval < MIN_INTERVAL_SECONDS:
            await update.message.reply_text("发送间隔不能小于5分钟。")
            context.user_data[group_interval_key] = state
            return True
        async with get_db_session() as db:
            setting = await _get_or_create_timed_setting(db, bot_id, "group", tag_id)
            setting.interval_seconds = interval
            setting_id = setting.id
        await refresh_application_timed_message_job(context.application, setting_id)
        await update.message.reply_text(
            "✅ 分组定时间隔已保存",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:group:{tag_id}:{group_id}:{page}")]]),
        )
        return True

    group_content_key = next((key for key in context.user_data if key.startswith("waiting_timed_group_content:")), None)
    if group_content_key:
        state = context.user_data.pop(group_content_key)
        tag_id, group_id, page = int(state["tag_id"]), int(state["group_id"]), int(state["page"])
        if text.strip() == "取消":
            await update.message.reply_text(
                "已取消",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:group:{tag_id}:{group_id}:{page}")]]),
            )
            return True
        content = text.strip()
        if not content:
            await update.message.reply_text("发送内容不能为空。")
            context.user_data[group_content_key] = state
            return True
        async with get_db_session() as db:
            setting = await _get_or_create_timed_setting(db, bot_id, "group", tag_id)
            setting.content = content
            setting_id = setting.id
        await refresh_application_timed_message_job(context.application, setting_id)
        await update.message.reply_text(
            "✅ 分组定时内容已保存",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"timedmsg:group:{tag_id}:{group_id}:{page}")]]),
        )
        return True

    return False


async def show_bot_join_page(query, context, notice: str = ""):
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        messages = await _get_config(db, bot_id, CFG_BOT_JOIN_MESSAGES, DEFAULT_BOT_JOIN_MESSAGES)
    if isinstance(messages, str):
        messages = [messages]
    preview = "\n---\n".join(messages or DEFAULT_BOT_JOIN_MESSAGES)
    text = (
        f"🤖 <b>机器人进群消息</b>\n\n{notice + chr(10) if notice else ''}"
        f"当前内容预览：\n<code>{html.escape(preview[:800])}</code>\n\n"
        "支持多条消息，用分隔线分开即可"
    )
    keyboard = [
        [InlineKeyboardButton("✏️ 修改内容", callback_data="botjoin:set"), InlineKeyboardButton("🗑️ 恢复默认", callback_data="botjoin:clear")],
        [InlineKeyboardButton("← 返回", callback_data="settings:main")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_topic_page(query, context, notice: str = ""):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        enabled = bool(await _get_config(db, bot_id, CFG_TOPIC_MODE_ENABLED, False))
        target_group_id = await _get_config(db, bot_id, CFG_TOPIC_TARGET_GROUP_ID)
    text = (
        f"🧵 <b>话题模式</b>\n\n{notice + chr(10) if notice else ''}"
        f"当前状态：{'✅ 已开启' if enabled else '❌ 已关闭'}\n"
        f"转发目标：<code>{target_group_id or '未设置'}</code>\n\n"
        "开启后，用户私聊消息将自动转发到指定群组"
    )
    keyboard = [
        [InlineKeyboardButton("✅ 开启", callback_data="topic:enable"), InlineKeyboardButton("❌ 关闭", callback_data="topic:disable")],
        [InlineKeyboardButton("设置转发群组", callback_data="topic:set_group")],
        [InlineKeyboardButton("← 返回", callback_data="settings:main")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_timed_messages_page(query, context, notice: str = ""):
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    await show_timed_mode_page(query, context, context.user_data.get("mygroups_last_group_id", 0), context.user_data.get("mygroups_page", 1))


async def show_ad_slot_page(query, context, notice: str = ""):
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        messages = await _get_config(db, bot_id, CFG_AD_SLOT, [])
    if isinstance(messages, str):
        messages = [messages]
    preview = "\n---\n".join(messages) if messages else "未设置"
    text = (
        f"📢 <b>广告位</b>\n\n{notice + chr(10) if notice else ''}"
        f"当前内容预览：\n<code>{html.escape(preview[:800])}</code>\n\n"
        "支持多条消息，自动轮播发送"
    )
    keyboard = [
        [InlineKeyboardButton("✏️ 修改内容", callback_data="ad:set"), InlineKeyboardButton("🗑️ 清空", callback_data="ad:clear")],
        [InlineKeyboardButton("← 返回", callback_data="settings:main")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def handle_private_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return False
    user = update.effective_user
    bot_id = get_current_bot_id(context)

    if await _handle_timed_text_input(update, context):
        return True

    waiting_send = context.user_data.get("mygroups_waiting_send")
    if waiting_send:
        group_id = int(waiting_send["group_id"])
        page = int(waiting_send.get("page", 1))
        async with get_db_session() as db:
            group = (
                await db.execute(select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == group_id)))
            ).scalar_one_or_none()
            if not group:
                context.user_data.pop("mygroups_waiting_send", None)
                await update.message.reply_text("❌ 群组不存在")
                return True
            if not await _can_manage_group(user.id, context, group, db=db):
                context.user_data.pop("mygroups_waiting_send", None)
                await update.message.reply_text("⚠️ 无权管理该群组")
                return True
        try:
            await context.bot.copy_message(
                chat_id=group_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
            context.user_data.pop("mygroups_waiting_send", None)
            await update.message.reply_text(
                "✅ 发送成功",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回详情", callback_data=f"mygroups:detail:{group_id}:{page}")]]),
            )
        except Exception as exc:
            logger.error("发送消息失败 group_id=%s: %s", group_id, exc, exc_info=True)
            await update.message.reply_text("❌ 发送失败，请检查群组权限")
        return True

    if context.user_data.get("waiting_bot_join_message"):
        if not await _is_owner(user.id, context):
            await update.message.reply_text("⚠️ 权限不足")
            return True
        raw = update.message.text or ""
        messages = [part.strip() for part in raw.split("\n---\n") if part.strip()] or DEFAULT_BOT_JOIN_MESSAGES
        async with get_db_session() as db:
            await _set_config(db, bot_id, CFG_BOT_JOIN_MESSAGES, messages, user.id, "进群消息设置")
        context.user_data.pop("waiting_bot_join_message", None)
        await update.message.reply_text(
            "✅ 进群消息已保存",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data="botjoin:show")]]),
        )
        return True

    if context.user_data.get("waiting_topic_group_id"):
        if not await _is_owner(user.id, context):
            await update.message.reply_text("⚠️ 权限不足")
            return True
        try:
            target_group_id = int((update.message.text or "").strip())
        except ValueError:
            await update.message.reply_text("❌ 无效群组ID，请输入数字ID")
            return True
        async with get_db_session() as db:
            await _set_config(db, bot_id, CFG_TOPIC_TARGET_GROUP_ID, target_group_id, user.id, "话题模式目标群组")
        context.user_data.pop("waiting_topic_group_id", None)
        await update.message.reply_text(
            "✅ 目标群组已保存",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data="topic:show")]]),
        )
        return True

    if context.user_data.get("waiting_ad_slot"):
        if not await _is_owner(user.id, context):
            await update.message.reply_text("⚠️ 权限不足")
            return True
        raw = update.message.text or ""
        messages = [part.strip() for part in raw.split("\n---\n") if part.strip()] or []
        async with get_db_session() as db:
            await _set_config(db, bot_id, CFG_AD_SLOT, messages, user.id, "广告位设置")
        context.user_data.pop("waiting_ad_slot", None)
        await update.message.reply_text(
            "✅ 广告位内容已保存",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data="ad:show")]]),
        )
        return True

    if update.effective_chat.type != ChatType.PRIVATE:
        return False
    if await _is_owner(user.id, context):
        return False
    role = await get_user_role(user.id, bot_id=bot_id)
    if role == UserRole.ADMIN:
        return False

    # 🆕 委托给新话题模式 handler
    from .topic_mode_handler import handle_topic_private_message
    return await handle_topic_private_message(update, context)


async def handle_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message:
        return False
    reply_user = update.message.reply_to_message.from_user
    if reply_user and reply_user.is_bot and reply_user.id != context.bot.id:
        return False
    text = update.message.text or ""
    try:
        from ..utils.parser import CommandParser
        if CommandParser.is_accounting_command(text) or CommandParser.is_pure_math_expression(text):
            return False
    except Exception:
        import traceback
        traceback.print_exc()
        logger.error("[GROUP_REPLY] parser guard failed", exc_info=True)
        return False
    # 仅作为话题模式群内回复桥接的兜底入口；异常不能污染普通群记账流程。
    from .topic_mode_handler import handle_topic_group_reply
    try:
        return await handle_topic_group_reply(update, context)
    except Exception:
        import traceback
        traceback.print_exc()
        logger.error("[GROUP_REPLY] topic group reply handler failed", exc_info=True)
        return False


async def send_bot_join_messages(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    invited_by_username: str | None = None,
    invited_by_name: str | None = None,
    group_name: str | None = None,
):
    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        messages = await _get_config(db, bot_id, CFG_BOT_JOIN_MESSAGES, DEFAULT_BOT_JOIN_MESSAGES)
    if isinstance(messages, str):
        messages = [messages]

    display_username = f"@{invited_by_username}" if invited_by_username else (invited_by_name or "你")
    display_name = invited_by_name or invited_by_username or "新用户"
    display_group_name = group_name or "本群"

    for message in messages or DEFAULT_BOT_JOIN_MESSAGES:
        rendered = (
            message.replace("@username", display_username)
            .replace("{username}", display_name)
            .replace("{group_name}", display_group_name)
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=rendered, parse_mode="HTML")
        except Exception as exc:
            logger.error("发送机器人入群提示失败: %s", exc, exc_info=True)


async def show_timed_group_list(query, context, group_id: int, page: int = 1, notice: str = ""):
    """新版按分组生效列表页，复用分组管理的双列分页样式。"""
    bot_id = get_current_bot_id(context)
    per_page = 10
    cols = 2

    async with get_db_session() as db:
        tags_result = await db.execute(
            select(GroupTag).where(
                and_(GroupTag.bot_id == bot_id, GroupTag.is_active.is_(True))
            ).order_by(GroupTag.tag_name)
        )
        tags = list(tags_result.scalars().all())

        tag_counts: dict[str, int] = {}
        total_groups = 0
        for tag in tags:
            count_result = await db.execute(
                select(func.count(Group.id)).where(
                    and_(
                        Group.bot_id == bot_id,
                        Group.group_tag == tag.tag_name,
                        Group.is_active.is_(True),
                    )
                )
            )
            count = count_result.scalar() or 0
            tag_counts[tag.tag_name] = count
            total_groups += count

    if not tags:
        text = "📁 <b>选择分组</b>\n\nℹ️ 暂无分组，请先在「分组管理」中创建分组"
        if notice:
            text += f"\n\n{notice}"
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ 返回", callback_data=f"timedmsg:mode:{group_id}:{page}")]]
            ),
            parse_mode="HTML",
        )
        return

    total_pages = max(1, (len(tags) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    page_tags = tags[(page - 1) * per_page:(page - 1) * per_page + per_page]

    keyboard = []
    for i in range(0, len(page_tags), cols):
        row = []
        for tag in page_tags[i:i + cols]:
            count = tag_counts.get(tag.tag_name, 0)
            row.append(
                InlineKeyboardButton(
                    f"📁 {tag.tag_name} ({count}个群组)",
                    callback_data=f"timedmsg:group:{tag.id}:{group_id}:{page}",
                )
            )
        if row:
            keyboard.append(row)

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"timedmsg:groups:{group_id}:{page - 1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"timedmsg:groups:{group_id}:{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"timedmsg:mode:{group_id}:{page}")])

    text = (
        "📁 <b>选择分组</b>\n\n"
        "✨点分组名即可进入详情页，就能：\n"
        "⏰设定时、✏️改内容、🔛切状态啦\n\n"
        f"当前共有 {len(tags)} 个分组，{total_groups} 个群组"
    )
    if notice:
        text += f"\n\n{notice}"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )

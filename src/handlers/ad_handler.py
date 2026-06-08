"""
广告设置菜单处理器 - 使用内联按钮菜单
"""
import logging
import html
import os
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..models import get_db_session
from ..services.ad_service import AdService
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import get_user_role, UserRole

logger = logging.getLogger(__name__)

# 状态机常量
STATE_WAITING_HEADER_TEXT = "waiting_header_text"
STATE_WAITING_HEADER_LINK = "waiting_header_link"
STATE_WAITING_FOOTER_TEXT = "waiting_footer_text"
STATE_WAITING_FOOTER_LINK = "waiting_footer_link"
STATE_WAITING_BUTTON_TEXT = "waiting_button_text"
STATE_WAITING_BUTTON_URL = "waiting_button_url"
STATE_WAITING_EDIT_BUTTON_TEXT = "waiting_edit_button_text"
STATE_WAITING_EDIT_BUTTON_URL = "waiting_edit_button_url"


def _log_ad_callback(data: str, user_id: int, bot_id: str, function_name: str) -> None:
    logger.info(
        "[AD CALLBACK] callback_data=%s user_id=%s bot_id=%s handler_file=%s handler_func=%s",
        data,
        user_id,
        bot_id,
        os.path.basename(__file__),
        function_name,
    )


async def check_ad_permission(user_id: int, bot_id: str) -> bool:
    """
    检查用户是否有广告设置权限

    Args:
        user_id: 用户ID
        bot_id: 机器人ID

    Returns:
        是否有权限
    """
    role = await get_user_role(user_id, bot_id=bot_id)
    if role in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER]:
        return True

    return False


# ============================================================================
# Button add overrides: support one-line input `名称 URL [行号]`
# ============================================================================

def _parse_button_line(msg: str):
    tokens = (msg or "").split()
    if len(tokens) < 2:
        return None

    row_number = 1
    if len(tokens) >= 3 and tokens[-1].isdigit():
        row_number = int(tokens[-1])
        url = tokens[-2]
        button_name = " ".join(tokens[:-2]).strip()
    else:
        url = tokens[-1]
        button_name = " ".join(tokens[:-1]).strip()

    if not button_name or not url:
        return None
    return button_name, url, row_number


async def handle_button_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    parts = data.split(":")
    action = parts[2] if len(parts) > 2 else None
    sub_action = parts[3] if len(parts) > 3 else None

    if action == "add":
        context.user_data[STATE_WAITING_BUTTON_TEXT] = True
        context.user_data.pop(STATE_WAITING_BUTTON_URL, None)
        context.user_data.pop("pending_button_text", None)
        await query.edit_message_text(
            "请输入按钮配置，支持一行完成：\n\n"
            "<code>名称 URL [行号]</code>\n\n"
            "示例：\n"
            "<code>官网 https://example.com 1</code>\n"
            "<code>联系客服 https://t.me/support</code>\n\n"
            "如果你只发按钮名称，我会再问一次链接。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ 返回", callback_data="ad:buttons")]]),
            parse_mode="HTML",
        )
        return
    if action == "edit":
        if sub_action == "list":
            await show_button_list(update, context, edit_mode=True)
        elif sub_action and sub_action.isdigit():
            await show_edit_button_menu(update, context, int(sub_action))
    elif action == "delete":
        if sub_action == "list":
            await show_button_list(update, context, edit_mode=False)
        elif sub_action and sub_action.isdigit():
            await show_delete_button_confirm(update, context, int(sub_action))


async def handle_ad_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        return False

    user_id = update.effective_user.id
    bot_id = get_current_bot_id(context)
    if not await check_ad_permission(user_id, bot_id):
        return False

    msg = update.message.text.strip() if update.message.text else ""
    if msg == "取消":
        from ..utils.settings_guard import clear_edit_states

        clear_edit_states(context)
        await update.message.reply_text(
            "已取消输入。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ 返回设置页", callback_data="ad:show")]]),
        )
        return True

    async with get_db_session() as db:
        if context.user_data.get(STATE_WAITING_BUTTON_TEXT):
            parsed = _parse_button_line(msg)
            if parsed:
                button_text, url, row_number = parsed
                if not AdService.validate_url(url):
                    await update.message.reply_text(
                        "❌ 链接格式不正确，请发送 http(s) 链接或 @username。\n\n"
                        "正确格式：<code>名称 URL [行号]</code>",
                        parse_mode="HTML",
                    )
                    return True
                await AdService.add_ad_button(db, bot_id, button_text, url, row_number)
                context.user_data.pop(STATE_WAITING_BUTTON_TEXT, None)
                context.user_data.pop(STATE_WAITING_BUTTON_URL, None)
                context.user_data.pop("pending_button_text", None)
                await update.message.reply_text(
                    f"✅ 按钮广告已添加：{button_text}\n\n"
                    f"格式：<code>{button_text} {url} {row_number}</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ 返回设置页", callback_data="ad:show")]]),
                )
                return True

            context.user_data.pop(STATE_WAITING_BUTTON_TEXT, None)
            context.user_data["pending_button_text"] = msg
            context.user_data[STATE_WAITING_BUTTON_URL] = True
            await update.message.reply_text(
                f"按钮名称：{msg}\n\n请输入按钮跳转链接（http(s) 或 @username）",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ 返回", callback_data="ad:buttons")]]),
            )
            return True

        if context.user_data.get(STATE_WAITING_BUTTON_URL):
            context.user_data.pop(STATE_WAITING_BUTTON_URL, None)
            if not AdService.validate_url(msg):
                await update.message.reply_text(
                    "❌ 链接格式不正确，请发送 http(s) 链接或 @username",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ 返回", callback_data="ad:buttons")]]),
                )
                context.user_data[STATE_WAITING_BUTTON_URL] = True
                return True
            button_text = context.user_data.pop("pending_button_text", "按钮")
            await AdService.add_ad_button(db, bot_id, button_text, msg)
            await update.message.reply_text(
                f"✅ 按钮广告已添加：{button_text}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ 返回设置页", callback_data="ad:show")]]),
            )
            return True

    return False


async def show_ad_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    显示广告设置主菜单
    """
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id
    bot_id = get_current_bot_id(context)

    if not await check_ad_permission(user_id, bot_id):
        if query:
            await query.answer("无权限访问", show_alert=True)
        else:
            await update.message.reply_text("❌ 无权限访问")
        return

    async with get_db_session() as db:
        settings = await AdService.get_or_create_settings(db, bot_id)
        buttons = await AdService.get_ad_buttons(db, bot_id)

    text = "🎉 广告设置\n\n"
    text += f"状态: {'✅ 开启' if settings.enabled else '❌ 关闭'}\n\n"

    text += "抬头广告:\n"
    text += f"文本: {'✅' if settings.header_text else '❌'}\n"
    text += f"链接: {'✅' if settings.header_link else '❌'}\n\n"

    text += "尾页广告:\n"
    text += f"文本: {'✅' if settings.footer_text else '❌'}\n"
    text += f"链接: {'✅' if settings.footer_link else '❌'}\n\n"

    text += f"按钮广告: {len(buttons)} 个\n"

    keyboard = [
        [
            InlineKeyboardButton("✅ 开启" if not settings.enabled else "❌ 关闭", callback_data="ad:toggle"),
        ],
        [
            InlineKeyboardButton("📝 抬头广告", callback_data="ad:header"),
            InlineKeyboardButton("📝 尾页广告", callback_data="ad:footer"),
        ],
        [
            InlineKeyboardButton("🔘 按钮广告", callback_data="ad:buttons"),
        ],
        [
            InlineKeyboardButton("👀 预览广告", callback_data="ad:preview"),
            InlineKeyboardButton("🗑 删除广告", callback_data="ad:clear"),
        ],
        [
            InlineKeyboardButton("← 返回", callback_data="settings:main"),
        ],
    ]

    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_ad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理广告相关的回调
    """
    try:
        await _handle_ad_callback_impl(update, context)
    except Exception:
        logger.exception("[AD CALLBACK] Unhandled exception with full traceback")
        query = update.callback_query if update else None
        if query:
            try:
                await query.answer("处理失败，请稍后重试", show_alert=True)
            except Exception:
                logger.exception("[AD CALLBACK] Failed to answer callback after exception")


async def _handle_ad_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理广告相关的回调
    """
    query = update.callback_query
    if not query:
        logger.error("[AD CALLBACK] Query is None")
        return

    data = context.user_data.get("_settings_unwrapped_callback_data") or query.data
    user_id = query.from_user.id
    bot_id = get_current_bot_id(context)
    _log_ad_callback(data, user_id, bot_id, "handle_ad_callback")

    if not await check_ad_permission(user_id, bot_id):
        await query.answer("无权限访问", show_alert=True)
        return

    if data in {
        "ad:show",
        "ad:back",
        "ad:toggle",
        "ad:header",
        "ad:footer",
        "ad:buttons",
        "ad:preview",
        "ad:clear",
    } or data.startswith("ad:button:add") or data in {
        "ad:button:edit:list",
        "ad:button:delete:list",
    }:
        await query.answer()

    if data == "ad:show" or data == "ad:back":
        await show_ad_main_menu(update, context)
    elif data == "ad:toggle":
        await toggle_ad(update, context)
    elif data == "ad:header":
        await show_header_menu(update, context)
    elif data == "ad:footer":
        await show_footer_menu(update, context)
    elif data == "ad:buttons":
        await show_buttons_menu(update, context)
    elif data == "ad:preview":
        await preview_ad(update, context)
    elif data == "ad:clear":
        await show_clear_confirm(update, context)
    elif data == "ad:clear:confirm":
        await clear_all_ads(update, context)
    elif data.startswith("ad:header:"):
        await handle_header_action(update, context, data)
    elif data.startswith("ad:footer:"):
        await handle_footer_action(update, context, data)
    elif data.startswith("ad:button:"):
        await handle_button_action(update, context, data)


async def toggle_ad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    切换广告开关
    """
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        settings = await AdService.get_or_create_settings(db, bot_id)
        await AdService.update_settings(db, bot_id, enabled=not settings.enabled)

    await show_ad_main_menu(update, context)


async def show_header_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    显示抬头广告设置菜单
    """
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        settings = await AdService.get_or_create_settings(db, bot_id)

    text = "抬头广告设置\n\n"
    text += f"当前文本: {html.escape(settings.header_text) if settings.header_text else '（未设置）'}\n"
    text += f"当前链接: {html.escape(settings.header_link) if settings.header_link else '（未设置）'}"

    keyboard = [
        [
            InlineKeyboardButton("✏️ 修改文本", callback_data="ad:header:text"),
            InlineKeyboardButton("🔗 修改链接", callback_data="ad:header:link"),
        ],
        [
            InlineKeyboardButton("🗑 删除抬头", callback_data="ad:header:delete"),
            InlineKeyboardButton("← 返回", callback_data="ad:show"),
        ],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_footer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    显示尾页广告设置菜单
    """
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        settings = await AdService.get_or_create_settings(db, bot_id)

    text = "尾页广告设置\n\n"
    text += f"当前文本: {html.escape(settings.footer_text) if settings.footer_text else '（未设置）'}\n"
    text += f"当前链接: {html.escape(settings.footer_link) if settings.footer_link else '（未设置）'}"

    keyboard = [
        [
            InlineKeyboardButton("✏️ 修改文本", callback_data="ad:footer:text"),
            InlineKeyboardButton("🔗 修改链接", callback_data="ad:footer:link"),
        ],
        [
            InlineKeyboardButton("🗑 删除尾页", callback_data="ad:footer:delete"),
            InlineKeyboardButton("← 返回", callback_data="ad:show"),
        ],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_header_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """
    处理抬头广告操作
    """
    query = update.callback_query
    action = data.split(":")[2] if len(data.split(":")) > 2 else None

    bot_id = get_current_bot_id(context)

    if action == "text":
        await query.answer()
        context.user_data[STATE_WAITING_HEADER_TEXT] = True
        await query.edit_message_text(
            "请发送新的抬头广告文本，支持换行。\n发送「取消」退出。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回", callback_data="ad:header")]])
        )
    elif action == "link":
        await query.answer()
        context.user_data[STATE_WAITING_HEADER_LINK] = True
        await query.edit_message_text(
            "请发送链接，例如：https://xxx.com 或 @username\n发送「取消」退出。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回", callback_data="ad:header")]])
        )
    elif action == "delete":
        async with get_db_session() as db:
            await AdService.update_settings(db, bot_id, header_text=None, header_link=None)
        await query.answer("已删除")
        await show_header_menu(update, context)


async def handle_footer_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """
    处理尾页广告操作
    """
    query = update.callback_query
    action = data.split(":")[2] if len(data.split(":")) > 2 else None

    bot_id = get_current_bot_id(context)

    if action == "text":
        await query.answer()
        context.user_data[STATE_WAITING_FOOTER_TEXT] = True
        await query.edit_message_text(
            "请发送新的尾页广告文本，支持换行。\n发送「取消」退出。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回", callback_data="ad:footer")]])
        )
    elif action == "link":
        await query.answer()
        context.user_data[STATE_WAITING_FOOTER_LINK] = True
        await query.edit_message_text(
            "请发送链接，例如：https://xxx.com 或 @username\n发送「取消」退出。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回", callback_data="ad:footer")]])
        )
    elif action == "delete":
        async with get_db_session() as db:
            await AdService.update_settings(db, bot_id, footer_text=None, footer_link=None)
        await query.answer("已删除")
        await show_footer_menu(update, context)


async def show_buttons_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    显示按钮广告设置菜单
    """
    from ..utils.settings_guard import clear_edit_states

    clear_edit_states(context)
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        buttons = await AdService.get_ad_buttons(db, bot_id)

    text = "按钮广告设置\n\n"
    text += f"当前按钮: {len(buttons)} 个\n\n"

    if buttons:
        for i, btn in enumerate(buttons, 1):
            text += f"{i}. {html.escape(btn.button_text)} -> {html.escape(btn.button_url)}\n"

    keyboard = [
        [
            InlineKeyboardButton("➕ 添加按钮", callback_data="ad:button:add"),
            InlineKeyboardButton("✏️ 编辑按钮", callback_data="ad:button:edit:list"),
        ],
        [
            InlineKeyboardButton("🗑 删除按钮", callback_data="ad:button:delete:list"),
            InlineKeyboardButton("← 返回", callback_data="ad:show"),
        ],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_button_list(update: Update, context: ContextTypes.DEFAULT_TYPE, edit_mode: bool = False) -> None:
    """
    显示按钮列表
    """
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        buttons = await AdService.get_ad_buttons(db, bot_id)

    if not buttons:
        await query.answer("暂无按钮", show_alert=True)
        await show_buttons_menu(update, context)
        return

    text = "选择要操作的按钮:\n\n"
    keyboard = []

    for i, btn in enumerate(buttons, 1):
        prefix = "✏️ " if edit_mode else "🗑 "
        action = f"ad:button:edit:{btn.id}" if edit_mode else f"ad:button:delete:{btn.id}"
        keyboard.append([InlineKeyboardButton(f"{prefix}{btn.button_text}", callback_data=action)])

    keyboard.append([InlineKeyboardButton("← 返回", callback_data="ad:buttons")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_edit_button_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, button_id: int) -> None:
    """
    显示编辑按钮菜单
    """
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        buttons = await AdService.get_ad_buttons(db, bot_id)
        button = next((b for b in buttons if b.id == button_id), None)

    if not button:
        await query.answer("按钮不存在", show_alert=True)
        await show_buttons_menu(update, context)
        return

    text = f"编辑按钮\n\n"
    text += f"当前名称: {html.escape(button.button_text)}\n"
    text += f"当前链接: {html.escape(button.button_url)}"

    keyboard = [
        [
            InlineKeyboardButton("✏️ 修改名称", callback_data=f"ad:button:edit:{button_id}:text"),
            InlineKeyboardButton("🔗 修改链接", callback_data=f"ad:button:edit:{button_id}:link"),
        ],
        [
            InlineKeyboardButton("← 返回", callback_data="ad:button:edit:list"),
        ],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_delete_button_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, button_id: int) -> None:
    """
    显示删除按钮确认
    """
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        buttons = await AdService.get_ad_buttons(db, bot_id)
        button = next((b for b in buttons if b.id == button_id), None)

    if not button:
        await query.answer("按钮不存在", show_alert=True)
        await show_buttons_menu(update, context)
        return

    text = f"确定删除这个按钮吗？\n\n按钮: {html.escape(button.button_text)}"

    keyboard = [
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"ad:button:delete:{button_id}:confirm"),
            InlineKeyboardButton("❌ 取消", callback_data="ad:button:delete:list"),
        ],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_clear_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    显示清空广告确认
    """
    query = update.callback_query

    text = "确定删除所有广告内容吗？\n\n这将删除所有广告设置"

    keyboard = [
        [
            InlineKeyboardButton("✅ 确认删除", callback_data="ad:clear:confirm"),
            InlineKeyboardButton("❌ 取消", callback_data="ad:show"),
        ],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def clear_all_ads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    清空所有广告
    """
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        await AdService.delete_all_ads(db, bot_id)

    await query.answer("已清空")
    await show_ad_main_menu(update, context)


async def preview_ad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """预览广告效果。"""
    query = update.callback_query
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        settings = await AdService.get_or_create_settings(db, bot_id)
        buttons = await AdService.get_ad_buttons(db, bot_id)

    text = "👀 广告预览\n\n"
    keyboard = []

    if settings.enabled:
        if settings.header_text:
            text += f"{settings.header_text}\n"
            if settings.header_link:
                text += f"🔗 {settings.header_link}\n"
            text += "\n"

        text += "--------------------\n"
        text += "💵 入款 100.00\n"
        text += "--------------------\n"

        if settings.footer_text:
            text += f"\n{settings.footer_text}\n"
            if settings.footer_link:
                text += f"🔗 {settings.footer_link}\n"

        for btn in buttons:
            keyboard.append([InlineKeyboardButton(btn.button_text, url=AdService.format_url_for_tg(btn.button_url))])
    else:
        text += "当前广告位未开启。"

    keyboard.append([InlineKeyboardButton("← 返回设置页", callback_data="ad:show")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

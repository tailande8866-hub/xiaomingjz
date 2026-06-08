"""
菜单按钮回调处理器
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

logger = logging.getLogger(__name__)

SETTINGS_OWNER_ONLY_CALLBACKS = {
    "topic:show",
    "botjoin:show",
    "timed:show",
    "ad:show",
    "admin:show",
    "admin:add:start",
    "auth:group:show",
    "broadcast_users:show",  # 🆕 广播用户
    "show_broadcast",  # 🆕 群发广播
    "welcome:show",  # 🆕 入群欢迎
    "keyword:show",  # 🆕 关键词
}

# 🆕 试用版禁用的功能回调
TRIAL_DISABLED_CALLBACKS = {
    "topic:show",
    "botjoin:show",
    "timed:show",
    "ad:show",
    "broadcast_users:show",
    "show_broadcast",
    "welcome:show",
    "keyword:show",
}

SETTINGS_ADMIN_ALLOWED_CALLBACKS = {
    "mygroups:show",
    "broadcast_users:show",
    "show_broadcast",
    "daycut:show",
    "display:show",
    "showname:show",
    "welcome:show",
    "keyword:show",
    "rename:show",
    "v1:group:manage",
}

SETTINGS_TOP_LEVEL_PREFIXES = (
    "mygroups:show",
    "broadcast_users:show",
    "show_broadcast",
    "v1:group:manage",
    "botjoin:show",
    "topic:show",
    "daycut:show",
    "display:show",
    "showname:show",
    "welcome:show",
    "keyword:show",
    "rename:show",
    "timed:show",
    "ad:show",
    "admin:show",
    "admin:add:start",
    "auth:group:show",
)

RETURN_NAVIGATION_CALLBACKS = {
    "settings:main",
    "settings_back",
    "menu_back",
    "menu:close",
    "back_to_main_menu",
    "back_to_group_manage",
    "daycut:show",
    "display:show",
    "showname:show",
    "welcome:show",
    "keyword:show",
    "admin:show",
    "auth:group:show",
    "mygroups:show",
    "botjoin:show",
    "topic:show",
    "timed:show",
    "ad:show",
}


def _is_return_navigation_callback(callback_data: str) -> bool:
    if callback_data in RETURN_NAVIGATION_CALLBACKS:
        return True
    return callback_data.startswith((
        "group_tag_detail_",
        "group_tag_manage_",
        "mygroups:page:",
        "mygroups:detail:",
        "timedmsg:mode:",
        "timedmsg:groups:",
        "timedmsg:global:",
        "timedmsg:group:",
    ))


# 🆕 检查是否是试用版用户
async def _check_trial_restriction(query, context, callback_data: str) -> bool:
    """
    检查试用版用户是否被限制使用某功能
    返回 True 表示允许使用，False 表示已限制并提示用户
    """
    # 检查是否是禁用功能
    is_disabled = False
    for disabled in TRIAL_DISABLED_CALLBACKS:
        if callback_data == disabled or callback_data.startswith(disabled.replace(":show", "")):
            is_disabled = True
            break

    if not is_disabled:
        return True

    from ..utils.bot_id_middleware import get_current_bot_id
    from ..services.account_status_service import account_status_service

    bot_id = get_current_bot_id(context)
    user_id = query.from_user.id
    account_status = await account_status_service.resolve(user_id, bot_id)

    if account_status.is_trial:
        await query.answer(
            "⚠️ 当前为试用版，暂不可使用该功能。升级全功能版解锁。",
            show_alert=True
        )
        return False

    return True

from ..models import Group, UserConfig, Transaction, get_db
from ..services.billing_service import BillingService
from ..utils.formatter import Formatter
from .operator import is_operator

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理主菜单按钮点击"""
    query = update.callback_query
    
    if not query or not query.message or not query.message.chat:
        return
    
    await query.answer()
    
    callback_data = query.data
    chat_id = query.message.chat.id
    user = query.from_user
    
    if callback_data == "menu_add":
        await _handle_menu_add(query)
    elif callback_data == "menu_query":
        await _handle_menu_query(query)
    elif callback_data == "menu_settings":
        await _show_settings_main(query, context)
    elif callback_data == "menu_help":
        await _handle_menu_help(query)
    elif callback_data == "menu_broadcast_users":
        await _show_broadcast_users_page(query, context)

async def _handle_menu_add(query):
    """处理'记一笔'按钮 - 显示快捷操作面板"""
    keyboard = [
        [InlineKeyboardButton("💵 快速入款 +100", callback_data="quick_deposit_100")],
        [InlineKeyboardButton("💵 快速入款 +500", callback_data="quick_deposit_500")],
        [InlineKeyboardButton("💵 快速入款 +1000", callback_data="quick_deposit_1000")],
        [InlineKeyboardButton("💸 快速下发 50", callback_data="quick_withdraw_50")],
        [InlineKeyboardButton("💸 快速下发 100", callback_data="quick_withdraw_100")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "💰 **快速记账**\n\n"
        "点击上方按钮可快速记账到当前用户\n\n"
        "💡 **手动记账格式：**\n"
        "• `+金额` - 给自己入款\n"
        "• `@用户名+金额` - 给指定用户入款\n"
        "• `下发金额` - 给自己下发\n"
        "• `@用户名下发金额` - 给指定用户下发"
    )
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def _handle_menu_query(query):
    """处理'账单查询'按钮"""
    keyboard = [
        [InlineKeyboardButton("📋 今日账单", callback_data="query_today")],
        [InlineKeyboardButton("👤 我的账单", callback_data="query_mine")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "📊 **账单查询**\n\n请选择要查询的内容："
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def _handle_menu_help(query):
    """处理"使用帮助"按钮"""
    text = (
        "📖 **使用帮助**\n\n"
        "**基础命令：**\n"
        "• `/start` - 开始记账\n"
        "• `上课` / `下课` - 开启/关闭禁言模式\n\n"
        "**记账操作：**\n"
        "• `+金额` - 入款\n"
        "• `用户名+金额` - 指定用户入款\n"
        "• `下发金额` - 下发\n"
        "• `用户名下发金额` - 指定用户下发\n\n"
        "**账单查询：**\n"
        "• `显示账单` - 查看今日账单\n"
        "• `我` - 查看我的账单\n\n"
        "**其他功能：**\n"
        "• `h0` - 查询火币C2C价格\n"
        "• `b0` - 查询币安C2C价格\n"
        "• `计算表达式` - 计算器功能\n\n"
        "如有问题请联系管理员。"
    )
    await query.edit_message_text(text, parse_mode="Markdown")

async def handle_sub_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理子菜单按钮点击
    
    使用新的 callback_data 格式：module:action
    例如：daycut:show, daycut:set:08:00, settings:main
    """
    query = update.callback_query

    if not query or not query.message or not query.message.chat:
        return

    print(
        "[BOT_MANAGE]",
        query.data,
        update.effective_user.id if update.effective_user else None
    )

    callback_data = query.data
    wrapped_settings_callback = False
    if callback_data and callback_data.startswith("s:"):
        wrapped_settings_callback = True
        from ..utils.settings_guard import (
            EXPIRED_MESSAGE,
            guard_settings_callback,
            unwrap_settings_callback,
        )

        callback_data, _, is_valid = unwrap_settings_callback(context, callback_data)
        if not is_valid:
            await query.answer(EXPIRED_MESSAGE, show_alert=True)
            return

        if not await guard_settings_callback(query, context, callback_data):
            return

        if _is_return_navigation_callback(callback_data):
            _clear_settings_feature_states(context)

        if callback_data.startswith(SETTINGS_TOP_LEVEL_PREFIXES):
            if not await _check_settings_feature_permission(update, query, context, callback_data):
                return
            _clear_settings_feature_states(context)

        if callback_data.startswith("v1:"):
            from ..core.runtime_router import runtime_router
            context.user_data["_settings_unwrapped_callback_data"] = callback_data
            try:
                await runtime_router.handle_update(update, context)
            finally:
                context.user_data.pop("_settings_unwrapped_callback_data", None)
            return

        if callback_data.startswith(("mygroups:", "botjoin:", "topic:", "topic_cs:", "timed:", "timedmsg:")):
            # 🆕 试用版限制检查
            if callback_data.startswith(("topic:", "botjoin:", "timed:")):
                if not await _check_trial_restriction(query, context, callback_data):
                    return
            from . import bot_group_features
            context.user_data["_settings_unwrapped_callback_data"] = callback_data
            try:
                await bot_group_features.handle_callback(update, context)
            finally:
                context.user_data.pop("_settings_unwrapped_callback_data", None)
            return

        if callback_data.startswith("ad:"):
            # 🆕 试用版限制检查
            if callback_data == "ad:show" or callback_data.startswith("ad:enable"):
                if not await _check_trial_restriction(query, context, "ad:show"):
                    return
            from .ad_handler import handle_ad_callback
            context.user_data["_settings_unwrapped_callback_data"] = callback_data
            try:
                await handle_ad_callback(update, context)
            finally:
                context.user_data.pop("_settings_unwrapped_callback_data", None)
            return

        if callback_data == "show_broadcast" or callback_data.startswith("broadcast_target_") or callback_data in {
            "broadcast_start_input",
            "broadcast_cancel",
            "broadcast_forward",
            "broadcast_send",
        }:
            from . import menu_callbacks
            context.user_data["_settings_unwrapped_callback_data"] = callback_data
            try:
                await menu_callbacks.handle_broadcast_callback(update, context)
            finally:
                context.user_data.pop("_settings_unwrapped_callback_data", None)
            return

    if callback_data.startswith(("mygroups:", "botjoin:", "topic:", "topic_cs:", "timed:", "timedmsg:")):
        if _is_return_navigation_callback(callback_data):
            _clear_settings_feature_states(context)
        if callback_data.startswith(("topic:", "botjoin:", "timed:")):
            if not await _check_trial_restriction(query, context, callback_data):
                return
        from . import bot_group_features
        context.user_data["_settings_unwrapped_callback_data"] = callback_data
        try:
            await bot_group_features.handle_callback(update, context)
        finally:
            context.user_data.pop("_settings_unwrapped_callback_data", None)
        return

    if callback_data.startswith("ad:"):
        if _is_return_navigation_callback(callback_data):
            _clear_settings_feature_states(context)
        if callback_data == "ad:show" or callback_data.startswith("ad:enable"):
            if not await _check_trial_restriction(query, context, "ad:show"):
                return
        from .ad_handler import handle_ad_callback
        context.user_data["_settings_unwrapped_callback_data"] = callback_data
        try:
            await handle_ad_callback(update, context)
        finally:
            context.user_data.pop("_settings_unwrapped_callback_data", None)
        return

    if not wrapped_settings_callback:
        await query.answer()

    chat_id = query.message.chat.id
    user = query.from_user

    # ==================== 机器人状态管理面板 ====================
    if callback_data.startswith("bot_mgmt"):
        """机器人状态管理面板回调"""
        import logging
        logger = logging.getLogger(__name__)
        bot_id = context.bot_data.get("bot_id", "unknown")
        logger.info(f"[CALLBACK] bot_mgmt: callback_data={callback_data}, user_id={user.id if user else 'N/A'}, bot_id={bot_id}")
        
        from .bot_management_handler import handle_bot_management_callback
        await handle_bot_management_callback(update, context)
        return

    # 权限检查
    from ..utils.role_checker import get_user_role, UserRole
    from ..utils.permission_checker import PermissionChecker

    bot_id = None
    try:
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
    except Exception:
        pass

    user_role = await get_user_role(user.id, bot_id=bot_id)

    # ==================== 试用申请 ====================
    if callback_data == "trial:apply":
        """处理立即申请试用按钮"""
        await _handle_trial_apply(query, context)

    # ==================== 购买套餐 ====================
    elif callback_data == "billing:self_renew":
        """处理直接购买套餐按钮"""
        await _handle_billing_self_renew(query, context)

    # ==================== 联系客服 ====================
    elif callback_data == "contact:support":
        """处理联系客服咨询按钮"""
        await _handle_contact_support(query, context)

    # ==================== 旧格式回调兼容 ====================
    elif callback_data == "menu_back":
        await _show_settings_main(query, context)

    elif callback_data.startswith("quick_deposit_"):
        # 快速入款
        amount = int(callback_data.split("_")[-1])
        await _handle_quick_deposit(query, context, amount)

    elif callback_data.startswith("quick_withdraw_"):
        # 快速下发
        amount = int(callback_data.split("_")[-1])
        await _handle_quick_withdraw(query, context, amount)

    elif callback_data.startswith("query_"):
        # 账单查询
        if callback_data == "query_today":
            await _handle_query_today(query, context)
        elif callback_data == "query_mine":
            await _handle_query_mine(query, context)









    # 删除菜单
    elif callback_data == "delete_menu":
        await _handle_delete_menu(query, context)

    # 导出账单
    elif callback_data == "export_bills":
        await _handle_export_bills(query, context)

    # ==================== 新格式回调：module:action ====================
    # 返回主菜单
    elif callback_data == "settings:main":
        _clear_settings_feature_states(context)
        await _show_settings_main(query, context)

    elif callback_data == "settings_back":
        _clear_settings_feature_states(context)
        await _show_settings_main(query, context)

    elif callback_data in {
        "settings_daycut_toggle",
        "settings_welcome_toggle",
        "settings_keyword_toggle",
        "settings_keyword_manage",
        "admin_auth_groups_list",
    }:
        await query.answer("旧版设置入口已下线，请从功能设置页重新进入。", show_alert=True)
        _clear_settings_feature_states(context)
        await _show_settings_main(query, context)

    elif callback_data == "show_broadcast" or callback_data.startswith("broadcast_target_") or callback_data in {
        "broadcast_start_input",
        "broadcast_cancel",
        "broadcast_forward",
        "broadcast_send",
    }:
        from . import menu_callbacks
        await menu_callbacks.handle_broadcast_callback(update, context)

    # 关闭菜单
    elif callback_data == "menu:close":
        _clear_settings_feature_states(context)
        await _handle_delete_menu(query, context)

    # 日切设置 - 新版交互流程
    elif callback_data == "daycut:show":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        # 清除临时状态
        context.user_data.pop('daycut_temp_hour', None)
        await _show_daycut_page(query, context)

    elif callback_data == "daycut:select_time":
        """点击选择时间按钮，显示时间选择子菜单"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_daycut_time_selector(query, context)

    elif callback_data.startswith("daycut:preview:"):
        """选择时间后预览，不直接保存"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        time_str = callback_data.removeprefix("daycut:preview:")
        hour = int(time_str.split(":")[0])
        # 保存临时选择的时间
        context.user_data['daycut_temp_hour'] = hour
        await _show_daycut_page(query, context)

    elif callback_data == "daycut:save_confirm":
        """显示保存确认对话框"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_daycut_save(query, context)

    elif callback_data == "daycut:save":
        """确认保存日切设置"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_daycut_save(query, context)

    elif callback_data == "daycut:disable_confirm":
        """显示关闭日切确认对话框"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_daycut_disable_confirm(query, context)

    elif callback_data == "daycut:disable":
        """确认关闭日切"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_daycut_disable(query, context)

    elif callback_data == "daycut:enable_confirm":
        """显示开启日切确认对话框"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_daycut_enable_confirm(query, context)

    elif callback_data == "daycut:enable":
        """确认开启日切"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_daycut_enable(query, context)

    # 记账条数设置 - 新版交互流程
    elif callback_data == "display:show":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_display_page(query, context)

    elif callback_data == "display:select_deposit":
        """显示入款条数选择器"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_display_deposit_selector(query, context)

    elif callback_data == "display:select_withdraw":
        """显示下发条数选择器"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_display_withdraw_selector(query, context)

    elif callback_data.startswith("display:preview_deposit:"):
        """预览入款条数选择"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        count = int(callback_data.split(":")[-1])
        context.user_data['display_temp_deposit'] = count
        await _show_display_page(query, context)

    elif callback_data.startswith("display:preview_withdraw:"):
        """预览下发条数选择"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        count = int(callback_data.split(":")[-1])
        context.user_data['display_temp_withdraw'] = count
        await _show_display_page(query, context)

    elif callback_data == "display:save_confirm":
        """显示保存确认对话框"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_display_save(query, context)

    elif callback_data == "display:save":
        """确认保存记账条数设置"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_display_save(query, context)

    # 记账成员名字显示设置 - 开关按钮式交互
    elif callback_data == "showname:show":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_showname_page_v2(query, context)

    elif callback_data == "showname:toggle:deposit":
        """切换入款名字显示状态（临时）"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        # 切换临时状态
        current = context.user_data.get('temp_deposit_name', True)
        context.user_data['temp_deposit_name'] = not current
        # 刷新页面
        await _show_showname_page_v2(query, context)
    elif callback_data == "showname:toggle:withdraw":
        """切换下发名字显示状态（临时）"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        # 切换临时状态
        current = context.user_data.get('temp_withdraw_name', True)
        context.user_data['temp_withdraw_name'] = not current
        # 刷新页面
        await _show_showname_page_v2(query, context)

    elif callback_data == "showname:save:v2":
        """保存记账成员名字显示设置"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_showname_save_v2(query, context)

    # 欢迎语设置
    elif callback_data == "welcome:show":
        # 🆕 试用版限制检查
        if not await _check_trial_restriction(query, context, callback_data):
            return
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_welcome_page(query, context)

    elif callback_data == "welcome:enable":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_welcome_enable(query, context)

    elif callback_data == "welcome:disable":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_welcome_disable(query, context)

    elif callback_data.startswith("welcome:delete:"):
        """设置删除消息时间"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        minutes = int(callback_data.split(":")[-1])
        await _handle_welcome_delete_minutes(query, context, minutes)

    elif callback_data == "welcome:delete_prev":
        """切换删除上一条消息"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_welcome_delete_prev(query, context)

    elif callback_data == "welcome:noop":
        await query.answer()

    elif callback_data == "welcome:edit_media":
        """编辑媒体"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_welcome_edit_media(query, context)

    elif callback_data == "welcome:edit_buttons":
        """编辑按钮"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_welcome_edit_buttons(query, context)

    elif callback_data == "welcome:edit_text":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_welcome_edit_text(query, context)

    elif callback_data == "welcome:cancel_edit":
        await _handle_welcome_cancel_edit(query, context)

    elif callback_data == "welcome:preview":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_welcome_preview(query, context)

    # 关键词设置
    elif callback_data == "keyword:show":
        # 🆕 试用版限制检查
        if not await _check_trial_restriction(query, context, callback_data):
            return
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _show_keyword_page(query, context)

    elif callback_data == "keyword:enable":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_keyword_enable(query, context)

    elif callback_data == "keyword:disable":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_keyword_disable(query, context)

    elif callback_data == "keyword:add":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_keyword_add(query, context)

    elif callback_data == "keyword:cancel_add":
        await _handle_keyword_cancel_add(query, context)

    elif callback_data == "keyword:list":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        await _handle_keyword_list(query, context)

    elif callback_data.startswith("keyword:delete:"):
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN], "管理员"):
            return
        keyword = callback_data.split(":")[-1]
        await _handle_keyword_delete(query, context, keyword)

    # 管理员管理 - 新版交互流程
    elif callback_data == "admin:show":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_admin_page(query, context)

    elif callback_data == "admin:add:start":
        """开始添加管理员"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_admin_add_start(query, context)

    elif callback_data == "admin:add_confirm":
        """确认添加管理员（简化版，只有管理员一个角色）"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _handle_admin_add(query, context, is_super_admin=False)

    elif callback_data == "admin:delete:list":
        """显示删除管理员列表"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_admin_delete_list(query, context)

    elif callback_data.startswith("admin:delete_confirm:"):
        """显示删除管理员确认"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        admin_user_id = int(callback_data.split(":")[-1])
        await _show_admin_delete_confirm(query, context, admin_user_id)

    elif callback_data.startswith("admin:delete:"):
        """确认删除管理员"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        admin_user_id = int(callback_data.split(":")[-1])
        await _handle_admin_delete(query, context, admin_user_id)

    # 授权群组管理 - 新版交互流程
    elif callback_data == "auth:group:show":
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_auth_group_page(query, context)

    elif callback_data == "authgroup:add:start":
        """开始手动授权群组"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_authgroup_add_start(query, context)

    elif callback_data == "authgroup:add_confirm":
        """确认授权群组"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _handle_authgroup_add(query, context)

    elif callback_data == "authgroup:remove:list":
        """显示移除授权群组列表"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_authgroup_remove_list(query, context)

    elif callback_data.startswith("authgroup:remove_confirm:"):
        """显示移除授权群组确认"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        group_id = int(callback_data.split(":")[-1])
        await _show_authgroup_remove_confirm(query, context, group_id)

    elif callback_data.startswith("authgroup:remove:"):
        """确认移除授权群组"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        group_id = int(callback_data.split(":")[-1])
        await _handle_authgroup_remove(query, context, group_id)

    elif callback_data.startswith("authgroup:page:"):
        """分页翻页"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        parts = callback_data.split(":")
        page = int(parts[2])
        show_authorized = parts[3] == "True" if len(parts) > 3 else True
        await _show_auth_group_page(query, context, page, show_authorized)

    elif callback_data == "authgroup:noop":
        """无操作（用于禁用状态的翻页按钮）"""
        await query.answer("已经是第一页/最后一页了", show_alert=False)

    elif callback_data.startswith("authgroup:switch:"):
        """切换已授权/未授权列表"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        show_authorized = callback_data.split(":")[-1] == "True"
        await _show_auth_group_page(query, context, 1, show_authorized)

    elif callback_data.startswith("authgroup:confirm:"):
        """显示单个群组授权/取消授权确认"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        parts = callback_data.split(":")
        group_id = int(parts[2])
        action = parts[3]  # 'authorize' 或 'unauthorize'
        await _show_authgroup_group_confirm(query, context, group_id, action)

    elif callback_data.startswith("authgroup:do_authorize:"):
        """确认授权单个群组"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        group_id = int(callback_data.split(":")[-1])
        await _handle_authgroup_authorize(query, context, group_id)

    elif callback_data.startswith("authgroup:do_unauthorize:"):
        """确认取消授权单个群组"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        group_id = int(callback_data.split(":")[-1])
        await _handle_authgroup_unauthorize(query, context, group_id)

    elif callback_data == "authgroup:batch_authorize_confirm":
        """显示批量授权确认"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_authgroup_batch_confirm(query, context, 'authorize')

    elif callback_data == "authgroup:batch_unauthorize_confirm":
        """显示批量取消授权确认"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _show_authgroup_batch_confirm(query, context, 'unauthorize')

    elif callback_data == "authgroup:batch_do_authorize":
        """批量授权当前页"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _handle_authgroup_batch_authorize(query, context)

    elif callback_data == "authgroup:batch_do_unauthorize":
        """批量取消授权当前页"""
        if not await _check_permission_and_show_denied(query, context,
            [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER], "Bot创建者"):
            return
        await _handle_authgroup_batch_unauthorize(query, context)

    # 更名检测提醒（所有用户可用）
    elif callback_data == "rename:show":
        """显示群组&成员设置页面"""
        await _show_group_member_settings_page(query, context)

    elif callback_data.startswith("groupmember:toggle:"):
        """切换群组&成员设置功能开关"""
        config_key = callback_data.split(":")[-1] + "_enabled"
        await _handle_groupmember_toggle(query, context, config_key)

    # ==================== 广播用户功能 ====================
    # 广播用户主页面
    elif callback_data == "broadcast_users:show":
        # 🆕 试用版限制检查
        if not await _check_trial_restriction(query, context, callback_data):
            return
        await _show_broadcast_users_page(query, context)

    # 广播用户模式选择
    elif callback_data.startswith("broadcast_users:mode:"):
        # 🆕 试用版限制检查
        if not await _check_trial_restriction(query, context, "broadcast_users:show"):
            return
        mode = callback_data.split(":")[-1]
        await _handle_broadcast_users_mode_select(query, context, mode)

    # 广播用户确认发送
    elif callback_data == "broadcast_users:confirm":
        # 🆕 试用版限制检查
        if not await _check_trial_restriction(query, context, "broadcast_users:show"):
            return
        await _handle_broadcast_users_confirm(query, context)

    # 广播用户取消
    elif callback_data == "broadcast_users:cancel":
        await _handle_broadcast_users_cancel(query, context)

    # 广播用户终止发送
    elif callback_data == "broadcast_users:stop":
        context.user_data['broadcast_users_stop'] = True
        await query.answer("⛔ 正在终止发送...", show_alert=False)

    # ==================== 超级管理员功能 ====================
    elif callback_data.startswith("sa:"):
        """超管功能回调"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[CALLBACK] sa: callback_data={callback_data}, user_id={user.id}, chat_id={chat_id}")
        
        from .super_admin_v2_handler import show_message_center, show_super_admin_panel

        if callback_data == "sa:message_center":
            logger.info(f"[CALLBACK] Calling show_message_center")
            await show_message_center(update, context)
        elif callback_data == "sa:panel":
            logger.info(f"[CALLBACK] Calling show_super_admin_panel")
            await show_super_admin_panel(update, context)
        else:
            logger.info(f"[CALLBACK] Unknown sa: callback, redirecting to panel")
            await query.answer("该超管功能正在整理中，请先返回面板。", show_alert=True)
            await show_super_admin_panel(update, context)

async def _show_main_menu(query, context):
    """显示主菜单"""
    keyboard = [
        [InlineKeyboardButton("💰 快速记账", callback_data="menu_add")],
        [InlineKeyboardButton("📊 账单查询", callback_data="menu_query")],
        [InlineKeyboardButton("⚙️ 系统设置", callback_data="menu_settings")],
        [InlineKeyboardButton("📖 使用帮助", callback_data="menu_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🎉 **欢迎使用记账机器人**\n\n请选择以下功能："
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def _handle_quick_deposit(query, context, amount):
    """处理快速入款"""
    chat_id = query.message.chat.id
    user = query.from_user
    
    # 模拟发送消息触发入款
    from telegram import Message
    fake_message = Message(
        message_id=query.message.message_id,
        date=query.message.date,
        chat=query.message.chat,
        from_user=user,
        text=f"+{amount}"
    )
    
    # 导入 billing handler
    from . import billing
    
    # 创建假的 update 对象
    class FakeUpdate:
        def __init__(self):
            self.message = fake_message
            self.effective_chat = chat_id
            self.effective_user = user
    
    fake_update = FakeUpdate()
    
    try:
        await billing.handle_deposit(fake_update, context)
        await query.edit_message_text(f"✅ 已成功入款 {amount}")
    except Exception as e:
        await query.edit_message_text(f"❌ 入款失败：{str(e)}")

async def _handle_quick_withdraw(query, context, amount):
    """处理快速下发"""
    chat_id = query.message.chat.id
    user = query.from_user
    
    # 模拟发送消息触发下发
    from telegram import Message
    fake_message = Message(
        message_id=query.message.message_id,
        date=query.message.date,
        chat=query.message.chat,
        from_user=user,
        text=f"下发{amount}"
    )
    
    # 导入 billing handler
    from . import billing
    
    # 创建假的 update 对象
    class FakeUpdate:
        def __init__(self):
            self.message = fake_message
            self.effective_chat = chat_id
            self.effective_user = user
    
    fake_update = FakeUpdate()
    
    try:
        await billing.handle_withdraw(fake_update, context)
        await query.edit_message_text(f"✅ 已成功下发 {amount}")
    except Exception as e:
        await query.edit_message_text(f"❌ 下发失败：{str(e)}")

async def _handle_query_today(query, context):
    """查询今日账单"""
    chat_id = query.message.chat.id
    
    # 导入 billing handler
    from . import billing
    
    # 创建假的 update 对象
    class FakeUpdate:
        def __init__(self):
            self.message = query.message
            self.effective_chat = chat_id
            self.effective_user = query.from_user
    
    fake_update = FakeUpdate()
    
    try:
        await billing.show_bills(fake_update, context)
    except Exception as e:
        await query.edit_message_text(f"❌ 查询失败：{str(e)}")

async def _handle_query_mine(query, context):
    """查询我的账单"""
    chat_id = query.message.chat.id
    user = query.from_user
    
    from . import billing
    
    class FakeUpdate:
        def __init__(self):
            self.message = query.message
            self.effective_chat = chat_id
            self.effective_user = user
    
    fake_update = FakeUpdate()
    
    try:
        await billing.show_my_bills(fake_update, context)
    except Exception as e:
        await query.edit_message_text(f"❌ 查询失败：{str(e)}")

async def _show_group_member_settings_page(query, context):
    """显示群组&成员设置页面（新版交互流程）

    页面展示：三个功能的当前状态、切换按钮、返回按钮
    """
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        # 获取三个功能的当前状态
        nickname_monitor = await global_config_service.get_config(db, bot_id, "nickname_monitor_enabled")
        username_monitor = await global_config_service.get_config(db, bot_id, "username_monitor_enabled")
        impersonation_detection = await global_config_service.get_config(db, bot_id, "impersonation_detection_enabled")

        # 转换为布尔值
        nickname_enabled = nickname_monitor if isinstance(nickname_monitor, bool) else False
        username_enabled = username_monitor if isinstance(username_monitor, bool) else False
        impersonation_enabled = impersonation_detection if isinstance(impersonation_detection, bool) else False

        # 状态文字
        nickname_status = "✅ 已开启" if nickname_enabled else "❌ 已关闭"
        username_status = "✅ 已开启" if username_enabled else "❌ 已关闭"
        impersonation_status = "✅ 已开启" if impersonation_enabled else "❌ 已关闭"

        text = (
            f"👥 <b>群组&成员设置</b>\n\n"
            f"当前配置：\n"
            f"监听昵称变更：{nickname_status}\n"
            f"监听用户名变更：{username_status}\n"
            f"冒充管理员监测：{impersonation_status}\n\n"
            f"👇 功能开关："
        )

        # 构建按钮
        keyboard = [
            [InlineKeyboardButton(f"{'✅ ' if nickname_enabled else ''}监听昵称变更", callback_data="groupmember:toggle:nickname_monitor")],
            [InlineKeyboardButton(f"{'✅ ' if username_enabled else ''}监听用户名变更", callback_data="groupmember:toggle:username_monitor")],
            [InlineKeyboardButton(f"{'✅ ' if impersonation_enabled else ''}冒充管理员监测", callback_data="groupmember:toggle:impersonation_detection")],
            [InlineKeyboardButton("🔙 返回设置", callback_data="settings:main")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def _show_group_member_page(query, context):
    """兼容 ui_schema_registry 的旧函数名。"""
    await _show_group_member_settings_page(query, context)

async def _handle_groupmember_toggle(query, context, config_key):
    """切换群组&成员设置功能开关"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        # 获取当前值
        current_value = await global_config_service.get_config(db, bot_id, config_key)
        current_bool = current_value if isinstance(current_value, bool) else False

        # 切换状态
        new_value = not current_bool

        # 保存新值
        await global_config_service.set_global_config(
            db, bot_id, config_key, new_value,
            description=f"群组&成员设置 - {config_key}",
            updated_by=query.from_user.id
        )

    # 功能名称映射
    feature_names = {
        "nickname_monitor_enabled": "监听昵称变更",
        "username_monitor_enabled": "监听用户名变更",
        "impersonation_detection_enabled": "冒充管理员监测"
    }
    feature_name = feature_names.get(config_key, config_key)
    status_text = "开启" if new_value else "关闭"

    await query.answer(f"✅ {feature_name}已{status_text}", show_alert=False)
    await _show_group_member_settings_page(query, context)

async def _show_settings_main(query, context):
    """兼容旧调用点，统一复用新的功能设置菜单渲染。"""
    from types import SimpleNamespace
    from .menu_callbacks import handle_settings

    update = SimpleNamespace(
        callback_query=query,
        message=None,
        effective_user=query.from_user,
    )
    await handle_settings(update, context)

def _clear_settings_feature_states(context):
    """清理功能设置相关的输入态和临时态。"""
    from ..utils.settings_guard import clear_edit_states
    from . import menu_callbacks

    clear_edit_states(context)
    _clear_broadcast_users_state(context)
    menu_callbacks._clear_broadcast_state(context)
    for key in (
        "waiting_for",
        "broadcast_users_stop",
        "broadcast_users_sending",
        "daycut_temp_hour",
        "display_temp_deposit",
        "display_temp_withdraw",
        "temp_deposit_name",
        "temp_withdraw_name",
        "_settings_unwrapped_callback_data",
        "_bot_id_override",
        "callback_params",
    ):
        context.user_data.pop(key, None)


async def _check_settings_feature_permission(update, query, context, callback_data: str) -> bool:
    """统一检查功能设置入口权限，权限不足时弹窗提示。"""
    from ..utils.settings_guard import LOCKED_FEATURE_MESSAGE
    from ..utils.role_checker import UserRole, get_user_role
    from ..utils.permission_checker import PermissionChecker

    bot_id = None
    try:
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
    except Exception:
        pass

    user_role = await get_user_role(query.from_user.id, bot_id=bot_id)
    if user_role in (UserRole.SUPER_ADMIN, UserRole.BOT_OWNER):
        return True

    # 普通用户、全局操作员、群组操作员统一禁止进入功能设置里的管理功能
    if user_role in (UserRole.NORMAL_USER, UserRole.GLOBAL_OPERATOR, UserRole.GROUP_OPERATOR):
        await query.answer(LOCKED_FEATURE_MESSAGE, show_alert=True)
        return False

    if callback_data in SETTINGS_OWNER_ONLY_CALLBACKS:
        await query.answer(LOCKED_FEATURE_MESSAGE, show_alert=True)
        return False

    if callback_data == "v1:group:manage":
        has_perm = await PermissionChecker.check_permission_and_alert(
            update,
            PermissionChecker.CAN_MANAGE_GROUPS,
            context=context,
        )
        return has_perm

    if callback_data in {"broadcast_users:show", "show_broadcast"}:
        has_perm = await PermissionChecker.check_permission_and_alert(
            update,
            PermissionChecker.CAN_BROADCAST,
            context=context,
        )
        return has_perm

    if callback_data in SETTINGS_ADMIN_ALLOWED_CALLBACKS:
        has_perm = await PermissionChecker.check_permission_and_alert(
            update,
            PermissionChecker.CAN_SETTINGS,
            context=context,
        )
        return has_perm

    return True

async def _check_permission_and_show_denied(query, context, required_roles, action_name):
    """检查权限，无权限时显示拒绝页面
    
    Args:
        query: 回调查询对象
        context: 上下文对象
        required_roles: 所需权限角色列表
        action_name: 操作名称（用于显示）
        
    Returns:
        bool: True表示有权限，False表示无权限
    """
    from ..utils.role_checker import get_user_role, UserRole
    from ..utils.bot_id_middleware import get_current_bot_id
    
    bot_id = None
    try:
        bot_id = get_current_bot_id(context)
    except Exception:
        pass
    
    user = query.from_user
    user_role = await get_user_role(user.id, bot_id=bot_id)
    
    # 检查是否有权限
    if user_role not in required_roles:
        from ..utils.settings_guard import LOCKED_FEATURE_MESSAGE
        await query.answer(LOCKED_FEATURE_MESSAGE, show_alert=True)
        return False
    
    return True

# 保留旧函数名以兼容现有代码
async def _handle_settings_back(query, context):
    """返回功能设置菜单（兼容旧代码）"""
    await _show_settings_main(query, context)

async def _handle_delete_menu(query, context):
    """删除菜单消息"""
    try:
        await query.message.delete()
    except Exception:
        pass

async def _show_daycut_page(query, context):
    """显示日切设置页面（新版交互流程）

    页面初始展示：状态、当前时间、生效群数量、选择时间按钮、关闭日切按钮、返回按钮
    """
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select, func
    from ..models.group import Group

    bot_id = get_current_bot_id(context)

    # 获取临时选择的时间（如果有）
    temp_hour = context.user_data.get('daycut_temp_hour')
    temp_selected = temp_hour is not None

    async with get_db_session() as db:
        # 获取当前日切配置
        day_cut_config = await global_config_service.get_config(db, bot_id, "day_cut_enabled")
        day_cut_time = await global_config_service.get_config(db, bot_id, "day_cut_time")

        # 获取授权群组数量
        group_count = 0
        try:
            result = await db.execute(
                select(func.count()).select_from(Group).where(Group.bot_id == bot_id)
            )
            group_count = result.scalar() or 0
        except Exception:
            pass

        is_enabled = day_cut_config if isinstance(day_cut_config, bool) else False
        saved_hour = day_cut_time if isinstance(day_cut_time, int) else 0

        # 如果有临时选择的时间，显示未保存状态
        if temp_selected:
            current_hour = temp_hour
            time_display = f"{current_hour:02d}:00（未保存）"
            status_text = "✅ 已启用" if is_enabled else "❌ 未启用"
        else:
            current_hour = saved_hour
            time_display = f"{current_hour:02d}:00"
            status_text = "✅ 已启用" if is_enabled else "❌ 未关闭"

        text = (
            f"📅 <b>全局日切设置</b>\n\n"
            f"状态：{status_text}\n"
            f"当前日切时间：{time_display}\n"
            f"应用到：{group_count} 个群组\n\n"
            f"请选择全局统一日切时间："
        )

        keyboard = []

        # 如果有临时选择的时间，显示保存按钮
        if temp_selected:
            keyboard.append([InlineKeyboardButton(f"⏱ 已选：{current_hour:02d}:00", callback_data="daycut:select_time")])
            keyboard.append([
                InlineKeyboardButton("✅ 保存并启用", callback_data="daycut:save"),
                InlineKeyboardButton("❌ 关闭日切", callback_data="daycut:disable_confirm")
            ])
        else:
            # 显示选择时间按钮
            if is_enabled:
                keyboard.append([InlineKeyboardButton(f"⏱ 已选：{current_hour:02d}:00", callback_data="daycut:select_time")])
            else:
                keyboard.append([InlineKeyboardButton("⏱ 选择时间", callback_data="daycut:select_time")])

            # 根据状态显示不同按钮
            if is_enabled:
                keyboard.append([
                    InlineKeyboardButton("✅ 保存并启用", callback_data="daycut:save"),
                    InlineKeyboardButton("❌ 关闭日切", callback_data="daycut:disable_confirm")
                ])
            else:
                keyboard.append([InlineKeyboardButton("✅ 重新开启", callback_data="daycut:enable_confirm")])

        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="settings:main")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_display_page(query, context):
    """显示记账条数设置页面（新版交互流程）

    页面初始展示：当前配置、设置入款/下发条数按钮、保存设置按钮、返回按钮
    """
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    # 获取临时选择的条数（如果有）
    temp_deposit = context.user_data.get('display_temp_deposit')
    temp_withdraw = context.user_data.get('display_temp_withdraw')

    async with get_db_session() as db:
        # 获取当前配置
        deposit_count = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_count = await global_config_service.get_config(db, bot_id, "withdraw_display_count")

        saved_deposit = deposit_count if isinstance(deposit_count, int) else 10
        saved_withdraw = withdraw_count if isinstance(withdraw_count, int) else 10

        # 使用临时值或保存值
        current_deposit = temp_deposit if temp_deposit is not None else saved_deposit
        current_withdraw = temp_withdraw if temp_withdraw is not None else saved_withdraw

        # 检查是否有未保存的更改
        has_unsaved = (temp_deposit is not None and temp_deposit != saved_deposit) or \
                      (temp_withdraw is not None and temp_withdraw != saved_withdraw)

        # 构建显示文本
        deposit_display = f"{current_deposit} 条"
        withdraw_display = f"{current_withdraw} 条"

        if has_unsaved:
            if temp_deposit is not None and temp_deposit != saved_deposit:
                deposit_display += "（未保存）"
            if temp_withdraw is not None and temp_withdraw != saved_withdraw:
                withdraw_display += "（未保存）"

        text = (
            f"📊 <b>全局记账条数设置</b>\n\n"
            f"当前配置：\n"
            f"入款显示条数：{deposit_display}\n"
            f"下发显示条数：{withdraw_display}\n\n"
            f"👇 分别设置入款和下发的全局显示条数"
        )

        keyboard = []

        # 设置条数按钮行
        deposit_label = f"⏱ 已选入款：{current_deposit}条 ▼" if temp_deposit is not None else f"⏱ 设置入款条数 ▼"
        withdraw_label = f"⏱ 已选下发：{current_withdraw}条 ▼" if temp_withdraw is not None else f"⏱ 设置下发条数 ▼"

        keyboard.append([
            InlineKeyboardButton(deposit_label, callback_data="display:select_deposit"),
            InlineKeyboardButton(withdraw_label, callback_data="display:select_withdraw")
        ])

        # 保存设置按钮
        keyboard.append([InlineKeyboardButton("✅ 保存设置", callback_data="display:save")])

        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="settings:main")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_welcome_page(query, context):
    """显示欢迎语设置页面 - 图2新样式"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        welcome_enabled = await global_config_service.get_config(db, bot_id, "welcome_ad_enabled")
        welcome_delete_prev = await global_config_service.get_config(db, bot_id, "welcome_delete_prev")
        welcome_delete_minutes = await global_config_service.get_config(db, bot_id, "welcome_delete_minutes")
        welcome_message = await global_config_service.get_config(db, bot_id, "welcome_message")
        welcome_has_media = await global_config_service.get_config(db, bot_id, "welcome_has_media")
        welcome_has_buttons = await global_config_service.get_config(db, bot_id, "welcome_has_buttons")

        is_enabled = welcome_enabled if isinstance(welcome_enabled, bool) else False
        delete_prev = welcome_delete_prev if isinstance(welcome_delete_prev, bool) else False
        delete_minutes = welcome_delete_minutes if isinstance(welcome_delete_minutes, int) else 0
        msg_text = welcome_message if isinstance(welcome_message, str) and welcome_message else "未设置"
        has_media = welcome_has_media if isinstance(welcome_has_media, bool) else False
        has_buttons = welcome_has_buttons if isinstance(welcome_has_buttons, bool) else False

        # 图2格式：进群欢迎
        text = (
            "🎉 <b>进群欢迎</b>\n\n"
            f"<b>状态：</b> {'关闭❌' if not is_enabled else '开启✅'}\n\n"
            f"<b>删除消息(分钟)：</b> "
        )
        
        if delete_minutes == 0 and not delete_prev:
            text += "不删除"
        elif delete_prev:
            text += "删除上一条"
        else:
            text += f"{delete_minutes}分钟"
        
        text += "\n\n"
        text += f"<b>自定义欢迎内容：</b>\n"
        text += f"️ 媒体图片：{'✅' if has_media else '❌'}\n"
        text += f"🔗 链接按钮：{'✅' if has_buttons else '❌'}\n"
        text += f"📄 文本内容：{'✅' if msg_text != '未设置' else '❌'}"

        keyboard = [
            # 状态切换行：状态： | 开启 | 关闭
            [
                InlineKeyboardButton("状态：", callback_data="welcome:noop"),
                InlineKeyboardButton("✅开启" if is_enabled else "开启", callback_data="welcome:enable"),
                InlineKeyboardButton("✅关闭" if not is_enabled else "关闭", callback_data="welcome:disable")
            ],
            # 否 | 1 | 5 | 10
            [
                InlineKeyboardButton(
                    "✅ 否" if delete_minutes == 0 and not delete_prev else "否",
                    callback_data="welcome:delete:0"
                ),
                InlineKeyboardButton(
                    "✅ 1" if delete_minutes == 1 and not delete_prev else "1",
                    callback_data="welcome:delete:1"
                ),
                InlineKeyboardButton(
                    "✅ 5" if delete_minutes == 5 and not delete_prev else "5",
                    callback_data="welcome:delete:5"
                ),
                InlineKeyboardButton(
                    "✅ 10" if delete_minutes == 10 and not delete_prev else "10",
                    callback_data="welcome:delete:10"
                )
            ],
            # ✅删除上一条
            [
                InlineKeyboardButton("✅删除上一条" if delete_prev else "删除上一条", callback_data="welcome:delete_prev")
            ],
            # 👀预览消息
            [
                InlineKeyboardButton("👀预览消息", callback_data="welcome:preview")
            ],
            # 📝修改文本 | 📷修改媒体
            [
                InlineKeyboardButton("📝修改文本", callback_data="welcome:edit_text"),
                InlineKeyboardButton("📷修改媒体", callback_data="welcome:edit_media")
            ],
            # 🔧修改按钮
            [
                InlineKeyboardButton("🔧修改按钮", callback_data="welcome:edit_buttons")
            ],
            # 返回
            [
                InlineKeyboardButton("🔙返回", callback_data="settings:main")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_welcome_enable(query, context):
    """启用欢迎语"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        await global_config_service.set_global_config(
            db, bot_id, "welcome_ad_enabled", True,
            description="全局入群欢迎语开关",
            updated_by=query.from_user.id
        )

    await query.answer("✅ 欢迎语已启用", show_alert=False)
    await _show_welcome_page(query, context)

async def _handle_welcome_disable(query, context):
    """禁用欢迎语"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        await global_config_service.set_global_config(
            db, bot_id, "welcome_ad_enabled", False,
            description="全局入群欢迎语开关",
            updated_by=query.from_user.id
        )

    await query.answer("✅ 欢迎语已禁用", show_alert=False)
    await _show_welcome_page(query, context)

async def _handle_welcome_delete_minutes(query, context, minutes: int):
    """设置删除消息时间"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        # 如果设置为0，同时关闭删除上一条
        if minutes == 0:
            await global_config_service.set_global_config(
                db, bot_id, "welcome_delete_prev", False,
                description="是否删除上一条欢迎消息",
                updated_by=query.from_user.id
            )
        
        await global_config_service.set_global_config(
            db, bot_id, "welcome_delete_minutes", minutes,
            description="欢迎消息删除时间（分钟）",
            updated_by=query.from_user.id
        )

    await query.answer(f"✅ 删除时间已设置为 {minutes} 分钟", show_alert=False)
    await _show_welcome_page(query, context)

async def _handle_welcome_delete_prev(query, context):
    """切换删除上一条消息"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        current = await global_config_service.get_config(db, bot_id, "welcome_delete_prev")
        new_value = not (current if isinstance(current, bool) else False)
        
        # 如果开启删除上一条，关闭定时删除
        if new_value:
            await global_config_service.set_global_config(
                db, bot_id, "welcome_delete_minutes", 0,
                description="欢迎消息删除时间（分钟）",
                updated_by=query.from_user.id
            )
        
        await global_config_service.set_global_config(
            db, bot_id, "welcome_delete_prev", new_value,
            description="是否删除上一条欢迎消息",
            updated_by=query.from_user.id
        )

    status = "开启" if new_value else "关闭"
    await query.answer(f"✅ 删除上一条已{status}", show_alert=False)
    await _show_welcome_page(query, context)

async def _handle_welcome_edit_media(query, context):
    """编辑媒体"""
    from ..utils.state_manager import set_edit_state, EDIT_STATE_WELCOME_MEDIA

    # 设置用户编辑状态
    await set_edit_state(context, EDIT_STATE_WELCOME_MEDIA)
    logger.info(f"[EDIT_MODE] Set edit_state for user {query.from_user.id} to {EDIT_STATE_WELCOME_MEDIA}, user_data={context.user_data}")

    text = (
        "📷 <b>编辑媒体</b>\n\n"
        "请直接发送媒体文件（图片/视频）：\n\n"
        "💡 提示：发送后会自动替换当前媒体"
    )

    keyboard = [
        [InlineKeyboardButton("返回", callback_data="welcome:show")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_welcome_edit_buttons(query, context):
    """编辑按钮"""
    from ..utils.state_manager import set_edit_state, EDIT_STATE_WELCOME_BUTTONS

    # 设置用户编辑状态
    await set_edit_state(context, EDIT_STATE_WELCOME_BUTTONS)
    logger.info(f"[EDIT_MODE] Set edit_state for user {query.from_user.id} to {EDIT_STATE_WELCOME_BUTTONS}, user_data={context.user_data}")

    text = (
        "🔧 <b>编辑按钮</b>\n\n"
        "请按照以下格式发送按钮配置：\n\n"
        "格式：按钮文字|链接URL\n"
        "示例：查看规则|https://example.com\n\n"
        "💡 提示：每行一个按钮，最多5个按钮"
    )

    keyboard = [
        [InlineKeyboardButton("返回", callback_data="welcome:show")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_welcome_edit_text(query, context):
    """进入编辑欢迎语模式"""
    from ..utils.state_manager import set_edit_state, EDIT_STATE_WELCOME_TEXT

    # 设置用户编辑状态
    await set_edit_state(context, EDIT_STATE_WELCOME_TEXT)
    logger.info(f"[EDIT_MODE] Set edit_state for user {query.from_user.id} to {EDIT_STATE_WELCOME_TEXT}, user_data={context.user_data}")

    text = (
        "✏️ <b>编辑欢迎语</b>\n\n"
        "请直接发送新的欢迎语内容：\n\n"
        "💡 <b>支持的变量：</b>\n"
        "• <code>@username</code> - 可点击的用户名（推荐）\n"
        "• <code>{username}</code> - 新用户用户名\n"
        "• <code>{group_name}</code> - 群组名称\n\n"
        "⚠️ 发送消息后将会自动保存"
    )

    keyboard = [[InlineKeyboardButton("❌ 取消", callback_data="welcome:cancel_edit")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_welcome_cancel_edit(query, context):
    """取消编辑欢迎语"""
    from ..utils.state_manager import clear_edit_state

    await clear_edit_state(context)
    await _show_welcome_page(query, context)

async def _handle_welcome_preview(query, context):
    """预览欢迎语效果"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    user = query.from_user

    async with get_db_session() as db:
        welcome_message = await global_config_service.get_config(db, bot_id, "welcome_message")
        msg_text = welcome_message if isinstance(welcome_message, str) and welcome_message else "欢迎 {username} 加入群组 🎉"

    # 替换变量进行预览
    preview_text = msg_text
    preview_text = preview_text.replace("@username", f"<a href='tg://user?id={user.id}'>{user.username or user.first_name or '新朋友'}</a>")
    preview_text = preview_text.replace("{username}", user.username or user.first_name or "新用户")
    preview_text = preview_text.replace("{group_name}", "示例群组")

    text = (
        f"👁 <b>欢迎语预览</b>\n\n"
        f"以下是欢迎语的显示效果：\n\n"
        f"───────────────\n"
        f"{preview_text}\n"
        f"───────────────\n\n"
        f"💡 实际发送时会替换为真实的用户名和群组名称"
    )

    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="welcome:show")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_keyword_page(query, context):
    """显示关键词设置页面 - 图1新样式"""
    from ..services.global_config_service import global_config_service
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        keyword_enabled = await global_config_service.get_config(db, bot_id, "keyword_reply_enabled")
        
        # 获取全局关键词列表（group_id=0）
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
        keyword_count = len(keywords)

        is_enabled = keyword_enabled if isinstance(keyword_enabled, bool) else True

        # 图1格式：关键词回复
        text = (
            f" <b>关键词回复</b>\n\n"
            f"已设置: <b>{keyword_count}</b> 条"
        )

        keyboard = [
            # 状态切换行：状态： | 开启 | ✅关闭
            [
                InlineKeyboardButton("状态：", callback_data="keyword:noop"),
                InlineKeyboardButton("开启", callback_data="keyword:enable"),
                InlineKeyboardButton("✅关闭" if is_enabled else "关闭", callback_data="keyword:disable")
            ],
            # 📝关键词列表
            [
                InlineKeyboardButton("📝关键词列表", callback_data="keyword:list")
            ],
            # 🔙返回
            [
                InlineKeyboardButton("🔙返回", callback_data="settings:main")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_keyword_enable(query, context):
    """启用关键词回复"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        await global_config_service.set_global_config(
            db, bot_id, "keyword_reply_enabled", True,
            description="全局关键词回复开关",
            updated_by=query.from_user.id
        )

    await query.answer("✅ 关键词回复已启用", show_alert=False)
    await _show_keyword_page(query, context)

async def _handle_keyword_disable(query, context):
    """禁用关键词回复"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        await global_config_service.set_global_config(
            db, bot_id, "keyword_reply_enabled", False,
            description="全局关键词回复开关",
            updated_by=query.from_user.id
        )

    await query.answer("✅ 关键词回复已禁用", show_alert=False)
    await _show_keyword_page(query, context)

async def _handle_keyword_add(query, context):
    """进入添加关键词模式"""
    from ..utils.state_manager import set_edit_state, EDIT_STATE_ADD_KEYWORD

    # 设置用户编辑状态
    await set_edit_state(context, EDIT_STATE_ADD_KEYWORD)

    text = (
        "➕ <b>添加关键词</b>\n\n"
        "请发送要添加的关键词：\n\n"
        "💡 <b>说明：</b>\n"
        "• 关键词将用于匹配用户消息\n"
        "• 匹配成功后会自动发送预设的回复\n"
        "• 下一步将要求您输入回复内容"
    )

    keyboard = [[InlineKeyboardButton("❌ 取消", callback_data="keyword:cancel_add")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_keyword_cancel_add(query, context):
    """取消添加关键词"""
    from ..utils.state_manager import clear_edit_state

    await clear_edit_state(context)
    await _show_keyword_page(query, context)

async def _handle_keyword_list(query, context):
    """显示关键词列表"""
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)

    if not keywords:
        text = (
            "📋 <b>关键词列表</b>\n\n"
            "暂无已配置的关键词\n\n"
            "💡 点击下方按钮添加关键词"
        )
    else:
        text = f"📋 <b>关键词列表</b>\n\n共 <b>{len(keywords)}</b> 个关键词：\n\n"

        for i, kw in enumerate(keywords, 1):
            reply_preview = kw.reply_text[:30] + "..." if len(kw.reply_text) > 30 else kw.reply_text
            text += f"{i}. <b>{kw.keyword}</b>\n   回复: {reply_preview}\n\n"

            # 限制显示数量
            if i >= 10:
                remaining = len(keywords) - 10
                if remaining > 0:
                    text += f"... 还有 {remaining} 个关键词\n"
                break

    keyboard = [
        [InlineKeyboardButton("➕ 添加关键词", callback_data="keyword:add")],
        [InlineKeyboardButton("🔙 返回", callback_data="keyword:show")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_keyword_delete(query, context, keyword: str):
    """删除关键词"""
    from ..services.custom_keyword_service import CustomKeywordService
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    success = await CustomKeywordService.delete_keyword(bot_id, keyword, group_id=0)

    if success:
        await query.answer(f"✅ 关键词「{keyword}」已删除", show_alert=False)
    else:
        await query.answer(f"❌ 删除失败", show_alert=False)

    await _handle_keyword_list(query, context)

async def _show_admin_page(query, context):
    """显示管理员管理页面（新版交互流程）- 简化版，只有管理员一个角色

    📌 重要说明：
    - 此页面只显示【已添加的管理员】（Admin表中的记录）
    - 【超级管理员】不在此列表中显示（通过配置SUPER_ADMIN_ID识别）
    - 超级管理员拥有所有权限，无需在此添加

    页面展示：管理员总数、管理员列表、操作按钮
    """
    from ..models import Admin, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        # 只查询已添加的管理员（不包括超级管理员）
        # 超级管理员通过配置识别，不存储在Admin表中
        result = await db.execute(
            select(Admin).where(Admin.bot_id == bot_id, Admin.is_active.is_(True))
        )
        admins = result.scalars().all()

        # 统计数量（只计算已添加的管理员）
        total_count = len(admins)

        text = (
            f"👥 <b>管理员管理</b>\n\n"
            f"当前管理员总数：{total_count} 人\n\n"
        )

        if admins:
            text += "👇 <b>管理员列表：</b>\n"
            for i, admin in enumerate(admins, 1):
                username = f"@{admin.username}" if admin.username else str(admin.user_id)
                text += f"{i}. {username}\n"
        else:
            text += "暂无管理员\n"

        text += "\n👇 选择操作："

        keyboard = [
            [
                InlineKeyboardButton("➕ 添加管理员", callback_data="admin:add:start"),
                InlineKeyboardButton("❌ 删除管理员", callback_data="admin:delete:list")
            ],
            [InlineKeyboardButton("🔙 返回设置", callback_data="settings:main")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_auth_group_page(query, context, page=1, show_authorized=True):
    """显示授权群组管理页面（新版交互流程，支持已授权/未授权切换和分页）

    页面展示：已授权/未授权数量、当前列表、操作按钮、快捷命令提示
    """
    from ..models import Group, get_db_session
    from ..models.enums import GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select, func, or_

    bot_id = get_current_bot_id(context)
    page_size = 5  # 每页显示5个群组

    async with get_db_session() as db:
        # 获取已授权群组数量（ACTIVE状态）
        authorized_count_result = await db.execute(
            select(func.count()).select_from(Group)
            .where(Group.bot_id == bot_id, Group.status == GroupStatus.ACTIVE)
        )
        authorized_count = authorized_count_result.scalar() or 0

        # 获取未授权群组数量（PENDING/UNAUTHORIZED/DISABLED/EXPIRED状态）
        unauthorized_count_result = await db.execute(
            select(func.count()).select_from(Group)
            .where(
                Group.bot_id == bot_id,
                or_(
                    Group.status == GroupStatus.PENDING,
                    Group.status == GroupStatus.UNAUTHORIZED,
                    Group.status == GroupStatus.DISABLED,
                    Group.status == GroupStatus.EXPIRED
                )
            )
        )
        unauthorized_count = unauthorized_count_result.scalar() or 0

        # 根据当前显示模式获取列表
        if show_authorized:
            # 已授权列表
            total_count = authorized_count
            base_query = select(Group).where(
                Group.bot_id == bot_id,
                Group.status == GroupStatus.ACTIVE
            )
            list_title = "✅ 已授权群组"
            batch_action_text = "❌ 取消当前页所有授权"
            batch_action_callback = "authgroup:batch_unauthorize_confirm"
        else:
            # 未授权列表
            total_count = unauthorized_count
            base_query = select(Group).where(
                Group.bot_id == bot_id,
                or_(
                    Group.status == GroupStatus.PENDING,
                    Group.status == GroupStatus.UNAUTHORIZED,
                    Group.status == GroupStatus.DISABLED,
                    Group.status == GroupStatus.EXPIRED
                )
            )
            list_title = "❌ 未授权群组"
            batch_action_text = "✅ 授权当前页所有群"
            batch_action_callback = "authgroup:batch_authorize_confirm"

        # 计算总页数
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))  # 确保页码在有效范围内

        # 获取当前页的群组
        offset = (page - 1) * page_size
        result = await db.execute(
            base_query
            .order_by(Group.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        groups = result.scalars().all()

        # 构建页面文本
        text = (
            f"🔐 <b>授权群组管理</b>\n\n"
            f"已授权：{authorized_count} 个 ｜ 未授权：{unauthorized_count} 个\n"
            f"当前：{list_title}  第 {page}/{total_pages} 页\n\n"
        )

        if groups:
            for i, group in enumerate(groups, offset + 1):
                group_name = group.group_name or f"群组 {group.group_id}"
                text += f"{i}. {group_name}\n"
        else:
            text += "暂无群组\n"

        # 构建键盘
        keyboard = []

        # 翻页按钮行
        prev_page = page - 1 if page > 1 else None
        next_page = page + 1 if page < total_pages else None

        pagination_row = []
        if prev_page:
            pagination_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"authgroup:page:{prev_page}:{show_authorized}"))
        else:
            pagination_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data="authgroup:noop"))

        if next_page:
            pagination_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"authgroup:page:{next_page}:{show_authorized}"))
        else:
            pagination_row.append(InlineKeyboardButton("➡️ 下一页", callback_data="authgroup:noop"))

        keyboard.append(pagination_row)

        # 批量操作按钮（仅当列表不为空时显示）
        if groups:
            keyboard.append([InlineKeyboardButton(batch_action_text, callback_data=batch_action_callback)])

        # 切换列表按钮
        if show_authorized:
            keyboard.append([
                InlineKeyboardButton("✅ 已授权群", callback_data="authgroup:noop"),
                InlineKeyboardButton("❌ 未授权群", callback_data="authgroup:switch:False")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("✅ 已授权群", callback_data="authgroup:switch:True"),
                InlineKeyboardButton("❌ 未授权群", callback_data="authgroup:noop")
            ])

        keyboard.append([InlineKeyboardButton("🔙 返回设置", callback_data="settings:main")])

        # 添加快捷命令提示
        text += (
            "\n💡 <b>快捷操作提示：</b>\n"
            "• 手动授权：<code>授权 群组ID</code>\n"
            "• 取消授权：<code>取消授权 群组ID</code>"
        )

        # 保存当前状态
        context.user_data['authgroup_current_page'] = page
        context.user_data['authgroup_show_authorized'] = show_authorized

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

# ==================== 管理员管理 - 新版交互流程 ====================

async def _show_admin_add_start(query, context):
    """开始添加管理员流程 - 简化版，直接添加为管理员"""
    text = (
        "➕ <b>添加管理员</b>\n\n"
        "请转发用户消息，或输入用户 ID / 用户名，添加为管理员。\n\n"
        "💡 提示：转发用户消息可以自动识别用户信息"
    )

    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="settings:main")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

    # 设置等待状态
    context.user_data['waiting_admin_add'] = True

async def _show_admin_role_select(query, context, user_id, username):
    """显示权限等级选择"""
    context.user_data['admin_add_user_id'] = user_id
    context.user_data['admin_add_username'] = username

    display_name = f"@{username}" if username else str(user_id)

    text = (
        f"➕ <b>添加管理员</b>\n\n"
        f"你要添加的用户：{display_name}（ID: {user_id}）\n\n"
        f"请选择权限等级："
    )

    keyboard = [
        [InlineKeyboardButton("🔹 普通管理员（仅能操作分配的功能）", callback_data="admin:add_role:normal")],
        [InlineKeyboardButton("🔹 超级管理员（可操作所有设置）", callback_data="admin:add_role:super")],
        [InlineKeyboardButton("❌ 取消", callback_data="admin:show")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_admin_add_confirm(query, context, is_super_admin):
    """显示添加管理员确认对话框"""
    user_id = context.user_data.get('admin_add_user_id')
    username = context.user_data.get('admin_add_username')

    if not user_id:
        await query.answer("❌ 用户信息丢失，请重新添加", show_alert=True)
        await _show_admin_page(query, context)
        return

    display_name = f"@{username}" if username else str(user_id)
    role_text = "超级管理员" if is_super_admin else "普通管理员"

    text = (
        f"➕ <b>确认添加管理员</b>\n\n"
        f"用户：{display_name}（ID: {user_id}）\n"
        f"权限：{role_text}\n\n"
        f"确定要添加吗？"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ 确认", callback_data=f"admin:add_confirm:{is_super_admin}"),
            InlineKeyboardButton("❌ 取消", callback_data="admin:show")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_admin_add(query, context, is_super_admin):
    """确认添加管理员"""
    from ..models import Admin, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    user_id = context.user_data.get('admin_add_user_id')
    username = context.user_data.get('admin_add_username')

    if not user_id:
        await query.answer("❌ 用户信息丢失", show_alert=True)
        await _show_admin_page(query, context)
        return

    async with get_db_session() as db:
        # 检查是否已存在
        from sqlalchemy import select
        result = await db.execute(
            select(Admin).where(Admin.bot_id == bot_id, Admin.user_id == user_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # 更新现有记录
            existing.is_active = True
            existing.can_manage_admins = is_super_admin
            existing.added_by = query.from_user.id
            existing.added_by_username = query.from_user.username
        else:
            # 创建新记录
            admin = Admin(
                bot_id=bot_id,
                user_id=user_id,
                username=username,
                is_active=True,
                can_manage_admins=is_super_admin,
                added_by=query.from_user.id,
                added_by_username=query.from_user.username
            )
            db.add(admin)

        await db.commit()

    # 清除临时状态
    context.user_data.pop('waiting_admin_add', None)
    context.user_data.pop('admin_add_user_id', None)
    context.user_data.pop('admin_add_username', None)

    display_name = f"@{username}" if username else str(user_id)

    await query.answer(f"✅ 用户 {display_name} 已添加为管理员", show_alert=True)
    await _show_admin_page(query, context)

async def _show_admin_delete_list(query, context):
    """显示删除管理员列表"""
    from ..models import Admin, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)
    current_user_id = query.from_user.id

    async with get_db_session() as db:
        result = await db.execute(
            select(Admin).where(Admin.bot_id == bot_id, Admin.is_active.is_(True))
        )
        admins = result.scalars().all()

        if not admins:
            await query.answer("⚠️ 暂无管理员可删除", show_alert=True)
            await _show_admin_page(query, context)
            return

        text = "❌ <b>删除管理员</b>\n\n请选择要删除的管理员：\n"

        keyboard = []
        for admin in admins:
            # 不能删除自己
            if admin.user_id == current_user_id:
                continue

            username = f"@{admin.username}" if admin.username else str(admin.user_id)
            role_text = "超级管理员" if admin.can_manage_admins else "普通管理员"
            keyboard.append([InlineKeyboardButton(f"{username} ({role_text})", callback_data=f"admin:delete_confirm:{admin.user_id}")])

        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin:show")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_admin_delete_confirm(query, context, admin_user_id):
    """显示删除管理员确认对话框"""
    from ..models import Admin, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        result = await db.execute(
            select(Admin).where(Admin.bot_id == bot_id, Admin.user_id == admin_user_id)
        )
        admin = result.scalar_one_or_none()

        if not admin:
            await query.answer("❌ 管理员不存在", show_alert=True)
            await _show_admin_page(query, context)
            return

        username = f"@{admin.username}" if admin.username else str(admin.user_id)

        text = (
            f"❌ <b>确认删除管理员</b>\n\n"
            f"你确定要删除管理员 {username} 吗？\n\n"
            f"删除后该用户将失去所有配置权限。"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ 确认删除", callback_data=f"admin:delete:{admin_user_id}"),
                InlineKeyboardButton("❌ 取消", callback_data="admin:show")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_admin_delete(query, context, admin_user_id):
    """确认删除管理员"""
    from ..models import Admin, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        result = await db.execute(
            select(Admin).where(Admin.bot_id == bot_id, Admin.user_id == admin_user_id)
        )
        admin = result.scalar_one_or_none()

        if admin:
            username = admin.username
            admin.is_active = False
            await db.commit()

            display_name = f"@{username}" if username else str(admin_user_id)
            await query.answer(f"✅ 管理员 {display_name} 已删除", show_alert=True)
        else:
            await query.answer("❌ 管理员不存在", show_alert=True)

    await _show_admin_page(query, context)

# ==================== 授权群组管理 - 新版交互流程 ====================

async def _show_authgroup_group_confirm(query, context, group_id, action):
    """显示单个群组授权/取消授权确认对话框

    Args:
        action: 'authorize' 或 'unauthorize'
    """
    from ..models import Group, get_db_session, GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        result = await db.execute(
            select(Group).where(Group.bot_id == bot_id, Group.group_id == group_id)
        )
        group = result.scalar_one_or_none()

        if not group:
            await query.answer("❌ 群组不存在", show_alert=True)
            await _show_auth_group_page(query, context)
            return

        group_name = group.group_name or f"群组 {group_id}"

        if action == 'authorize':
            text = (
                f"✅ <b>确认授权</b>\n\n"
                f"确定要授权「{group_name}」吗？\n\n"
                f"授权后该群将可以使用机器人所有功能。"
            )
            confirm_callback = f"authgroup:do_authorize:{group_id}"
        else:
            text = (
                f"❌ <b>确认取消授权</b>\n\n"
                f"确定要取消「{group_name}」的授权吗？\n\n"
                f"取消后该群将无法使用机器人所有功能。"
            )
            confirm_callback = f"authgroup:do_unauthorize:{group_id}"

        keyboard = [
            [
                InlineKeyboardButton("✅ 确认", callback_data=confirm_callback),
                InlineKeyboardButton("❌ 取消", callback_data="auth:group:show")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_authgroup_authorize(query, context, group_id):
    """确认授权单个群组"""
    from ..models import Group, get_db_session, GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        result = await db.execute(
            select(Group).where(Group.bot_id == bot_id, Group.group_id == group_id)
        )
        group = result.scalar_one_or_none()

        if group:
            group.status = GroupStatus.ACTIVE
            group.is_active = True
            await db.commit()

            group_name = group.group_name or f"群组 {group_id}"
            await query.answer(f"✅ 群组「{group_name}」已授权", show_alert=True)
        else:
            await query.answer("❌ 群组不存在", show_alert=True)

    await _show_auth_group_page(query, context)

async def _handle_authgroup_unauthorize(query, context, group_id):
    """确认取消授权单个群组"""
    from ..models import Group, get_db_session, GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        result = await db.execute(
            select(Group).where(Group.bot_id == bot_id, Group.group_id == group_id)
        )
        group = result.scalar_one_or_none()

        if group:
            group.status = GroupStatus.DISABLED
            group.is_active = False
            await db.commit()

            group_name = group.group_name or f"群组 {group_id}"
            await query.answer(f"❌ 群组「{group_name}」的授权已取消", show_alert=True)
        else:
            await query.answer("❌ 群组不存在", show_alert=True)

    await _show_auth_group_page(query, context)

async def _show_authgroup_batch_confirm(query, context, action):
    """显示批量操作确认对话框

    Args:
        action: 'authorize' 或 'unauthorize'
    """
    from ..models import Group, get_db_session, GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select, or_

    bot_id = get_current_bot_id(context)
    page = context.user_data.get('authgroup_current_page', 1)
    page_size = 5
    offset = (page - 1) * page_size

    async with get_db_session() as db:
        # 获取当前页的群组ID列表
        if action == 'authorize':
            # 未授权列表
            result = await db.execute(
                select(Group).where(
                    Group.bot_id == bot_id,
                    or_(
                        Group.status == GroupStatus.PENDING,
                        Group.status == GroupStatus.UNAUTHORIZED,
                        Group.status == GroupStatus.DISABLED,
                        Group.status == GroupStatus.EXPIRED
                    )
                )
                .order_by(Group.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        else:
            # 已授权列表
            result = await db.execute(
                select(Group).where(
                    Group.bot_id == bot_id,
                    Group.status == GroupStatus.ACTIVE
                )
                .order_by(Group.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )

        groups = result.scalars().all()
        group_count = len(groups)

        if group_count == 0:
            await query.answer("⚠️ 当前页没有群组可操作", show_alert=True)
            await _show_auth_group_page(query, context)
            return

        # 保存群组ID列表到上下文
        context.user_data['authgroup_batch_group_ids'] = [g.group_id for g in groups]

        if action == 'authorize':
            text = (
                f"✅ <b>确认批量授权</b>\n\n"
                f"确定要授权当前页所有群吗？\n"
                f"本页共 {group_count} 个群，授权后将可以使用机器人所有功能。"
            )
            confirm_callback = "authgroup:batch_do_authorize"
        else:
            text = (
                f"❌ <b>确认批量取消授权</b>\n\n"
                f"确定要取消当前页所有群的授权吗？\n"
                f"本页共 {group_count} 个群，取消后将无法使用机器人功能。"
            )
            confirm_callback = "authgroup:batch_do_unauthorize"

        keyboard = [
            [
                InlineKeyboardButton("✅ 确认", callback_data=confirm_callback),
                InlineKeyboardButton("❌ 取消", callback_data="auth:group:show")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_authgroup_batch_authorize(query, context):
    """批量授权当前页所有群组"""
    from ..models import Group, get_db_session, GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)
    group_ids = context.user_data.get('authgroup_batch_group_ids', [])

    if not group_ids:
        await query.answer("❌ 群组列表丢失", show_alert=True)
        await _show_auth_group_page(query, context)
        return

    async with get_db_session() as db:
        count = 0
        for group_id in group_ids:
            result = await db.execute(
                select(Group).where(Group.bot_id == bot_id, Group.group_id == group_id)
            )
            group = result.scalar_one_or_none()
            if group:
                group.status = GroupStatus.ACTIVE
                group.is_active = True
                count += 1

        await db.commit()

    # 清除临时状态
    context.user_data.pop('authgroup_batch_group_ids', None)

    await query.answer(f"✅ 已批量授权 {count} 个群组", show_alert=True)
    await _show_auth_group_page(query, context)

async def _handle_authgroup_batch_unauthorize(query, context):
    """批量取消授权当前页所有群组"""
    from ..models import Group, get_db_session, GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select

    bot_id = get_current_bot_id(context)
    group_ids = context.user_data.get('authgroup_batch_group_ids', [])

    if not group_ids:
        await query.answer("❌ 群组列表丢失", show_alert=True)
        await _show_auth_group_page(query, context)
        return

    async with get_db_session() as db:
        count = 0
        for group_id in group_ids:
            result = await db.execute(
                select(Group).where(Group.bot_id == bot_id, Group.group_id == group_id)
            )
            group = result.scalar_one_or_none()
            if group:
                group.status = GroupStatus.DISABLED
                group.is_active = False
                count += 1

        await db.commit()

    # 清除临时状态
    context.user_data.pop('authgroup_batch_group_ids', None)

    await query.answer(f"❌ 已批量取消授权 {count} 个群组", show_alert=True)
    await _show_auth_group_page(query, context)

# ==================== 日切设置 - 新版交互流程 ====================

async def _show_daycut_time_selector(query, context):
    """显示时间选择子菜单（24小时选项）"""
    text = (
        "📅 <b>全局日切设置</b>\n\n"
        "请选择日切时间：\n"
    )

    # 24小时时间选择网格 (4列 x 6行)
    keyboard = []
    for row_start in range(0, 24, 4):
        row = []
        for hour in range(row_start, min(row_start + 4, 24)):
            label = f"{hour:02d}:00"
            row.append(InlineKeyboardButton(label, callback_data=f"daycut:preview:{hour:02d}:00"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 返回日切设置", callback_data="daycut:show")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_daycut_save_confirm(query, context):
    """显示保存确认对话框"""
    temp_hour = context.user_data.get('daycut_temp_hour', 0)

    text = (
        f"📅 <b>确认保存日切设置</b>\n\n"
        f"确定要将全局日切时间设置为 {temp_hour:02d}:00 吗？\n"
        f"设置后所有授权群组统一生效。"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ 确认", callback_data="daycut:save"),
            InlineKeyboardButton("❌ 取消", callback_data="daycut:show")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_daycut_disable_confirm(query, context):
    """显示关闭日切确认对话框"""
    text = (
        "📅 <b>确认关闭日切</b>\n\n"
        "确定要关闭全局日切功能吗？\n"
        "关闭后所有群将不再自动日切。"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ 确认关闭", callback_data="daycut:disable"),
            InlineKeyboardButton("❌ 取消", callback_data="daycut:show")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_daycut_enable_confirm(query, context):
    """显示开启日切确认对话框"""
    temp_hour = context.user_data.get('daycut_temp_hour')
    saved_hour = 0

    # 获取已保存的时间
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        day_cut_time = await global_config_service.get_config(db, bot_id, "day_cut_time")
        if isinstance(day_cut_time, int):
            saved_hour = day_cut_time

    current_hour = temp_hour if temp_hour is not None else saved_hour

    text = (
        f"📅 <b>确认开启日切</b>\n\n"
        f"确定要开启全局日切功能吗？\n"
        f"日切时间：{current_hour:02d}:00\n"
        f"开启后所有授权群组将统一生效。"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ 确认开启", callback_data="daycut:enable"),
            InlineKeyboardButton("❌ 取消", callback_data="daycut:show")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_daycut_save(query, context):
    """确认保存日切设置"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    temp_hour = context.user_data.get('daycut_temp_hour')

    async with get_db_session() as db:
        if temp_hour is None:
            day_cut_time = await global_config_service.get_config(db, bot_id, "day_cut_time")
            temp_hour = day_cut_time if isinstance(day_cut_time, int) else 0
        await global_config_service.set_global_config(
            db, bot_id, "day_cut_enabled", True,
            description="每日定时日切账单开关",
            updated_by=query.from_user.id
        )
        await global_config_service.set_global_config(
            db, bot_id, "day_cut_time", temp_hour,
            description="日切时间（小时）",
            updated_by=query.from_user.id
        )

    # 清除临时状态
    context.user_data.pop('daycut_temp_hour', None)

    await query.answer(f"✅ 全局日切已保存为 {temp_hour:02d}:00，所有群组生效", show_alert=True)
    await _show_daycut_page(query, context)

async def _handle_daycut_disable(query, context):
    """确认关闭日切"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        await global_config_service.set_global_config(
            db, bot_id, "day_cut_enabled", False,
            description="每日定时日切账单开关",
            updated_by=query.from_user.id
        )

    await query.answer("❎ 全局日切已关闭", show_alert=True)
    await _show_daycut_page(query, context)

async def _handle_daycut_enable(query, context):
    """确认开启日切"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    temp_hour = context.user_data.get('daycut_temp_hour')

    async with get_db_session() as db:
        # 获取已保存的时间或使用默认值
        if temp_hour is None:
            day_cut_time = await global_config_service.get_config(db, bot_id, "day_cut_time")
            temp_hour = day_cut_time if isinstance(day_cut_time, int) else 0

        await global_config_service.set_global_config(
            db, bot_id, "day_cut_enabled", True,
            description="每日定时日切账单开关",
            updated_by=query.from_user.id
        )
        await global_config_service.set_global_config(
            db, bot_id, "day_cut_time", temp_hour,
            description="日切时间（小时）",
            updated_by=query.from_user.id
        )

    await query.answer(f"✅ 全局日切已开启，时间：{temp_hour:02d}:00", show_alert=True)
    await _show_daycut_page(query, context)

# ==================== 记账条数设置 - 新版交互流程 ====================

async def _show_display_deposit_selector(query, context):
    """显示入款条数选择子菜单"""
    text = (
        "📊 <b>全局记账条数设置</b>\n\n"
        "请选择入款显示条数："
    )

    options = [5, 10, 15, 20, 25]
    keyboard = []

    for count in options:
        keyboard.append([InlineKeyboardButton(f"{count}条", callback_data=f"display:preview_deposit:{count}")])

    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="display:show")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_display_withdraw_selector(query, context):
    """显示下发条数选择子菜单"""
    text = (
        "📊 <b>全局记账条数设置</b>\n\n"
        "请选择下发显示条数："
    )

    options = [5, 10, 15, 20, 25]
    keyboard = []

    for count in options:
        keyboard.append([InlineKeyboardButton(f"{count}条", callback_data=f"display:preview_withdraw:{count}")])

    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="display:show")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _show_display_save_confirm(query, context):
    """显示保存确认对话框"""
    temp_deposit = context.user_data.get('display_temp_deposit')
    temp_withdraw = context.user_data.get('display_temp_withdraw')

    # 获取已保存的值
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        deposit_count = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_count = await global_config_service.get_config(db, bot_id, "withdraw_display_count")

        saved_deposit = deposit_count if isinstance(deposit_count, int) else 10
        saved_withdraw = withdraw_count if isinstance(withdraw_count, int) else 10

    # 使用临时值或保存值
    current_deposit = temp_deposit if temp_deposit is not None else saved_deposit
    current_withdraw = temp_withdraw if temp_withdraw is not None else saved_withdraw

    text = (
        f"📊 <b>确认保存设置</b>\n\n"
        f"你确定要将全局记账条数设置为：\n"
        f"入款：{current_deposit} 条\n"
        f"下发：{current_withdraw} 条\n\n"
        f"所有授权群组将同步生效。"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ 确认", callback_data="display:save"),
            InlineKeyboardButton("❌ 取消", callback_data="display:show")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_display_save(query, context):
    """确认保存记账条数设置"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    temp_deposit = context.user_data.get('display_temp_deposit')
    temp_withdraw = context.user_data.get('display_temp_withdraw')

    async with get_db_session() as db:
        # 获取当前值
        deposit_count = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_count = await global_config_service.get_config(db, bot_id, "withdraw_display_count")

        saved_deposit = deposit_count if isinstance(deposit_count, int) else 10
        saved_withdraw = withdraw_count if isinstance(withdraw_count, int) else 10

        # 使用临时值或保持原值
        final_deposit = temp_deposit if temp_deposit is not None else saved_deposit
        final_withdraw = temp_withdraw if temp_withdraw is not None else saved_withdraw

        await global_config_service.set_global_config(
            db, bot_id, "deposit_display_count", final_deposit,
            description="入款显示条数",
            updated_by=query.from_user.id
        )
        await global_config_service.set_global_config(
            db, bot_id, "withdraw_display_count", final_withdraw,
            description="下发显示条数",
            updated_by=query.from_user.id
        )

    # 清除临时状态
    context.user_data.pop('display_temp_deposit', None)
    context.user_data.pop('display_temp_withdraw', None)

    await query.answer(f"✅ 全局记账条数已更新：入款{final_deposit}条，下发{final_withdraw}条，所有群组生效", show_alert=True)
    await _show_display_page(query, context)

# ==================== 记账成员名字显示 - 新版交互流程 ====================

async def _show_showname_page_v2(query, context):
    """显示记账成员名字设置页面（开关按钮式交互）

    页面布局：
    - 当前配置状态（实时预览）
    - 开关按钮：入款名字显示、下发名字显示
    - 保存设置按钮（有未保存更改时高亮）
    - 返回按钮
    """
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    # 获取临时选择的状态（如果有）
    temp_deposit = context.user_data.get('temp_deposit_name')
    temp_withdraw = context.user_data.get('temp_withdraw_name')

    async with get_db_session() as db:
        # 获取当前配置
        deposit_show_name = await global_config_service.get_config(db, bot_id, "deposit_show_name")
        withdraw_show_name = await global_config_service.get_config(db, bot_id, "withdraw_show_name")

        saved_deposit = deposit_show_name if isinstance(deposit_show_name, bool) else False
        saved_withdraw = withdraw_show_name if isinstance(withdraw_show_name, bool) else False

        # 使用临时值或保存值
        current_deposit = temp_deposit if temp_deposit is not None else saved_deposit
        current_withdraw = temp_withdraw if temp_withdraw is not None else saved_withdraw

        # 检查是否有未保存的更改
        has_unsaved = (temp_deposit is not None and temp_deposit != saved_deposit) or \
                      (temp_withdraw is not None and temp_withdraw != saved_withdraw)

        # 构建显示文本
        deposit_status = "✅ 开启" if current_deposit else "❌ 关闭"
        withdraw_status = "✅ 开启" if current_withdraw else "❌ 关闭"

        unsaved_mark = " <b>（未保存）</b>" if has_unsaved else ""

        text = (
            f"👤 <b>全局记账成员名字显示</b>\n\n"
            f"当前配置：\n"
            f"🧾 入款显示名字：{deposit_status}{' <b>（未保存）</b>' if temp_deposit is not None and temp_deposit != saved_deposit else ''}\n"
            f"💸 下发显示名字：{withdraw_status}{' <b>（未保存）</b>' if temp_withdraw is not None and temp_withdraw != saved_withdraw else ''}\n\n"
            f"👇 点击开关切换显示状态，修改后记得保存"
        )

        keyboard = []

        # 开关按钮行
        deposit_btn_text = f"🧾 入款名字显示：{'✅ 开启' if current_deposit else '❌ 关闭'}"
        withdraw_btn_text = f"💸 下发名字显示：{'✅ 开启' if current_withdraw else '❌ 关闭'}"

        keyboard.append([InlineKeyboardButton(deposit_btn_text, callback_data="showname:toggle:deposit")])
        keyboard.append([InlineKeyboardButton(withdraw_btn_text, callback_data="showname:toggle:withdraw")])

        # 保存设置按钮（有未保存更改时显示不同样式）
        save_btn_text = "💾 保存设置" if has_unsaved else "✅ 保存设置"
        keyboard.append([InlineKeyboardButton(save_btn_text, callback_data="showname:save:v2")])

        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="settings:main")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def _handle_showname_save_v2(query, context):
    """保存记账成员名字显示设置（v2版本）"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    temp_deposit = context.user_data.get('temp_deposit_name')
    temp_withdraw = context.user_data.get('temp_withdraw_name')

    async with get_db_session() as db:
        # 获取当前值
        deposit_show_name = await global_config_service.get_config(db, bot_id, "deposit_show_name")
        withdraw_show_name = await global_config_service.get_config(db, bot_id, "withdraw_show_name")

        saved_deposit = deposit_show_name if isinstance(deposit_show_name, bool) else False
        saved_withdraw = withdraw_show_name if isinstance(withdraw_show_name, bool) else False

        # 使用临时值或保持原值
        final_deposit = temp_deposit if temp_deposit is not None else saved_deposit
        final_withdraw = temp_withdraw if temp_withdraw is not None else saved_withdraw

        await global_config_service.set_global_config(
            db, bot_id, "deposit_show_name", final_deposit,
            description="入款显示名字开关",
            updated_by=query.from_user.id
        )
        await global_config_service.set_global_config(
            db, bot_id, "withdraw_show_name", final_withdraw,
            description="下发显示名字开关",
            updated_by=query.from_user.id
        )
        await global_config_service.set_global_config(
            db, bot_id, "show_member_name", bool(final_deposit and final_withdraw),
            description="全局记账成员名字显示开关",
            updated_by=query.from_user.id
        )

    # 清除临时状态
    context.user_data.pop('temp_deposit_name', None)
    context.user_data.pop('temp_withdraw_name', None)

    await query.answer("✅ 全局记账名字显示已更新，所有群组生效", show_alert=True)
    await _show_showname_page_v2(query, context)

async def _handle_export_bills(query, context):
    """导出账单Excel"""
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        xlsx_enabled = await global_config_service.get_config(db, bot_id, "xlsx_enabled")
        is_enabled = xlsx_enabled if isinstance(xlsx_enabled, bool) else False

    if not is_enabled:
        await query.answer("⚠️ xlsx账单导出功能未启用，请联系管理员开启", show_alert=True)
        return

    try:
        from . import billing
        from telegram import Update

        class FakeUpdate:
            def __init__(self):
                self.message = query.message
                self.effective_chat = query.message.chat
                self.effective_user = query.from_user

        fake_update = FakeUpdate()
        await billing.handle_export_xlsx(fake_update, context)
    except Exception as e:
        await query.answer(f"❌ 导出失败：{str(e)}", show_alert=True)

async def _show_permission_denied(query, user_role, required_role):
    """显示权限不足提示
    
    Args:
        query: 回调查询对象
        user_role: 当前用户角色
        required_role: 所需权限角色描述
    """
    from ..utils.role_checker import UserRole
    
    # 将角色枚举转换为中文描述
    role_names = {
        UserRole.SUPER_ADMIN: "超级管理员",
        UserRole.BOT_OWNER: "Bot创建者",
        UserRole.ADMIN: "管理员",
        UserRole.NORMAL_USER: "普通用户"
    }
    
    current_role_name = role_names.get(user_role, "未知身份")
    
    text = (
        f"❌ <b>权限不足</b>\n\n"
        f"👤 当前身份: {current_role_name}\n"
        f"🔐 所需权限: {required_role}\n\n"
        f"💡 请联系管理员获取相应权限。"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="settings_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

# ============================================================================
# 编辑模式消息处理器
# ============================================================================

async def handle_edit_mode_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理编辑模式下的用户消息
    
    当用户处于编辑状态时，此处理器会拦截用户消息并进行相应处理：
    - edit_welcome_text: 保存欢迎语
    - add_keyword: 保存关键词，进入添加回复模式
    - add_keyword_reply: 保存关键词回复
    """
    user_id = update.effective_user.id
    logger.info(f"[EDIT_MODE] handle_edit_mode_message called for user {user_id}")
    
    from ..utils.state_manager import (
        get_edit_state, clear_edit_state, set_edit_state,
        EDIT_STATE_WELCOME_TEXT, EDIT_STATE_ADD_KEYWORD, EDIT_STATE_ADD_KEYWORD_REPLY
    )
    from ..services.global_config_service import global_config_service
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    state, data = await get_edit_state(context)
    
    logger.info(f"[EDIT_MODE] User {user_id} sent message, edit_state={state}, user_data_keys={list(context.user_data.keys())}")

    if not state:
        return  # 不在编辑状态，跳过

    bot_id = get_current_bot_id(context)

    # 处理编辑欢迎语
    if state == EDIT_STATE_WELCOME_TEXT:
        new_welcome_text = update.message.text

        async with get_db_session() as db:
            await global_config_service.set_global_config(
                db,
                bot_id,
                "welcome_message",
                new_welcome_text,
                description="全局入群欢迎语内容",
                updated_by=user_id,
            )

        await clear_edit_state(context)
        await update.message.reply_text(
            f"✅ <b>欢迎语已保存</b>\n\n"
            f"新的欢迎语：\n<code>{new_welcome_text[:100]}{'...' if len(new_welcome_text) > 100 else ''}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("← 返回设置页", callback_data="welcome:show")]]
            ),
        )
        return True

    elif state == EDIT_STATE_ADD_KEYWORD:
        keyword = update.message.text.strip()

        # 检查关键词是否已存在
        existing_keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
        if any(kw.keyword == keyword for kw in existing_keywords):
            await update.message.reply_text(
                f"⚠️ 关键词「{keyword}」已存在，请输入其他关键词或取消：",
                parse_mode="HTML"
            )
            return True

        # 进入添加回复模式
        await set_edit_state(context, EDIT_STATE_ADD_KEYWORD_REPLY, {"keyword": keyword})

        await update.message.reply_text(
            f"✅ 关键词「{keyword}」已记录\n\n"
            f"请发送该关键词的回复内容：",
            parse_mode="HTML"
        )

        return True

    # 处理添加关键词回复
    elif state == EDIT_STATE_ADD_KEYWORD_REPLY:
        reply_text = update.message.text
        keyword = data.get("keyword") if data else None

        if not keyword:
            await clear_edit_state(context)
            await update.message.reply_text(
                "❌ 发生错误，请重新添加关键词",
                parse_mode="HTML"
            )
            return True

        # 保存关键词和回复
        success = await CustomKeywordService.add_keyword(
            bot_id=bot_id,
            keyword=keyword,
            reply_text=reply_text,
            group_id=0,  # 全局关键词
            created_by=user_id
        )

        await clear_edit_state(context)

        if success:
            await update.message.reply_text(
                f"✅ <b>关键词添加成功</b>\n\n"
                f"关键词：<b>{keyword}</b>\n"
                f"回复：{reply_text[:50]}{'...' if len(reply_text) > 50 else ''}",
                parse_mode="HTML"
            )

        else:
            await update.message.reply_text(
                "❌ 添加关键词失败，请稍后重试",
                parse_mode="HTML"
            )

        return True

    return False  # 未知状态，返回 False


# ==================== 广播用户功能 ====================

async def _show_broadcast_users_page(query, context):
    """
    显示广播用户主页面 - 根据角色自动处理
    
    角色权限：
    - 超级管理员：显示选择菜单（2个选项）
    - Bot创建者：自动选中"向此bot用户发送"，直接进入输入内容
    - 其他角色：显示权限不足提示
    """
    from ..utils.role_checker import get_user_role, UserRole
    from ..utils.bot_id_middleware import get_current_bot_id
    
    user = query.from_user
    bot_id = get_current_bot_id(context)
    user_role = await get_user_role(user.id, bot_id=bot_id)
    
    # 检查权限
    if user_role not in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER]:
        # 无权限用户
        await query.edit_message_text(
            "❌ <b>权限不足</b>\n\n"
            "你没有使用广播功能的权限，请联系管理员。",
            parse_mode="HTML"
        )
        return
    
    # 清空之前的状态
    _clear_broadcast_users_state(context)
    
    if user_role == UserRole.SUPER_ADMIN:
        # 超级管理员：显示选择菜单
        keyboard = [
            [InlineKeyboardButton("📢 向所有BOT用户发送", callback_data="broadcast_users:mode:all_bots"),
             InlineKeyboardButton("📢 向主bot用户发送", callback_data="broadcast_users:mode:this_bot")],
            [InlineKeyboardButton("◀ 返回主菜单", callback_data="settings:main")]
        ]
        text = (
            "📢 <b>广播用户</b>\n\n"
            "请选择广播目标"
        )
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        # Bot创建者：自动选中，直接进入输入内容
        await _handle_broadcast_users_mode_select(query, context, "this_bot", auto_selected=True)


async def _handle_broadcast_users_mode_select(query, context, mode, auto_selected=False):
    """
    处理广播用户模式选择
    
    Args:
        mode: 'all_bots' 或 'this_bot'
        auto_selected: 是否为自动选中（Bot创建者）
    """
    # 保存选择的模式到状态
    context.user_data['broadcast_users_mode'] = mode
    context.user_data['broadcast_users_waiting_input'] = True
    context.user_data['broadcast_users_sending'] = False
    
    # 更新提示
    keyboard = [
        [InlineKeyboardButton("❌ 取消广播", callback_data="broadcast_users:cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if auto_selected:
        # Bot创建者自动选中
        text = (
            "📢 <b>广播用户</b>\n\n"
            "已默认选择：向此Bot用户发送\n"
            "请发送广播内容（文本/图片/文件/视频）"
        )
    else:
        # 超级管理员手动选择
        mode_names = {
            'all_bots': '向所有BOT用户发送',
            'this_bot': '向主bot用户发送'
        }
        mode_name = mode_names.get(mode, '未知模式')
        text = (
            "📢 <b>广播用户</b>\n\n"
            f"已选择：{mode_name}\n"
            "请发送广播内容（文本/图片/文件/视频）"
        )
    
    await query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )


async def _handle_broadcast_users_input(update, context):
    """
    处理用户输入的广播消息
    支持文本、图片、文件
    """
    from ..utils.bot_id_middleware import get_current_bot_id

    # 检查是否在等待输入状态
    if not context.user_data.get('broadcast_users_waiting_input'):
        return False

    if not update.message:
        return False

    bot_id = get_current_bot_id(context)
    
    # 保存消息内容
    message_data = {}
    
    if update.message.text:
        # 文本消息
        message_data['type'] = 'text'
        message_data['content'] = update.message.text
        message_data['preview'] = update.message.text[:200] + ('...' if len(update.message.text) > 200 else '')
    elif update.message.photo:
        # 图片消息
        message_data['type'] = 'photo'
        message_data['file_id'] = update.message.photo[-1].file_id
        message_data['caption'] = update.message.caption or ''
        message_data['preview'] = f"[图片] {message_data['caption'][:100]}"
    elif update.message.document:
        # 文件消息
        message_data['type'] = 'document'
        message_data['file_id'] = update.message.document.file_id
        message_data['caption'] = update.message.caption or ''
        message_data['file_name'] = update.message.document.file_name
        message_data['preview'] = f"[文件: {message_data['file_name']}] {message_data['caption'][:50]}"
    elif update.message.video:
        # 视频消息
        message_data['type'] = 'video'
        message_data['file_id'] = update.message.video.file_id
        message_data['caption'] = update.message.caption or ''
        message_data['preview'] = f"[视频] {message_data['caption'][:100]}"
    else:
        # 不支持的消息类型
        await update.message.reply_text(
            "⚠️ 不支持的消息类型，请发送文本、图片、文件或视频。",
            parse_mode="HTML"
        )
        return True
    
    # 保存消息数据
    context.user_data['broadcast_users_message'] = message_data
    context.user_data['broadcast_users_waiting_input'] = False
    
    # 统计目标用户数量
    target_count = await _get_broadcast_users_count(bot_id, context.user_data.get('broadcast_users_mode'))
    
    # 获取目标范围描述
    mode = context.user_data.get('broadcast_users_mode')
    target_desc = '所有BOT用户' if mode == 'all_bots' else '此Bot用户'
    
    # 显示确认对话框（必显示内容）
    keyboard = [
        [InlineKeyboardButton("✅ 确认发送", callback_data="broadcast_users:confirm"),
         InlineKeyboardButton("❌ 取消广播", callback_data="broadcast_users:cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    confirm_text = (
        "📢 <b>广播预览</b>\n\n"
        f"目标：{target_desc}\n"
        f"预计发送：{target_count} 人\n\n"
        f"━━━━━ 预览内容 ━━━━━\n"
        f"{message_data['preview']}\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"确认发送？发送后无法撤回"
    )
    
    await update.message.reply_text(
        confirm_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    return True


async def _get_broadcast_users_count(bot_id, mode):
    """获取目标用户数量"""
    try:
        from ..services.user_broadcast_service import UserBroadcastService

        target_users = await UserBroadcastService.get_target_users(mode, bot_id=bot_id)
        return len(target_users)
    except Exception as e:
        logger.error(f"获取广播用户数量失败: {e}")
        return 0


async def _handle_broadcast_users_confirm(query, context):
    """处理确认发送广播"""
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..services.user_broadcast_service import UserBroadcastService
    
    bot_id = get_current_bot_id(context)
    mode = context.user_data.get('broadcast_users_mode')
    message_data = context.user_data.get('broadcast_users_message')
    
    if not message_data:
        await query.answer("❌ 消息数据丢失，请重新开始", show_alert=True)
        await _show_broadcast_users_page(query, context)
        return
    
    # 获取目标用户列表
    target_users = await UserBroadcastService.get_target_users(mode, bot_id=bot_id)
    total = len(target_users)
    
    if total == 0:
        await query.edit_message_text(
            "❌ <b>没有可发送的目标用户</b>\n\n"
            "请检查用户数据或联系管理员。",
            parse_mode="HTML"
        )
        _clear_broadcast_users_state(context)
        return
    
    # 设置终止标志
    context.user_data['broadcast_users_stop'] = False
    context.user_data['broadcast_users_sending'] = True
    
    # 显示发送进度（带终止按钮）
    keyboard = [
        [InlineKeyboardButton("⛔ 终止发送", callback_data="broadcast_users:stop")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    progress_message = await query.edit_message_text(
        f"📢 <b>广播发送中…</b>\n\n"
        f"进度：0/{total}",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    last_progress = {"current": 0}

    async def progress_callback(current, total_count):
        if current == last_progress["current"]:
            return
        last_progress["current"] = current

        if current % 10 != 0 and current != total_count:
            return

        try:
            await progress_message.edit_text(
                f"📢 <b>广播发送中…</b>\n\n"
                f"进度：{current}/{total_count}",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception:
            pass

    result = await UserBroadcastService.send_broadcast(
        context=context,
        user_ids=target_users,
        message_content=message_data,
        progress_callback=progress_callback,
        stop_check=lambda: context.user_data.get('broadcast_users_stop', False),
    )

    was_stopped = result.get('stopped', False) or context.user_data.get('broadcast_users_stop', False)
    success_count = result.get('success', 0)
    fail_count = result.get('fail', 0)
    processed_count = result.get('processed', success_count + fail_count)
    
    # 发送完成报告
    keyboard = [
        [InlineKeyboardButton("📢 再次广播", callback_data="broadcast_users:show"),
         InlineKeyboardButton("◀ 返回主菜单", callback_data="settings:main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if was_stopped:
        status_text = "⛔ <b>广播已终止</b>"
    else:
        status_text = "✅ <b>广播完成</b>"
    
    await progress_message.edit_text(
        f"{status_text}\n\n"
        f"总人数：{total}\n"
        f"已处理：{processed_count}\n"
        f"成功：{success_count}\n"
        f"失败：{fail_count}",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    # 清理状态
    _clear_broadcast_users_state(context)


async def _send_broadcast_message(context, user_id, message_data):
    """发送广播消息到指定用户"""
    msg_type = message_data.get('type')
    
    if msg_type == 'text':
        await context.bot.send_message(
            chat_id=user_id,
            text=message_data['content'],
            parse_mode="HTML"
        )
    elif msg_type == 'photo':
        await context.bot.send_photo(
            chat_id=user_id,
            photo=message_data['file_id'],
            caption=message_data['caption'],
            parse_mode="HTML"
        )
    elif msg_type == 'document':
        await context.bot.send_document(
            chat_id=user_id,
            document=message_data['file_id'],
            caption=message_data['caption'],
            parse_mode="HTML"
        )
    elif msg_type == 'video':
        await context.bot.send_video(
            chat_id=user_id,
            video=message_data['file_id'],
            caption=message_data['caption'],
            parse_mode="HTML"
        )


async def _get_broadcast_users_list(bot_id, mode):
    """获取目标用户ID列表"""
    from ..models.database import get_db_session
    from ..models import UserConfig
    from sqlalchemy import select
    
    try:
        async with get_db_session() as db:
            if mode == 'all_bots':
                # 所有BOT的用户
                query = select(UserConfig.user_id).where(
                    UserConfig.is_active.is_(True)
                )
            else:
                # 当前Bot的用户
                query = select(UserConfig.user_id).where(
                    (UserConfig.bot_id == bot_id) &
                    (UserConfig.is_active.is_(True))
                )
            
            result = await db.execute(query)
            users = result.scalars().all()
            return list(users)
    except Exception as e:
        logger.error(f"获取广播用户列表失败: {e}")
        return []


def _clear_broadcast_users_state(context):
    """清空广播用户相关状态"""
    context.user_data.pop('broadcast_users_mode', None)
    context.user_data.pop('broadcast_users_waiting_input', None)
    context.user_data.pop('broadcast_users_message', None)
    context.user_data.pop('broadcast_users_stop', None)
    context.user_data.pop('broadcast_users_sending', None)


async def _handle_broadcast_users_cancel(query, context):
    """处理取消广播"""
    _clear_broadcast_users_state(context)
    await _show_settings_main(query, context)


async def handle_broadcast_users_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理广播用户功能的消息输入
    此函数在 bot_factory.py 中注册，专门处理广播用户的消息输入
    """
    # 检查是否在等待广播用户输入状态
    if not context.user_data.get('broadcast_users_waiting_input'):
        return  # 不在等待状态，让其他处理器处理
    
    # 调用处理函数
    result = await _handle_broadcast_users_input(update, context)
    
    # 如果处理了消息，返回，不再让其他处理器处理
    if result:
        return


async def cancel_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """中断广播并清理状态。"""
    from . import menu_callbacks

    user_data = context.user_data
    had_user_broadcast_state = any(
        user_data.get(key)
        for key in (
            'broadcast_users_waiting_input',
            'broadcast_users_message',
            'broadcast_users_sending',
            'broadcast_users_mode',
        )
    )
    had_group_broadcast_state = any(
        user_data.get(key)
        for key in (
            'waiting_broadcast_msg',
            'broadcast_msg',
            'broadcast_target',
            'broadcast_selected_group_ids',
            'broadcast_mode',
        )
    )

    if user_data.get('broadcast_users_sending'):
        user_data['broadcast_users_stop'] = True
    else:
        _clear_broadcast_users_state(context)

    menu_callbacks._clear_broadcast_state(context)

    if not had_user_broadcast_state and not had_group_broadcast_state:
        text = "当前没有进行中的广播会话。"
    elif user_data.get('broadcast_users_stop'):
        text = "已收到中断指令，正在停止用户广播并清理状态。"
    else:
        text = "广播会话已取消，临时状态已清理。"

    if update.effective_message:
        await update.effective_message.reply_text(text)


async def handle_admin_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理添加管理员时的用户输入"""
    if not update.message or not update.effective_user:
        return
    
    # 检查是否处于等待添加管理员的状态
    if not context.user_data.get('waiting_admin_add'):
        return  # 不在等待状态，让其他处理器处理
    
    user_input = update.message.text.strip()
    user_id = None
    username = None
    
    # 尝试从输入中提取用户ID或用户名
    if user_input.startswith('@'):
        # 用户名格式
        username = user_input[1:]
    elif user_input.isdigit():
        # 数字ID格式
        user_id = int(user_input)
    else:
        # 尝试其他格式
        await update.message.reply_text(
            "❌ <b>格式错误</b>\n\n"
            "请发送：\n"
            "• 用户ID（数字）\n"
            "• 用户名（@username）\n\n"
            "例如：<code>123456789</code> 或 <code>@username</code>",
            parse_mode='HTML'
        )
        return
    
    # 清除等待状态
    context.user_data.pop('waiting_admin_add', None)
    
    # 保存用户信息
    if user_id:
        context.user_data['admin_add_user_id'] = user_id
    if username:
        context.user_data['admin_add_username'] = username
    
    display_name = f"@{username}" if username else str(user_id)
    
    # 直接显示确认页面（只有管理员一个角色）
    text = (
        f"➕ <b>确认添加管理员</b>\n\n"
        f"用户：{display_name}\n"
        f"权限：管理员\n\n"
        f"确定要添加吗？"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认", callback_data="admin:add_confirm"),
            InlineKeyboardButton("❌ 取消", callback_data="admin:show")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')


async def _handle_trial_apply(query, context):
    """
    处理试用申请 - 赋予试用管理员权限

    流程：
    1. 申请资格校验（查询 TrialRecord）
    2. 生成试用权限（15天，管理员身份）
    3. 赋予管理员身份（写入 Admin 表）
    4. 写入试用记录
    5. 成功反馈
    """
    from datetime import datetime, timedelta
    from sqlalchemy import select, func
    from ..models import TrialRecord, Admin, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from config.enhanced_config import config_manager

    user = query.from_user
    user_id = user.id
    username = user.username or ""
    user_fullname = user.full_name or ""

    # 获取当前Bot ID
    bot_id = get_current_bot_id(context)

    # 获取试用配置（硬编码）
    trial_days = 8  # 试用8天
    trial_group_limit = 5  # 试用管理员最多管理5个群组

    try:
        async with get_db_session() as session:
            # ========== 步骤1：申请资格校验 ==========
            # 查询是否已存在试用记录
            stmt = select(TrialRecord).where(
                TrialRecord.bot_id == bot_id,
                TrialRecord.user_id == user_id
            )
            result = await session.execute(stmt)
            existing_trial = result.scalar_one_or_none()

            if existing_trial:
                # 已申请过，拒绝重复申请
                await query.edit_message_text(
                    "❌ <b>申请失败</b>\n\n"
                    "每位用户仅可申请一次试用。\n"
                    "请购买正式套餐。",
                    parse_mode="HTML"
                )
                return

            # ========== 步骤2：生成试用权限 ==========
            now = datetime.utcnow()
            start_time = now
            expire_time = now + timedelta(days=trial_days)

            # ========== 步骤3：赋予管理员身份 ==========
            # 查询是否已是管理员
            stmt = select(Admin).where(
                Admin.bot_id == bot_id,
                Admin.user_id == user_id
            )
            result = await session.execute(stmt)
            existing_admin = result.scalar_one_or_none()

            if existing_admin:
                # 更新为试用管理员
                existing_admin.is_trial = True
                existing_admin.group_limit = trial_group_limit
                existing_admin.expire_time = expire_time
                existing_admin.is_active = True
            else:
                # 创建新的试用管理员记录
                # 获取超级管理员ID作为添加者
                from ..config.config import config
                super_admin_id = config.SUPER_ADMIN_ID

                admin = Admin(
                    bot_id=bot_id,
                    user_id=user_id,
                    username=username,
                    first_name=user.first_name if hasattr(user, 'first_name') else None,
                    last_name=user.last_name if hasattr(user, 'last_name') else None,
                    is_active=True,
                    # 试用管理员拥有完整权限
                    can_create_bot=False,  # 试用管理员不能创建机器人
                    can_manage_admins=False,  # 试用管理员不能管理其他管理员
                    can_manage_group_members=True,
                    can_broadcast=True,
                    can_set_day_cut=True,
                    can_set_keywords=True,
                    can_billing=True,
                    can_query=True,
                    can_settings=True,
                    can_renew=True,
                    added_by=super_admin_id,
                    added_by_username="system_trial",
                    note=f"试用管理员，自动创建，到期时间：{expire_time.strftime('%Y-%m-%d %H:%M:%S')}",
                    # 试用相关字段
                    is_trial=True,
                    group_limit=trial_group_limit,
                    expire_time=expire_time
                )
                session.add(admin)

            # ========== 步骤4：写入试用记录 ==========
            trial_record = TrialRecord(
                bot_id=bot_id,
                user_id=user_id,
                apply_time=now,
                start_time=start_time,
                expire_time=expire_time,
                used_once=True,
                username=username,
                user_fullname=user_fullname
            )
            session.add(trial_record)

            # 提交事务
            await session.commit()

            # ========== 步骤5：成功反馈 ==========
            # 格式化时间显示
            start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
            expire_time_str = expire_time.strftime("%Y-%m-%d %H:%M:%S")

            # 构建用户信息显示
            user_display = f"@{username}" if username else str(user_id)

            success_text = (
                f"🎉 <b>申请试用成功</b>\n"
                f"已获得当前BOT管理员权限\n\n"
                f"试用时长：{trial_days}天\n\n"
                f"👤 <b>用户信息（已更新）</b>\n"
                f"用户编号：<code>{user_id}</code>\n"
                f"用户账号：{user_display}\n"
                f"用户姓名：{user_fullname or '未设置'}\n"
                f"身份：管理员（试用）\n"
                f"开始时间：{start_time_str}\n"
                f"到期时间：{expire_time_str}\n"
                f"群组额度：{trial_group_limit}个\n\n"
                f"💡 <b>试用说明</b>\n"
                f"• 获得当前BOT管理员权限\n"
                f"• 最多管理{trial_group_limit}个群组\n"
                f"• 每位用户仅限申请一次\n"
                f"• 到期自动取消管理员身份"
            )

            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu:close")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                success_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

            logger.info(f"用户 {user_id} ({username}) 成功申请试用管理员，到期时间：{expire_time_str}")

    except Exception as e:
        logger.error(f"试用申请处理失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ <b>申请试用失败</b>\n\n"
            "系统处理异常，请稍后重试或联系客服。",
            parse_mode="HTML"
        )


async def _handle_billing_self_renew(query, context):
    """
    处理直接购买套餐按钮
    调用自助续费/创建机器人逻辑
    """
    from ..handlers.menu_callbacks import handle_self_renew
    from ..core.ui_schema_registry import self_renew_handler

    try:
        # 使用 ui_schema_registry 中的 handler
        from ..services.tenant_context import tenant_context_manager, TenantContext
        from ..utils.bot_id_middleware import get_current_bot_id

        bot_id = get_current_bot_id(context)
        user = query.from_user

        # 获取租户上下文
        tenant_context = await tenant_context_manager.get_tenant_context(bot_id, user.id)
        if not tenant_context:
            await query.edit_message_text(
                "❌ <b>系统错误</b>\n\n"
                "无法获取租户上下文，请稍后重试。",
                parse_mode="HTML"
            )
            return

        # 调用 handler
        await self_renew_handler(query, context, tenant_context)

    except Exception as e:
        logger.error(f"购买套餐处理失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ <b>处理失败</b>\n\n"
            "系统处理异常，请稍后重试或联系客服。",
            parse_mode="HTML"
        )


async def _handle_contact_support(query, context):
    """
    处理联系客服咨询按钮
    调用联系客服逻辑
    """
    try:
        await query.edit_message_text(
            "💼 <b>联系客服</b>\n\n"
            "TG小明记账机器人售后技术\n\n"
            "Telegram: @xiaomingjz\n\n"
            "如有任何问题，请随时联系！",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"联系客服处理失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ <b>处理失败</b>\n\n"
            "系统处理异常，请稍后重试或联系客服。",
            parse_mode="HTML"
        )


# ==================== 申请试用页面内联按钮回调处理 ====================

async def handle_trial_apply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 trial:apply 回调（申请试用页面-立即申请试用按钮）"""
    query = update.callback_query
    await query.answer()
    await _handle_trial_apply(query, context)


async def handle_billing_self_renew_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 billing:self_renew 回调（申请试用页面-直接购买套餐按钮）"""
    query = update.callback_query
    await query.answer()
    await _handle_billing_self_renew(query, context)


async def handle_contact_support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 contact:support 回调（申请试用页面-联系客服咨询按钮）"""
    query = update.callback_query
    await query.answer()
    await _handle_contact_support(query, context)


async def _show_auth_group_page(query, context, page=1, show_authorized=True):
    """新版授权群组列表页，统一为双列分页样式。"""
    from sqlalchemy import func, or_

    from ..models import Group, get_db_session
    from ..models.enums import GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id

    def _short_name(name: str | None, group_id: int) -> str:
        raw = (name or f"群组{group_id}").strip()
        return raw[:6]

    bot_id = get_current_bot_id(context)
    page_size = 10

    async with get_db_session() as db:
        authorized_count_result = await db.execute(
            select(func.count()).select_from(Group).where(
                Group.bot_id == bot_id,
                Group.status == GroupStatus.ACTIVE,
            )
        )
        authorized_count = authorized_count_result.scalar() or 0

        unauthorized_filter = or_(
            Group.status == GroupStatus.PENDING,
            Group.status == GroupStatus.UNAUTHORIZED,
            Group.status == GroupStatus.DISABLED,
            Group.status == GroupStatus.EXPIRED,
        )
        unauthorized_count_result = await db.execute(
            select(func.count()).select_from(Group).where(
                Group.bot_id == bot_id,
                unauthorized_filter,
            )
        )
        unauthorized_count = unauthorized_count_result.scalar() or 0

        if show_authorized:
            total_count = authorized_count
            base_query = select(Group).where(
                Group.bot_id == bot_id,
                Group.status == GroupStatus.ACTIVE,
            )
            list_label = "✅ 已授权群"
            batch_action_text = "❌ 取消授权"
            batch_action_callback = "authgroup:batch_unauthorize_confirm"
            item_action = "unauthorize"
        else:
            total_count = unauthorized_count
            base_query = select(Group).where(
                Group.bot_id == bot_id,
                unauthorized_filter,
            )
            list_label = "❌ 未授权群"
            batch_action_text = "✅ 批量授权"
            batch_action_callback = "authgroup:batch_authorize_confirm"
            item_action = "authorize"

        total_pages = max(1, (total_count + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size
        result = await db.execute(
            base_query.order_by(Group.created_at.desc()).offset(offset).limit(page_size)
        )
        groups = list(result.scalars().all())

    context.user_data["authgroup_current_page"] = page
    context.user_data["authgroup_show_authorized"] = show_authorized

    text = (
        "📡 <b>授权群组管理</b>\n\n"
        "✨点群名即可快速授权或取消授权\n"
        "🧭 可切换已授权群和未授权群查看\n\n"
        f"当前共有 {authorized_count + unauthorized_count} 个群组\n"
        f"当前列表：{list_label}（{total_count}个）"
    )

    keyboard = []
    if groups:
        for i in range(0, len(groups), 2):
            row = []
            for group in groups[i:i + 2]:
                row.append(
                    InlineKeyboardButton(
                        f"📁 {_short_name(group.group_name, group.group_id)}",
                        callback_data=f"authgroup:confirm:{group.group_id}:{item_action}",
                    )
                )
            if row:
                keyboard.append(row)
    else:
        text += "\n\nℹ️ 当前列表暂无群组"

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"authgroup:page:{page - 1}:{show_authorized}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"authgroup:page:{page + 1}:{show_authorized}"))
        if nav_row:
            keyboard.append(nav_row)

    if groups:
        keyboard.append([InlineKeyboardButton(batch_action_text, callback_data=batch_action_callback)])

    if show_authorized:
        keyboard.append([
            InlineKeyboardButton("✅ 已授权群", callback_data="authgroup:noop"),
            InlineKeyboardButton("❌ 未授权群", callback_data="authgroup:switch:False"),
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("✅ 已授权群", callback_data="authgroup:switch:True"),
            InlineKeyboardButton("❌ 未授权群", callback_data="authgroup:noop"),
        ])

    keyboard.append([InlineKeyboardButton("⬅️ 返回设置", callback_data="settings:main")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


# ============================================================================
# Keyword page overrides
# ============================================================================

_legacy_handle_edit_mode_message = handle_edit_mode_message


async def _show_keyword_page(query, context):
    from ..services.global_config_service import global_config_service
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        keyword_enabled = await global_config_service.get_config(db, bot_id, "keyword_reply_enabled")
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)

    is_enabled = keyword_enabled if isinstance(keyword_enabled, bool) else True
    keyword_count = len(keywords)
    status_text = "✅ 已开启" if is_enabled else "❌ 已关闭"
    enable_text = "☑️ 开启" if is_enabled else "开启"
    disable_text = "☑️ 关闭" if not is_enabled else "关闭"

    text = (
        "🔑 <b>关键词回复</b>\n\n"
        f"当前状态：{status_text}\n"
        f"已设置 <b>{keyword_count}</b> 条关键词\n\n"
        "点击下方按钮管理关键词回复。"
    )

    keyboard = [
        [
            InlineKeyboardButton("状态：", callback_data="keyword:noop"),
            InlineKeyboardButton(enable_text, callback_data="keyword:enable"),
            InlineKeyboardButton(disable_text, callback_data="keyword:disable"),
        ],
        [InlineKeyboardButton("📑 关键词列表", callback_data="keyword:list")],
        [InlineKeyboardButton("➕ 添加关键词", callback_data="keyword:add")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_back")],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _handle_keyword_enable(query, context):
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        await global_config_service.set_global_config(
            db,
            bot_id,
            "keyword_reply_enabled",
            True,
            description="全局关键词回复开关",
            updated_by=query.from_user.id,
        )
    await query.answer("✅ 关键词回复已开启", show_alert=False)
    await _show_keyword_page(query, context)


async def _handle_keyword_disable(query, context):
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        await global_config_service.set_global_config(
            db,
            bot_id,
            "keyword_reply_enabled",
            False,
            description="全局关键词回复开关",
            updated_by=query.from_user.id,
        )
    await query.answer("✅ 关键词回复已关闭", show_alert=False)
    await _show_keyword_page(query, context)


async def _handle_keyword_add(query, context):
    from ..utils.state_manager import set_edit_state, EDIT_STATE_ADD_KEYWORD

    await set_edit_state(context, EDIT_STATE_ADD_KEYWORD)
    text = (
        "➕ <b>添加关键词</b>\n\n"
        "请先发送关键词，随后再发送回复内容。\n\n"
        "例如：\n"
        "<code>开门</code>\n"
        "<code>你好</code>\n\n"
        "完成后会自动给你返回主菜单按钮。"
    )
    keyboard = [[InlineKeyboardButton("❌ 取消", callback_data="keyword:cancel_add")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _handle_keyword_cancel_add(query, context):
    from ..utils.state_manager import clear_edit_state

    await clear_edit_state(context)
    await _show_keyword_page(query, context)


async def _handle_keyword_list(query, context):
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)

    if not keywords:
        text = (
            "📑 <b>关键词列表</b>\n\n"
            "暂无已配置关键词。\n"
            "点击下方按钮添加关键词。"
        )
    else:
        text = f"📑 <b>关键词列表</b>\n\n共有 <b>{len(keywords)}</b> 条关键词：\n\n"
        for i, kw in enumerate(keywords, 1):
            reply_preview = kw.reply_text[:30] + "..." if len(kw.reply_text) > 30 else kw.reply_text
            text += f"{i}. <b>{kw.keyword}</b>\n   回复: {reply_preview}\n\n"
            if i >= 10:
                remaining = len(keywords) - 10
                if remaining > 0:
                    text += f"... 还有 {remaining} 条关键词\n"
                break

    keyboard = [
        [InlineKeyboardButton("➕ 添加关键词", callback_data="keyword:add")],
        [InlineKeyboardButton("🔙 返回", callback_data="keyword:show")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _handle_keyword_delete(query, context, keyword: str):
    from ..services.custom_keyword_service import CustomKeywordService
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    success = await CustomKeywordService.delete_keyword(bot_id, keyword, group_id=0)
    if success:
        await query.answer(f"✅ 关键词「{keyword}」已删除", show_alert=False)
    else:
        await query.answer("❌ 删除失败", show_alert=False)
    await _handle_keyword_list(query, context)


async def handle_edit_mode_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ..utils.state_manager import (
        get_edit_state,
        clear_edit_state,
        set_edit_state,
        EDIT_STATE_ADD_KEYWORD,
        EDIT_STATE_ADD_KEYWORD_REPLY,
    )
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    state, data = await get_edit_state(context)
    if not state:
        return await _legacy_handle_edit_mode_message(update, context)

    bot_id = get_current_bot_id(context)
    user_id = update.effective_user.id

    if state == EDIT_STATE_ADD_KEYWORD:
        keyword = (update.message.text or "").strip()
        if not keyword:
            await update.message.reply_text("❌ 关键词不能为空")
            return True

        existing_keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
        if any(kw.keyword == keyword for kw in existing_keywords):
            await update.message.reply_text(
                f"❌ 关键词「{keyword}」已存在，请输入其他关键词或取消。",
                parse_mode="HTML",
            )
            return True

        await set_edit_state(context, EDIT_STATE_ADD_KEYWORD_REPLY, {"keyword": keyword})
        await update.message.reply_text(
            f"✅ 关键词「{keyword}」已记录\n\n请发送该关键词的回复内容。",
            parse_mode="HTML",
        )
        return True

    if state == EDIT_STATE_ADD_KEYWORD_REPLY:
        reply_text = update.message.text or ""
        keyword = (data or {}).get("keyword")
        if not keyword:
            await clear_edit_state(context)
            await update.message.reply_text("❌ 发生错误，请重新添加关键词。", parse_mode="HTML")
            return True

        success = await CustomKeywordService.add_keyword(
            bot_id=bot_id,
            keyword=keyword,
            reply_text=reply_text,
            group_id=0,
            created_by=user_id,
        )
        await clear_edit_state(context)

        if success:
            await update.message.reply_text(
                f"✅ <b>关键词添加成功</b>\n\n"
                f"关键词：<b>{keyword}</b>\n"
                f"回复：{reply_text[:50]}{'...' if len(reply_text) > 50 else ''}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_back")],
                ]),
            )
        else:
            await update.message.reply_text("❌ 添加关键词失败，请稍后重试。", parse_mode="HTML")
        return True

    return await _legacy_handle_edit_mode_message(update, context)


# ============================================================================
# Unified settings page overrides
# ============================================================================

async def _show_daycut_page(query, context):
    from sqlalchemy import select, func
    from ..services.global_config_service import global_config_service
    from ..models import Group, get_db_session
    from ..models.enums import GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    temp_selected = context.user_data.get("daycut_temp_selected", False)
    temp_hour = context.user_data.get("daycut_temp_hour")

    async with get_db_session() as db:
        enabled_conf = await global_config_service.get_config(db, bot_id, "daily_day_cut_enabled")
        hour_conf = await global_config_service.get_config(db, bot_id, "day_cut_hour")
        result = await db.execute(
            select(func.count()).select_from(Group).where(
                Group.bot_id == bot_id,
                Group.status == GroupStatus.ACTIVE,
            )
        )
        group_count = result.scalar() or 0

    is_enabled = enabled_conf if isinstance(enabled_conf, bool) else False
    saved_hour = hour_conf if isinstance(hour_conf, int) else 0
    current_hour = temp_hour if temp_selected and temp_hour is not None else saved_hour
    time_display = f"{current_hour:02d}:00"
    if temp_selected:
        time_display += "（未保存）"

    text = (
        "📅 <b>全局日切设置</b>\n\n"
        f"状态：{ui_renderer.format_status(enabled=is_enabled)}\n"
        f"当前日切时间：{time_display}\n"
        f"应用到：{group_count} 个群组\n\n"
        "请选择全局统一日切时间："
    )

    keyboard = [[InlineKeyboardButton(f"⏰ 已选：{current_hour:02d}:00", callback_data="daycut:select_time")]]
    if is_enabled or temp_selected:
        keyboard.append([
            InlineKeyboardButton("✅ 保存并启用", callback_data="daycut:save"),
            InlineKeyboardButton("⚪ 已关闭", callback_data="daycut:disable_confirm"),
        ])
    else:
        keyboard.append([InlineKeyboardButton("🟢 已开启", callback_data="daycut:enable_confirm")])
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _show_display_page(query, context):
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    temp_deposit = context.user_data.get("display_temp_deposit")
    temp_withdraw = context.user_data.get("display_temp_withdraw")

    async with get_db_session() as db:
        deposit_count = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_count = await global_config_service.get_config(db, bot_id, "withdraw_display_count")

    saved_deposit = deposit_count if isinstance(deposit_count, int) else 10
    saved_withdraw = withdraw_count if isinstance(withdraw_count, int) else 10
    current_deposit = temp_deposit if temp_deposit is not None else saved_deposit
    current_withdraw = temp_withdraw if temp_withdraw is not None else saved_withdraw

    deposit_display = f"{current_deposit} 条"
    withdraw_display = f"{current_withdraw} 条"
    if temp_deposit is not None and temp_deposit != saved_deposit:
        deposit_display += "（未保存）"
    if temp_withdraw is not None and temp_withdraw != saved_withdraw:
        withdraw_display += "（未保存）"

    text = (
        "📊 <b>全局记账条数设置</b>\n\n"
        f"入款显示条数：{deposit_display}\n"
        f"下发显示条数：{withdraw_display}\n\n"
        "请选择要调整的全局显示条数："
    )

    keyboard = [[
        InlineKeyboardButton(f"📥 入款：{current_deposit}", callback_data="display:select_deposit"),
        InlineKeyboardButton(f"📤 下发：{current_withdraw}", callback_data="display:select_withdraw"),
    ]]
    keyboard.append([InlineKeyboardButton("✅ 保存设置", callback_data="display:save")])
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _show_welcome_page(query, context):
    from ..services.global_config_service import global_config_service
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        welcome_enabled = await global_config_service.get_config(db, bot_id, "welcome_ad_enabled")
        welcome_delete_prev = await global_config_service.get_config(db, bot_id, "welcome_delete_prev")
        welcome_delete_minutes = await global_config_service.get_config(db, bot_id, "welcome_delete_minutes")
        welcome_message = await global_config_service.get_config(db, bot_id, "welcome_message")
        welcome_has_media = await global_config_service.get_config(db, bot_id, "welcome_has_media")
        welcome_has_buttons = await global_config_service.get_config(db, bot_id, "welcome_has_buttons")

    is_enabled = bool(welcome_enabled) if isinstance(welcome_enabled, bool) else False
    delete_prev = bool(welcome_delete_prev) if isinstance(welcome_delete_prev, bool) else False
    delete_minutes = welcome_delete_minutes if isinstance(welcome_delete_minutes, int) else 0
    has_media = bool(welcome_has_media) if isinstance(welcome_has_media, bool) else False
    has_buttons = bool(welcome_has_buttons) if isinstance(welcome_has_buttons, bool) else False
    has_text = bool(isinstance(welcome_message, str) and welcome_message)

    text = (
        "🎉 <b>进群欢迎</b>\n\n"
        f"状态：{ui_renderer.format_status(enabled=is_enabled)}\n\n"
        f"删除消息(分钟)：{'删除上一条' if delete_prev else delete_minutes if delete_minutes else '否'}\n\n"
        "自定义欢迎内容：\n"
        f"🖼️ 媒体图片：{'🟢 已开启' if has_media else '🟡 未配置'}\n"
        f"🔗 链接按钮：{'🟢 已开启' if has_buttons else '🟡 未配置'}\n"
        f"📝 文本内容：{'🟢 已开启' if has_text else '🟡 未配置'}"
    )

    keyboard = [
        [
            InlineKeyboardButton("🟢 已开启" if is_enabled else "开启", callback_data="welcome:enable"),
            InlineKeyboardButton("⚪ 已关闭" if not is_enabled else "关闭", callback_data="welcome:disable"),
        ],
        [
            InlineKeyboardButton("🟢 否" if delete_minutes == 0 and not delete_prev else "否", callback_data="welcome:delete:0"),
            InlineKeyboardButton("🟢 1" if delete_minutes == 1 and not delete_prev else "1", callback_data="welcome:delete:1"),
            InlineKeyboardButton("🟢 5" if delete_minutes == 5 and not delete_prev else "5", callback_data="welcome:delete:5"),
            InlineKeyboardButton("🟢 10" if delete_minutes == 10 and not delete_prev else "10", callback_data="welcome:delete:10"),
        ],
        [InlineKeyboardButton("🟢 删除上一条" if delete_prev else "删除上一条", callback_data="welcome:delete_prev")],
        [InlineKeyboardButton("👁 预览消息", callback_data="welcome:preview")],
        [
            InlineKeyboardButton("📝 修改文本", callback_data="welcome:edit_text"),
            InlineKeyboardButton("🖼️ 修改媒体", callback_data="welcome:edit_media"),
        ],
        [InlineKeyboardButton("🔗 修改按钮", callback_data="welcome:edit_buttons")],
    ]
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _show_keyword_page(query, context):
    from ..services.global_config_service import global_config_service
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        keyword_enabled = await global_config_service.get_config(db, bot_id, "keyword_reply_enabled")
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
    keyword_count = len(keywords)
    is_enabled = keyword_enabled if isinstance(keyword_enabled, bool) else True

    text = (
        "🔑 <b>关键词回复</b>\n\n"
        f"状态：{ui_renderer.format_status(enabled=is_enabled)}\n"
        f"已设置 <b>{keyword_count}</b> 条关键词\n\n"
        "点击下方按钮管理关键词回复。"
    )
    keyboard = [
        [
            InlineKeyboardButton("🟢 已开启" if is_enabled else "开启", callback_data="keyword:enable"),
            InlineKeyboardButton("⚪ 已关闭" if not is_enabled else "关闭", callback_data="keyword:disable"),
        ],
        [
            InlineKeyboardButton("📑 关键词列表", callback_data="keyword:list"),
            InlineKeyboardButton("➕ 添加关键词", callback_data="keyword:add"),
        ],
    ]
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _show_admin_page(query, context):
    from sqlalchemy import select
    from ..models import Admin, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        result = await db.execute(select(Admin).where(Admin.bot_id == bot_id, Admin.is_active.is_(True)))
        admins = result.scalars().all()

    text = f"👥 <b>管理员管理</b>\n\n当前管理员总数：{len(admins)} 人\n\n"
    if admins:
        text += "👇 管理员列表：\n"
        for idx, admin in enumerate(admins, 1):
            name = f"@{admin.username}" if admin.username else str(admin.user_id)
            text += f"{idx}. {name}\n"
    else:
        text += "暂无管理员\n"
    text += "\n👇 请选择操作："

    keyboard = [[
        InlineKeyboardButton("➕ 添加管理员", callback_data="admin:add:start"),
        InlineKeyboardButton("🗑️ 删除管理员", callback_data="admin:delete:list"),
    ]]
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _show_auth_group_page(query, context, page=1, show_authorized=True):
    from sqlalchemy import select, func, or_
    from ..models import Group, get_db_session
    from ..models.enums import GroupStatus
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    page_size = 5
    async with get_db_session() as db:
        authorized_count = (await db.execute(
            select(func.count()).select_from(Group).where(
                Group.bot_id == bot_id, Group.status == GroupStatus.ACTIVE
            )
        )).scalar() or 0
        unauthorized_count = (await db.execute(
            select(func.count()).select_from(Group).where(
                Group.bot_id == bot_id,
                or_(
                    Group.status == GroupStatus.PENDING,
                    Group.status == GroupStatus.UNAUTHORIZED,
                    Group.status == GroupStatus.DISABLED,
                    Group.status == GroupStatus.EXPIRED,
                ),
            )
        )).scalar() or 0

        if show_authorized:
            total_count = authorized_count
            base_query = select(Group).where(Group.bot_id == bot_id, Group.status == GroupStatus.ACTIVE)
            list_title = "🟢 已开启"
            batch_action_text = "取消当前页授权"
            batch_action_callback = "authgroup:batch_unauthorize_confirm"
        else:
            total_count = unauthorized_count
            base_query = select(Group).where(
                Group.bot_id == bot_id,
                or_(
                    Group.status == GroupStatus.PENDING,
                    Group.status == GroupStatus.UNAUTHORIZED,
                    Group.status == GroupStatus.DISABLED,
                    Group.status == GroupStatus.EXPIRED,
                ),
            )
            list_title = "🔴 已禁用"
            batch_action_text = "授权当前页群组"
            batch_action_callback = "authgroup:batch_authorize_confirm"

        total_pages = max(1, (total_count + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size
        groups = list((await db.execute(
            base_query.order_by(Group.created_at.desc()).offset(offset).limit(page_size)
        )).scalars().all())

    text = (
        "📡 <b>授权群组管理</b>\n\n"
        f"已授权：{authorized_count} 个｜未授权：{unauthorized_count} 个\n"
        f"当前：{list_title} 第 {page}/{total_pages} 页\n\n"
    )
    if groups:
        for index, group in enumerate(groups, offset + 1):
            text += f"{index}. {group.group_name or f'群组 {group.group_id}'}\n"
    else:
        text += "暂无群组\n"

    keyboard: list[list[InlineKeyboardButton]] = []
    pagination_row = ui_renderer.build_pagination_row(
        page,
        total_pages,
        f"authgroup:page:{page - 1}:{show_authorized}" if page > 1 else None,
        f"authgroup:page:{page + 1}:{show_authorized}" if page < total_pages else None,
    )
    if pagination_row:
        keyboard.append(pagination_row)
    if groups:
        keyboard.append([InlineKeyboardButton(batch_action_text, callback_data=batch_action_callback)])
    keyboard.append([
        InlineKeyboardButton("🟢 已开启", callback_data="authgroup:noop" if show_authorized else "authgroup:switch:True"),
        InlineKeyboardButton("🔴 已禁用", callback_data="authgroup:switch:False" if show_authorized else "authgroup:noop"),
    ])
    ui_renderer.append_standard_footer(keyboard, "settings:main")
    context.user_data["authgroup_current_page"] = page
    context.user_data["authgroup_show_authorized"] = show_authorized
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _handle_keyword_add(query, context):
    from ..utils.state_manager import set_edit_state, EDIT_STATE_ADD_KEYWORD
    from ..core.ui_renderer import ui_renderer

    await set_edit_state(context, EDIT_STATE_ADD_KEYWORD)
    text = (
        "🔑 <b>添加关键词</b>\n\n"
        "请先发送关键词，随后再发送回复内容。\n\n"
        "发送后会自动校验并保存。"
    )
    keyboard = []
    ui_renderer.append_standard_footer(keyboard, "keyword:show")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def _handle_keyword_list(query, context):
    from ..services.custom_keyword_service import CustomKeywordService
    from ..models import get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)
    async with get_db_session() as db:
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)

    if not keywords:
        text = "🔑 <b>关键词回复</b>\n\n🟡 未配置\n\n点击下方按钮添加关键词。"
    else:
        text = f"🔑 <b>关键词回复</b>\n\n已设置 <b>{len(keywords)}</b> 条关键词：\n\n"
        for keyword in keywords[:5]:
            preview = keyword.reply_text[:30] + ("..." if len(keyword.reply_text) > 30 else "")
            text += f"• <b>{keyword.keyword}</b>\n  {preview}\n"
    keyboard = [[InlineKeyboardButton("➕ 添加关键词", callback_data="keyword:add")]]
    ui_renderer.append_standard_footer(keyboard, "keyword:show")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

"""
UI Schema 路由注册器

职责：
1. 将 UI Schema 页面映射到 Runtime Router 路由
2. 自动注册动态菜单 handler
3. 支持热更新 Schema
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from .ui_renderer import ui_renderer
from .runtime_router import runtime_router
from ..services.tenant_context import tenant_context_manager, TenantContext
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)


async def _render_page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext, page: str):
    """
    通用页面渲染 Handler
    
    Args:
        update: Telegram Update
        context: Telegram Context
        tenant_context: 租户上下文
        page: 页面标识
    """
    await ui_renderer.render_page(
        update=update,
        context=context,
        page=page,
        tenant_context=tenant_context
    )


def register_ui_schema_routes():
    """
    注册所有 UI Schema 路由到 Runtime Router
    
    这个函数应该在 bot_factory.py 的 _register_handlers 中调用
    """
    
    # === 主菜单 ===
    async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        await _render_page_handler(update, context, tenant_context, "main_menu")
    
    runtime_router.register_route("v1:menu:main", main_menu_handler)
    logger.info("Registered UI schema route: v1:menu:main")
    
    # === 个人中心 ===
    async def personal_center_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        个人中心 Handler - 适配旧架构

        新架构：先渲染 UI Schema 页面，然后由 Runtime Router 处理后续按钮点击
        """
        try:
            from ..handlers.menu_callbacks import handle_personal_center
            await handle_personal_center(update, context)
        except Exception as e:
            logger.error(f"[personal_center_handler] Error: {e}", exc_info=True)
            try:
                if update.callback_query:
                    await update.callback_query.answer("加载个人中心失败，请稍后重试", show_alert=True)
                elif update.message:
                    await update.message.reply_text("加载个人中心失败，请稍后重试")
            except Exception:
                pass

    runtime_router.register_route("v1:menu:personal_center", personal_center_handler)
    logger.info("Registered UI schema route: v1:menu:personal_center")
    
    # === 使用说明 ===
    async def usage_guide_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        使用说明 Handler - 适配旧架构
        """
        from ..handlers.menu_callbacks import handle_usage_guide
        await handle_usage_guide(update, context)
    
    runtime_router.register_route("v1:menu:usage_guide", usage_guide_handler)
    logger.info("Registered UI schema route: v1:menu:usage_guide")
    
    # === 联系客服 ===
    async def contact_support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        联系客服 Handler - 适配旧架构
        """
        from ..handlers.menu_callbacks import handle_contact_support
        await handle_contact_support(update, context)
    
    runtime_router.register_route("v1:menu:contact_support", contact_support_handler)
    logger.info("Registered UI schema route: v1:menu:contact_support")

    # === 申请试用 ===
    async def apply_trial_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        申请试用 Handler - 普通用户点击申请试用按钮
        """
        from ..handlers.menu_callbacks import handle_apply_trial
        await handle_apply_trial(update, context)

    runtime_router.register_route("v1:menu:apply_trial", apply_trial_handler)
    logger.info("Registered UI schema route: v1:menu:apply_trial")

    # === 旧群发广播兼容入口（重定向到用户广播） ===
    async def broadcast_send_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        旧群发广播兼容 Handler - 统一重定向到新的用户广播入口
        """
        from ..handlers import menu

        if update.callback_query:
            await update.callback_query.answer("旧版群发广播已下线，请使用“用户广播”。", show_alert=True)
            await menu._show_broadcast_users_page(update.callback_query, context)
        elif update.message:
            await update.message.reply_text("旧版群发广播已下线，请从功能设置进入“用户广播”。")
    
    runtime_router.register_route("v1:broadcast:send", broadcast_send_handler)
    logger.info("Registered UI schema route: v1:broadcast:send")
    
    # === 能量 TRX ===
    async def energy_trx_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        能量 TRX Handler
        """
        text = (
            "⚡ <b>能量TRX兑换</b>\n\n"
            "💡 功能说明：\n"
            "• 提供TRX能量兑换服务\n"
            "• 支持多种兑换方式\n"
            "• 自动到账，无需等待\n\n"
            "🔧 此功能正在开发中，敬请期待！"
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        elif update.message:
            await update.message.reply_text(text, parse_mode="HTML")
    
    runtime_router.register_route("v1:energy:trx", energy_trx_handler)
    logger.info("Registered UI schema route: v1:energy:trx")
    
    # === USDT 监听 ===
    async def usdt_monitor_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        USDT 监听 Handler - 新版用户级监听
        """
        from ..handlers.usdt_monitor import handle_usdt_monitor
        await handle_usdt_monitor(update, context, tenant_context)
    
    runtime_router.register_route("v1:usdt:monitor", usdt_monitor_handler)
    logger.info("Registered UI schema route: v1:usdt:monitor (new user-level monitoring)")
    
    # === 创建机器人/续费 统一入口 ===
    async def create_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        创建续费 Handler - 统一入口（SaaS 自动售卖）
        根据用户是否已创建 Bot 自动判断走创建流程还是续费流程
        """
        from ..handlers.saas_purchase import handle_create_renew_entry
        await handle_create_renew_entry(update, context)
    
    runtime_router.register_route("v1:saas:create_bot", create_bot_handler)
    logger.info("Registered UI schema route: v1:saas:create_bot (unified create/renew entry)")
    
    # === 分组管理 ===
    async def group_manage_adapter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        分组管理 Handler - 使用新的 GroupTag 系统
        """
        from ..handlers.basic import handle_group_manage
        await handle_group_manage(update, context)
    
    runtime_router.register_route("v1:group:manage", group_manage_adapter_handler)
    logger.info("Registered UI schema route: v1:group:manage (GroupTag system)")
    
    # === 功能设置 ===
    async def settings_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        功能设置 Handler - 适配旧架构
        """
        from ..handlers.menu_callbacks import handle_settings
        try:
            await handle_settings(update, context)
        except Exception as e:
            logger.error(f"[settings_main_handler] Error: {e}", exc_info=True)
            # 异常兜底：返回友好提示
            error_text = "⚠️ 加载功能设置菜单时出现错误，请稍后重试或联系客服。"
            try:
                if update.callback_query:
                    await update.callback_query.answer(error_text, show_alert=True)
                elif update.message:
                    await update.message.reply_text(error_text)
            except Exception as inner_e:
                logger.error(f"[settings_main_handler] Failed to send error message: {inner_e}")
    
    runtime_router.register_route("v1:settings:main", settings_main_handler)
    logger.info("Registered UI schema route: v1:settings:main (adapter)")
    
    # === 广播用户 ===
    async def broadcast_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        广播用户 Handler - 新架构内联菜单版本
        支持权限分级：超级管理员/Bot创建者/无权限
        """
        from ..handlers import menu
        
        query = update.callback_query
        if query:
            await query.answer()
            await menu._show_broadcast_users_page(query, context)
        else:
            # 🔥 关键修复：如果是消息触发的（从菜单点击），直接根据权限显示对应内容
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            from ..handlers import menu
            
            # 获取用户角色
            from ..utils.role_checker import get_user_role, UserRole
            from ..utils.bot_id_middleware import get_current_bot_id
            
            user = update.effective_user
            bot_id = get_current_bot_id(context)
            user_role = await get_user_role(user.id, bot_id=bot_id)
            
            # 清空之前的状态
            menu._clear_broadcast_users_state(context)
            
            if user_role == UserRole.SUPER_ADMIN:
                # 🔥 超级管理员：直接显示两个内联按钮
                keyboard = [
                    [InlineKeyboardButton("📢 向此bot用户广播", callback_data="broadcast_users:mode:this_bot"),
                     InlineKeyboardButton("📢 向所有bot用户广播", callback_data="broadcast_users:mode:all_bots")],
                    [InlineKeyboardButton("◀ 返回主菜单", callback_data="menu_back")]
                ]
                text = (
                    "📢 <b>广播用户</b>\n\n"
                    "请选择广播目标："
                )
                reply_markup = InlineKeyboardMarkup(keyboard)
                sent_message = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
                context.user_data['last_menu_message_id'] = sent_message.message_id
                
            elif user_role == UserRole.BOT_OWNER:
                # 🔥 Bot创建者：直接显示一个内联按钮
                keyboard = [
                    [InlineKeyboardButton("📢 向此bot用户广播", callback_data="broadcast_users:mode:this_bot")],
                    [InlineKeyboardButton("◀ 返回主菜单", callback_data="menu_back")]
                ]
                text = (
                    "📢 <b>广播用户</b>\n\n"
                    "请选择广播目标："
                )
                reply_markup = InlineKeyboardMarkup(keyboard)
                sent_message = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
                context.user_data['last_menu_message_id'] = sent_message.message_id
                
            else:
                # 无权限用户
                sent_message = await update.message.reply_text(
                    "❌ <b>权限不足</b>\n\n"
                    "你没有使用广播功能的权限，请联系管理员。",
                    parse_mode="HTML"
                )
                context.user_data['last_menu_message_id'] = sent_message.message_id
    
    runtime_router.register_route("v1:broadcast:users", broadcast_users_handler)
    logger.info("Registered UI schema route: v1:broadcast:users (new inline menu version)")
    
    # === 运行统计 ===
    async def stats_runtime_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        运行统计 Handler - 适配旧架构
        仅超级管理员、Bot创建者、管理员可用
        """
        from ..handlers.menu_callbacks import handle_runtime_stats
        await handle_runtime_stats(update, context)
    
    runtime_router.register_route("v1:stats:runtime", stats_runtime_handler)
    logger.info("Registered UI schema route: v1:stats:runtime (adapter)")
    
    # === 全局日切设置 ===
    async def settings_daycut_global_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        全局日切设置 Handler - 适配旧架构
        仅超级管理员、Bot创建者、管理员可用
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from ..services.global_config_service import global_config_service
        from ..models import get_db_session
        from ..utils.bot_id_middleware import get_current_bot_id
        
        user = update.effective_user
        bot_id = get_current_bot_id(context)
        
        async with get_db_session() as db:
            current_time = await global_config_service.get_config(db, bot_id, "day_cut_time")
            is_enabled = await global_config_service.get_config(db, bot_id, "day_cut_enabled")
            
            if isinstance(is_enabled, dict):
                is_enabled = is_enabled.get("enabled", False)
            elif isinstance(is_enabled, bool):
                pass
            else:
                is_enabled = False
            
            status = "✅ 已启用" if is_enabled else "❌ 未启用"
            current_time = current_time if current_time else "00:00"
            
            text = (
                f"✂️ <b>全局日切设置</b>\n\n"
                f"📊 当前状态: {status}\n"
                f"⏰ 日切时间: <code>{current_time}</code>\n\n"
                f"💡 <b>功能说明：</b>\n"
                f"• 设置每日定时切换账单的时间\n"
                f"• 对所有授权群组生效\n"
                f"• 切换时间后，旧账单归档，新账单开始记录\n\n"
                f"🔧 请发送您想要设置的日切时间（格式：HH:MM，如 00:00 或 03:00）"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔄 切换日切状态", callback_data="settings_daycut_toggle")],
                [InlineKeyboardButton("🔙 返回功能设置", callback_data="settings_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
            elif update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
            
            context.user_data['waiting_for'] = 'daycut_time_global'
    
    runtime_router.register_route("v1:settings:daycut_global", settings_daycut_global_handler)
    logger.info("Registered UI schema route: v1:settings:daycut_global (adapter)")
    
    # === 全局记账条数设置 ===
    async def settings_display_count_global_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        全局记账条数设置 Handler - 适配旧架构
        仅超级管理员、Bot创建者、管理员可用
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from ..services.global_config_service import global_config_service
        from ..models import get_db_session
        from ..utils.bot_id_middleware import get_current_bot_id
        
        user = update.effective_user
        bot_id = get_current_bot_id(context)
        
        async with get_db_session() as db:
            deposit_count = await global_config_service.get_config(db, bot_id, "deposit_display_count")
            withdraw_count = await global_config_service.get_config(db, bot_id, "withdraw_display_count")
            deposit_count = deposit_count if isinstance(deposit_count, int) else 10
            withdraw_count = withdraw_count if isinstance(withdraw_count, int) else 10
            
            text = (
                f"📊 <b>全局记账条数设置</b>\n\n"
                f"📝 当前入款显示条数: <code>{deposit_count}</code> 条\n"
                f"📝 当前下发显示条数: <code>{withdraw_count}</code> 条\n\n"
                f"💡 <b>功能说明：</b>\n"
                f"• 设置全局默认的记账显示条数\n"
                f"• 对所有授权群组生效\n"
                f"• 群组可单独覆盖此设置\n\n"
                f"🔧 请发送您想要设置的记账条数（1-100）"
            )
            
            keyboard = [[InlineKeyboardButton("🔙 返回功能设置", callback_data="settings_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
            elif update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
            
            context.user_data['waiting_for'] = 'display_count_global'
    
    runtime_router.register_route("v1:settings:display_count_global", settings_display_count_global_handler)
    logger.info("Registered UI schema route: v1:settings:display_count_global (adapter)")
    
    # === 全局记账成员名字显示 ===
    async def settings_show_name_global_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        全局记账成员名字显示 Handler - 开关按钮式布局
        仅超级管理员、Bot创建者、管理员可用
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from ..services.global_config_service import global_config_service
        from ..models import get_db_session
        from ..utils.bot_id_middleware import get_current_bot_id
        
        user = update.effective_user
        bot_id = get_current_bot_id(context)
        
        # 获取临时状态（如果有）
        temp_deposit_name = context.user_data.get('temp_deposit_name')
        temp_withdraw_name = context.user_data.get('temp_withdraw_name')
        has_unsaved_changes = temp_deposit_name is not None or temp_withdraw_name is not None
        
        async with get_db_session() as db:
            # 获取当前配置（使用与 menu.py 一致的配置键）
            deposit_config = await global_config_service.get_config(db, bot_id, "deposit_show_name")
            withdraw_config = await global_config_service.get_config(db, bot_id, "withdraw_show_name")
            
            deposit_enabled = deposit_config if isinstance(deposit_config, bool) else True
            withdraw_enabled = withdraw_config if isinstance(withdraw_config, bool) else True
            
            # 使用临时状态（如果有）
            if temp_deposit_name is not None:
                deposit_enabled = temp_deposit_name
            if temp_withdraw_name is not None:
                withdraw_enabled = temp_withdraw_name
            
            # 按钮状态显示
            deposit_status = "✅ 开启" if deposit_enabled else "❌ 关闭"
            withdraw_status = "✅ 开启" if withdraw_enabled else "❌ 关闭"
            
            # 未保存标记
            unsaved_mark = " （未保存）" if has_unsaved_changes else ""
            
            text = (
                f"👤 <b>全局记账成员名字显示</b>{unsaved_mark}\n\n"
                f"当前配置：\n"
                f"入款显示名字：{'✅ 已开启' if deposit_enabled else '❌ 已关闭'}\n"
                f"下发显示名字：{'✅ 已开启' if withdraw_enabled else '❌ 已关闭'}\n\n"
                f"👇 点击按钮切换状态（修改后需保存生效）"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton(f"🧾 入款名字显示：{deposit_status}", callback_data="showname:toggle:deposit")
                ],
                [
                    InlineKeyboardButton(f"💸 下发名字显示：{withdraw_status}", callback_data="showname:toggle:withdraw")
                ],
                [InlineKeyboardButton("✅ 保存设置", callback_data="showname:save:v2")],
                [InlineKeyboardButton("🔙 返回", callback_data="settings_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
            elif update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    runtime_router.register_route("v1:settings:show_name_global", settings_show_name_global_handler)
    logger.info("Registered UI schema route: v1:settings:show_name_global (adapter)")
    
    # === 全局入群欢迎语 ===
    async def settings_welcome_global_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        全局入群欢迎语 Handler - 适配旧架构
        仅超级管理员、Bot创建者、管理员可用
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from ..services.global_config_service import global_config_service
        from ..models import get_db_session
        from ..utils.bot_id_middleware import get_current_bot_id
        
        user = update.effective_user
        bot_id = get_current_bot_id(context)
        
        async with get_db_session() as db:
            welcome_message = await global_config_service.get_config(db, bot_id, "welcome_message")
            is_enabled = await global_config_service.get_config(db, bot_id, "welcome_ad_enabled")
            
            if isinstance(is_enabled, dict):
                is_enabled = is_enabled.get("enabled", False)
            elif isinstance(is_enabled, bool):
                pass
            else:
                is_enabled = False
            
            status = "✅ 已启用" if is_enabled else "❌ 未启用"
            welcome_message = welcome_message if welcome_message else "欢迎入群！"
            
            text = (
                f"👋 <b>全局入群欢迎语</b>\n\n"
                f"📊 当前状态: {status}\n"
                f"💬 当前欢迎语: <code>{welcome_message}</code>\n\n"
                f"💡 <b>功能说明：</b>\n"
                f"• 设置新用户入群时的欢迎消息\n"
                f"• 对所有授权群组生效\n"
                f"• 群组可单独覆盖此设置\n\n"
                f"🔧 请发送您想要设置的欢迎语"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔄 切换状态", callback_data="settings_welcome_toggle")],
                [InlineKeyboardButton("🔙 返回功能设置", callback_data="settings_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
            elif update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
            
            context.user_data['waiting_for'] = 'welcome_global'
    
    runtime_router.register_route("v1:settings:welcome_global", settings_welcome_global_handler)
    logger.info("Registered UI schema route: v1:settings:welcome_global (adapter)")
    
    # === 全局关键词设置 ===
    async def settings_keyword_global_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        全局关键词设置 Handler - 适配旧架构
        仅超级管理员、Bot创建者、管理员可用
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from ..services.global_config_service import global_config_service
        from ..models import get_db_session
        from ..utils.bot_id_middleware import get_current_bot_id
        
        user = update.effective_user
        bot_id = get_current_bot_id(context)
        
        async with get_db_session() as db:
            is_enabled = await global_config_service.get_config(db, bot_id, "keyword_reply_enabled")
            
            if isinstance(is_enabled, dict):
                is_enabled = is_enabled.get("enabled", False)
            elif isinstance(is_enabled, bool):
                pass
            else:
                is_enabled = False
            
            status = "✅ 已启用" if is_enabled else "❌ 未启用"
            
            text = (
                f"💬 <b>全局关键词设置</b>\n\n"
                f"📊 当前状态: {status}\n\n"
                f"💡 <b>功能说明：</b>\n"
                f"• 设置关键词自动回复功能\n"
                f"• 可以配置多个关键词和对应的回复内容\n"
                f"• 对所有授权群组生效\n"
                f"• 群组可单独覆盖此设置\n\n"
                f"🔧 请发送您的选择：\n"
                f"• <code>启用关键词</code> - 启用关键词回复\n"
                f"• <code>禁用关键词</code> - 禁用关键词回复"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔄 切换状态", callback_data="settings_keyword_toggle")],
                [InlineKeyboardButton("🔧 管理关键词", callback_data="settings_keyword_manage")],
                [InlineKeyboardButton("🔙 返回功能设置", callback_data="settings_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
            elif update.callback_query:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
            
            context.user_data['waiting_for'] = 'keyword_global'
    
    runtime_router.register_route("v1:settings:keyword_global", settings_keyword_global_handler)
    logger.info("Registered UI schema route: v1:settings:keyword_global (adapter)")
    
    # === 群组&成员设置（监听昵称、用户名、冒充管理员） ===
    async def settings_rename_notification_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        群组&成员设置 Handler - 新版三个功能独立控制
        """
        from ..handlers.menu import _show_group_member_page
        from telegram import Update
        
        # 使用 callback_query 或创建模拟的 query
        if update.callback_query:
            await _show_group_member_page(update.callback_query, context)
        elif update.message:
            class FakeQuery:
                def __init__(self, message, user):
                    self.message = message
                    self.from_user = user
                async def edit_message_text(self, **kwargs):
                    await self.message.reply_text(**kwargs)
            
            fake_query = FakeQuery(update.message, update.effective_user)
            await _show_group_member_page(fake_query, context)
    
    runtime_router.register_route("v1:settings:rename_notification", settings_rename_notification_handler)
    logger.info("Registered UI schema route: v1:settings:rename_notification (new group member settings)")
    
    # === 添加管理员 ===
    async def admin_add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        添加管理员 Handler - 适配旧架构
        仅超级管理员和Bot创建者可用
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        text = (
            f"👥 <b>添加管理员</b>\n\n"
            f"💡 <b>功能说明：</b>\n"
            f"• 添加新的管理员来协助管理Bot\n"
            f"• 管理员可以管理群组和查看统计数据\n\n"
            f"🔧 请发送您要添加的管理员的用户名或用户ID"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 返回功能设置", callback_data="settings_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        
        context.user_data['waiting_for'] = 'admin_add'
    
    runtime_router.register_route("v1:admin:add", admin_add_handler)
    logger.info("Registered UI schema route: v1:admin:add (adapter)")
    
    # === 授权群组 ===
    async def admin_authorize_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        授权群组 Handler - 适配旧架构
        仅超级管理员和Bot创建者可用
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        text = (
            f"🔐 <b>授权群组</b>\n\n"
            f"💡 <b>功能说明：</b>\n"
            f"• 授权新的群组使用Bot\n"
            f"• 可以管理已授权的群组列表\n\n"
            f"🔧 请发送您要授权的群组的链接或ID"
        )
        
        keyboard = [
            [InlineKeyboardButton("📋 查看已授权群组", callback_data="admin_auth_groups_list")],
            [InlineKeyboardButton("🔙 返回功能设置", callback_data="settings_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        
        context.user_data['waiting_for'] = 'authorize_group'
    
    runtime_router.register_route("v1:admin:authorize_group", admin_authorize_group_handler)
    logger.info("Registered UI schema route: v1:admin:authorize_group (adapter)")

    # === 超级管理员功能 ===
    # 🆕 消息中心 - 直接进入，不显示中间提示页
    async def super_admin_message_center_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """消息中心 Handler"""
        from ..handlers.super_admin_v2_handler import show_message_center
        # 直接调用消息中心主逻辑
        await show_message_center(update, context)

    runtime_router.register_route("v1:super_admin:message_center", super_admin_message_center_handler)
    logger.info("Registered UI schema route: v1:super_admin:message_center")

    # 🆕 超管后台 - 直接进入，不显示中间提示页
    async def super_admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """超管后台 Handler"""
        from ..handlers.super_admin_v2_handler import show_super_admin_panel
        # 直接调用超管后台主逻辑
        await show_super_admin_panel(update, context)

    runtime_router.register_route("v1:super_admin:panel", super_admin_panel_handler)
    logger.info("Registered UI schema route: v1:super_admin:panel")

    logger.info("✅ All UI schema routes registered successfully")


def register_custom_ui_schema(page: str, handler_func):
    """
    注册自定义 UI Schema 页面
    
    Args:
        page: 页面标识
        handler_func: 自定义 handler 函数，签名：async def handler(update, context, tenant_context)
    """
    route_name = f"v1:{page.replace('_', ':')}"
    runtime_router.register_route(route_name, handler_func)
    logger.info(f"Registered custom UI schema route: {route_name}")

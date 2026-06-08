"""
动态菜单处理器（使用 UI Schema Engine）

展示如何使用 UI Schema 渲染动态菜单
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from ..core.ui_renderer import ui_renderer
from ..services.tenant_context import tenant_context_manager
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理主菜单请求
    
    使用 UI Schema Engine 动态渲染菜单
    """
    try:
        # 获取 bot_id 和 user_id
        bot_id = get_current_bot_id(context)
        user_id = update.effective_user.id
        
        # 获取租户上下文
        tenant_context = await tenant_context_manager.get_tenant_context(bot_id, user_id)
        
        # 渲染主菜单页面
        await ui_renderer.render_page(
            update=update,
            context=context,
            page="main_menu",
            tenant_context=tenant_context
        )
        
        logger.info(f"Main menu rendered for user {user_id} in bot {bot_id}")
    
    except Exception as e:
        logger.error(f"Error handling main menu: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.answer("❌ 加载菜单时出现错误", show_alert=True)
        elif update.message:
            await update.message.reply_text("❌ 加载菜单时出现错误")


async def handle_group_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群组管理菜单请求
    """
    try:
        # 获取 bot_id 和 user_id
        bot_id = get_current_bot_id(context)
        user_id = update.effective_user.id
        
        # 获取租户上下文
        tenant_context = await tenant_context_manager.get_tenant_context(bot_id, user_id)
        
        # 渲染群组管理页面
        await ui_renderer.render_page(
            update=update,
            context=context,
            page="group_manage",
            tenant_context=tenant_context
        )
        
        logger.info(f"Group manage menu rendered for user {user_id} in bot {bot_id}")
    
    except Exception as e:
        logger.error(f"Error handling group manage menu: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.answer("❌ 加载菜单时出现错误", show_alert=True)
        elif update.message:
            await update.message.reply_text("❌ 加载菜单时出现错误")


async def handle_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理设置菜单请求
    """
    try:
        # 获取 bot_id 和 user_id
        bot_id = get_current_bot_id(context)
        user_id = update.effective_user.id
        
        # 获取租户上下文
        tenant_context = await tenant_context_manager.get_tenant_context(bot_id, user_id)
        
        # 渲染设置菜单页面
        await ui_renderer.render_page(
            update=update,
            context=context,
            page="settings_menu",
            tenant_context=tenant_context
        )
        
        logger.info(f"Settings menu rendered for user {user_id} in bot {bot_id}")
    
    except Exception as e:
        logger.error(f"Error handling settings menu: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.answer("❌ 加载菜单时出现错误", show_alert=True)
        elif update.message:
            await update.message.reply_text("❌ 加载菜单时出现错误")

"""
UI Renderer 中间件

职责：
1. 拦截菜单相关的请求
2. 自动加载对应的 UI Schema
3. 根据 Tenant Context 和 Feature Flag 过滤
4. 渲染成 Telegram Inline Keyboard
5. 发送消息
"""
import logging
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from .ui_schema_engine import ui_schema_engine, UISchema
from ..services.tenant_context import TenantContext

logger = logging.getLogger(__name__)


class UIRenderer:
    """
    UI 渲染器
    
    负责将 UI Schema 渲染成 Telegram 消息
    """
    
    @staticmethod
    async def render_page(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        page: str,
        tenant_context: Optional[TenantContext] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        extra_text: Optional[str] = None
    ):
        """
        渲染页面
        
        Args:
            update: Telegram Update
            context: Telegram Context
            page: 页面标识（例如：'main_menu', 'group_manage'）
            tenant_context: 租户上下文
            title: 自定义标题（可选，覆盖 Schema 中的标题）
            description: 自定义描述（可选）
            extra_text: 额外文本（可选，追加到消息末尾）
        """
        try:
            # 1. 获取 UI Schema
            schema = ui_schema_engine.get_schema(page)
            if not schema:
                logger.warning(f"UI Schema not found for page: {page}")
                await UIRenderer._send_error_message(update, context, f"❌ 页面 '{page}' 不存在")
                return
            
            # 2. 获取 Feature Flags
            feature_flags = None
            if tenant_context:
                feature_flags = tenant_context.feature_flags
            
            # 3. 渲染键盘
            keyboard = ui_schema_engine.render_keyboard(schema, tenant_context, feature_flags)
            
            # 4. 构建消息文本
            message_text = UIRenderer._build_message_text(schema, title, description, extra_text)
            
            # 5. 发送消息
            await UIRenderer._send_message(update, context, message_text, keyboard)
            
            logger.info(f"Rendered page '{page}' for user {update.effective_user.id}")
        
        except Exception as e:
            logger.error(f"Error rendering page '{page}': {e}", exc_info=True)
            await UIRenderer._send_error_message(update, context, f"❌ 渲染页面时出现错误")
    
    @staticmethod
    def _build_message_text(
        schema: UISchema,
        title: Optional[str] = None,
        description: Optional[str] = None,
        extra_text: Optional[str] = None
    ) -> str:
        """
        构建消息文本
        
        Args:
            schema: UI Schema
            title: 自定义标题
            description: 自定义描述
            extra_text: 额外文本
            
        Returns:
            消息文本
        """
        parts = []
        
        # 标题
        page_title = title or schema.title or ""
        if page_title:
            parts.append(f"<b>{page_title}</b>")
        
        # 描述
        page_description = description or schema.description or ""
        if page_description:
            parts.append(page_description)
        
        # 额外文本
        if extra_text:
            parts.append(extra_text)
        
        return "\n\n".join(parts)
    
    @staticmethod
    async def _send_message(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
        keyboard: InlineKeyboardMarkup
    ):
        """
        发送消息
        
        Args:
            update: Telegram Update
            context: Telegram Context
            text: 消息文本
            keyboard: 键盘布局
        """
        if update.callback_query:
            # 如果是回调，编辑原消息
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        elif update.message:
            # 如果是新消息，发送新消息
            await update.message.reply_text(
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
    
    @staticmethod
    async def _send_error_message(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error_text: str
    ):
        """
        发送错误消息
        
        Args:
            update: Telegram Update
            context: Telegram Context
            error_text: 错误文本
        """
        if update.callback_query:
            await update.callback_query.answer(error_text, show_alert=True)
        elif update.message:
            await update.message.reply_text(error_text)

    @staticmethod
    def format_status(enabled: Optional[bool] = None, configured: bool = True, disabled: bool = False) -> str:
        if disabled:
            return "🔴 已禁用"
        if not configured:
            return "🟡 未配置"
        if enabled is True:
            return "🟢 已开启"
        return "⚪ 已关闭"

    @staticmethod
    def build_standard_footer(
        back_callback: str,
        close_callback: str = "menu:close",
    ) -> list[list[InlineKeyboardButton]]:
        return [[
            InlineKeyboardButton("⏪ 返回", callback_data=back_callback),
            InlineKeyboardButton("⛔ 关闭", callback_data=close_callback),
        ]]

    @staticmethod
    def append_standard_footer(
        keyboard: list[list[InlineKeyboardButton]],
        back_callback: str,
        close_callback: str = "menu:close",
    ) -> list[list[InlineKeyboardButton]]:
        keyboard.extend(UIRenderer.build_standard_footer(back_callback, close_callback))
        return keyboard

    @staticmethod
    def build_pagination_row(
        page: int,
        total_pages: int,
        prev_callback: Optional[str],
        next_callback: Optional[str],
    ) -> list[InlineKeyboardButton]:
        row: list[InlineKeyboardButton] = []
        if total_pages <= 1:
            return row
        if page > 1 and prev_callback:
            row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=prev_callback))
        if page < total_pages and next_callback:
            row.append(InlineKeyboardButton("➡️ 下一页", callback_data=next_callback))
        return row


# 全局实例
ui_renderer = UIRenderer()

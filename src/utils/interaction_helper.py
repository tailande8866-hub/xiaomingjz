"""
前端交互优化工具模块

提供：
- 加载动画显示
- 改进的错误提示
- 确认对话框
- 用户友好的消息格式化
"""
import logging
from typing import Optional, List, Tuple
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_callback_alert_patch_installed = False


def install_callback_alert_patch() -> None:
    """
    统一 CallbackQuery 弹窗样式：
    - 有文案的 callback 提示，默认强制使用居中弹窗(show_alert=True)
    - 无文案的纯 ACK 保持原样
    """
    global _callback_alert_patch_installed
    if _callback_alert_patch_installed:
        return

    original_answer = CallbackQuery.answer

    async def patched_answer(
        self,
        text: Optional[str] = None,
        show_alert: Optional[bool] = None,
        url: Optional[str] = None,
        cache_time: Optional[int] = None,
        *,
        read_timeout=None,
        write_timeout=None,
        connect_timeout=None,
        pool_timeout=None,
        api_kwargs=None,
    ):
        final_show_alert = show_alert
        if text:
            final_show_alert = True
        elif final_show_alert is None:
            final_show_alert = False

        return await original_answer(
            self,
            text=text,
            show_alert=final_show_alert,
            url=url,
            cache_time=cache_time,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
        )

    CallbackQuery.answer = patched_answer
    _callback_alert_patch_installed = True
    logger.info("CallbackQuery alert patch installed: all callback messages will use modal alerts")


# ============================================================================
# 加载动画工具
# ============================================================================

async def show_loading(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                      message: str = "⏳ 正在处理，请稍候...") -> None:
    """
    显示加载动画
    
    Args:
        update: Telegram更新对象
        context: 上下文对象
        message: 加载提示信息
        
    Example:
        >>> await show_loading(update, context, "⏳ 正在查询账单...")
    """
    if update.message:
        await update.message.reply_text(message)


async def edit_to_success(message, success_text: str) -> None:
    """
    将加载消息编辑为成功消息
    
    Args:
        message: 之前发送的消息对象
        success_text: 成功提示文本
        
    Example:
        >>> loading_msg = await update.message.reply_text("⏳ 处理中...")
        >>> # ... 执行操作 ...
        >>> await edit_to_success(loading_msg, "✅ 操作完成！")
    """
    try:
        await message.edit_text(success_text)
    except Exception as e:
        logger.warning(f"Failed to edit message: {e}")


async def edit_to_error(message, error_text: str) -> None:
    """
    将加载消息编辑为错误消息
    
    Args:
        message: 之前发送的消息对象
        error_text: 错误提示文本
        
    Example:
        >>> loading_msg = await update.message.reply_text("⏳ 处理中...")
        >>> # ... 执行操作 ...
        >>> await edit_to_error(loading_msg, "❌ 操作失败：金额无效")
    """
    try:
        await message.edit_text(error_text)
    except Exception as e:
        logger.warning(f"Failed to edit message: {e}")


# ============================================================================
# 错误提示工具
# ============================================================================

class ErrorMessages:
    """统一的错误消息管理"""
    
    # 权限相关
    PERMISSION_DENIED = "❌ 您没有操作权限\n\n💡 请联系管理员获取操作人权限"
    
    # 群组相关
    GROUP_NOT_ACTIVE = "❌ 该群组未开启记账功能\n\n💡 请在群组中发送 /start 命令开启记账"
    GROUP_NOT_FOUND = "❌ 未找到群组配置\n\n💡 请重新发送 /start 命令初始化"
    
    # 输入验证
    INVALID_AMOUNT = "❌ 金额无效\n\n💡 请输入正数，例如：+100 或 +100.5"
    NEGATIVE_AMOUNT = "❌ 金额不能为负数\n\n💡 入款请使用 +金额，下发请使用 -金额"
    INVALID_EXCHANGE_RATE = "❌ 汇率无效\n\n💡 请输入0-999之间的数字，例如：7.3"
    INVALID_FEE_RATE = "❌ 费率无效\n\n💡 请输入0-100之间的数字，例如：3.0"
    
    # 操作相关
    TRANSACTION_NOT_FOUND = "❌ 未找到对应的交易记录\n\n💡 请检查序号是否正确"
    USER_CONFIG_NOT_FOUND = "❌ 未找到用户配置\n\n💡 请先进行一笔交易以创建配置"
    
    # 系统错误
    DATABASE_ERROR = "❌ 数据库操作失败\n\n💡 请稍后重试，如问题持续请联系管理员"
    UNKNOWN_ERROR = "❌ 处理您的请求时出现错误\n\n💡 请稍后重试或联系管理员"
    
    @staticmethod
    def format_error(title: str, reason: str, solution: Optional[str] = None) -> str:
        """
        格式化错误消息
        
        Args:
            title: 错误标题（例如：❌ 入款失败）
            reason: 错误原因
            solution: 解决方案（可选）
            
        Returns:
            格式化的错误消息
            
        Example:
            >>> ErrorMessages.format_error(
            ...     "❌ 入款失败",
            ...     "金额不能为负数",
            ...     "请使用 +金额 格式，例如：+100"
            ... )
        """
        message = f"{title}\n\n{reason}"
        if solution:
            message += f"\n\n💡 {solution}"
        return message


async def send_error_message(update: Update, error_type: str, 
                            custom_message: Optional[str] = None) -> None:
    """
    发送错误消息
    
    Args:
        update: Telegram更新对象
        error_type: 错误类型（使用ErrorMessages中的常量名）
        custom_message: 自定义错误消息（如果提供则覆盖默认消息）
        
    Example:
        >>> await send_error_message(update, "PERMISSION_DENIED")
        >>> await send_error_message(update, "INVALID_AMOUNT", "❌ 金额必须大于0")
    """
    if custom_message:
        message = custom_message
    else:
        message = getattr(ErrorMessages, error_type, ErrorMessages.UNKNOWN_ERROR)
    
    if update.message:
        await update.message.reply_text(message)


# ============================================================================
# 确认对话框工具
# ============================================================================

async def show_confirmation_dialog(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    question: str,
    confirm_callback_data: str,
    cancel_callback_data: str = "cancel",
    confirm_text: str = "✅ 确认",
    cancel_text: str = "❌ 取消"
) -> None:
    """
    显示确认对话框
    
    Args:
        update: Telegram更新对象
        context: 上下文对象
        question: 确认问题
        confirm_callback_data: 确认按钮的回调数据
        cancel_callback_data: 取消按钮的回调数据
        confirm_text: 确认按钮文本
        cancel_text: 取消按钮文本
        
    Example:
        >>> await show_confirmation_dialog(
        ...     update, context,
        ...     "⚠️ 确定要删除这条账单吗？此操作不可恢复！",
        ...     f"confirm_delete_{bill_id}",
        ...     "cancel"
        ... )
    """
    keyboard = [
        [
            InlineKeyboardButton(confirm_text, callback_data=confirm_callback_data),
            InlineKeyboardButton(cancel_text, callback_data=cancel_callback_data)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(question, reply_markup=reply_markup)


async def show_dangerous_action_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action_name: str,
    confirm_callback_data: str,
    detail_info: Optional[str] = None
) -> None:
    """
    显示危险操作确认对话框（专门用于删除等危险操作）
    
    Args:
        update: Telegram更新对象
        context: 上下文对象
        action_name: 操作名称（例如：删除账单、清空数据）
        confirm_callback_data: 确认按钮的回调数据
        detail_info: 详细信息（可选）
        
    Example:
        >>> await show_dangerous_action_confirmation(
        ...     update, context,
        ...     "删除账单",
        ...     f"confirm_delete_{bill_id}",
        ...     "账单ID: 12345\n金额: ¥100.00"
        ... )
    """
    question = f"⚠️ 确定要{action_name}吗？\n\n"
    question += "此操作不可恢复！\n\n"
    
    if detail_info:
        question += f"📋 详细信息:\n{detail_info}\n\n"
    
    question += "请谨慎操作！"
    
    await show_confirmation_dialog(
        update, context,
        question,
        confirm_callback_data,
        confirm_text="⚠️ 确认删除",
        cancel_text="❌ 取消"
    )


# ============================================================================
# 成功消息工具
# ============================================================================

class SuccessMessages:
    """统一的成功消息管理"""
    
    # 交易相关
    DEPOSIT_SUCCESS = "✅ 入款成功"
    WITHDRAW_SUCCESS = "✅ 下发成功"
    STORAGE_SUCCESS = "✅ 寄存成功"
    
    # 配置相关
    EXCHANGE_RATE_SET = "✅ 汇率设置成功"
    FEE_RATE_SET = "✅ 费率设置成功"
    DISPLAY_COUNT_SET = "✅ 显示数量设置成功"
    
    # 操作相关
    TRANSACTION_REVOKED = "✅ 已撤销交易"
    CONFIG_DELETED = "✅ 已删除配置"
    
    @staticmethod
    def format_success(action: str, detail: Optional[str] = None) -> str:
        """
        格式化成功消息
        
        Args:
            action: 操作描述（例如：✅ 入款成功）
            detail: 详细信息（可选）
            
        Returns:
            格式化的成功消息
            
        Example:
            >>> SuccessMessages.format_success("✅ 入款成功", "金额: ¥100.00")
        """
        message = action
        if detail:
            message += f"\n\n{detail}"
        return message


async def send_success_message(update: Update, success_text: str, 
                              detail: Optional[str] = None) -> None:
    """
    发送成功消息
    
    Args:
        update: Telegram更新对象
        success_text: 成功提示文本
        detail: 详细信息（可选）
        
    Example:
        >>> await send_success_message(update, "✅ 入款成功", "金额: ¥100.00")
    """
    message = SuccessMessages.format_success(success_text, detail)
    
    if update.message:
        await update.message.reply_text(message)


# ============================================================================
# 信息提示工具
# ============================================================================

async def send_info_message(update: Update, info_text: str) -> None:
    """
    发送信息提示消息
    
    Args:
        update: Telegram更新对象
        info_text: 信息文本
        
    Example:
        >>> await send_info_message(update, "ℹ️ 当前汇率: 7.3")
    """
    if update.message:
        await update.message.reply_text(f"ℹ️ {info_text}")


async def send_warning_message(update: Update, warning_text: str) -> None:
    """
    发送警告消息
    
    Args:
        update: Telegram更新对象
        warning_text: 警告文本
        
    Example:
        >>> await send_warning_message(update, "⚠️ 余额不足，无法下发")
    """
    if update.message:
        await update.message.reply_text(f"⚠️ {warning_text}")


# ============================================================================
# 使用示例
# ============================================================================

"""
使用示例：

1. 加载动画：
```python
async def handle_deposit(update, context):
    # 显示加载
    await show_loading(update, context, "⏳ 正在处理入款...")
    
    # 执行操作
    try:
        # ... 数据库操作 ...
        await edit_to_success(loading_msg, "✅ 入款成功")
    except Exception as e:
        await edit_to_error(loading_msg, f"❌ 入款失败：{str(e)}")
```

2. 错误提示：
```python
async def handle_withdraw(update, context):
    if amount < 0:
        await send_error_message(update, "NEGATIVE_AMOUNT")
        return
    
    if not is_operator:
        await send_error_message(update, "PERMISSION_DENIED")
        return
```

3. 确认对话框：
```python
async def delete_bill(update, context):
    await show_dangerous_action_confirmation(
        update, context,
        "删除账单",
        f"confirm_delete_{bill_id}",
        f"账单ID: {bill_id}\n金额: ¥{amount}"
    )

# 在callback handler中处理
async def confirm_delete_callback(update, context):
    # 执行删除
    await update.callback_query.answer("已删除")
    await update.callback_query.edit_message_text("✅ 账单已删除")
```
"""

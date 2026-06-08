"""
账单管理操作处理器

包含：
- delete_bills: 删除账单
- save_bills: 保存账单
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from sqlalchemy import select

from ...models import Group, get_db_session
from ...services.billing_service import BillingService
from ...utils.formatter import Formatter
from ...utils.bot_id_middleware import get_current_bot_id
from ..operator import is_operator

logger = logging.getLogger(__name__)


async def delete_bills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除账单 - 显示二次确认"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
        
    # 🔑 获取 bot_id（多租户隔离）
    bot_id = get_current_bot_id(context)
    
    # 🔐 检查群组授权状态
    from ...utils.permission_checker import PermissionChecker
    is_authorized = await PermissionChecker.check_group_authorization(update, context)
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking delete_bills command")
        return
    
    async with get_db_session() as db:
        # 检查是否为群组聊天
        if chat_id > 0:
            await update.message.reply_text(
                "⚠️ 此功能仅在群组中可用\n\n"
                "请在群组中使用此命令。"
            )
            return
            
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return
    
    # ✅ 显示二次确认对话框
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"confirm_delete_bills_{chat_id}"),
            InlineKeyboardButton("❌ 取消", callback_data="cancel_delete_bills")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚠️ 确认删除全部账单？此操作不可撤销。",
        reply_markup=reply_markup
    )


async def confirm_delete_bills_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理确认删除账单的回调"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    # 🔑 获取 bot_id（多租户隔离）
    bot_id = get_current_bot_id(context)
    
    # 解析回调数据，验证群组ID
    callback_data = query.data
    parts = callback_data.split('_')
    if len(parts) < 4 or parts[0] != 'confirm' or parts[1] != 'delete' or parts[2] != 'bills':
        await query.edit_message_text("❌ 无效的回调数据")
        return
    
    target_chat_id = int(parts[3])
    
    # 验证是否是同一群组
    if target_chat_id != chat_id:
        await query.edit_message_text("❌ 群组不匹配")
        return
    
    async with get_db_session() as db:
        # 检查操作权限
        if not await is_operator(user_id, chat_id, db, context):
            await query.edit_message_text("❌ 您没有操作权限")
            return
        
        # 删除所有账单
        count = await BillingService.delete_all_transactions(db, bot_id, chat_id)
        
        # 更新消息，显示删除成功
        await query.edit_message_text(f"✅ 已删除 {count} 条账单记录")


async def cancel_delete_bills_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理取消删除账单的回调"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    await query.edit_message_text("❌ 已取消删除操作")


async def save_bills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """保存账单"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
        
    # 🔑 获取 bot_id（多租户隔离）
    bot_id = get_current_bot_id(context)
    
    # 🔐 检查群组授权状态
    from ...utils.permission_checker import PermissionChecker
    is_authorized = await PermissionChecker.check_group_authorization(update, context)
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking save_bills command")
        return
    
    async with get_db_session() as db:
        # 检查是否为群组聊天
        if chat_id > 0:
            await update.message.reply_text(
                "⚠️ 此功能仅在群组中可用\n\n"
                "请在群组中使用此命令。"
            )
            return
                
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return
        
        # 保存账单
        daily_summary = await BillingService.save_bills(db, bot_id, chat_id)

        # 格式化汇总消息
        summary_dict = {
            'deposit_count': daily_summary.total_deposit_count,
            'deposit_amount': daily_summary.total_deposit_amount,
            'deposit_cny': daily_summary.total_deposit_cny,
            'withdraw_count': daily_summary.total_withdraw_count,
            'withdraw_amount': daily_summary.total_withdraw_amount,
            'withdraw_cny': daily_summary.total_withdraw_cny,
            'storage_amount': daily_summary.total_storage_amount,
            'total_fee': daily_summary.total_fee_amount,
            'net_amount': daily_summary.net_amount
        }

        message = Formatter.format_summary(summary_dict, title="账单已保存")
        await update.message.reply_text(message)

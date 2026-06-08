"""
寄存操作处理器

包含：
- handle_storage: 处理寄存操作（增加/减少）
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from ...models import Group, get_db_session
from ...services.billing_service import BillingService
from ...utils.parser import CommandParser
from ...utils.db_helper import get_group
from ...utils.bot_id_middleware import get_current_bot_id
from ..operator import is_operator

logger = logging.getLogger(__name__)


async def handle_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理寄存操作"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text
    
    # 🔑 获取 bot_id（多租户隔离）
    bot_id = get_current_bot_id(context)
    
    # 🔐 检查群组授权状态
    from ...utils.permission_checker import PermissionChecker
    is_authorized = await PermissionChecker.check_group_authorization(update, context)
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking storage command")
        return

    async with get_db_session() as db:
        # 检查是否为群组聊天
        if chat_id > 0:
            await update.message.reply_text(
                "⚠️ 记账功能仅在群组中可用\n\n"
                "请将机器人添加到群组中，并在群组中使用记账命令。"
            )
            return
        
        # 检查记账是否开启（✅ 传递 bot_id 以支持多租户隔离）
        group = await get_group(db, chat_id, bot_id)
        if not group or not group.is_active:
            await update.message.reply_text(
                "❌ 该群组未开启记账功能\n\n"
                "请联系管理员在群组中发送 /start 命令开启记账。"
            )
            return

        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 解析寄存命令
        storage_info = CommandParser.parse_storage(text)

        if not storage_info:
            return

        # 确定金额（加或减）
        amount = storage_info['amount'] if storage_info['operation'] == '+' else -storage_info['amount']

        # 创建交易记录
        transaction = await BillingService.create_transaction(
            db=db,
            bot_id=bot_id,
            group_id=chat_id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            operator_id=user.id,
            operator_username=user.username,
            operator_first_name=user.first_name,
            operator_chat_id=chat_id,  # ✅ 操作人所在聊天ID
            transaction_type='storage',
            amount=amount,
            currency='CNY',
            note=storage_info['note'],
            message_id=update.message.message_id,
                        message_date=update.message.date.replace(tzinfo=None) if update.message.date else None
        )

        operation_text = "增加" if storage_info['operation'] == '+' else "减少"
        await update.message.reply_text(f"✅ 寄存{operation_text}成功: ¥{abs(amount):.2f}")

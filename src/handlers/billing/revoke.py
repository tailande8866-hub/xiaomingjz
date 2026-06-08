"""
撤销操作处理器

包含：
- revoke_by_reply: 通过回复消息撤销指定交易
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from ...models import get_db_session
from ...services.billing_service import BillingService
from ...utils.db_helper import get_group
from ...utils.bot_id_middleware import get_current_bot_id
from ..operator import is_operator

logger = logging.getLogger(__name__)


async def revoke_by_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """通过回复消息撤销指定交易"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()

    # 检查是否为“撤销”命令
    if text != "撤销":
        return
    
    # ⭐ 获取 bot_id（多租户隔离）
    bot_id = get_current_bot_id(context)
    
    # 🔐 检查群组授权状态
    from ...utils.permission_checker import PermissionChecker
    is_authorized = await PermissionChecker.check_group_authorization(update, context)
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking revoke command")
        return

    async with get_db_session() as db:
        # 检查是否为群组聊天
        if chat_id > 0:
            await update.message.reply_text(
                "❌ 此功能仅在群组中可用\n\n"
                "请在群组中使用此命令。"
            )
            return
            
        # 检查记账是否开启（✅ 传递 bot_id 以支持多租户隔离）
        group = await get_group(db, chat_id, bot_id)
        if not group or not group.is_active:
            await update.message.reply_text("❌ 该群组未开启记账功能")
            return
    
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 检查是否有回复消息
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "⚠️ 请回复要撤销的记账消息\n\n"
                "使用方法：回复某条记账消息，然后发送“撤销”"
            )
            return

        # 获取回复消息的message_id
        replied_message_id = update.message.reply_to_message.message_id

        # 查找对应的交易记录（✅ 传递 bot_id）
        transaction = await BillingService.get_transaction_by_message_id(
            db=db,
            bot_id=bot_id,
            group_id=chat_id,
            message_id=replied_message_id
        )

        if not transaction:
            await update.message.reply_text(
                "❌ 未找到对应的交易记录\n\n"
                "请确保回复的是记账消息。"
            )
            return

        # 🔥 Event Sourcing 撤销：创建 reversal transaction
        try:
            original_tx, reversal_tx = await BillingService.revoke_transaction(
                db=db,
                bot_id=bot_id,
                transaction_id=transaction.id,
                operator_id=user.id,
                reason="用户通过回复消息撤销"
            )
            
            # ✅ 样式1：简洁的撤销提示（参考参考程序样式）
            type_text = "入款" if transaction.transaction_type == 'deposit' else \
                       "下发" if transaction.transaction_type == 'withdraw' else "寄存"
            
            await update.message.reply_text(
                f"✅ 已成功撤销{type_text}交易，金额：{transaction.amount:.2f}。"
            )
            
            # ✅ 样式2：撤销后自动发送账单（与入款/下发后保持一致）
            from ...repositories import TransactionRepo, GroupRepo, CustomButtonRepo
            from ...utils.formatter import Formatter
            
            # 获取群组配置
            group_repo = GroupRepo(db, bot_id)
            group = await group_repo.get_by_group_id(chat_id)
            
            # ✅ 从全局配置获取显示条数（优先级高于群组设置）
            from ...services.global_config_service import global_config_service
            deposit_limit = await global_config_service.get_config(db, bot_id, "deposit_display_count")
            withdraw_limit = await global_config_service.get_config(db, bot_id, "withdraw_display_count")
            deposit_display_count = deposit_limit if isinstance(deposit_limit, int) else group.deposit_display_count
            withdraw_display_count = withdraw_limit if isinstance(withdraw_limit, int) else group.withdraw_display_count
            
            # 获取最新的入款和下发记录
            tx_repo = TransactionRepo(db, bot_id)
            deposits = await tx_repo.get_visible_transactions(
                group_id=chat_id,
                transaction_type='deposit',
                limit=deposit_display_count
            )
            
            withdraws = await tx_repo.get_visible_transactions(
                group_id=chat_id,
                transaction_type='withdraw',
                limit=withdraw_display_count
            )
            
            # 计算汇总
            summary = await BillingService.calculate_summary(
                db=db,
                bot_id=bot_id,
                group_id=chat_id
            )
            
            # 查询按钮
            button_repo = CustomButtonRepo(db, bot_id)
            buttons = await button_repo.get_active_buttons(chat_id)
            
            # 读取全局名字显示配置
            from ...services.global_config_service import global_config_service
            deposit_show_name = await global_config_service.get_config(db, bot_id, "deposit_show_name")
            withdraw_show_name = await global_config_service.get_config(db, bot_id, "withdraw_show_name")
            show_member_name = await global_config_service.get_config(db, bot_id, "show_member_name")
            show_member_name_enabled = False
            if isinstance(show_member_name, bool):
                show_member_name_enabled = show_member_name
            elif isinstance(show_member_name, str):
                show_member_name_enabled = show_member_name.lower() in ('true', '1', 'yes', 'on')
            elif isinstance(show_member_name, int):
                show_member_name_enabled = show_member_name == 1

            # 转换值为布尔类型（处理可能的字符串或整数类型）
            deposit_show_name_bool = None
            if isinstance(deposit_show_name, bool):
                deposit_show_name_bool = deposit_show_name
            elif isinstance(deposit_show_name, str):
                deposit_show_name_bool = deposit_show_name.lower() in ('true', '1', 'yes', 'on')
            elif isinstance(deposit_show_name, int):
                deposit_show_name_bool = deposit_show_name == 1

            withdraw_show_name_bool = None
            if isinstance(withdraw_show_name, bool):
                withdraw_show_name_bool = withdraw_show_name
            elif isinstance(withdraw_show_name, str):
                withdraw_show_name_bool = withdraw_show_name.lower() in ('true', '1', 'yes', 'on')
            elif isinstance(withdraw_show_name, int):
                withdraw_show_name_bool = withdraw_show_name == 1

            # 格式化账单
            reply_message, keyboard = Formatter.format_bill_with_buttons(
                deposits=deposits,
                withdraws=withdraws,
                summary=summary,
                group_name=group.group_name or "记账机器人",
                currency=group.currency_display or "USDT",
                group_exchange_rate=group.exchange_rate,
                group_fee_rate=group.fee_rate,
                display_mode=group.display_mode,
                buttons=buttons if buttons else None,
                deposit_show_name=deposit_show_name_bool,
                withdraw_show_name=withdraw_show_name_bool,
                show_member_name=show_member_name_enabled
            )
            
            # 发送账单（不引用用户消息）
            if keyboard:
                from telegram import InlineKeyboardMarkup
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=reply_message,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=reply_message,
                    parse_mode="HTML"
                )
                
        except ValueError as e:
            await update.message.reply_text(f"❌ 撤销失败: {str(e)}")

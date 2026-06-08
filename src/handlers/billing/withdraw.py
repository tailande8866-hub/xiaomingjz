"""
下发操作处理器

包含：
- handle_withdraw: 处理下发操作
- revoke_withdraw: 撤销下发
"""
import logging
import uuid
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ...models import get_db_session
from ...services.billing_service import BillingService
from ...utils.parser import CommandParser
from ...utils.formatter import Formatter
from ...utils.rate_limiter import rate_limit_withdraw
from ...utils.db_helper import get_group
from ...utils.bot_id_middleware import get_current_bot_id
from ...repositories import CustomButtonRepo, UserConfigRepo
from ..operator import is_operator
from .debug import current_traceback, format_rate_config, get_effective_accounting_bot_id, log_accounting_debug, log_accounting_trace

logger = logging.getLogger(__name__)


@rate_limit_withdraw
async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理下发操作（3秒限流）"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text
    reply_user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if reply_user and reply_user.is_bot and reply_user.id != context.bot.id:
        return
    
    # ⭐ 获取 bot_id（多租户隔离）
    raw_bot_id = get_current_bot_id(context)
    bot_id = get_effective_accounting_bot_id(context, raw_bot_id)
    try:
        context.user_data['_bot_id_override'] = bot_id
    except Exception:
        pass
    try:
        context.chat_data.pop('_accounting_committed', None)
    except Exception:
        pass
    log_accounting_debug(
        update=update,
        context=context,
        handler="billing.handle_withdraw.entry",
        bot_id=bot_id,
    )
    log_accounting_trace(
        update=update,
        context=context,
        handler="billing.handle_withdraw.entry",
        bot_id=raw_bot_id,
        effective_bot_id=bot_id,
        tenant_query_bot_id=bot_id,
    )
    
    # 🔐 检查群组授权状态
    from ...utils.permission_checker import PermissionChecker
    is_authorized = await PermissionChecker.check_group_authorization(update, context)
    log_accounting_debug(
        update=update,
        context=context,
        handler="billing.handle_withdraw.authorization",
        bot_id=bot_id,
        permission_pass=is_authorized,
    )
    log_accounting_trace(
        update=update,
        context=context,
        handler="billing.handle_withdraw.authorization",
        bot_id=raw_bot_id,
        effective_bot_id=bot_id,
        tenant_query_bot_id=bot_id,
    )
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking withdraw command")
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
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_withdraw.group_config",
            bot_id=bot_id,
            group=group,
            db=db,
            rate_config=format_rate_config(group),
        )
        log_accounting_trace(
            update=update,
            context=context,
            handler="billing.handle_withdraw.group_config",
            bot_id=raw_bot_id,
            effective_bot_id=bot_id,
            group=group,
            tenant_query_bot_id=bot_id,
        )
        if not group or not group.is_active:
            await update.message.reply_text(
                "❌ 该群组未开启记账功能\n\n"
                "请联系管理员在群组中发送 /start 命令开启记账。"
            )
            return

        # 检查操作权限
        operator_found = await is_operator(user.id, chat_id, db, context)
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_withdraw.operator",
            bot_id=bot_id,
            group=group,
            operator_found=operator_found,
            permission_pass=operator_found,
            db=db,
            rate_config=format_rate_config(group),
        )
        log_accounting_trace(
            update=update,
            context=context,
            handler="billing.handle_withdraw.operator",
            bot_id=raw_bot_id,
            effective_bot_id=bot_id,
            group=group,
            operator_found=operator_found,
            tenant_query_bot_id=bot_id,
        )
        if not operator_found:
            await update.message.reply_text("❌ 您没有操作权限")
            return

        if not CommandParser.is_accounting_command(text):
            return

        # 解析下发命令
        withdraw_info = CommandParser.parse_withdraw(text)

        if not withdraw_info:
            return

        # 确定下发用户
        target_user_id = user.id
        target_username = user.username
        target_first_name = user.first_name

        # 如果是回复消息
        if update.message.reply_to_message and update.message.reply_to_message.from_user:
            replied_user = update.message.reply_to_message.from_user
            if not replied_user.is_bot:
                target_user_id = replied_user.id
                target_username = replied_user.username
                target_first_name = replied_user.first_name

        # 获取用户个人配置（✅ 使用 Repository）
        user_config_repo = UserConfigRepo(db, bot_id)
        user_config = await user_config_repo.get_by_user(chat_id, target_user_id)

        # 确定汇率和费率
        exchange_rate = withdraw_info['exchange_rate'] or \
                       (user_config.exchange_rate if user_config else None) or \
                       group.exchange_rate

        fee_rate = withdraw_info['fee_rate'] or \
                  (user_config.fee_rate if user_config else None) or \
                  group.fee_rate
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_withdraw.rate_config",
            bot_id=bot_id,
            group=group,
            operator_found=True,
            permission_pass=True,
            db=db,
            rate_config=format_rate_config(group, exchange_rate, fee_rate),
        )

        # 🔑 生成 trace_id（UUID，用于审计和撤销）
        trace_id = str(uuid.uuid4())
        
        #  取消幂等性检查，允许重复记账
        idempotency_key = None  # 不再使用 bot_id:chat_id:message_id

        # 创建交易记录（✅ 传递 bot_id + trace_id + idempotency_key）
        transaction = await BillingService.create_transaction(
            db=db,
            bot_id=bot_id,
            group_id=chat_id,
            user_id=target_user_id,
            username=target_username,
            first_name=target_first_name,
            operator_id=user.id,
            operator_username=user.username,
            operator_first_name=user.first_name,
            operator_chat_id=chat_id,  # ✅ 操作人所在聊天ID
            transaction_type='withdraw',
            amount=withdraw_info['amount'],
            currency=withdraw_info['currency'],
            exchange_rate=exchange_rate,
            fee_rate=fee_rate,
            note=withdraw_info['note'],
            message_id=update.message.message_id,
            reply_to_message_id=update.message.reply_to_message.message_id if update.message.reply_to_message else None,
            message_date=update.message.date.replace(tzinfo=None) if update.message.date else None,
            trace_id=trace_id,
            idempotency_key=idempotency_key
        )

        # ✅ 在 commit 之前保存需要的值，避免 commit 后对象过期
        # ✅ 从全局配置获取显示条数（优先级高于群组设置）
        from ...services.global_config_service import global_config_service
        deposit_limit = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_limit = await global_config_service.get_config(db, bot_id, "withdraw_display_count")
        
        # 如果全局配置存在且为有效数字，使用全局配置；否则使用群组默认值
        deposit_display_count = deposit_limit if isinstance(deposit_limit, int) else group.deposit_display_count
        withdraw_display_count = withdraw_limit if isinstance(withdraw_limit, int) else group.withdraw_display_count

        #  集成额度检查（外部传入 db 会话，基于同一个会话查询最新数据）
        try:
            from ...services.quota_service import quota_service
            is_over_quota = await quota_service.check_and_warn_quota(
                db=db,  # ✅ 传入当前数据库会话
                group_id=chat_id,
                bot_id=bot_id,
                new_amount=withdraw_info['amount'],
                currency=withdraw_info['currency'],
                transaction_type='withdraw',
                context=context
            )
        except Exception as e:
            logger.error(f"[BOT:{bot_id}] Quota check failed: {e}", exc_info=True)
            log_accounting_debug(
                update=update,
                context=context,
                handler="billing.handle_withdraw.quota_error",
                bot_id=bot_id,
                group=group,
                operator_found=True,
                permission_pass=True,
                db=db,
                rate_config=format_rate_config(group, exchange_rate, fee_rate),
                error_traceback=current_traceback(),
            )
            # 额度检查失败不影响记账，继续执行

        # ✅ 提交事务，确保交易记录已持久化到数据库
        await db.commit()
        try:
            context.chat_data['_accounting_committed'] = True
        except Exception:
            pass
        logger.info(
            f"[BOT:{bot_id}] Withdraw committed: chat_id={chat_id}, "
            f"amount={withdraw_info['amount']}"
        )

        try:
            deposits = await BillingService.get_transactions(
                db=db,
                bot_id=bot_id,
                group_id=chat_id,
                transaction_type='deposit',
                limit=deposit_display_count
            )
            
            withdraws = await BillingService.get_transactions(
                db=db,
                bot_id=bot_id,
                group_id=chat_id,
                transaction_type='withdraw',
                limit=withdraw_display_count
            )
            
            summary = await BillingService.calculate_summary(
                db=db,
                bot_id=bot_id,
                group_id=chat_id
            )
            
            button_repo = CustomButtonRepo(db, bot_id)
            buttons = await button_repo.get_active_buttons(chat_id)

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

            from ...services.ad_service import AdService
            ad_content = await AdService.get_ad_content(db, bot_id)
            if ad_content['enabled']:
                if ad_content['header_text']:
                    header_ad_text = ad_content['header_text']
                    if ad_content['header_link']:
                        header_ad_text += f"\n{ad_content['header_link']}"
                    reply_message = f"{header_ad_text}\n\n{reply_message}"
                if ad_content['footer_text']:
                    footer_ad_text = ad_content['footer_text']
                    if ad_content['footer_link']:
                        footer_ad_text += f"\n{ad_content['footer_link']}"
                    reply_message = f"{reply_message}\n\n{footer_ad_text}"
                if ad_content['buttons']:
                    from telegram import InlineKeyboardButton
                    if keyboard is None:
                        keyboard = []
                    for btn in ad_content['buttons']:
                        keyboard.append([InlineKeyboardButton(btn['text'], url=AdService.format_url_for_tg(btn['url']))])

            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)
                sent_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=reply_message,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                sent_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=reply_message,
                    parse_mode="HTML"
                )

            if group.pin_enabled:
                try:
                    await sent_message.pin(disable_notification=True)
                except Exception:
                    pass
        except Exception:
            logger.error("[ACCOUNTING_DEBUG] withdraw post-processing failed", exc_info=True)
            log_accounting_debug(
                update=update,
                context=context,
                handler="billing.handle_withdraw.postprocess_error",
                bot_id=bot_id,
                group=group,
                operator_found=True,
                permission_pass=True,
                db=db,
                rate_config=format_rate_config(group, exchange_rate, fee_rate),
                error_traceback=current_traceback(),
            )


async def revoke_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """撤销下发操作"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text
    
    # ⭐ 获取 bot_id（多租户隔离）
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        # 检查记账是否开启（✅ 传递 bot_id 以支持多租户隔离）
        group = await get_group(db, chat_id, bot_id)
        if not group or not group.is_active:
            await update.message.reply_text("❌ 该群组未开启记账功能")
            return

        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 解析撤销命令
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ 命令格式错误\n\n"
                "使用方法：\n"
                "• 撤销下发 序号\n"
                "• 撤销下发 @用户名 序号"
            )
            return

        # 提取序号
        try:
            sequence_number = int(parts[-1])
        except ValueError:
            await update.message.reply_text("❌ 序号必须是数字")
            return

        # 查找对应的下发记录（✅ 使用 Repository）
        from ...repositories import TransactionRepo
        tx_repo = TransactionRepo(db, bot_id)
        transaction = await tx_repo.get_by_sequence_number(chat_id, 'withdraw', sequence_number)

        if not transaction:
            await update.message.reply_text("❌ 未找到对应的下发记录")
            return

        # 🔥 Event Sourcing 撤销：创建 reversal transaction
        try:
            original_tx, reversal_tx = await BillingService.revoke_transaction(
                db=db,
                bot_id=bot_id,
                transaction_id=transaction.id,
                operator_id=user.id,
                reason=f"用户通过序号撤销 #{sequence_number}"
            )
            
            await update.message.reply_text(
                f"✅ 已撤销下发记录 #{sequence_number}\n"
                f"金额：{transaction.amount} {transaction.currency}\n"
                f"原交易 ID: {original_tx.id}\n"
                f"撤销交易 ID: {reversal_tx.id}"
            )
        except ValueError as e:
            await update.message.reply_text(f"❌ 撤销失败: {str(e)}")

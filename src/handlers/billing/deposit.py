"""
入款操作处理器

包含：
- handle_deposit: 处理入款操作
- revoke_deposit: 撤销入款
"""
import logging
from datetime import datetime, timedelta
import uuid
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ...models import get_db_session
from ...services.billing_service import BillingService
from ...utils.parser import CommandParser
from ...utils.formatter import Formatter
from ...utils.rate_limiter import rate_limit_deposit
from ...utils.db_helper import get_group
from ...utils.bot_id_middleware import get_current_bot_id
from ...repositories import CustomButtonRepo
from ..operator import is_operator as operator_checker
from .debug import current_traceback, format_rate_config, get_effective_accounting_bot_id, log_accounting_debug, log_accounting_trace

logger = logging.getLogger(__name__)


def get_day_cut_period(group) -> tuple:
    """
    获取当前日切周期的开始和结束时间
    
    Args:
        group: 群组对象
        
    Returns:
        tuple: (start_date, end_date) 或者 (None, None) 如果没有设置日切
    """
    if not group.day_cut_time:
        return None, None
    
    now = datetime.utcnow()
    day_cut_hour = group.day_cut_time.hour
    day_cut_minute = group.day_cut_time.minute
    
    # 今天的日切时间
    today_cut = now.replace(hour=day_cut_hour, minute=day_cut_minute, second=0, microsecond=0)
    
    # 判断当前是否在今天日切之后
    if now >= today_cut:
        # 当前周期从今天日切开始，到明天日切结束
        start_date = today_cut
        end_date = today_cut + timedelta(days=1)
    else:
        # 当前周期从昨天日切开始，到今天日切结束
        start_date = today_cut - timedelta(days=1)
        end_date = today_cut
    
    return start_date, end_date


# ✅ 已取消限流 - 用户要求不限制操作频率
# @rate_limit_deposit
async def handle_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理入款操作（已取消3秒限流）"""
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
        handler="billing.handle_deposit.entry",
        bot_id=bot_id,
    )
    log_accounting_trace(
        update=update,
        context=context,
        handler="billing.handle_deposit.entry",
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
        handler="billing.handle_deposit.authorization",
        bot_id=bot_id,
        permission_pass=is_authorized,
    )
    log_accounting_trace(
        update=update,
        context=context,
        handler="billing.handle_deposit.authorization",
        bot_id=raw_bot_id,
        effective_bot_id=bot_id,
        tenant_query_bot_id=bot_id,
    )
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking deposit command")
        return

    async with get_db_session() as db:
        # 检查是否为群组聊天
        if chat_id > 0:
            await update.message.reply_text(
                "⚠️ 记账功能仅在群组中可用\n\n"
                "请将机器人添加到群组中，并在群组中使用记账命令。\n\n"
                "💡 使用方法：\n"
                "• 将机器人添加到群组\n"
                "• 在群组中发送 /start 开启记账\n"
                "• 使用 +金额 进行入款操作"
            )
            return
        
        # 检查记账是否开启（✅ 传递 bot_id 以支持多租户隔离）
        group = await get_group(db, chat_id, bot_id)
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_deposit.group_config",
            bot_id=bot_id,
            group=group,
            db=db,
            rate_config=format_rate_config(group),
        )
        log_accounting_trace(
            update=update,
            context=context,
            handler="billing.handle_deposit.group_config",
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

        # 检查操作权限（✅ 传递 context 以支持租户隔离）
        operator_found = await operator_checker(user.id, chat_id, db, context)
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_deposit.operator",
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
            handler="billing.handle_deposit.operator",
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

        # 解析入款命令
        deposit_info = CommandParser.parse_deposit(text)
        correction_info = None
        if not deposit_info:
            correction_info = CommandParser.parse_correction(text)
            if not correction_info or correction_info.get('type') != 'deposit':
                return
            deposit_info = {
                'username': None,
                'amount': -correction_info['amount'],
                'currency': 'CNY',
                'exchange_rate': None,
                'fee_rate': None,
                'note': correction_info.get('note', ''),
                'is_correction': True,
            }

        # +0 查看账单和普通记账都依赖显示条数配置，这里统一提前读取
        from ...services.global_config_service import global_config_service
        deposit_limit = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_limit = await global_config_service.get_config(db, bot_id, "withdraw_display_count")
        deposit_display_count = deposit_limit if isinstance(deposit_limit, int) else group.deposit_display_count
        withdraw_display_count = withdraw_limit if isinstance(withdraw_limit, int) else group.withdraw_display_count

        # 特殊处理：+0 查看账单（不创建入款记录）
        if deposit_info['amount'] == 0:
            # 获取最新的入款和下发记录（✅ 传递 bot_id）
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
            
            # 计算汇总（✅ 传递 bot_id）
            summary = await BillingService.calculate_summary(
                db=db,
                bot_id=bot_id,
                group_id=chat_id
            )
            
            # 查询按钮（✅ 使用 Repository）
            button_repo = CustomButtonRepo(db, bot_id)
            buttons = await button_repo.get_active_buttons(chat_id)
            
            # 读取全局名字显示配置
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
            
            # 格式化完整账单样式并获取按钮
            logger.info(f"[BOT:{bot_id}] 显示账单 - 群组汇率: {group.exchange_rate}, 群组费率: {group.fee_rate}, 显示名字: deposit={deposit_show_name_bool}, withdraw={withdraw_show_name_bool}")
            
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

            # 🔔 处理广告
            from ...services.ad_service import AdService
            ad_content = await AdService.get_ad_content(db, bot_id)
            
            # 构建广告消息和广告按钮
            if ad_content['enabled']:
                # 抬头广告
                if ad_content['header_text']:
                    header_ad_text = ad_content['header_text']
                    if ad_content['header_link']:
                        # 如果是 @username，直接显示；如果是链接，添加格式
                        if ad_content['header_link'].startswith('@'):
                            header_ad_text += f"\n{ad_content['header_link']}"
                        else:
                            header_ad_text += f"\n{ad_content['header_link']}"
                    reply_message = f"{header_ad_text}\n\n{reply_message}"
                
                # 尾页广告
                if ad_content['footer_text']:
                    footer_ad_text = ad_content['footer_text']
                    if ad_content['footer_link']:
                        if ad_content['footer_link'].startswith('@'):
                            footer_ad_text += f"\n{ad_content['footer_link']}"
                        else:
                            footer_ad_text += f"\n{ad_content['footer_link']}"
                    reply_message = f"{reply_message}\n\n{footer_ad_text}"
                
                # 广告按钮
                if ad_content['buttons']:
                    from telegram import InlineKeyboardButton
                    if keyboard is None:
                        keyboard = []
                    # 添加广告按钮
                    for btn in ad_content['buttons']:
                        keyboard.append([InlineKeyboardButton(btn['text'], url=AdService.format_url_for_tg(btn['url']))])

            # 发送账单（不引用用户消息）
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

            # 如果开启置顶，置顶消息
            if group.pin_enabled:
                try:
                    await sent_message.pin(disable_notification=True)
                except Exception:
                    pass
            
            return

        # 确定入款用户
        target_user_id = user.id
        target_username = user.username
        target_first_name = user.first_name

        # 如果指定了用户名或是回复消息
        if deposit_info['username']:
            # TODO: 根据用户名查找用户ID
            pass
        elif update.message.reply_to_message and update.message.reply_to_message.from_user:
            replied_user = update.message.reply_to_message.from_user
            if not replied_user.is_bot:
                target_user_id = replied_user.id
                target_username = replied_user.username
                target_first_name = replied_user.first_name

        # 获取用户个人配置（✅ 使用 Repository）
        from ...repositories import UserConfigRepo
        user_config_repo = UserConfigRepo(db, bot_id)
        user_config = await user_config_repo.get_by_user(chat_id, target_user_id)

        # 确定汇率和费率
        exchange_rate = deposit_info['exchange_rate'] or \
                       (user_config.exchange_rate if user_config else None) or \
                       group.exchange_rate

        fee_rate = deposit_info['fee_rate'] or \
                  (user_config.fee_rate if user_config else None) or \
                  group.fee_rate
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_deposit.rate_config",
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

        # ✅ 创建交易记录（只创建一次）
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
            transaction_type='deposit',
            amount=deposit_info['amount'],
            currency=deposit_info['currency'],
            exchange_rate=exchange_rate,
            fee_rate=fee_rate,
            note=deposit_info['note'],
            message_id=update.message.message_id,
            reply_to_message_id=update.message.reply_to_message.message_id if update.message.reply_to_message else None,
            message_date=update.message.date.replace(tzinfo=None) if update.message.date else None,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            is_correction=deposit_info.get('is_correction', False)
        )

        # ✅ 在 commit 之前保存需要的值，避免 commit 后对象过期
        # ✅ 从全局配置获取显示条数（优先级高于群组设置）
        deposit_limit = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_limit = await global_config_service.get_config(db, bot_id, "withdraw_display_count")
        
        # 如果全局配置存在且为有效数字，使用全局配置；否则使用群组默认值
        deposit_display_count = deposit_limit if isinstance(deposit_limit, int) else group.deposit_display_count
        withdraw_display_count = withdraw_limit if isinstance(withdraw_limit, int) else group.withdraw_display_count

        # ✅ 提交事务，确保交易记录已持久化到数据库
        await db.commit()
        try:
            context.chat_data['_accounting_committed'] = True
        except Exception:
            pass
        
        logger.info(
            f"[BOT:{bot_id}] Deposit committed: chat_id={chat_id}, "
            f"amount={deposit_info['amount']}"
        )

        # 🆕 集成额度检查（外部传入 db 会话，基于同一个会话查询最新数据）
        try:
            from ...services.quota_service import quota_service
            is_over_quota = await quota_service.check_and_warn_quota(
                db=db,  # ✅ 传入当前数据库会话
                group_id=chat_id,
                bot_id=bot_id,
                new_amount=deposit_info['amount'],
                currency=deposit_info['currency'],
                transaction_type='deposit',
                context=context
            )
        except Exception as e:
            logger.error(f"[BOT:{bot_id}] Quota check failed: {e}", exc_info=True)
            log_accounting_debug(
                update=update,
                context=context,
                handler="billing.handle_deposit.quota_error",
                bot_id=bot_id,
                group=group,
                operator_found=True,
                permission_pass=True,
                db=db,
                rate_config=format_rate_config(group, exchange_rate, fee_rate),
                error_traceback=current_traceback(),
            )
            # 额度检查失败不影响记账，继续执行

        try:
            # 获取最新的入款和下发记录（✅ 传递 bot_id）
            deposits = await BillingService.get_transactions(
                db=db,
                bot_id=bot_id,
                group_id=chat_id,
                transaction_type='deposit',
                limit=deposit_display_count  # ✅ 使用 commit 前保存的值
            )
            
            withdraws = await BillingService.get_transactions(
                db=db,
                bot_id=bot_id,
                group_id=chat_id,
                transaction_type='withdraw',
                limit=withdraw_display_count  # ✅ 使用 commit 前保存的值
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
            logger.error("[ACCOUNTING_DEBUG] deposit post-processing failed", exc_info=True)
            log_accounting_debug(
                update=update,
                context=context,
                handler="billing.handle_deposit.postprocess_error",
                bot_id=bot_id,
                group=group,
                operator_found=True,
                permission_pass=True,
                db=db,
                rate_config=format_rate_config(group, exchange_rate, fee_rate),
                error_traceback=current_traceback(),
            )


async def revoke_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """撤销入款操作"""
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

        # 检查操作权限（✅ 传递 context 以支持租户隔离）
        if not await operator_checker(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 解析撤销命令
        # 格式：撤销入款 序号 或 撤销入款 @用户名 序号
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ 命令格式错误\n\n"
                "使用方法：\n"
                "• 撤销入款 序号\n"
                "• 撤销入款 @用户名 序号"
            )
            return

        # 提取序号
        try:
            sequence_number = int(parts[-1])
        except ValueError:
            await update.message.reply_text("❌ 序号必须是数字")
            return

        # 查找对应的入款记录（✅ 使用 Repository）
        from ...repositories import TransactionRepo
        tx_repo = TransactionRepo(db, bot_id)
        transaction = await tx_repo.get_by_sequence_number(chat_id, 'deposit', sequence_number)

        if not transaction:
            await update.message.reply_text("❌ 未找到对应的入款记录")
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
            
            # ✅ 样式1：简洁的撤销提示
            await update.message.reply_text(
                f"✅ 已成功撤销入款交易，金额：{transaction.amount:.2f}。"
            )
            
            # ✅ 样式2：撤销后自动发送账单
            from ...repositories import TransactionRepo, GroupRepo, CustomButtonRepo
            from ...utils.formatter import Formatter
            from ...services.global_config_service import global_config_service
            
            # 获取群组配置
            group_repo = GroupRepo(db, bot_id)
            group = await group_repo.get_by_group_id(chat_id)
            
            # ✅ 从全局配置获取显示条数（优先级高于群组设置）
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
            
            # 🔔 处理广告
            from ...services.ad_service import AdService
            ad_content = await AdService.get_ad_content(db, bot_id)
            
            # 构建广告消息和广告按钮
            if ad_content['enabled']:
                # 抬头广告
                if ad_content['header_text']:
                    header_ad_text = ad_content['header_text']
                    if ad_content['header_link']:
                        # 如果是 @username，直接显示；如果是链接，添加格式
                        if ad_content['header_link'].startswith('@'):
                            header_ad_text += f"\n{ad_content['header_link']}"
                        else:
                            header_ad_text += f"\n{ad_content['header_link']}"
                    reply_message = f"{header_ad_text}\n\n{reply_message}"
                
                # 尾页广告
                if ad_content['footer_text']:
                    footer_ad_text = ad_content['footer_text']
                    if ad_content['footer_link']:
                        if ad_content['footer_link'].startswith('@'):
                            footer_ad_text += f"\n{ad_content['footer_link']}"
                        else:
                            footer_ad_text += f"\n{ad_content['footer_link']}"
                    reply_message = f"{reply_message}\n\n{footer_ad_text}"
                
                # 广告按钮
                if ad_content['buttons']:
                    from telegram import InlineKeyboardButton
                    if keyboard is None:
                        keyboard = []
                    # 添加广告按钮
                    for btn in ad_content['buttons']:
                        keyboard.append([InlineKeyboardButton(btn['text'], url=AdService.format_url_for_tg(btn['url']))])
            
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

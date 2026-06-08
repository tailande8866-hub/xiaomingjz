"""
账单查询处理器 - Financial Reality Renderer

职责：
- Projection Assembly（投影组装）
- Telegram Rendering（Telegram 渲染）

不再直接操作 ORM，所有数据通过 Projection Service 获取
"""
import logging
from datetime import datetime, timedelta, time as dt_time
from telegram import Update
from telegram.ext import ContextTypes

from ...models import get_db_session
from ...models.transaction import Transaction
from ...repositories import GroupRepo, TransactionRepo
from ...projections import TransactionProjectionService, SummaryProjectionService
from .deposit import get_day_cut_period

logger = logging.getLogger(__name__)


async def _resolve_effective_day_cut_period(db, bot_id: str, group):
    """优先使用群组日切；未单独设置时回退到全局日切。"""
    if group.day_cut_time:
        return get_day_cut_period(group)

    from ...services.global_config_service import global_config_service

    day_cut_enabled = await global_config_service.get_config(db, bot_id, "day_cut_enabled")
    day_cut_hour = await global_config_service.get_config(db, bot_id, "day_cut_time")
    if not day_cut_enabled or not isinstance(day_cut_hour, int):
        return None, None

    now = datetime.utcnow()
    today_cut = now.replace(hour=day_cut_hour, minute=0, second=0, microsecond=0)
    if now >= today_cut:
        return today_cut, today_cut + timedelta(days=1)
    return today_cut - timedelta(days=1), today_cut


async def show_bills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示账单（用户可见投影）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    reply_user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if reply_user and reply_user.is_bot and reply_user.id != context.bot.id:
        return
    from ...utils.parser import CommandParser
    if text and CommandParser.is_accounting_command(text):
        return
    
    # 🔑 获取 bot_id（从 context 中）
    from ...utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    
    # 🔐 检查群组授权状态
    from ...utils.permission_checker import PermissionChecker
    is_authorized = await PermissionChecker.check_group_authorization(update, context)
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking show_bills command")
        return

    async with get_db_session() as db:
        # 检查是否为群组聊天
        if chat_id > 0:
            await update.message.reply_text(
                "❌ 账单查询仅在群组中可用\n\n"
                "请在群组中使用此命令。"
            )
            return
        
        # ✅ 使用 Repository 获取群组配置
        group_repo = GroupRepo(db, bot_id)
        group = await group_repo.get_by_group_id(chat_id)

        if not group:
            await update.message.reply_text("❌ 未找到群组配置")
            return

        # 计算日切周期：群组设置优先，否则使用全局日切
        start_date, end_date = await _resolve_effective_day_cut_period(db, bot_id, group)
        
        # ✅ 从全局配置获取显示条数（优先级高于群组设置）
        from ...services.global_config_service import global_config_service
        deposit_limit = await global_config_service.get_config(db, bot_id, "deposit_display_count")
        withdraw_limit = await global_config_service.get_config(db, bot_id, "withdraw_display_count")
        
        # 如果全局配置存在且为有效数字，使用全局配置；否则使用群组默认值
        deposit_limit = deposit_limit if isinstance(deposit_limit, int) else 5
        withdraw_limit = withdraw_limit if isinstance(withdraw_limit, int) else 5
        
        # ✅ 使用 Visibility Policy 获取可见交易
        tx_repo = TransactionRepo(db, bot_id)
        
        # 获取入款记录（只显示 SUCCESS + NORMAL）
        deposit_txs = await tx_repo.get_visible_transactions(
            group_id=chat_id,
            transaction_type='deposit',
            start_date=start_date,
            end_date=end_date,
            limit=deposit_limit
        )
        
        # 投影为 DTO
        deposit_projections = await TransactionProjectionService.project_user_bill(deposit_txs)

        # 获取下发记录（只显示 SUCCESS + NORMAL）
        withdraw_txs = await tx_repo.get_visible_transactions(
            group_id=chat_id,
            transaction_type='withdraw',
            start_date=start_date,
            end_date=end_date,
            limit=withdraw_limit
        )
        
        # 投影为 DTO
        withdraw_projections = await TransactionProjectionService.project_user_bill(withdraw_txs)

        # ✅ 使用 Projection Service 渲染 Markdown
        message_parts = []
        
        # 添加周期提示
        if start_date:
            period_text = f"📅 当前周期: {start_date.strftime('%m-%d %H:%M')} ~ {end_date.strftime('%m-%d %H:%M')}"
            message_parts.append(period_text)

        if deposit_projections:
            deposit_msg = TransactionProjectionService.render_bill_html(
                deposit_projections,
                title=f"最近{len(deposit_projections)}条入款",
                show_header=False
            )
            message_parts.append(deposit_msg)

        if withdraw_projections:
            withdraw_msg = TransactionProjectionService.render_bill_html(
                withdraw_projections,
                title=f"最近{len(withdraw_projections)}条下发",
                show_header=False
            )
            message_parts.append(withdraw_msg)

        if not message_parts or (len(message_parts) == 1 and start_date):
            message_parts.append("📭 暂无账单记录")

        # 🆕 添加导出按钮
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Excel明细", callback_data="export_bills")],
            [InlineKeyboardButton("👥 分组统计", callback_data="group_stats")]
        ])
        
        await update.message.reply_text("\n\n".join(message_parts), parse_mode="HTML", reply_markup=keyboard)



async def show_my_bills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示我的账单（个人投影）- 只显示我操作的账单，样式同“账单”命令"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # 🔑 获取 bot_id（强制校验，防止租户隔离失效）
    from ...utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    if not bot_id:
        await update.message.reply_text(
            "⚠️ 系统异常：无法识别当前 Bot 实例\n\n"
            "请联系管理员检查配置。"
        )
        return
    
    # 🔐 检查群组授权状态
    from ...utils.permission_checker import PermissionChecker
    is_authorized = await PermissionChecker.check_group_authorization(update, context)
    if not is_authorized:
        logger.warning(f"🚫 Group {chat_id} is not authorized, blocking show_my_bills command")
        return

    async with get_db_session() as db:
        # 检查是否为群组聊天
        if chat_id > 0:
            await update.message.reply_text(
                "⚠️ 账单查询仅在群组中可用\n\n"
                "请在群组中使用此命令。"
            )
            return
        
        # ✅ 使用 Repository 获取群组配置
        group_repo = GroupRepo(db, bot_id)
        group = await group_repo.get_by_group_id(chat_id)

        if not group:
            await update.message.reply_text("❌ 未找到群组配置")
            return

        # 计算日切周期：群组设置优先，否则使用全局日切
        start_date, end_date = await _resolve_effective_day_cut_period(db, bot_id, group)

        # ✅ 获取用户操作的所有账单（作为 operator）
        from sqlalchemy import select, and_, desc
        from src.models.transaction import TransactionStatus, TransactionCategory
        
        conditions = [
            Transaction.bot_id == bot_id,
            Transaction.group_id == chat_id,
            Transaction.operator_id == user_id,  # 🔑 关键：查询用户操作的账单
            Transaction.status == TransactionStatus.SUCCESS,
            Transaction.category == TransactionCategory.NORMAL,
            Transaction.is_deleted.is_(False)  # 🔑 过滤已删除的记录
        ]
        
        if start_date:
            conditions.append(Transaction.transaction_date >= start_date)
        
        if end_date:
            conditions.append(Transaction.transaction_date < end_date)
        
        stmt = (
            select(Transaction)
            .where(and_(*conditions))
            .order_by(desc(Transaction.transaction_date))
            .limit(50)  # 最多显示 50 条
        )
        
        result = await db.execute(stmt)
        all_user_txs = result.scalars().all()
        
        # 分离入款和下发
        user_deposit_txs = [tx for tx in all_user_txs if tx.transaction_type == 'deposit']
        user_withdraw_txs = [tx for tx in all_user_txs if tx.transaction_type == 'withdraw']
        
        # ✅ 渲染：使用与"今日个人记账汇总"完全一致的样式（图一）
        from ...utils.formatter import Formatter
        
        user_name = update.effective_user.first_name or update.effective_user.username or f"用户{user_id}"
        group_name = group.group_name or "记账机器人"
        
        # 计算汇总数据
        # ✅ 核心修复：直接使用数据库中已冻结的USDT值，零计算！
        total_deposit_cny = sum(tx.cny_amount if tx.cny_amount and tx.cny_amount > 0 else tx.amount for tx in user_deposit_txs)
        total_withdraw_cny = sum(tx.cny_amount if tx.cny_amount and tx.cny_amount > 0 else tx.amount for tx in user_withdraw_txs)
        
        # ✅ 直接使用冻结的USDT值（不再重新计算）
        total_deposit_usdt_raw = sum(tx.amount_usd or 0 for tx in user_deposit_txs)  # 未扣费
        total_deposit_usdt_final = sum(tx.final_amount_usd or 0 for tx in user_deposit_txs)  # 扣费后
        total_withdraw_usdt = sum(tx.amount_usd or 0 for tx in user_withdraw_txs)
        total_fee_usdt = sum(tx.fee_amount_usd or 0 for tx in user_deposit_txs)
        
        exchange_rate = group.exchange_rate or 1
        fee_rate = group.fee_rate or 0
        
        summary = {
            'deposit_amount': total_deposit_usdt_final,  # ✅ USDT 总额（扣费后）
            'deposit_cny': total_deposit_cny,  # ✅ CNY 总额
            'withdraw_amount': total_withdraw_usdt,  # ✅ USDT 总额
            'withdraw_cny': total_withdraw_cny,  # ✅ CNY 总额
            'pending_withdraw': total_deposit_cny - total_withdraw_cny,
            'total_fee': 0,  # 个人账单不显示手续费
            'fee_amount_usd': total_fee_usdt,  # ✅ 冻结的手续费USDT
            'final_amount_usd': total_deposit_usdt_final,  # ✅ 冻结的扣费后USDT
            'balance': total_deposit_cny - total_withdraw_cny,
            'exchange_rate': exchange_rate,
            'fee_rate': fee_rate,
        }
        
        # 🌟 根据全局配置决定是否显示名字
        display_mode = group.display_mode

        # 全局“昵称显示”开关优先级最高：开启后所有授权群组统一显示回复人/入款人昵称
        from ...services.global_config_service import global_config_service
        show_member_name = await global_config_service.get_config(db, bot_id, "show_member_name")
        show_member_name_enabled = False
        if isinstance(show_member_name, bool):
            show_member_name_enabled = show_member_name
        elif isinstance(show_member_name, str):
            show_member_name_enabled = show_member_name.lower() in ('true', '1', 'yes', 'on')
        elif isinstance(show_member_name, int):
            show_member_name_enabled = show_member_name == 1

        if show_member_name_enabled:
            display_mode = "reply"
        
        if not show_member_name_enabled:
            # 检查入款名字显示配置（有入款记录时才检查）
            if len(user_deposit_txs) > 0:
                deposit_config = await global_config_service.get_config(db, bot_id, "deposit_show_name")
                # 转换值为布尔类型（处理可能的字符串或整数类型）
                deposit_config_bool = None
                if isinstance(deposit_config, bool):
                    deposit_config_bool = deposit_config
                elif isinstance(deposit_config, str):
                    deposit_config_bool = deposit_config.lower() in ('true', '1', 'yes', 'on')
                elif isinstance(deposit_config, int):
                    deposit_config_bool = deposit_config == 1
                if deposit_config_bool is False:  # 明确关闭
                    display_mode = "pure"

            # 检查下发名字显示配置（有下发记录时才检查）
            if len(user_withdraw_txs) > 0:
                withdraw_config = await global_config_service.get_config(db, bot_id, "withdraw_show_name")
                # 转换值为布尔类型（处理可能的字符串或整数类型）
                withdraw_config_bool = None
                if isinstance(withdraw_config, bool):
                    withdraw_config_bool = withdraw_config
                elif isinstance(withdraw_config, str):
                    withdraw_config_bool = withdraw_config.lower() in ('true', '1', 'yes', 'on')
                elif isinstance(withdraw_config, int):
                    withdraw_config_bool = withdraw_config == 1
                if withdraw_config_bool is False:  # 明确关闭
                    display_mode = "pure"
        
        message_text = Formatter.format_user_complete_bill(
            deposits=user_deposit_txs,
            withdraws=user_withdraw_txs,
            summary=summary,
            group_name=group_name,
            user_name=user_name,
            currency=group.currency_display or 'USDT',
            group_exchange_rate=exchange_rate,
            group_fee_rate=fee_rate,
            display_mode=display_mode  # 使用计算后的显示模式
        )
        
        # 🔧 处理 Telegram 消息长度限制（4096 字符）
        if len(message_text) > 4000:
            message_text = f"{group_name}\n{user_name} 今日个人记账汇总：\n\n️ 账单记录较多，请使用「账单」命令查看完整记录"
        
        await update.message.reply_text(message_text, parse_mode="HTML")

"""
账单服务 - 多租户隔离版本

所有方法必须传入 bot_id，确保数据隔离
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging
import uuid

from ..repositories import TransactionRepo, GroupRepo, DailySummaryRepo
from ..utils.calculator import Calculator
from ..models.transaction import TransactionStatus, TransactionCategory

logger = logging.getLogger(__name__)


class BillingService:
    """账单服务类"""

    @staticmethod
    async def create_transaction(
        db,
        bot_id: str,
        group_id: int,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        operator_id: int,
        operator_username: Optional[str],
        operator_first_name: Optional[str],
        transaction_type: str,
        amount: float,
        currency: str = "USDT",
        exchange_rate: Optional[float] = None,
        fee_rate: Optional[float] = None,
        note: str = "",
        message_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        operator_chat_id: Optional[int] = None,  # ✅ 操作人所在聊天ID
        is_correction: bool = False,
        message_date: Optional[datetime] = None,
        trace_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        parent_trace_id: Optional[str] = None  # 🔑 Reversal transaction 关联父交易
    ):
        """
        创建交易记录（使用 Repository）
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID（用于多租户隔离）
            trace_id: 追踪ID（UUID，用于审计和撤销）
            idempotency_key: 幂等性键（防止重复记账）
        """
        # 🔐 幂等性检查
        if idempotency_key:
            from src.repositories import TransactionRepo
            tx_repo = TransactionRepo(db, bot_id)
            existing_tx = await tx_repo.get_by_idempotency_key(idempotency_key)
            
            if existing_tx:
                logger.info(f"[BOT:{bot_id}] Idempotency hit: {idempotency_key}, returning existing transaction {existing_tx.id}")
                
                # 🔥 记录幂等拦截事件
                from .event_service import EventService
                await EventService.log_idempotency_blocked(
                    db=db,
                    bot_id=bot_id,
                    trace_id=trace_id or str(uuid.uuid4()),
                    idempotency_key=idempotency_key,
                    group_id=group_id,
                    existing_transaction_id=existing_tx.id
                )
                
                return existing_tx
        
        # 获取群组配置
        from src.repositories import GroupRepo
        logger.debug(f"[BOT:{bot_id}] 查询群组 group_id={group_id}")
        group_repo = GroupRepo(db, bot_id)
        group = await group_repo.get_by_group_id(group_id)
        
        if not group:
            logger.error(f"[BOT:{bot_id}] Group {group_id} not found!")
            raise ValueError(f"Group {group_id} not found")
        
        # 计算金额
        from ..utils.calculator import Calculator
        calc_result = Calculator.calculate_transaction(
            amount=amount,
            currency=currency,
            exchange_rate=exchange_rate,
            fee_rate=fee_rate
        )
        
        # ✅ 批次锁：获取或创建批次 ID
        from src.services.batch_lock_manager import BatchLockManager
        batch_id, _ = await BatchLockManager.get_or_create_batch(
            bot_id=bot_id,
            exchange_rate=exchange_rate,
            fee_rate=fee_rate,
            description=f"{transaction_type}: {amount} {currency}"
        )

        # 统一将message_date转换为naive datetime（去除时区信息）
        if message_date is not None and message_date.tzinfo is not None:
            message_date = message_date.replace(tzinfo=None)
        
        # 创建交易记录（Repository 自动注入 bot_id）
        from src.repositories import TransactionRepo
        from src.models.transaction import TransactionStatus
        
        tx_repo = TransactionRepo(db, bot_id)
        transaction = await tx_repo.create(
            group_id=group_id,
            user_id=user_id,
            username=username,
            first_name=first_name,
            operator_id=operator_id,
            operator_username=operator_username,
            operator_first_name=operator_first_name,
            operator_chat_id=operator_chat_id,  # ✅ 操作人所在聊天ID
            transaction_type=transaction_type,
            amount=amount,
            currency=currency,
            exchange_rate=exchange_rate,
            fee_rate=fee_rate,
            cny_amount=calc_result['cny_amount'],
            fee_amount=calc_result['fee_amount'],
            final_amount=calc_result['final_amount'],
            amount_usd=calc_result['amount_usd'],  # ✅ 冻结的 USDT 金额（未扣费）
            final_amount_usd=calc_result['final_amount_usd'],  # ✅ 冻结的扣费后USDT金额
            fee_amount_usd=calc_result['fee_amount_usd'],  # ✅ 冻结的手续费 USDT
            note=note,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            is_correction=is_correction,
            transaction_date=datetime.utcnow(),
            message_date=message_date or datetime.utcnow(),
            day_cut_date=datetime.utcnow() if group.day_cut_time else None,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            parent_trace_id=parent_trace_id,  #  Reversal transaction 关联
            status=TransactionStatus.SUCCESS,  # 🔄 设置初始状态
            category=TransactionCategory.REVERSAL if transaction_type.startswith('reversal_') else TransactionCategory.NORMAL,  #  设置交易类别
            batch_id=batch_id  # ✅ 批次锁：绑定批次 ID
        )
        
        logger.info(
            f"[BOT:{bot_id}] Created transaction: type={transaction_type}, "
            f"amount={amount} {currency}, trace_id={trace_id}, "
            f"idempotency_key={idempotency_key}"
        )
        
        # 🔥 记录事件
        from .event_service import EventService
        await EventService.log_transaction_created(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id or str(uuid.uuid4()),
            transaction_id=transaction.id,
            group_id=group_id,
            operator_id=operator_id,
            amount=amount,
            currency=currency,
            transaction_type=transaction_type
        )

        return transaction

    @staticmethod
    async def get_transactions(
        db,
        bot_id: str,
        group_id: int,
        transaction_type: Optional[str] = None,
        user_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None,
        include_deleted: bool = False
    ):
        """
        查询交易记录（使用 Repository）
        """
        tx_repo = TransactionRepo(db, bot_id)
        
        # ✅ 使用 get_visible_transactions 替代 get_by_group，支持更多过滤参数
        transactions = await tx_repo.get_visible_transactions(
            group_id=group_id,
            limit=limit or 100,
            offset=0,
            transaction_type=transaction_type,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date
        )
        
        return transactions

    @staticmethod
    async def get_latest_transaction(
        db,
        bot_id: str,
        group_id: int,
        transaction_type: str
    ):
        """
        获取最新的一条交易记录（使用 Repository）
        """
        tx_repo = TransactionRepo(db, bot_id)
        return await tx_repo.get_latest(group_id, transaction_type)

    @staticmethod
    async def get_transaction_by_message_id(
        db,
        bot_id: str,
        group_id: int,
        message_id: int
    ):
        """
        根据message_id查找交易记录（使用 Repository）
        """
        tx_repo = TransactionRepo(db, bot_id)
        return await tx_repo.get_by_message_id(group_id, message_id)

    @staticmethod
    async def delete_transaction(
        db,
        bot_id: str,
        transaction_id: int
    ) -> bool:
        """
        删除（标记）交易记录（使用 Repository）
        """
        tx_repo = TransactionRepo(db, bot_id)
        success = await tx_repo.soft_delete(transaction_id)
        
        if success:
            logger.info(f"[BOT:{bot_id}] Deleted transaction {transaction_id}")
        
        return success

    @staticmethod
    async def delete_all_transactions(
        db,
        bot_id: str,
        group_id: int
    ) -> int:
        """
        删除（标记）群组所有交易记录（使用 Repository）
        """
        tx_repo = TransactionRepo(db, bot_id)
        count = await tx_repo.soft_delete_all(group_id)
        
        logger.info(f"[BOT:{bot_id}] Deleted {count} transactions for group {group_id}")
        return count

    @staticmethod
    async def get_user_transactions(
        db,
        bot_id: str,
        group_id: int,
        user_id: int,
        limit: Optional[int] = None
    ):
        """
        获取指定用户的交易记录（使用 Repository）
        """
        return await BillingService.get_transactions(
            db=db,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            limit=limit
        )

    @staticmethod
    async def search_user_by_name(
        db,
        bot_id: str,
        group_id: int,
        name_query: str
    ):
        """
        根据名字模糊查询用户ID（使用 Repository）
        """
        tx_repo = TransactionRepo(db, bot_id)
        return await tx_repo.search_users_by_name(group_id, name_query)

    @staticmethod
    async def calculate_summary(
        db,
        bot_id: str,
        group_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        计算账单汇总（使用 Repository）
        """
        transactions = await BillingService.get_transactions(
            db=db,
            bot_id=bot_id,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date
        )

        return Calculator.calculate_summary(transactions)

    @staticmethod
    async def calculate_user_summary(
        db,
        bot_id: str,
        group_id: int,
        user_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        计算用户个人账单汇总（使用 Repository）
        """
        transactions = await BillingService.get_transactions(
            db=db,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date
        )

        return Calculator.calculate_summary(transactions)

    @staticmethod
    async def create_daily_summary(
        db,
        bot_id: str,
        group_id: int,
        summary_date: datetime
    ):
        """
        创建每日汇总（使用 Repository）
        """
        # 计算当日汇总
        start_date = summary_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)

        summary_data = await BillingService.calculate_summary(
            db=db,
            bot_id=bot_id,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date
        )

        # 创建或更新汇总记录（Repository 自动注入 bot_id）
        summary_repo = DailySummaryRepo(db, bot_id)
        daily_summary = await summary_repo.create_or_update(
            group_id=group_id,
            summary_date=summary_date,
            total_deposit_count=summary_data['deposit_count'],
            total_deposit_amount=summary_data['deposit_amount'],
            total_deposit_cny=summary_data['deposit_cny'],
            total_withdraw_count=summary_data['withdraw_count'],
            total_withdraw_amount=summary_data['withdraw_amount'],
            total_withdraw_cny=summary_data['withdraw_cny'],
            total_storage_amount=summary_data['storage_amount'],
            total_fee_amount=summary_data['total_fee'],
            net_amount=summary_data['net_amount']
        )
        
        logger.info(f"[BOT:{bot_id}] Created/updated daily summary for {summary_date.date()}")
        return daily_summary

    @staticmethod
    async def save_bills(
        db,
        bot_id: str,
        group_id: int
    ):
        """
        保存账单（创建当日汇总并标记为已保存）
        """
        today = datetime.utcnow()
        daily_summary = await BillingService.create_daily_summary(
            db=db,
            bot_id=bot_id,
            group_id=group_id,
            summary_date=today
        )

        # 标记为已保存
        daily_summary.is_saved = True
        await db.commit()
        await db.refresh(daily_summary)
        
        logger.info(f"[BOT:{bot_id}] Saved bills for group {group_id}")
        return daily_summary
    
    @staticmethod
    async def revoke_transaction(
        db,
        bot_id: str,
        transaction_id: int,
        operator_id: int,
        reason: str = ""
    ):
        """
        撤销交易（Event Sourcing 模式）
        
        不修改原交易，而是：
        1. 将原交易状态改为 REVOKED
        2. 创建 reversal transaction（反向交易）
        3. 记录审计信息
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
            transaction_id: 要撤销的交易ID
            operator_id: 撤销操作人ID
            reason: 撤销原因
            
        Returns:
            (original_tx, reversal_tx) 元组
        """
        from src.repositories import TransactionRepo
        from src.models.transaction import TransactionStatus
        
        tx_repo = TransactionRepo(db, bot_id)
        
        # 1. 获取原交易
        original_tx = await tx_repo.get_by_id(transaction_id)
        
        if not original_tx:
            raise ValueError(f"Transaction {transaction_id} not found")
        
        if original_tx.status == TransactionStatus.REVOKED:
            raise ValueError(f"Transaction {transaction_id} already revoked")
        
        # 2. 更新原交易状态为 REVOKED
        original_tx.status = TransactionStatus.REVOKED
        original_tx.reversed_by = operator_id
        original_tx.reversed_at = datetime.utcnow()
        original_tx.reversal_reason = reason
        
        await db.flush()  # 先保存原交易状态变更
        
        # 3. 创建 reversal transaction（反向交易）
        import uuid
        reversal_trace_id = str(uuid.uuid4())
        
        # ✅ BUG-3 修复：撤销时不应该反转金额，而是创建一条金额相反的交易
        # 原逻辑：reversal_amount = -original_tx.amount 会导致负数金额
        # 新逻辑：根据原交易类型决定 reversal 的金额正负
        # 例如：原入款 1000，撤销时创建 reversal_deposit -1000
        #      原下发 500，撤销时创建 reversal_withdraw 500
        
        if original_tx.transaction_type == 'deposit':
            reversal_amount = -original_tx.amount  # 入款撤销：金额为负
        elif original_tx.transaction_type == 'withdraw':
            reversal_amount = original_tx.amount   # 下发撤销：金额为正
        else:
            reversal_amount = -original_tx.amount  # 其他类型：金额为负
        
        reversal_tx = await BillingService.create_transaction(
            db=db,
            bot_id=bot_id,
            group_id=original_tx.group_id,
            user_id=original_tx.user_id,
            username=original_tx.username,
            first_name=original_tx.first_name,
            operator_id=operator_id,
            operator_username=original_tx.operator_username,
            operator_first_name=original_tx.operator_first_name,
            operator_chat_id=original_tx.operator_chat_id,  # ✅ 使用原交易的操作人聊天ID
            transaction_type=f"reversal_{original_tx.transaction_type}",  # reversal_deposit / reversal_withdraw
            amount=reversal_amount,  # ✅ 反转后的金额
            currency=original_tx.currency,
            exchange_rate=original_tx.exchange_rate,
            fee_rate=original_tx.fee_rate,
            note=f"撤销交易 #{original_tx.id}: {reason}",
            message_id=None,
            reply_to_message_id=None,
            is_correction=True,
            message_date=datetime.utcnow(),
            trace_id=reversal_trace_id,
            idempotency_key=None,  # reversal transaction 不需要幂等性
            parent_trace_id=original_tx.trace_id  # 🔑 关联父交易
        )
        
        await db.commit()
        
        logger.info(
            f"[BOT:{bot_id}] Revoked transaction {transaction_id}, "
            f"created reversal {reversal_tx.id}, reason: {reason}"
        )
        
        # 🔥 记录撤销事件
        from .event_service import EventService
        await EventService.log_transaction_revoked(
            db=db,
            bot_id=bot_id,
            trace_id=original_tx.trace_id,
            parent_trace_id=reversal_tx.trace_id,
            transaction_id=original_tx.id,
            reversal_transaction_id=reversal_tx.id,
            group_id=original_tx.group_id,
            operator_id=operator_id,
            reason=reason
        )
        
        return original_tx, reversal_tx

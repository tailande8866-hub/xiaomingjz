"""
Transaction Repository - 交易记录数据访问层

所有查询自动注入 bot_id，确保数据隔离
"""
from typing import List, Optional
from datetime import datetime
from sqlalchemy import select, and_, func, desc, update, false

from .base_repo import BaseRepo
from src.models.transaction import Transaction


class TransactionRepo(BaseRepo[Transaction]):
    """
    交易记录 Repository
    
    使用示例：
        repo = TransactionRepo(session, bot_id)
        
        # 获取所有交易
        transactions = await repo.get_all()
        
        # 根据群组获取交易
        transactions = await repo.get_by_group(group_id)
        
        # 创建交易
        tx = await repo.create(
            group_id=group_id,
            user_id=user_id,
            ...
        )
    """
    
    @property
    def model_class(self):
        return Transaction
    
    async def get_by_group(self, group_id: int, limit: int = 50, offset: int = 0) -> List[Transaction]:
        """
        获取指定群组的交易记录
        
        Args:
            group_id: 群组 ID
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            交易记录列表
        """
        stmt = (
            select(Transaction)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.group_id == group_id,
                Transaction.is_deleted.is_(False)
            ))
            .order_by(desc(Transaction.transaction_date))
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_user(self, group_id: int, user_id: int, limit: int = 50) -> List[Transaction]:
        """
        获取指定用户的交易记录
        
        Args:
            group_id: 群组 ID
            user_id: 用户 ID
            limit: 限制数量
            
        Returns:
            交易记录列表
        """
        stmt = (
            select(Transaction)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.group_id == group_id,
                Transaction.user_id == user_id,
                Transaction.is_deleted.is_(False)
            ))
            .order_by(desc(Transaction.transaction_date))
            .limit(limit)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_message_id(self, group_id: int, message_id: int) -> Optional[Transaction]:
        """
        根据 message_id 获取交易记录
        
        Args:
            group_id: 群组 ID
            message_id: 消息 ID
            
        Returns:
            交易记录，如果不存在则返回 None
        """
        stmt = (
            select(Transaction)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.group_id == group_id,
                Transaction.message_id == message_id,
                Transaction.is_deleted.is_(False)
            ))
            .limit(1)
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_type(self, group_id: int, transaction_type: str, limit: int = 50) -> List[Transaction]:
        """
        获取指定类型的交易记录
        
        Args:
            group_id: 群组 ID
            transaction_type: 交易类型 (deposit/withdraw/storage)
            limit: 限制数量
            
        Returns:
            交易记录列表
        """
        stmt = (
            select(Transaction)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.group_id == group_id,
                Transaction.transaction_type == transaction_type,
                Transaction.is_deleted.is_(False)
            ))
            .order_by(desc(Transaction.transaction_date))
            .limit(limit)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_daily_summary(self, group_id: int, date: datetime) -> dict:
        """
        获取每日汇总统计
        
        Args:
            group_id: 群组 ID
            date: 日期
            
        Returns:
            汇总统计数据
        """
        # 入款统计
        deposit_stmt = select(
            func.count(Transaction.id).label('count'),
            func.sum(Transaction.amount).label('total_amount'),
            func.sum(Transaction.cny_amount).label('total_cny')
        ).where(and_(
            Transaction.bot_id == self.bot_id,
            Transaction.group_id == group_id,
            Transaction.transaction_type == 'deposit',
            Transaction.is_deleted.is_(False),
            func.date(Transaction.transaction_date) == func.date(date)
        ))
        
        deposit_result = await self.session.execute(deposit_stmt)
        deposit_row = deposit_result.first()
        
        # 下发统计
        withdraw_stmt = select(
            func.count(Transaction.id).label('count'),
            func.sum(Transaction.amount).label('total_amount'),
            func.sum(Transaction.cny_amount).label('total_cny')
        ).where(and_(
            Transaction.bot_id == self.bot_id,
            Transaction.group_id == group_id,
            Transaction.transaction_type == 'withdraw',
            Transaction.is_deleted.is_(False),
            func.date(Transaction.transaction_date) == func.date(date)
        ))
        
        withdraw_result = await self.session.execute(withdraw_stmt)
        withdraw_row = withdraw_result.first()
        
        return {
            'deposit_count': deposit_row.count or 0,
            'deposit_amount': deposit_row.total_amount or 0.0,
            'deposit_cny': deposit_row.total_cny or 0.0,
            'withdraw_count': withdraw_row.count or 0,
            'withdraw_amount': withdraw_row.total_amount or 0.0,
            'withdraw_cny': withdraw_row.total_cny or 0.0,
        }
    
    async def soft_delete(self, transaction_id: int) -> bool:
        """
        软删除交易记录
        
        Args:
            transaction_id: 交易 ID
            
        Returns:
            是否删除成功
        """
        stmt = (
            update(Transaction)
            .where(and_(
                Transaction.id == transaction_id,
                Transaction.bot_id == self.bot_id
            ))
            .values(is_deleted=True)
        )
        
        result = await self.session.execute(stmt)
        return result.rowcount > 0
    
    async def soft_delete_all(self, group_id: int) -> int:
        """
        软删除群组所有交易记录
        
        Args:
            group_id: 群组 ID
            
        Returns:
            删除的记录数
        """
        stmt = (
            update(Transaction)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.group_id == group_id,
                Transaction.is_deleted.is_(False)
            ))
            .values(is_deleted=True)
        )
        
        result = await self.session.execute(stmt)
        return result.rowcount
    
    async def get_by_sequence_number(
        self,
        group_id: int,
        transaction_type: str,
        sequence_number: int
    ) -> Optional[Transaction]:
        """
        根据序号获取交易记录
        
        Args:
            group_id: 群组 ID
            transaction_type: 交易类型 (deposit/withdraw/storage)
            sequence_number: 序号（从 1 开始）
            
        Returns:
            Transaction 对象或 None
        """
        # ✅ BUG-2 修复：根据序号获取交易记录
        # 注意：数据库中 Transaction 模型没有 sequence_number 字段
        # 我们需要根据 group_id + transaction_type 查询所有记录，然后按 ID 排序
        # 序号从 1 开始，对应第 N 条记录
        from sqlalchemy import desc
        
        # 查询该群组该类型的所有有效交易记录
        stmt = (
            select(Transaction)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.group_id == group_id,
                Transaction.transaction_type == transaction_type,
                Transaction.is_deleted.is_(False)
            ))
            .order_by(desc(Transaction.id))  # 按 ID 降序，最新的在前
        )
        
        result = await self.session.execute(stmt)
        all_transactions = result.scalars().all()
        
        # 转换为列表并反转（最新的在最后）
        all_transactions = list(all_transactions)
        all_transactions.reverse()  # 现在最新的在最后，序号从 1 开始
        
        # 根据序号获取对应的交易记录
        if 1 <= sequence_number <= len(all_transactions):
            return all_transactions[sequence_number - 1]  # 序号从 1 开始，索引从 0 开始
        
        return None
    
    async def search_users_by_name(
        self,
        group_id: int,
        name_query: str
    ) -> List[int]:
        """
        根据名字模糊查询用户ID
        
        Args:
            group_id: 群组 ID
            name_query: 搜索关键词
            
        Returns:
            用户 ID 列表
        """
        from sqlalchemy import or_
        
        stmt = (
            select(Transaction.user_id)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.group_id == group_id,
                or_(
                    Transaction.username.ilike(f"%{name_query}%"),
                    Transaction.first_name.ilike(f"%{name_query}%")
                )
            ))
            .distinct()
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_idempotency_key(
        self,
        idempotency_key: str
    ) -> Optional[Transaction]:
        """
        根据幂等性键查询交易
        
        Args:
            idempotency_key: 幂等性键
            
        Returns:
            Transaction 对象或 None
        """
        stmt = (
            select(Transaction)
            .where(and_(
                Transaction.bot_id == self.bot_id,
                Transaction.idempotency_key == idempotency_key
            ))
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    # ========================================
    # 🔥 Transaction Visibility Policy
    # 金融级可见性策略
    # ========================================
    
    async def get_visible_transactions(
        self,
        group_id: int,
        limit: int = 50,
        offset: int = 0,
        transaction_type: Optional[str] = None,
        user_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Transaction]:
        """
        获取可见交易（只显示 SUCCESS 状态 + NORMAL 类别）
        
        这是用户账单、汇总统计的默认查询方法
        过滤掉：REVOKED/FAILED/PENDING 状态
        过滤掉：REVERSAL/ADJUSTMENT/FEE/SYSTEM 类别
        
        Args:
            group_id: 群组 ID
            limit: 限制数量
            offset: 偏移量
            transaction_type: 交易类型过滤
            user_id: 用户 ID 过滤
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            可见交易列表（仅 SUCCESS 状态 + NORMAL 类别）
        """
        from src.models.transaction import TransactionStatus, TransactionCategory
        
        conditions = [
            Transaction.bot_id == self.bot_id,
            Transaction.group_id == group_id,
            Transaction.status == TransactionStatus.SUCCESS,  # 🔑 只显示 SUCCESS
            Transaction.category == TransactionCategory.NORMAL,  # 🔑 只显示 NORMAL 类别
            Transaction.is_deleted.is_(False)  # 🔑 过滤已删除的记录
        ]
        
        if transaction_type:
            conditions.append(Transaction.transaction_type == transaction_type)
        
        if user_id:
            conditions.append(Transaction.user_id == user_id)
        
        if start_date:
            conditions.append(Transaction.transaction_date >= start_date)
        
        if end_date:
            conditions.append(Transaction.transaction_date < end_date)
        
        stmt = (
            select(Transaction)
            .where(and_(*conditions))
            .order_by(desc(Transaction.transaction_date))
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_audit_transactions(
        self,
        group_id: int,
        status_filter: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Transaction]:
        """
        获取审计交易（管理员模式，可查看所有状态）
        
        Args:
            group_id: 群组 ID
            status_filter: 状态过滤列表（None=全部）
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            审计交易列表
        """
        from src.models.transaction import TransactionStatus
        
        conditions = [
            Transaction.bot_id == self.bot_id,
            Transaction.group_id == group_id
        ]
        
        if status_filter:
            # 将字符串转换为枚举
            statuses = [TransactionStatus(s) for s in status_filter]
            conditions.append(Transaction.status.in_(statuses))
        
        stmt = (
            select(Transaction)
            .where(and_(*conditions))
            .order_by(desc(Transaction.transaction_date))
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_active_summary_transactions(
        self,
        group_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[Transaction]:
        """
        获取用于汇总统计的有效交易
        
        过滤规则：
        - status == SUCCESS
        - category != REVERSAL（撤销交易不参与统计）
        
        Args:
            group_id: 群组 ID
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            有效交易列表（用于汇总统计）
        """
        from src.models.transaction import TransactionStatus, TransactionCategory
        
        conditions = [
            Transaction.bot_id == self.bot_id,
            Transaction.group_id == group_id,
            Transaction.status == TransactionStatus.SUCCESS,
            Transaction.category != TransactionCategory.REVERSAL,  # 🔑 排除 reversal
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
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()

"""
群组额度管理 Repository - 多租户隔离

提供额度配置的 CRUD 操作和额度使用情况查询
"""
import logging
from typing import Optional
from datetime import datetime
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.group_quota import GroupQuota
from ..models.transaction import Transaction, TransactionStatus

logger = logging.getLogger(__name__)


class GroupQuotaRepo:
    """群组额度管理数据访问层"""
    
    def __init__(self, db: AsyncSession, bot_id: str):
        self.db = db
        self.bot_id = bot_id
    
    async def get_by_group_id(self, group_id: int) -> Optional[GroupQuota]:
        """
        获取群组的额度配置
        
        Args:
            group_id: 群组ID
            
        Returns:
            GroupQuota 对象，如果不存在则返回 None
        """
        query = select(GroupQuota).where(
            and_(
                GroupQuota.group_id == group_id,
                GroupQuota.bot_id == self.bot_id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def create_or_update(
        self,
        group_id: int,
        quota_limit: float,
        quota_currency: str = "USDT"
    ) -> GroupQuota:
        """
        创建或更新群组额度配置
        
        Args:
            group_id: 群组ID
            quota_limit: 额度上限
            quota_currency: 额度币种（默认 USDT）
            
        Returns:
            创建或更新后的 GroupQuota 对象
        """
        # 查询是否已存在
        existing = await self.get_by_group_id(group_id)
        
        if existing:
            # 更新现有配置
            existing.quota_limit = quota_limit
            existing.quota_currency = quota_currency
            existing.quota_enabled = True
            existing.updated_at = datetime.utcnow()
            # 重置预警标志，允许重新触发
            existing.warning_threshold_90 = False
            existing.warning_threshold_100 = False
            logger.info(f"[BOT:{self.bot_id}] Updated quota for group {group_id}: {quota_limit} {quota_currency}")
        else:
            # 创建新配置
            new_quota = GroupQuota(
                bot_id=self.bot_id,
                group_id=group_id,
                quota_limit=quota_limit,
                quota_currency=quota_currency,
                quota_enabled=True,
                warning_threshold_90=False,
                warning_threshold_100=False
            )
            self.db.add(new_quota)
            existing = new_quota
            logger.info(f"[BOT:{self.bot_id}] Created quota for group {group_id}: {quota_limit} {quota_currency}")
        
        await self.db.flush()
        return existing
    
    async def disable_quota(self, group_id: int) -> bool:
        """
        禁用群组的额度监控
        
        Args:
            group_id: 群组ID
            
        Returns:
            是否成功禁用
        """
        quota = await self.get_by_group_id(group_id)
        
        if not quota:
            logger.warning(f"[BOT:{self.bot_id}] Quota not found for group {group_id}")
            return False
        
        quota.quota_enabled = False
        quota.updated_at = datetime.utcnow()
        logger.info(f"[BOT:{self.bot_id}] Disabled quota for group {group_id}")
        
        return True
    
    async def reset_warning_flags(self, group_id: int) -> bool:
        """
        重置预警标志（用于额度调整后）
        
        Args:
            group_id: 群组ID
            
        Returns:
            是否成功重置
        """
        quota = await self.get_by_group_id(group_id)
        
        if not quota:
            return False
        
        quota.warning_threshold_90 = False
        quota.warning_threshold_100 = False
        quota.updated_at = datetime.utcnow()
        logger.info(f"[BOT:{self.bot_id}] Reset warning flags for group {group_id}")
        
        return True
    
    async def get_quota_usage(self, group_id: int) -> dict:
        """
        计算群组当前的净入账金额（入款总额 - 下发总额）
        
        Args:
            group_id: 群组ID
            
        Returns:
            字典包含：
            - deposit_total: 入款总额
            - withdraw_total: 下发总额
            - net_amount: 净入账金额
        """
        # 查询入款总额（仅统计 SUCCESS 状态的交易）
        deposit_query = select(func.sum(Transaction.amount)).where(
            and_(
                Transaction.group_id == group_id,
                Transaction.bot_id == self.bot_id,
                Transaction.transaction_type == 'deposit',
                Transaction.status == TransactionStatus.SUCCESS.value
            )
        )
        deposit_result = await self.db.execute(deposit_query)
        deposit_total = deposit_result.scalar() or 0.0
        
        # 查询下发总额
        withdraw_query = select(func.sum(Transaction.amount)).where(
            and_(
                Transaction.group_id == group_id,
                Transaction.bot_id == self.bot_id,
                Transaction.transaction_type == 'withdraw',
                Transaction.status == TransactionStatus.SUCCESS.value
            )
        )
        withdraw_result = await self.db.execute(withdraw_query)
        withdraw_total = withdraw_result.scalar() or 0.0
        
        # 计算净入账
        net_amount = deposit_total - withdraw_total
        
        logger.info(
            f"[BOT:{self.bot_id}] get_quota_usage for group {group_id}: "
            f"deposit_total={deposit_total}, withdraw_total={withdraw_total}, net_amount={net_amount}"
        )
        
        return {
            'deposit_total': deposit_total,
            'withdraw_total': withdraw_total,
            'net_amount': net_amount
        }

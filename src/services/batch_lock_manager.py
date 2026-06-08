"""
批次锁管理器 - 规则快照核心

职责：
1. 生成批次 ID (格式: YYYYMMDD-序号)
2. 创建/查询规则快照
3. 确保同一批次内的交易使用相同规则
"""
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy import select
from src.models.database import AsyncSessionLocal
from src.models.rule_snapshot import RuleSnapshot


class BatchLockManager:
    """批次锁管理器"""
    
    @staticmethod
    def generate_batch_id() -> str:
        """
        生成批次 ID
        
        格式: YYYYMMDD-序号
        例如: 20260523-001, 20260523-002
        
        Returns:
            batch_id 字符串
        """
        today = datetime.now().strftime("%Y%m%d")
        # TODO: 需要查询当天已有批次数量，这里先返回固定序号
        # 实际使用时应该从数据库查询当天的最大序号
        return f"{today}-001"
    
    @staticmethod
    async def get_or_create_batch(
        bot_id: str,
        exchange_rate: float,
        fee_rate: float,
        description: Optional[str] = None
    ) -> Tuple[str, RuleSnapshot]:
        """
        获取或创建批次（带规则快照）
        
        Args:
            bot_id: 机器人 ID
            exchange_rate: 汇率
            fee_rate: 费率 (%)
            description: 批次描述
            
        Returns:
            (batch_id, rule_snapshot) 元组
        """
        async with AsyncSessionLocal() as session:
            # 1. 查找今天是否已有相同规则的批次
            today = datetime.now().strftime("%Y%m%d")
            batch_prefix = f"{today}-"
            
            # 查询今天的所有批次
            result = await session.execute(
                select(RuleSnapshot).where(
                    RuleSnapshot.bot_id == bot_id,
                    RuleSnapshot.batch_id.like(f"{batch_prefix}%"),
                    RuleSnapshot.is_active == True
                ).order_by(RuleSnapshot.created_at.desc())
            )
            today_batches = result.scalars().all()
            
            # 2. 检查是否有相同规则的批次
            for batch in today_batches:
                if (abs(batch.exchange_rate - exchange_rate) < 0.001 and 
                    abs(batch.fee_rate - fee_rate) < 0.001):
                    # 找到相同规则的批次，复用
                    return batch.batch_id, batch
            
            # 3. 没有相同规则的批次，创建新批次
            # 计算新批次的序号
            max_seq = 0
            for batch in today_batches:
                try:
                    seq = int(batch.batch_id.split("-")[1])
                    max_seq = max(max_seq, seq)
                except (IndexError, ValueError):
                    continue
            
            new_seq = max_seq + 1
            new_batch_id = f"{today}-{new_seq:03d}"
            
            # 创建规则快照
            new_snapshot = RuleSnapshot(
                bot_id=bot_id,
                batch_id=new_batch_id,
                exchange_rate=exchange_rate,
                fee_rate=fee_rate,
                description=description or f"汇率{exchange_rate}, 费率{fee_rate}%"
            )
            
            session.add(new_snapshot)
            await session.commit()
            await session.refresh(new_snapshot)
            
            return new_batch_id, new_snapshot
    
    @staticmethod
    async def get_batch_rules(bot_id: str, batch_id: str) -> Optional[RuleSnapshot]:
        """
        查询批次的规则快照
        
        Args:
            bot_id: 机器人 ID
            batch_id: 批次 ID
            
        Returns:
            RuleSnapshot 或 None
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RuleSnapshot).where(
                    RuleSnapshot.bot_id == bot_id,
                    RuleSnapshot.batch_id == batch_id
                )
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def deactivate_batch(bot_id: str, batch_id: str) -> bool:
        """
        停用批次（不再接受新交易）
        
        Args:
            bot_id: 机器人 ID
            batch_id: 批次 ID
            
        Returns:
            是否成功停用
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RuleSnapshot).where(
                    RuleSnapshot.bot_id == bot_id,
                    RuleSnapshot.batch_id == batch_id
                )
            )
            snapshot = result.scalar_one_or_none()
            
            if snapshot:
                snapshot.is_active = False
                await session.commit()
                return True
            return False

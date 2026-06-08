"""
Daily Summary Repository - 每日汇总数据访问层

所有查询自动注入 bot_id，确保数据隔离
"""
from typing import Optional
from datetime import date, datetime
from sqlalchemy import select, and_

from .base_repo import BaseRepo
from src.models.transaction import DailySummary


class DailySummaryRepo(BaseRepo[DailySummary]):
    """
    每日汇总 Repository
    
    使用示例：
        repo = DailySummaryRepo(session, bot_id)
        
        # 获取某日汇总
        summary = await repo.get_by_date(group_id, summary_date)
        
        # 创建或更新汇总
        summary = await repo.create_or_update(...)
    """
    
    @property
    def model_class(self):
        return DailySummary
    
    async def get_by_date(
        self,
        group_id: int,
        summary_date: date
    ) -> Optional[DailySummary]:
        """
        根据日期获取汇总记录
        
        Args:
            group_id: 群组 ID
            summary_date: 汇总日期
            
        Returns:
            DailySummary 对象或 None
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    self.model_class.group_id == group_id,
                    self.model_class.summary_date == summary_date
                )
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create_or_update(
        self,
        group_id: int,
        summary_date: datetime,
        **kwargs
    ) -> DailySummary:
        """
        创建或更新汇总记录
        
        Args:
            group_id: 群组 ID
            summary_date: 汇总日期
            **kwargs: 其他字段
            
        Returns:
            DailySummary 对象
        """
        # 先查找是否已存在
        existing = await self.get_by_date(group_id, summary_date.date())
        
        if existing:
            # 更新现有记录
            for key, value in kwargs.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            
            await self.session.commit()
            await self.session.refresh(existing)
            return existing
        else:
            # 创建新记录（Repository 自动设置 bot_id）
            new_summary = DailySummary(
                bot_id=self.bot_id,
                group_id=group_id,
                summary_date=summary_date.date(),
                **kwargs
            )
            self.session.add(new_summary)
            await self.session.commit()
            await self.session.refresh(new_summary)
            return new_summary

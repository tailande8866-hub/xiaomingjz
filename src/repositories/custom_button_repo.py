"""
Custom Button Repository - 自定义按钮数据访问层

所有查询自动注入 bot_id，确保数据隔离
"""
from typing import List, Optional
from sqlalchemy import select, and_, or_

from .base_repo import BaseRepo
from src.models.group import CustomButton


class CustomButtonRepo(BaseRepo[CustomButton]):
    """
    自定义按钮 Repository
    
    使用示例：
        repo = CustomButtonRepo(session, bot_id)
        
        # 获取活跃按钮（全局 + 当前群组）
        buttons = await repo.get_active_buttons(group_id)
        
        # 创建按钮
        button = await repo.create(...)
    """
    
    @property
    def model_class(self):
        return CustomButton
    
    async def get_active_buttons(
        self,
        group_id: int
    ) -> List[CustomButton]:
        """
        获取活跃按钮（全局按钮 + 当前群组的指定按钮）
        
        Args:
            group_id: 群组 ID
            
        Returns:
            CustomButton 列表
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    or_(
                        self.model_class.group_id == 0,  # 全局按钮
                        self.model_class.group_id == group_id  # 当前群组的指定按钮
                    ),
                    self.model_class.is_active.is_(True)
                )
            )
            .order_by(self.model_class.sort_order)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_group(
        self,
        group_id: int
    ) -> List[CustomButton]:
        """
        获取指定群组的按钮（不包括全局按钮）
        
        Args:
            group_id: 群组 ID
            
        Returns:
            CustomButton 列表
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    self.model_class.group_id == group_id
                )
            )
            .order_by(self.model_class.sort_order)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()

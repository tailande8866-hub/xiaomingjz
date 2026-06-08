"""
Group Repository - 群组数据访问层

所有查询自动注入 bot_id，确保数据隔离
"""
import logging
from typing import List, Optional
from sqlalchemy import select, and_

from .base_repo import BaseRepo
from src.models.group import Group, GroupOperator

logger = logging.getLogger(__name__)


class GroupRepo(BaseRepo[Group]):
    """
    群组 Repository
    
    使用示例：
        repo = GroupRepo(session, bot_id)
        
        # 获取群组
        group = await repo.get_by_group_id(group_id)
        
        # 创建群组
        group = await repo.create(
            group_id=group_id,
            group_name="Test Group",
            ...
        )
    """
    
    @property
    def model_class(self):
        return Group
    
    async def get_by_group_id(self, group_id: int) -> Optional[Group]:
        """
        根据群组 ID 获取群组
        
        Args:
            group_id: Telegram 群组 ID
            
        Returns:
            群组对象或 None
        """
        stmt = select(Group).where(
            and_(
                Group.bot_id == self.bot_id,
                Group.group_id == group_id
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_all_active(self) -> List[Group]:
        """
        获取所有活跃的群组
        
        Returns:
            群组列表
        """
        stmt = select(Group).where(
            and_(
                Group.bot_id == self.bot_id,
                Group.is_active.is_(True)
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()


class GroupOperatorRepo(BaseRepo[GroupOperator]):
    """
    群组操作员 Repository
    """
    
    @property
    def model_class(self):
        return GroupOperator
    
    async def get_operators(self, group_id: int) -> List[GroupOperator]:
        """
        获取群组的操作员列表
        
        Args:
            group_id: 群组 ID
            
        Returns:
            操作员列表
        """
        stmt = select(GroupOperator).where(
            and_(
                GroupOperator.bot_id == self.bot_id,
                GroupOperator.group_id == group_id
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def is_operator(self, group_id: int, user_id: int) -> bool:
        """
        检查用户是否是操作员
        
        Args:
            group_id: 群组 ID
            user_id: 用户 ID
            
        Returns:
            是否是操作员
        """
        stmt = select(GroupOperator).where(
            and_(
                GroupOperator.bot_id == self.bot_id,
                GroupOperator.group_id == group_id,
                GroupOperator.user_id == user_id
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
    
    async def add_operator(self, group_id: int, user_id: int, username: str = None, first_name: str = None) -> GroupOperator:
        """
        添加操作员
        
        Args:
            group_id: 群组 ID
            user_id: 用户 ID
            username: 用户名
            first_name: 名字
            
        Returns:
            创建的操作员记录
        """
        operator = await self.create(
            group_id=group_id,
            user_id=user_id,
            username=username,
            first_name=first_name,
            is_global=False
        )
        return operator
    
    async def remove_operator(self, group_id: int, user_id: int) -> bool:
        """
        移除操作员
        
        Args:
            group_id: 群组 ID
            user_id: 用户 ID
            
        Returns:
            是否移除成功
        """
        from sqlalchemy import delete
        
        stmt = delete(GroupOperator).where(
            and_(
                GroupOperator.bot_id == self.bot_id,
                GroupOperator.group_id == group_id,
                GroupOperator.user_id == user_id
            )
        )
        
        result = await self.session.execute(stmt)
        return result.rowcount > 0
    
    async def set_join_welcome(
        self,
        group_id: int,
        message: str,
        enabled: bool = True
    ) -> bool:
        """
        设置群组入群欢迎语
        
        Args:
            group_id: 群组 ID
            message: 欢迎语文本
            enabled: 是否启用
            
        Returns:
            是否设置成功
        """
        group = await self.get_by_group_id(group_id)
        
        if not group:
            return False
        
        group.join_welcome_message = message
        group.join_welcome_enabled = enabled
        
        logger.info(f"[BOT:{self.bot_id}] Set join welcome for group {group_id}")
        return True
    
    async def toggle_join_welcome(
        self,
        group_id: int,
        enabled: bool
    ) -> bool:
        """
        开关群组入群欢迎语
        
        Args:
            group_id: 群组 ID
            enabled: True 启用，False 禁用
            
        Returns:
            是否操作成功
        """
        group = await self.get_by_group_id(group_id)
        
        if not group:
            return False
        
        group.join_welcome_enabled = enabled
        
        action = "enabled" if enabled else "disabled"
        logger.info(f"[BOT:{self.bot_id}] {action} join welcome for group {group_id}")
        return True

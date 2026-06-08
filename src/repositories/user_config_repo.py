"""
User Config Repository - 用户配置数据访问层

所有查询自动注入 bot_id，确保数据隔离
"""
from typing import Optional
from sqlalchemy import select, and_

from .base_repo import BaseRepo
from src.models.group import UserConfig


class UserConfigRepo(BaseRepo[UserConfig]):
    """
    用户配置 Repository
    
    使用示例：
        repo = UserConfigRepo(session, bot_id)
        
        # 获取用户配置
        config = await repo.get_by_user(group_id, user_id)
        
        # 创建或更新配置
        config = await repo.create_or_update(...)
    """
    
    @property
    def model_class(self):
        return UserConfig
    
    async def get_by_user(
        self,
        group_id: int,
        user_id: int
    ) -> Optional[UserConfig]:
        """
        根据群组ID和用户ID获取配置
        
        Args:
            group_id: 群组 ID
            user_id: 用户 ID
            
        Returns:
            UserConfig 对象或 None
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    self.model_class.group_id == group_id,
                    self.model_class.user_id == user_id
                )
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create_or_update(
        self,
        group_id: int,
        user_id: int,
        **kwargs
    ) -> UserConfig:
        """
        创建或更新用户配置
        
        Args:
            group_id: 群组 ID
            user_id: 用户 ID
            **kwargs: 其他字段（exchange_rate, fee_rate等）
            
        Returns:
            UserConfig 对象
        """
        # 先查找是否已存在
        existing = await self.get_by_user(group_id, user_id)
        
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
            new_config = UserConfig(
                bot_id=self.bot_id,
                group_id=group_id,
                user_id=user_id,
                **kwargs
            )
            self.session.add(new_config)
            await self.session.commit()
            await self.session.refresh(new_config)
            return new_config

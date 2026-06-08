"""
话题模式 Repository - 多租户隔离

所有查询自动注入 bot_id 条件
"""
import logging
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_

from .base_repo import BaseRepo
from ..models.topic_mode import TopicModeSettings, UserTopic, UserActiveTarget, UserBlock

logger = logging.getLogger(__name__)


class TopicModeSettingsRepo(BaseRepo[TopicModeSettings]):
    """话题模式配置 Repository"""

    @property
    def model_class(self):
        return TopicModeSettings

    async def get_settings(self) -> Optional[TopicModeSettings]:
        """获取当前bot的话题模式配置"""
        stmt = select(self.model_class).where(self.model_class.bot_id == self.bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, enabled: bool, group_id: int = None,
                      group_title: str = None, created_by: int = None) -> TopicModeSettings:
        """创建或更新配置"""
        settings = await self.get_settings()
        if settings:
            settings.enabled = enabled
            if group_id is not None:
                settings.group_id = group_id
            if group_title is not None:
                settings.group_title = group_title
            await self.session.flush()
            return settings
        else:
            return await self.create(
                enabled=enabled,
                group_id=group_id,
                group_title=group_title,
                created_by=created_by,
            )


class UserTopicRepo(BaseRepo[UserTopic]):
    """用户话题绑定 Repository"""

    @property
    def model_class(self):
        return UserTopic

    async def get_by_user(self, user_id: int) -> Optional[UserTopic]:
        """获取用户的话题绑定"""
        stmt = select(self.model_class).where(
            and_(self.model_class.bot_id == self.bot_id, self.model_class.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: int, group_id: int, topic_id: int,
                             username: str = None, first_name: str = None) -> UserTopic:
        """获取或创建用户话题绑定"""
        existing = await self.get_by_user(user_id)
        if existing:
            existing.group_id = group_id
            existing.topic_id = topic_id
            existing.active = True
            existing.last_message_at = datetime.utcnow()
            if username:
                existing.username = username
            if first_name:
                existing.first_name = first_name
            await self.session.flush()
            return existing
        return await self.create(
            user_id=user_id,
            group_id=group_id,
            topic_id=topic_id,
            username=username,
            first_name=first_name,
            active=True,
            last_message_at=datetime.utcnow(),
        )

    async def update_last_message(self, user_id: int):
        """更新用户最后消息时间"""
        topic = await self.get_by_user(user_id)
        if topic:
            topic.last_message_at = datetime.utcnow()
            await self.session.flush()

    async def get_active_topics(self, limit: int = 50) -> List[UserTopic]:
        """获取活跃话题列表"""
        stmt = (
            select(self.model_class)
            .where(and_(self.model_class.bot_id == self.bot_id, self.model_class.active == True))
            .order_by(self.model_class.last_message_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def deactivate_all(self):
        """停用所有话题（群组失效时调用）"""
        stmt = (
            select(self.model_class)
            .where(and_(self.model_class.bot_id == self.bot_id, self.model_class.active == True))
        )
        result = await self.session.execute(stmt)
        topics = result.scalars().all()
        for t in topics:
            t.active = False
            t.topic_id = None
        await self.session.flush()


class UserActiveTargetRepo(BaseRepo[UserActiveTarget]):
    """管理员当前聊天目标 Repository"""

    @property
    def model_class(self):
        return UserActiveTarget

    async def get_target(self, admin_user_id: int) -> Optional[UserActiveTarget]:
        """获取管理员的当前聊天目标"""
        stmt = select(self.model_class).where(
            and_(self.model_class.bot_id == self.bot_id, self.model_class.admin_user_id == admin_user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_target(self, admin_user_id: int, target_user_id: int,
                          group_id: int = None, topic_id: int = None) -> UserActiveTarget:
        """设置管理员的聊天目标"""
        existing = await self.get_target(admin_user_id)
        if existing:
            existing.target_user_id = target_user_id
            existing.group_id = group_id
            existing.topic_id = topic_id
            await self.session.flush()
            return existing
        return await self.create(
            admin_user_id=admin_user_id,
            target_user_id=target_user_id,
            group_id=group_id,
            topic_id=topic_id,
        )

    async def clear_target(self, admin_user_id: int):
        """清除管理员的聊天目标"""
        existing = await self.get_target(admin_user_id)
        if existing:
            await self.session.delete(existing)
            await self.session.flush()


class UserBlockRepo(BaseRepo[UserBlock]):
    """用户禁言/拉黑 Repository"""

    @property
    def model_class(self):
        return UserBlock

    async def get_block(self, user_id: int) -> Optional[UserBlock]:
        """获取用户的封禁记录"""
        stmt = select(self.model_class).where(
            and_(self.model_class.bot_id == self.bot_id, self.model_class.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_blocked(self, user_id: int) -> bool:
        """检查用户是否被封禁"""
        block = await self.get_block(user_id)
        if not block:
            return False
        if block.permanent:
            return True
        if block.blocked_until and block.blocked_until > datetime.utcnow():
            return True
        return False

    async def block_user(self, user_id: int, duration_days: int = None,
                          permanent: bool = False, reason: str = None):
        """封禁用户"""
        existing = await self.get_block(user_id)
        blocked_until = None
        if permanent:
            permanent = True
        elif duration_days:
            blocked_until = datetime.utcnow() + __import__('datetime').timedelta(days=duration_days)

        if existing:
            existing.blocked_until = blocked_until
            existing.permanent = permanent
            existing.reason = reason
            await self.session.flush()
            return existing
        return await self.create(
            user_id=user_id,
            blocked_until=blocked_until,
            permanent=permanent,
            reason=reason,
        )

    async def unblock_user(self, user_id: int):
        """解封用户"""
        existing = await self.get_block(user_id)
        if existing:
            await self.session.delete(existing)
            await self.session.flush()

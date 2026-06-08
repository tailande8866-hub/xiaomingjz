"""
超级管理员功能 Repository - 多租户隔离

所有查询自动注入 bot_id 条件
"""
import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, desc

from .base_repo import BaseRepo
from ..models.super_admin import (
    GlobalForwardBlacklist,
    SuperAdminSettings,
    ClosedUser,
    PendingProvision,
    SuperAdminMessageState,
)

logger = logging.getLogger(__name__)


class GlobalForwardBlacklistRepo(BaseRepo[GlobalForwardBlacklist]):
    """全局消息转发黑名单 Repository"""

    @property
    def model_class(self):
        return GlobalForwardBlacklist

    async def get_block(self, user_id: int) -> Optional[GlobalForwardBlacklist]:
        """获取用户的拉黑记录"""
        stmt = select(self.model_class).where(
            and_(self.model_class.bot_id == self.bot_id, self.model_class.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_blocked(self, user_id: int) -> bool:
        """检查用户是否被拉黑"""
        block = await self.get_block(user_id)
        if not block:
            return False
        if block.permanent:
            return True
        if block.blocked_until and block.blocked_until > datetime.utcnow():
            return True
        return False

    async def block_user(self, user_id: int, blocked_by: int,
                         duration_days: int = None, permanent: bool = False,
                         reason: str = None) -> GlobalForwardBlacklist:
        """拉黑用户"""
        blocked_until = None
        if not permanent and duration_days:
            blocked_until = datetime.utcnow() + __import__('datetime').timedelta(days=duration_days)

        existing = await self.get_block(user_id)
        if existing:
            existing.blocked_by = blocked_by
            existing.blocked_at = datetime.utcnow()
            existing.blocked_until = blocked_until
            existing.permanent = permanent
            existing.reason = reason
            await self.session.flush()
            return existing

        return await self.create(
            user_id=user_id,
            blocked_by=blocked_by,
            blocked_until=blocked_until,
            permanent=permanent,
            reason=reason,
        )

    async def unblock_user(self, user_id: int) -> bool:
        """解除拉黑"""
        existing = await self.get_block(user_id)
        if existing:
            await self.session.delete(existing)
            await self.session.flush()
            return True
        return False

    async def get_blocked_list(self, limit: int = 50, offset: int = 0) -> List[GlobalForwardBlacklist]:
        """获取拉黑列表（分页）"""
        stmt = (
            select(self.model_class)
            .where(self.model_class.bot_id == self.bot_id)
            .order_by(desc(self.model_class.blocked_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_blocked(self) -> int:
        """统计拉黑数量"""
        stmt = select(self.model_class).where(self.model_class.bot_id == self.bot_id)
        result = await self.session.execute(stmt)
        return len(result.scalars().all())


class SuperAdminSettingsRepo(BaseRepo[SuperAdminSettings]):
    """超管设置 Repository"""

    @property
    def model_class(self):
        return SuperAdminSettings

    async def get_settings(self) -> Optional[SuperAdminSettings]:
        """获取当前bot的超管设置"""
        stmt = select(self.model_class).where(self.model_class.bot_id == self.bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self) -> SuperAdminSettings:
        """获取或创建设置"""
        settings = await self.get_settings()
        if settings:
            return settings
        return await self.create(do_not_disturb=False)

    async def set_do_not_disturb(self, enabled: bool):
        """设置免打扰模式"""
        settings = await self.get_or_create()
        settings.do_not_disturb = enabled
        await self.session.flush()
        return settings

    async def is_do_not_disturb(self) -> bool:
        """检查是否开启免打扰"""
        settings = await self.get_settings()
        return settings.do_not_disturb if settings else False


class ClosedUserRepo(BaseRepo[ClosedUser]):
    """已关闭用户 Repository"""

    @property
    def model_class(self):
        return ClosedUser

    async def get_closed_user(self, user_id: int) -> Optional[ClosedUser]:
        """获取已关闭用户记录"""
        stmt = select(self.model_class).where(
            and_(self.model_class.bot_id == self.bot_id, self.model_class.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def close_user(self, user_id: int, username: str, closed_by: int,
                         original_expire_time: datetime = None, reason: str = None) -> ClosedUser:
        """关闭用户"""
        existing = await self.get_closed_user(user_id)
        if existing:
            existing.reopened = False
            existing.reopened_at = None
            existing.closed_at = datetime.utcnow()
            existing.closed_by = closed_by
            existing.original_expire_time = original_expire_time
            existing.reason = reason
            await self.session.flush()
            return existing

        return await self.create(
            user_id=user_id,
            username=username,
            closed_by=closed_by,
            original_expire_time=original_expire_time,
            reason=reason,
        )

    async def reopen_user(self, user_id: int) -> bool:
        """重新开通用户"""
        existing = await self.get_closed_user(user_id)
        if existing:
            existing.reopened = True
            existing.reopened_at = datetime.utcnow()
            await self.session.flush()
            return True
        return False

    async def get_closed_list(self, limit: int = 50, offset: int = 0) -> List[ClosedUser]:
        """获取已关闭用户列表（分页）"""
        stmt = (
            select(self.model_class)
            .where(and_(self.model_class.bot_id == self.bot_id, self.model_class.reopened == False))
            .order_by(desc(self.model_class.closed_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class PendingProvisionRepo(BaseRepo[PendingProvision]):
    """待开通用户 Repository"""

    @property
    def model_class(self):
        return PendingProvision

    async def get_pending(self, user_id: int) -> Optional[PendingProvision]:
        """获取待开通记录"""
        stmt = select(self.model_class).where(
            and_(self.model_class.bot_id == self.bot_id, self.model_class.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_pending(self, user_id: int, username: str, provisioned_by: int,
                             duration_days: int, expire_time: datetime,
                             mode: str = "admin_send") -> PendingProvision:
        """创建待开通记录"""
        existing = await self.get_pending(user_id)
        if existing:
            existing.duration_days = duration_days
            existing.expire_time = expire_time
            existing.mode = mode
            existing.provisioned_by = provisioned_by
            existing.provisioned_at = datetime.utcnow()
            existing.completed = False
            existing.completed_at = None
            existing.token_received = False
            existing.token = None
            await self.session.flush()
            return existing

        return await self.create(
            user_id=user_id,
            username=username,
            provisioned_by=provisioned_by,
            duration_days=duration_days,
            expire_time=expire_time,
            mode=mode,
        )

    async def receive_token(self, user_id: int, token: str):
        """用户提交Token"""
        pending = await self.get_pending(user_id)
        if pending:
            pending.token_received = True
            pending.token = token
            await self.session.flush()
            return pending
        return None

    async def complete_provision(self, user_id: int):
        """完成开通"""
        pending = await self.get_pending(user_id)
        if pending:
            pending.completed = True
            pending.completed_at = datetime.utcnow()
            await self.session.flush()
            return pending
        return None


class SuperAdminMessageStateRepo(BaseRepo[SuperAdminMessageState]):
    """超管消息发送状态 Repository"""

    @property
    def model_class(self):
        return SuperAdminMessageState

    async def get_state(self, admin_user_id: int) -> Optional[SuperAdminMessageState]:
        """获取消息发送状态"""
        stmt = select(self.model_class).where(
            and_(self.model_class.bot_id == self.bot_id, self.model_class.admin_user_id == admin_user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_target(self, admin_user_id: int, target_user_id: int) -> SuperAdminMessageState:
        """设置发送目标"""
        existing = await self.get_state(admin_user_id)
        if existing:
            existing.target_user_id = target_user_id
            existing.created_at = datetime.utcnow()
            await self.session.flush()
            return existing
        return await self.create(
            admin_user_id=admin_user_id,
            target_user_id=target_user_id,
        )

    async def clear_state(self, admin_user_id: int):
        """清除状态"""
        existing = await self.get_state(admin_user_id)
        if existing:
            await self.session.delete(existing)
            await self.session.flush()

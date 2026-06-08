"""
试用管理员群组额度服务

职责：
1. 检查试用管理员的群组额度
2. 统计已管理群组数量
3. 提供额度不足提示
"""
import logging
from sqlalchemy import select, and_, func
from typing import Optional, Tuple

from ..models import Admin, Group, get_db_session
from ..models.enums import GroupStatus

logger = logging.getLogger(__name__)


class TrialGroupLimitService:
    """试用管理员群组额度服务"""

    async def check_group_limit(
        self,
        bot_id: str,
        user_id: int
    ) -> Tuple[bool, int, int, Optional[str]]:
        """
        检查试用管理员的群组额度

        Args:
            bot_id: Bot 实例 ID
            user_id: 用户 ID

        Returns:
            (是否允许, 当前数量, 额度限制, 拒绝消息)
            - 如果不是试用管理员，返回 (True, 0, 0, None)
            - 如果是试用管理员且额度充足，返回 (True, current, limit, None)
            - 如果是试用管理员且额度不足，返回 (False, current, limit, message)
        """
        async with get_db_session() as session:
            # 1. 查询用户是否为试用管理员
            stmt = select(Admin).where(
                and_(
                    Admin.bot_id == bot_id,
                    Admin.user_id == user_id,
                    Admin.is_active.is_(True)
                )
            )
            result = await session.execute(stmt)
            admin = result.scalar_one_or_none()

            # 如果不是试用管理员，不限制
            if not admin or not admin.is_trial:
                return True, 0, 0, None

            # 2. 统计当前已管理的群组数量（ACTIVE 状态）
            stmt = select(func.count()).select_from(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.status == GroupStatus.ACTIVE.value,
                    Group.invited_by == user_id  # 该用户拉进群或被指定为主管理员的群组
                )
            )
            result = await session.execute(stmt)
            current_groups = result.scalar() or 0

            # 3. 检查额度
            group_limit = admin.group_limit or 5  # 默认5个

            if current_groups >= group_limit:
                # 额度不足
                message = (
                    f"❌ <b>群组额度不足</b>\n\n"
                    f"试用管理员最多管理 {group_limit} 个群组\n"
                    f"当前：{current_groups}/{group_limit}\n\n"
                    f"请购买正式套餐提升额度。"
                )
                return False, current_groups, group_limit, message

            # 额度充足
            return True, current_groups, group_limit, None

    async def get_trial_admin_info(
        self,
        bot_id: str,
        user_id: int
    ) -> Optional[dict]:
        """
        获取试用管理员信息

        Returns:
            试用管理员信息字典，如果不是试用管理员返回 None
        """
        async with get_db_session() as session:
            stmt = select(Admin).where(
                and_(
                    Admin.bot_id == bot_id,
                    Admin.user_id == user_id,
                    Admin.is_active.is_(True),
                    Admin.is_trial.is_(True)
                )
            )
            result = await session.execute(stmt)
            admin = result.scalar_one_or_none()

            if not admin:
                return None

            # 统计已管理群组数量
            stmt = select(func.count()).select_from(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.status == GroupStatus.ACTIVE.value,
                    Group.invited_by == user_id
                )
            )
            result = await session.execute(stmt)
            current_groups = result.scalar() or 0

            return {
                'is_trial': True,
                'group_limit': admin.group_limit or 5,
                'current_groups': current_groups,
                'expire_time': admin.expire_time,
                'remaining_slots': (admin.group_limit or 5) - current_groups
            }


# 全局实例
trial_group_limit_service = TrialGroupLimitService()

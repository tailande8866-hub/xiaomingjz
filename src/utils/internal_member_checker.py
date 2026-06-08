"""
管理员权限检查工具
"""
import logging
from typing import Optional
from sqlalchemy import select, and_
from ..models import Admin, get_db

logger = logging.getLogger(__name__)


async def is_admin(user_id: int, bot_id: str = None) -> bool:
    """
    检查用户是否为管理员（支持租户隔离）
    
    Args:
        user_id: Telegram用户ID
        bot_id: 机器人实例ID（可选，用于租户隔离）
        
    Returns:
        bool: 是否为管理员
    """
    try:
        async for db in get_db():
            conditions = [
                Admin.user_id == user_id,
                Admin.is_active.is_(True)
            ]
            
            # ✅ 如果提供了 bot_id，则进行租户隔离
            if bot_id:
                conditions.append(Admin.bot_id == bot_id)
            
            query = select(Admin).where(and_(*conditions))
            result = await db.execute(query)
            member = result.scalar_one_or_none()
            
            if member:
                logger.debug(f"User {user_id} is admin (bot_id={bot_id})")
                return True
            
            logger.debug(f"User {user_id} is NOT admin (bot_id={bot_id})")
            return False
    except Exception as e:
        logger.error(f"Error checking admin: {e}", exc_info=True)
        return False


async def get_admin(user_id: int, bot_id: str = None) -> Optional[Admin]:
    """
    获取管理员信息（支持租户隔离）
    
    Args:
        user_id: Telegram用户ID
        bot_id: 机器人实例ID（可选，用于租户隔离）
        
    Returns:
        Admin对象或None
    """
    try:
        async for db in get_db():
            conditions = [
                Admin.user_id == user_id,
                Admin.is_active.is_(True)
            ]
            
            # ✅ 如果提供了 bot_id，则进行租户隔离
            if bot_id:
                conditions.append(Admin.bot_id == bot_id)
            
            query = select(Admin).where(and_(*conditions))
            result = await db.execute(query)
            member = result.scalar_one_or_none()
            
            return member
    except Exception as e:
        logger.error(f"Error getting admin: {e}", exc_info=True)
        return None


async def check_admin_permission(user_id: int, permission: str, bot_id: str = None) -> bool:
    """
    检查管理员的特定权限（支持租户隔离）
    
    Args:
        user_id: Telegram用户ID
        permission: 权限名称
            - 'can_create_bot': 创建机器人
            - 'can_manage_admins': 管理其他管理员
            - 'can_manage_group_members': 管理群成员
            - 'can_broadcast': 群发广播/分组广播
            - 'can_set_day_cut': 设置日切时间
            - 'can_set_keywords': 设置关键词回复
        bot_id: 机器人实例ID（可选，用于租户隔离）
            
    Returns:
        bool: 是否有该权限
    """
    try:
        member = await get_admin(user_id, bot_id)
        
        if not member:
            logger.debug(f"User {user_id} is not admin (bot_id={bot_id}), permission denied")
            return False
        
        # 检查具体权限
        has_permission = getattr(member, permission, False)
        
        if has_permission:
            logger.debug(f"User {user_id} has permission: {permission} (bot_id={bot_id})")
        else:
            logger.debug(f"User {user_id} does NOT have permission: {permission} (bot_id={bot_id})")
        
        return has_permission
    except Exception as e:
        logger.error(f"Error checking admin permission: {e}", exc_info=True)
        return False

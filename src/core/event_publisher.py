"""
事件发布工具函数

提供便捷的事件发布函数，用于在关键位置发布事件
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ..core.event_bus import event_bus, EventType

logger = logging.getLogger(__name__)


async def publish_bot_created(bot_id: str, root_bot_id: str, owner_id: int, instance_dir: str):
    """
    发布 Bot 创建事件
    
    Args:
        bot_id: Bot 实例 ID
        root_bot_id: 根 Bot ID
        owner_id: 所有者 Telegram ID
        instance_dir: 实例目录路径
    """
    await event_bus.publish_simple(
        event_type=EventType.BOT_CREATED,
        data={
            'bot_id': bot_id,
            'root_bot_id': root_bot_id,
            'owner_id': owner_id,
            'instance_dir': instance_dir,
            'timestamp': datetime.utcnow().isoformat()
        },
        bot_id=bot_id,
        root_bot_id=root_bot_id
    )
    logger.info(f"Published BOT_CREATED event for {bot_id}")


async def publish_bot_started(bot_id: str, root_bot_id: str):
    """
    发布 Bot 启动事件
    
    Args:
        bot_id: Bot 实例 ID
        root_bot_id: 根 Bot ID
    """
    await event_bus.publish_simple(
        event_type=EventType.BOT_STARTED,
        data={
            'bot_id': bot_id,
            'root_bot_id': root_bot_id,
            'timestamp': datetime.utcnow().isoformat()
        },
        bot_id=bot_id,
        root_bot_id=root_bot_id
    )
    logger.info(f"Published BOT_STARTED event for {bot_id}")


async def publish_bot_stopped(bot_id: str, root_bot_id: str):
    """
    发布 Bot 停止事件
    
    Args:
        bot_id: Bot 实例 ID
        root_bot_id: 根 Bot ID
    """
    await event_bus.publish_simple(
        event_type=EventType.BOT_STOPPED,
        data={
            'bot_id': bot_id,
            'root_bot_id': root_bot_id,
            'timestamp': datetime.utcnow().isoformat()
        },
        bot_id=bot_id,
        root_bot_id=root_bot_id
    )
    logger.info(f"Published BOT_STOPPED event for {bot_id}")


async def publish_group_status_changed(group_id: int, bot_id: str, old_status: str, new_status: str):
    """
    发布群组状态变更事件
    
    Args:
        group_id: 群组 ID
        bot_id: Bot 实例 ID
        old_status: 旧状态
        new_status: 新状态
    """
    # 获取 root_bot_id（需要查询数据库）
    from ..models import BotCreation, get_db_session
    from sqlalchemy import select
    
    root_bot_id = bot_id  # 默认值
    async with get_db_session() as db:
        query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        result = await db.execute(query)
        bot_creation = result.scalar_one_or_none()
        if bot_creation:
            root_bot_id = bot_creation.root_bot_id or bot_id
    
    await event_bus.publish_simple(
        event_type=EventType.GROUP_STATUS_CHANGED,
        data={
            'group_id': group_id,
            'bot_id': bot_id,
            'old_status': old_status,
            'new_status': new_status,
            'timestamp': datetime.utcnow().isoformat()
        },
        bot_id=bot_id,
        root_bot_id=root_bot_id
    )
    logger.info(f"Published GROUP_STATUS_CHANGED event for group {group_id} in bot {bot_id}")


async def publish_permission_changed(user_id: int, bot_id: str, permission: str, granted: bool):
    """
    发布权限变更事件
    
    Args:
        user_id: 用户 Telegram ID
        bot_id: Bot 实例 ID
        permission: 权限名称
        granted: 是否授予
    """
    # 获取 root_bot_id
    from ..models import BotCreation, get_db_session
    from sqlalchemy import select
    
    root_bot_id = bot_id
    async with get_db_session() as db:
        query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        result = await db.execute(query)
        bot_creation = result.scalar_one_or_none()
        if bot_creation:
            root_bot_id = bot_creation.root_bot_id or bot_id
    
    await event_bus.publish_simple(
        event_type=EventType.PERMISSION_CHANGED,
        data={
            'user_id': user_id,
            'bot_id': bot_id,
            'permission': permission,
            'granted': granted,
            'timestamp': datetime.utcnow().isoformat()
        },
        bot_id=bot_id,
        root_bot_id=root_bot_id
    )
    logger.info(f"Published PERMISSION_CHANGED event for user {user_id} in bot {bot_id}")


async def publish_admin_added(user_id: int, bot_id: str, admin_permissions: Dict[str, bool]):
    """
    发布管理员添加事件
    
    Args:
        user_id: 用户 Telegram ID
        bot_id: Bot 实例 ID
        admin_permissions: 管理员权限字典
    """
    # 获取 root_bot_id
    from ..models import BotCreation, get_db_session
    from sqlalchemy import select
    
    root_bot_id = bot_id
    async with get_db_session() as db:
        query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        result = await db.execute(query)
        bot_creation = result.scalar_one_or_none()
        if bot_creation:
            root_bot_id = bot_creation.root_bot_id or bot_id
    
    await event_bus.publish_simple(
        event_type=EventType.ADMIN_ADDED,
        data={
            'user_id': user_id,
            'bot_id': bot_id,
            'permissions': admin_permissions,
            'timestamp': datetime.utcnow().isoformat()
        },
        bot_id=bot_id,
        root_bot_id=root_bot_id
    )
    logger.info(f"Published ADMIN_ADDED event for user {user_id} in bot {bot_id}")


async def publish_config_updated(bot_id: str, config_key: str, old_value: Any, new_value: Any):
    """
    发布配置更新事件
    
    Args:
        bot_id: Bot 实例 ID
        config_key: 配置键
        old_value: 旧值
        new_value: 新值
    """
    # 获取 root_bot_id
    from ..models import BotCreation, get_db_session
    from sqlalchemy import select
    
    root_bot_id = bot_id
    async with get_db_session() as db:
        query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        result = await db.execute(query)
        bot_creation = result.scalar_one_or_none()
        if bot_creation:
            root_bot_id = bot_creation.root_bot_id or bot_id
    
    await event_bus.publish_simple(
        event_type=EventType.VERSION_UPDATED,  # 使用 VERSION_UPDATED 代替 CONFIG_UPDATED
        data={
            'bot_id': bot_id,
            'config_key': config_key,
            'old_value': old_value,
            'new_value': new_value,
            'timestamp': datetime.utcnow().isoformat()
        },
        bot_id=bot_id,
        root_bot_id=root_bot_id
    )
    logger.info(f"Published CONFIG_UPDATED event for {config_key} in bot {bot_id}")

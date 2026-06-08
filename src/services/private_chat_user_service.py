"""
私聊用户管理服务
负责记录和查询与机器人私聊过的用户
"""
import logging
from typing import Optional
from telegram import User
from sqlalchemy import select
from ..models import PrivateChatUser, get_db

logger = logging.getLogger(__name__)


async def save_private_chat_user(telegram_user: User) -> None:
    """
    保存私聊用户信息
    
    Args:
        telegram_user: Telegram用户对象
    """
    try:
        async for db in get_db():
            # 检查用户是否已存在
            query = select(PrivateChatUser).where(PrivateChatUser.user_id == telegram_user.id)
            result = await db.execute(query)
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                # 更新用户信息
                existing_user.username = telegram_user.username
                existing_user.first_name = telegram_user.first_name
                existing_user.last_name = telegram_user.last_name
                existing_user.language_code = telegram_user.language_code
                existing_user.is_bot = telegram_user.is_bot
                logger.debug(f"Updated private chat user: {telegram_user.id}")
            else:
                # 创建新用户记录
                new_user = PrivateChatUser(
                    user_id=telegram_user.id,
                    username=telegram_user.username,
                    first_name=telegram_user.first_name,
                    last_name=telegram_user.last_name,
                    language_code=telegram_user.language_code,
                    is_bot=telegram_user.is_bot
                )
                db.add(new_user)
                logger.info(f"Saved new private chat user: {telegram_user.id} (@{telegram_user.username})")
            
            await db.commit()
    except Exception as e:
        logger.error(f"Error saving private chat user: {e}", exc_info=True)


async def get_user_by_username(username: str, context=None) -> Optional[PrivateChatUser]:
    """
    根据用户名查找私聊用户
    
    Args:
        username: Telegram用户名（不带@）
        context: Bot上下文，用于获取当前bot_id进行租户隔离
        
    Returns:
        PrivateChatUser对象或None
    """
    try:
        # 移除@符号
        username = username.lstrip('@')
        
        async for db in get_db():
            # 使用租户隔离查询
            from ..utils.tenant_scope import scoped_query
            from ..utils.bot_id_middleware import get_current_bot_id
            
            if context:
                # 如果有context，使用租户隔离查询
                bot_id = get_current_bot_id(context)
                query = scoped_query(PrivateChatUser, context).where(
                    PrivateChatUser.username == username
                )
            else:
                # 否则查询所有记录（向后兼容）
                query = select(PrivateChatUser).where(
                    PrivateChatUser.username == username
                )
            
            result = await db.execute(query)
            users = result.scalars().all()
            
            if not users:
                logger.debug(f"User not found by username: {username}")
                return None
            
            # 如果有重复记录，返回第一条并记录警告
            if len(users) > 1:
                logger.warning(f"Found {len(users)} duplicate records for username: {username}, using first one (ID: {users[0].user_id})")
            else:
                logger.debug(f"Found user by username: {username} (ID: {users[0].user_id})")
            
            return users[0]
    except Exception as e:
        logger.error(f"Error getting user by username: {e}", exc_info=True)
        return None


async def get_user_by_user_id(user_id: int) -> Optional[PrivateChatUser]:
    """
    根据用户ID查找私聊用户
    
    Args:
        user_id: Telegram用户ID
        
    Returns:
        PrivateChatUser对象或None
    """
    try:
        async for db in get_db():
            query = select(PrivateChatUser).where(
                PrivateChatUser.user_id == user_id
            )
            result = await db.execute(query)
            user = result.scalar_one_or_none()
            
            return user
    except Exception as e:
        logger.error(f"Error getting user by user_id: {e}", exc_info=True)
        return None

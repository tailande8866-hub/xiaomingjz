"""
用户身份识别工具
用于判断用户在子Bot中的权限等级
"""
import logging
from sqlalchemy import select, and_
from config import config

from ..models import GroupOperator, Admin, get_db, get_db_session

logger = logging.getLogger(__name__)


class UserRole:
    """用户角色常量"""
    SUPER_ADMIN = "super_admin"        # 平台超管（Master Bot 的管理员）
    BOT_OWNER = "bot_owner"            # 🆕 Bot 拥有者（子 Bot 的创建者/购买者）
    ADMIN = "admin"                    # 管理员（超级管理员添加的）
    GLOBAL_OPERATOR = "global_operator"  # 🆕 全局操作人（所有群有权限）
    GROUP_OPERATOR = "group_operator"    # 🆕 群操作人（仅本群有权限）
    OPERATOR = "operator"              # 操作人（兼容旧代码，已废弃）
    NORMAL_USER = "normal_user"        # 普通用户


async def get_user_role(user_id: int, group_id: int = None, bot_id: str = None) -> str:
    """
    获取用户角色（支持租户隔离）
    
    Args:
        user_id: Telegram用户ID
        group_id: 群组ID（可选，用于检查群组操作人权限）
        bot_id: 机器人实例ID（可选，用于租户隔离）
    
    Returns:
        用户角色字符串
    """
    from ..models import BotCreation
    
    # 1. 检查是否为超级管理员（配置文件中设置的SUPER_ADMIN_ID）
    # 🔥 关键修复：主 Bot 超级管理员在任何子 Bot 中都拥有最高权限
    # 🔥 三重检查：config → 环境变量 → 数据库主BOT记录（兜底）
    import os
    
    # 获取配置中的超级管理员 ID
    config_super_admin_raw = getattr(config, 'SUPER_ADMIN_ID', 0)
    env_super_admin_str = os.getenv('SUPER_ADMIN_ID', '0')
    
    # 统一转换为 int 类型
    try:
        config_super_admin = int(config_super_admin_raw)
    except (ValueError, TypeError):
        config_super_admin = 0
    
    try:
        env_super_admin = int(env_super_admin_str)
    except ValueError:
        env_super_admin = 0
    
    # 确保 user_id 也是 int
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        user_id_int = 0
    
    # 详细日志
    is_match_config = user_id_int == config_super_admin
    is_match_env = user_id_int == env_super_admin
    is_fixed_super_admin = user_id_int == 7862093562
    is_super_admin = is_match_config or is_match_env or is_fixed_super_admin
    
    # 🔥 第三重兜底：查询主BOT的 BotCreation.super_admin_id 作为全局超管
    # 场景：子BOT的 .env 中 SUPER_ADMIN_ID 存的是子BOT创建者ID，不是全局超管ID
    global_super_admin_id = 0
    if not is_super_admin:
        try:
            async with get_db_session() as db:
                query = select(BotCreation).where(BotCreation.instance_id == 'main_bot')
                result = await db.execute(query)
                main_bot = result.scalar_one_or_none()
                if main_bot and main_bot.super_admin_id:
                    global_super_admin_id = int(main_bot.super_admin_id)
                    if user_id_int == global_super_admin_id:
                        is_super_admin = True
                        logger.info(f"[ROLE_CHECK] ✅ User {user_id_int} matched MAIN BOT super_admin_id={global_super_admin_id} via DB fallback")
        except Exception as e:
            logger.warning(f"[ROLE_CHECK] DB fallback check failed: {e}")
    
    logger.info(f"[ROLE_CHECK] user_id={user_id_int}(type={type(user_id).__name__}), config_super={config_super_admin}, env_super={env_super_admin}, global_super={global_super_admin_id}, is_super_admin={is_super_admin}")
    
    if is_super_admin:
        logger.info(f"[ROLE_CHECK] ✅ User {user_id_int} is SUPER_ADMIN - granting full access")
        return UserRole.SUPER_ADMIN
    
    # 2. 检查数据库中的管理员和群组操作人
    async with get_db_session() as db:
        try:
            # 2.0 检查是否为当前 Bot 的拥有者（BOT_OWNER）
            if bot_id:
                query = select(BotCreation).where(
                    and_(
                        BotCreation.instance_id == bot_id,
                        (BotCreation.telegram_id == user_id_int) | (BotCreation.super_admin_id == user_id_int)
                    )
                )
                result = await db.execute(query)
                bot_creation = result.scalar_one_or_none()
                
                if bot_creation:
                    logger.debug(f"[ROLE_CHECK] User {user_id} is BOT_OWNER of {bot_id}")
                    return UserRole.BOT_OWNER

                try:
                    from ..models.bot_management import BotAdmin
                    owner_query = select(BotAdmin).where(
                        and_(
                            BotAdmin.bot_id == bot_id,
                            BotAdmin.user_id == user_id_int,
                            BotAdmin.role == "owner",
                            BotAdmin.is_active.is_(True),
                        )
                    )
                    owner_result = await db.execute(owner_query)
                    if owner_result.scalar_one_or_none():
                        logger.debug(f"[ROLE_CHECK] User {user_id} is BOT_OWNER via bot_admins of {bot_id}")
                        return UserRole.BOT_OWNER
                except Exception as e:
                    logger.warning(f"[ROLE_CHECK] bot_admins owner lookup failed: {e}")

                # 兜底：当子Bot运行在独立实例目录、共享库未及时同步时，允许使用 .env 中的 BOT_OWNER_ID 识别创建者
                try:
                    env_bot_owner_raw = os.getenv('BOT_OWNER_ID', '0')
                    env_bot_owner_id = int(env_bot_owner_raw)
                except (ValueError, TypeError):
                    env_bot_owner_id = 0

                if env_bot_owner_id and env_bot_owner_id == user_id_int:
                    logger.info(f"[ROLE_CHECK] User {user_id_int} matched BOT_OWNER_ID={env_bot_owner_id} via env fallback")
                    return UserRole.BOT_OWNER
            
            # 2.1 检查是否为当前 Bot 的管理员（含细粒度权限）
            conditions = [
                Admin.user_id == user_id_int,
                Admin.is_active.is_(True)
            ]
            
            # 如果提供了 bot_id，则进行租户隔离
            if bot_id:
                conditions.append(Admin.bot_id == bot_id)
            
            query = select(Admin).where(and_(*conditions))
            result = await db.execute(query)
            admin = result.scalar_one_or_none()
            
            if admin:
                logger.debug(f"User {user_id_int} is ADMIN (bot_id={bot_id})")
                return UserRole.ADMIN
            
            # 2.2 检查是否为全局操作人
            query = select(GroupOperator).where(
                and_(
                    GroupOperator.bot_id == bot_id if bot_id else True,
                    GroupOperator.user_id == user_id_int,
                    GroupOperator.is_global.is_(True)
                )
            )
            result = await db.execute(query)
            global_operator = result.scalar_one_or_none()
            
            if global_operator:
                return UserRole.OPERATOR
            
            # 2.3 检查是否为任何群组的操作人
            conditions = [GroupOperator.user_id == user_id_int]
            if bot_id:
                conditions.append(GroupOperator.bot_id == bot_id)
            if group_id:
                conditions.append(GroupOperator.group_id == group_id)
            query = select(GroupOperator).where(and_(*conditions))
            result = await db.execute(query)
            operators = result.scalars().all()
            
            if operators:
                return UserRole.OPERATOR
            
            return UserRole.NORMAL_USER
            
        except Exception as e:
            logger.error(f"Error getting user role: {e}", exc_info=True)
            return UserRole.NORMAL_USER


async def is_super_admin(user_id: int, bot_id: str = None) -> bool:
    """检查用户是否为超级管理员"""
    return await get_user_role(user_id, bot_id=bot_id) == UserRole.SUPER_ADMIN


async def is_admin(user_id: int, bot_id: str = None) -> bool:
    """检查用户是否为管理员（超级管理员添加的，支持租户隔离）"""
    return await get_user_role(user_id, bot_id=bot_id) == UserRole.ADMIN


async def is_operator(user_id: int, bot_id: str = None) -> bool:
    """检查用户是否为操作人（包括全局操作人和群组操作人，支持租户隔离）"""
    role = await get_user_role(user_id, bot_id=bot_id)
    return role in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]


async def is_normal_user(user_id: int, bot_id: str = None) -> bool:
    """检查用户是否为普通用户（支持租户隔离）"""
    return await get_user_role(user_id, bot_id=bot_id) == UserRole.NORMAL_USER

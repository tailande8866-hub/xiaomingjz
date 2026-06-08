"""
统一权限服务 (Permission Service)

职责：
1. 统一权限检查入口
2. 支持租户隔离（bot_id）
3. 支持权限继承
4. 细粒度权限控制

设计原则：
- 所有权限检查走这里，不再散落各处
- 运行时计算权限继承，不在数据库存储
- 支持未来扩展新权限无需修改多处代码
"""
import logging
from enum import Enum
from typing import Set
from sqlalchemy import select, and_

from ..models import Admin, GroupOperator, BotCreation, get_db_session
from ..utils.role_checker import UserRole

logger = logging.getLogger(__name__)


class Permission(Enum):
    """权限枚举（避免硬编码字符串）"""
    
    # 管理员权限
    MANAGE_ADMINS = "manage_admins"           # 管理管理员（添加/删除）
    CREATE_BOT = "create_bot"                 # 创建机器人（无限裂变）
    RENEW_BOT = "renew_bot"                   # 续费
    
    # 群组管理权限
    MANAGE_GROUPS = "manage_groups"           # 管理群组（分组、授权）
    AUTHORIZE_GROUP = "authorize_group"       # 授权群组
    
    # 业务功能权限
    BILLING = "billing"                       # 记账功能
    QUERY = "query"                           # 查询账单
    BROADCAST = "broadcast"                   # 广播（群发/分组广播）
    SETTINGS = "settings"                     # 设置（关键词、日切、欢迎语等）
    
    def __str__(self):
        return self.value


class PermissionService:
    """统一权限服务"""
    
    # === 角色权限矩阵（支持继承）===
    # 注意：这是运行时计算，不存储在数据库中
    
    ROLE_PERMISSIONS: dict[UserRole, Set[Permission]] = {
        # L1: 超级管理员 - 拥有所有权限，包括手动开通/续费/全平台广播
        UserRole.SUPER_ADMIN: {
            Permission.MANAGE_ADMINS,
            Permission.CREATE_BOT,
            Permission.RENEW_BOT,
            Permission.MANAGE_GROUPS,
            Permission.AUTHORIZE_GROUP,
            Permission.BILLING,
            Permission.QUERY,
            Permission.BROADCAST,
            Permission.SETTINGS,
        },
        
        # L2: Bot 拥有者 - 在自己的 Bot 中拥有所有权限，可以裂变创建下级Bot
        UserRole.BOT_OWNER: {
            Permission.MANAGE_ADMINS,
            Permission.CREATE_BOT,
            Permission.RENEW_BOT,
            Permission.MANAGE_GROUPS,
            Permission.AUTHORIZE_GROUP,
            Permission.BILLING,
            Permission.QUERY,
            Permission.BROADCAST,
            Permission.SETTINGS,
        },
        
        # L3: Bot 管理员 - 拥有大部分管理权限（包括创建Bot和续费）
        UserRole.ADMIN: {
            Permission.MANAGE_GROUPS,
            Permission.AUTHORIZE_GROUP,
            Permission.BILLING,
            Permission.QUERY,
            Permission.BROADCAST,
            Permission.SETTINGS,
            Permission.CREATE_BOT,  # ✅ 可以付费创建自己的Bot
            Permission.RENEW_BOT,   # ✅ 可以续费
            # 注意：MANAGE_ADMINS 需要细粒度权限控制
        },
        
        # L4: 全局操作人 - 所有群组的业务操作，可以付费创建自己的Bot
        UserRole.GLOBAL_OPERATOR: {
            Permission.BILLING,
            Permission.QUERY,
            Permission.CREATE_BOT,  # ✅ 可以付费创建自己的Bot
        },
        
        # L5: 群操作人 - 所属群组的业务操作，可以付费创建自己的Bot
        UserRole.GROUP_OPERATOR: {
            Permission.BILLING,
            Permission.QUERY,
            Permission.CREATE_BOT,  # ✅ 可以付费创建自己的Bot
        },
        
        # L6: 普通用户 - 仅查询功能，可以付费创建自己的Bot
        UserRole.NORMAL_USER: {
            Permission.QUERY,
            Permission.CREATE_BOT,  # ✅ 可以付费创建自己的Bot
        },
    }
    
    @classmethod
    async def has_permission(cls, bot_id: str, user_id: int, permission: Permission) -> bool:
        """
        检查用户是否有指定权限（统一入口）
        
        Args:
            bot_id: Bot 实例 ID（租户隔离）
            user_id: 用户 Telegram ID
            permission: 权限枚举
        
        Returns:
            是否有权限
        
        Example:
            if await permission_service.has_permission(bot_id, user_id, Permission.MANAGE_ADMINS):
                # 允许操作
                pass
        """
        # 1. 获取用户角色
        user_role = await cls._get_user_role(user_id, bot_id)
        
        # 2. 检查角色基础权限
        if permission in cls.ROLE_PERMISSIONS.get(user_role, set()):
            logger.debug(f"✅ User {user_id} ({user_role}) has permission: {permission}")
            return True
        
        # 3. 特殊处理：Admin 的细粒度权限
        if user_role == UserRole.ADMIN:
            has_fine_grained = await cls._check_admin_fine_grained_permission(
                user_id, bot_id, permission
            )
            if has_fine_grained:
                logger.debug(f"✅ Admin {user_id} has fine-grained permission: {permission}")
                return True
        
        logger.debug(f"❌ User {user_id} ({user_role}) denied permission: {permission}")
        return False
    
    @classmethod
    async def _get_user_role(cls, user_id: int, bot_id: str) -> str:
        """
        获取用户角色（增强版，区分 GLOBAL 和 GROUP operator）
        
        优先级：
        SUPER_ADMIN > BOT_OWNER > ADMIN > GLOBAL_OPERATOR > GROUP_OPERATOR > NORMAL_USER
        
        🔥 统一使用 role_checker.get_user_role，确保超管判断逻辑一致
        """
        from ..utils.role_checker import get_user_role
        return await get_user_role(user_id, bot_id=bot_id)
    
    @classmethod
    async def _check_admin_fine_grained_permission(
        cls, user_id: int, bot_id: str, permission: Permission
    ) -> bool:
        """
        检查 Admin 的细粒度权限
        
        Admin 表中存储了详细的权限字段，用于覆盖默认权限
        """
        async with get_db_session() as db:
            query = select(Admin).where(
                and_(
                    Admin.user_id == user_id,
                    Admin.bot_id == bot_id,
                    Admin.is_active.is_(True)
                )
            )
            result = await db.execute(query)
            admin = result.scalar_one_or_none()
            
            if not admin:
                return False
            
            # 权限映射：Permission 枚举 -> Admin 表字段（优化版）
            permission_field_map = {
                Permission.MANAGE_ADMINS: admin.can_manage_admins,
                Permission.CREATE_BOT: admin.can_create_bot,
                Permission.RENEW_BOT: admin.can_renew,
                Permission.MANAGE_GROUPS: admin.can_manage_group_members,
                Permission.AUTHORIZE_GROUP: admin.can_manage_group_members,
                Permission.BILLING: admin.can_billing,
                Permission.QUERY: admin.can_query,
                Permission.BROADCAST: admin.can_broadcast,
                Permission.SETTINGS: admin.can_set_keywords or admin.can_set_day_cut or admin.can_settings,
            }
            
            # 获取对应的字段值
            field_value = permission_field_map.get(permission)
            if field_value is None:
                # 没有映射的权限，使用角色默认权限
                return False
            
            return bool(field_value)
    
    @classmethod
    async def get_user_permissions(cls, bot_id: str, user_id: int) -> Set[Permission]:
        """
        获取用户的所有权限
        
        Args:
            bot_id: Bot 实例 ID
            user_id: 用户 Telegram ID
        
        Returns:
            权限集合
        """
        user_role = await cls._get_user_role(user_id, bot_id)
        permissions = cls.ROLE_PERMISSIONS.get(user_role, set()).copy()
        
        # 如果是 Admin，合并细粒度权限
        if user_role == UserRole.ADMIN:
            async with get_db_session() as db:
                query = select(Admin).where(
                    and_(
                        Admin.user_id == user_id,
                        Admin.bot_id == bot_id,
                        Admin.is_active.is_(True)
                    )
                )
                result = await db.execute(query)
                admin = result.scalar_one_or_none()
                
                if admin:
                    if admin.can_manage_admins:
                        permissions.add(Permission.MANAGE_ADMINS)
                    if admin.can_create_bot:
                        permissions.add(Permission.CREATE_BOT)
        
        return permissions


# 全局单例
permission_service = PermissionService()

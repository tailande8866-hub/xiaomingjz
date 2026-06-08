"""
租户上下文注入系统

职责：
1. 自动识别 bot_id、root_bot_id、owner_id
2. 注入 tenant_context 到每个请求
3. 提供统一的权限检查和功能开关
"""
import logging
from typing import Optional, Dict, Any
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models import BotCreation, Admin, get_db_session
from .account_status_service import account_status_service

logger = logging.getLogger(__name__)


class TenantContext:
    """
    租户上下文
    
    包含当前 Bot 的所有运行时信息
    """
    
    def __init__(
        self,
        bot_id: str,
        root_bot_id: str,
        owner_id: int,
        tree_depth: int,
        permissions: Dict[str, bool],
        feature_flags: Dict[str, bool],
        version_info: Dict[str, str],
        config_snapshot: Optional[Dict[str, Any]] = None,
        user_role: Optional[str] = None
    ):
        self.bot_id = bot_id
        self.root_bot_id = root_bot_id
        self.owner_id = owner_id
        self.tree_depth = tree_depth
        self.permissions = permissions
        self.feature_flags = feature_flags
        self.version_info = version_info
        self.config_snapshot = config_snapshot or {}
        self.user_role = user_role or 'normal_user'
    
    def has_permission(self, permission: str) -> bool:
        """检查是否有某个权限"""
        return self.permissions.get(permission, False)
    
    def is_feature_enabled(self, feature: str) -> bool:
        """检查某个功能是否启用"""
        return self.feature_flags.get(feature, False)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'bot_id': self.bot_id,
            'root_bot_id': self.root_bot_id,
            'owner_id': self.owner_id,
            'tree_depth': self.tree_depth,
            'permissions': self.permissions,
            'feature_flags': self.feature_flags,
            'version_info': self.version_info,
            'config_snapshot': self.config_snapshot
        }


class TenantContextManager:
    """
    租户上下文管理器
    
    负责创建和注入租户上下文
    """
    
    # 默认功能开关
    DEFAULT_FEATURE_FLAGS = {
        'enable_ai': False,
        'enable_auto_day_cut': True,
        'enable_global_operator': True,
        'enable_broadcast': True,
        'enable_custom_keywords': True,
        'enable_group_management': True,
        'enable_menu': True,
        'enable_saas': True,
        'enable_billing': True,
        'enable_settings': True,
        'enable_energy': True,
        'enable_usdt_monitor': True,
    }
    
    async def get_tenant_context(self, bot_id: str, user_id: int) -> Optional[TenantContext]:
        """
        获取租户上下文
        
        Args:
            bot_id: Bot 实例 ID
            user_id: 用户 Telegram ID
            
        Returns:
            TenantContext 对象，如果 Bot 不存在则返回 None
        """
        async with get_db_session() as db:
            # 查询 Bot 创建记录
            query = select(BotCreation).where(BotCreation.instance_id == bot_id)
            result = await db.execute(query)
            bot_creation = result.scalar_one_or_none()
            
            if not bot_creation:
                # 🆕 B方案：运行时兜底 - 尝试自动修复
                logger.warning(f"🛠️ Bot {bot_id} not found, attempting auto-repair...")
                
                try:
                    from .system_bootstrap_service import system_bootstrap_service
                    bot_creation = await system_bootstrap_service.auto_repair_bot_creation(bot_id)
                    
                    if bot_creation:
                        logger.info(f"✅ Auto-repair successful for {bot_id}, retrying get_tenant_context...")
                        # 重新查询（现在应该存在了）
                        query = select(BotCreation).where(BotCreation.instance_id == bot_id)
                        result = await db.execute(query)
                        bot_creation = result.scalar_one_or_none()
                except Exception as e:
                    logger.error(f"❌ Auto-repair failed for {bot_id}: {e}")
                
                if not bot_creation:
                    logger.error(f"❌ Bot {bot_id} not found and auto-repair failed")
                    return None
            
            # 查询用户权限
            permissions = await self._get_user_permissions(db, bot_id, user_id)
            
            # ✅ 获取用户角色
            from ..utils.role_checker import get_user_role
            user_role = await get_user_role(user_id, bot_id=bot_id)
            logger.info(f"[TENANT] User {user_id} on Bot {bot_id} has role: {user_role}")
            
            # 解析配置快照
            import json
            config_snapshot = {}
            if bot_creation.config_snapshot:
                try:
                    config_snapshot = json.loads(bot_creation.config_snapshot)
                except Exception as e:
                    logger.error(f"Failed to parse config_snapshot: {e}")
            
            # 构建版本信息
            version_info = {
                'core_version': bot_creation.core_version or '1.0.0',
                'ui_version': bot_creation.ui_version or '1.0.0',
                'permission_version': bot_creation.permission_version or '1.0.0'
            }
            
            # 创建租户上下文
            tenant_context = TenantContext(
                bot_id=bot_id,
                root_bot_id=bot_creation.root_bot_id or bot_id,
                owner_id=bot_creation.super_admin_id,
                tree_depth=bot_creation.tree_depth or 0,
                permissions=permissions,
                feature_flags=self.DEFAULT_FEATURE_FLAGS.copy(),
                version_info=version_info,
                config_snapshot=config_snapshot,
                user_role=user_role
            )
            
            return tenant_context
    
    async def _get_user_permissions(self, db, bot_id: str, user_id: int) -> Dict[str, bool]:
        """
        获取用户权限
        
        Args:
            db: 数据库会话
            bot_id: Bot 实例 ID
            user_id: 用户 Telegram ID
            
        Returns:
            权限字典
        """
        # 默认权限（普通用户）
        permissions = {
            'can_create_bot': True,
            'can_manage_admins': False,
            'can_manage_group_members': False,
            'can_broadcast': False,
            'can_set_day_cut': False,
            'can_set_keywords': False,
            'can_renew': True,
            'can_settings': False,
        }

        account_status = await account_status_service.resolve(user_id, bot_id)
        if account_status.is_trial:
            permissions.update({
                'can_create_bot': False,
                'can_broadcast': False,
                'can_set_day_cut': False,
                'can_set_keywords': False,
                'can_settings': False,
            })
            return permissions

        from ..utils.role_checker import get_user_role, UserRole
        user_role = await get_user_role(user_id, bot_id=bot_id)
        if user_role in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER]:
            permissions.update({
                'can_create_bot': True,
                'can_manage_admins': True,
                'can_manage_group_members': True,
                'can_broadcast': True,
                'can_set_day_cut': True,
                'can_set_keywords': True,
                'can_renew': True,
                'can_settings': True,
            })
            return permissions
        
        # 查询管理员记录
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
            # 管理员权限
            permissions.update({
                'can_create_bot': admin.can_create_bot or False,
                'can_manage_admins': admin.can_manage_admins or False,
                'can_manage_group_members': admin.can_manage_group_members or False,
                'can_broadcast': admin.can_broadcast or False,
                'can_set_day_cut': admin.can_set_day_cut or False,
                'can_set_keywords': admin.can_set_keywords or False,
                'can_renew': True,  # 管理员可以续费
                'can_settings': True,  # 管理员可以设置
            })
        
        return permissions
    
    def inject_tenant_context(self, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
        """
        注入租户上下文到 context
        
        Args:
            context: Telegram Context
            tenant_context: 租户上下文对象
        """
        context.bot_data['tenant_context'] = tenant_context
        logger.debug(f"Injected tenant context for bot {tenant_context.bot_id}")
    
    def get_tenant_context_from_context(self, context: ContextTypes.DEFAULT_TYPE) -> Optional[TenantContext]:
        """
        从 context 中获取租户上下文
        
        Args:
            context: Telegram Context
            
        Returns:
            TenantContext 对象，如果不存在则返回 None
        """
        return context.bot_data.get('tenant_context')


# 全局实例
tenant_context_manager = TenantContextManager()

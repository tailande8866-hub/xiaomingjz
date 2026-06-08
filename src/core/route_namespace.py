"""
路由命名空间系统（Route Namespace System）

职责：
1. 为所有路由添加版本前缀（v1:, v2:）
2. 防止 callback 冲突和历史按钮失效
3. 支持路由迁移和向后兼容
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RouteNamespace:
    """
    路由命名空间管理器
    
    使用示例：
    # 旧格式
    'menu:personal_center'
    
    # 新格式（带版本）
    'v1:menu:personal_center'
    'v2:menu:personal_center'
    """
    
    # 当前版本号
    CURRENT_VERSION = "v1"
    
    # 支持的版本列表
    SUPPORTED_VERSIONS = ["v1"]
    
    @staticmethod
    def build_route(module: str, action: str, version: Optional[str] = None) -> str:
        """
        构建路由名称
        
        Args:
            module: 模块名称（例如：'menu', 'group', 'admin'）
            action: 动作名称（例如：'personal_center', 'manage', 'list'）
            version: 版本号（可选，默认使用 CURRENT_VERSION）
            
        Returns:
            完整的路由名称（例如：'v1:menu:personal_center'）
        """
        ver = version or RouteNamespace.CURRENT_VERSION
        return f"{ver}:{module}:{action}"
    
    @staticmethod
    def parse_route(route_name: str) -> dict:
        """
        解析路由名称
        
        Args:
            route_name: 路由名称（例如：'v1:menu:personal_center'）
            
        Returns:
            字典：{'version': 'v1', 'module': 'menu', 'action': 'personal_center'}
        """
        parts = route_name.split(':')
        
        if len(parts) == 3:
            # 新版本格式：v1:module:action
            return {
                'version': parts[0],
                'module': parts[1],
                'action': parts[2]
            }
        elif len(parts) == 2:
            # 旧版本格式：module:action（自动补全版本）
            logger.warning(f"Legacy route format detected: {route_name}, auto-upgrading to v1")
            return {
                'version': RouteNamespace.CURRENT_VERSION,
                'module': parts[0],
                'action': parts[1]
            }
        else:
            logger.error(f"Invalid route format: {route_name}")
            return {
                'version': RouteNamespace.CURRENT_VERSION,
                'module': 'unknown',
                'action': route_name
            }
    
    @staticmethod
    def is_version_supported(version: str) -> bool:
        """
        检查版本是否支持
        
        Args:
            version: 版本号
            
        Returns:
            是否支持
        """
        return version in RouteNamespace.SUPPORTED_VERSIONS
    
    @staticmethod
    def migrate_route(old_route: str, new_version: str) -> str:
        """
        迁移路由到新版本
        
        Args:
            old_route: 旧路由名称
            new_version: 新版本号
            
        Returns:
            新路由名称
        """
        parsed = RouteNamespace.parse_route(old_route)
        return RouteNamespace.build_route(parsed['module'], parsed['action'], new_version)
    
    @staticmethod
    def register_legacy_route(runtime_router, old_route: str, handler):
        """
        注册旧版本路由（用于向后兼容）
        
        Args:
            runtime_router: RuntimeRouter 实例
            old_route: 旧路由名称
            handler: 处理函数
        """
        parsed = RouteNamespace.parse_route(old_route)
        
        # 注册旧版本路由
        runtime_router.register_route(old_route, handler)
        logger.info(f"Registered legacy route: {old_route}")
        
        # 如果旧版本不是当前版本，也注册新版本路由
        if parsed['version'] != RouteNamespace.CURRENT_VERSION:
            new_route = RouteNamespace.migrate_route(old_route, RouteNamespace.CURRENT_VERSION)
            runtime_router.register_route(new_route, handler)
            logger.info(f"Also registered upgraded route: {new_route}")


# 预定义的路由常量（避免硬编码）
class Routes:
    """路由常量定义"""
    
    # === 菜单模块 ===
    MENU_PERSONAL_CENTER = RouteNamespace.build_route('menu', 'personal_center')
    MENU_USAGE_GUIDE = RouteNamespace.build_route('menu', 'usage_guide')
    MENU_CONTACT_SUPPORT = RouteNamespace.build_route('menu', 'contact_support')
    MENU_APPLY_TRIAL = RouteNamespace.build_route('menu', 'apply_trial')  # 🆕 申请试用
    
    # === SaaS 模块 ===
    SAAS_CREATE_BOT = RouteNamespace.build_route('saas', 'create_bot')
    SAAS_SELECT_PLAN = RouteNamespace.build_route('saas', 'select_plan')
    SAAS_CONFIRM_PAYMENT = RouteNamespace.build_route('saas', 'confirm_payment')
    
    # === 账单模块 ===
    BILLING_SELF_RENEW = RouteNamespace.build_route('billing', 'self_renew')
    BILLING_DEPOSIT = RouteNamespace.build_route('billing', 'deposit')
    BILLING_WITHDRAW = RouteNamespace.build_route('billing', 'withdraw')
    BILLING_SHOW_BILLS = RouteNamespace.build_route('billing', 'show_bills')
    
    # === 群组模块 ===
    GROUP_MANAGE = RouteNamespace.build_route('group', 'manage')
    GROUP_LIST = RouteNamespace.build_route('group', 'list')
    GROUP_DETAIL = RouteNamespace.build_route('group', 'detail')
    GROUP_CREATE = RouteNamespace.build_route('group', 'create')
    GROUP_DELETE = RouteNamespace.build_route('group', 'delete')
    
    # === 广播模块 ===
    BROADCAST_SEND = RouteNamespace.build_route('broadcast', 'send')
    BROADCAST_USERS = RouteNamespace.build_route('broadcast', 'users')  # 🆕 广播用户
    BROADCAST_GROUPS = RouteNamespace.build_route('broadcast', 'groups')
    BROADCAST_CREATE_GROUP = RouteNamespace.build_route('broadcast', 'create_group')
    
    # === 设置模块 ===
    SETTINGS_MAIN = RouteNamespace.build_route('settings', 'main')
    SETTINGS_BASIC = RouteNamespace.build_route('settings', 'basic')
    SETTINGS_DISPLAY = RouteNamespace.build_route('settings', 'display')
    SETTINGS_OPERATOR = RouteNamespace.build_route('settings', 'operator')
    # 🆕 新增全局设置路由
    SETTINGS_DAYCUT_GLOBAL = RouteNamespace.build_route('settings', 'daycut_global')
    SETTINGS_DISPLAY_COUNT_GLOBAL = RouteNamespace.build_route('settings', 'display_count_global')
    SETTINGS_SHOW_NAME_GLOBAL = RouteNamespace.build_route('settings', 'show_name_global')
    SETTINGS_WELCOME_GLOBAL = RouteNamespace.build_route('settings', 'welcome_global')
    SETTINGS_KEYWORD_GLOBAL = RouteNamespace.build_route('settings', 'keyword_global')
    SETTINGS_RENAME_NOTIFICATION = RouteNamespace.build_route('settings', 'rename_notification')
    
    # === 管理员模块 ===
    ADMIN_ADD = RouteNamespace.build_route('admin', 'add')
    ADMIN_REMOVE = RouteNamespace.build_route('admin', 'remove')
    ADMIN_LIST = RouteNamespace.build_route('admin', 'list')
    ADMIN_AUTHORIZE_GROUP = RouteNamespace.build_route('admin', 'authorize_group')  # 🆕 授权群组
    ADMIN_USER_INFO = RouteNamespace.build_route('admin', 'user_info')
    
    # === 操作人模块 ===
    OPERATOR_ADD = RouteNamespace.build_route('operator', 'add')
    OPERATOR_REMOVE = RouteNamespace.build_route('operator', 'remove')
    OPERATOR_LIST = RouteNamespace.build_route('operator', 'list')
    
    # === 关键词模块 ===
    KEYWORD_CONFIG = RouteNamespace.build_route('keyword', 'config')
    KEYWORD_CREATE = RouteNamespace.build_route('keyword', 'create')
    KEYWORD_DELETE = RouteNamespace.build_route('keyword', 'delete')
    
    # === 能量模块 ===
    ENERGY_TRX = RouteNamespace.build_route('energy', 'trx')
    
    # === USDT 监听模块 ===
    USDT_MONITOR = RouteNamespace.build_route('usdt', 'monitor')
    USDT_ADD = RouteNamespace.build_route('usdt', 'add')
    USDT_LIST = RouteNamespace.build_route('usdt', 'list')
    USDT_TOGGLE = RouteNamespace.build_route('usdt', 'toggle')
    USDT_DELETE = RouteNamespace.build_route('usdt', 'delete')
    
    # === 统计模块 ===
    STATS_RUNTIME = RouteNamespace.build_route('stats', 'runtime')  # 🆕 运行统计

    # === 超级管理员模块 ===
    SUPER_ADMIN_MESSAGE_CENTER = RouteNamespace.build_route('super_admin', 'message_center')  # 🆕 消息中心
    SUPER_ADMIN_PANEL = RouteNamespace.build_route('super_admin', 'panel')  # 🆕 超管后台

"""
统一运行时路由器（Runtime Router）

职责：
1. 所有 Bot 共享同一个 Router
2. 自动识别 bot_id、tenant_id、route、user_role
3. 注入 tenant_context 到每个请求
4. 根据 feature_flags 动态路由
5. 支持路由版本控制（Route Namespace System）
"""
import logging
from typing import Callable, Awaitable, Optional
from telegram import Update
from telegram.ext import ContextTypes, Application

from ..services.tenant_context import tenant_context_manager, TenantContext
from .route_namespace import RouteNamespace, Routes
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)


class RuntimeRouter:
    """
    统一运行时路由器
    
    所有 Bot 的请求都通过这个 Router 处理
    """
    
    def __init__(self):
        # 路由表：{route_name: handler_function}
        self.routes: dict[str, Callable[[Update, ContextTypes.DEFAULT_TYPE, TenantContext], Awaitable[None]]] = {}
        
        # 中间件列表
        self.middlewares: list[Callable[[Update, ContextTypes.DEFAULT_TYPE, TenantContext], Awaitable[bool]]] = []
    
    def register_route(self, route_name: str, handler: Callable[[Update, ContextTypes.DEFAULT_TYPE, TenantContext], Awaitable[None]]):
        """
        注册路由
        
        Args:
            route_name: 路由名称（例如：'menu:personal_center', 'group:manage'）
            handler: 处理函数，签名：async def handler(update, context, tenant_context)
        """
        self.routes[route_name] = handler
        logger.info(f"Registered route: {route_name}")
    
    def register_middleware(self, middleware: Callable[[Update, ContextTypes.DEFAULT_TYPE, TenantContext], Awaitable[bool]]):
        """
        注册中间件
        
        Args:
            middleware: 中间件函数，返回 True 继续处理，False 中断
        """
        self.middlewares.append(middleware)
        logger.info(f"Registered middleware")

    @staticmethod
    def _route_parts(route_name: str) -> tuple[str, str]:
        """Return (module, action) for legacy and versioned route names."""
        parts = route_name.split(':')
        if len(parts) >= 3 and parts[0].startswith('v'):
            return parts[1], parts[2]
        if len(parts) >= 2:
            return parts[0], parts[1]
        return route_name, ""
    
    async def handle_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理更新（统一入口）
        
        Args:
            update: Telegram Update
            context: Telegram Context
        """
        try:
            # Step 1: 获取 bot_id
            bot_id = get_current_bot_id(context)
            if not bot_id:
                logger.warning("No bot_id found in context")
                return
            
            # Step 2: 获取 user_id
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                logger.warning("No user_id found in update")
                return
            
            # 🆕 Step 2.3: Callback 限流检查
            if update.callback_query:
                from ..utils.rate_limiter import rate_limiter
                if await rate_limiter.check_limit(user_id, action="callback"):
                    remaining = await rate_limiter.get_remaining(user_id, action="callback")
                    try:
                        await update.callback_query.answer(
                            f"⚠️ 操作过于频繁，请稍后再试\n剩余次数：{remaining} 次/分钟",
                            show_alert=True
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send rate limit message: {e}")
                    return

            # 🆕 Step 2.4: 内联键盘过期检查（5分钟）
            if update.callback_query and update.callback_query.message:
                from datetime import datetime, timedelta, timezone
                message_date = update.callback_query.message.date
                # 确保 message_date 是带时区的
                if message_date.tzinfo is None:
                    message_date = message_date.replace(tzinfo=timezone.utc)
                expiry_time = message_date + timedelta(minutes=5)
                current_time = datetime.now(timezone.utc)

                if current_time > expiry_time:
                    try:
                        await update.callback_query.answer(
                            "⏱️ 此菜单已过期（超过5分钟），请重新打开",
                            show_alert=True
                        )
                        # 尝试删除过期消息
                        try:
                            await update.callback_query.message.delete()
                        except:
                            pass
                    except Exception as e:
                        logger.warning(f"Failed to send expiry message: {e}")
                    return

            # 🆕 Step 2.5: 设置日志上下文
            from ..utils.log_context import log_context
            with log_context(bot_id=bot_id, user_id=user_id):
                # Step 3: 获取租户上下文
                tenant_context = await tenant_context_manager.get_tenant_context(bot_id, user_id)
                if not tenant_context:
                    logger.warning(f"No tenant context for bot {bot_id}, user {user_id}")
                    return
                
                # Step 4: 注入租户上下文
                tenant_context_manager.inject_tenant_context(context, tenant_context)
                
                # Step 5: 执行中间件
                for middleware in self.middlewares:
                    should_continue = await middleware(update, context, tenant_context)
                    if not should_continue:
                        logger.debug(f"Middleware interrupted request for user {user_id}")
                        return
                
                # Step 6: 确定路由名称（从 callback_data 或 message text）
                route_name = self._determine_route(update, context)
                if not route_name:
                    # 🆕 添加调试日志
                    if update.message and update.message.text:
                        logger.info(f"[DEBUG] No route for text: '{update.message.text}' from user {user_id}")
                    else:
                        logger.debug(f"No route determined for update from user {user_id}")
                    return
                else:
                    logger.info(f"[DEBUG] Route determined: '{route_name}' for user {user_id}")
            
            # Step 7: 检查功能开关
            if not self._check_feature_flag(route_name, tenant_context):
                logger.warning(f"Feature disabled for route {route_name}, bot {bot_id}")
                await self._send_feature_disabled_message(update, context, route_name)
                return
            
            # Step 8: 检查权限
            if not self._check_permission(route_name, tenant_context):
                logger.warning(f"Permission denied for route {route_name}, user {user_id}")
                await self._send_permission_denied_message(update, context, route_name)
                return
            
            # Step 9: 执行路由处理
            handler = self.routes.get(route_name)
            if handler:
                await handler(update, context, tenant_context)
            else:
                logger.warning(f"No handler found for route: {route_name}")
        
        except Exception as e:
            logger.error(f"Error in RuntimeRouter.handle_update: {e}", exc_info=True)
            await self._handle_error(update, context, e)
    
    def _determine_route(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        """
        确定路由名称（支持 Route Namespace System）
        
        Args:
            update: Telegram Update
            context: Telegram Context
            
        Returns:
            路由名称，如果无法确定则返回 None
        """
        # 优先从 callback_data 中获取
        if update.callback_query:
            callback_data = (
                context.user_data.get("_settings_unwrapped_callback_data")
                or update.callback_query.data
            )
        else:
            callback_data = None

        if callback_data:
            
            # ✅ 解析 callback_data 格式：v1:route_name:param1:param2
            parts = callback_data.split(':')
            
            # 检查是否是带版本的路由
            if len(parts) >= 2 and parts[0].startswith('v'):
                # 新版本格式：v1:module:action:params...
                version = parts[0]
                module = parts[1] if len(parts) > 1 else 'unknown'
                action = parts[2] if len(parts) > 2 else 'unknown'
                params = parts[3:] if len(parts) > 3 else []
                
                route_name = f"{version}:{module}:{action}"
                
                # 将参数存储到 context.user_data
                if params:
                    context.user_data['callback_params'] = params
                else:
                    context.user_data.pop('callback_params', None)
                
                return route_name
            else:
                # 旧版本格式：route_name:params...（自动升级）
                if len(parts) >= 2:
                    route_name = f"{parts[0]}:{parts[1]}"
                    params = parts[2:]
                else:
                    route_name = parts[0]
                    params = []
                
                # 自动升级到 v1
                parsed = RouteNamespace.parse_route(route_name)
                upgraded_route = f"{RouteNamespace.CURRENT_VERSION}:{parsed['module']}:{parsed['action']}"
                
                logger.info(f"Auto-upgrading legacy route '{route_name}' to '{upgraded_route}'")
                
                # 将参数存储到 context.user_data
                if params:
                    context.user_data['callback_params'] = params
                else:
                    context.user_data.pop('callback_params', None)
                
                return upgraded_route
        
        # 从 message text 中获取
        if update.message and update.message.text:
            text = update.message.text.strip()
            
            # 映射文本到路由名称（使用 Routes 常量）
            # 根据脑图权限设计：
            # - 超级管理员/Bot创建者: 使用说明、广播用户、运行统计、分组管理、功能设置、群发广播、个人中心、能量TRX、USDT监听
            # - 管理员: 使用说明、创建续费、运行统计、分组管理、功能设置、群发广播、个人中心、能量TRX、USDT监听
            # - 普通用户: 使用说明、创建续费、功能设置、联系客服、能量TRX、USDT监听
            route_mapping = {
                '📖 使用说明': Routes.MENU_USAGE_GUIDE,
                '使用说明': Routes.MENU_USAGE_GUIDE,
                '📢 广播用户': Routes.BROADCAST_USERS,
                '广播用户': Routes.BROADCAST_USERS,
                '💰 创建续费': Routes.SAAS_CREATE_BOT,
                '创建续费': Routes.SAAS_CREATE_BOT,
                '📊 运行统计': Routes.STATS_RUNTIME,
                '运行统计': Routes.STATS_RUNTIME,
                '📁 分组管理': Routes.GROUP_MANAGE,
                '分组管理': Routes.GROUP_MANAGE,
                '⚙️ 功能设置': Routes.SETTINGS_MAIN,
                '功能设置': Routes.SETTINGS_MAIN,
                '👤 个人中心': Routes.MENU_PERSONAL_CENTER,
                '个人中心': Routes.MENU_PERSONAL_CENTER,
                '⚡ 能量TRX': Routes.ENERGY_TRX,
                '能量TRX': Routes.ENERGY_TRX,
                '💰 USDT监听': Routes.USDT_MONITOR,
                'USDT监听': Routes.USDT_MONITOR,
                '💬 联系客服': Routes.MENU_CONTACT_SUPPORT,
                '联系客服': Routes.MENU_CONTACT_SUPPORT,
                # 🆕 申请试用
                '📝 申请试用': Routes.MENU_APPLY_TRIAL,
                '申请试用': Routes.MENU_APPLY_TRIAL,
                # 🆕 功能设置子菜单
                '✂️ 全局日切设置': Routes.SETTINGS_DAYCUT_GLOBAL,
                '全局日切设置': Routes.SETTINGS_DAYCUT_GLOBAL,
                '📊 全局记账条数设置': Routes.SETTINGS_DISPLAY_COUNT_GLOBAL,
                '全局记账条数设置': Routes.SETTINGS_DISPLAY_COUNT_GLOBAL,
                '👤 全局记账成员名字显示': Routes.SETTINGS_SHOW_NAME_GLOBAL,
                '全局记账成员名字显示': Routes.SETTINGS_SHOW_NAME_GLOBAL,
                '👋 全局入群欢迎语': Routes.SETTINGS_WELCOME_GLOBAL,
                '全局入群欢迎语': Routes.SETTINGS_WELCOME_GLOBAL,
                '💬 全局关键词设置': Routes.SETTINGS_KEYWORD_GLOBAL,
                '全局关键词设置': Routes.SETTINGS_KEYWORD_GLOBAL,
                '🍀 用户更名检测': Routes.SETTINGS_RENAME_NOTIFICATION,
                '用户更名检测': Routes.SETTINGS_RENAME_NOTIFICATION,
                '👥 添加管理员': Routes.ADMIN_ADD,
                '添加管理员': Routes.ADMIN_ADD,
                '🔐 授权群组': Routes.ADMIN_AUTHORIZE_GROUP,
                '授权群组': Routes.ADMIN_AUTHORIZE_GROUP,
                # 🆕 超级管理员功能
                '💬 消息中心': Routes.SUPER_ADMIN_MESSAGE_CENTER,
                '消息中心': Routes.SUPER_ADMIN_MESSAGE_CENTER,
                '🛠 超管后台': Routes.SUPER_ADMIN_PANEL,
                '超管后台': Routes.SUPER_ADMIN_PANEL,
            }
            
            return route_mapping.get(text)
        
        return None
    
    def _check_feature_flag(self, route_name: str, tenant_context: TenantContext) -> bool:
        """
        检查功能开关
        
        Args:
            route_name: 路由名称
            tenant_context: 租户上下文
            
        Returns:
            是否启用
        """
        # 提取功能名称（兼容 'menu:main' 与 'v1:menu:main'）
        feature_name, _ = self._route_parts(route_name)
        
        # 映射功能名称到 feature flag
        feature_flag_mapping = {
            'menu': 'enable_menu',
            'saas': 'enable_saas',
            'billing': 'enable_billing',
            'broadcast': 'enable_broadcast',
            'group': 'enable_group_management',
            'settings': 'enable_settings',
            'energy': 'enable_energy',
            'usdt': 'enable_usdt_monitor',
        }
        
        feature_flag = feature_flag_mapping.get(feature_name)
        if not feature_flag:
            return True  # 没有对应的 feature flag，默认启用
        
        return tenant_context.is_feature_enabled(feature_flag)
    
    def _check_permission(self, route_name: str, tenant_context: TenantContext) -> bool:
        """
        检查权限
        
        Args:
            route_name: 路由名称
            tenant_context: 租户上下文
            
        Returns:
            是否有权限
        """
        # 映射路由名称到权限
        permission_mapping = {
            'billing:self_renew': 'can_renew',
            'broadcast:users': 'can_broadcast',
            'broadcast:send': 'can_broadcast',
            'group:manage': 'can_manage_group_members',
            'settings:main': 'can_settings',
            'settings:daycut_global': 'can_settings',
            'settings:display_count_global': 'can_settings',
            'settings:show_name_global': 'can_settings',
            'settings:welcome_global': 'can_settings',
            'settings:keyword_global': 'can_settings',
            'admin:add': 'can_manage_admins',
            'admin:authorize_group': 'can_manage_admins',
        }
        
        module, action = self._route_parts(route_name)
        normalized_route = f"{module}:{action}" if action else module
        required_permission = permission_mapping.get(normalized_route)
        if not required_permission:
            return True  # 没有对应的权限要求，默认允许
        
        return tenant_context.has_permission(required_permission)
    
    async def _send_feature_disabled_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, route_name: str):
        """发送功能禁用消息"""
        message = f"❌ 该功能暂未对您开放\n\n如需使用，请联系客服升级套餐。"
        
        if update.callback_query:
            await update.callback_query.answer(message, show_alert=True)
        elif update.message:
            await update.message.reply_text(message)
    
    async def _send_permission_denied_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, route_name: str):
        """发送权限拒绝消息"""
        message = f"❌ 您没有权限执行此操作\n\n如需提升权限，请联系管理员。"
        
        if update.callback_query:
            await update.callback_query.answer(message, show_alert=True)
        elif update.message:
            await update.message.reply_text(message)
    
    async def _handle_error(self, update: Update, context: ContextTypes.DEFAULT_TYPE, error: Exception):
        """处理错误"""
        error_message = f"❌ 处理您的请求时出现错误\n\n请稍后重试，或联系客服。"
        
        if update.callback_query:
            await update.callback_query.answer(error_message, show_alert=True)
        elif update.message:
            await update.message.reply_text(error_message)


# 全局实例
runtime_router = RuntimeRouter()

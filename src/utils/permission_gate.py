"""
权限门禁系统（Permission Gate）

🔥 运行时强约束：防止任何模块绕过 role_checker
🔥 统一装饰器：所有 handler 必须通过此门禁
🔥 强制日志：每次权限检查都记录，便于审计

使用方式：
    @require_super_admin()
    async def my_handler(update, context):
        ...
    
    @require_admin()
    async def my_handler(update, context):
        ...
    
    @require_role([UserRole.SUPER_ADMIN, UserRole.BOT_OWNER])
    async def my_handler(update, context):
        ...
"""

import functools
import logging
from typing import List, Optional, Callable, Union

from telegram import Update
from telegram.ext import ContextTypes

from .role_checker import get_user_role, UserRole, is_super_admin, is_admin
from .bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """权限不足异常"""
    pass


def _get_user_id_from_update(update: Update) -> Optional[int]:
    """从 update 中提取用户ID"""
    if update.effective_user:
        return update.effective_user.id
    if update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user.id
    if update.message and update.message.from_user:
        return update.message.from_user.id
    return None


def _log_permission_check(
    user_id: int,
    required_role: str,
    actual_role: str,
    granted: bool,
    handler_name: str
):
    """记录权限检查日志"""
    status = "✅ GRANTED" if granted else "❌ DENIED"
    logger.info(
        f"[PermissionGate] {status} | "
        f"Handler={handler_name} | "
        f"User={user_id} | "
        f"Required={required_role} | "
        f"Actual={actual_role}"
    )


def require_super_admin(
    error_message: str = "❌ 该功能仅限超级管理员使用",
    silent: bool = False
):
    """
    装饰器：要求超级管理员权限
    
    Args:
        error_message: 权限不足时返回的错误消息
        silent: 是否静默拒绝（不发送消息）
    """
    def decorator(handler_func: Callable):
        @functools.wraps(handler_func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = _get_user_id_from_update(update)
            handler_name = handler_func.__name__
            
            if not user_id:
                logger.warning(f"[PermissionGate] ❌ 无法获取用户ID: {handler_name}")
                if not silent and update.effective_message:
                    await update.effective_message.reply_text("❌ 无法识别用户身份")
                return
            
            bot_id = get_current_bot_id(context)
            
            # 🔥 强制通过 role_checker 检查（三重兜底）
            actual_role = await get_user_role(user_id, bot_id=bot_id)
            is_granted = actual_role == UserRole.SUPER_ADMIN
            
            _log_permission_check(
                user_id=user_id,
                required_role="SUPER_ADMIN",
                actual_role=actual_role,
                granted=is_granted,
                handler_name=handler_name
            )
            
            if not is_granted:
                if not silent and update.effective_message:
                    await update.effective_message.reply_text(error_message)
                raise PermissionDeniedError(
                    f"User {user_id} is not SUPER_ADMIN (actual: {actual_role})"
                )
            
            return await handler_func(update, context, *args, **kwargs)
        
        return wrapper
    return decorator


def require_bot_owner(
    error_message: str = "❌ 该功能仅限BOT拥有者使用",
    silent: bool = False
):
    """装饰器：要求BOT拥有者权限（超管自动通过）"""
    def decorator(handler_func: Callable):
        @functools.wraps(handler_func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = _get_user_id_from_update(update)
            handler_name = handler_func.__name__
            
            if not user_id:
                logger.warning(f"[PermissionGate] ❌ 无法获取用户ID: {handler_name}")
                if not silent and update.effective_message:
                    await update.effective_message.reply_text("❌ 无法识别用户身份")
                return
            
            bot_id = get_current_bot_id(context)
            actual_role = await get_user_role(user_id, bot_id=bot_id)
            
            # 超管或BOT拥有者都通过
            is_granted = actual_role in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER]
            
            _log_permission_check(
                user_id=user_id,
                required_role="SUPER_ADMIN or BOT_OWNER",
                actual_role=actual_role,
                granted=is_granted,
                handler_name=handler_name
            )
            
            if not is_granted:
                if not silent and update.effective_message:
                    await update.effective_message.reply_text(error_message)
                raise PermissionDeniedError(
                    f"User {user_id} is not BOT_OWNER (actual: {actual_role})"
                )
            
            return await handler_func(update, context, *args, **kwargs)
        
        return wrapper
    return decorator


def require_admin(
    error_message: str = "❌ 该功能仅限管理员使用",
    silent: bool = False
):
    """装饰器：要求管理员权限（超管/BOT拥有者/管理员都通过）"""
    def decorator(handler_func: Callable):
        @functools.wraps(handler_func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = _get_user_id_from_update(update)
            handler_name = handler_func.__name__
            
            if not user_id:
                logger.warning(f"[PermissionGate] ❌ 无法获取用户ID: {handler_name}")
                if not silent and update.effective_message:
                    await update.effective_message.reply_text("❌ 无法识别用户身份")
                return
            
            bot_id = get_current_bot_id(context)
            actual_role = await get_user_role(user_id, bot_id=bot_id)
            
            # 超管、BOT拥有者、管理员都通过
            admin_roles = [
                UserRole.SUPER_ADMIN,
                UserRole.BOT_OWNER,
                UserRole.ADMIN
            ]
            is_granted = actual_role in admin_roles
            
            _log_permission_check(
                user_id=user_id,
                required_role="ADMIN+",
                actual_role=actual_role,
                granted=is_granted,
                handler_name=handler_name
            )
            
            if not is_granted:
                if not silent and update.effective_message:
                    await update.effective_message.reply_text(error_message)
                raise PermissionDeniedError(
                    f"User {user_id} is not ADMIN (actual: {actual_role})"
                )
            
            return await handler_func(update, context, *args, **kwargs)
        
        return wrapper
    return decorator


def require_role(
    allowed_roles: List[str],
    error_message: str = "❌ 权限不足",
    silent: bool = False
):
    """
    装饰器：要求指定角色之一
    
    Args:
        allowed_roles: 允许的角色列表，如 [UserRole.SUPER_ADMIN, UserRole.ADMIN]
    """
    def decorator(handler_func: Callable):
        @functools.wraps(handler_func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = _get_user_id_from_update(update)
            handler_name = handler_func.__name__
            
            if not user_id:
                logger.warning(f"[PermissionGate] ❌ 无法获取用户ID: {handler_name}")
                if not silent and update.effective_message:
                    await update.effective_message.reply_text("❌ 无法识别用户身份")
                return
            
            bot_id = get_current_bot_id(context)
            actual_role = await get_user_role(user_id, bot_id=bot_id)
            
            is_granted = actual_role in allowed_roles
            
            _log_permission_check(
                user_id=user_id,
                required_role=f"one of {allowed_roles}",
                actual_role=actual_role,
                granted=is_granted,
                handler_name=handler_name
            )
            
            if not is_granted:
                if not silent and update.effective_message:
                    await update.effective_message.reply_text(error_message)
                raise PermissionDeniedError(
                    f"User {user_id} role {actual_role} not in {allowed_roles}"
                )
            
            return await handler_func(update, context, *args, **kwargs)
        
        return wrapper
    return decorator


# 🔥 兼容性包装：允许在旧代码中逐步迁移
async def check_permission(
    user_id: int,
    required_role: str,
    bot_id: str = None,
    context: ContextTypes.DEFAULT_TYPE = None
) -> bool:
    """
    程序化权限检查（非装饰器方式）
    
    用于无法在装饰器中处理的场景
    """
    if context and not bot_id:
        bot_id = get_current_bot_id(context)
    
    actual_role = await get_user_role(user_id, bot_id=bot_id)
    
    role_hierarchy = {
        UserRole.SUPER_ADMIN: 4,
        UserRole.BOT_OWNER: 3,
        UserRole.ADMIN: 2,
        UserRole.GLOBAL_OPERATOR: 1,
        UserRole.GROUP_OPERATOR: 1,
        UserRole.NORMAL_USER: 0
    }
    
    required_level = role_hierarchy.get(required_role, 0)
    actual_level = role_hierarchy.get(actual_role, 0)
    
    is_granted = actual_level >= required_level
    
    _log_permission_check(
        user_id=user_id,
        required_role=required_role,
        actual_role=actual_role,
        granted=is_granted,
        handler_name="check_permission"
    )
    
    return is_granted

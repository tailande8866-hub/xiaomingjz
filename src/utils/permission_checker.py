"""
权限检查工具
用于验证用户是否有权限执行特定操作
"""
import logging
from typing import Optional
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from .role_checker import get_user_role, UserRole
from ..models.enums import GroupStatus

logger = logging.getLogger(__name__)


class PermissionChecker:
    """权限检查器"""
    
    # 权限常量
    CAN_BROADCAST = "can_broadcast"  # 广播所有用户
    CAN_GROUP_BROADCAST = "can_group_broadcast"  # 分组广播
    CAN_KEYWORD_REPLY = "can_keyword_reply"  # 关键词回复
    CAN_SETTINGS = "can_settings"  # 功能设置
    CAN_MANAGE_GROUPS = "can_manage_group_members"  # 分组管理
    CAN_BILLING = "can_billing"  # 记账功能
    CAN_QUERY = "can_query"  # 查询功能
    CAN_CREATE_BOT = "can_create_bot"  # 创建机器人
    CAN_RENEW = "can_renew"  # 续费
    
    # 角色权限映射（优化版）
    ROLE_PERMISSIONS = {
        # L1 - 超级管理员：拥有所有权限，包括手动开通/续费/全平台广播
        UserRole.SUPER_ADMIN: [
            CAN_BROADCAST, CAN_GROUP_BROADCAST, CAN_KEYWORD_REPLY,
            CAN_SETTINGS, CAN_MANAGE_GROUPS, CAN_BILLING, CAN_QUERY, CAN_CREATE_BOT, CAN_RENEW
        ],
        # L2 - Bot拥有者：在自己的Bot中拥有全部权限，可以裂变创建下级Bot
        UserRole.BOT_OWNER: [
            CAN_BROADCAST, CAN_GROUP_BROADCAST, CAN_KEYWORD_REPLY,
            CAN_SETTINGS, CAN_MANAGE_GROUPS, CAN_BILLING, CAN_QUERY, CAN_CREATE_BOT, CAN_RENEW
        ],
        # L3 - 管理员：管理Bot内群组和业务功能，可以付费创建自己的Bot（成为BOT_OWNER）
        UserRole.ADMIN: [
            CAN_BROADCAST, CAN_GROUP_BROADCAST, CAN_KEYWORD_REPLY,
            CAN_SETTINGS, CAN_MANAGE_GROUPS, CAN_BILLING, CAN_QUERY, CAN_CREATE_BOT, CAN_RENEW
        ],
        # L4 - 全局操作人：所有群组的业务操作
        UserRole.GLOBAL_OPERATOR: [
            CAN_BILLING, CAN_QUERY, CAN_CREATE_BOT
        ],
        # L5 - 群操作人：所属群组的业务操作
        UserRole.GROUP_OPERATOR: [
            CAN_BILLING, CAN_QUERY, CAN_CREATE_BOT
        ],
        # L6 - 普通用户：仅查询功能
        UserRole.NORMAL_USER: [
            CAN_QUERY, CAN_CREATE_BOT
        ]
    }
    
    @classmethod
    def has_permission(cls, user_role: str, permission: str) -> bool:
        """
        检查用户角色是否有指定权限
        
        Args:
            user_role: 用户角色
            permission: 权限名称
        
        Returns:
            是否有权限
        """
        permissions = cls.ROLE_PERMISSIONS.get(user_role, [])
        return permission in permissions
    
    @classmethod
    def get_user_permissions(cls, user_role: str) -> list:
        """
        获取用户角色的所有权限
        
        Args:
            user_role: 用户角色
        
        Returns:
            权限列表
        """
        return cls.ROLE_PERMISSIONS.get(user_role, [])
    
    @classmethod
    async def check_permission_and_alert(cls, update: Update, required_permission: str, context=None) -> bool:
        """
        检查用户权限，如果没有权限则发送弹窗提示（支持租户隔离）
        
        Args:
            update: Telegram更新对象
            required_permission: 需要的权限
            context: Bot上下文（可选，用于获取bot_id进行租户隔离）
        
        Returns:
            是否有权限
        """
        user_id = update.effective_user.id
        
        # ✅ 如果提供了 context，获取 bot_id 进行租户隔离检查
        bot_id = None
        if context:
            from .bot_id_middleware import get_current_bot_id
            bot_id = get_current_bot_id(context)
        
        user_role = await get_user_role(user_id, bot_id=bot_id)
        
        # 检查是否为管理员，并验证具体权限
        from .internal_member_checker import check_admin_permission
        is_admin_user = await check_admin_permission(user_id, required_permission, bot_id)
        
        if is_admin_user:
            logger.debug(f"Admin {user_id} has permission: {required_permission}")
            return True
        
        if cls.has_permission(user_role, required_permission):
            return True
        
        # 没有权限，发送弹窗提示
        from .settings_guard import LOCKED_FEATURE_MESSAGE
        no_permission_msg = LOCKED_FEATURE_MESSAGE
        
        role_names = {
            UserRole.SUPER_ADMIN: "超级管理员（L1）",
            UserRole.BOT_OWNER: "Bot拥有者（L2）",
            UserRole.ADMIN: "管理员（L3）",
            UserRole.GLOBAL_OPERATOR: "全局操作人（L4）",
            UserRole.GROUP_OPERATOR: "群操作人（L5）",
            UserRole.NORMAL_USER: "普通用户（L6）"
        }
        
        permission_names = {
            cls.CAN_BROADCAST: "广播所有用户",
            cls.CAN_GROUP_BROADCAST: "分组广播",
            cls.CAN_KEYWORD_REPLY: "关键词回复",
            cls.CAN_SETTINGS: "功能设置",
            cls.CAN_MANAGE_GROUPS: "分组管理",
            cls.CAN_BILLING: "记账功能",
            cls.CAN_QUERY: "查询功能",
            cls.CAN_CREATE_BOT: "创建机器人",
            cls.CAN_RENEW: "续费功能"
        }
        
        message = no_permission_msg
        
        # 使用弹窗方式发送（带确定按钮）
        alert_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 确定", callback_data="close_alert")]
        ])
        
        if update.callback_query:
            await update.callback_query.answer(message, show_alert=True)
        elif update.message:
            await update.message.reply_text(message, parse_mode='HTML', reply_markup=alert_keyboard)
        
        logger.warning(f"User {user_id} ({user_role}) denied permission: {required_permission}")
        return False
    
    @classmethod
    async def check_group_authorization(cls, update: Update, context=None) -> bool:
        """
        检查群组是否已授权（新架构）
        
        Args:
            update: Telegram更新对象
            context: Bot上下文（用于获取bot_id和chat_id）
        
        Returns:
            群组是否已授权
        """
        # 仅对群组消息进行检查
        if not update.effective_chat or update.effective_chat.type == 'private':
            return True
        
        chat_id = update.effective_chat.id
        
        # 获取 bot_id
        if not context:
            logger.warning("Context is required for group authorization check")
            return True
        
        from .bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)

        try:
            if update.effective_user:
                user_role = await get_user_role(update.effective_user.id, chat_id, bot_id)
                if user_role == UserRole.SUPER_ADMIN:
                    logger.info(
                        "Group %s authorization bypassed for super admin %s",
                        chat_id,
                        update.effective_user.id,
                    )
                    return True
        except Exception:
            logger.error(
                "Failed to resolve super admin bypass for group authorization",
                exc_info=True,
            )
        
        # 查询群组状态
        from ..models import Group, get_db_session
        from sqlalchemy import select, and_
        
        async with get_db_session() as db:
            query = select(Group).where(
                and_(
                    Group.group_id == chat_id,
                    Group.bot_id == bot_id
                )
            )
            result = await db.execute(query)
            group = result.scalar_one_or_none()
            
            # 如果群组记录不存在，允许通过（可能是旧群组或刚创建）
            if not group:
                logger.debug(f"Group {chat_id} not found in database, allowing access")
                return True
            
            # 检查群组状态
            status = group.status
            
            # 未授权或待处理状态，拒绝访问
            if status in [GroupStatus.UNAUTHORIZED.value, GroupStatus.PENDING.value]:
                logger.warning(f"Group {chat_id} is {status}, blocking access")
                            
                # 🆕 只发送一次提示（针对 UNAUTHORIZED 状态）
                if status == GroupStatus.UNAUTHORIZED.value and not group.unauthorized_notice_sent:
                    # 获取超级管理员用户名（动态显示）
                    super_admin_username = await cls._get_super_admin_username_static(bot_id)
                    contact_info = f"@{super_admin_username}" if super_admin_username else "Bot 超管"
                                
                    # 根据状态选择不同的提示文案
                    notice = (
                        "❌ <b>此群组已被取消授权</b>\n\n"
                        "📋 当前状态：\n"
                        "• Bot 功能已被禁用\n"
                        "• 无法使用任何命令\n\n"
                        f"💡 请联系 {contact_info} 重新授权\n"
                        "⚠️ 只有授权后，Bot 才能正常使用"
                    )
                    
                    # 发送提示消息
                    if update.callback_query:
                        await update.callback_query.answer(notice, show_alert=True)
                    elif update.message:
                        await update.message.reply_text(notice, parse_mode='HTML')
                    
                    # 标记为已发送
                    group.unauthorized_notice_sent = True
                    await db.commit()
                    logger.info(f"    已发送取消授权提示到群组 {chat_id}（仅一次）")
                elif status == GroupStatus.UNAUTHORIZED.value:
                    # 已经发送过提示，静默拒绝（只记录日志）
                    logger.debug(f"    群组 {chat_id} 已发送过取消授权提示，静默拒绝")
                else:  # PENDING 状态，每次都提示
                    # 获取超级管理员用户名（动态显示）
                    super_admin_username = await cls._get_super_admin_username_static(bot_id)
                    contact_info = f"@{super_admin_username}" if super_admin_username else "Bot 超管"
                    
                    notice = (
                        "⏳ <b>当前群等待授权</b>\n\n"
                        "此 Bot 需要由超级管理员或管理员授权后才能使用。\n\n"
                        f"📞 <b>请联系 {contact_info} 进行授权</b>\n\n"
                        "💡 提示：只有 Bot 的超管和管理员拉我进群才会自动授权哦~"
                    )
                    
                    if update.callback_query:
                        await update.callback_query.answer(notice, show_alert=True)
                    elif update.message:
                        await update.message.reply_text(notice, parse_mode='HTML')
                
                return False
            
            # 其他状态（ACTIVE等）允许访问
            return True
    
    @classmethod
    async def _get_super_admin_username_static(cls, bot_id: str) -> Optional[str]:
        """
        获取创建此 Bot 的超级管理员用户名
        
        Args:
            bot_id: Bot 实例 ID
            
        Returns:
            超级管理员用户名（不含@），如果找不到则返回 None
        """
        try:
            from ..models import BotCreation, Admin, get_db_session
            from sqlalchemy import select, and_
            
            async with get_db_session() as db:
                # 查询 BotCreation 记录
                query = select(BotCreation).where(BotCreation.instance_id == bot_id)
                result = await db.execute(query)
                bot_creation = result.scalar_one_or_none()
                
                if not bot_creation:
                    logger.warning(f"Bot creation record not found for bot_id: {bot_id}")
                    return None
                
                super_admin_id = bot_creation.super_admin_id
                logger.debug(f"Found super_admin_id: {super_admin_id} for bot: {bot_id}")
                
                # 查询 Admin 记录获取用户名
                query = select(Admin).where(
                    and_(
                        Admin.user_id == super_admin_id,
                        Admin.bot_id == bot_id,
                        Admin.is_active.is_(True)
                    )
                )
                result = await db.execute(query)
                admin = result.scalar_one_or_none()
                
                if admin and admin.username:
                    logger.debug(f"Found super admin username: @{admin.username}")
                    return admin.username
                
                logger.warning(f"Admin username not found in database for user_id: {super_admin_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting super admin username: {e}", exc_info=True)
            return None


def require_authorized_group(func):
    """
    装饰器：要求群组已授权才能执行
    
    用法：
        @require_authorized_group
        async def some_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            ...
    """
    @wraps(func)
    async def wrapper(update: Update, context=None, *args, **kwargs):
        # 使用 PermissionChecker 检查群组授权
        is_authorized = await PermissionChecker.check_group_authorization(update, context)
        if not is_authorized:
            logger.debug(f"🚫 Blocked {func.__name__} due to unauthorized group")
            return None  # 直接返回，不执行原函数
        
        # 群组已授权，执行原函数
        return await func(update, context, *args, **kwargs)
    
    return wrapper


async def is_admin_or_operator(user_id: int, chat_id: int, db, context) -> bool:
    """
    检查用户是否是群组管理员或操作人
    
    Args:
        user_id: 用户ID
        chat_id: 群组ID
        db: 数据库会话
        context: Telegram Context
    
    Returns:
        是否为管理员或操作人
    """
    from .role_checker import get_user_role, UserRole
    from ..utils.bot_id_middleware import get_current_bot_id
    
    bot_id = get_current_bot_id(context)
    
    # 获取用户角色
    role = await get_user_role(user_id, chat_id, bot_id)
    
    # 超管、Bot拥有者、管理员、操作人都可以配置欢迎语
    if role in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN, UserRole.OPERATOR]:
        return True
    
    return False

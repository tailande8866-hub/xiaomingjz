"""
授权服务 - SaaS Bot Operating System 核心（插件式接入）

设计原则：
1. ✅ 仅新增功能，不修改现有 Handler
2. ✅ 默认关闭，需要显式开启才生效
3. ✅ 向后兼容，老群组完全不受影响
4. ✅ 独立 Service，可单独启用/禁用

职责：
1. 检查用户是否有权限拉 bot 进群
2. 自动授权群组（管理员/超管拉群）- 可选功能
3. 标记未授权群组（普通用户拉群）- 可选功能
4. 发送首次授权欢迎语 - 可选功能
5. 超管手动授权群组 - 可选功能

使用方式：
    # 在 chat_member_handler 中安全调用
    if AUTHORIZATION_ENABLED:  # Feature Flag
        await authorization_service.check_and_authorize_group(...)
"""
import logging
from typing import Optional, Tuple
from telegram import User, Chat
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from datetime import datetime

from ..core.event_bus import Event, EventType
from ..models import Group, Admin, AdminGlobalConfig, get_db_session
from ..models.enums import GroupStatus
from ..utils.role_checker import get_user_role, UserRole
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)

# ============================================================================
# Feature Flag - 功能开关（默认关闭，确保安全）
# ============================================================================
AUTHORIZATION_ENABLED = True       # ✅ 授权系统总开关（已启用）
AUTO_AUTHORIZE_BY_ROLE = True      # ✅ 根据角色自动授权（已启用）
SEND_FIRST_AUTH_WELCOME = True     # ✅ 发送首次授权欢迎语（已启用）


class AuthorizationService:
    """授权服务 - 管理群组的授权状态"""
    
    async def check_and_authorize_group(
        self,
        chat: Chat,
        inviter: User,
        context: ContextTypes.DEFAULT_TYPE,
        auto_authorize: bool = False  # 是否启用自动授权
    ) -> Tuple[GroupStatus, bool]:
        """
        检查并授权群组（安全版 - 不影响现有逻辑）
        
        ⚠️ 重要：此方法仅在 AUTHORIZATION_ENABLED=True 时才会被调用
        
        Args:
            chat: Telegram 群组对象
            inviter: 邀请 bot 进群的用户
            context: Context 对象
            auto_authorize: 是否启用自动授权（默认 False，需要显式开启）
            
        Returns:
            (群组状态, 是否已发送首次欢迎语)
        """
        # 🛡️ 安全检查：如果功能未启用，直接返回 ACTIVE（保持原有行为）
        if not AUTHORIZATION_ENABLED:
            logger.debug("⏭️ 授权系统未启用，跳过检查")
            return GroupStatus.ACTIVE, False
        
        bot_id = get_current_bot_id(context)
        chat_id = chat.id
        
        logger.info(f"🔐 [AUTH] 检查群组 {chat_id} 授权状态，邀请者: {inviter.username or inviter.first_name}")
        
        # 1. 检查邀请者角色
        role = await get_user_role(inviter.id, chat_id, bot_id)
        logger.info(f"   [AUTH] 邀请者角色: {role}")
        
        # 🆕 关键修复：直接使用 role_checker 的统一判断，消除重复代码
        # role_checker.get_user_role 已包含三重检查：config → 环境变量 → 数据库主BOT记录
        is_super_admin = (role == UserRole.SUPER_ADMIN)
        
        if is_super_admin:
            logger.info(f"   [AUTH] 🔥 邀请者是超级管理员，强制授权并跳过所有限制！")
        
        async with get_db_session() as db:
            # 2. 查询或创建群组记录
            query = select(Group).where(
                and_(
                    Group.group_id == chat_id,
                    Group.bot_id == bot_id
                )
            )
            result = await db.execute(query)
            group = result.scalar_one_or_none()
            
            if not group:
                # 创建新群组记录（默认为 PENDING 状态）
                group = Group(
                    bot_id=bot_id,
                    group_id=chat_id,
                    group_name=chat.title or "Unknown",
                    group_type=chat.type,
                    status=GroupStatus.PENDING.value,  # 初始状态为 PENDING
                    invited_by=inviter.id,
                    invited_by_username=inviter.username,
                    first_welcome_sent=False
                )
                db.add(group)
                await db.flush()  # 获取 ID
                
                # ✅ 关键修复：创建群组时自动分配到默认分组
                await self._assign_to_default_group(group, bot_id, db)
                
                # ✅ 发布群组绑定事件，触发页面实时刷新
                try:
                    await event_bus.publish(Event(
                        event_type=EventType.GROUP_BOUND_TO_TAG,
                        data={
                            "bot_id": bot_id,
                            "group_id": chat_id,
                            "group_name": chat.title or "Unknown",
                            "tag_name": DEFAULT_BROADCAST_GROUP_TAG,
                            "operator_id": inviter.id
                        },
                        bot_id=bot_id
                    ))
                    logger.info(f"   [AUTH] 📡 已发布群组绑定事件: {chat_id} -> 默认")
                except Exception as e:
                    logger.warning(f"   [AUTH] ️ 发布群组绑定事件失败: {e}")
                
                logger.info(f"   [AUTH] ✅ 创建新群组记录: {chat_id} (status=PENDING)")
            
            # 3. 如果启用了自动授权，根据角色决定授权状态
            if auto_authorize and AUTO_AUTHORIZE_BY_ROLE:
                # 🆕 修复：BOT_OWNER、SUPER_ADMIN、ADMIN 都可以自动授权
                if role in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN]:
                    # 🔥 关键修复：超级管理员跳过额度检查，永远自动授权
                    if role != UserRole.SUPER_ADMIN:
                        # 🆕 检查试用管理员的群组额度（仅非超管需要检查）
                        from .trial_group_limit_service import trial_group_limit_service
                        can_add, current_groups, group_limit, limit_message = await trial_group_limit_service.check_group_limit(
                            bot_id, inviter.id
                        )

                        if not can_add:
                            # 额度不足，标记为未授权并发送提示
                            if group.status != GroupStatus.UNAUTHORIZED.value:
                                old_status = group.status
                                group.status = GroupStatus.UNAUTHORIZED.value
                                logger.info(f"   [AUTH] ⚠️ 试用管理员群组额度不足: {old_status} → UNAUTHORIZED ({current_groups}/{group_limit})")

                            await db.commit()

                            # 发送额度不足提示
                            await self._send_trial_limit_notice(chat, context, limit_message)

                            return GroupStatus.UNAUTHORIZED, False
                    else:
                        logger.info(f"   [AUTH] 🔥 超级管理员跳过额度检查，直接授权")

                    # 管理员/超管/Bot拥有者拉群 → 自动授权
                    if group.status != GroupStatus.ACTIVE.value:
                        old_status = group.status
                        group.status = GroupStatus.ACTIVE.value
                        logger.info(f"   [AUTH] ✅ 自动授权群组: {old_status} → ACTIVE (role={role})")

                    # 绑定主管理员
                    if not group.invited_by:
                        group.invited_by = inviter.id
                        group.invited_by_username = inviter.username
                        logger.info(f"   [AUTH] 👤 绑定主管理员: {inviter.username or inviter.first_name}")

                    await self._ensure_group_operator(db, bot_id, chat_id, inviter)

                    await db.commit()

                    # 4. 如果启用了首次欢迎语，发送欢迎语（仅发送一次）
                    welcome_sent = False
                    if SEND_FIRST_AUTH_WELCOME:
                        welcome_sent = await self._send_first_auth_welcome(group, inviter, context)

                    try:
                        from ..handlers.bot_group_features import build_authorized_group_panel_keyboard, build_authorized_group_panel_text
                        title = "🎉 首次群组授权成功" if not group.first_welcome_sent else "🎉 群组重新激活通知"
                        await context.bot.send_message(
                            chat_id=inviter.id,
                            text=build_authorized_group_panel_text(group, title=title),
                            reply_markup=build_authorized_group_panel_keyboard(group.group_id, back_callback="mygroups:show"),
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.warning(f"   ⚠️ 发送授权成功私聊通知失败: {e}")

                    return GroupStatus.ACTIVE, welcome_sent
                else:
                    # 普通用户拉群 → 标记为未授权
                    if group.status != GroupStatus.UNAUTHORIZED.value:
                        old_status = group.status
                        group.status = GroupStatus.UNAUTHORIZED.value
                        logger.info(f"   [AUTH] ⚠️ 标记为未授权: {old_status} → UNAUTHORIZED (role={role})")
                    
                    await db.commit()
                    
                    # 发送未授权提示
                    await self._send_unauthorized_notice(chat, context)
                    
                    return GroupStatus.UNAUTHORIZED, False
            else:
                # 未启用自动授权，保持原有状态（向后兼容）
                logger.debug(f"   [AUTH] ⏭️ 自动授权未启用，保持当前状态: {group.status}")
                return GroupStatus(group.status), group.first_welcome_sent

    async def _ensure_group_operator(self, db, bot_id: str, chat_id: int, user: User) -> None:
        from ..repositories.group_repo import GroupOperatorRepo

        op_repo = GroupOperatorRepo(db, bot_id)
        if await op_repo.is_operator(chat_id, user.id):
            return
        await op_repo.add_operator(
            group_id=chat_id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )
        logger.info(
            "   [AUTH] ➕ 已将邀请者写入当前 bot 的 group_operators: bot_id=%s group_id=%s user_id=%s",
            bot_id,
            chat_id,
            user.id,
        )
    
    async def _send_first_auth_welcome(
        self,
        group: Group,
        inviter: User,
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        发送首次授权欢迎语（仅在 SEND_FIRST_AUTH_WELCOME=True 时调用）
        ✅ 每次 Bot 进群都会发送，无次数限制
        🆕 优先使用自定义欢迎语，没有则使用用户要求的默认文案
        
        Returns:
            是否已发送
        """
        bot_id = group.bot_id
        
        try:
            # 🆕 优先读取自定义欢迎语（从 AdminGlobalConfig）
            custom_messages = None
            
            async with get_db_session() as db:
                config_query = select(AdminGlobalConfig).where(
                    and_(
                        AdminGlobalConfig.bot_id == bot_id,
                        AdminGlobalConfig.config_key == "bot_join_messages",
                        AdminGlobalConfig.is_active.is_(True)
                    )
                )
                config_result = await db.execute(config_query)
                config = config_result.scalar_one_or_none()
            
            # 如果有自定义欢迎语，优先使用
            if config and config.config_value:
                try:
                    import json
                    custom_messages = json.loads(config.config_value).get("value")
                except Exception:
                    custom_messages = config.config_value
            
            # 替换占位符
            username = inviter.username or inviter.first_name or "用户"
            
            if custom_messages:
                # 使用自定义欢迎语
                if isinstance(custom_messages, str):
                    custom_messages = [custom_messages]
                
                for msg in custom_messages:
                    processed_msg = msg
                    # 支持替换 {username} 或 @{username}
                    processed_msg = processed_msg.replace("{username}", username)
                    processed_msg = processed_msg.replace("@{username}", f"@{username}")
                    
                    await context.bot.send_message(
                        chat_id=group.group_id,
                        text=processed_msg,
                        parse_mode="HTML"
                    )
                logger.info(f"   [AUTH] 🎉 使用自定义欢迎语发送到群组 {group.group_id}")
            else:
                # 🆕 使用用户要求的默认欢迎语文案
                welcome_message = (
                    "🎉 欢迎 @{username} 将我添加到本群\n"
                    "✅ 本群已被授权使用✨ 所有功能已启用\n\n"
                    "📝 发送 /start 即可开始记账📖 发送 /help 查看详细指南\n\n"
                    "💡 如果发送命令没反应，请检查：\n"
                    "• 请到 @BotFather 关闭本机器人的 Group Privacy（群组隐私模式）\n"
                    "• 或将机器人设置为群管理员后再测试"
                )
                
                # 替换占位符
                message = welcome_message.replace("@{username}", f"@{username}")
                message = message.replace("{username}", f"@{username}")
                
                await context.bot.send_message(
                    chat_id=group.group_id,
                    text=message,
                    parse_mode="HTML"
                )
                logger.info(f"   [AUTH] 🎉 使用默认欢迎语文案发送到群组 {group.group_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"   [AUTH] ❌ 发送首次授权欢迎语失败: {e}", exc_info=True)
            return False
    
    async def _send_trial_limit_notice(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE, message: str):
        """发送试用管理员群组额度不足提示"""
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=message,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"发送额度不足提示失败: {e}")

    async def _send_unauthorized_notice(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE):
        """发送未授权提示（动态显示超级管理员用户名）"""
        # 获取 bot_id
        bot_id = get_current_bot_id(context)
            
        # 获取超级管理员用户名
        super_admin_username = await self._get_super_admin_username(bot_id)
            
        # 构建提示信息
        notice = "❌ <b>当前群未授权</b>\n\n"
            
        if super_admin_username:
            notice += f"请联系 <b>@{super_admin_username}</b> 进行授权。\n\n"
        else:
            notice += "请联系 Bot 超管进行授权。\n\n"
            
        notice += " 提示：只有 Bot 的超管和管理员拉我进群才会自动授权哦~"
            
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=notice,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"发送未授权提示失败: {e}")
        
    async def _get_super_admin_username(self, bot_id: str) -> Optional[str]:
        """
        获取创建此 Bot 的超级管理员用户名
        
        ✅ 新架构：使用异步数据库会话 + 租户隔离查询
        
        Args:
            bot_id: Bot 实例 ID
                
        Returns:
            超级管理员用户名（不含@），如果找不到则返回 None
        """
        try:
            async with get_db_session() as db:
                # ✅ 查询 BotCreation 记录（租户隔离：bot_id 已限定）
                from ..models import BotCreation
                query = select(BotCreation).where(BotCreation.instance_id == bot_id)
                result = await db.execute(query)
                bot_creation = result.scalar_one_or_none()
                    
                if not bot_creation:
                    logger.warning(f"Bot creation record not found for bot_id: {bot_id}")
                    return None
                    
                super_admin_id = bot_creation.super_admin_id
                logger.debug(f"Found super_admin_id: {super_admin_id} for bot: {bot_id}")
                    
                # ✅ 查询 Admin 记录获取用户名（租户隔离）
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
    
    async def manual_authorize_group(
        self,
        chat_id: int,
        bot_id: str,
        authorized_by: int,
        context: ContextTypes.DEFAULT_TYPE = None
    ) -> tuple[bool, str]:
        """
        超管手动授权群组（增强版）
        - 授权后自动获取群成员列表
        - 找到拉 bot 进群的用户（invited_by）
        - 自动设置为该群组的主管理员
        
        Args:
            chat_id: 群组 ID
            bot_id: Bot 实例 ID
            authorized_by: 授权者用户 ID
            
        Returns:
            (是否成功, 消息文本)
        """
        # ✅ 修复：GroupOperatorRepo 在 group_repo 模块中
        from ..repositories.group_repo import GroupOperatorRepo
        from ..repositories.group_repo import GroupRepo
        
        async with get_db_session() as db:
            # 查询群组
            query = select(Group).where(
                and_(
                    Group.group_id == chat_id,
                    Group.bot_id == bot_id
                )
            )
            result = await db.execute(query)
            group = result.scalar_one_or_none()
            
            if not group:
                return False, f"❌ 群组 {chat_id} 不存在\n\n请先将 Bot 添加到该群组。"
            
            # 🆕 检查群组是否已经授权
            if group.status == GroupStatus.ACTIVE.value:
                inviter_info = ""
                if group.invited_by:
                    inviter_info = f"\n👤 主管理员：@{group.invited_by_username or '未知'}"
                
                return False, f"⚠️ 群组 {chat_id}\n\n已经授权，无需重复授权\n 当前状态：✅已经授权{inviter_info}"
            
            # 更新状态
            old_status = group.status
            group.status = GroupStatus.ACTIVE.value
            
            # 🆕 重置首次欢迎语标记（允许重新发送）
            # 如果希望每个群组只发送一次，可以注释掉下面这行
            # group.first_welcome_sent = False
            
            # 🆕 如果还没有绑定主管理员，尝试从 Telegram API 获取
            if not group.invited_by:
                try:
                    # ✅ 新架构：直接使用 context.bot，不再使用 bot_instance_manager
                    if context and context.bot:
                        admins = await context.bot.get_chat_administrators(chat_id)
                        
                        # 优先绑定群主（creator）
                        for admin in admins:
                            if admin.status == 'creator':
                                group.invited_by = admin.user.id
                                group.invited_by_username = admin.user.username
                                logger.info(f"   👤 绑定群主为主管理员: {admin.user.username}")
                                
                                # 🆕 同时将群主添加为群组操作人
                                op_repo = GroupOperatorRepo(db, bot_id)
                                is_already_operator = await op_repo.is_operator(chat_id, admin.user.id)
                                
                                if not is_already_operator:
                                    await op_repo.add_operator(
                                        group_id=chat_id,
                                        user_id=admin.user.id,
                                        username=admin.user.username,
                                        first_name=admin.user.first_name
                                    )
                                    logger.info(f"   ➕ 已将群主添加为群组操作人")
                                
                                break
                        
                        # 如果没有找到群主，使用第一个管理员
                        if not group.invited_by and admins:
                            first_admin = admins[0]
                            group.invited_by = first_admin.user.id
                            group.invited_by_username = first_admin.user.username
                            logger.info(f"   👤 绑定第一个管理员为主管理员: {first_admin.user.username}")
                    else:
                        logger.warning(f"   ⚠️ context.bot 不可用，无法获取管理员列表")
                        
                except Exception as e:
                    logger.warning(f"   ⚠️ 无法获取群管理员信息: {e}")
            
            await db.commit()
            
            logger.info(f"   ✅ 手动授权群组: {chat_id} ({old_status} → ACTIVE)")
            
            # 🆕 向群组发送授权成功通知
            if context and context.bot:
                try:
                    notification_message = (
                        f"🎉 <b>机器人授权成功</b>\n\n"
                        f"本群组已成功授权使用记账机器人\n"
                        f"现在可以正常使用所有功能了！\n\n"
                        f"如有疑问，请联系群管理员。"
                    )
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=notification_message,
                        parse_mode='HTML'
                    )
                    logger.info(f"   📨 已向群组 {chat_id} 发送授权成功通知")
                except Exception as e:
                    logger.warning(f"   ⚠️ 发送授权通知失败: {e}")
            
            if context and context.bot and group.invited_by:
                try:
                    from ..handlers.bot_group_features import build_authorized_group_panel_keyboard, build_authorized_group_panel_text
                    title = "🎉 首次群组授权成功" if not group.first_welcome_sent else "🎉 群组重新激活通知"
                    await context.bot.send_message(
                        chat_id=group.invited_by,
                        text=build_authorized_group_panel_text(group, title=title),
                        reply_markup=build_authorized_group_panel_keyboard(group.group_id, back_callback="mygroups:show"),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"   ⚠️ 发送授权私聊通知失败: {e}")

            inviter_info = ""
            if group.invited_by:
                inviter_info = f"\n👤 主管理员：@{group.invited_by_username or '未知'}"
            
            return True, f"🎉 <b>群组授权成功</b>\n\n📋 <b>授权信息</b>\n 群组 ID：<code>{chat_id}</code>\n 授权状态：✅已被授权使用{inviter_info}\n\n✨ 群组现已激活，可以正常使用机器人功能！"
    
    async def _get_chat_administrators(self, chat_id: int, bot_id: str, context: ContextTypes.DEFAULT_TYPE = None):
        """
        获取群组管理员列表
        
        ✅ 新架构：使用 context.bot 调用 Telegram API
        
        Args:
            chat_id: 群组 ID
            bot_id: Bot 实例 ID（用于日志记录）
            context: Context 对象（可选）
        
        Returns:
            管理员列表，如果失败则返回空列表
        """
        if not context or not context.bot:
            logger.warning(f"   ⚠️ context.bot 不可用，无法获取管理员列表")
            return []
        
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            logger.info(f"    成功获取群组 {chat_id} 的管理员列表: {len(admins)} 人")
            return admins
        except Exception as e:
            logger.error(f"    获取群组管理员列表失败: {e}")
            return []
    
    async def _assign_to_default_group(self, group, bot_id, db):
        """
        分配到默认分组
        
        Args:
            group: Group 对象
            bot_id: Bot 实例 ID
            db: 数据库会话
        """
        from ..models import BroadcastGroup
        from ..models.group import DEFAULT_BROADCAST_GROUP_TAG
        
        query = select(BroadcastGroup).where(
            and_(
                BroadcastGroup.name == DEFAULT_BROADCAST_GROUP_TAG,
                BroadcastGroup.bot_id == bot_id
            )
        )
        result = await db.execute(query)
        default_group = result.scalar_one_or_none()
        
        if default_group:
            group.broadcast_group_id = default_group.id
            logger.info(f"   [AUTH] 📌 群组自动分配到默认分组 (id={default_group.id})")
        else:
            logger.warning(f"   [AUTH] ⚠️ 默认分组不存在，无法分配")


# 全局实例
authorization_service = AuthorizationService()

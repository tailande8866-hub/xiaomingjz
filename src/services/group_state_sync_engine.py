"""
群组状态同步引擎（增强版）

职责：
1. 监听机器人被踢/退群事件
2. 监听机器人重新进群事件
3. 自动更新群组状态和分组配置
4. 通知管理员群组状态变更
5. 🆕 集成授权服务，根据角色自动授权群组
"""
import logging
from telegram import ChatMember, Update, User
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models import Group, BroadcastGroup, Admin, get_db_session
from ..models.group import DEFAULT_BROADCAST_GROUP_TAG
from ..models.enums import GroupStatus
from .authorization_service import authorization_service, AUTHORIZATION_ENABLED, AUTO_AUTHORIZE_BY_ROLE

logger = logging.getLogger(__name__)


class GroupStateSyncEngine:
    """
    群组状态同步引擎
    
    状态流转：
    active → kicked/left → inactive
    inactive → joined/restored → active (重置为默认分组)
    """
    
    async def handle_status_change(
        self, 
        chat_id: int, 
        old_status: str, 
        new_status: str,
        bot_id: str,
        context: ContextTypes.DEFAULT_TYPE,
        from_user=None  # 👤 拉 bot 进群的用户
    ):
        """
        处理群组状态变更
        
        Args:
            chat_id: 群组 ID
            old_status: 旧状态 (member/administrator/kicked/left)
            new_status: 新状态
            bot_id: Bot 实例 ID
            context: Context 对象
        """
        async with get_db_session() as db:
            # 查询群组记录
            query = select(Group).where(
                and_(
                    Group.group_id == chat_id,
                    Group.bot_id == bot_id
                )
            )
            result = await db.execute(query)
            group = result.scalar_one_or_none()
            
            if not group:
                # ✅ 场景：新群组加入，自动创建记录并分配到默认分组
                if new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                    await self._create_new_group(chat_id, bot_id, context, db, from_user)
                return
            
            # 场晩1：机器人被踢或退群
            # ✅ 修复：Telegram Bot API 20.x 中 KICKED 已改为 BANNED
            if new_status in [ChatMember.LEFT, ChatMember.BANNED]:
                await self._handle_removal(group, chat_id, bot_id, db, context)
            
            # 场晩2：机器人重新进群
            elif new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                if not group.is_active:
                    await self._handle_restoration(group, chat_id, bot_id, db, context, from_user)
                else:
                    # 🆕 场晩3：机器人已经是激活状态，检查权限变更（从 member -> administrator）
                    await self._handle_permission_upgrade(group, chat_id, old_status, new_status, bot_id, db, context)
    
    async def _handle_removal(self, group, chat_id, bot_id, db, context):
        """处理机器人被移除"""
        if group.is_active:
            group.is_active = False
            group.broadcast_group_id = None  # ✅ 清除分组配置
            await db.commit()
            
            logger.warning(f"⚠️ Group {chat_id} marked as inactive (bot removed)")
            
            # 通知管理员
            await self._notify_admins(chat_id, "removed", bot_id, context)
    
    async def _handle_restoration(self, group, chat_id, bot_id, db, context, from_user=None):
        """处理机器人重新加入"""
        # 🆕 如果启用了授权系统，检查邀请者角色
        if AUTHORIZATION_ENABLED and AUTO_AUTHORIZE_BY_ROLE and from_user:
            logger.info(f"🔐 [AUTH] 群组 {chat_id} 重新进群，调用授权服务检查邀请者角色")
            
            try:
                chat = await context.bot.get_chat(chat_id)
                group_status, welcome_sent = await authorization_service.check_and_authorize_group(
                    chat=chat,
                    inviter=from_user,
                    context=context,
                    auto_authorize=True
                )
                
                logger.info(f"   [AUTH] 授权结果: status={group_status}, welcome_sent={welcome_sent}")
                
                # 如果是未授权状态，不激活群组
                if group_status.value == 'UNAUTHORIZED':
                    logger.warning(f"⚠️ 群组 {chat_id} 未授权，保持非激活状态")
                    return
            except Exception as e:
                logger.error(f"   [AUTH] 授权检查失败: {e}，继续执行原有逻辑")
        
        # ✅ 关键：重新激活时重置为默认分组
        await self._assign_to_default_group(group, bot_id, db)
        
        # 👤 更新邀请者信息（如果是重新进群）
        if from_user and not group.invited_by:
            group.invited_by = from_user.id
            group.invited_by_username = from_user.username
            logger.info(f"👤 Updated inviter for group {chat_id}: {from_user.username or from_user.first_name}")
        
        group.is_active = True
        await db.commit()
        
        logger.info(f"✅ Group {chat_id} reactivated and reset to default group")

        # 🆕 移除重复发送：只在新群组时发送欢迎语，避免重复
        # 通知管理员
        await self._notify_admins(chat_id, "restored", bot_id, context)
    
    async def _assign_to_default_group(self, group, bot_id, db):
        """分配到默认分组"""
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
            logger.info(f"📌 Group assigned to default group (id={default_group.id})")
        else:
            group.broadcast_group_id = None
            logger.warning(f"⚠️ Default group not found for bot {bot_id}")
    
    async def _create_new_group(self, chat_id, bot_id, context, db, from_user=None):
        """创建新群组记录并处理授权逻辑"""
        from datetime import datetime
        
        # 获取群组名称
        try:
            chat = await context.bot.get_chat(chat_id)
            chat_title = chat.title or "Unknown"
        except Exception:
            chat_title = "Unknown"
        
        # 🆕 如果启用了授权系统，先调用授权服务检查并授权
        if AUTHORIZATION_ENABLED and AUTO_AUTHORIZE_BY_ROLE and from_user:
            logger.info(f"🔐 [AUTH] 新群组 {chat_id}，调用授权服务检查邀请者角色")
            
            # 调用授权服务（自动授权模式）
            group_status, welcome_sent = await authorization_service.check_and_authorize_group(
                chat=chat,
                inviter=from_user,
                context=context,
                auto_authorize=True  # 启用自动授权
            )
            
            logger.info(f"   [AUTH] 授权结果: status={group_status}, welcome_sent={welcome_sent}")
            
            # 如果是未授权状态，直接返回（不创建操作人等后续逻辑）
            if group_status.value == 'UNAUTHORIZED':
                logger.warning(f"⚠️ 群组 {chat_id} 未授权，跳过后续初始化")
                return
            
            # ✅ 如果授权成功，授权服务已经创建了 Group 记录，直接返回
            if group_status.value == 'ACTIVE':
                logger.info(f"✅ 群组 {chat_id} 已通过授权服务创建并授权")
                # 🆕 移除重复发送：授权服务已经发送了欢迎语，避免重复
                return
        
        # 创建新的 Group 记录（仅在授权系统未启用时执行）
        new_group = Group(
            bot_id=bot_id,
            group_id=chat_id,
            group_name=chat_title,
            group_type="supergroup",
            status=GroupStatus.ACTIVE.value,  # ✅ 明确设置状态
            is_active=True,
            is_muted=False,
            display_mode="pure",
            currency_mode="single",
            currency_display="USDT",
            pin_enabled=False,
            deposit_display_count=5,
            withdraw_display_count=5,
            category_enabled=False,
            exchange_rate=7.3,
            fee_rate=3.0,
            real_time_rate=False,
            all_members_operator=False,
            first_welcome_sent=False  # ✅ 重置首次欢迎语标记
        )
        
        # 👤 记录邀请者信息
        if from_user:
            new_group.invited_by = from_user.id
            new_group.invited_by_username = from_user.username
            logger.info(f"👤 Recorded inviter for new group {chat_id}: {from_user.username or from_user.first_name}")
        
        # 分配到默认分组
        await self._assign_to_default_group(new_group, bot_id, db)
        
        db.add(new_group)
        await db.commit()
        
        logger.info(f"✅ Created new group record for {chat_id} ({chat_title})")

        # 🆕 移除重复发送：如果启用了授权系统，授权服务已经发送了欢迎语
    
    async def _handle_permission_upgrade(self, group, chat_id, old_status, new_status, bot_id, db, context):
        """处理权限升级（从 member -> administrator）"""
        # 检测是否从普通成员升级为管理员
        if old_status == ChatMember.MEMBER and new_status == ChatMember.ADMINISTRATOR:
            logger.info(f"🔐 Bot promoted to admin in group {chat_id}")
            
            # 在群组中发送提示消息
            try:
                message = (
                    "✅ <b>机器人权限已更新</b>\n\n"
                    "🎉 感谢将机器人设置为管理员！\n\n"
                    "现在机器人可以：\n"
                    "• 📌 置顶账单消息\n"
                    "• 🗑️ 删除过期消息\n"
                    "• 👥 管理群组成员\n"
                    "• 📊 获取更准确的群组信息\n\n"
                    "💡 使用提示：\n"
                    "• 发送 <code>/help</code> 查看帮助\n"
                    "• 发送 <code>/start</code> 开启记账功能\n"
                )
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='HTML'
                )
                
                logger.info(f"✅ Sent admin promotion notification to group {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send admin promotion notification: {e}")
    
    async def _notify_admins(self, chat_id, action, bot_id, context):
        """通知管理员群组状态变更"""
        async with get_db_session() as db:
            query = select(Admin).where(
                and_(
                    Admin.bot_id == bot_id,
                    Admin.is_active.is_(True)
                )
            )
            result = await db.execute(query)
            admins = result.scalars().all()
            
            for admin in admins:
                try:
                    if action == "removed":
                        message = (
                            f"⚠️ 群组状态变更通知\n\n"
                            f"群组ID：{chat_id}\n"
                            f"状态：机器人已被移出群组\n"
                            f"操作：该群组已标记为失效，分组配置已清除"
                        )
                    else:  # restored
                        group = (await db.execute(
                            select(Group).where(and_(Group.bot_id == bot_id, Group.group_id == chat_id))
                        )).scalar_one_or_none()
                        if group:
                            if group.invited_by:
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
                                    logger.warning(f"Failed to notify inviter {group.invited_by}: {e}")
                            from ..handlers.bot_group_features import build_authorized_group_panel_keyboard, build_authorized_group_panel_text
                            await context.bot.send_message(
                                chat_id=admin.user_id,
                                text=build_authorized_group_panel_text(group, title="✅ 群组重新激活通知"),
                                reply_markup=build_authorized_group_panel_keyboard(group.group_id, back_callback="mygroups:show"),
                                parse_mode="HTML",
                            )
                            continue
                        message = (
                            f"✅ 群组重新激活通知\n\n"
                            f"群组ID：{chat_id}\n"
                            f"状态：机器人已重新加入群组\n"
                            f"操作：群组已重新激活，并自动分配到「默认」分组"
                        )

                    await context.bot.send_message(chat_id=admin.user_id, text=message)
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin.user_id}: {e}")


# 全局实例
group_state_sync_engine = GroupStateSyncEngine()

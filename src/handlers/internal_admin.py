"""
管理员管理处理器
处理添加/删除/查看管理员（高权限成员）

⚠️ DEPRECATED - 旧架构实现
此文件已迁移到新架构,请参考:
- capability_system.py (权限控制: admin:manage)
- ui_schema_registry.py (UI路由)
- repositories/admin_repo.py (数据访问)

新功能请使用新架构开发
预计删除时间: 2026-Q3
"""
import logging
import re
from datetime import datetime
from telegram import Update, User
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models import Admin, GroupOperator, get_db
from ..services.private_chat_user_service import get_user_by_username
from ..utils.tenant_scope import scoped_query, scoped_insert

logger = logging.getLogger(__name__)


async def is_admin_user(user_id: int, db, bot_id: str = None) -> bool:
    """检查用户是否为管理员（支持租户隔离）"""
    logger.debug(f"Checking admin: user_id={user_id}, bot_id={bot_id}")
    
    # ✅ Admin 现在支持租户隔离
    conditions = [
        Admin.user_id == user_id,
        Admin.is_active.is_(True)
    ]
    
    if bot_id:
        conditions.append(Admin.bot_id == bot_id)
    
    query = select(Admin).where(and_(*conditions))
    result = await db.execute(query)
    member = result.scalar_one_or_none()
    
    if member:
        logger.debug(f"User {user_id} is admin for bot {bot_id}")
        return True
    
    logger.debug(f"User {user_id} is NOT admin for bot {bot_id}")
    return False


async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加管理员（仅限私聊 + 全局权限人）"""
    try:
        if not update.message or not update.effective_chat or not update.effective_user:
            return

        chat_id = update.effective_chat.id
        user = update.effective_user
        text = update.message.text.strip()

        logger.info(f"收到添加管理员命令: '{text}', 聊天类型: {update.effective_chat.type}, 用户: {user.id}")

        # 检查是否为私聊
        if update.effective_chat.type != 'private':
            await update.message.reply_text(
                "🚫 添加管理员仅限在私聊中使用\n\n"
                "请私聊机器人进行添加操作"
            )
            return

        logger.info(f"处理添加管理员命令: {text}, 用户: {user.id}")

        async for db in get_db():
            # ✅ 使用 PermissionService 检查权限（P0 优化 - 低风险入口接入）
            from src.services.permission_service import permission_service, Permission
            from ..utils.bot_id_middleware import get_current_bot_id
            from ..utils.role_checker import is_super_admin

            bot_id = get_current_bot_id(context)

            if not await permission_service.has_permission(bot_id, user.id, Permission.MANAGE_ADMINS):
                await update.message.reply_text(
                    "❌ 权限不足\n\n"
                    "只有超级管理员或拥有管理管理员权限的管理员可以添加管理员\n\n"
                    "如需添加管理员，请联系超级管理员"
                )
                return

            # 获取要添加的用户
            target_user = None
            target_username = None

            # 方法1: 从回复消息中获取用户
            if update.message.reply_to_message and update.message.reply_to_message.from_user:
                target_user = update.message.reply_to_message.from_user
                logger.info(f"从回复消息中获取用户: {target_user.id}")
            # 方法2: 从text_mention实体中获取用户（群组中@用户）
            elif update.message.entities:
                for entity in update.message.entities:
                    if entity.type == "text_mention" and entity.user:
                        target_user = entity.user
                        logger.info(f"从text_mention中获取用户: {target_user.id}")
                        break

            # 方法3: 从文本中提取@username并查找私聊过的用户
            if not target_user:
                match = re.search(r'@(\w+)', text)
                if match:
                    target_username = match.group(1)
                    logger.info(f"从文本中提取到username: @{target_username}")

                    # 查找该用户是否曾与机器人私聊过
                    private_chat_user = await get_user_by_username(target_username, context)

                    if private_chat_user:
                        # 找到用户，创建一个User对象
                        target_user = User(
                            id=private_chat_user.user_id,
                            is_bot=False,
                            first_name=private_chat_user.first_name or target_username,
                            username=private_chat_user.username
                        )
                        logger.info(f"通过username查找到用户: ID={private_chat_user.user_id}, @{target_username}")
                    else:
                        logger.warning(f"未找到与机器人私聊过的用户: @{target_username}")

            logger.info(f"最终target_user: {target_user}")

            if not target_user:
                await update.message.reply_text(
                    "❌ 未找到目标用户\n\n"
                    "使用方法（任选其一）：\n"
                    "1️⃣ 回复该用户的消息后发送「添加管理员」\n"
                    "2️⃣ 发送「添加管理员 @username」（该用户必须曾与机器人私聊过）\n\n"
                    "💡 提示：\n"
                    "• 如果用户从未与机器人私聊过，请先让该用户私聊机器人\n"
                    "• 可以通过 /start 命令开始私聊"
                )
                return

            target_user_id = target_user.id

            # 检查目标用户是否是超级管理员
            if await is_super_admin(target_user_id, bot_id=bot_id):
                user_display = target_user.first_name or target_user.username or f'ID:{target_user_id}'
                await update.message.reply_text(
                    f"⚠️ {user_display} 已是超级管理员\n\n"
                    f"无需添加到管理员列表"
                )
                return
            
            # 检查是否已存在该用户的管理员记录（不管is_active状态）
            # ✅ Admin 支持租户隔离
            query = scoped_query(Admin, context).where(
                Admin.user_id == target_user_id
            )
            result = await db.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                if existing.is_active:
                    # 已经是活跃的管理员，显示友好提示
                    # 构建友好的重复添加提示
                    permissions = []
                    # 群组所有功能（管理群成员 + 其他群组权限）
                    if existing.can_manage_group_members:
                        permissions.append("✅ 群组所有功能")
                    # 广播权限
                    if existing.can_broadcast:
                        permissions.append("✅ 广播权限")
                    # 日切设置
                    if existing.can_set_day_cut:
                        permissions.append("✅ 日切设置")
                    # 关键词回复
                    if existing.can_set_keywords:
                        permissions.append("✅ 关键词回复")
                    # 管理管理员（需 can_manage_admins 权限）
                    if existing.can_manage_admins:
                        permissions.append("✅ 管理管理员")
                    # 创建机器人
                    if existing.can_create_bot:
                        permissions.append("✅ 创建机器人")
                    
                    perm_text = "\n".join(permissions) if permissions else "❌ 暂无特殊权限"
                    
                    # 用户名兼容处理：优先显示 first_name，其次 username，最后显示 ID
                    user_display = target_user.first_name or target_user.username or f'ID:{target_user_id}'
                    
                    await update.message.reply_text(
                        f"ℹ️ 该用户已经是管理员\n\n"
                        f" 用户名：{user_display}\n"
                        f" Telegram ID：{target_user_id}\n"
                        f"📅 添加时间：{existing.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                        f" 添加者：{existing.added_by_username or f'ID:{existing.added_by}'}\n\n"
                        f"🔐 当前权限：\n{perm_text}\n\n"
                        f"💡 提示：\n"
                        f"• 如需修改权限，请联系超级管理员"
                    )
                    return
                else:
                    # 存在但is_active=False，重新激活并更新信息
                    logger.info(f"重新激活已删除的管理员: user_id={target_user_id}")
                    existing.is_active = True
                    existing.username = target_user.username
                    existing.first_name = target_user.first_name
                    existing.last_name = target_user.last_name
                    existing.updated_at = datetime.utcnow()
                    await db.commit()
                    logger.info(f"管理员已重新激活: user_id={target_user_id}")
                    
                    # 获取管理员总数
                    # ✅ Admin 支持租户隔离
                    query = scoped_query(Admin, context).where(Admin.is_active.is_(True))
                    result = await db.execute(query)
                    all_admins = result.scalars().all()
                    total_count = len(all_admins)
                    
                    # 显示重新激活成功的消息
                    user_display_short = target_user.username or target_user.first_name or f'用户{target_user_id}'
                    await update.message.reply_text(
                        f"添加内部成员命令\n"
                        f"✅@{user_display_short} 已经设置为管理员"
                    )
                    
                    logger.info(f"User {user.id} reactivated admin {target_user_id}")
                    return
            
            # 添加管理员（默认不授予创建机器人权限，需手动开启以支持裂变）
            admin = Admin(
                user_id=target_user_id,
                username=target_user.username,
                first_name=target_user.first_name,
                can_create_bot=False,  # 默认不能创建机器人（如需支持裂变，请手动设置为 True）
                can_manage_group_members=True,
                can_broadcast=True,
                can_set_day_cut=True,
                can_set_keywords=True,
                added_by=user.id,
                added_by_username=user.username,
                is_active=True
            )
            
            # ✅ 注入 bot_id（租户隔离）
            admin = scoped_insert(admin, context)
            
            db.add(admin)
            await db.commit()
            
            # 获取管理员总数
            # ✅ Admin 支持租户隔离
            query = scoped_query(Admin, context).where(Admin.is_active.is_(True))
            result = await db.execute(query)
            all_admins = result.scalars().all()
            total_count = len(all_admins)
            
            # 第一条消息：简洁的成功提示（匹配截图格式）
            user_display_short = target_user.username or target_user.first_name or f'用户{target_user_id}'
            await update.message.reply_text(
                f"添加内部成员命令\n"
                f"✅@{user_display_short} 已经设置为管理员"
            )
            
            # 第二条消息：详细信息 + 总数 + 查看链接（匹配截图格式）
            # 用户名兼容处理：优先 first_name > username > ID
            user_display = target_user.first_name or target_user.username or f'ID:{target_user_id}'
            await update.message.reply_text(
                f"👤 用户名：{user_display}\n"
                f" Telegram ID：{target_user_id}\n\n"
                f"🔐 权限：\n"
                f"• ✅ 可无限授权群组使用机器人功能\n"
                f"• ✅ 可授权添加/移除群成员记账权限\n"
                f"• ✅ 有权限群发广播、分组广播\n"
                f"• ✅ 可设置日切时间\n"
                f"• ✅ 有权限设置关键词回复\n\n"
                f"共计：{total_count} 人\n"
                f"👁️ 查看 /USERINFO"
            )
            
            logger.info(f"User {user.id} added admin {target_user_id}")
    except Exception as e:
        logger.error(f"Error in add_admin: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text(
                f"❌ 处理请求时出错：{str(e)}"
            )


async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除管理员"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()
    
    # 检查是否为私聊
    if update.effective_chat.type != 'private':
        await update.message.reply_text(
            "🚫 删除管理员仅限在私聊中使用\n\n"
            "请私聊机器人进行删除操作"
        )
        return
    
    logger.info(f"处理删除管理员命令, 用户: {user.id}")
    
    async for db in get_db():
        # ✅ 使用 PermissionService 检查权限（P0 优化 - 低风险入口接入）
        from src.services.permission_service import permission_service, Permission
        from ..utils.bot_id_middleware import get_current_bot_id
        
        bot_id = get_current_bot_id(context)
        
        if not await permission_service.has_permission(bot_id, user.id, Permission.MANAGE_ADMINS):
            await update.message.reply_text(
                "❌ 权限不足\n\n"
                "只有超级管理员或拥有管理管理员权限的管理员可以删除管理员\n\n"
                "如需删除管理员，请联系超级管理员"
            )
            return
        
        # 获取要删除的用户
        target_user = None
        
        if update.message.reply_to_message and update.message.reply_to_message.from_user:
            target_user = update.message.reply_to_message.from_user
        elif update.message.entities:
            for entity in update.message.entities:
                if entity.type == "text_mention" and entity.user:
                    target_user = entity.user
                    break
        
        # 从文本中提取@username并查找私聊过的用户
        if not target_user:
            match = re.search(r'@(\w+)', text)
            if match:
                target_username = match.group(1)
                logger.info(f"从文本中提取到username: @{target_username}")
                
                private_chat_user = await get_user_by_username(target_username, context)
                
                if private_chat_user:
                    target_user = User(
                        id=private_chat_user.user_id,
                        is_bot=False,
                        first_name=private_chat_user.first_name or target_username,
                        username=private_chat_user.username
                    )
                    logger.info(f"通过username查找到用户: ID={private_chat_user.user_id}, @{target_username}")
        
        if not target_user:
            await update.message.reply_text(
                "❌ 未找到目标用户\n\n"
                "使用方法（任选其一）：\n"
                "1️⃣ 回复该用户的消息后发送「删除管理员」\n"
                "2️⃣ 发送「删除管理员 @username」（该用户必须曾与机器人私聊过）\n\n"
                "💡 提示：\n"
                "• 如果用户从未与机器人私聊过，请先让该用户私聊机器人\n"
                "• 可以通过 /start 命令开始私聊"
            )
            return
        
        target_user_id = target_user.id

        # 检查目标用户是否是超级管理员
        if await is_super_admin(target_user_id, bot_id=bot_id):
            user_display = target_user.first_name or target_user.username or f'ID:{target_user_id}'
            await update.message.reply_text(
                f"⚠️ 无法删除超级管理员 {user_display}\n\n"
                f"超级管理员权限来自系统配置，不能通过此操作删除"
            )
            return

        # 查找管理员
        # ✅ Admin 支持租户隔离
        query = scoped_query(Admin, context).where(
            and_(
                Admin.user_id == target_user_id,
                Admin.is_active.is_(True)
            )
        )
        result = await db.execute(query)
        member = result.scalar_one_or_none()
        
        if not member:
            await update.message.reply_text(
                f"ℹ️ 用户 {target_user.first_name or target_user.username} 不是管理员"
            )
            return
        
        # 删除管理员（设置为非活跃）
        member.is_active = False
        await db.commit()
        
        # ✅ 联动：将该管理员授权的群组标记为 UNAUTHORIZED
        from ..models import Group
        from ..models.enums import GroupStatus
        
        # 查询该管理员授权的所有 ACTIVE 群组
        query = select(Group).where(
            and_(
                Group.bot_id == member.bot_id,  # 租户隔离
                Group.invited_by == target_user_id,
                Group.status == GroupStatus.ACTIVE.value
            )
        )
        result = await db.execute(query)
        authorized_groups = result.scalars().all()
        
        revoked_count = 0
        revoked_groups = []  # 记录被取消授权的群组
        if authorized_groups:
            # 批量更新状态为 UNAUTHORIZED
            for group in authorized_groups:
                group.status = GroupStatus.UNAUTHORIZED.value
                revoked_count += 1
                revoked_groups.append(group)
            
            await db.commit()
            logger.info(f"Revoked {revoked_count} groups authorized by admin {target_user_id}")
        
        # ✅ 发送通知到被取消授权的群组（失败不影响主流程）
        from telegram import Bot
        from config import config
        
        main_bot = Bot(token=config.BOT_TOKEN)
        
        for group in revoked_groups:
            try:
                notice = (
                    f"⚠️ <b>权限变更通知</b>\n\n"
                    f"关联管理员 @{target_user.username or '用户'} 的权限已被取消。\n\n"
                    f"📋 当前状态：\n"
                    f"• 本群已停止记账\n"
                    f"• Bot 功能已被禁用\n\n"
                    f"💡 请联系 Bot 创建者重新授权\n"
                    f"⚠️ 只有授权后，Bot 才能正常使用"
                )
                
                await main_bot.send_message(
                    chat_id=group.group_id,
                    text=notice,
                    parse_mode="HTML"
                )
                logger.info(f"Sent revocation notice to group {group.group_id}")
            except Exception as e:
                # ✅ 通知失败不影响删除管理员的主流程
                logger.error(f"Failed to send notice to group {group.group_id}: {e}")
        
        # 获取管理员总数
        # ✅ Admin 支持租户隔离
        query = scoped_query(Admin, context).where(Admin.is_active.is_(True))
        result = await db.execute(query)
        all_admins = result.scalars().all()
        total_count = len(all_admins)
        
        # 成功提示
        success_msg = f"✅ 已成功删除管理员 @{target_user.username or '用户'}"
        
        if revoked_count > 0:
            success_msg += f"\n\n⚠️ 同时取消了 {revoked_count} 个群组的授权\n"
            success_msg += "这些群组已变为未授权状态，需要重新授权才能使用"
        
        await update.message.reply_text(success_msg)
        
        logger.info(f"User {user.id} removed admin {target_user_id}")


async def show_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示管理员列表

    📌 说明：此列表只显示【已添加的管理员】，不显示【超级管理员】
    超级管理员通过配置(SUPER_ADMIN_ID)识别，拥有所有权限
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    # 检查是否为私聊
    if update.effective_chat.type != 'private':
        await update.message.reply_text(
            "🚫 查看管理员仅限在私聊中使用"
        )
        return

    logger.info(f"处理查看管理员命令, 用户: {user.id}")

    async for db in get_db():
        # 检查操作权限：只有超级管理员或拥有can_manage_admins权限的管理员可以查看管理员列表
        from ..utils.role_checker import is_super_admin
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)

        # 检查是否为超级管理员
        super_admin = await is_super_admin(user.id, bot_id=bot_id)

        if not super_admin:
            # 检查是否为拥有管理管理员权限的管理员
            # ✅ Admin 支持租户隔离
            query = scoped_query(Admin, context).where(
                and_(
                    Admin.user_id == user.id,
                    Admin.is_active.is_(True),
                    Admin.can_manage_admins.is_(True)
                )
            )
            result = await db.execute(query)
            admin_with_permission = result.scalar_one_or_none()

            if not admin_with_permission:
                await update.message.reply_text(
                    "❌ 权限不足\n\n"
                    "只有超级管理员可以查看管理员列表\n\n"
                    "如需查看，请联系超级管理员"
                )
                return

        # 获取所有活跃的管理员（只显示已添加的管理员，不包括超级管理员）
        # ✅ Admin 支持租户隔离
        # 注：超级管理员不在Admin表中，通过配置识别
        query = scoped_query(Admin, context).where(Admin.is_active.is_(True))
        result = await db.execute(query)
        members = result.scalars().all()

        if not members:
            await update.message.reply_text(
                "ℹ️ 当前没有管理员"
            )
            return

        # 构建管理员列表消息（简洁版 - 只显示用户名）
        message = f"👥 管理员（{len(members)}）\n\n"

        for member in members:
            # 优先显示 username，其次 first_name，最后显示 ID
            if member.username:
                name = f"@{member.username}"
            elif member.first_name and member.first_name != "None":
                name = member.first_name
            else:
                name = f"ID:{member.user_id}"
            message += f"• {name}\n"

        await update.message.reply_text(message)


async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看用户信息（管理员可查看所有用户权限信息）"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # ✅ 获取正确的 bot_id（UUID 格式）
    from ..utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    
    async for db in get_db():
        # 检查是否为管理员（✅ Admin 支持租户隔离）
        admin_user = await is_admin_user(user.id, db, bot_id)
        
        if not admin_user:
            await update.message.reply_text(
                "❌ 此功能仅限管理员使用"
            )
            return
        
        # 获取要查询的用户
        target_user = None
        
        if update.message.reply_to_message and update.message.reply_to_message.from_user:
            target_user = update.message.reply_to_message.from_user
        elif update.message.entities:
            for entity in update.message.entities:
                if entity.type == "text_mention" and entity.user:
                    target_user = entity.user
                    break
        
        if not target_user:
            # 查看自己的信息
            target_user = user
        
        target_user_id = target_user.id
        
        # 查询用户是否为管理员
        # ✅ Admin 支持租户隔离，scoped_query 已自动注入 WHERE bot_id = ?
        query = scoped_query(Admin).where(
            and_(
                Admin.user_id == target_user_id,
                Admin.is_active.is_(True)
            )
        )
        result = await db.execute(query)
        internal_member_info = result.scalar_one_or_none()
        
        # 查询用户是否为全局操作人
        query = scoped_query(GroupOperator).where(
            and_(
                GroupOperator.user_id == target_user_id,
                GroupOperator.is_global.is_(True)
            )
        )
        result = await db.execute(query)
        global_operator = result.scalar_one_or_none()
        
        # 查询用户在各群组的操作人身份
        query = scoped_query(GroupOperator).where(
            and_(
                GroupOperator.user_id == target_user_id,
                GroupOperator.is_global.is_(False)
            )
        )
        result = await db.execute(query)
        group_operators = result.scalars().all()
        
        # 格式化显示
        user_display = target_user.first_name or target_user.username or f"ID:{target_user_id}"
        
        message = f" <b>用户信息</b>\n\n"
        message += f"👤 用户名：{user_display}\n"
        message += f"🆔 Telegram ID：{target_user_id}\n\n"
        message += f"🔐 权限信息：\n"
        
        if internal_member_info:
            message += f"• 🌟 内部成员：✅\n"
            message += f"   可创建机器人：{'✅' if internal_member_info.can_create_bot else '❌'}\n"
            message += f"   可管理群成员：{'✅' if internal_member_info.can_manage_group_members else '❌'}\n"
        else:
            message += f"• 🌟 内部成员：❌\n"
        
        if global_operator:
            message += f"• 🌍 全局操作人：✅\n"
        else:
            message += f"• 🌍 全局操作人：❌\n"
        
        if group_operators:
            message += f"•  群组操作人：✅ ({len(group_operators)} 个群组)\n"
        else:
            message += f"• 👥 群组操作人：❌\n"
        
        message += f"\n━━━━━━━━━━━━━━\n"
        message += "💡 提示：\n"
        message += "• 内部成员拥有最高权限\n"
        message += "• 全局操作人可管理所有群组\n"
        message += "• 群组操作人仅可管理指定群组"
        
        await update.message.reply_text(message, parse_mode="HTML")

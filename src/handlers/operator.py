"""
操作人管理处理器

⚠️ DEPRECATED - 旧架构实现
此文件已迁移到新架构,请参考:
- capability_system.py (权限控制: operator:manage)
- ui_schema_registry.py (UI路由)
- repositories/group_operator_repo.py (数据访问)

新功能请使用新架构开发
预计删除时间: 2026-Q3
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models import Group, GroupOperator, get_db
from ..utils.formatter import Formatter
from ..utils.tenant_scope import scoped_query, scoped_insert
from ..utils.permission_checker import require_authorized_group  # 🔐 新增：授权检查装饰器

logger = logging.getLogger(__name__)


async def is_operator(user_id: int, group_id: int, db, context=None) -> bool:
    """
    检查用户是否为操作人（支持租户隔离）
    
    Args:
        user_id: Telegram用户ID
        group_id: 群组ID
        db: 数据库会话
        context: Bot上下文（可选，用于获取bot_id进行租户隔离）
    """
    logger.debug(f"Checking operator permission: user_id={user_id}, group_id={group_id}")
    
    # ✅ 如果提供了 context，获取 bot_id 进行租户隔离检查
    bot_id = None
    if context:
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
    
    # 检查是否为超级管理员（在私聊中自动拥有所有权限）
    from ..utils.role_checker import is_super_admin
    if await is_super_admin(user_id, bot_id=bot_id):
        logger.debug(f"Permission granted: user {user_id} is SUPER_ADMIN")
        return True

    from ..utils.role_checker import get_user_role, UserRole
    if await get_user_role(user_id, group_id, bot_id) == UserRole.BOT_OWNER:
        logger.debug(f"Permission granted: user {user_id} is BOT_OWNER (bot_id={bot_id})")
        return True
    
    # 检查是否为管理员（管理员默认拥有所有群组的操作人权限）
    from ..utils.internal_member_checker import is_admin
    if await is_admin(user_id, bot_id):
        logger.debug(f"Permission granted: user {user_id} is admin (bot_id={bot_id})")
        return True
    
    # 检查群组是否设置全员可操作
    query = scoped_query(Group, context).where(Group.group_id == group_id)
    result = await db.execute(query)
    group = result.scalar_one_or_none()

    if group and group.all_members_operator:
        logger.debug("Permission granted: all_members_operator is True")
        return True

    # 检查是否为群组操作人或全局操作人
    query = scoped_query(GroupOperator, context).where(
        and_(
            GroupOperator.group_id == group_id,
            GroupOperator.user_id == user_id
        )
    )
    result = await db.execute(query)
    operator = result.scalar_one_or_none()

    if operator:
        logger.debug(f"Permission granted: found group operator (group_id={group_id})")
        return True

    # 检查全局操作人
    query = scoped_query(GroupOperator, context).where(
        and_(
            GroupOperator.user_id == user_id,
            GroupOperator.is_global.is_(True)
        )
    )
    result = await db.execute(query)
    global_operator = result.scalar_one_or_none()

    if global_operator:
        logger.debug("Permission granted: found global operator")
        return True
    
    logger.debug("Permission denied: no matching operator found")
    return False


@require_authorized_group  # 🔐 新增：要求群组已授权
async def add_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加操作人 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 获取 bot_id 和检查权限
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..utils.role_checker import get_user_role, UserRole
    
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user.id, chat_id, bot_id)
    
    # 只有 SUPER_ADMIN 和 ADMIN 可以添加操作员
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系群组管理员进行操作。"
        )
        return

    # 解析@提及的用户
    mentioned_users = []

    # 从消息实体中获取提及的用户
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention" and entity.user:
                # text_mention 包含完整的用户信息（回复消息或点击用户名）
                mentioned_users.append({
                    'user_id': entity.user.id,
                    'username': entity.user.username,
                    'first_name': entity.user.first_name
                })
            elif entity.type == "mention":
                # mention 只有用户名（如 @yurong08），需要通过 Telegram API 获取 user_id
                username = update.message.text[entity.offset:entity.offset + entity.length]
                username = username.strip('@')
                if username:
                    mentioned_users.append({'username': username})

    # 如果是回复消息，添加被回复的用户（优先级最高）
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        replied_user = update.message.reply_to_message.from_user
        mentioned_users.append({
            'user_id': replied_user.id,
            'username': replied_user.username,
            'first_name': replied_user.first_name
        })

    if not mentioned_users:
        await update.message.reply_text("❌ 请@用户或回复用户消息来添加操作人")
        return

    async for db in get_db():
        added_count = 0
        failed_count = 0

        for user_info in mentioned_users:
            if isinstance(user_info, str):
                # 只有用户名，无法直接添加
                continue

            user_id = user_info.get('user_id')
            
            # 🆕 如果没有 user_id（只有 username），先尝试从数据库索引查询
            if not user_id and user_info.get('username'):
                from ..repositories.group_member_index_repo import GroupMemberIndexRepo
                from ..utils.bot_id_middleware import get_current_bot_id
                
                bot_id = get_current_bot_id(context)
                if bot_id:
                    # 从数据库查询（bot_id + group_id + username）
                    user_id = await GroupMemberIndexRepo.get_user_id_by_username(
                        db=db,
                        bot_id=bot_id,
                        group_id=chat_id,
                        username=user_info['username']
                    )
                    
                    if user_id:
                        user_info['user_id'] = user_id
                        logger.info(f"✅ 通过数据库索引解析 user_id: @{user_info['username']} -> {user_id}")
                    else:
                        logger.warning(f"❌ 数据库中未找到用户: @{user_info['username']}")
            
            # 如果数据库中没有，再尝试 Telegram API
            if not user_id and user_info.get('username'):
                try:
                    telegram_user = await context.bot.get_chat('@' + user_info['username'])
                    user_id = telegram_user.id
                    user_info['user_id'] = user_id
                    if not user_info.get('first_name'):
                        user_info['first_name'] = telegram_user.first_name
                    logger.info(f"✅ 通过 Telegram API 解析 user_id: @{user_info['username']} -> {user_id}")
                except Exception as e:
                    logger.warning(f"❌ 无法通过 username 获取用户信息: @{user_info['username']}, 错误: {e}")
                    failed_count += 1
                    # 提示用户使用其他方式
                    await update.message.reply_text(
                        f"❌ 无法找到用户 @{user_info['username']}\n\n"
                        f"该用户可能从未与本群 Bot 互动过。\n\n"
                        f"💡 请使用以下方法之一：\n"
                        f"1️⃣ 让该用户在群里发送一条消息\n"
                        f"2️⃣ 点击该用户的用户名（蓝色文字）来添加\n"
                        f"3️⃣ 回复该用户的消息来添加"
                    )
                    return
                        
            if not user_id:
                logger.warning(f"❌ 缺少 user_id，跳过: {user_info}")
                failed_count += 1
                continue

            # 检查是否已存在
            query = scoped_query(GroupOperator, context).where(
                and_(
                    GroupOperator.group_id == chat_id,
                    GroupOperator.user_id == user_id
                )
            )
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if not existing:
                operator = scoped_insert(
                    GroupOperator(
                        group_id=chat_id,
                        user_id=user_id,
                        username=user_info.get('username'),
                        first_name=user_info.get('first_name'),
                        is_global=False
                    ),
                    context
                )
                db.add(operator)
                added_count += 1

        await db.commit()

        if added_count > 0:
            await update.message.reply_text(f"✅ 已添加 {added_count} 个操作人")
        elif failed_count > 0:
            # 已经有错误提示了，这里不再重复
            pass
        else:
            await update.message.reply_text("ℹ️ 用户已经是操作人")


async def remove_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除操作人 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 获取 bot_id 和检查权限
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..utils.role_checker import get_user_role, UserRole
    
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user.id, chat_id, bot_id)
    
    # 只有 SUPER_ADMIN 和 ADMIN 可以删除操作员
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系群组管理员进行操作。"
        )
        return

    # 获取要删除的用户（支持 text_mention 和 mention）
    target_users = []
    target_usernames = []

    # 如果是回复消息
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_users.append(update.message.reply_to_message.from_user.id)

    # 解析@提及的用户
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention" and entity.user:
                # text_mention 包含完整的用户信息（回复消息或点击用户名）
                target_users.append(entity.user.id)
            elif entity.type == "mention":
                # mention 只有用户名（如 @yurong08），需要通过 Telegram API 获取 user_id
                username = update.message.text[entity.offset:entity.offset + entity.length]
                username = username.strip('@')
                if username:
                    target_usernames.append(username)

    if not target_users and not target_usernames:
        await update.message.reply_text("❌ 请@用户或回复用户消息来删除操作人")
        return

    async for db in get_db():
        removed_count = 0

        # 处理有 user_id 的用户
        for user_id in target_users:
            query = scoped_query(GroupOperator, context).where(
                and_(
                    GroupOperator.group_id == chat_id,
                    GroupOperator.user_id == user_id
                )
            )
            result = await db.execute(query)
            operator = result.scalar_one_or_none()

            if operator:
                await db.delete(operator)
                removed_count += 1

        # 处理只有 username 的用户（优先从数据库查询）
        for username in target_usernames:
            user_id = None
                    
            # 🆕 优先从数据库索引查询
            from ..repositories.group_member_index_repo import GroupMemberIndexRepo
                    
            if bot_id:
                user_id = await GroupMemberIndexRepo.get_user_id_by_username(
                    db=db,
                    bot_id=bot_id,
                    group_id=chat_id,
                    username=username
                )
                        
                if user_id:
                    logger.info(f"✅ 通过数据库索引解析 user_id: @{username} -> {user_id}")
                    
            # 如果数据库中没有，再尝试 Telegram API
            if not user_id:
                try:
                    telegram_user = await context.bot.get_chat('@' + username)
                    user_id = telegram_user.id
                    logger.info(f"✅ 通过 Telegram API 解析 user_id: @{username} -> {user_id}")
                except Exception as e:
                    logger.warning(f"❌ 无法通过 username 获取用户信息: @{username}, 错误: {e}")
                    continue
                    
            # 使用 user_id 删除操作人
            if user_id:
                query = scoped_query(GroupOperator, context).where(
                    and_(
                        GroupOperator.group_id == chat_id,
                        GroupOperator.user_id == user_id
                    )
                )
                result = await db.execute(query)
                operator = result.scalar_one_or_none()
        
                if operator:
                    await db.delete(operator)
                    removed_count += 1

        await db.commit()

        if removed_count > 0:
            await update.message.reply_text(f"✅ 已删除 {removed_count} 个操作人")
        else:
            await update.message.reply_text("️ 用户不是操作人")


async def show_operators(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示操作人列表 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    #  获取 bot_id 和检查权限
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..utils.role_checker import get_user_role, UserRole
    
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user.id, chat_id, bot_id)
    
    # 查看操作员需要至少是OPERATOR权限
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系群组管理员或操作员。"
        )
        return

    async for db in get_db():
        # 获取群组操作人
        query = scoped_query(GroupOperator, context).where(
            and_(
                GroupOperator.group_id == chat_id,
                GroupOperator.is_global.is_(False)
            )
        )
        result = await db.execute(query)
        group_operators = result.scalars().all()

        # 获取全局操作人
        query = scoped_query(GroupOperator, context).where(GroupOperator.is_global.is_(True))
        result = await db.execute(query)
        global_operators = result.scalars().all()
        
        # 👤 获取拉 bot 进群的用户（从数据库中的 invited_by 字段）
        chat_creator = None
        try:
            group_query = scoped_query(Group, context).where(Group.group_id == chat_id)
            group_result = await db.execute(group_query)
            group = group_result.scalar_one_or_none()
            
            if group and group.invited_by:
                logger.info(f"✅ 找到邀请者: user_id={group.invited_by}, username={group.invited_by_username}")
                # 从 Telegram API 获取最新信息
                inviter_user = await context.bot.get_chat(group.invited_by)
                chat_creator = inviter_user
            else:
                logger.warning(f"⚠️ 数据库中未找到邀请者信息")
        except Exception as e:
            logger.warning(f"获取邀请者信息失败: {e}")
        
        # 🆕 从 Telegram API 获取用户的最新信息（username/昵称）
        async def get_user_info(user_id: int):
            """从 Telegram 获取用户最新信息"""
            try:
                user = await context.bot.get_chat(user_id)
                return user
            except Exception as e:
                logger.debug(f"获取用户 {user_id} 信息失败: {e}")
                return None
        
        # 更新群组操作人的用户信息（去重）
        enriched_group_operators = []
        seen_user_ids = set()
        for op in group_operators:
            # 去重：只显示群组内添加的操作人
            if op.user_id in seen_user_ids:
                logger.info(f"跳过重复操作人: {op.user_id}")
                continue
            
            seen_user_ids.add(op.user_id)
            
            user_info = await get_user_info(op.user_id)
            if user_info:
                # 创建一个包含最新信息的对象
                enriched_op = type('EnrichedOperator', (), {
                    'user_id': op.user_id,
                    'username': user_info.username,
                    'first_name': user_info.first_name,
                    'last_name': user_info.last_name
                })()
                enriched_group_operators.append(enriched_op)
            else:
                enriched_group_operators.append(op)
        
        # 更新全局操作人的用户信息
        enriched_global_operators = []
        for op in global_operators:
            user_info = await get_user_info(op.user_id)
            if user_info:
                enriched_op = type('EnrichedOperator', (), {
                    'user_id': op.user_id,
                    'username': user_info.username,
                    'first_name': user_info.first_name,
                    'last_name': user_info.last_name
                })()
                enriched_global_operators.append(enriched_op)
            else:
                enriched_global_operators.append(op)

        # 格式化显示（传入邀请者信息和更新后的操作人列表）
        # 如果获取不到邀请者，使用第一个全局操作人作为主管理员（备用方案）
        if not chat_creator and enriched_global_operators:
            chat_creator = enriched_global_operators[0]
            logger.info(f"✅ 使用全局操作人作为主管理员（备用）: {chat_creator.username or chat_creator.first_name}")
        
        message = Formatter.format_operators(enriched_group_operators, enriched_global_operators, chat_creator)

        # 检查是否全员可操作
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group and group.all_members_operator:
            message += "\n\n⚠️ 当前设置为全员可操作"

        await update.message.reply_text(message, parse_mode="HTML")


async def enable_all_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置全员可操作 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 获取 bot_id 和检查权限
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..utils.role_checker import get_user_role, UserRole
    
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user.id, chat_id, bot_id)
    
    # 只有 SUPER_ADMIN 和 ADMIN 可以设置全员
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系群组管理员进行操作。"
        )
        return

    async for db in get_db():
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            group.all_members_operator = True
            await db.commit()
            await update.message.reply_text("✅  已开启全员记账模式，群内所有人均可记账。")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def disable_all_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消全员可操作 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 获取 bot_id 和检查权限
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..utils.role_checker import get_user_role, UserRole
    
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user.id, chat_id, bot_id)
    
    # 只有 SUPER_ADMIN 和 ADMIN 可以取消全员
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系群组管理员进行操作。"
        )
        return

    async for db in get_db():
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            group.all_members_operator = False
            await db.commit()
            await update.message.reply_text("✅ 已关闭全员记账模式，仅限管理员和操作员记账。")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def add_global_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加全局操作人 - 支持 @username 解析"""
    if not update.message or not update.effective_user:
        return

    # 检查是否为超级管理员
    from ..utils.role_checker import is_super_admin
    if not await is_super_admin(update.effective_user.id):
        await update.message.reply_text("❌ 只有超级管理员可以添加全局操作人")
        return

    # 获取要添加的用户（支持 reply、text_mention、mention）
    target_user = None
    target_username = None
    chat_id = update.effective_chat.id if update.effective_chat else None

    # 如果是回复消息
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user = update.message.reply_to_message.from_user
    elif update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention" and entity.user:
                # text_mention 包含完整的用户信息（回复消息或点击用户名）
                target_user = entity.user
                break
            elif entity.type == "mention":
                # mention 只有用户名（如 @xiaomingjz），需要从数据库或 Telegram API 获取 user_id
                username = update.message.text[entity.offset:entity.offset + entity.length]
                username = username.strip('@')
                if username:
                    target_username = username
                    break

    if not target_user and not target_username:
        await update.message.reply_text("❌ 请@用户或回复用户消息")
        return

    async for db in get_db():
        # 如果只有 username，先尝试从数据库查询 user_id
        if not target_user and target_username:
            from ..utils.bot_id_middleware import get_current_bot_id
            from ..repositories.group_member_index_repo import GroupMemberIndexRepo
            
            bot_id = get_current_bot_id(context)
            user_id = None
            
            if bot_id and chat_id:
                # 优先从数据库查询
                user_id = await GroupMemberIndexRepo.get_user_id_by_username(
                    db=db,
                    bot_id=bot_id,
                    group_id=chat_id,
                    username=target_username
                )
            
            # 如果数据库中没有，再尝试 Telegram API
            if not user_id:
                try:
                    telegram_user = await context.bot.get_chat('@' + target_username)
                    user_id = telegram_user.id
                    target_user = telegram_user
                    logger.info(f"✅ 通过 Telegram API 解析 user_id: @{target_username} -> {user_id}")
                except Exception as e:
                    logger.warning(f"❌ 无法通过 username 获取用户信息: @{target_username}, 错误: {e}")
                    await update.message.reply_text(
                        f"❌ 无法找到用户 @{target_username}\n\n"
                        f"该用户可能从未与本群 Bot 互动过。\n\n"
                        f"💡 请使用以下方法之一：\n"
                        f"1️⃣ 让该用户在群里发送一条消息\n"
                        f"2️ 点击该用户的用户名（蓝色文字）来添加\n"
                        f"3️ 回复该用户的消息来添加"
                    )
                    return
            else:
                logger.info(f"✅ 通过数据库索引解析 user_id: @{target_username} -> {user_id}")
                # 从数据库获取用户信息后，需要构造一个类似 User 的对象
                from telegram import User
                target_user = User(id=user_id, is_bot=False, first_name=target_username)
        
        # 检查是否已存在
        query = scoped_query(GroupOperator, context).where(
            and_(
                GroupOperator.user_id == target_user.id,
                GroupOperator.is_global.is_(True)
            )
        )
        result = await db.execute(query)
        existing = result.scalar_one_or_none()

        if existing:
            await update.message.reply_text("ℹ️ 用户已经是全局操作人")
            return

        # 添加全局操作人
        operator = scoped_insert(
            GroupOperator(
                group_id=0,  # 全局操作人group_id为0
                user_id=target_user.id,
                username=target_user.username,
                first_name=target_user.first_name,
                is_global=True
            ),
            context
        )
        db.add(operator)
        await db.commit()

        await update.message.reply_text(f"✅ 已添加 {target_user.first_name or target_user.username} 为全局操作人")


async def remove_global_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除全局操作人 - 支持 @username 解析"""
    if not update.message or not update.effective_user:
        return

    # 检查是否为超级管理员
    from ..utils.role_checker import is_super_admin
    if not await is_super_admin(update.effective_user.id):
        await update.message.reply_text("❌ 只有超级管理员可以删除全局操作人")
        return

    # 获取要删除的用户（支持 reply、text_mention、mention）
    target_user = None
    target_username = None
    chat_id = update.effective_chat.id if update.effective_chat else None

    # 如果是回复消息
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user = update.message.reply_to_message.from_user
    elif update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention" and entity.user:
                # text_mention 包含完整的用户信息（回复消息或点击用户名）
                target_user = entity.user
                break
            elif entity.type == "mention":
                # mention 只有用户名（如 @xiaomingjz），需要从数据库或 Telegram API 获取 user_id
                username = update.message.text[entity.offset:entity.offset + entity.length]
                username = username.strip('@')
                if username:
                    target_username = username
                    break

    if not target_user and not target_username:
        await update.message.reply_text("❌ 请@用户或回复用户消息")
        return

    async for db in get_db():
        user_id = None
        
        # 如果有完整的用户信息，直接使用
        if target_user:
            user_id = target_user.id
        elif target_username:
            # 如果只有 username，先尝试从数据库查询 user_id
            from ..utils.bot_id_middleware import get_current_bot_id
            from ..repositories.group_member_index_repo import GroupMemberIndexRepo
            
            bot_id = get_current_bot_id(context)
            
            if bot_id and chat_id:
                # 优先从数据库查询
                user_id = await GroupMemberIndexRepo.get_user_id_by_username(
                    db=db,
                    bot_id=bot_id,
                    group_id=chat_id,
                    username=target_username
                )
            
            # 如果数据库中没有，再尝试 Telegram API
            if not user_id:
                try:
                    telegram_user = await context.bot.get_chat('@' + target_username)
                    user_id = telegram_user.id
                    logger.info(f"✅ 通过 Telegram API 解析 user_id: @{target_username} -> {user_id}")
                except Exception as e:
                    logger.warning(f"❌ 无法通过 username 获取用户信息: @{target_username}, 错误: {e}")
                    await update.message.reply_text(
                        f"❌ 无法找到用户 @{target_username}\n\n"
                        f"该用户可能从未与本群 Bot 互动过。\n\n"
                        f"💡 请使用以下方法之一：\n"
                        f"1️ 让该用户在群里发送一条消息\n"
                        f"2️ 点击该用户的用户名（蓝色文字）来添加\n"
                        f"3️ 回复该用户的消息来添加"
                    )
                    return
            else:
                logger.info(f"✅ 通过数据库索引解析 user_id: @{target_username} -> {user_id}")
        
        if not user_id:
            await update.message.reply_text("❌ 无法获取用户 ID")
            return
        
        # 查询是否存在全局操作人记录
        query = scoped_query(GroupOperator, context).where(
            and_(
                GroupOperator.user_id == user_id,
                GroupOperator.is_global.is_(True)
            )
        )
        result = await db.execute(query)
        operator = result.scalar_one_or_none()

        if operator:
            await db.delete(operator)
            await db.commit()
            await update.message.reply_text(f"✅ 已删除 1 位全局操作人。")
        else:
            await update.message.reply_text("ℹ️ 用户不是全局操作人")


async def show_global_operators(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示全局操作人 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    
    # 🆕 获取 bot_id 和检查权限
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..utils.role_checker import get_user_role, UserRole
    
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user.id, None, bot_id)  # 私聊，group_id=None
    
    # 只有 SUPER_ADMIN 和 ADMIN 可以查看全局操作员
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系超级管理员或管理员。"
        )
        return

    async for db in get_db():
        query = scoped_query(GroupOperator, context).where(GroupOperator.is_global.is_(True))
        result = await db.execute(query)
        global_operators = result.scalars().all()
        
        # 🆕 从 Telegram API 获取用户的最新信息（username/昵称）
        async def get_user_info(user_id: int):
            """从 Telegram 获取用户最新信息"""
            try:
                user = await context.bot.get_chat(user_id)
                return user
            except Exception as e:
                logger.debug(f"获取用户 {user_id} 信息失败: {e}")
                return None
        
        # 更新全局操作人的用户信息
        enriched_global_operators = []
        for op in global_operators:
            user_info = await get_user_info(op.user_id)
            if user_info:
                enriched_op = type('EnrichedOperator', (), {
                    'user_id': op.user_id,
                    'username': user_info.username,
                    'first_name': user_info.first_name,
                    'last_name': user_info.last_name
                })()
                enriched_global_operators.append(enriched_op)
            else:
                enriched_global_operators.append(op)

        # 格式化全局操作人列表（使用专用格式）
        if not enriched_global_operators:
            message = "🌐 您的全局操作人列表：\n\n暂无全局操作人"
        else:
            lines = ["🌐 您的全局操作人列表：", ""]
            for i, op in enumerate(enriched_global_operators, 1):
                if op.username:
                    user_display = f"@{op.username}"
                elif op.first_name:
                    user_display = op.first_name
                else:
                    user_display = f"用户{op.user_id}"
                lines.append(f"{i}. {user_display}")
            
            lines.append("")
            lines.append("这些用户可以在您管理的所有群组中进行记账操作。")
            message = "\n".join(lines)
        
        await update.message.reply_text(message, parse_mode="HTML")

"""
群组成员更名检测通知处理器

当群组成员更改用户名（first_name、last_name 或 username）时，
在群组中发送通知消息提醒其他成员。

功能：
1. Bot进入群后，自动缓存当前群所有管理员/群主的昵称到数据库
2. 监听群内用户昵称变更事件
3. 当用户修改昵称时，检查新昵称是否与管理员列表中的昵称完全一致
4. 如果一致，且该用户本身不是管理员/群主，则判定为冒充
5. 发送冒充提醒消息
6. 功能由「冒充管理员监测」开关控制

注意：需要 Bot 是群管理员才能收到 chat_member 事件
"""
import logging
from telegram import Update, ChatMemberUpdated
from telegram.ext import ContextTypes, ChatMemberHandler, MessageHandler, filters, CommandHandler
from sqlalchemy import select, and_, delete

from ..services.global_config_service import global_config_service
from ..utils.bot_id_middleware import get_current_bot_id
from ..models import get_db_session, ImpersonationWhitelist, AdminNicknameCache

logger = logging.getLogger(__name__)


async def handle_member_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群组成员更名事件（🆕 增强版：包含防骗警告）

    监听 Telegram 的 chat_member 事件，检测用户名称变更
    根据图1格式显示：用户ID、用户名变更、昵称变更、防骗警告
    """
    if not update.chat_member:
        logger.debug("No chat_member in update, skipping")
        return

    chat_member_update: ChatMemberUpdated = update.chat_member
    new_status = chat_member_update.new_chat_member.status
    old_status = chat_member_update.old_chat_member.status

    chat_id = chat_member_update.chat.id
    user = chat_member_update.new_chat_member.user
    old_user = chat_member_update.old_chat_member.user

    bot_id = get_current_bot_id(context)

    # 检测是否是 Bot 加入群组的事件
    if user.is_bot and new_status in ['member', 'administrator'] and old_status == 'left':
        logger.info(f"🤖 Bot {bot_id} joined group {chat_id}, caching admin nicknames...")
        await _cache_admin_nicknames(context, chat_id, bot_id)
        return

    # 检测是否是 Bot 被移除群组的事件
    if user.is_bot and new_status == 'left':
        logger.info(f"🤖 Bot removed from group {chat_id}, clearing admin cache...")
        await _clear_admin_cache(bot_id, chat_id)
        return

    # 只处理已经是成员的用户的状态变化（排除新加入/离开的情况）
    if new_status not in ['member', 'administrator', 'creator']:
        return

    if old_status not in ['member', 'administrator', 'creator']:
        return

    # 忽略机器人自己
    if user.is_bot:
        return

    # 检测名称是否发生变化
    old_name = old_user.first_name or ""
    new_name = user.first_name or ""
    old_username = old_user.username or ""
    new_username = user.username or ""

    name_changed = old_name != new_name
    username_changed = old_username != new_username

    # 如果没有任何变化，直接返回
    if not name_changed and not username_changed:
        return

    logger.info(
        f"📝 Member renamed in group {chat_id}: "
        f"{old_name}(@{old_username}) -> {new_name}(@{new_username})"
    )

    # 检查是否启用了监听昵称变更或用户名变更
    async with get_db_session() as db:
        try:
            # 获取三个功能的配置
            nickname_enabled = await global_config_service.get_config(
                db, bot_id, "nickname_monitor_enabled"
            )
            username_enabled = await global_config_service.get_config(
                db, bot_id, "username_monitor_enabled"
            )
            impersonation_enabled = await global_config_service.get_config(
                db, bot_id, "impersonation_detection_enabled"
            )

            nickname_on = nickname_enabled if isinstance(nickname_enabled, bool) else False
            username_on = username_enabled if isinstance(username_enabled, bool) else False
            impersonation_on = impersonation_enabled if isinstance(impersonation_enabled, bool) else False

            # 如果没有启用任何功能，直接返回
            if not nickname_on and not username_on and not impersonation_on:
                logger.debug(f"All group member monitoring is disabled for bot {bot_id}")
                return

            # 根据启用的功能发送通知
            # 1. 监听用户名变更
            if username_on and username_changed:
                notification_lines = []
                notification_lines.append("📢 <b>用户名变更提醒</b>")
                notification_lines.append("")
                notification_lines.append(f"用户ID: <code>{user.id}</code>")
                old_user_display = f"@{old_username}" if old_username else "无"
                new_user_display = f"@{new_username}" if new_username else "无"
                notification_lines.append(f"旧用户名: {old_user_display}")
                notification_lines.append(f"新用户名: {new_user_display}")
                notification_lines.append(f"群: {chat_member_update.chat.title or '未知群组'}")
                from datetime import datetime
                notification_lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

                notification_text = "\n".join(notification_lines)

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=notification_text,
                    parse_mode="HTML"
                )

            # 2. 监听昵称变更
            if nickname_on and name_changed:
                notification_lines = []
                notification_lines.append("📢 <b>昵称变更提醒</b>")
                notification_lines.append("")
                notification_lines.append(f"用户ID: <code>{user.id}</code>")
                notification_lines.append(f"旧昵称: {old_name or '无'}")
                notification_lines.append(f"新昵称: {new_name or '无'}")
                notification_lines.append(f"群: {chat_member_update.chat.title or '未知群组'}")
                from datetime import datetime
                notification_lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

                notification_text = "\n".join(notification_lines)

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=notification_text,
                    parse_mode="HTML"
                )

            # 3. 冒充管理员监测（🆕 严格模式：只检测昵称完全一致）
            if impersonation_on:
                is_impersonation = await _check_name_impersonation(
                    context, db, chat_id, user.id, bot_id, new_name
                )
            else:
                is_impersonation = False

            if is_impersonation:
                warning_text = (
                    f"⚠️ 冒充管理员提醒：\n\n"
                    f"用户 {user.mention_html(new_name) if new_name else user.id} "
                    f"将昵称改为「{new_name}」，与真实管理员昵称完全一致，"
                    f"请不要冒充管理员！"
                )

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=warning_text,
                    parse_mode="HTML"
                )

            logger.info(f"✅ Sent rename notification to group {chat_id}")

        except Exception as e:
            logger.error(f"Failed to send rename notification: {e}", exc_info=True)


async def handle_impersonation_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群内普通消息的冒充管理员监测。

    Telegram 不会为每条消息触发 chat_member 更新，所以“非管理员发言伪装成管理员”
    必须在群消息流里检查。配置仍使用当前 bot_id 下的全局开关，保证子 Bot 隔离。
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup") or user.is_bot:
        return

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        try:
            enabled = await global_config_service.get_config(
                db, bot_id, "impersonation_detection_enabled"
            )
        except Exception as e:
            logger.error(f"Failed to read impersonation config: {e}", exc_info=True)
            return

    if not (enabled if isinstance(enabled, bool) else False):
        return

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in ("administrator", "creator", "owner"):
            return
    except Exception as e:
        logger.debug(f"Failed to get chat member status for {user.id}: {e}")

    new_username = user.username or ""
    new_name = user.first_name or ""

    is_suspicious, impersonated_admin = await _check_suspicious_rename(
        context,
        chat.id,
        user.id,
        bot_id,
        "",
        new_username,
        "",
        new_name,
    )

    if not is_suspicious:
        return

    import time
    cooldown_key = f"impersonation_warn:{bot_id}:{chat.id}:{user.id}"
    now = time.time()
    last_warned_at = context.bot_data.get(cooldown_key, 0)
    if now - last_warned_at < 600:
        return
    context.bot_data[cooldown_key] = now

    warning_lines = [
        "⚠️ <b>冒充管理员警报</b>",
        "",
        f"群: {chat.title or '未知群组'}",
        f"用户ID: <code>{user.id}</code>",
        f"昵称: {new_name or '无'}",
        f"用户名: @{new_username}" if new_username else "用户名: 无",
        "状态: 非管理员",
        "风险: 疑似冒充管理员，请警惕诈骗！",
    ]

    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        admin_mentions = []
        for admin in admins:
            if admin.user.is_bot:
                continue
            if impersonated_admin and admin.user.username and admin.user.username.lower() == impersonated_admin.lower():
                admin_mentions.insert(0, f"@{admin.user.username}")
            elif admin.user.username:
                admin_mentions.append(f"@{admin.user.username}")
            else:
                admin_mentions.append(f"<a href='tg://user?id={admin.user.id}'>{admin.user.first_name}</a>")
        if admin_mentions:
            warning_lines.append(" ".join(admin_mentions[:5]))
    except Exception as e:
        logger.error(f"Failed to get admins for impersonation warning: {e}")

    warning_lines.extend([
        "",
        "误报处理，使用指令添加白名单:",
        f"<code>设置白名单 @{new_username}</code>" if new_username else f"<code>设置白名单 {user.id}</code>",
    ])

    try:
        await update.message.reply_text(
            "\n".join(warning_lines),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Failed to send impersonation warning: {e}", exc_info=True)


async def _check_suspicious_rename(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    bot_id: str,
    old_username: str,
    new_username: str,
    old_name: str,
    new_name: str
) -> tuple[bool, str | None]:
    """
    检查更名是否可疑（可能是诈骗行为）

    检测规则：
    1. 更改为包含"admin"、"客服"、"官方"等关键词的用户名
    2. 更改为与现有管理员相似的用户名
    3. 检查用户是否在白名单中

    Returns:
        tuple[bool, str | None]: (是否可疑, 被冒充的管理员用户名)
    """
    try:
        # 首先检查白名单（同时匹配 user_id 或 username）
        async with get_db_session() as db:
            # 检查 user_id
            whitelist_result = await db.execute(
                select(ImpersonationWhitelist).where(
                    ImpersonationWhitelist.bot_id == bot_id,
                    ImpersonationWhitelist.user_id == user_id
                )
            )
            whitelist_entry = whitelist_result.scalar_one_or_none()
            if whitelist_entry:
                logger.info(f"User {user_id} is in impersonation whitelist, skipping check")
                return False, None
            
            # 检查 username（如果提供了用户名）
            if new_username:
                whitelist_result = await db.execute(
                    select(ImpersonationWhitelist).where(
                        ImpersonationWhitelist.bot_id == bot_id,
                        ImpersonationWhitelist.username == new_username.lower()
                    )
                )
                whitelist_entry = whitelist_result.scalar_one_or_none()
                if whitelist_entry:
                    logger.info(f"User @{new_username} is in impersonation whitelist, skipping check")
                    return False, None

        # 获取群组管理员列表
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
        except Exception as e:
            logger.error(f"Failed to get admins: {e}")
            return False, None

        # 构建管理员信息列表
        admin_usernames = []
        admin_names = []
        for admin in admins:
            if not admin.user.is_bot:
                if admin.user.username:
                    admin_usernames.append(admin.user.username.lower())
                admin_names.append(admin.user.first_name.lower())

        new_username_lower = (new_username or "").lower()
        new_name_lower = (new_name or "").lower()

        # 规则1: 检查是否直接使用了管理员的用户名（完全匹配）
        if new_username_lower and new_username_lower in admin_usernames:
            logger.warning(f"🚨 Impersonation detected: user {user_id} changed to admin username @{new_username}")
            return True, new_username

        # 规则2: 检查是否使用了管理员的昵称（完全匹配）
        if new_name_lower and new_name_lower in admin_names:
            logger.warning(f"🚨 Impersonation detected: user {user_id} changed to admin name {new_name}")
            return True, None

        # 规则3: 检查用户名相似度（编辑距离）
        if new_username_lower:
            for admin_username in admin_usernames:
                if _is_similar_username(new_username_lower, admin_username):
                    logger.warning(f"🚨 Similar username detected: user {user_id} (@{new_username}) similar to admin @{admin_username}")
                    return True, admin_username

        # 规则4: 检查昵称相似度
        if new_name_lower:
            for admin_name in admin_names:
                if _is_similar_name(new_name_lower, admin_name):
                    logger.warning(f"🚨 Similar name detected: user {user_id} ({new_name}) similar to admin {admin_name}")
                    return True, None

        # 规则5: 检查敏感关键词
        suspicious_keywords = ['admin', '客服', '官方', '管理', '助手', 'help', 'support', 'service', 'owner', 'creator']
        for keyword in suspicious_keywords:
            if keyword in new_username_lower or keyword in new_name_lower:
                logger.warning(f"🚨 Suspicious keyword detected: user {user_id} used keyword '{keyword}'")
                return True, None

        return False, None

    except Exception as e:
        logger.error(f"Error in suspicious rename check: {e}")
        return False, None


def _is_similar_username(username1: str, username2: str) -> bool:
    """
    检查两个用户名是否相似（简单的相似度检测）

    检测规则：
    1. 一个包含另一个
    2. 编辑距离较小（允许1-2个字符的差异）
    """
    if not username1 or not username2:
        return False

    # 完全包含
    if username1 in username2 or username2 in username1:
        return True

    # 简单的编辑距离检测（Levenshtein distance）
    # 如果长度差异太大，不可能是相似的
    if abs(len(username1) - len(username2)) > 2:
        return False

    # 计算编辑距离
    distance = _levenshtein_distance(username1, username2)

    # 如果编辑距离小于等于2，认为是相似的
    return distance <= 2


def _is_similar_name(name1: str, name2: str) -> bool:
    """
    检查两个昵称是否相似

    检测规则：
    1. 完全包含
    2. 编辑距离较小
    3. 长度大于3才进行比较（避免误判短昵称）
    """
    if not name1 or not name2:
        return False

    # 短昵称不进行比较（避免误判）
    if len(name1) < 3 or len(name2) < 3:
        return False

    # 完全包含
    if name1 in name2 or name2 in name1:
        return True

    # 如果长度差异太大，不可能是相似的
    if abs(len(name1) - len(name2)) > 2:
        return False

    # 计算编辑距离
    distance = _levenshtein_distance(name1, name2)

    # 如果编辑距离小于等于2，认为是相似的
    return distance <= 2


def _levenshtein_distance(s1: str, s2: str) -> int:
    """
    计算两个字符串的编辑距离（Levenshtein distance）
    """
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


async def _cache_admin_nicknames(context: ContextTypes.DEFAULT_TYPE, chat_id: int, bot_id: str):
    """
    缓存群组管理员昵称到数据库

    Args:
        context: Telegram Context
        chat_id: 群组ID
        bot_id: Bot实例ID
    """
    try:
        # 获取群组管理员列表
        admins = await context.bot.get_chat_administrators(chat_id)

        async with get_db_session() as db:
            # 先清除旧缓存
            await db.execute(
                delete(AdminNicknameCache).where(
                    and_(
                        AdminNicknameCache.bot_id == bot_id,
                        AdminNicknameCache.group_id == chat_id
                    )
                )
            )

            # 插入新的管理员昵称
            for admin in admins:
                if not admin.user.is_bot:
                    admin_nickname_cache = AdminNicknameCache(
                        bot_id=bot_id,
                        group_id=chat_id,
                        admin_user_id=admin.user.id,
                        admin_username=admin.user.username,
                        admin_nickname=admin.user.first_name or "",
                        admin_status=admin.status.value if hasattr(admin.status, 'value') else str(admin.status)
                    )
                    db.add(admin_nickname_cache)

            await db.commit()

        logger.info(f"✅ Cached {len([a for a in admins if not a.user.is_bot])} admin nicknames for group {chat_id}")

    except Exception as e:
        logger.error(f"Failed to cache admin nicknames: {e}", exc_info=True)


async def refresh_all_groups_admin_cache(bot, bot_id: str) -> int:
    """
    刷新所有群组的管理员昵称缓存

    Args:
        bot: Telegram Bot 实例
        bot_id: Bot实例ID

    Returns:
        int: 刷新缓存的群组数量
    """
    try:
        # 获取所有有效的群组
        async with get_db_session() as db:
            from sqlalchemy import select
            from ..models import Group
            query = select(Group.group_id).where(Group.bot_id == bot_id)
            result = await db.execute(query)
            groups = result.scalars().all()

        logger.info(f"Found {len(groups)} groups to refresh admin cache")

        # 为每个群组刷新缓存
        refreshed_count = 0
        for group_id in groups:
            try:
                # 创建一个临时的 context-like 对象
                class TempContext:
                    bot = bot

                temp_context = TempContext()
                await _cache_admin_nicknames(temp_context, group_id, bot_id)
                refreshed_count += 1
            except Exception as e:
                logger.warning(f"Failed to refresh admin cache for group {group_id}: {e}")

        return refreshed_count

    except Exception as e:
        logger.error(f"Failed to refresh all groups admin cache: {e}", exc_info=True)
        return 0


async def _clear_admin_cache(bot_id: str, chat_id: int):
    """
    清除群组管理员缓存

    Args:
        bot_id: Bot实例ID
        chat_id: 群组ID
    """
    try:
        async with get_db_session() as db:
            await db.execute(
                delete(AdminNicknameCache).where(
                    and_(
                        AdminNicknameCache.bot_id == bot_id,
                        AdminNicknameCache.group_id == chat_id
                    )
                )
            )
            await db.commit()

        logger.info(f"✅ Cleared admin cache for group {chat_id}")

    except Exception as e:
        logger.error(f"Failed to clear admin cache: {e}", exc_info=True)


async def _check_name_impersonation(
    context: ContextTypes.DEFAULT_TYPE,
    db,
    chat_id: int,
    user_id: int,
    bot_id: str,
    new_name: str
) -> bool:
    """
    检查是否冒充管理员昵称（严格模式：只检测昵称完全一致）

    Args:
        context: Telegram Context
        db: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID
        bot_id: Bot实例ID
        new_name: 新昵称

    Returns:
        bool: 是否冒充
    """
    try:
        # 首先检查该用户是否是管理员（如果是，则不算冒充）
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ('administrator', 'creator', 'owner'):
                logger.debug(f"User {user_id} is admin, skipping impersonation check")
                return False
        except Exception as e:
            logger.debug(f"Failed to check user admin status: {e}")

        # 检查白名单
        whitelist_result = await db.execute(
            select(ImpersonationWhitelist).where(
                and_(
                    ImpersonationWhitelist.bot_id == bot_id,
                    ImpersonationWhitelist.user_id == user_id
                )
            )
        )
        whitelist_entry = whitelist_result.scalar_one_or_none()
        if whitelist_entry:
            logger.info(f"User {user_id} is in impersonation whitelist, skipping check")
            return False

        # 从数据库缓存中获取管理员昵称列表
        cached_admins_result = await db.execute(
            select(AdminNicknameCache).where(
                and_(
                    AdminNicknameCache.bot_id == bot_id,
                    AdminNicknameCache.group_id == chat_id
                )
            )
        )
        cached_admins = cached_admins_result.scalars().all()

        # 如果缓存为空，尝试重新获取
        if not cached_admins:
            logger.warning(f"Admin cache is empty for group {chat_id}, refreshing...")
            await _cache_admin_nicknames(context, chat_id, bot_id)

            # 重新查询
            cached_admins_result = await db.execute(
                select(AdminNicknameCache).where(
                    and_(
                        AdminNicknameCache.bot_id == bot_id,
                        AdminNicknameCache.group_id == chat_id
                    )
                )
            )
            cached_admins = cached_admins_result.scalars().all()

        # 检查新昵称是否与缓存的管理员昵称完全一致
        new_name_lower = (new_name or "").lower().strip()
        for admin_cache in cached_admins:
            if admin_cache.admin_nickname and admin_cache.admin_nickname.lower().strip() == new_name_lower:
                # 检查该管理员是否还在群里（可能被移除）
                try:
                    current_admin = await context.bot.get_chat_member(chat_id, admin_cache.admin_user_id)
                    if current_admin.status in ('administrator', 'creator', 'owner'):
                        logger.warning(f"🚨 Impersonation detected: user {user_id} changed name to admin nickname '{new_name}'")
                        return True
                except Exception as e:
                    logger.debug(f"Failed to verify admin status: {e}")

        return False

    except Exception as e:
        logger.error(f"Error in name impersonation check: {e}", exc_info=True)
        return False


async def handle_refresh_admin_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    手动刷新管理员缓存命令处理器

    命令格式：/refreshadmins
    """
    if not update.message or not update.effective_chat:
        return

    chat = update.effective_chat
    bot_id = get_current_bot_id(context)

    # 只有群组才需要刷新缓存
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("此命令仅限群组使用")
        return

    logger.info(f"Manual admin cache refresh requested for group {chat.id}")

    # 刷新缓存
    await _cache_admin_nicknames(context, chat.id, bot_id)

    # 获取缓存的统计信息
    async with get_db_session() as db:
        cached_admins_result = await db.execute(
            select(AdminNicknameCache).where(
                and_(
                    AdminNicknameCache.bot_id == bot_id,
                    AdminNicknameCache.group_id == chat.id
                )
            )
        )
        cached_admins = cached_admins_result.scalars().all()

    await update.message.reply_text(
        f"✅ 管理员昵称缓存已刷新\n\n"
        f"群组: {chat.title}\n"
        f"已缓存: {len(cached_admins)} 位管理员昵称\n\n"
        f"提示: Bot重启后会自动刷新所有群组的管理员缓存"
    )


def register_member_rename_handler(application):
    """
    注册群组成员更名检测处理器

    Args:
        application: Telegram Application 实例
    """
    handler = ChatMemberHandler(handle_member_rename, ChatMemberHandler.CHAT_MEMBER)
    application.add_handler(handler)

    # 添加手动刷新缓存命令
    refresh_handler = CommandHandler("refreshadmins", handle_refresh_admin_cache)
    application.add_handler(refresh_handler)

    logger.info("✅ Member rename notification handler registered")

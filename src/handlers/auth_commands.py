"""
授权管理命令处理器（独立插件 - 不影响现有功能）

功能：
1. 超管私聊发送 "授权 +群组ID" 手动授权群组
2. 超管私聊发送 "取消授权 +群组ID" 删除授权
3. 查询群组授权状态

⚠️ 注意：这些命令仅在 AUTHORIZATION_ENABLED=True 时生效
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from ..services.authorization_service import authorization_service, AUTHORIZATION_ENABLED
from ..utils.role_checker import get_user_role, UserRole
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)


async def cmd_authorize_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    超管手动授权群组
    
    用法：/authorize -1001234567890
    或：授权 -1001234567890
    """
    # 🛡️ 安全检查：如果功能未启用，直接返回
    if not AUTHORIZATION_ENABLED:
        logger.debug("️ 授权系统未启用，跳过命令处理")
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    # 仅允许私聊
    if chat.type != 'private':
        await update.message.reply_text("❌ 此命令仅支持在私聊中使用")
        return
    
    bot_id = get_current_bot_id(context)
    
    # 检查用户是否为超管或管理员
    role = await get_user_role(user.id, None, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text("❌ 仅超级管理员或管理员可以使用此命令")
        return
    
    # 解析群组 ID
    text = update.message.text.strip()
    
    # 支持两种格式：/authorize -100xxx 或 授权 -100xxx
    if text.startswith('/authorize'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ 用法错误\n\n"
                "正确用法：\n"
                "/authorize -1001234567890\n"
                "或\n"
                "授权 -1001234567890"
            )
            return
        chat_id_str = parts[1].strip()
    elif text.startswith('授权'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ 用法错误\n\n"
                "正确用法：授权 -1001234567890"
            )
            return
        chat_id_str = parts[1].strip()
    else:
        return  # 不匹配，让其他 handler 处理
    
    # 转换为整数
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        await update.message.reply_text(f"❌ 无效的群组 ID: {chat_id_str}")
        return
    
    # 执行授权
    success, message = await authorization_service.manual_authorize_group(
        chat_id=chat_id,
        bot_id=bot_id,
        authorized_by=user.id,
        context=context
    )
    
    await update.message.reply_text(message, parse_mode='HTML')



async def cmd_deauthorize_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    超管取消授权群组（删除授权）
    
    用法：/deauthorize -1001234567890
    或：取消授权 -1001234567890
    """
    # 🔵 安全检查：如果功能未启用，直接返回
    if not AUTHORIZATION_ENABLED:
        logger.debug("⏭️ 授权系统未启用，跳过命令处理")
        return
        
    user = update.effective_user
    chat = update.effective_chat
        
    # 解析群组 ID
    text = update.message.text.strip()
    chat_id_str = None
        
    # 支持两种格式：/deauthorize -100xxx 或 取消授权 -100xxx
    if text.startswith('/deauthorize'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ 用法错误\n\n"
                "正确用法：\n"
                "/deauthorize -1001234567890\n"
                "或\n"
                "取消授权 -1001234567890"
            )
            return
        chat_id_str = parts[1].strip()
    elif text.startswith('取消授权'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ 用法错误\n\n"
                "正确用法：取消授权 -1001234567890"
            )
            return
        chat_id_str = parts[1].strip()
    else:
        return  # 不匹配，让其他 handler 处理
    
    # 仅允许私聊（但在群组中发送时给提示）
    if chat.type != 'private':
        logger.info(f"   ❌ 非私聊环境，返回提示")
        await update.message.reply_text(
            "⚠️ <b>此命令仅支持在私聊中使用</b>\n\n"
            "请在私聊中发送：\n"
            f"<code>取消授权 {chat_id_str}</code>"
        )
        return
    
    # 🔵 获取bot_id并检查权限
    bot_id = get_current_bot_id(context)
    logger.info(f"   Bot ID: {bot_id}")
    
    # 检查用户是否为超管或管理员
    role = await get_user_role(user.id, None, bot_id)
    logger.info(f"   User role: {role}")
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        logger.info(f"   ❌ 用户不是超管或管理员")
        await update.message.reply_text("❌ 仅超级管理员或管理员可以使用此命令")
        return
    
    # 转换为整数
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        await update.message.reply_text(f"❌ 无效的群组 ID: {chat_id_str}")
        return
    
    # 执行取消授权
    from sqlalchemy import select, and_
    from ..models import Group, get_db_session
    from ..models.enums import GroupStatus
    
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
            await update.message.reply_text(f"❌ 未找到群组 {chat_id}\n\n请先将 Bot 添加到该群组。")
            return
        
        # 检查群组是否已经取消授权
        if group.status == GroupStatus.UNAUTHORIZED.value:
            inviter_info = ""
            if group.invited_by:
                inviter_info = f"\n👤 主管理员：@{group.invited_by_username or '未知'}"
            
            message = (
                f"⚠️ 群组 {chat_id}\n\n"
                f"已经取消授权，无需重复操作\n"
                f"当前状态：❌未授权{inviter_info}"
            )
            await update.message.reply_text(message, parse_mode='HTML')
            return
        
        # 更新状态为 UNAUTHORIZED
        old_status = group.status
        group.status = GroupStatus.UNAUTHORIZED.value
        await db.commit()
        
        logger.info(f"   ✅ 取消授权群组: {chat_id} ({old_status} → UNAUTHORIZED)")
        
        inviter_info = ""
        if group.invited_by:
            inviter_info = f"\n👤 主管理员：@{group.invited_by_username or '未知'}"
        
        message = (
            f"✅ 群组 {chat_id} 已取消授权\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"状态变更：{old_status} → ❌未授权\n\n"
            f"📋 说明：\n"
            f"• 群组功能已被禁用\n"
            f"• 群成员无法使用 Bot 功能\n"
            f"• 需要重新授权才能恢复使用\n\n"
            f"💡 提示：如需恢复，请联系超管重新授权{inviter_info}"
        )
        
        await update.message.reply_text(message, parse_mode='HTML')


async def cmd_check_group_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查询群组授权状态
    
    用法：/checkstatus -1001234567890
    或：查询群组状态 -1001234567890
    """
    # 🛡️ 安全检查
    if not AUTHORIZATION_ENABLED:
        logger.debug("⏭️ 授权系统未启用，跳过命令处理")
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    # 仅允许私聊
    if chat.type != 'private':
        await update.message.reply_text("❌ 此命令仅支持在私聊中使用")
        return
    
    bot_id = get_current_bot_id(context)
    
    # 检查用户是否为超管或管理员
    role = await get_user_role(user.id, None, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text("❌ 仅管理员可以使用此命令")
        return
    
    # 解析群组 ID
    text = update.message.text.strip()
    
    if text.startswith('/checkstatus'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ 用法错误\n\n正确用法：/checkstatus -1001234567890")
            return
        chat_id_str = parts[1].strip()
    elif text.startswith('查询群组状态'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ 用法错误\n\n正确用法：查询群组状态 -1001234567890")
            return
        chat_id_str = parts[1].strip()
    else:
        return
    
    # 转换为整数
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        await update.message.reply_text(f"❌ 无效的群组 ID: {chat_id_str}")
        return
    
    # 查询群组信息
    from sqlalchemy import select, and_
    from ..models import Group, get_db_session
    
    async with get_db_session() as db:
        query = select(Group).where(
            and_(
                Group.group_id == chat_id,
                Group.bot_id == bot_id
            )
        )
        result = await db.execute(query)
        group = result.scalar_one_or_none()
    
    if not group:
        await update.message.reply_text(
            f"❌ 未找到群组 {chat_id}\n\n请先将 Bot 添加到该群组。",
            parse_mode='HTML'
        )
        return
    
    # 构建状态信息
    status_emoji = {
        'PENDING': '⏳',
        'ACTIVE': '✅',
        'UNAUTHORIZED': '❌',
        'EXPIRED': '⏰',
        'DISABLED': '🚫'
    }
    
    status_text = {
        'PENDING': '待处理',
        'ACTIVE': '已授权',
        'UNAUTHORIZED': '未授权',
        'EXPIRED': '已过期',
        'DISABLED': '已禁用'
    }
    
    status_desc = {
        'PENDING': '待处理（Bot 刚被拉入群）',
        'ACTIVE': '活跃（已授权，正常使用）',
        'UNAUTHORIZED': '未授权（需要超管授权）',
        'EXPIRED': '已过期（套餐到期）',
        'DISABLED': '已禁用（手动禁用）'
    }
    
    inviter_info = ""
    if group.invited_by:
        inviter_info = f"\n👤 主管理员：@{group.invited_by_username or '未知'}"
    
    welcome_info = "\n 首次欢迎语：已发送" if group.first_welcome_sent else "\n🎉 首次欢迎语：未发送"
    
    message = (
        f"📊 <b>群组授权状态查询</b>\n\n"
        f"群组ID：<code>{group.group_id}</code>\n"
        f"群组名称：{group.group_name}\n"
        f"状态：{status_emoji.get(group.status, '❓')} {status_text.get(group.status, '未知')}\n"
        f"说明：{status_desc.get(group.status, '未知状态')}"
        f"{inviter_info}"
        f"{welcome_info}"
    )
    
    await update.message.reply_text(message, parse_mode='HTML')


async def cmd_set_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    设置冒充管理员白名单

    用法：设置白名单 @username
    或：设置白名单 123456789
    """
    user = update.effective_user
    chat = update.effective_chat

    # 仅允许私聊
    if chat.type != 'private':
        await update.message.reply_text("❌ 此命令仅支持在私聊中使用")
        return

    bot_id = get_current_bot_id(context)

    # 检查用户是否为超管或管理员
    role = await get_user_role(user.id, None, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text("❌ 仅超级管理员或管理员可以使用此命令")
        return

    # 解析参数
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await update.message.reply_text(
            "❌ 用法错误\n\n"
            "正确用法：\n"
            "<code>设置白名单 @username</code>\n"
            "或\n"
            "<code>设置白名单 123456789</code>\n\n"
            "💡 说明：将用户添加到冒充管理员检测白名单，该用户更名时不会被检测",
            parse_mode='HTML'
        )
        return

    target = parts[1].strip()

    # 解析用户ID或用户名
    target_user_id = None
    target_username = None

    if target.startswith('@'):
        target_username = target[1:]
    else:
        try:
            target_user_id = int(target)
        except ValueError:
            await update.message.reply_text(
                "❌ 无效的用户标识\n\n"
                "请使用以下格式之一：\n"
                "• <code>设置白名单 @username</code>\n"
                "• <code>设置白名单 123456789</code>",
                parse_mode='HTML'
            )
            return

    # 添加到白名单
    from ..models import get_db_session, ImpersonationWhitelist
    from sqlalchemy import select
    from datetime import datetime

    async with get_db_session() as db:
        # 检查是否已存在
        if target_user_id:
            existing = await db.execute(
                select(ImpersonationWhitelist).where(
                    ImpersonationWhitelist.bot_id == bot_id,
                    ImpersonationWhitelist.user_id == target_user_id
                )
            )
        else:
            existing = await db.execute(
                select(ImpersonationWhitelist).where(
                    ImpersonationWhitelist.bot_id == bot_id,
                    ImpersonationWhitelist.username == target_username
                )
            )

        if existing.scalar_one_or_none():
            await update.message.reply_text(
                f"⚠️ 该用户已在白名单中\n\n"
                f"用户: <code>{target}</code>\n"
                f"无需重复添加",
                parse_mode='HTML'
            )
            return

        # 创建白名单记录
        whitelist_entry = ImpersonationWhitelist(
            bot_id=bot_id,
            user_id=target_user_id or 0,  # 如果只有用户名，暂时用0占位
            username=target_username,
            added_by=user.id,
            added_at=datetime.now(),
            reason="手动添加"
        )

        db.add(whitelist_entry)
        await db.commit()

    await update.message.reply_text(
        f"✅ <b>白名单添加成功</b>\n\n"
        f"用户: <code>{target}</code>\n"
        f"添加者: @{user.username or user.id}\n"
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"💡 该用户更名时将不再触发冒充管理员检测",
        parse_mode='HTML'
    )


async def cmd_remove_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    移除冒充管理员白名单

    用法：移除白名单 @username
    或：移除白名单 123456789
    """
    user = update.effective_user
    chat = update.effective_chat

    # 仅允许私聊
    if chat.type != 'private':
        await update.message.reply_text("❌ 此命令仅支持在私聊中使用")
        return

    bot_id = get_current_bot_id(context)

    # 检查用户是否为超管或管理员
    role = await get_user_role(user.id, None, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text("❌ 仅超级管理员或管理员可以使用此命令")
        return

    # 解析参数
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await update.message.reply_text(
            "❌ 用法错误\n\n"
            "正确用法：\n"
            "<code>移除白名单 @username</code>\n"
            "或\n"
            "<code>移除白名单 123456789</code>",
            parse_mode='HTML'
        )
        return

    target = parts[1].strip()

    # 解析用户ID或用户名
    target_user_id = None
    target_username = None

    if target.startswith('@'):
        target_username = target[1:]
    else:
        try:
            target_user_id = int(target)
        except ValueError:
            await update.message.reply_text(
                "❌ 无效的用户标识\n\n"
                "请使用以下格式之一：\n"
                "• <code>移除白名单 @username</code>\n"
                "• <code>移除白名单 123456789</code>",
                parse_mode='HTML'
            )
            return

    # 从白名单移除
    from ..models import get_db_session, ImpersonationWhitelist
    from sqlalchemy import select, delete

    async with get_db_session() as db:
        # 查找并删除
        if target_user_id:
            result = await db.execute(
                delete(ImpersonationWhitelist).where(
                    ImpersonationWhitelist.bot_id == bot_id,
                    ImpersonationWhitelist.user_id == target_user_id
                )
            )
        else:
            result = await db.execute(
                delete(ImpersonationWhitelist).where(
                    ImpersonationWhitelist.bot_id == bot_id,
                    ImpersonationWhitelist.username == target_username
                )
            )

        await db.commit()

        if result.rowcount > 0:
            await update.message.reply_text(
                f"✅ <b>白名单移除成功</b>\n\n"
                f"用户: <code>{target}</code>\n"
                f"操作者: @{user.username or user.id}\n\n"
                f"💡 该用户更名时将重新触发冒充管理员检测",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                f"⚠️ 该用户不在白名单中\n\n"
                f"用户: <code>{target}</code>\n"
                f"无需移除",
                parse_mode='HTML'
            )


async def cmd_list_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查看冒充管理员白名单列表

    用法：查看白名单
    """
    user = update.effective_user
    chat = update.effective_chat

    # 仅允许私聊
    if chat.type != 'private':
        await update.message.reply_text("❌ 此命令仅支持在私聊中使用")
        return

    bot_id = get_current_bot_id(context)

    # 检查用户是否为超管或管理员
    role = await get_user_role(user.id, None, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        await update.message.reply_text("❌ 仅超级管理员或管理员可以使用此命令")
        return

    # 查询白名单
    from ..models import get_db_session, ImpersonationWhitelist
    from sqlalchemy import select, func

    async with get_db_session() as db:
        # 获取总数
        count_result = await db.execute(
            select(func.count()).select_from(ImpersonationWhitelist).where(
                ImpersonationWhitelist.bot_id == bot_id
            )
        )
        total_count = count_result.scalar() or 0

        # 获取白名单列表
        result = await db.execute(
            select(ImpersonationWhitelist)
            .where(ImpersonationWhitelist.bot_id == bot_id)
            .order_by(ImpersonationWhitelist.added_at.desc())
            .limit(20)
        )
        whitelist_entries = result.scalars().all()

    if not whitelist_entries:
        await update.message.reply_text(
            f"📋 <b>冒充管理员白名单</b>\n\n"
            f"总数: 0 人\n\n"
            f"暂无白名单记录\n\n"
            f"💡 使用 <code>设置白名单 @username</code> 添加用户",
            parse_mode='HTML'
        )
        return

    text = (
        f"📋 <b>冒充管理员白名单</b>\n\n"
        f"总数: {total_count} 人\n"
        f"显示前 {len(whitelist_entries)} 条:\n\n"
    )

    for i, entry in enumerate(whitelist_entries, 1):
        username_display = f"@{entry.username}" if entry.username else "无用户名"
        name_display = entry.first_name or "无昵称"
        text += f"{i}. {username_display} ({name_display})\n"
        if entry.reason:
            text += f"   原因: {entry.reason[:30]}{'...' if len(entry.reason) > 30 else ''}\n"

    if total_count > 20:
        text += f"\n... 还有 {total_count - 20} 条记录"

    text += (
        f"\n💡 <b>操作说明：</b>\n"
        f"• 添加白名单：<code>设置白名单 @username</code>\n"
        f"• 移除白名单：<code>移除白名单 @username</code>"
    )

    await update.message.reply_text(text, parse_mode='HTML')


def register_auth_commands(application):
    """
    注册授权管理命令

    Args:
        application: Telegram Application 实例
    """
    # /authorize 或 授权
    application.add_handler(CommandHandler("authorize", cmd_authorize_group))
    # ✅ 修复：允许有空格或无空格
    application.add_handler(MessageHandler(filters.Regex(r'^授权\s*-?\d+'), cmd_authorize_group))

    # /deauthorize 或 取消授权
    application.add_handler(CommandHandler("deauthorize", cmd_deauthorize_group))
    application.add_handler(MessageHandler(filters.Regex(r'^取消授权\s*-?\d+'), cmd_deauthorize_group))

    # 首次欢迎语配置功能已取消

    # /checkstatus 或 查询群组状态
    application.add_handler(CommandHandler("checkstatus", cmd_check_group_status))
    application.add_handler(MessageHandler(filters.Regex(r'^查询群组状态\s+-?\d+'), cmd_check_group_status))

    # 冒充管理员白名单管理命令
    application.add_handler(CommandHandler("setwhitelist", cmd_set_whitelist))
    application.add_handler(MessageHandler(filters.Regex(r'^设置白名单\s+.+'), cmd_set_whitelist))

    application.add_handler(CommandHandler("removewhitelist", cmd_remove_whitelist))
    application.add_handler(MessageHandler(filters.Regex(r'^移除白名单\s+.+'), cmd_remove_whitelist))

    application.add_handler(CommandHandler("listwhitelist", cmd_list_whitelist))
    application.add_handler(MessageHandler(filters.Regex(r'^查看白名单$'), cmd_list_whitelist))

    logger.info("✅ 授权管理命令已注册（仅在 AUTHORIZATION_ENABLED=True 时生效）")

"""
基础功能处理器

⚠️ DEPRECATED - 旧架构实现
此文件已迁移到新架构,请参考:
- capability_system.py (权限控制)
- ui_schema_registry.py (UI路由)
- runtime_router.py (命令处理)

新功能请使用新架构开发
预计删除时间: 2026-Q3
"""
import logging
import re
from datetime import datetime
from telegram import Update, ChatMember, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select as sql_select, select, and_, func, or_, distinct, update as sa_update

from ..models import Group, PrivateChatUser, get_db
from ..models.group import DEFAULT_BROADCAST_GROUP_TAG, GroupTag
from ..utils.role_checker import get_user_role, UserRole
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.tenant_scope import scoped_query, scoped_insert
from ..utils.state_manager import clear_state
from ..repositories import TransactionRepo, GroupRepo, GroupOperatorRepo
from ..services.group_tag_service import GroupTagService
from ..services.account_status_service import account_status_service

logger = logging.getLogger(__name__)


def render_command(cmd: str) -> str:
    """
    统一命令渲染引擎
    
    优先使用 Telegram 原生命令格式，实现：
    - 蓝色高亮显示
    - 点击自动填入输入框
    - 用户只需点发送即可执行
    - 完美匹配 Telegram 原生体验
    
    支持的格式：
    - 斜杠命令：/help, /start, /bill（Telegram原生支持，蓝色可点击）
    - 普通命令：<code>开始记账</code>（等宽字体，长按复制）
    
    Args:
        cmd: 命令文本
    
    Returns:
        HTML 格式的命令字符串
    """
    # 如果命令已经是斜杠开头，直接返回（Telegram会自动识别为蓝色可点击）
    if cmd.startswith('/'):
        return cmd
    
    # 否则使用 code 标签（等宽字体，长按复制）
    return f"<code>{cmd}</code>"


async def start_billing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始记账 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or "Private Chat"
    user = update.effective_user
    
    # 🆕 获取租户上下文和 bot_id
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..services.tenant_context import tenant_context_manager
    from ..core.capability_system import capability_resolver
    
    bot_id = get_current_bot_id(context)
    
    # 🔐 新增：检查群组是否已授权（仅对群组消息）
    if update.effective_chat.type in ['group', 'supergroup']:
        from ..utils.permission_checker import PermissionChecker
        is_authorized = await PermissionChecker.check_group_authorization(update, context)
        if not is_authorized:
            logger.warning(f"🚫 Group {chat_id} is not authorized, blocking /start command")
            return
    
    # 🆕 对于群组操作，检查 accounting:start_stop 能力
    if update.effective_chat.type in ['group', 'supergroup']:
        # 获取用户角色
        from ..utils.role_checker import get_user_role, UserRole
        role = await get_user_role(user.id, chat_id, bot_id)
        
        # 只有管理员或操作员可以开启记账
        if role not in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN, UserRole.OPERATOR]:
            await update.message.reply_text(
                "❌ 您没有权限开启记账功能\n\n"
                "请联系群组管理员或操作员进行操作。"
            )
            return

    async for db in get_db():
        # 记录私聊用户（支持租户隔离）
        if update.effective_chat.type == 'private' and user:
            try:
                query = scoped_query(PrivateChatUser, context).where(PrivateChatUser.user_id == user.id)
                result = await db.execute(query)
                existing_user = result.scalar_one_or_none()
                
                if not existing_user:
                    # ✅ 首次私聊初始化：添加新用户
                    private_user = scoped_insert(
                        PrivateChatUser(
                            user_id=user.id,
                            username=user.username or None,  # ✅ 空值保护
                            first_name=user.first_name or None,
                            last_name=user.last_name or None,
                            language_code=user.language_code or None,
                            is_bot=user.is_bot or False
                        ),
                        context
                    )
                    db.add(private_user)
                    await db.commit()
                    logger.info(f"[PRIVATE] New user recorded: {user.id} ({user.username})")
                else:
                    # ✅ 更新用户信息（昵称可能变化）
                    existing_user.username = user.username or existing_user.username
                    existing_user.first_name = user.first_name or existing_user.first_name
                    existing_user.last_name = user.last_name or existing_user.last_name
                    existing_user.updated_at = datetime.utcnow()
                    await db.commit()
                    logger.debug(f"[PRIVATE] User info updated: {user.id}")
            except Exception as e:
                logger.error(f"[PRIVATE] Failed to record user: {e}", exc_info=True)
                # ✅ 即使数据库操作失败，也继续发送欢迎消息
            
            # 根据统一账号状态和角色生成私聊菜单，避免试用/全功能/Bot创建者串台
            from ..utils.role_checker import get_user_role as _get_user_role, UserRole as _UserRole
            from ..utils.bot_id_middleware import get_current_bot_id
            import os
            bot_id = get_current_bot_id(context)
            user_role = await _get_user_role(user.id, group_id=None, bot_id=bot_id)
            account_status = await account_status_service.resolve(user.id, bot_id)
            try:
                env_bot_owner_id = int(os.getenv('BOT_OWNER_ID', '0'))
            except (ValueError, TypeError):
                env_bot_owner_id = 0
            if env_bot_owner_id and user.id == env_bot_owner_id:
                user_role = _UserRole.BOT_OWNER
            if account_status.tier == "full" and account_status.active_bot:
                user_role = _UserRole.BOT_OWNER
            
            # 收集所有该用户可见的菜单项
            all_buttons = []
            
            # ===== 超级管理员 =====
            # 显示：运行统计、创建续费、功能设置、个人中心、能量TRX、usdt监听、消息中心、超管后台
            if user.id == 7862093562:  # 固定超管ID
                is_main_runtime = os.environ.get('IS_MAIN_BOT', 'true').lower() == 'true'
                all_buttons.append('📊 运行统计')
                all_buttons.append('💰 创建续费')
                all_buttons.append('⚙️ 功能设置')
                all_buttons.append('👤 个人中心')
                all_buttons.append('⚡ 能量TRX')
                all_buttons.append('💰 USDT监听')
                if is_main_runtime or bot_id in ("main_bot", "test_bot"):
                    all_buttons.append('💬 消息中心')
                    all_buttons.append('🛠 超管后台')

            # ===== Bot创建者 =====
            # 显示：运行统计、创建续费、功能设置、个人中心、能量TRX、usdt监听
            elif user_role in [_UserRole.SUPER_ADMIN, _UserRole.BOT_OWNER]:
                all_buttons.append('📊 运行统计')
                all_buttons.append('💰 创建续费')
                all_buttons.append('⚙️ 功能设置')
                all_buttons.append('👤 个人中心')
                all_buttons.append('⚡ 能量TRX')
                all_buttons.append('💰 USDT监听')
            
            # ===== 管理员 =====
            # 显示：创建续费、个人中心、功能设置、能量TRX、usdt监听、运行统计
            # 不显示：使用说明、申请试用、联系客服
            elif user_role == _UserRole.ADMIN:
                all_buttons.append('💰 创建续费')
                all_buttons.append('👤 个人中心')
                all_buttons.append('⚙️ 功能设置')
                all_buttons.append('⚡ 能量TRX')
                all_buttons.append('💰 USDT监听')
                all_buttons.append('📊 运行统计')
            
            # ===== 全局操作员 / 群组记账员 / 普通用户 =====
            # 显示：申请试用、创建续费、个人中心、联系客服、能量TRX、usdt监听
            # 不显示：使用说明、运行统计、功能设置
            else:
                if account_status.tier != "trial":
                    all_buttons.append('📝 申请试用')
                all_buttons.append('💰 创建续费')
                all_buttons.append('👤 个人中心')
                all_buttons.append('💬 联系客服')
                all_buttons.append('⚡ 能量TRX')
                all_buttons.append('💰 USDT监听')
            
            # 每行3个按钮进行分组
            menu_buttons = []
            for i in range(0, len(all_buttons), 3):
                row = all_buttons[i:i+3]
                menu_buttons.append(row)
            
            reply_markup = ReplyKeyboardMarkup(menu_buttons, resize_keyboard=True)
            
            # 显示用户角色信息
            role_display = {
                _UserRole.SUPER_ADMIN: "超级管理员",
                _UserRole.BOT_OWNER: "Bot创建者",
                _UserRole.ADMIN: "管理员",
                _UserRole.NORMAL_USER: "普通用户"
            }.get(user_role, "普通用户")
            
            # 新文案：简洁友好的欢迎消息（只发送一条，包含内联按钮）
            bot_display_name = context.bot.first_name or context.bot.username or "记账机器人"
            welcome_text = f"""✨ 欢迎使用{bot_display_name}！
我是你的专属记账助手，帮你轻松管理群组账单～

💡 拉我进群，发送「开始」就能开启记账！
👇 快带我回家吧！🎉"""

            # 添加内联键盘按钮 - "添加到群组" 和 "分享机器人"
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            inline_keyboard = [[
                InlineKeyboardButton(
                    "➕ 添加到群组",
                    url="https://t.me/{}?startgroup=start".format(context.bot.username)
                ),
                InlineKeyboardButton(
                    "📤 分享机器人",
                    url="https://t.me/share/url?url=https://t.me/{}&text=推荐一个好用的记账机器人！".format(context.bot.username)
                )
            ]]
            inline_reply_markup = InlineKeyboardMarkup(inline_keyboard)

            # 发送欢迎消息（带内联按钮）
            await update.message.reply_text(
                welcome_text,
                reply_markup=inline_reply_markup
            )
            
            # 发送下方菜单键盘
            await update.message.reply_text(
                "👇 请选择下方菜单操作：",
                reply_markup=reply_markup
            )
            return

        # 查找或创建群组
        bot_id = get_current_bot_id(context)
        group_repo = GroupRepo(db, bot_id)
        
        group = await group_repo.get_by_group_id(chat_id)

        is_new_group = False
        if not group:
            # ✅ 创建新群组（Repository 自动设置 bot_id）
            # ✅ 新群组首次进群自动分配到系统内置的"默认"分组
            group = await group_repo.create(
                group_id=chat_id,
                group_name=chat_title,
                group_type=update.effective_chat.type,
                is_active=True,
                group_tag=DEFAULT_BROADCAST_GROUP_TAG
            )
            is_new_group = True
            logger.info(f"[BOT:{bot_id}] Created new group: {chat_id} ({chat_title}), auto-assigned to default broadcast group")
        else:
            # ✅ 已有群组重新激活，保持原有分组不变
            # 即使之前没有分组，也不再自动分配（避免覆盖管理员的配置意图）
            group.is_active = True
            logger.info(f"[BOT:{bot_id}] Activated existing group: {chat_id}, keeping existing tag: {group.group_tag or 'None'}")

        await db.commit()

        # 如果是新群组，自动将添加者设置为操作人
        if is_new_group and user:
            op_repo = GroupOperatorRepo(db, bot_id)
            
            # 检查添加者是否已经是操作人
            is_already_operator = await op_repo.is_operator(chat_id, user.id)
            
            if not is_already_operator:
                # 添加为群组操作人（Repository 自动设置 bot_id）
                await op_repo.add_operator(
                    group_id=chat_id,
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name
                )
                logger.info(f"[BOT:{bot_id}] Auto-added operator: {user.first_name or user.username} (ID: {user.id}) to group {chat_title}")

        # 如果有欢迎语，先发送欢迎语
        if group and group.welcome_message:
            try:
                await update.message.reply_text(group.welcome_message, parse_mode="HTML")
            except Exception as e:
                logger.error(f"发送欢迎语失败: {str(e)}")
                await update.message.reply_text(group.welcome_message)

        # 群组中不显示底部菜单键盘，只发送文本消息
        welcome_text = (
            f"✅ 已开启记账功能，现在可以开始记账。"
        )

        await update.message.reply_text(welcome_text, parse_mode='HTML')


async def stop_billing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """停止记账 - 新架构版本（接入 Capability System）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 获取租户上下文和 bot_id
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..services.tenant_context import tenant_context_manager
    from ..core.capability_system import capability_resolver
    
    bot_id = get_current_bot_id(context)
    
    # 🆕 对于群组操作，检查 accounting:start_stop 能力
    if update.effective_chat.type in ['group', 'supergroup']:
        # 获取用户角色
        from ..utils.role_checker import get_user_role, UserRole
        role = await get_user_role(user.id, chat_id, bot_id)
        
        # 只有管理员或操作员可以停止记账
        if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]:
            await update.message.reply_text(
                "❌ 您没有权限停止记账功能\n\n"
                "请联系群组管理员或操作员进行操作。"
            )
            return

    async for db in get_db():
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            group.is_active = False
            await db.commit()
            await update.message.reply_text("⛔ 记账功能已停止")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def mute_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """下课（禁言模式）- 新架构版本（接入 Capability System）- 需要机器人为管理员"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 获取租户上下文和 bot_id
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..services.tenant_context import tenant_context_manager
    from ..core.capability_system import capability_resolver
    
    bot_id = get_current_bot_id(context)
    
    # 🆕 对于群组操作，检查 accounting:mute_control 能力
    if update.effective_chat.type in ['group', 'supergroup']:
        # 获取用户角色
        from ..utils.role_checker import get_user_role, UserRole
        role = await get_user_role(user.id, chat_id, bot_id)
        
        # 只有管理员可以控制禁言
        if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
            await update.message.reply_text(
                "❌ 您没有权限执行此操作\n\n"
                "请联系群组管理员进行操作。"
            )
            return

    try:
        # 检查机器人是否为管理员
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await update.message.reply_text("❌ 机器人需要管理员权限才能执行此操作")
            return

        # 设置禁言 - 禁止所有消息发送
        from telegram import ChatPermissions
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=True,  # 保留邀请用户权限
            can_pin_messages=False
        )
        await context.bot.set_chat_permissions(chat_id, permissions)

        async for db in get_db():
            query = scoped_query(Group, context).where(Group.group_id == chat_id)
            result = await db.execute(query)
            group = result.scalar_one_or_none()

            if group:
                group.is_muted = True
                await db.commit()

        await update.message.reply_text("🔇 群组已进入禁言模式（下课）")

    except Exception as e:
        logger.error(f"Mute group error: {e}")
        await update.message.reply_text(f"❌ 操作失败: {str(e)}")


async def unmute_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """上课（解除禁言）- 新架构版本（接入 Capability System）- 需要机器人为管理员"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 获取租户上下文和 bot_id
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..services.tenant_context import tenant_context_manager
    from ..core.capability_system import capability_resolver
    
    bot_id = get_current_bot_id(context)
    
    # 🆕 对于群组操作，检查 accounting:mute_control 能力
    if update.effective_chat.type in ['group', 'supergroup']:
        # 获取用户角色
        from ..utils.role_checker import get_user_role, UserRole
        role = await get_user_role(user.id, chat_id, bot_id)
        
        # 只有管理员可以控制禁言
        if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
            await update.message.reply_text(
                "❌ 您没有权限执行此操作\n\n"
                "请联系群组管理员进行操作。"
            )
            return

    try:
        # 检查机器人是否为管理员
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await update.message.reply_text("❌ 机器人需要管理员权限才能执行此操作")
            return

        # 解除禁言 - 设置所有权限为True
        from telegram import ChatPermissions
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False
        )
        await context.bot.set_chat_permissions(chat_id, permissions)

        async for db in get_db():
            query = scoped_query(Group, context).where(Group.group_id == chat_id)
            result = await db.execute(query)
            group = result.scalar_one_or_none()

            if group:
                group.is_muted = False
                await db.commit()

        await update.message.reply_text("🔊 群组已解除禁言（上课）")

    except Exception as e:
        logger.error(f"Unmute group error: {e}")
        await update.message.reply_text(f"❌ 操作失败: {str(e)}")


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助信息 - 已迁移到高级帮助中心"""
    # ✅ 重定向到新的帮助中心
    from src.handlers.help_handler import show_help as new_show_help
    await new_show_help(update, context)


async def handle_group_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理“分组管理”按钮"""
    query = update.callback_query
    message = update.message

    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..utils.role_checker import get_user_role, UserRole

    bot_id = get_current_bot_id(context)
    user_id = update.effective_user.id

    user_role = await get_user_role(user_id, bot_id=bot_id)
    if user_role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.BOT_OWNER]:
        logger.warning(f"[GROUP_MANAGE PERMISSION] 权限拒绝 - User ID: {user_id}, Role: {user_role}")
        if query:
            from ..utils.settings_guard import LOCKED_FEATURE_MESSAGE
            await query.answer(LOCKED_FEATURE_MESSAGE, show_alert=True)
        elif message:
            error_text = (
                "❌ 无权限访问'分组管理'\n\n"
                "这是管理功能，仅机器人管理员可以使用。\n\n"
                "📡 联系客服：@xiaomingjz"
            )
            await message.reply_text(error_text, parse_mode='HTML')
        return

    logger.info(f"🔳 [handle_group_manage] bot_id={bot_id}, user_id={user_id}, role={user_role}")

    try:
        if query:
            await _render_group_manage_page(query, context)
        elif message:
            await _render_group_manage_page(message, context)
    except Exception as e:
        logger.error(f"❌ 处理分组管理时出错: {e}", exc_info=True)
        error_text = f"❌ 获取分组信息时出错：{str(e)}"
        if query:
            await query.edit_message_text(error_text, parse_mode='HTML')
        elif message:
            await message.reply_text(error_text, parse_mode='HTML')

async def handle_group_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理“群发广播”按钮"""
    if not update.message:
        return
    await update.message.reply_text(
        " **群发广播**\n\n"
        "此功能正在开发中...\n\n"
        "💡 **提示：**\n"
        "向指定群组发送消息",
        parse_mode="Markdown"
    )


async def show_help_guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理“使用说明”按钮点击，直接调用show_help函数显示帮助消息"""
    query = update.callback_query
    if not query:
        return
    
    # 回答回调
    await query.answer()
    
    # 直接调用show_help函数，复用帮助消息内容，避免重复代码
    await show_help(update, context)


async def handle_back_to_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理返回主菜单回调（删除当前消息并重新显示主菜单）"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    from ..utils.settings_guard import clear_edit_states
    clear_edit_states(context)
    _reset_group_tag_waiting_state(context)

    try:
        from .menu_callbacks import handle_settings
        logger.info(f"🔙 [handle_back_to_main_menu_callback] user_id={query.from_user.id}, bot_id={get_current_bot_id(context)}")
        await handle_settings(update, context)
        logger.info("✅ 已返回功能配置菜单")
        
    except Exception as e:
        logger.error(f"❌ 返回主菜单时出错: {e}", exc_info=True)
        try:
            await query.edit_message_text(f"❌ 返回主菜单时出错：{str(e)}")
        except:
            pass


async def show_system_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统状态（仅超级管理员）"""
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    
    # 检查是否为超级管理员
    from config import config_manager
    if user.id != config_manager.telegram.super_admin_id:
        await update.message.reply_text("❌ 此命令仅限超级管理员使用")
        return
    
    # 获取系统健康报告
    from ..utils.monitoring import bot_monitor
    report = bot_monitor.get_health_report()
    
    await update.message.reply_text(report, parse_mode="Markdown")


# ============================================================================
# 🆕 分组管理回调处理器
# ============================================================================

GROUP_TAG_NAME_MAX_LEN = 20
GROUP_TAG_GROUP_PAGE_SIZE = 10


def _is_valid_group_tag_name(name: str) -> bool:
    if not name or len(name) > GROUP_TAG_NAME_MAX_LEN:
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9 _-]+", name))


def _parse_group_tag_page_callback(callback_data: str, marker: str):
    prefix = f"{marker}__page__"
    if not callback_data.startswith(prefix):
        return None, None
    payload = callback_data.replace(prefix, "", 1)
    parts = payload.split("__", 1)
    if len(parts) != 2:
        return None, None
    try:
        page = int(parts[0])
    except ValueError:
        return None, None
    return parts[1], page


async def _load_group_tags_and_counts(db, bot_id: str):
    tags_query = select(GroupTag).where(
        and_(
            GroupTag.bot_id == bot_id,
            GroupTag.is_active.is_(True)
        )
    ).order_by(GroupTag.tag_name)
    tags_result = await db.execute(tags_query)
    tags = list(tags_result.scalars().all())

    counts_query = (
        select(Group.group_tag, func.count(distinct(Group.group_id)))
        .where(
            and_(
                Group.bot_id == bot_id,
                Group.is_active.is_(True)
            )
        )
        .group_by(Group.group_tag)
    )
    counts_result = await db.execute(counts_query)
    counts_map = {
        (tag_name or DEFAULT_BROADCAST_GROUP_TAG): count
        for tag_name, count in counts_result.all()
    }

    for tag in tags:
        counts_map.setdefault(tag.tag_name, 0)

    total_groups_query = select(func.count(distinct(Group.group_id))).where(
        and_(
            Group.bot_id == bot_id,
            Group.is_active.is_(True),
        )
    )
    total_groups_result = await db.execute(total_groups_query)
    total_groups = total_groups_result.scalar() or 0
    return tags, counts_map, total_groups


def _set_group_tag_prompt_state(context: ContextTypes.DEFAULT_TYPE, query, mode: str, tag_name: str | None = None):
    if not query or not getattr(query, "message", None):
        return
    context.user_data["group_tag_prompt_state"] = {
        "chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
        "mode": mode,
        "tag_name": tag_name,
    }


def _get_group_tag_prompt_target(context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("group_tag_prompt_state") or {}
    chat_id = state.get("chat_id")
    message_id = state.get("message_id")
    if not chat_id or not message_id:
        return None
    return chat_id, message_id


def _clear_group_tag_prompt_state(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("group_tag_prompt_state", None)


async def _send_group_tag_message(target, context: ContextTypes.DEFAULT_TYPE, message_text: str, reply_markup):
    if isinstance(target, tuple) and len(target) == 2:
        chat_id, message_id = target
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=message_text,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return

    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(message_text, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await target.reply_text(message_text, parse_mode='HTML', reply_markup=reply_markup)


def _reset_group_tag_waiting_state(context: ContextTypes.DEFAULT_TYPE):
    context.user_data['waiting_for_group_tag_name'] = False
    context.user_data['waiting_for_rename_group_tag_name'] = False
    context.user_data.pop('old_group_tag_name', None)
    _clear_group_tag_prompt_state(context)


async def _render_group_manage_page(target, context: ContextTypes.DEFAULT_TYPE, notice: str | None = None, page: int = 0):
    """渲染分组管理页面 - 一行2个按钮，每页10个，支持分页"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    PER_PAGE = 5   # 每页最多5条
    COLS = 2       # 一行2个

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        tags, group_counts, total_groups = await _load_group_tags_and_counts(db, bot_id)

    # 无分组时的边界处理
    if not tags:
        message_text = "📁 <b>分组管理</b>\n\n"
        message_text += "ℹ️ 暂无分组，请先在「分组管理」中创建分组"
        if notice:
            message_text += f"\n\n{notice}"
        keyboard = [
            [InlineKeyboardButton("➕ 创建分组", callback_data="group_tag_create")],
            [InlineKeyboardButton("🗑️ 删除分组", callback_data="group_tag_delete_list")],
        ]
        ui_renderer.append_standard_footer(keyboard, "back_to_main_menu")
        await _send_group_tag_message(target, context, message_text, InlineKeyboardMarkup(keyboard))
        return

    # 分页计算
    total_pages = max(1, (len(tags) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PER_PAGE
    end = start + PER_PAGE
    page_tags = tags[start:end]

    # 构建按钮 - 分组按钮一行2个
    keyboard = []
    for i in range(0, len(page_tags), COLS):
        row = []
        for j in range(COLS):
            idx = i + j
            if idx < len(page_tags):
                tag = page_tags[idx]
                count = group_counts.get(tag.tag_name, 0)
                row.append(InlineKeyboardButton(
                    f"📁 {tag.tag_name} ({count}个群组)",
                    callback_data=f"group_tag_detail_{tag.tag_name}"
                ))
        if row:
            keyboard.append(row)

    nav_row = ui_renderer.build_pagination_row(
        page + 1,
        total_pages,
        f"group_tag_page_{page - 1}" if page > 0 else None,
        f"group_tag_page_{page + 1}" if page < total_pages - 1 else None,
    )
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton("➕ 创建分组", callback_data="group_tag_create"),
        InlineKeyboardButton("🗑️ 删除分组", callback_data="group_tag_delete_list"),
    ])
    ui_renderer.append_standard_footer(keyboard, "back_to_main_menu")

    reply_markup = InlineKeyboardMarkup(keyboard)

    # 标题和提示文案
    message_text = "📁 <b>分组管理</b>\n\n"
    message_text += "✨点分组名即可进入详情页，就能：\n"
    message_text += "✏️改名字、🗑️删分组、➕加群组啦\n\n"
    message_text += f"当前共有 {len(tags)} 个分组，{total_groups} 个群组"

    if notice:
        message_text += f"\n\n{notice}"

    await _send_group_tag_message(target, context, message_text, reply_markup)


async def _render_group_tag_action_menu(target, context: ContextTypes.DEFAULT_TYPE, tag_name: str, notice: str | None = None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from sqlalchemy import select, and_
    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        tag_query = select(GroupTag).where(
            and_(
                GroupTag.bot_id == bot_id,
                GroupTag.tag_name == tag_name,
                GroupTag.is_active.is_(True)
            )
        )
        tag_result = await db.execute(tag_query)
        tag = tag_result.scalar_one_or_none()

        if not tag:
            await _send_group_tag_message(target, context, "❌ 分组不存在或已删除", None)
            return

        count_query = select(func.count(Group.id)).where(
            and_(
                Group.bot_id == bot_id,
                Group.group_tag == tag_name,
                Group.is_active.is_(True)
            )
        )
        count_result = await db.execute(count_query)
        group_count = count_result.scalar() or 0

    keyboard = [[InlineKeyboardButton("✏️ 编辑分组名称", callback_data=f"group_tag_rename_{tag_name}")]]
    if tag_name != DEFAULT_BROADCAST_GROUP_TAG:
        keyboard.append([InlineKeyboardButton("🗑️ 删除分组", callback_data=f"group_tag_delete_{tag_name}")])
    keyboard.append([InlineKeyboardButton("➕ 添加群组到该分组", callback_data=f"group_tag_add_{tag_name}")])
    ui_renderer.append_standard_footer(keyboard, "back_to_group_manage")

    message = (
        f"📂 <b>分组：{tag_name} ({group_count}个群组)</b>\n"
        f"请选择要执行的操作："
    )
    if notice:
        message += f"\n\n{notice}"
    await _send_group_tag_message(target, context, message, InlineKeyboardMarkup(keyboard))

async def handle_group_tag_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理分组详情回调（点击分组名）"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    callback_data = query.data or ""
    if not callback_data.startswith("group_tag_detail_"):
        return

    tag_name = callback_data.replace("group_tag_detail_", "", 1)
    logger.info(f"🔳 [handle_group_tag_detail] bot_id={get_current_bot_id(context)}, tag_name={tag_name}")
    await _render_group_tag_action_menu(query, context, tag_name)


async def handle_group_tag_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理分组管理分页"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    callback_data = query.data or ""
    # 解析页码: group_tag_page_{page}
    parts = callback_data.split("_")
    if len(parts) >= 4 and parts[3] != "none":
        try:
            page = int(parts[3])
        except ValueError:
            page = 0
    else:
        # 边界页（第一页点上一页 / 最后一页点下一页）
        page = 0

    await _render_group_manage_page(query, context, page=page)


async def handle_group_tag_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理关闭分组管理"""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass


async def handle_group_tag_delete_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理删除分组 - 显示分组列表供选择"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..core.ui_renderer import ui_renderer

    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        tags, group_counts, total_groups = await _load_group_tags_and_counts(db, bot_id)

    if not tags:
        await query.answer("当前暂无可删除的分组", show_alert=True)
        return

    keyboard = []
    row = []
    for tag in tags:
        count = group_counts.get(tag.tag_name, 0)
        row.append(InlineKeyboardButton(
            f"🗑️ {tag.tag_name} ({count}个群组)",
            callback_data=f"group_tag_delete_{tag.tag_name}"
        ))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    ui_renderer.append_standard_footer(keyboard, "back_to_group_manage")

    text = "🗑️ <b>删除分组</b>\n\n请选择要删除的分组："
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def handle_group_tag_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理创建分组回调"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    message = (
        "➕ <b>创建新分组</b>\n\n"
        "请在下方输入分组名称（支持文字，不包含特殊字符，不超过20字）\n"
        "例如：VIP群组、测试群组"
    )

    keyboard = [[InlineKeyboardButton("← 取消", callback_data="back_to_group_manage")]]
    _set_group_tag_prompt_state(context, query, mode="create")
    await query.edit_message_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    context.user_data['waiting_for_group_tag_name'] = True
    context.user_data.pop('waiting_for_rename_group_tag_name', None)
    context.user_data.pop('old_group_tag_name', None)

async def handle_group_tag_rename_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理重命名分组回调"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    callback_data = query.data or ""
    if not callback_data.startswith("group_tag_rename_"):
        return

    tag_name = callback_data.replace("group_tag_rename_", "", 1)
    logger.info(f"🔳 [handle_group_tag_rename] bot_id={get_current_bot_id(context)}, tag_name={tag_name}")

    message = (
        f"✏️ <b>编辑分组名称：{tag_name}</b>\n\n"
        "请发送新的分组名称：\n"
        "- 仅支持中文、英文、数字、空格、下划线、短横线\n"
        "- 长度不超过20字\n"
        "- 发送 /cancel 取消"
    )

    keyboard = [[InlineKeyboardButton("← 返回分组菜单", callback_data=f"group_tag_detail_{tag_name}")]]
    _set_group_tag_prompt_state(context, query, mode="rename", tag_name=tag_name)
    await query.edit_message_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    context.user_data['waiting_for_rename_group_tag_name'] = True
    context.user_data['old_group_tag_name'] = tag_name
    context.user_data.pop('waiting_for_group_tag_name', None)

async def handle_group_tag_rename_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理重命名分组的输入"""
    if not update.message or not context.user_data.get('waiting_for_rename_group_tag_name'):
        return

    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    old_name = context.user_data.get('old_group_tag_name')
    new_name = (update.message.text or '').strip()
    prompt_target = _get_group_tag_prompt_target(context)

    if new_name.lower() in ("/cancel", "取消"):
        _reset_group_tag_waiting_state(context)
        if prompt_target and old_name:
            try:
                await _render_group_tag_action_menu(prompt_target, context, old_name, notice="已取消重命名分组")
                return
            except Exception as e:
                logger.error(f"❌ 取消重命名后刷新页面失败: {e}", exc_info=True)
        await update.message.reply_text("已取消重命名分组")
        return

    if not new_name:
        await update.message.reply_text("❌ 分组名称不能为空，请重新输入")
        return
    if not _is_valid_group_tag_name(new_name):
        await update.message.reply_text("❌ 分组名称仅支持中文、英文、数字、空格、下划线、短横线，且长度不能超过20字")
        return
    if old_name == DEFAULT_BROADCAST_GROUP_TAG:
        _reset_group_tag_waiting_state(context)
        if prompt_target:
            try:
                await _render_group_tag_action_menu(prompt_target, context, old_name, notice="❌ 默认分组不支持重命名")
                return
            except Exception as e:
                logger.error(f"❌ 刷新默认分组页面失败: {e}", exc_info=True)
        await update.message.reply_text("❌ 默认分组不支持重命名")
        return

    async with get_db_session() as db:
        try:
            existing_tag_query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == new_name,
                    GroupTag.is_active.is_(True)
                )
            )
            existing_tag_result = await db.execute(existing_tag_query)
            existing_tag = existing_tag_result.scalar_one_or_none()
            if existing_tag and new_name != old_name:
                await update.message.reply_text(f"❌ 分组名称【{new_name}】已存在，请使用其他名称")
                return

            await db.execute(
                sa_update(GroupTag)
                .where(and_(GroupTag.bot_id == bot_id, GroupTag.tag_name == old_name, GroupTag.is_active.is_(True)))
                .values(tag_name=new_name)
            )
            await db.execute(
                sa_update(Group)
                .where(and_(Group.bot_id == bot_id, Group.group_tag == old_name))
                .values(group_tag=new_name)
            )
            await db.commit()

            _reset_group_tag_waiting_state(context)
            await update.message.reply_text(
                f"✅ 分组名称已更新为【{new_name}】",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data=f"group_tag_detail_{new_name}")]])
            )
        except Exception as e:
            logger.error(f"❌ 重命名分组时出错: {e}", exc_info=True)
            await update.message.reply_text(f"❌ 重命名分组时出错：{str(e)}")

async def handle_group_tag_create_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理创建分组输入"""
    if not update.message or not context.user_data.get('waiting_for_group_tag_name'):
        return

    from ..models.database import get_db_session
    from ..models.group import GroupTag
    from ..utils.bot_id_middleware import get_current_bot_id

    bot_id = get_current_bot_id(context)
    user_id = update.effective_user.id
    tag_name = (update.message.text or '').strip()
    prompt_target = _get_group_tag_prompt_target(context)

    if tag_name.lower() in ("/cancel", "取消"):
        _reset_group_tag_waiting_state(context)
        if prompt_target:
            try:
                await _render_group_manage_page(prompt_target, context, notice="已取消创建分组")
                return
            except Exception as e:
                logger.error(f"❌ 取消创建后刷新页面失败: {e}", exc_info=True)
        await update.message.reply_text("已取消创建分组")
        return

    if not tag_name:
        await update.message.reply_text("❌ 分组名称不能为空，请重新输入")
        return
    if not _is_valid_group_tag_name(tag_name):
        await update.message.reply_text("❌ 分组名称仅支持中文、英文、数字、空格、下划线、短横线，且长度不能超过20字")
        return

    async with get_db_session() as db:
        try:
            existing_query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == tag_name,
                    GroupTag.is_active.is_(True)
                )
            )
            existing_result = await db.execute(existing_query)
            if existing_result.scalar_one_or_none():
                await update.message.reply_text(f"❌ 分组名称【{tag_name}】已存在，请使用其他名称")
                return

            db.add(GroupTag(bot_id=bot_id, tag_name=tag_name, created_by=user_id, is_active=True))
            await db.commit()
            _reset_group_tag_waiting_state(context)
            await update.message.reply_text(
                f"✅ 分组【{tag_name}】创建成功",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← 返回设置页", callback_data="back_to_group_manage")]])
            )
            if prompt_target:
                try:
                    await _render_group_manage_page(prompt_target, context, notice=f"✅ 分组【{tag_name}】创建成功")
                    return
                except Exception as e:
                    logger.error(f"❌ 创建成功后刷新页面失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"❌ 创建分组时出错: {e}", exc_info=True)
            await update.message.reply_text(f"❌ 创建分组时出错：{str(e)}")


async def handle_group_tag_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理分组管理输入态的 /cancel"""
    if not update.message:
        return

    waiting_create = context.user_data.get('waiting_for_group_tag_name')
    waiting_rename = context.user_data.get('waiting_for_rename_group_tag_name')
    if not waiting_create and not waiting_rename:
        return

    prompt_target = _get_group_tag_prompt_target(context)
    old_name = context.user_data.get('old_group_tag_name')
    _reset_group_tag_waiting_state(context)

    if waiting_rename and prompt_target and old_name:
        try:
            await _render_group_tag_action_menu(prompt_target, context, old_name, notice="已取消当前分组操作")
            return
        except Exception as e:
            logger.error(f"❌ 取消重命名命令后刷新页面失败: {e}", exc_info=True)

    if waiting_create and prompt_target:
        try:
            await _render_group_manage_page(prompt_target, context, notice="已取消当前分组操作")
            return
        except Exception as e:
            logger.error(f"❌ 取消创建命令后刷新页面失败: {e}", exc_info=True)

    await update.message.reply_text("已取消当前分组操作")

async def handle_group_tag_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理删除分组回调"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    callback_data = query.data or ""
    confirm_prefix = "group_tag_delete_confirm_"
    normal_prefix = "group_tag_delete_"
    if callback_data.startswith(confirm_prefix):
        tag_name = callback_data.replace(confirm_prefix, "", 1)
        confirmed = True
    elif callback_data.startswith(normal_prefix):
        tag_name = callback_data.replace(normal_prefix, "", 1)
        confirmed = False
    else:
        return

    bot_id = get_current_bot_id(context)
    logger.info(f"🔳 [handle_group_tag_delete] bot_id={bot_id}, tag_name={tag_name}, confirmed={confirmed}")

    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group

    async with get_db_session() as db:
        try:
            tag_query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == tag_name,
                    GroupTag.is_active.is_(True)
                )
            )
            tag_result = await db.execute(tag_query)
            tag = tag_result.scalar_one_or_none()
            if not tag:
                await query.edit_message_text("❌ 分组不存在或已删除")
                return

            if tag_name == DEFAULT_BROADCAST_GROUP_TAG:
                await query.answer("默认分组不能删除", show_alert=True)
                await _render_group_tag_action_menu(query, context, tag_name)
                return

            count_query = select(func.count(Group.id)).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.group_tag == tag_name,
                    Group.is_active.is_(True)
                )
            )
            count_result = await db.execute(count_query)
            group_count = count_result.scalar() or 0

            if not confirmed:
                keyboard = [
                    [InlineKeyboardButton("✅ 确认删除", callback_data=f"group_tag_delete_confirm_{tag_name}")],
                    [InlineKeyboardButton("← 返回分组菜单", callback_data=f"group_tag_detail_{tag_name}")],
                ]
                message = (
                    f"⚠️ <b>确定要删除该分组吗？</b>\n\n"
                    f"分组：<b>{tag_name}</b>\n"
                    f"当前包含 {group_count} 个群组\n\n"
                    f"删除后分组内所有群组将自动回到默认分组。"
                )
                await query.edit_message_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
                return

            default_tag = await GroupTagService.ensure_default_tag(bot_id)
            await db.execute(
                sa_update(Group)
                .where(and_(Group.bot_id == bot_id, Group.group_tag == tag_name))
                .values(group_tag=default_tag.tag_name)
            )
            await db.execute(
                sa_update(GroupTag)
                .where(and_(GroupTag.bot_id == bot_id, GroupTag.tag_name == tag_name))
                .values(is_active=False)
            )
            await db.commit()

            await _render_group_manage_page(
                query,
                context,
                notice=f"✅ 分组已删除，{group_count}个群组已自动移回默认分组"
            )
        except Exception as e:
            logger.error(f"❌ 删除分组时出错: {e}", exc_info=True)
            await query.edit_message_text(f"❌ 删除分组时出错：{str(e)}")

async def handle_group_tag_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """兼容旧入口：跳转到分组操作菜单"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    callback_data = query.data or ""
    if not callback_data.startswith("group_tag_manage_"):
        return
    tag_name = callback_data.replace("group_tag_manage_", "", 1)
    await _render_group_tag_action_menu(query, context, tag_name)

async def handle_group_tag_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理添加群组到分组回调"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    callback_data = query.data or ""
    if not callback_data.startswith("group_tag_add_"):
        return

    page_tag_name, page = _parse_group_tag_page_callback(callback_data, "group_tag_add")
    if page_tag_name is not None:
        tag_name = page_tag_name
        current_page = max(page, 1)
    else:
        tag_name = callback_data.replace("group_tag_add_", "", 1)
        current_page = 1
    bot_id = get_current_bot_id(context)

    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group

    async with get_db_session() as db:
        try:
            tag_query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == tag_name,
                    GroupTag.is_active.is_(True)
                )
            )
            tag_result = await db.execute(tag_query)
            tag = tag_result.scalar_one_or_none()
            if not tag:
                await query.edit_message_text("❌ 分组不存在或已删除")
                return

            groups_query = select(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.is_active.is_(True),
                    or_(Group.group_tag.is_(None), Group.group_tag != tag_name)
                )
            ).order_by(Group.group_name.asc())
            groups_result = await db.execute(groups_query)
            groups = list(groups_result.scalars().all())

            message = f"➕ <b>添加群组到分组：{tag_name}</b>\n\n"
            keyboard = []
            if groups:
                total_pages = max((len(groups) + GROUP_TAG_GROUP_PAGE_SIZE - 1) // GROUP_TAG_GROUP_PAGE_SIZE, 1)
                current_page = min(current_page, total_pages)
                start_idx = (current_page - 1) * GROUP_TAG_GROUP_PAGE_SIZE
                page_groups = groups[start_idx:start_idx + GROUP_TAG_GROUP_PAGE_SIZE]
                message += "请选择要添加的群组：\n"
                for group in page_groups:
                    group_name = group.group_name or f"Group {group.group_id}"
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{group_name} ({group.group_id})",
                            callback_data=f"group_tag_add_select_{tag_name}_{group.group_id}"
                        )
                    ])
                message += f"\n\n第 {current_page}/{total_pages} 页"
                nav_row = []
                if current_page > 1:
                    nav_row.append(InlineKeyboardButton("← 上一页", callback_data=f"group_tag_add__page__{current_page - 1}__{tag_name}"))
                if current_page < total_pages:
                    nav_row.append(InlineKeyboardButton("下一页 →", callback_data=f"group_tag_add__page__{current_page + 1}__{tag_name}"))
                if nav_row:
                    keyboard.append(nav_row)
            else:
                message += "当前没有可添加的群组。"

            keyboard.append([InlineKeyboardButton("← 返回分组菜单", callback_data=f"group_tag_detail_{tag_name}")])
            await query.edit_message_text(message, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"❌ 处理添加群组时出错: {e}", exc_info=True)
            await query.edit_message_text(f"❌ 添加群组时出错：{str(e)}")

async def handle_group_tag_add_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理选择要添加的群组"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    callback_data = query.data or ""
    if not callback_data.startswith("group_tag_add_select_"):
        return

    remaining = callback_data.replace("group_tag_add_select_", "", 1)
    parts = remaining.rsplit("_", 1)
    if len(parts) != 2:
        await query.edit_message_text("❌ 无效的群组选择")
        return

    tag_name, group_id = parts[0], int(parts[1])
    bot_id = get_current_bot_id(context)

    from ..models.database import get_db_session
    from ..models.group import Group

    async with get_db_session() as db:
        try:
            group_query = select(Group).where(
                and_(Group.bot_id == bot_id, Group.group_id == group_id, Group.is_active.is_(True))
            )
            group_result = await db.execute(group_query)
            group = group_result.scalar_one_or_none()
            if not group:
                await query.edit_message_text("❌ 群组不存在")
                return

            await db.execute(
                sa_update(Group)
                .where(and_(Group.bot_id == bot_id, Group.group_id == group_id))
                .values(group_tag=tag_name)
            )
            await db.commit()

            group_name = group.group_name or f"Group {group.group_id}"
            await _render_group_tag_action_menu(
                query,
                context,
                tag_name,
                notice=f"✅ 群组【{group_name}】已成功添加到【{tag_name}】"
            )
        except Exception as e:
            logger.error(f"❌ 添加群组时出错: {e}", exc_info=True)
            await query.edit_message_text(f"❌ 添加群组时出错：{str(e)}")

async def handle_group_tag_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理移除群组回调（点击移除群组按钮）"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from sqlalchemy import select, and_
    from ..models.database import get_db_session
    from ..models.group import GroupTag, Group
    from ..utils.bot_id_middleware import get_current_bot_id
    
    bot_id = get_current_bot_id(context)
    
    # 解析 callback_data: group_tag_remove_{tag_name}
    callback_data = query.data
    if not callback_data.startswith("group_tag_remove_"):
        return
    
    page_tag_name, page = _parse_group_tag_page_callback(callback_data, "group_tag_remove")
    if page_tag_name is not None:
        tag_name = page_tag_name
        current_page = max(page, 1)
    else:
        tag_name = callback_data.replace("group_tag_remove_", "", 1)
        current_page = 1
    
    logger.info(f" [handle_group_tag_remove] bot_id={bot_id}, tag_name={tag_name}")
    
    async with get_db_session() as db:
        try:
            # 查询分组信息
            tag_query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == tag_name,
                    GroupTag.is_active.is_(True)
                )
            )
            tag_result = await db.execute(tag_query)
            tag = tag_result.scalar_one_or_none()
            
            if not tag:
                await query.edit_message_text("❌ 分组不存在或已删除")
                return
            
            # 查询该分组下的所有群组
            groups_query = select(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.group_tag == tag_name,
                    Group.is_active.is_(True)
                )
            ).order_by(Group.group_name.asc())
            groups_result = await db.execute(groups_query)
            groups = groups_result.scalars().all()
            
            # 构建消息内容
            message = f"➖ <b>从分组中移除群组：{tag_name}</b>\n\n"
            
            if groups:
                total_pages = max((len(groups) + GROUP_TAG_GROUP_PAGE_SIZE - 1) // GROUP_TAG_GROUP_PAGE_SIZE, 1)
                current_page = min(current_page, total_pages)
                start_idx = (current_page - 1) * GROUP_TAG_GROUP_PAGE_SIZE
                page_groups = groups[start_idx:start_idx + GROUP_TAG_GROUP_PAGE_SIZE]
                message += f"当前分组中的群组（{len(groups)}个）：\n\n"
                # 构建群组选择按钮（每行1个）
                keyboard = []
                for group in page_groups:
                    group_name = group.group_name or f"Group {group.group_id}"
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{group_name} ({group.group_id})",
                            callback_data=f"group_tag_remove_select_{tag_name}_{group.group_id}"
                        )
                    ])
                message += f"\n第 {current_page}/{total_pages} 页"
                nav_row = []
                if current_page > 1:
                    nav_row.append(InlineKeyboardButton("← 上一页", callback_data=f"group_tag_remove__page__{current_page - 1}__{tag_name}"))
                if current_page < total_pages:
                    nav_row.append(InlineKeyboardButton("下一页 →", callback_data=f"group_tag_remove__page__{current_page + 1}__{tag_name}"))
                if nav_row:
                    keyboard.append(nav_row)
            else:
                message += "当前分组中没有群组\n\n"
                keyboard = []
            
            keyboard.append([InlineKeyboardButton(" 返回管理群组", callback_data=f"group_tag_manage_{tag_name}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(message, parse_mode='HTML', reply_markup=reply_markup)
            except Exception as e:
                # 如果消息内容完全相同，Telegram 会报错，这是正常的，忽略即可
                if "Message is not modified" in str(e):
                    logger.info(f"Message not modified for remove group page, ignoring")
                else:
                    raise
            
        except Exception as e:
            logger.error(f"❌ 处理移除群组时出错: {e}", exc_info=True)
            await query.edit_message_text(f" 移除群组时出错：{str(e)}")


async def handle_group_tag_remove_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理选择要移除的群组"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from sqlalchemy import select, update, and_
    from ..models.database import get_db_session
    from ..models.group import Group
    from ..utils.bot_id_middleware import get_current_bot_id
    
    bot_id = get_current_bot_id(context)
    
    # 解析 callback_data: group_tag_remove_select_{tag_name}_{group_id}
    callback_data = query.data
    if not callback_data.startswith("group_tag_remove_select_"):
        return
    
    # 提取 tag_name 和 group_id
    # 使用 rsplit 从右侧分割，确保 group_id 被正确提取（即使 tag_name 中包含下划线）
    remaining = callback_data.replace("group_tag_remove_select_", "", 1)
    parts = remaining.rsplit("_", 1)  # 从右侧分割一次
    if len(parts) != 2:
        await query.edit_message_text("❌ 无效的群组选择")
        return
    
    tag_name = parts[0]
    group_id = parts[1]
    
    logger.info(f" [handle_group_tag_remove_select] bot_id={bot_id}, tag_name={tag_name}, group_id={group_id}, callback_data={callback_data}")
    
    async with get_db_session() as db:
        try:
            # 查询群组是否存在
            group_query = select(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.group_id == group_id,
                    Group.is_active.is_(True)
                )
            )
            group_result = await db.execute(group_query)
            group = group_result.scalar_one_or_none()
            
            if not group:
                await query.edit_message_text("❌ 群组不存在")
                return
            
            # 更新群组的分组标签为空（移除分组）
            update_stmt = (
                update(Group)
                .where(
                    and_(
                        Group.bot_id == bot_id,
                        Group.group_id == group_id
                    )
                )
                .values(group_tag=None)
            )
            await db.execute(update_stmt)
            await db.commit()
            
            group_name = group.group_name or f"Group {group.group_id}"
            await _render_group_tag_action_menu(
                query,
                context,
                tag_name,
                notice=f"✅ 群组【{group_name}】已从【{tag_name}】中移除"
            )
            
            logger.info(f"✅ 群组 {group_id} 已从分组 {tag_name} 中移除")
            
        except Exception as e:
            logger.error(f"❌ 移除群组时出错: {e}", exc_info=True)
            await query.edit_message_text(f"❌ 移除群组时出错：{str(e)}")


async def handle_back_to_group_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理返回分组管理列表回调"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    from ..utils.settings_guard import clear_edit_states
    clear_edit_states(context)
    _reset_group_tag_waiting_state(context)
    logger.info(f"🔳 [handle_back_to_group_manage_callback] bot_id={get_current_bot_id(context)}, user_id={query.from_user.id}")
    await _render_group_manage_page(query, context)

async def handle_token_rebind_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 Token 重绑消息，仅在用户处于重绑状态时处理 Token。"""
    if not update.message or not update.effective_user:
        return
    
    # 检查是否处于重绑状态
    if not context.user_data.get('rebinding_bot_token'):
        return
    
    user_input = update.message.text.strip()
    
    # 用户取消重绑
    if user_input == '取消':
        clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')
        await update.message.reply_text("已取消 Token 重绑")
        return
    
    bot_id = context.user_data.get('rebind_bot_instance_id')
    user_id = update.effective_user.id
    if not bot_id:
        clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')
        await update.message.reply_text("已退出 Token 重绑状态。")
        return
    
    from ..services.token_check_service import token_check_service
    
    # 处理 Token 重绑
    success, message = await token_check_service.process_rebind_token(bot_id, user_id, user_input)
    
    if success:
        # 重绑成功
        clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')
        
        bot_info = await token_check_service.get_bot_info(bot_id)
        expire_time = bot_info.get('expire_time') if bot_info else None
        
        # 格式化到期时间
        expire_str = "永久" if not expire_time else expire_time.strftime("%Y-%m-%d %H:%M")
        
        success_text = (
            "✅ <b>Token 重绑成功！</b>\n\n"
            "你的机器人已恢复正常状态，到期时间、套餐和数据都会自动保留。\n\n"
            f"🤖 机器人信息：{message}\n"
            f"⏰ 当前到期时间：{expire_str}\n"
            "🔐 Token 状态：✅ 有效\n\n"
            "现在可以继续使用所有功能。"
        )
        await update.message.reply_text(success_text, parse_mode='HTML')
    else:
        # 重绑失败
        if message == '重绑状态已结束':
            clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')
            await update.message.reply_text("已退出 Token 重绑状态。")
            return
        error_text = f"❌ {message}"
        await update.message.reply_text(error_text)








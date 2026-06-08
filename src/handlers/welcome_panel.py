"""
欢迎词配置面板处理器 - 新版交互系统

功能：
1. 发送欢迎词配置面板（内联按钮）
2. 启用/禁用切换
3. 配置流程（等待用户发送内容）
4. 变量替换和渲染
5. 新用户入群欢迎消息
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, update as sql_update

from ..models import Group, get_db
from ..utils.tenant_scope import scoped_query
from ..utils.bot_id_middleware import get_current_bot_id
from .operator import is_operator

logger = logging.getLogger(__name__)


async def handle_welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理"设置欢迎语"命令 - 发送配置面板"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user = update.effective_user
    
    bot_id = get_current_bot_id(context)
    
    async for db in get_db():
        if chat_type == 'private':
            # 私聊模式：检查是否为超管
            from ..utils.role_checker import get_user_role, UserRole
            role = await get_user_role(user.id, None, bot_id)
            if role != UserRole.SUPER_ADMIN:
                await update.message.reply_text("⚠️ 仅超级管理员可以使用此命令")
                return
            
            # 私聊模式：全局配置（所有群组生效）
            context.user_data['welcome_config_mode'] = 'global'
            context.user_data['welcome_config_group_id'] = None
            await _send_welcome_panel_to_user(update, context, db, bot_id, mode='global')
        
        elif chat_type in ['group', 'supergroup']:
            # 群组模式：检查操作权限
            from ..utils.permission_checker import is_admin_or_operator
            if not await is_admin_or_operator(user.id, chat_id, db, context):
                await update.message.reply_text("⚠️ 仅管理员和操作人可以设置群组欢迎语")
                return
            
            # 群组模式：仅当前群组生效
            context.user_data['welcome_config_mode'] = 'group'
            context.user_data['welcome_config_group_id'] = chat_id
            await _send_welcome_panel_to_user(update, context, db, bot_id, mode='group', group_id=chat_id)
        
        else:
            await update.message.reply_text("⚠️ 此命令仅支持在私聊和群组中使用")
            return


async def _send_welcome_panel_to_user(update, context, db, bot_id, mode='global', group_id=None):
    """向用户发送欢迎词配置面板
    
    Args:
        update: Telegram Update
        context: Context
        db: Database session
        bot_id: Bot ID
        mode: 'global' (所有群组) 或 'group' (当前群组)
        group_id: 群组ID (仅群组模式需要)
    """
    # 查询当前配置状态
    if mode == 'global':
        # 全局模式：查询 group_id=0 的全局配置记录
        query_stmt = (
            select(Group)
            .where(Group.bot_id == bot_id, Group.group_id == 0)
        )
        result = await db.execute(query_stmt)
        group = result.scalar_one_or_none()
        
        is_enabled = group.join_welcome_enabled if group else False
        has_config = bool(group and (group.join_welcome_message or group.join_welcome_file_id))
        
        # 构建面板消息
        status_text = "☑️ 已启用" if is_enabled else "☐ 已禁用"
        config_text = "☑️ 已配置" if has_config else "☐ 未配置"
        
        # 如果有已配置的欢迎语，显示预览
        preview_section = ""
        if has_config and group.join_welcome_message:
            preview_content = group.join_welcome_message[:50]
            if len(group.join_welcome_message) > 50:
                preview_content += "..."
            
            preview_section = (
                f"\n\n📋 **当前欢迎语预览：**\n"
                f"```\n{preview_content}\n```"
            )
        
        message_text = (
            f"💎 **全局入群欢迎词配置**\n\n"
            f"📊 **当前状态**\n"
            f"• 欢迎词开关：{status_text}\n"
            f"• 欢迎词内容：{config_text}"
            f"{preview_section}\n\n"
            f"💡 **说明**\n"
            f"• 配置后将对所有授权群组生效\n"
            f"• 支持文本/图片/视频/动图/转发消息\n"
            f"• 使用 `@username` 可快捷复制用户名\n\n"
            f"👉 点击【配置入群欢迎词】设置新的欢迎语"
        )
    else:
        # 群组模式：查询当前群组配置
        query_stmt = (
            select(Group)
            .where(Group.bot_id == bot_id, Group.group_id == group_id)
        )
        result = await db.execute(query_stmt)
        group = result.scalar_one_or_none()
        
        is_enabled = group.join_welcome_enabled if group else False
        has_config = bool(group and (group.join_welcome_message or group.join_welcome_file_id))
        
        status_text = "☑️ 已启用" if is_enabled else "☐ 已禁用"
        config_text = "☑️ 已配置" if has_config else "☐ 未配置"
        
        group_name = group.group_name if group and group.group_name else f"ID: {group_id}"
        
        # 如果有已配置的欢迎语，显示预览
        preview_section = ""
        if has_config and group.join_welcome_message:
            preview_content = group.join_welcome_message[:50]
            if len(group.join_welcome_message) > 50:
                preview_content += "..."
            
            preview_section = (
                f"\n\n📋 **当前欢迎语预览：**\n"
                f"```\n{preview_content}\n```"
            )
        
        message_text = (
            f"💎 **群组欢迎词配置**\n\n"
            f"🏠 群组：{group_name}\n\n"
            f"📊 **当前状态**\n"
            f"• 欢迎词开关：{status_text}\n"
            f"• 欢迎词内容：{config_text}"
            f"{preview_section}\n\n"
            f"💡 **说明**\n"
            f"• 配置后仅对当前群组生效\n"
            f"• 支持文本/图片/视频/动图/转发消息\n"
            f"• 使用 `@username` 可快捷复制用户名\n\n"
            f"👉 点击【配置入群欢迎词】设置新的欢迎语"
        )
    
    # 构建内联按钮（动态显示当前状态）
    if is_enabled:
        # 已启用：启用按钮高亮，禁用按钮灰色
        enable_btn = InlineKeyboardButton("☑️ 启用中", callback_data="welcome_toggle_enable")
        disable_btn = InlineKeyboardButton("  禁用", callback_data="welcome_toggle_disable")
    else:
        # 已禁用：禁用按钮高亮，启用按钮灰色
        enable_btn = InlineKeyboardButton("☐ 启用", callback_data="welcome_toggle_enable")
        disable_btn = InlineKeyboardButton("☑️ 禁用中", callback_data="welcome_toggle_disable")
        
    keyboard = [
        [InlineKeyboardButton("📝 配置入群欢迎词", callback_data="welcome_config_start")],
        [enable_btn, disable_btn],
        [InlineKeyboardButton("🏠 返回", callback_data="welcome_close")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 发送消息
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )


async def welcome_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理欢迎词面板的回调按钮点击"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    callback_data = query.data
    
    # 获取 bot_id
    bot_id = get_current_bot_id(context)
    
    async for db in get_db():
        # 权限检查
        if not await is_operator(user.id, chat_id, db, context):
            await query.edit_message_text(" 无权限访问")
            return
        
        # 根据回调数据执行不同操作
        if callback_data == "welcome_config_start":
            # 开始配置流程 - 提示用户发送内容
            await _start_config_process(query, context, db, bot_id)
        
        elif callback_data == "welcome_toggle_enable":
            # 启用欢迎词
            await _toggle_welcome(query, context, db, bot_id, enabled=True)
        
        elif callback_data == "welcome_toggle_disable":
            # 禁用欢迎词
            await _toggle_welcome(query, context, db, bot_id, enabled=False)
        
        elif callback_data == "welcome_close":
            # 关闭面板
            await query.message.delete()


async def _start_config_process(query, context, db, bot_id):
    """开始配置流程 - 提示用户发送欢迎词内容"""
    # 设置等待状态
    context.user_data['waiting_welcome_content'] = True
    context.user_data['welcome_panel_message_id'] = query.message.message_id
    
    # 编辑消息显示配置提示
    message_text = (
        "💎 **欢迎词配置流程**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📤 **请发送以下任意内容：**\n\n"
        "  📝 文本消息\n"
        "  ️ 图片\n"
        "  ️ 视频\n"
        "  🎞️ 动图\n"
        "  📤 转发的消息\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 **支持变量：**\n"
        "  `@username` → 快捷复制用户名\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💬 **等待您的消息...**"
    )
    
    await query.edit_message_text(
        message_text,
        parse_mode="HTML"
    )


async def _toggle_welcome(query, context, db, bot_id, enabled: bool):
    """切换欢迎词启用/禁用状态"""
    # 获取配置模式
    mode = context.user_data.get('welcome_config_mode', 'global')
    group_id = context.user_data.get('welcome_config_group_id')
    
    if mode == 'global':
        # 全局模式：更新 group_id=0 的全局配置记录
        # 先检查是否存在全局配置记录
        global_query = (
            select(Group)
            .where(Group.bot_id == bot_id, Group.group_id == 0)
        )
        global_result = await db.execute(global_query)
        global_group = global_result.scalar_one_or_none()
        
        if global_group:
            # 更新现有全局配置
            await db.execute(
                sql_update(Group)
                .where(Group.bot_id == bot_id, Group.group_id == 0)
                .values(join_welcome_enabled=enabled)
            )
        else:
            # 创建全局配置记录
            from sqlalchemy import insert
            await db.execute(
                insert(Group).values(
                    bot_id=bot_id,
                    group_id=0,
                    group_name="全局默认配置",
                    group_type="global_config",
                    join_welcome_enabled=enabled
                )
            )
    else:
        # 群组模式：仅更新当前群组
        await db.execute(
            sql_update(Group)
            .where(Group.bot_id == bot_id, Group.group_id == group_id)
            .values(join_welcome_enabled=enabled)
        )
    
    await db.commit()
    
    # 重新显示面板
    await _show_welcome_panel(query, context, db, bot_id, query.message.message_id)


async def _show_welcome_panel(query, context, db, bot_id, message_id=None):
    """显示欢迎词配置面板"""
    # 获取配置模式
    mode = context.user_data.get('welcome_config_mode', 'global')
    group_id = context.user_data.get('welcome_config_group_id')
    
    # 查询当前配置状态
    if mode == 'global':
        # 全局模式：查询 group_id=0 的全局配置记录
        query_stmt = (
            select(Group)
            .where(Group.bot_id == bot_id, Group.group_id == 0)
        )
        result = await db.execute(query_stmt)
        group = result.scalar_one_or_none()
        
        is_enabled = group.join_welcome_enabled if group else False
        has_config = bool(group and (group.join_welcome_message or group.join_welcome_file_id))
        
        status_text = "☑️ 已启用" if is_enabled else "☐ 已禁用"
        config_text = "☑️ 已配置" if has_config else "☐ 未配置"
        
        # 如果有已配置的欢迎语，显示预览
        preview_section = ""
        if has_config and group.join_welcome_message:
            preview_content = group.join_welcome_message[:50]
            if len(group.join_welcome_message) > 50:
                preview_content += "..."
            
            preview_section = (
                f"\n\n📋 **当前欢迎语预览：**\n"
                f"```\n{preview_content}\n```"
            )
        
        message_text = (
            f"💎 **全局入群欢迎词配置**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 **当前状态**\n"
            f"• 欢迎词开关：{status_text}\n"
            f"• 欢迎词内容：{config_text}"
            f"{preview_section}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 **说明**\n"
            f"• 配置后将对所有授权群组生效\n"
            f"• 支持文本/图片/视频/动图/转发消息\n"
            f"• 使用 `@username` 可快捷复制用户名\n\n"
            f"👉 点击【配置入群欢迎词】设置新的欢迎语"
        )
    else:
        query_stmt = (
            select(Group)
            .where(Group.bot_id == bot_id, Group.group_id == group_id)
        )
        result = await db.execute(query_stmt)
        group = result.scalar_one_or_none()
        
        is_enabled = group.join_welcome_enabled if group else False
        has_config = bool(group and (group.join_welcome_message or group.join_welcome_file_id))
        
        status_text = "☑️ 已启用" if is_enabled else "☐ 已禁用"
        config_text = "☑️ 已配置" if has_config else "☐ 未配置"
        
        group_name = group.group_name if group and group.group_name else f"ID: {group_id}"
        
        # 如果有已配置的欢迎语，显示预览
        preview_section = ""
        if has_config and group.join_welcome_message:
            preview_content = group.join_welcome_message[:50]
            if len(group.join_welcome_message) > 50:
                preview_content += "..."
            
            preview_section = (
                f"\n\n📋 **当前欢迎语预览：**\n"
                f"```\n{preview_content}\n```"
            )
        
        message_text = (
            f"💎 **群组欢迎词配置**\n\n"
            f"🏠 群组：{group_name}\n\n"
            f"📊 **当前状态**\n"
            f"• 欢迎词开关：{status_text}\n"
            f"• 欢迎词内容：{config_text}"
            f"{preview_section}\n\n"
            f"💡 **说明**\n"
            f"• 配置后仅对当前群组生效\n"
            f"• 支持文本/图片/视频/动图/转发消息\n"
            f"• 使用 `@username` 可快捷复制用户名\n\n"
            f"👉 点击【配置入群欢迎词】设置新的欢迎语"
        )
    
    # 构建内联按钮（动态显示当前状态）
    if is_enabled:
        # 已启用：启用按钮显示☑️，禁用按钮显示☐
        enable_btn = InlineKeyboardButton("☑️ 启用中", callback_data="welcome_toggle_enable")
        disable_btn = InlineKeyboardButton("☐ 禁用", callback_data="welcome_toggle_disable")
    else:
        # 已禁用：启用按钮显示☐，禁用按钮显示☑️
        enable_btn = InlineKeyboardButton("☐ 启用", callback_data="welcome_toggle_enable")
        disable_btn = InlineKeyboardButton("☑️ 禁用中", callback_data="welcome_toggle_disable")
    
    keyboard = [
        [InlineKeyboardButton(" 配置入群欢迎词", callback_data="welcome_config_start")],
        [enable_btn, disable_btn],
        [InlineKeyboardButton("🏠 返回", callback_data="welcome_close")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 更新消息
    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    # 清除等待状态
    context.user_data.pop('waiting_welcome_content', None)


async def handle_welcome_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户发送的欢迎词内容"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    # 检查是否在等待状态
    if not context.user_data.get('waiting_welcome_content'):
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    bot_id = get_current_bot_id(context)
    
    logger.info(f"收到欢迎词内容: user_id={user.id}, chat_type={update.effective_chat.type}")
    
    # 获取消息类型和内容
    message_type = None
    file_id = None
    text_content = None
    caption = None
    
    if update.message.text:
        # 文本消息
        message_type = "text"
        text_content = update.message.text
        
    elif update.message.photo:
        # 图片消息
        message_type = "photo"
        file_id = update.message.photo[-1].file_id  # 获取最高分辨率
        caption = update.message.caption
    
    elif update.message.video:
        # 视频消息
        message_type = "video"
        file_id = update.message.video.file_id
        caption = update.message.caption
    
    elif update.message.animation:
        # 动图消息
        message_type = "animation"
        file_id = update.message.animation.file_id
        caption = update.message.caption
    
    elif update.message.forward_from or update.message.forward_from_chat:
        # 转发消息 - 根据转发的消息类型提取内容
        if update.message.text:
            # 转发的文本消息（带引用）
            message_type = "text"
            text_content = update.message.text
        elif update.message.photo:
            # 转发的图片消息
            message_type = "photo"
            file_id = update.message.photo[-1].file_id
            caption = update.message.caption
        elif update.message.video:
            # 转发的视频消息
            message_type = "video"
            file_id = update.message.video.file_id
            caption = update.message.caption
        elif update.message.animation:
            # 转发的动图消息
            message_type = "animation"
            file_id = update.message.animation.file_id
            caption = update.message.caption
        else:
            await update.message.reply_text("❌ 不支持的转发消息类型，请转发文本、图片、视频或动图")
            return
    
    else:
        await update.message.reply_text("❌ 不支持的消息类型，请发送文本、图片、视频或动图")
        return
    
    async for db in get_db():
        # 检查权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text(" 无权限操作")
            return
        
        # 获取配置模式
        mode = context.user_data.get('welcome_config_mode', 'global')
        group_id = context.user_data.get('welcome_config_group_id')
        
        # 保存到数据库
        if mode == 'global':
            # 全局模式：保存到 group_id=0 的全局配置记录
            # 先检查是否存在全局配置记录
            global_query = (
                select(Group)
                .where(Group.bot_id == bot_id, Group.group_id == 0)
            )
            global_result = await db.execute(global_query)
            global_group = global_result.scalar_one_or_none()
            
            if global_group:
                # 更新现有全局配置
                await db.execute(
                    sql_update(Group)
                    .where(Group.bot_id == bot_id, Group.group_id == 0)
                    .values(
                        join_welcome_message=text_content,
                        join_welcome_type=message_type,
                        join_welcome_file_id=file_id,
                        join_welcome_caption=caption,
                        join_welcome_parse_mode="HTML"
                    )
                )
            else:
                # 创建全局配置记录
                from sqlalchemy import insert
                await db.execute(
                    insert(Group).values(
                        bot_id=bot_id,
                        group_id=0,
                        group_name="全局默认配置",
                        group_type="global_config",
                        join_welcome_message=text_content,
                        join_welcome_type=message_type,
                        join_welcome_file_id=file_id,
                        join_welcome_caption=caption,
                        join_welcome_parse_mode="HTML"
                    )
                )
            scope_text = "所有授权群组"
        else:
            # 群组模式：仅应用到当前群组
            await db.execute(
                sql_update(Group)
                .where(Group.bot_id == bot_id, Group.group_id == group_id)
                .values(
                    join_welcome_message=text_content,
                    join_welcome_type=message_type,
                    join_welcome_file_id=file_id,
                    join_welcome_caption=caption,
                    join_welcome_parse_mode="HTML"
                )
            )
            scope_text = f"当前群组 (ID: {group_id})"
        
        await db.commit()
        
        # 发送成功提示，附带操作按钮
        # 查询当前启用状态以显示正确的按钮样式
        if mode == 'global':
            status_query = (
                select(Group)
                .where(Group.bot_id == bot_id, Group.group_id == 0)
            )
        else:
            status_query = (
                select(Group)
                .where(Group.bot_id == bot_id, Group.group_id == group_id)
            )
        
        status_result = await db.execute(status_query)
        current_group = status_result.scalar_one_or_none()
        current_enabled = current_group.join_welcome_enabled if current_group else False
        
        if current_enabled:
            success_enable_btn = InlineKeyboardButton("☑️ 启用中", callback_data="welcome_toggle_enable")
            success_disable_btn = InlineKeyboardButton("☐ 禁用", callback_data="welcome_toggle_disable")
        else:
            success_enable_btn = InlineKeyboardButton("☐ 启用", callback_data="welcome_toggle_enable")
            success_disable_btn = InlineKeyboardButton("☑️ 禁用中", callback_data="welcome_toggle_disable")
        
        success_keyboard = [
            [success_enable_btn, success_disable_btn],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data="welcome_close")]
        ]
        success_reply_markup = InlineKeyboardMarkup(success_keyboard)
        
        # 构建预览内容
        preview_text = ""
        if message_type == "text":
            preview_text = f"\n\n━━━━━━━━━━━━\n\n**📝 预览：**\n{text_content}"
        elif message_type in ["photo", "video", "animation"]:
            preview_text = f"\n\n━━━━━━━━━━━━\n\n**📎 媒体附件：**{caption if caption else ' 无附言'}"
        else:
            preview_text = f"\n\n━━━━━━━━━━━━\n\n**📤 转发消息：**{text_content if text_content else ' 无附加文本'}"
        
        await update.message.reply_text(
            "✅ **欢迎词配置成功！**\n\n"
            "• 类型：{}\n"
            "• 应用范围：{}\n\n"
            "💡 新用户入群时将自动发送此欢迎词{}".format(
                {
                    "text": "📝 文本",
                    "photo": "🖼️ 图片",
                    "video": "🎬 视频",
                    "animation": "🎞️ 动图",
                    "forward": " 转发消息"
                }.get(message_type, message_type),
                scope_text,
                preview_text
            ),
            reply_markup=success_reply_markup,
            parse_mode="HTML"
        )
        
        # 清除等待状态
        context.user_data.pop('waiting_welcome_content', None)
        
        # 重新显示面板
        panel_msg_id = context.user_data.get('welcome_panel_message_id')
        if panel_msg_id:
            try:
                message = await context.bot.get_message(chat_id=chat_id, message_id=panel_msg_id)
                # 创建假 query 对象来更新面板
                class FakeQuery:
                    def __init__(self, msg):
                        self.message = msg
                    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                        await self.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                
                fake_query = FakeQuery(message)
                await _show_welcome_panel(fake_query, context, db, bot_id)
            except Exception as e:
                logger.warning(f"无法更新面板: {e}")


async def send_join_welcome(group_id: int, new_member_id: int, new_member_username: str, bot, db, bot_id: str):
    """发送入群欢迎消息给新用户
    
    Args:
        group_id: 群组ID
        new_member_id: 新用户ID
        new_member_username: 新用户名
        bot: Telegram Bot 实例
        db: 数据库会话
        bot_id: Bot ID
    """
    try:
        # 查询群组欢迎词配置
        query = (
            select(Group)
            .where(Group.bot_id == bot_id, Group.group_id == group_id)
        )
        result = await db.execute(query)
        group = result.scalar_one_or_none()
        
        if not group or not group.join_welcome_enabled:
            return
        
        if not group.join_welcome_message and not group.join_welcome_file_id:
            return
        
        # 渲染变量
        welcome_text = group.join_welcome_message or ""
        welcome_text = welcome_text.replace("@username", f"<a href='tg://user?id={new_member_id}'>{new_member_username or '新朋友'}</a>")
        
        # 根据类型发送消息
        if group.join_welcome_type == "text":
            await bot.send_message(
                chat_id=new_member_id,
                text=welcome_text,
                parse_mode="HTML"
            )
        
        elif group.join_welcome_type == "photo" and group.join_welcome_file_id:
            await bot.send_photo(
                chat_id=new_member_id,
                photo=group.join_welcome_file_id,
                caption=welcome_text,
                parse_mode="HTML"
            )
        
        elif group.join_welcome_type == "video" and group.join_welcome_file_id:
            await bot.send_video(
                chat_id=new_member_id,
                video=group.join_welcome_file_id,
                caption=welcome_text,
                parse_mode="HTML"
            )
        
        elif group.join_welcome_type == "animation" and group.join_welcome_file_id:
            await bot.send_animation(
                chat_id=new_member_id,
                animation=group.join_welcome_file_id,
                caption=welcome_text,
                parse_mode="HTML"
            )
        
        logger.info(f"✅ 已发送入群欢迎消息: group_id={group_id}, user_id={new_member_id}")
        
    except Exception as e:
        logger.error(f"发送入群欢迎消息失败: {e}", exc_info=True)

"""
首次授权欢迎语配置面板 - 新版交互系统

功能：
1. 发送首次授权欢迎语配置面板（内联按钮）
2. 启用/禁用切换
3. 配置流程（等待用户发送内容）
4. 变量替换和渲染（{username}、{group_name}）
5. 超管拉 Bot 进群自动发送欢迎消息

新架构特性：
✅ Bot ID 中间件隔离
✅ Repository 模式
✅ 租户隔离查询
✅ 异步数据库会话
✅ 统一渲染引擎
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, update as sql_update

from ..models import AdminGlobalConfig, get_db_session
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import get_user_role, UserRole

logger = logging.getLogger(__name__)

# 配置项键名
CONFIG_FIRST_AUTH_WELCOME_TEXT = "first_auth_welcome_text"
CONFIG_FIRST_AUTH_WELCOME_TYPE = "first_auth_welcome_type"
CONFIG_FIRST_AUTH_WELCOME_FILE_ID = "first_auth_welcome_file_id"
CONFIG_FIRST_AUTH_WELCOME_ENABLED = "first_auth_welcome_enabled"


async def handle_first_auth_welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理"设置首次欢迎语"命令 - 发送配置面板
    
    用法：/firstauthwelcome 或 设置首次欢迎语（不带参数）
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user = update.effective_user
    
    # 仅允许私聊
    if chat_type != 'private':
        await update.message.reply_text("⚠️ 此命令仅支持在私聊中使用")
        return
    
    bot_id = get_current_bot_id(context)
    
    # 检查用户是否为超管
    role = await get_user_role(user.id, None, bot_id)
    if role != UserRole.SUPER_ADMIN:
        await update.message.reply_text("⚠️ 仅超级管理员可以使用此命令")
        return
    
    async with get_db_session() as db:
        await _send_first_auth_welcome_panel(update, context, db, bot_id)


async def _send_first_auth_welcome_panel(update, context, db, bot_id):
    """
    向超管发送首次授权欢迎语配置面板
    
    Args:
        update: Telegram Update
        context: Context
        db: Database session
        bot_id: Bot ID
    """
    # 查询当前配置状态
    from sqlalchemy import and_
    
    query_stmt = select(AdminGlobalConfig).where(
        and_(
            AdminGlobalConfig.bot_id == bot_id,
            AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_ENABLED
        )
    )
    result = await db.execute(query_stmt)
    config = result.scalar_one_or_none()
    
    is_enabled = config.config_value == "true" if config else False
    
    # 查询是否有已配置的欢迎语
    text_query = select(AdminGlobalConfig).where(
        and_(
            AdminGlobalConfig.bot_id == bot_id,
            AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_TEXT
        )
    )
    text_result = await db.execute(text_query)
    text_config = text_result.scalar_one_or_none()
    
    has_config = bool(text_config and text_config.config_value)
    
    # 构建面板消息
    status_text = "☑️ 已启用" if is_enabled else "☐ 已禁用"
    config_text = "☑️ 已配置" if has_config else "☐ 未配置"
    
    # 如果有已配置的欢迎语，显示预览
    preview_section = ""
    if has_config and text_config.config_value:
        preview_content = text_config.config_value[:50]
        if len(text_config.config_value) > 50:
            preview_content += "..."
        
        preview_section = (
            f"\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 **当前欢迎语预览：**\n"
            f"```\n{preview_content}\n```"
        )
    
    message_text = (
        f"💎 **首次授权欢迎语配置**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 **当前状态**\n"
        f"• 欢迎语开关：{status_text}\n"
        f"• 欢迎语内容：{config_text}"
        f"{preview_section}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 **说明**\n"
        f"• 当超管/管理员拉 Bot 进群时，自动发送此欢迎语（仅一次）\n"
        f"• 支持文本/图片/视频/动图/转发消息\n"
        f"• 支持占位符：{'`{username}`'}（邀请者用户名）、{'`{group_name}`'}（群组名称）\n\n"
        f"👉 点击【配置首次欢迎词】设置新的欢迎语"
    )
    
    # 构建内联按钮（动态显示当前状态）
    if is_enabled:
        # 已启用：启用按钮显示☑️，禁用按钮显示☐
        enable_btn = InlineKeyboardButton("☑️ 启用中", callback_data="first_auth_welcome_toggle_enable")
        disable_btn = InlineKeyboardButton("☐ 禁用", callback_data="first_auth_welcome_toggle_disable")
    else:
        # 已禁用：启用按钮显示☐，禁用按钮显示☑️
        enable_btn = InlineKeyboardButton("☐ 启用", callback_data="first_auth_welcome_toggle_enable")
        disable_btn = InlineKeyboardButton("☑️ 禁用中", callback_data="first_auth_welcome_toggle_disable")
    
    keyboard = [
        [InlineKeyboardButton("📝 配置首次欢迎词", callback_data="first_auth_welcome_config_start")],
        [enable_btn, disable_btn],
        [InlineKeyboardButton("🏠 返回", callback_data="first_auth_welcome_close")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 发送消息
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )


async def first_auth_welcome_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理首次授权欢迎语面板的回调按钮点击
    """
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    callback_data = query.data
    
    # 获取 bot_id
    bot_id = get_current_bot_id(context)
    
    # 权限检查：仅超管可操作
    role = await get_user_role(user.id, None, bot_id)
    if role != UserRole.SUPER_ADMIN:
        await query.edit_message_text("⚠️ 无权限访问")
        return
    
    async with get_db_session() as db:
        # 根据回调数据执行不同操作
        if callback_data == "first_auth_welcome_config_start":
            # 开始配置流程 - 提示用户发送内容
            await _start_config_process(query, context, db, bot_id)
        
        elif callback_data == "first_auth_welcome_toggle_enable":
            # 启用欢迎语
            await _toggle_welcome(query, context, db, bot_id, enabled=True)
        
        elif callback_data == "first_auth_welcome_toggle_disable":
            # 禁用欢迎语
            await _toggle_welcome(query, context, db, bot_id, enabled=False)
        
        elif callback_data == "first_auth_welcome_close":
            # 关闭面板（删除消息）
            try:
                await query.message.delete()
            except Exception as e:
                logger.warning(f"删除消息失败: {e}")
                await query.edit_message_text("🏠 面板已关闭")


async def _start_config_process(query, context, db, bot_id):
    """
    开始配置流程 - 提示用户发送欢迎语内容
    """
    # 设置等待状态
    context.user_data['waiting_first_auth_welcome'] = True
    context.user_data['first_auth_welcome_panel_message_id'] = query.message.message_id
    
    # 编辑消息显示配置提示
    message_text = (
        "💎 **首次授权欢迎语配置**\n\n"
        "📤 **请发送以下内容：**\n"
        "• 📝 文本消息\n"
        "• 🖼️ 图片 / 🎬 视频 / 🎞️ 动图\n"
        "• 📤 转发的消息\n\n"
        "💡 **支持占位符：**\n"
        "`{username}` → 邀请者用户名\n"
        "`{group_name}` → 群组名称\n\n"
        "⏳ 等待您的消息..."
    )
    
    await query.edit_message_text(
        message_text,
        parse_mode="HTML"
    )


async def _toggle_welcome(query, context, db, bot_id, enabled: bool):
    """
    切换欢迎语启用/禁用状态
    """
    from sqlalchemy import and_
    
    # 更新或创建启用状态配置
    query_stmt = select(AdminGlobalConfig).where(
        and_(
            AdminGlobalConfig.bot_id == bot_id,
            AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_ENABLED
        )
    )
    result = await db.execute(query_stmt)
    config = result.scalar_one_or_none()
    
    if config:
        await db.execute(
            sql_update(AdminGlobalConfig)
            .where(
                and_(
                    AdminGlobalConfig.bot_id == bot_id,
                    AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_ENABLED
                )
            )
            .values(config_value="true" if enabled else "false")
        )
    else:
        from sqlalchemy import insert
        await db.execute(
            insert(AdminGlobalConfig).values(
                bot_id=bot_id,
                config_key=CONFIG_FIRST_AUTH_WELCOME_ENABLED,
                config_value="true" if enabled else "false"
            )
        )
    
    await db.commit()
    
    # 重新显示面板
    class FakeQuery:
        def __init__(self, msg):
            self.message = msg
        async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
            await self.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    
    fake_query = FakeQuery(query.message)
    await _show_first_auth_welcome_panel(fake_query, context, db, bot_id)


async def _show_first_auth_welcome_panel(query, context, db, bot_id):
    """
    显示首次授权欢迎语配置面板
    """
    from sqlalchemy import and_
    
    # 查询当前配置状态
    query_stmt = select(AdminGlobalConfig).where(
        and_(
            AdminGlobalConfig.bot_id == bot_id,
            AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_ENABLED
        )
    )
    result = await db.execute(query_stmt)
    config = result.scalar_one_or_none()
    
    is_enabled = config.config_value == "true" if config else False
    
    # 查询是否有已配置的欢迎语
    text_query = select(AdminGlobalConfig).where(
        and_(
            AdminGlobalConfig.bot_id == bot_id,
            AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_TEXT
        )
    )
    text_result = await db.execute(text_query)
    text_config = text_result.scalar_one_or_none()
    
    has_config = bool(text_config and text_config.config_value)
    
    status_text = "☑️ 已启用" if is_enabled else "☐ 已禁用"
    config_text = "☑️ 已配置" if has_config else "☐ 未配置"
    
    # 如果有已配置的欢迎语，显示预览
    preview_section = ""
    if has_config and text_config.config_value:
        preview_content = text_config.config_value[:50]
        if len(text_config.config_value) > 50:
            preview_content += "..."
        
        preview_section = (
            f"\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f" **当前欢迎语预览：**\n"
            f"```\n{preview_content}\n```"
        )
    
    message_text = (
        f"💎 **首次授权欢迎语配置**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 **当前状态**\n"
        f"• 欢迎语开关：{status_text}\n"
        f"• 欢迎语内容：{config_text}"
        f"{preview_section}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 **说明**\n"
        f"• 当超管/管理员拉 Bot 进群时，自动发送此欢迎语（仅一次）\n"
        f"• 支持文本/图片/视频/动图/转发消息\n"
        f"• 支持占位符：{'`{username}`'}（邀请者用户名）、{'`{group_name}`'}（群组名称）\n\n"
        f"👉 点击【配置首次欢迎词】设置新的欢迎语"
    )
    
    # 构建内联按钮（动态显示当前状态）
    if is_enabled:
        enable_btn = InlineKeyboardButton("☑️ 启用中", callback_data="first_auth_welcome_toggle_enable")
        disable_btn = InlineKeyboardButton(" 禁用", callback_data="first_auth_welcome_toggle_disable")
    else:
        enable_btn = InlineKeyboardButton("☐ 启用", callback_data="first_auth_welcome_toggle_enable")
        disable_btn = InlineKeyboardButton("☑️ 禁用中", callback_data="first_auth_welcome_toggle_disable")
    
    keyboard = [
        [InlineKeyboardButton("📝 配置首次欢迎词", callback_data="first_auth_welcome_config_start")],
        [enable_btn, disable_btn],
        [InlineKeyboardButton("🏠 返回", callback_data="first_auth_welcome_close")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 更新消息
    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    # 清除等待状态
    context.user_data.pop('waiting_first_auth_welcome', None)


async def handle_first_auth_welcome_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理用户发送的首次授权欢迎语内容
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    # 检查是否在等待状态
    if not context.user_data.get('waiting_first_auth_welcome'):
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    bot_id = get_current_bot_id(context)
    
    logger.info(f"收到首次授权欢迎语内容: user_id={user.id}, chat_type={update.effective_chat.type}")
    
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
    
    async with get_db_session() as db:
        # 检查权限
        role = await get_user_role(user.id, None, bot_id)
        if role != UserRole.SUPER_ADMIN:
            await update.message.reply_text("⚠️ 无权限操作")
            return
        
        from sqlalchemy import and_
        
        # 保存到数据库
        # 1. 保存欢迎语文本
        text_query = select(AdminGlobalConfig).where(
            and_(
                AdminGlobalConfig.bot_id == bot_id,
                AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_TEXT
            )
        )
        text_result = await db.execute(text_query)
        text_config = text_result.scalar_one_or_none()
        
        if text_config:
            await db.execute(
                sql_update(AdminGlobalConfig)
                .where(
                    and_(
                        AdminGlobalConfig.bot_id == bot_id,
                        AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_TEXT
                    )
                )
                .values(config_value=text_content)
            )
        else:
            from sqlalchemy import insert
            await db.execute(
                insert(AdminGlobalConfig).values(
                    bot_id=bot_id,
                    config_key=CONFIG_FIRST_AUTH_WELCOME_TEXT,
                    config_value=text_content
                )
            )
        
        # 2. 保存消息类型
        type_query = select(AdminGlobalConfig).where(
            and_(
                AdminGlobalConfig.bot_id == bot_id,
                AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_TYPE
            )
        )
        type_result = await db.execute(type_query)
        type_config = type_result.scalar_one_or_none()
        
        if type_config:
            await db.execute(
                sql_update(AdminGlobalConfig)
                .where(
                    and_(
                        AdminGlobalConfig.bot_id == bot_id,
                        AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_TYPE
                    )
                )
                .values(config_value=message_type)
            )
        else:
            await db.execute(
                insert(AdminGlobalConfig).values(
                    bot_id=bot_id,
                    config_key=CONFIG_FIRST_AUTH_WELCOME_TYPE,
                    config_value=message_type
                )
            )
        
        # 3. 保存 file_id（如果有）
        if file_id:
            file_query = select(AdminGlobalConfig).where(
                and_(
                    AdminGlobalConfig.bot_id == bot_id,
                    AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_FILE_ID
                )
            )
            file_result = await db.execute(file_query)
            file_config = file_result.scalar_one_or_none()
            
            if file_config:
                await db.execute(
                    sql_update(AdminGlobalConfig)
                    .where(
                        and_(
                            AdminGlobalConfig.bot_id == bot_id,
                            AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_FILE_ID
                        )
                    )
                    .values(config_value=file_id)
                )
            else:
                await db.execute(
                    insert(AdminGlobalConfig).values(
                        bot_id=bot_id,
                        config_key=CONFIG_FIRST_AUTH_WELCOME_FILE_ID,
                        config_value=file_id
                    )
                )
        
        await db.commit()
        
        # 发送成功提示，附带操作按钮
        # 查询当前启用状态以显示正确的按钮样式
        status_query = select(AdminGlobalConfig).where(
            and_(
                AdminGlobalConfig.bot_id == bot_id,
                AdminGlobalConfig.config_key == CONFIG_FIRST_AUTH_WELCOME_ENABLED
            )
        )
        status_result = await db.execute(status_query)
        status_config = status_result.scalar_one_or_none()
        current_enabled = status_config.config_value == "true" if status_config else False
        
        if current_enabled:
            success_enable_btn = InlineKeyboardButton("☑️ 启用中", callback_data="first_auth_welcome_toggle_enable")
            success_disable_btn = InlineKeyboardButton("☐ 禁用", callback_data="first_auth_welcome_toggle_disable")
        else:
            success_enable_btn = InlineKeyboardButton("☐ 启用", callback_data="first_auth_welcome_toggle_enable")
            success_disable_btn = InlineKeyboardButton("☑️ 禁用中", callback_data="first_auth_welcome_toggle_disable")
        
        success_keyboard = [
            [success_enable_btn, success_disable_btn],
            [InlineKeyboardButton(" 返回主菜单", callback_data="first_auth_welcome_close")]
        ]
        success_reply_markup = InlineKeyboardMarkup(success_keyboard)
        
        # 构建预览内容
        preview_text = ""
        if message_type == "text":
            preview_text = f"\n\n📝 **预览：**\n{text_content}"
        elif message_type in ["photo", "video", "animation"]:
            preview_text = f"\n\n📎 **媒体附件：**{caption if caption else '无附言'}"
        else:
            preview_text = f"\n\n📤 **转发消息：**{text_content if text_content else '无附加文本'}"
        
        await update.message.reply_text(
            "✅ **首次授权欢迎语配置成功**\n\n"
            "• 类型：{}\n"
            "• 应用范围：所有授权群组\n\n"
            "💡 超管/管理员拉 Bot 进群时将自动发送此欢迎语（仅一次）{}".format(
                {
                    "text": "📝 文本",
                    "photo": "🖼️ 图片",
                    "video": "🎬 视频",
                    "animation": "🎞️ 动图",
                    "forward": "转发消息"
                }.get(message_type, message_type),
                preview_text
            ),
            reply_markup=success_reply_markup,
            parse_mode="HTML"
        )
        
        # 清除等待状态
        context.user_data.pop('waiting_first_auth_welcome', None)
        
        # 重新显示面板
        panel_msg_id = context.user_data.get('first_auth_welcome_panel_message_id')
        if panel_msg_id:
            try:
                message = await context.bot.get_message(chat_id=chat_id, message_id=panel_msg_id)
                
                class FakeQuery:
                    def __init__(self, msg):
                        self.message = msg
                    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                        await self.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                
                fake_query = FakeQuery(message)
                await _show_first_auth_welcome_panel(fake_query, context, db, bot_id)
            except Exception as e:
                logger.warning(f"无法更新面板: {e}")

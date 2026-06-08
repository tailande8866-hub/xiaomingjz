"""
帮助中心 Handler
严格按照用户要求实现
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from src.services.help_builder import build_help_page
from src.keyboards.help_keyboard import help_keyboard
from src.config.help_data import PAGE_MAP
from src.models.database import get_db_session
from src.models.saas_auto import BotCreation
from src.models.group import PrivateChatUser
from sqlalchemy import select

logger = logging.getLogger(__name__)

# 固定超级管理员ID
FIXED_SUPER_ADMIN_ID = 7862093562


async def _get_bot_creator(bot: ContextTypes.DEFAULT_TYPE.bot, bot_id: str) -> str:
    """获取Bot创建者用户名，优先显示用户名，如果没有则显示ID"""
    try:
        async with get_db_session() as db:
            # 1. 从 BotCreation 获取创建者ID
            result = await db.execute(
                select(BotCreation).where(BotCreation.instance_id == bot_id)
            )
            bot_creation = result.scalar_one_or_none()
            
            if bot_creation and bot_creation.super_admin_id:
                creator_id = bot_creation.super_admin_id
                
                # 2. 尝试从 PrivateChatUser 表获取用户名
                user_result = await db.execute(
                    select(PrivateChatUser).where(
                        PrivateChatUser.bot_id == bot_id,
                        PrivateChatUser.user_id == creator_id
                    )
                )
                user = user_result.scalar_one_or_none()
                
                if user and user.username:
                    # 有用户名，显示 @用户名
                    return f"@{user.username}"
                elif user and user.first_name:
                    # 有名字，显示名字
                    return f"{user.first_name}"
                
                # 3. 尝试从 Telegram API 获取用户信息
                try:
                    chat = await bot.get_chat(creator_id)
                    if chat.username:
                        return f"@{chat.username}"
                    elif chat.first_name:
                        return f"{chat.first_name}"
                except Exception:
                    pass
                
                # 都没有，显示ID（可点击复制）
                return f"<code>{creator_id}</code>"
    except Exception as e:
        logger.warning(f"[帮助] 获取Bot创建者失败: {e}")
    
    # 默认返回超级管理员ID
    return f"<code>{FIXED_SUPER_ADMIN_ID}</code>"


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助中心（命令触发）- 显示分类索引"""
    message = update.message
    
    # 获取机器人信息
    bot = context.bot
    bot_info = await bot.get_me()
    bot_name = bot_info.first_name
    bot_username = bot_info.username
    
    # 获取创建者信息（从数据库查询）
    bot_id = context.bot_data.get("bot_id", bot_username)
    bot_creator = await _get_bot_creator(bot, bot_id)
    
    # 构建首页内容
    text = build_help_page("index", bot_name, bot_creator)
    keyboard = help_keyboard("index")
    
    await message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
    logger.info(f"[帮助] 用户 {message.from_user.id} 查看帮助中心")


async def handle_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """帮助中心回调切页（按钮点击）"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    # ⛔ 关闭：删除消息
    if callback_data == "help_close":
        await query.message.delete()
        logger.info(f"[帮助] 用户 {query.from_user.id} 关闭帮助消息")
        return
    
    # ⏪ 返回主页
    if callback_data == "help_index":
        bot = context.bot
        bot_info = await bot.get_me()
        bot_name = bot_info.first_name
        bot_username = bot_info.username
        
        # 获取创建者信息
        bot_id = context.bot_data.get("bot_id", bot_username)
        bot_creator = await _get_bot_creator(bot, bot_id)
        
        text = build_help_page("index", bot_name, bot_creator)
        keyboard = help_keyboard("index")
        
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"[帮助] 用户 {query.from_user.id} 返回帮助主页")
        return
    
    # 分类页面切换
    page = PAGE_MAP.get(callback_data, "basic")
    
    text = build_help_page(page)
    keyboard = help_keyboard(page)
    
    # ✅ 关键：编辑原消息，不刷屏
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
    logger.info(f"[帮助] 用户 {query.from_user.id} 切换到页面: {page}")

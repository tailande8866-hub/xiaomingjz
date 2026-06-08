"""
私聊关键词配置处理器 - 需要管理员权限，默认对所有授权群组生效
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from ..services.custom_keyword_service import CustomKeywordService
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.state_manager import clear_state

logger = logging.getLogger(__name__)


async def handle_private_keyword_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理私聊关键词菜单
    
    入口：用户私聊机器人发送"关键词回复"命令
    """
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 检查是否为私聊
    if update.effective_chat.type != 'private':
        await update.message.reply_text(
            "🚫 私聊关键词配置仅限在私聊中使用\n\n"
            "请私聊机器人进行关键词配置"
        )
        return
    
    # 检查管理员权限（超级管理员或数据库中的管理员）
    from ..utils.role_checker import is_super_admin, is_admin
    bot_id = get_current_bot_id(context)

    if not await is_super_admin(user.id, bot_id=bot_id) and not await is_admin(user.id, bot_id=bot_id):
        await update.message.reply_text(
            " 权限不足\n\n"
            "此功能仅限管理员使用\n"
            "请联系超级管理员添加您为管理员"
        )
        return
    
    # 显示关键词配置菜单
    
    # 获取全局关键词列表
    keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
    
    text = "💬 <b>私聊关键词配置</b>\n\n"
    text += "📌 <b>说明：</b>\n"
    text += "• 私聊配置的关键词将对<b>所有授权群组</b>生效\n"
    text += "• 需要管理员权限才能配置\n"
    text += "• 群组内配置的关键词优先级更高\n\n"
    
    if keywords:
        text += f"📝 当前全局关键词（共{len(keywords)}个）：\n\n"
        for kw in keywords[:10]:  # 最多显示10个
            text += f"🔑 <code>{kw.keyword}</code>\n"
            text += f"   💬 {kw.reply_text[:50]}\n\n"
        if len(keywords) > 10:
            text += f"...还有 {len(keywords) - 10} 个关键词\n\n"
    else:
        text += "📭 当前没有配置全局关键词\n\n"
    
    text += "<b>使用方法：</b>\n"
    text += "• 添加关键词：发送 <code>添加关键词 关键词|回复内容</code>\n"
    text += "• 删除关键词：发送 <code>删除关键词 关键词</code>\n"
    text += "• 查看关键词：发送 <code>查看关键词</code>\n\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加关键词", callback_data="private_keyword_add")],
        [InlineKeyboardButton("🗑️ 删除关键词", callback_data="private_keyword_delete")],
        [InlineKeyboardButton("📋 查看关键词", callback_data="private_keyword_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)


async def handle_private_keyword_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理私聊关键词回调按钮
    """
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    callback_data = query.data
    
    # 检查管理员权限
    from ..utils.role_checker import is_super_admin, is_admin
    bot_id = get_current_bot_id(context)

    if not await is_super_admin(user.id, bot_id=bot_id) and not await is_admin(user.id, bot_id=bot_id):
        await query.edit_message_text("❌ 权限不足")
        return
    
    if callback_data == "private_keyword_menu":
        clear_state(context, "awaiting_keyword_input", "keyword_action")
        text, reply_markup = await _build_private_keyword_menu(bot_id)
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return

    if callback_data == "private_keyword_add":
        await query.edit_message_text(
            "➕ <b>添加全局关键词</b>\n\n"
            "请按照以下格式发送：\n"
            "<code>关键词|回复内容</code>\n\n"
            "示例：\n"
            "<code>你好|您好！欢迎使用记账机器人</code>\n"
            "<code>帮助|请输入 /help 查看帮助</code>\n\n"
            "⚠️ 注意：\n"
            "• 这个关键词将对<b>所有授权群组</b>生效\n"
            "• 如果关键词已存在，将会更新回复内容\n"
            "• 支持多行回复内容",
            parse_mode='HTML'
        )
        context.user_data['awaiting_keyword_input'] = True
        context.user_data['keyword_action'] = 'add'
        
    elif callback_data == "private_keyword_delete":
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
        
        if not keywords:
            await query.edit_message_text("📭 当前没有全局关键词可删除")
            return
        
        # 构建删除选择键盘
        keyboard = []
        row = []
        for kw in keywords[:20]:  # 最多显示20个
            row.append(InlineKeyboardButton(kw.keyword[:15], callback_data=f"del_kw_{kw.keyword}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="private_keyword_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🗑️ <b>删除全局关键词</b>\n\n"
            "请选择要删除的关键词：",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        
    elif callback_data == "private_keyword_list":
        keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
        
        if not keywords:
            await query.edit_message_text("📭 当前没有配置全局关键词")
            return
        
        text = "📋 <b>全局关键词列表</b>\n\n"
        for idx, kw in enumerate(keywords, 1):
            text += f"{idx}. 🔑 <code>{kw.keyword}</code>\n"
            text += f"   💬 {kw.reply_text[:80]}\n\n"
        
        text += f"\n共 {len(keywords)} 个关键词"
        
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="private_keyword_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)


async def _build_private_keyword_menu(bot_id: str):
    keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)

    text = "💬 <b>私聊关键词配置</b>\n\n"
    text += "📌 <b>说明：</b>\n"
    text += "• 私聊配置的关键词将对<b>所有授权群组</b>生效\n"
    text += "• 需要管理员权限才能配置\n"
    text += "• 群组内配置的关键词优先级更高\n\n"

    if keywords:
        text += f"📝 当前全局关键词（共{len(keywords)}个）：\n\n"
        for kw in keywords[:10]:
            text += f"🔑 <code>{kw.keyword}</code>\n"
            text += f"   💬 {kw.reply_text[:50]}\n\n"
        if len(keywords) > 10:
            text += f"...还有 {len(keywords) - 10} 个关键词\n\n"
    else:
        text += "📭 当前没有配置全局关键词\n\n"

    text += "<b>使用方法：</b>\n"
    text += "• 添加关键词：发送 <code>添加关键词 关键词|回复内容</code>\n"
    text += "• 删除关键词：发送 <code>删除关键词 关键词</code>\n"
    text += "• 查看关键词：发送 <code>查看关键词</code>\n\n"

    keyboard = [
        [InlineKeyboardButton("➕ 添加关键词", callback_data="private_keyword_add")],
        [InlineKeyboardButton("🗑️ 删除关键词", callback_data="private_keyword_delete")],
        [InlineKeyboardButton("📋 查看关键词", callback_data="private_keyword_list")]
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def handle_private_keyword_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理私聊关键词输入
    
    当用户处于等待输入状态时，处理关键词添加
    """
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    text = update.message.text.strip()
    
    # 检查是否在等待输入状态
    if not context.user_data.get('awaiting_keyword_input'):
        return
    
    # 清除等待状态
    context.user_data.pop('awaiting_keyword_input', None)
    action = context.user_data.pop('keyword_action', None)
    
    if action != 'add':
        return
    
    # 解析关键词和回复内容
    if "|" not in text:
        await update.message.reply_text(
            "❌ 格式错误\n\n"
            "正确格式：<code>关键词|回复内容</code>\n\n"
            "示例：<code>你好|您好！欢迎使用</code>"
        )
        return
    
    parts = text.split("|", 1)
    keyword = parts[0].strip()
    reply_text = parts[1].strip()
    
    if not keyword or not reply_text:
        await update.message.reply_text("❌ 关键词和回复内容不能为空")
        return
    
    # 添加关键词（全局，group_id=0）
    bot_id = get_current_bot_id(context)
    success = await CustomKeywordService.add_keyword(
        bot_id=bot_id,
        keyword=keyword,
        reply_text=reply_text,
        group_id=0,  # 全局关键词
        created_by=user.id
    )
    
    if success:
        await update.message.reply_text(
            f"✅ 已成功添加全局关键词\n\n"
            f"🔑 关键词：<code>{keyword}</code>\n"
            f"💬 回复内容：{reply_text[:100]}\n\n"
            f"📌 此关键词将对<b>所有授权群组</b>生效",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("❌ 添加关键词失败，请稍后重试")


async def handle_view_keywords_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理私聊中直接发送的"查看关键词"命令
    
    入口：用户私聊机器人发送"查看关键词"命令
    """
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    
    # 检查是否为私聊
    if update.effective_chat.type != 'private':
        return
    
    # 检查是否是查看关键词命令
    if text not in ["查看关键词", "关键词列表"]:
        return
    
    # 检查管理员权限（超级管理员或数据库中的管理员）
    from ..utils.role_checker import is_super_admin, is_admin
    bot_id = get_current_bot_id(context)

    if not await is_super_admin(user.id, bot_id=bot_id) and not await is_admin(user.id, bot_id=bot_id):
        await update.message.reply_text(
            "❌ 权限不足\n\n"
            "此功能仅限管理员使用\n"
            "请联系超级管理员添加您为管理员"
        )
        return
    
    # 获取全局关键词列表
    keywords = await CustomKeywordService.get_keywords(bot_id, group_id=0)
    
    if not keywords:
        await update.message.reply_text("📭 当前没有配置全局关键词")
        return
    
    text_response = "📋 <b>全局关键词列表</b>\n\n"
    for idx, kw in enumerate(keywords, 1):
        text_response += f"{idx}. 🔑 <code>{kw.keyword}</code>\n"
        text_response += f"   💬 {kw.reply_text[:80]}\n\n"
    
    text_response += f"\n共 {len(keywords)} 个关键词"
    
    keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="private_keyword_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text_response, parse_mode='HTML', reply_markup=reply_markup)


async def handle_delete_keyword_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理删除关键词回调
    """
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("del_kw_"):
        return
    
    keyword = query.data.replace("del_kw_", "", 1)
    
    bot_id = get_current_bot_id(context)
    success = await CustomKeywordService.delete_keyword(bot_id, keyword, group_id=0)
    
    if success:
        await query.edit_message_text(f"✅ 已删除全局关键词：<code>{keyword}</code>", parse_mode='HTML')
    else:
        await query.edit_message_text(f"❌ 删除失败，关键词不存在")

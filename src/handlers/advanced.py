"""
高级功能处理器 - 广播、统计、设置、分组管理
"""
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, func, and_
from datetime import datetime
import asyncio

from ..models import Group, GroupOperator, UserConfig, Transaction, PrivateChatUser, get_db
from ..utils.state_manager import clear_state
from ..utils.tenant_scope import scoped_query, scoped_insert
from ..utils.permission_checker import require_authorized_group  # 🔐 新增：授权检查装饰器

logger = logging.getLogger(__name__)


async def handle_broadcast_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理“广播所有用户”按钮"""
    if not update.message or not update.effective_chat:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🆕 限流检查：每小时最多 5 次广播
    from ..utils.rate_limiter import rate_limiter
    if await rate_limiter.check_limit(user.id, action="broadcast"):
        remaining = await rate_limiter.get_remaining(user.id, action="broadcast")
        await update.message.reply_text(
            f"⚠️ 操作过于频繁\n\n"
            f"广播限制：每小时最多 5 次\n"
            f"剩余次数：{remaining} 次"
        )
        return
    
    # 检查操作权限
    async for db in get_db():
        from .operator import is_operator
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return
        
        # 🔑 获取 bot_id（多租户隔离）
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
        
        # 获取所有私聊用户（带 bot_id 过滤）
        query = select(PrivateChatUser.user_id).where(PrivateChatUser.bot_id == bot_id)
        result = await db.execute(query)
        user_ids = [row[0] for row in result.all()]
        
        if not user_ids:
            await update.message.reply_text("📭 当前没有任何用户记录")
            return
        
        await update.message.reply_text(
            f"📢 广播所有用户\n\n"
            f"找到 {len(user_ids)} 个用户\n\n"
            f"请输入要广播的消息内容：\n"
            f"（输入 /cancel 取消）"
        )
        
        # 设置等待广播消息的状态
        context.user_data['waiting_for_broadcast'] = True
        context.user_data['broadcast_chat_id'] = chat_id


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理广播消息的实际发送（带状态检查）"""
    if not update.message or not update.effective_chat:
        return
    
    user_data = context.user_data
    
    # 检查是否在等待广播消息
    if not user_data.get('waiting_for_broadcast'):
        return
    
    chat_id = update.effective_chat.id
    message_text = update.message.text
    
    # 清除等待状态（使用统一的状态管理工具）
    clear_state(context, 'waiting_for_broadcast', 'broadcast_chat_id')
    
    async for db in get_db():
        # 🔑 获取 bot_id（多租户隔离）
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
        
        # 获取所有私聊用户（带 bot_id 过滤）
        query = select(PrivateChatUser.user_id).where(PrivateChatUser.bot_id == bot_id)
        result = await db.execute(query)
        user_ids = [row[0] for row in result.all()]
        
        if not user_ids:
            await update.message.reply_text("📭 当前没有任何用户记录")
            return
        
        success_count = 0
        fail_count = 0
        
        # 向每个用户私聊发送消息
        for uid in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=message_text,
                    parse_mode="HTML"
                )
                success_count += 1
                # 避免频繁请求，稍作延迟
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"广播到用户 {uid} 失败: {str(e)}")
                fail_count += 1
        
        result_text = (
            f"✅ 广播完成\n\n"
            f"成功发送：{success_count} 个用户\n"
            f"发送失败：{fail_count} 个用户\n\n"
            f"广播内容：\n{message_text[:200]}{'...' if len(message_text) > 200 else ''}"
        )
        
        await update.message.reply_text(result_text)





async def handle_bot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理"机器人设置"按钮"""
    if not update.message:
        return
    
    # 显示机器人设置菜单（底部固定键盘）
    keyboard = [
        [KeyboardButton("📝 设置机器人描述"), KeyboardButton("👋 设置欢迎语")],
        [KeyboardButton("💬 设置客服"), KeyboardButton("❌ 关闭")]  
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    settings_text = (
        "️ <b>机器人设置</b>\n\n"
        "您可以修改机器人的名称、详情描述或头像。\n\n"
        "请选择要设置的选项："
    )
    
    await update.message.reply_text(settings_text, reply_markup=reply_markup, parse_mode="HTML")


async def handle_group_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理"分组管理"按钮"""
    if not update.message or not update.effective_chat:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    async for db in get_db():
        from .operator import is_operator
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return
        
        # 获取当前群组信息
        query = scoped_query(Group).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()
        
        if not group:
            await update.message.reply_text("❌ 未找到群组信息")
            return
        
        keyboard = [
            [KeyboardButton("🏷️ 设置分组标签"), KeyboardButton("📋 查看分组"), KeyboardButton(" 返回主菜单")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        current_tag = group.group_tag or "未设置"
        
        group_text = (
            f"👥 **分组管理**\n\n"
            f"当前群组：{group.group_name}\n"
            f"当前分组：{current_tag}\n\n"
            f"请输入新的分组标签：\n"
            f"（输入 /cancel 取消）"
        )
        
        await update.message.reply_text(group_text, reply_markup=reply_markup, parse_mode="Markdown")
        
        # 设置等待分组标签的状态
        context.user_data['waiting_for_group_tag'] = True
        context.user_data['group_tag_chat_id'] = chat_id


@require_authorized_group  # 🔐 新增：要求群组已授权
async def handle_group_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理“群发广播”按钮"""
    if not update.message or not update.effective_chat:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 🔑 获取 bot_id（多租户隔离）
    from ..utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    
    async for db in get_db():
        from .operator import is_operator
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return
        
        # 获取所有分组（带 bot_id 过滤）
        query = select(func.distinct(Group.group_tag)).where(
            and_(
                Group.bot_id == bot_id,
                Group.group_tag.isnot(None)
            )
        )
        result = await db.execute(query)
        tags = result.scalars().all()
        
        if not tags:
            await update.message.reply_text(
                "📭 当前没有设置分组的群组\n\n"
                "请先使用\"分组管理\"设置分组标签"
            )
            return
        
        tags_list = "\n".join([f"• {tag}" for tag in tags])
        
        keyboard = []
        tag_list = list(tags)
        for i in range(0, len(tag_list), 3):
            row = [KeyboardButton(tag) for tag in tag_list[i:i+3]]
            keyboard.append(row)
        keyboard.append([KeyboardButton("← 返回主菜单")])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        broadcast_text = (
            f"📡 **群发广播**\n\n"
            f"请选择要广播的分组：\n\n"
            f"{tags_list}\n\n"
            f"或直接输入分组名称"
        )
        
        await update.message.reply_text(broadcast_text, reply_markup=reply_markup, parse_mode="Markdown")
        
        # 设置等待选择分组的状态
        context.user_data['waiting_for_broadcast_group'] = True
        context.user_data['broadcast_group_chat_id'] = chat_id


async def handle_group_tag_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理分组标签的输入和保存（带状态检查）"""
    if not update.message or not update.effective_chat:
        return
    
    user_data = context.user_data
    
    # 检查是否在等待分组标签
    if not user_data.get('waiting_for_group_tag'):
        return
    
    chat_id = update.effective_chat.id
    tag_text = update.message.text.strip()
    
    # 清除等待状态（使用统一的状态管理工具）
    clear_state(context, 'waiting_for_group_tag', 'group_tag_chat_id')
    
    async for db in get_db():
        # 获取当前群组
        query = scoped_query(Group).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()
        
        if not group:
            await update.message.reply_text("❌ 未找到群组信息")
            return
        
        # 更新分组标签
        old_tag = group.group_tag or "未设置"
        group.group_tag = tag_text
        await db.commit()
        
        await update.message.reply_text(
            f"✅ 分组标签已更新\n\n"
            f"原标签：{old_tag}\n"
            f"新标签：{tag_text}"
        )


async def handle_group_broadcast_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按分组广播的选择（带状态检查）"""
    if not update.message or not update.effective_chat:
        return
    
    user_data = context.user_data
    
    # 检查是否在等待选择分组
    if not user_data.get('waiting_for_broadcast_group'):
        return
    
    chat_id = update.effective_chat.id
    selected_tag = update.message.text.strip()
    
    # 如果是返回主菜单按钮，清除状态
    if selected_tag == "← 返回主菜单":
        clear_state(context, 'waiting_for_broadcast_group', 'broadcast_group_chat_id')
        await update.message.reply_text("已取消群发广播")
        return
    
    # 清除等待状态（使用统一的状态管理工具）
    clear_state(context, 'waiting_for_broadcast_group', 'broadcast_group_chat_id')
    
    async for db in get_db():
        # 查找该分组的所有活跃群组
        query = scoped_query(Group).where(
            (Group.group_tag == selected_tag) & (Group.is_active.is_(True))
        )
        result = await db.execute(query)
        groups = result.scalars().all()
        
        if not groups:
            await update.message.reply_text(f"📭 分组 '{selected_tag}' 下没有活跃的群组")
            return
        
        # 设置等待广播消息的状态
        user_data['waiting_for_group_broadcast_message'] = True
        user_data['broadcast_target_tag'] = selected_tag
        
        await update.message.reply_text(
            f"📡 **群发广播**\n\n"
            f"目标分组：{selected_tag}\n"
            f"群组数量：{len(groups)}\n\n"
            f"请输入要广播的消息内容：\n"
            f"（输入 /cancel 取消）",
            parse_mode="Markdown"
        )


async def handle_group_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按分组广播消息的实际发送（带状态检查）"""
    if not update.message or not update.effective_chat:
        return
    
    user_data = context.user_data
    
    # 检查是否在等待分组广播消息
    if not user_data.get('waiting_for_group_broadcast_message'):
        return
    
    chat_id = update.effective_chat.id
    message_text = update.message.text
    target_tag = user_data.get('broadcast_target_tag', '')
    
    # 清除等待状态（使用统一的状态管理工具）
    clear_state(context, 'waiting_for_group_broadcast_message', 'broadcast_target_tag')
    
    async for db in get_db():
        # 获取该分组的所有活跃群组
        query = scoped_query(Group).where(
            (Group.group_tag == target_tag) & (Group.is_active.is_(True))
        )
        result = await db.execute(query)
        groups = result.scalars().all()
        
        if not groups:
            await update.message.reply_text(f"📭 分组 '{target_tag}' 下没有活跃的群组")
            return
        
        success_count = 0
        fail_count = 0
        
        # 向每个群组发送消息
        for group in groups:
            try:
                await context.bot.send_message(
                    chat_id=group.group_id,
                    text=message_text,
                    parse_mode="HTML"
                )
                success_count += 1
                # 避免频繁请求，稍作延迟
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"广播到群组 {group.group_id} 失败: {str(e)}")
                fail_count += 1
        
        result_text = (
            f"✅ 分组广播完成\n\n"
            f"目标分组：{target_tag}\n"
            f"成功发送：{success_count} 个群组\n"
            f"发送失败：{fail_count} 个群组\n\n"
            f"广播内容：\n{message_text[:200]}{'...' if len(message_text) > 200 else ''}"
        )
        
        await update.message.reply_text(result_text)



async def handle_ad_content_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理广告内容的输入和保存"""
    if not update.message or not update.effective_chat:
        return
    
    user_data = context.user_data
    
    # 检查是否在等待广告内容
    if not user_data.get('waiting_for_ad_content'):
        return
    
    chat_id = update.effective_chat.id
    ad_text = update.message.text.strip()
    
    # 清除等待状态（使用统一的状态管理工具）
    clear_state(context, 'waiting_for_ad_content', 'ad_chat_id')
    
    async for db in get_db():
        # 获取当前群组
        query = scoped_query(Group).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()
        
        if not group:
            await update.message.reply_text("❌ 未找到群组信息")
            return
        
        # 更新广告内容
        old_ad = group.top_ad or "未设置"
        group.top_ad = ad_text
        await db.commit()
        
        await update.message.reply_text(
            f"✅ 顶部广告已更新\n\n"
            f"原广告：{old_ad}\n"
            f"新广告：{ad_text[:100]}{'...' if len(ad_text) > 100 else ''}"
        )



async def handle_bot_set_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理"设置机器人描述"按钮点击"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    text = (
        "📝 <b>设置机器人描述</b>\n\n"
        "请发送您想要设置的机器人描述内容。\n\n"
        "<b>提示：</b>\n"
        "• 描述会显示在机器人资料页\n"
        "• 建议简洁明了，让用户快速了解机器人功能\n"
        "• 发送 <code>/cancel</code> 取消操作"
    )
    
    await query.edit_message_text(text, parse_mode='HTML')
    context.user_data['waiting_for_bot_description'] = True



async def handle_bot_set_customer_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理"设置客服"按钮点击"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    text = (
        "💬 <b>设置客服</b>\n\n"
        "请发送客服的Telegram用户名或链接。\n\n"
        "<b>格式示例：</b>\n"
        "• 用户名：<code>@username</code>\n"
        "• 链接：<code>https://t.me/username</code>\n\n"
        "• 发送 <code>/cancel</code> 取消操作"
    )
    
    await query.edit_message_text(text, parse_mode='HTML')
    context.user_data['waiting_for_customer_service'] = True


async def handle_bot_close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理"关闭"按钮点击"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    await query.delete_message()


async def handle_bot_settings_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理机器人设置的用户输入"""
    if not update.message or not update.message.text:
        return
    
    # 检查是否在等待机器人描述
    if context.user_data.get('waiting_for_bot_description'):
        description = update.message.text
        
        # 取消操作
        if description.lower() in ['/cancel', '取消']:
            context.user_data['waiting_for_bot_description'] = False
            await update.message.reply_text(" 已取消设置机器人描述")
            return
        
        # 保存描述（这里只是提示，实际需要调用Telegram Bot API）
        context.user_data['waiting_for_bot_description'] = False
        context.user_data['bot_description'] = description
        
        await update.message.reply_text(
            f"✅ <b>机器人描述设置成功!</b>\n\n"
            f"描述内容：{description}\n\n"
            f"<b>注意：</b>此功能需要调用Telegram Bot API的setMyDescription方法才能真正生效。\n"
            f"如需使用，请确保机器人有足够的权限。",
            parse_mode='HTML'
        )
        return
    
    # 检查是否在等待客服设置
    if context.user_data.get('waiting_for_customer_service'):
        customer_service = update.message.text
        
        # 取消操作
        if customer_service.lower() in ['/cancel', '取消']:
            context.user_data['waiting_for_customer_service'] = False
            await update.message.reply_text("❌ 已取消设置客服")
            return
        
        # 保存客服信息
        context.user_data['waiting_for_customer_service'] = False
        context.user_data['customer_service'] = customer_service
        
        await update.message.reply_text(
            f"✅ <b>客服设置成功!</b>\n\n"
            f"客服信息：{customer_service}\n\n"
            f"<b>注意：</b>此设置已保存到本地，您可以在欢迎语或其他地方使用此客服信息。",
            parse_mode='HTML'
        )
        return
    
    # 如果没有匹配任何状态，返回None让其他Handler处理
    return None





"""
自定义功能处理器 - 关键词回复、自定义按钮、@all通知、欢迎语
"""
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, delete as sql_delete

from ..models import Group, CustomKeyword, CustomButton, GroupOperator, get_db
from ..utils.tenant_scope import scoped_query, scoped_query_with_filters, scoped_insert, scoped_count
from .operator import is_operator
from ..utils.permission_checker import require_authorized_group  # 🔐 新增：授权检查装饰器

logger = logging.getLogger(__name__)


@require_authorized_group  # 🔐 新增：要求群组已授权
async def handle_keyword_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理关键词配置命令
    
    支持两种场景：
    1. 私聊中：创建全局关键词（对所有授权群生效）
    2. 群组中：创建群组关键词（仅当前群生效）
    
    命令格式：创建关键词 关键词|回复内容
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()
    is_private = (update.effective_chat.type == 'private')
    
    async for db in get_db():
        # 权限检查
        if is_private:
            # 私聊配置全局关键词：需要Bot管理员权限
            from ..utils.role_checker import is_super_admin, is_admin
            bot_id = context.application.bot_data.get('bot_id')

            if not await is_super_admin(user.id, bot_id=bot_id) and not await is_admin(user.id, bot_id=bot_id):
                await update.message.reply_text("❌ 权限不足\n仅Bot管理员可以配置全局关键词")
                return
        else:
            # 群组配置群关键词：需要群组操作人权限
            if not await is_operator(user.id, chat_id, db):
                await update.message.reply_text("❌ 权限不足\n仅群组管理员可以配置群关键词")
                return
        
        # 解析命令
        if text == "关键词配置":
            # 显示已配置的关键词列表
            if is_private:
                # 私聊：显示全局关键词
                query = scoped_query_with_filters(CustomKeyword, context, group_id=0, is_active=True)
                scope_text = "全局关键词（所有授权群生效）"
            else:
                # 群组：显示当前群关键词
                query = scoped_query_with_filters(CustomKeyword, context, group_id=chat_id, is_active=True)
                scope_text = f"群组关键词（仅当前群生效）"
            
            result = await db.execute(query)
            keywords = result.scalars().all()
            
            if not keywords:
                msg = f"📭 {scope_text}\n\n暂无已添加关键词回复\n\n"
                msg += "💡 你可以发送：\n"
                msg += "<code>创建关键词 关键词|回复内容</code>\n\n"
                msg += "例如：\n"
                msg += "<code>创建关键词 地址|我们的官网是 https://example.com</code>"
                await update.message.reply_text(msg, parse_mode='HTML')
            else:
                msg = f"📝 {scope_text}\n\n"
                # 1行2个按钮的格式显示
                for i in range(0, len(keywords), 2):
                    kw1 = keywords[i]
                    if i + 1 < len(keywords):
                        kw2 = keywords[i + 1]
                        msg += f"🔹 <code>{kw1.keyword}</code>  🔹 <code>{kw2.keyword}</code>\n"
                    else:
                        msg += f"🔹 <code>{kw1.keyword}</code>\n"
                
                msg += f"\n共 {len(keywords)} 个关键词\n\n"
                msg += "💡 添加新关键词：\n"
                msg += "<code>创建关键词 关键词|回复内容</code>\n\n"
                msg += "💡 删除关键词：\n"
                msg += "<code>删除关键词 关键词</code>"
                await update.message.reply_text(msg, parse_mode='HTML')
        
        elif text.startswith("创建关键词"):
            # 创建关键词
            parts = text.split(" ", 1)
            if len(parts) < 2:
                await update.message.reply_text(
                    "❌ 格式错误\n\n"
                    "正确格式：<code>创建关键词 关键词|回复内容</code>\n\n"
                    "例如：\n"
                    "<code>创建关键词 地址|我们的官网是 https://example.com</code>",
                    parse_mode='HTML'
                )
                return
            
            config_text = parts[1].strip()
            if "|" not in config_text:
                await update.message.reply_text(
                    "❌ 格式错误\n\n"
                    "请使用 | 分隔关键词和回复内容\n\n"
                    "例如：\n"
                    "<code>创建关键词 地址|我们的官网是 https://example.com</code>",
                    parse_mode='HTML'
                )
                return
            
            keyword, reply_text = config_text.split("|", 1)
            keyword = keyword.strip()
            reply_text = reply_text.strip()
            
            if not keyword or not reply_text:
                await update.message.reply_text("❌ 关键词和回复内容不能为空")
                return
            
            # 确定作用域
            if is_private:
                target_group_id = 0  # 全局关键词
                scope_text = "全局（所有授权群生效）"
            else:
                target_group_id = chat_id  # 群组关键词
                scope_text = "当前群组"
            
            # 检查是否已存在
            query = scoped_query_with_filters(CustomKeyword, context, group_id=target_group_id, keyword=keyword)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                # 更新现有关键词
                existing.reply_text = reply_text
                existing.is_active = True
                action_text = "已更新"
            else:
                # 创建新关键词
                new_keyword = scoped_insert(
                    CustomKeyword(
                        group_id=target_group_id,
                        keyword=keyword,
                        reply_text=reply_text,
                        is_active=True,
                        created_by=user.id
                    ),
                    context
                )
                db.add(new_keyword)
                action_text = "已添加"
            
            await db.commit()
            
            await update.message.reply_text(
                f"✅ {action_text}关键词\n\n"
                f"🔑 关键词：<code>{keyword}</code>\n"
                f"💬 回复内容：{reply_text[:100]}{'...' if len(reply_text) > 100 else ''}\n"
                f"📍 作用范围：{scope_text}",
                parse_mode='HTML'
            )
        
        elif text.startswith("删除关键词"):
            # 删除关键词
            parts = text.split(" ", 1)
            if len(parts) < 2:
                await update.message.reply_text(
                    "❌ 格式错误\n\n"
                    "正确格式：<code>删除关键词 关键词</code>",
                    parse_mode='HTML'
                )
                return
            
            keyword = parts[1].strip()
            
            # 确定作用域
            if is_private:
                target_group_id = 0  # 全局关键词
                scope_text = "全局"
            else:
                target_group_id = chat_id  # 群组关键词
                scope_text = "当前群组"
            
            # 查找关键词
            query = scoped_query_with_filters(CustomKeyword, context, group_id=target_group_id, keyword=keyword)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                existing.is_active = False
                await db.commit()
                await update.message.reply_text(
                    f"✅ 已删除{scope_text}关键词：<code>{keyword}</code>",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    f"❌ 未找到{scope_text}关键词：<code>{keyword}</code>\n\n"
                    f"💡 提示：私聊删除的是全局关键词，群内删除的是群关键词",
                    parse_mode='HTML'
                )


async def handle_custom_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理自定义按钮配置（仅限私聊 + 最高权限人）"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()
    
    # 检查是否为私聊（群组不允许设置）
    if update.effective_chat.type != 'private':
        await update.message.reply_text(
            "🚫 按钮配置仅限创始人在私聊中配置使用\n\n"
            "请私聊机器人进行按钮配置"
        )
        return
    
    logger.info(f"处理按钮命令(私聊): {text}, 用户: {user.id}")
    
    async for db in get_db():
        # 检查是否为最高权限人（全局操作人或超级管理员）
        from ..utils.role_checker import is_super_admin
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
        
        # ✅ 关键修复：使用 scoped_query 自动添加 bot_id 过滤
        query = scoped_query_with_filters(GroupOperator, context, user_id=user.id, is_global=True)
        result = await db.execute(query)
        global_operator = result.scalar_one_or_none()
        
        super_admin = await is_super_admin(user.id, bot_id=bot_id)
        
        logger.info(f"用户 {user.id} 权限检查 - 全局操作人: {global_operator is not None}, 超级管理员: {super_admin}")
        
        if not global_operator and not super_admin:
            await update.message.reply_text(
                "权限不足\n"
                "此功能仅限最高权限人（全局操作人或超级管理员）使用"
            )
            return
        
        # 解析命令：添加按钮（不带参数则显示帮助）
        if text == "添加按钮" or text == "自定义按钮" or text == "创建账单按钮方式":
            await update.message.reply_text(
                "<b>🔘 按钮配置说明</b>\n\n"
                "<b>命令格式：</b>\n"
                "<code>添加按钮 按钮名称 URL [行号]</code>\n\n"
                "<b>示例：</b>\n"
                "<code>添加按钮 官网 https://example.com 1</code>\n"
                "<code>添加按钮 帮助中心 https://help.example.com 2</code>\n"
                "<code>添加按钮 联系客服 https://t.me/support 1</code>\n\n"
                "<b>参数说明：</b>\n"
                "• <b>按钮名称</b>：按钮显示的文字\n"
                "• <b>URL</b>：按钮点击后跳转的链接（必须是http://或https://开头）\n"
                "• <b>[行号]</b>：可选参数，决定按钮在哪一行显示（默认为1）\n\n"
                "<b>效果：</b>\n"
                "• 行号1的按钮会在第1行显示\n"
                "• 行号2的按钮会在第2行显示\n"
                "• 每行最多显示2个按钮\n\n"
                "<b>⚠️ 注意事项：</b>\n"
                "• 仅限超级管理员和管理员使用\n"
                "• 全局生效：在该bot授权的所有群组中显示\n"
                "• 管理员只能删除自己创建的按钮\n"
                "• 建议每行不超过2个，总共不超过10个\n\n"
                "<b>相关命令：</b>\n"
                "• <code>查看按钮</code> - 查看所有按钮\n"
                "• <code>删除按钮 按钮名称</code> - 删除指定按钮",
                parse_mode="HTML"
            )
        
        # 解析命令：添加按钮 按钮名称 URL [行号]
        elif text.startswith("添加按钮 ") or text.startswith("自定义按钮 ") or text.startswith("设置按钮"):
            parts = text.split(" ", 1)
            if len(parts) < 2:
                await update.message.reply_text(
                    "❌ 格式错误\n\n"
                    "正确格式：<code>添加按钮 按钮名称 URL [行号]</code>\n\n"
                    "示例：\n"
                    "<code>添加按钮 官网 https://example.com 1</code>\n"
                    "<code>添加按钮 帮助中心 https://help.example.com</code>（默认行号1）",
                    parse_mode='HTML'
                )
                return
            
            config_text = parts[1].strip()
            
            # 解析参数：按钮名称 URL [行号]
            # 支持两种格式：
            # 1. 添加按钮 名称 URL （无行号，默认1）
            # 2. 添加按钮 名称 URL 行号
            tokens = config_text.split()
            
            if len(tokens) < 2:
                await update.message.reply_text(
                    "❌ 参数不足\n\n"
                    "至少需要提供按钮名称和URL\n\n"
                    "正确格式：<code>添加按钮 按钮名称 URL [行号]</code>",
                    parse_mode='HTML'
                )
                return
            
            # 提取行号（如果存在）
            row_number = 1  # 默认行号
            url = None
            button_name = None
            
            # 检查最后一个token是否为数字（行号）
            if len(tokens) >= 3 and tokens[-1].isdigit():
                row_number = int(tokens[-1])
                url = tokens[-2]
                button_name = " ".join(tokens[:-2])
            else:
                # 没有行号，最后两个是URL和名称
                url = tokens[-1]
                button_name = " ".join(tokens[:-1])
            
            # 验证按钮名称
            if not button_name or len(button_name.strip()) == 0:
                await update.message.reply_text("❌ 按钮名称不能为空")
                return
            
            button_name = button_name.strip()
            
            # 验证URL格式
            if not url:
                await update.message.reply_text("❌ URL不能为空")
                return
            
            if not url.startswith("http://") and not url.startswith("https://"):
                await update.message.reply_text("❌ URL必须以http://或https://开头")
                return
            
            # 验证行号范围（1-10）
            if row_number < 1 or row_number > 10:
                await update.message.reply_text("❌ 行号必须在1-10之间")
                return
            
            # 检查是否已存在同名按钮
            query = scoped_query_with_filters(CustomButton, context, group_id=0, button_text=button_name)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                # 更新现有按钮
                existing.button_url = url
                existing.sort_order = row_number
                existing.is_active = True
                action_text = "已更新"
            else:
                # 创建新按钮
                # ✅ 关键修复：使用 scoped_insert 自动注入 bot_id
                new_button = scoped_insert(
                    CustomButton(
                        group_id=0,  # 0表示全局按钮
                        button_text=button_name,
                        button_url=url,
                        sort_order=row_number,
                        is_active=True,
                        created_by=user.id
                    ),
                    context
                )
                db.add(new_button)
                action_text = "已添加"
            
            await db.commit()
            
            # 构建成功消息
            success_msg = (
                f"✅ {action_text}按钮成功！\n\n"
                f"🔘 按钮名称：<b>{button_name}</b>\n"
                f"🔗 链接：{url}\n"
                f"📍 行号：{row_number}\n\n"
                f"💡 提示：\n"
                f"• 该按钮将在所有群组中显示\n"
                f"• 在群组中发送 <code>+0</code> 查看效果\n"
                f"• 每行最多显示2个按钮\n"
                f"• 使用 <code>查看按钮</code> 查看所有按钮"
            )
            
            await update.message.reply_text(success_msg, parse_mode='HTML')
        
        # 解析命令：删除按钮 按钮名称
        elif text.startswith("删除按钮 "):
            parts = text.split(" ", 1)
            if len(parts) < 2:
                await update.message.reply_text(
                    "❌ 格式错误\n\n"
                    "正确格式：<code>删除按钮 按钮名称</code>\n\n"
                    "示例：<code>删除按钮 官网</code>",
                    parse_mode='HTML'
                )
                return
            
            button_name = parts[1].strip()
            
            # 查找按钮
            query = scoped_query_with_filters(CustomButton, context, group_id=0, button_text=button_name)
            result = await db.execute(query)
            button = result.scalar_one_or_none()
            
            if not button:
                await update.message.reply_text(f"❌ 未找到按钮：<code>{button_name}</code>", parse_mode='HTML')
                return
            
            # 权限检查：只能删除自己创建的按钮（超级管理员除外）
            from ..utils.role_checker import is_super_admin
            from ..utils.bot_id_middleware import get_current_bot_id
            super_admin = await is_super_admin(user.id, bot_id=get_current_bot_id(context))
            
            if not super_admin and button.created_by != user.id:
                await update.message.reply_text(
                    "❌ 权限不足\n\n"
                    "您只能删除自己创建的按钮\n"
                    "如需删除其他按钮，请联系超级管理员"
                )
                return
            
            # 删除按钮
            await db.delete(button)
            await db.commit()
            
            await update.message.reply_text(f"✅ 已删除按钮：<code>{button_name}</code>", parse_mode='HTML')
        
        # 解析命令：删除按钮（无参数，显示帮助）
        elif text == "删除按钮":
            await update.message.reply_text(
                "❌ 格式错误\n\n"
                "正确格式：<code>删除按钮 按钮名称</code>\n\n"
                "示例：<code>删除按钮 官网</code>\n\n"
                "💡 提示：\n"
                "• 管理员只能删除自己创建的按钮\n"
                "• 超级管理员可以删除任何按钮\n"
                "• 使用 <code>查看按钮</code> 查看所有按钮",
                parse_mode='HTML'
            )
        
        # 解析命令：查看按钮
        elif text == "查看按钮":
            # ✅ 关键修复：使用 scoped_query 自动添加 bot_id 过滤
            query = scoped_query_with_filters(CustomButton, context, group_id=0, is_active=True).order_by(CustomButton.sort_order)
            result = await db.execute(query)
            buttons = result.scalars().all()
            
            if not buttons:
                await update.message.reply_text(
                    "📭 当前没有配置任何按钮\n\n"
                    "💡 使用方法：\n"
                    "<code>添加按钮 按钮名称 URL [行号]</code>\n\n"
                    "示例：\n"
                    "<code>添加按钮 官网 https://example.com 1</code>\n"
                    "<code>添加按钮 帮助中心 https://help.example.com 2</code>",
                    parse_mode='HTML'
                )
            else:
                msg = "🔘 <b>按钮列表</b>\n\n"
                
                # 预检查是否为超级管理员（避免循环内重复检查）
                from ..utils.role_checker import is_super_admin
                from ..utils.bot_id_middleware import get_current_bot_id
                super_admin = await is_super_admin(user.id, bot_id=get_current_bot_id(context))
                
                # 按行号分组显示
                buttons_by_row = {}
                for btn in buttons:
                    row = btn.sort_order
                    if row not in buttons_by_row:
                        buttons_by_row[row] = []
                    buttons_by_row[row].append(btn)
                
                # 按行号排序显示
                for row_num in sorted(buttons_by_row.keys()):
                    row_buttons = buttons_by_row[row_num]
                    msg += f"<b>第{row_num}行：</b>\n"
                    for btn in row_buttons:
                        creator_info = ""
                        if btn.created_by == user.id:
                            creator_info = " (您的)"
                        elif super_admin:
                            creator_info = f" (创建者ID: {btn.created_by})"
                        
                        msg += f"  🔹 <b>{btn.button_text}</b>{creator_info}\n"
                        msg += f"     {btn.button_url}\n"
                    msg += "\n"
                
                msg += f"\n共 {len(buttons)} 个按钮\n\n"
                msg += "💡 管理按钮：\n"
                msg += "• <code>添加按钮 名称 URL [行号]</code> - 添加新按钮\n"
                msg += "• <code>删除按钮 名称</code> - 删除指定按钮"
                
                await update.message.reply_text(msg, parse_mode='HTML')


async def handle_mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理@all通知所有人"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()
    
    # 支持多种触发方式
    if text not in ["通知所有人", "@all", "@everyone"]:
        return
    
    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return
        
        # 获取群组信息
        # ✅ 关键修复：使用 scoped_query 自动添加 bot_id 过滤
        query = scoped_query_with_filters(Group, context, group_id=chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()
        
        if not group:
            await update.message.reply_text("❌ 未找到群组配置")
            return
        
        # 构建通知消息
        notification_text = (
            f"📢 <b>重要通知</b>\n\n"
            f"来自：{user.first_name or user.username}\n\n"
            f"请所有成员注意查看上方消息！"
        )
        
        try:
            # 尝试使用Telegram的mention_all功能（如果机器人是管理员）
            await context.bot.send_message(
                chat_id=chat_id,
                text=notification_text,
                parse_mode="HTML"
            )
            await update.message.reply_text("✅ 已发送通知")
        except Exception as e:
            logger.error(f"发送通知失败: {str(e)}")
            await update.message.reply_text("❌ 发送通知失败，请确保机器人是群组管理员")


# ==================== 关键词回复消息管理 ====================

# 缓存：记录每个群组的最后一条关键词回复消息ID
_keyword_last_reply_cache = {}


async def _delete_last_keyword_reply(context: ContextTypes.DEFAULT_TYPE, chat_id: int, bot_id: str):
    """删除上一条关键词回复消息"""
    cache_key = f"{bot_id}_{chat_id}"
    last_msg_id = _keyword_last_reply_cache.get(cache_key)
    if last_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
            logger.debug(f"[KEYWORD] 已删除上一条关键词回复 msg_id={last_msg_id} in chat={chat_id}")
        except Exception as e:
            logger.debug(f"[KEYWORD] 删除上一条关键词回复失败: {e}")
        _keyword_last_reply_cache.pop(cache_key, None)


async def _record_last_keyword_reply(chat_id: int, bot_id: str, message_id: int):
    """记录当前关键词回复消息ID"""
    cache_key = f"{bot_id}_{chat_id}"
    _keyword_last_reply_cache[cache_key] = message_id
    logger.debug(f"[KEYWORD] 记录关键词回复 msg_id={message_id} in chat={chat_id}")


async def _schedule_keyword_deletion(context: ContextTypes.DEFAULT_TYPE, chat_id: int, bot_id: str, message_id: int, minutes: int):
    """定时删除关键词回复消息"""
    async def delete_after_delay():
        await asyncio.sleep(minutes * 60)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"[KEYWORD] 定时删除关键词回复 msg_id={message_id} after {minutes}min")
        except Exception as e:
            logger.debug(f"[KEYWORD] 定时删除关键词回复失败: {e}")

    asyncio.create_task(delete_after_delay())
    logger.debug(f"[KEYWORD] 已安排 {minutes}分钟后删除关键词回复 msg_id={message_id}")


async def check_and_reply_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检查并回复自定义关键词（作为消息处理器）- 支持全局和群组关键词"""
    if not update.message or not update.effective_chat:
        return
    
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    
    # ✅ 关键修复：检查是否处于等待状态（广播分组输入、SaaS流程等）
    # 如果是，则不拦截消息，让专用的 handler 处理
    pending_action = context.user_data.get('pending_broadcast_group_action')
    waiting_broadcast_msg = context.user_data.get('waiting_broadcast_msg')
    waiting_for_broadcast_content = context.user_data.get('waiting_for_broadcast_content')
    waiting_saas_token = context.user_data.get('waiting_saas_token')
    waiting_rename_group = context.user_data.get('waiting_rename_group', False)
    waiting_for_rename_group_tag_name = context.user_data.get('waiting_for_rename_group_tag_name', False)
    waiting_usdt_alias = context.user_data.get('usdt_alias_state')  # ✅ USDT备注名输入状态
    
    # ✅ 关键修复：检查是否处于provision流程（手动开通套餐）
    # 如果是，则不拦截消息，让 handle_token_input 处理
    provision_state = context.user_data.get('provision_state')
    
    if pending_action or waiting_broadcast_msg or waiting_for_broadcast_content or waiting_saas_token or waiting_rename_group or waiting_for_rename_group_tag_name or waiting_usdt_alias or provision_state:
        logger.debug(f"[KEYWORD CHECK] 用户处于等待状态，跳过关键词检查: provision_state={provision_state}, pending_action={pending_action}, usdt_alias={waiting_usdt_alias}")
        return  # 不拦截，让专用的 handler 处理
    
    logger.info(f"收到消息: {text}, 聊天ID: {chat_id}")
    
    # 特殊处理：使用说明
    if text == "使用说明":
        logger.info("匹配到使用说明命令")
        # ✅ 重定向到新的帮助中心
        from src.services.help_builder import build_help_page
        from src.keyboards.help_keyboard import help_keyboard
        
        await update.message.reply_text(
            build_help_page("basic"),
            parse_mode="HTML",
            reply_markup=help_keyboard("basic")
        )
        return
    
    # 忽略命令和特殊消息
    if text.startswith("/") or text.startswith("+") or text.startswith("-"):
        return
    
    # ✅ 关键修复：忽略"开通"和"取消"消息，让它们传递给专用 handler
    if text.startswith("开通") or text == "取消":
        logger.debug(f"[KEYWORD_CHECK] Ignoring '{text}' to let provision handler process it")
        return
    
    # 使用新的关键词服务查找匹配的关键词
    from ..services.custom_keyword_service import CustomKeywordService
    from ..utils.bot_id_middleware import get_current_bot_id
    
    bot_id = get_current_bot_id(context)
    keyword_obj = await CustomKeywordService.find_matching_keyword(bot_id, chat_id, text)
    
    if keyword_obj:
        from ..services.global_config_service import global_config_service
        from ..models import get_db_session

        # 获取关键词配置（开关 + 删除设置）
        async with get_db_session() as db:
            keyword_enabled = await global_config_service.get_config(db, bot_id, "keyword_reply_enabled")
            delete_prev = await global_config_service.get_config(db, bot_id, "keyword_delete_prev")
            delete_minutes = await global_config_service.get_config(db, bot_id, "keyword_delete_minutes")

        is_enabled = keyword_enabled if isinstance(keyword_enabled, bool) else True
        if not is_enabled:
            logger.debug(f"[KEYWORD] 全局关键词回复已关闭，跳过")
            return

        is_delete_prev = delete_prev if isinstance(delete_prev, bool) else False
        auto_delete_minutes = delete_minutes if isinstance(delete_minutes, int) else 0

        # 删除上一条关键词回复
        if is_delete_prev:
            await _delete_last_keyword_reply(context, chat_id, bot_id)

        # 发送关键词回复
        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=keyword_obj.reply_text
        )

        # 记录当前回复消息
        if sent_msg:
            if is_delete_prev:
                await _record_last_keyword_reply(chat_id, bot_id, sent_msg.message_id)
            elif auto_delete_minutes > 0:
                await _schedule_keyword_deletion(context, chat_id, bot_id, sent_msg.message_id, auto_delete_minutes)

        return

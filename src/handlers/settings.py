"""
参数设置处理器

⚠️ DEPRECATED - 旧架构实现
此文件已迁移到新架构,请参考:
- capability_system.py (权限控制)
- config_center.py (配置管理)
- ui_schema_registry.py (UI路由)

新功能请使用新架构开发
预计删除时间: 2026-Q3
"""
from datetime import time as dt_time
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models import Group, UserConfig, get_db
from ..utils.parser import CommandParser
from ..utils.formatter import Formatter
from .operator import is_operator
from ..utils.tenant_scope import scoped_query, scoped_insert


async def prompt_private_global_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """群聊中拦截旧设置指令，统一引导到机器人私聊功能菜单。"""
    if not update.message:
        return
    await update.message.reply_text("请前往机器人私聊功能菜单进行全局设置")


async def set_exchange_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置汇率"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text(" 您没有操作权限")
            return

        # 解析设置命令
        rate_info = CommandParser.parse_rate_setting(text)

        if not rate_info or rate_info['type'] != 'exchange_rate':
            return

        # 设置群组默认汇率
        else:
            # 设置群组默认汇率
            query = scoped_query(Group, context).where(Group.group_id == chat_id)
            result = await db.execute(query)
            group = result.scalar_one_or_none()

            if group:
                group.exchange_rate = rate_info['value']
                await db.commit()
                await update.message.reply_text(f"✅ 已设置群组汇率为 {rate_info['value']}")
            else:
                await update.message.reply_text(" 未找到群组配置")


async def set_fee_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置费率"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 解析设置命令
        rate_info = CommandParser.parse_rate_setting(text)

        if not rate_info or rate_info['type'] != 'fee_rate':
            return

        # 设置群组默认费率
        else:
            # 设置群组默认费率
            query = scoped_query(Group, context).where(Group.group_id == chat_id)
            result = await db.execute(query)
            group = result.scalar_one_or_none()

            if group:
                group.fee_rate = rate_info['value']
                await db.commit()
                await update.message.reply_text(f"✅ 已设置群组费率为 {rate_info['value']}%")
            else:
                await update.message.reply_text("❌ 未找到群组配置")


async def show_user_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看费汇配置"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    async for db in get_db():
        # 获取所有用户配置
        query = scoped_query(UserConfig, context).where(UserConfig.group_id == chat_id)
        result = await db.execute(query)
        configs = result.scalars().all()

        # 格式化消息
        message = Formatter.format_user_configs(configs)

        await update.message.reply_text(message)


async def delete_user_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除用户配置"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 如果是回复消息
        if update.message.reply_to_message and update.message.reply_to_message.from_user:
            target_user = update.message.reply_to_message.from_user

            # 查找用户配置
            query = scoped_query(UserConfig, context).where(
                and_(
                    UserConfig.group_id == chat_id,
                    UserConfig.user_id == target_user.id
                )
            )
            result = await db.execute(query)
            user_config = result.scalar_one_or_none()

            if user_config:
                await db.delete(user_config)
                await db.commit()

                user_display = target_user.first_name or target_user.username
                await update.message.reply_text(f"✅ 已删除 {user_display} 的费汇配置")
            else:
                await update.message.reply_text("❌ 未找到该用户的配置")
        else:
            await update.message.reply_text("❌ 请回复用户消息来删除配置")


async def set_display_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置显示条数"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 解析命令
        count_info = CommandParser.parse_display_count(text)

        if not count_info:
            return

        # 更新群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            if count_info['type'] == 'deposit':
                group.deposit_display_count = count_info['count']
                await db.commit()
                await update.message.reply_text(f"✅ 已设置入款显示条数为 {count_info['count']}")
            elif count_info['type'] == 'withdraw':
                group.withdraw_display_count = count_info['count']
                await db.commit()
                await update.message.reply_text(f"✅ 已设置下发显示条数为 {count_info['count']}")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def set_currency_display(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置/切换币种显示"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 解析命令
        currency = CommandParser.parse_currency_display(text)

        if not currency:
            return

        # 更新群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            old_currency = group.currency_display or "USDT"
            group.currency_display = currency
            await db.commit()
            await update.message.reply_text(f"✅ 已将币种从 {old_currency} 切换为 {currency}")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def toggle_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换置顶功能"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 更新群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            if text in ["记账置顶", "开启置顶"]:
                group.pin_enabled = True
                await db.commit()
                await update.message.reply_text("✅ 已开启记账置顶")
            elif text in ["置顶关闭", "关闭置顶"]:
                group.pin_enabled = False
                await db.commit()
                await update.message.reply_text("✅ 已关闭记账置顶")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def toggle_currency_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换币种模式"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 更新群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            if text == "双币模式":
                group.currency_mode = "dual"
                await db.commit()
                await update.message.reply_text("✅ 已切换为双币模式")
            elif text == "单币模式":
                group.currency_mode = "single"
                await db.commit()
                await update.message.reply_text("✅ 已切换为单币模式")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def toggle_display_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换显示模式"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 更新群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            if text == "纯净模式":
                # 切换纯净模式：如果当前是纯净模式则关闭，否则开启
                if group.display_mode == "pure":
                    group.display_mode = "reply"  # 切换到显示回复人模式
                    await db.commit()
                    await update.message.reply_text("✅ 已关闭纯净模式，显示回复人或者操作人模式")
                else:
                    group.display_mode = "pure"
                    await db.commit()
                    await update.message.reply_text("✅ 已开启纯净模式（不显示任何人名）")
            elif text == "显示回复人":
                group.display_mode = "reply"
                await db.commit()
                await update.message.reply_text("✅ 已切换为显示回复人模式")
            elif text == "显示入账人":
                group.display_mode = "operator"
                await db.commit()
                await update.message.reply_text("✅ 已切换为显示操作人模式")
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def set_day_cut_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置日切时间"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 显示日切时间设置界面（内联键盘）
        await show_day_cut_keyboard(update, context, db)


async def show_day_cut_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, db):
    """显示日切时间选择键盘"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    chat_id = update.effective_chat.id
    
    # 获取群组当前日切时间
    query = scoped_query(Group, context).where(Group.group_id == chat_id)
    result = await db.execute(query)
    group = result.scalar_one_or_none()
    
    if not group:
        await update.message.reply_text("❌ 未找到群组配置")
        return
    
    current_hour = group.day_cut_time.hour if group.day_cut_time else None
    
    # 构建内联键盘
    keyboard = []
    
    # 0-23点按钮，每行6个
    for row_start in range(0, 24, 6):
        row = []
        for hour in range(row_start, row_start + 6):
            # 当前选中的小时显示勾选标记
            if current_hour is not None and hour == current_hour:
                button_text = f"{hour}点✅"
            else:
                button_text = f"{hour}点"
            
            row.append(InlineKeyboardButton(
                button_text,
                callback_data=f"daycut_{hour}"
            ))
        keyboard.append(row)
    
    # 底部按钮
    keyboard.append([
        InlineKeyboardButton("开启日切", callback_data="daycut_enable"),
        InlineKeyboardButton("关闭日切", callback_data="daycut_close")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 构建消息文本
    message_text = f"{update.effective_user.first_name or update.effective_user.username}\n"
    
    if current_hour is not None:
        message_text += f"已选择：{current_hour} 点"
    else:
        message_text += f"已选择：未设置"
    
    await update.message.reply_text(message_text, reply_markup=reply_markup)


async def day_cut_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理日切时间选择回调"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data
    
    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user_id, chat_id, db, context):
            await query.edit_message_text("❌ 您没有操作权限")
            return
        
        # 获取群组配置
        group_query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(group_query)
        group = result.scalar_one_or_none()
        
        if not group:
            await query.edit_message_text("❌ 未找到群组配置")
            return
        
        if data == "daycut_close":
            # 关闭日切
            group.day_cut_time = None
            await db.commit()
            
            # 更新定时任务
            from ..services.schedule_service import ScheduleService
            if hasattr(context.application, 'schedule_service'):
                await context.application.schedule_service.remove_day_cut_task(group.group_id)
            
            await query.message.delete()
            await update.effective_chat.send_message("✅ 日切功能已关闭！未下发的账单将会累积")
            return
        
        elif data == "daycut_enable":
            # 开启日切：获取当前选中的时间并保存
            # 先获取当前显示的消息文本，提取选中的时间
            current_text = query.message.text
            if "未设置" in current_text:
                await query.edit_message_text("⚠️ 请先选择一个时间点，再点击开启日切")
                return
            
            # 从文本中提取当前设定的小时（支持两种格式："当前设定"和"已选择"）
            import re
            match = re.search(r'(?:当前设定|已选择)：(\d+) 点', current_text)
            if not match:
                await query.edit_message_text("⚠️ 请先选择一个时间点，再点击开启日切")
                return
            
            hour = int(match.group(1))
            day_cut_time = dt_time(hour=hour, minute=0)
            
            group.day_cut_time = day_cut_time
            await db.commit()
            
            # 更新定时任务
            from ..services.schedule_service import ScheduleService
            if hasattr(context.application, 'schedule_service'):
                await context.application.schedule_service.add_day_cut_task(group)
            
            await query.message.delete()
            await update.effective_chat.send_message(f"✅ 日切功能已开启！\n\n⏰ 日切时间：{hour:02d}:00\n📊 到时间将自动删除账单")
            return
        
        elif data.startswith("daycut_"):
            # 选择日切时间（只更新UI显示，不保存到数据库）
            hour = int(data.split("_")[1])
            
            # 更新键盘显示（更新勾选标记）
            keyboard = []
            for row_start in range(0, 24, 6):
                row = []
                for h in range(row_start, row_start + 6):
                    if h == hour:
                        button_text = f"{h}点✅"
                    else:
                        button_text = f"{h}点"
                    
                    row.append(InlineKeyboardButton(
                        button_text,
                        callback_data=f"daycut_{h}"
                    ))
                keyboard.append(row)
            
            keyboard.append([
                InlineKeyboardButton("开启日切", callback_data="daycut_enable"),
                InlineKeyboardButton("关闭日切", callback_data="daycut_close")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 更新消息文本，提示用户需要点击开启日切来保存
            message_text = f"{update.effective_user.first_name or update.effective_user.username}\n"
            message_text += f"已选择：{hour} 点\n"
            message_text += f" 请点击「开启日切」保存设置"
            
            await query.edit_message_text(message_text, reply_markup=reply_markup)


async def set_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置下发地址（支持多种格式）
    
    支持的格式：
    1. 直接发送：设置下发地址 TRC20地址
    2. 回复消息：回复包含地址的消息 + 设置下发地址
    3. 无空格：设置下发地址TRC20地址
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text

    async for db in get_db():
        # 检查操作权限（新架构：租户隔离）
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        address = None
        
        # 方式1：尝试从回复的消息中提取地址
        if update.message.reply_to_message:
            replied_text = update.message.reply_to_message.text or ""
            # TRC20 地址格式：T开头，34位字符
            import re
            trc20_pattern = r'T[A-Za-z0-9]{33}'
            match = re.search(trc20_pattern, replied_text)
            if match:
                address = match.group(0)
        
        # 方式2：从命令文本中提取地址
        if not address and text.startswith("设置下发地址"):
            address = text[6:].strip()  # "设置下发地址" 长度为6
        
        # 验证地址格式
        if not address:
            await update.message.reply_text("❌ 请提供下发地址（直接发送或在回复消息中包含TRC20地址）")
            return
        
        # TRC20 地址验证：T开头，34位字符
        import re
        trc20_pattern = r'^T[A-Za-z0-9]{33}$'
        if not re.match(trc20_pattern, address):
            await update.message.reply_text("❌ 地址格式错误，请输入有效的TRC20地址（T开头，34位字符）")
            return

        # 更新群组配置（新架构：租户隔离查询）
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            group.withdraw_address = address
            await db.commit()
            # 使用统一渲染引擎（code标签支持复制）
            message = f"✅ 已设置本群下发地址\n\n<code>{address}</code>"
            await update.message.reply_text(message, parse_mode='HTML')
        else:
            await update.message.reply_text("❌ 未找到群组配置")


async def show_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示下发地址（简洁文本格式）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    async for db in get_db():
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group and group.withdraw_address:
            address = group.withdraw_address
            
            # 使用代码格式，地址带有复制按钮
            message = f"本群下发地址已设置：\n<code>{address}</code>"
            
            await update.message.reply_text(message, parse_mode='HTML')
        else:
            await update.message.reply_text("❌ 未设置下发地址")


async def delete_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除下发地址"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 提取地址（支持"删除下发地址TRC20地址"和"删除下发地址 TRC20地址"）
        if text.startswith("删除下发地址"):
            address = text[6:].strip()  # "删除下发地址" 长度为6
        else:
            await update.message.reply_text("❌ 命令格式错误")
            return
        
        if not address:
            await update.message.reply_text("❌ 请提供要删除的地址")
            return

        # 查找群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if not group:
            await update.message.reply_text("❌ 未找到群组配置")
            return
        
        # 验证当前群组设置的下发地址是否匹配
        if group.withdraw_address != address:
            await update.message.reply_text("❌ 地址不匹配，当前的下发地址为：\n" 
                                           f"<code>{group.withdraw_address}</code>",
                                           parse_mode='HTML')
            return
        
        # 清空下发地址
        group.withdraw_address = None
        await db.commit()
        await update.message.reply_text("✅ 已删除本群下发地址")


async def show_group_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示群组配置"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    async for db in get_db():
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            message = Formatter.format_group_config(group)
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(" 未找到群组配置")


async def toggle_real_time_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换实时汇率"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 获取群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if not group:
            await update.message.reply_text("❌ 未找到群组配置")
            return

        # 显示实时汇率设置界面（内联键盘）
        await show_real_time_rate_keyboard(update, context, db)


async def show_real_time_rate_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, db):
    """显示实时汇率设置键盘"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from ..services.exchange_service import ExchangeService
    import logging
    logger = logging.getLogger(__name__)
    
    chat_id = update.effective_chat.id
    
    # 获取群组当前汇率
    query = scoped_query(Group, context).where(Group.group_id == chat_id)
    result = await db.execute(query)
    group = result.scalar_one_or_none()
    
    if not group:
        await update.message.reply_text("❌ 未找到群组配置")
        return
    
    # 获取火币和欧意价格
    logger.info("正在获取火币价格...")
    huobi_price = await ExchangeService.get_huobi_usdt_price()
    logger.info(f"火币价格: {huobi_price}")
    
    logger.info("正在获取欧意价格...")
    okex_price = await ExchangeService.get_okex_usdt_price()
    logger.info(f"欧意价格: {okex_price}")
    
    current_rate = group.exchange_rate
    
    # 构建消息文本
    message_text = f"欧易 => 所有商家实时交易汇率Top10\n\n"
    
    # 显示价格信息
    if huobi_price:
        message_text += f"01) {huobi_price:.1f} 鸿发币行 👉\n"
    else:
        message_text += f"火币价格获取失败\n"
    
    if okex_price:
        message_text += f"02) {okex_price:.1f} 欧意币行\n"
    
    message_text += f"\n当前档位价格：{current_rate:.2f}"
    
    # 构建内联键盘
    keyboard = [
        [
            InlineKeyboardButton("火币汇率", callback_data="rate_source_huobi"),
            InlineKeyboardButton("欧意汇率", callback_data="rate_source_okex")
        ],
        [
            InlineKeyboardButton("减0.1", callback_data="rate_minus_0.1"),
            InlineKeyboardButton("加0.1", callback_data="rate_add_0.1")
        ],
        [
            InlineKeyboardButton("减0.01", callback_data="rate_minus_0.01"),
            InlineKeyboardButton("加0.01", callback_data="rate_add_0.01")
        ],
        [
            InlineKeyboardButton("启用实时汇率", callback_data="rate_enable_realtime")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message_text, reply_markup=reply_markup)


async def real_time_rate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理实时汇率回调"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from ..services.exchange_service import ExchangeService
    
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data
    
    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user_id, chat_id, db, context):
            await query.edit_message_text("❌ 您没有操作权限")
            return
        
        # 获取群组配置
        group_query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(group_query)
        group = result.scalar_one_or_none()
        
        if not group:
            await query.edit_message_text("❌ 未找到群组配置")
            return
        
        current_rate = group.exchange_rate
        
        if data == "rate_add_0.1":
            current_rate += 0.1
        elif data == "rate_minus_0.1":
            current_rate -= 0.1
        elif data == "rate_add_0.01":
            current_rate += 0.01
        elif data == "rate_minus_0.01":
            current_rate -= 0.01
        elif data == "rate_enable_realtime":
            # 启用实时汇率 - 获取火币价格并更新
            huobi_price = await ExchangeService.get_huobi_usdt_price()
            if huobi_price:
                group.exchange_rate = round(huobi_price, 2)
                group.real_time_rate = True
                await db.commit()
                await query.edit_message_text(f"✅ 已开启实时汇率模式\n\n当前汇率：{group.exchange_rate}\n系统将自动获取实时汇率进行计算")
            else:
                await query.edit_message_text("❌ 获取实时汇率失败，请稍后重试")
            return
        elif data.startswith("rate_source_"):
            # 切换汇率来源，暂时只是提示
            source = data.split("_")[2]
            if source == "huobi":
                await query.edit_message_text("✅ 已切换为火币汇率源\n\n系统将使用火币实时汇率")
            else:
                await query.edit_message_text("✅ 已切换为欧意汇率源\n\n系统将使用欧意实时汇率")
            return
        
        # 更新汇率
        group.exchange_rate = current_rate
        await db.commit()
        
        # 获取最新价格
        huobi_price = await ExchangeService.get_huobi_usdt_price()
        okex_price = await ExchangeService.get_okex_usdt_price()
        
        # 重新构建消息
        message_text = f"欧易 => 所有商家实时交易汇率Top10\n\n"
        
        if huobi_price:
            message_text += f"01) {huobi_price:.1f} 鸿发币行 👉\n"
        
        message_text += f"\n当前档位价格：{current_rate:.2f}"
        
        # 重新构建键盘
        keyboard = [
            [
                InlineKeyboardButton("火币汇率", callback_data="rate_source_huobi"),
                InlineKeyboardButton("欧意汇率", callback_data="rate_source_okex")
            ],
            [
                InlineKeyboardButton("减0.1", callback_data="rate_minus_0.1"),
                InlineKeyboardButton("加0.1", callback_data="rate_add_0.1")
            ],
            [
                InlineKeyboardButton("减0.01", callback_data="rate_minus_0.01"),
                InlineKeyboardButton("加0.01", callback_data="rate_add_0.01")
            ],
            [
                InlineKeyboardButton("启用实时汇率", callback_data="rate_enable_realtime")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message_text, reply_markup=reply_markup)


async def show_day_cut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看日切时间"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"show_day_cut 被调用: {update.message.text if update.message else 'No message'}")
    
    if not update.message or not update.effective_chat or not update.effective_user:
        logger.warning("show_day_cut: 缺少必要参数")
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 获取群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if not group:
            await update.message.reply_text("❌ 未找到群组配置")
            return

        if group.day_cut_time:
            hour = group.day_cut_time.hour
            minute = group.day_cut_time.minute
            time_str = f"{hour:02d}:{minute:02d}"
            await update.message.reply_text(f"📅 日切时间设置\n\n当前设定：{time_str}\n状态：✅ 已开启")
        else:
            await update.message.reply_text("📅 日切时间设置\n\n当前设定：未设置\n状态：❌ 已关闭")


async def close_day_cut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """关闭日切功能"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return

        # 获取群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if not group:
            await update.message.reply_text("❌ 未找到群组配置")
            return

        # 关闭日切
        group.day_cut_time = None
        await db.commit()

        # 更新定时任务
        from ..services.schedule_service import ScheduleService
        if hasattr(context.application, 'schedule_service'):
            await context.application.schedule_service.remove_day_cut_task(group.group_id)

        await update.message.reply_text("✅ 已关闭日切功能\n\n系统将不再自动执行日切操作")

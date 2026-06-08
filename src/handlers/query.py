"""
查询和辅助功能处理器
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.ext import ContextTypes

from ..services.exchange_service import ExchangeService
from ..services.exchange_rate_service import get_exchange_rates
from ..services.rate_formatter import RateFormatter
from ..services.keyboard_builder import KeyboardBuilder
from ..services.rate_cache_service import get_cached_rates, cache_rates
from ..utils.parser import CommandParser
from ..utils.calculator import Calculator

logger = logging.getLogger(__name__)


async def query_huobi_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查询火币U价 - 新版架构
    支持缓存、筛选、InlineKeyboard
    """
    if not update.message:
        return
    
    # 默认查询所有支付方式
    await _send_rate_message(update, context, "htx", "all")


async def query_binance_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查询币安U价 - 新版架构
    支持缓存、筛选、InlineKeyboard
    """
    if not update.message:
        return
    
    # 默认查询所有支付方式
    await _send_rate_message(update, context, "binance", "all")


async def query_trc20_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查询TRC20地址信息（图片+文本卡片样式）- 群组自动识别"""
    if not update.message:
        return

    text = update.message.text.strip()

    # 检查是否为TRC20地址
    if not CommandParser.is_trc20_address(text):
        return

    logger = logging.getLogger(__name__)
    logger.info(f"[TRC20] 检测到TRC20地址: {text}")

    try:
        # 获取地址信息
        address_info = await ExchangeService.get_tron_address_info(text)

        if not address_info:
            await update.message.reply_text("❌ 获取地址信息失败，请稍后重试")
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from datetime import datetime
        from ..services.card_generator import TRC20CardGenerator
        
        # 获取基本信息
        address = address_info.get('address', text)
        balance_trx = address_info.get('balance', 0) / 1_000_000
        
        # 获取USDT余额
        usdt_balance = 0
        tokens = address_info.get("trc20token_balances", [])
        for token in tokens:
            if token.get('tokenName') == 'Tether USD' or token.get('tokenAbbr') == 'USDT':
                token_balance = token.get("balance", "0")
                token_decimals = int(token.get("tokenDecimal", 6))
                usdt_balance = float(token_balance) / (10 ** token_decimals)
                break
        
        # 获取交易统计
        total_transactions = address_info.get('transactions', 0)
        
        # 获取时间信息
        create_time = address_info.get('date_created', 0)
        
        # 从交易记录中获取最近活跃时间
        latest_operation_time = 0
        try:
            latest_transactions = await ExchangeService.get_tron_transactions(text, limit=1)
            if latest_transactions and len(latest_transactions) > 0:
                latest_operation_time = latest_transactions[0].get('block_ts', 0)
        except Exception as e:
            logger.warning(f"[TRC20] 获取最新交易时间失败: {e}")
        
        first_tx_time = "N/A"
        latest_active_time = "N/A"
        
        if create_time:
            first_tx_time = datetime.fromtimestamp(create_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
        if latest_operation_time:
            latest_active_time = datetime.fromtimestamp(latest_operation_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
        
        # 获取签名状态
        owner_address = address_info.get('ownerAddress', '')
        signature_status = "单签地址" if not address_info.get('ownerAddress') or owner_address == address else "多签地址"
        
        # 获取能量和带宽
        bandwidth_info = address_info.get('bandwidth', {})
        energy = bandwidth_info.get('energyRemaining', 0)
        energy_limit = bandwidth_info.get('energyLimit', 0)
        bandwidth = bandwidth_info.get('freeNetRemaining', 0) + bandwidth_info.get('netRemaining', 0)
        bandwidth_limit = bandwidth_info.get('freeNetLimit', 0) + bandwidth_info.get('netLimit', 0)
        
        # 当前时间
        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 生成图片卡片
        try:
            generator = TRC20CardGenerator()
            image_bytes = generator.generate_card(address, now_time)
        except Exception as e:
            logger.error(f"[TRC20] 生成图片卡片失败: {e}", exc_info=True)
            await update.message.reply_text("❌ 生成验证卡片失败，请稍后重试")
            return
        
        # 构建文本消息
        message = (
            f"🔍 查询地址: <code>{address}</code>\n\n"
            f"💡 交易次数: <code>{total_transactions}</code>\n"
            f"⏰ 首次交易: <code>{first_tx_time}</code>\n"
            f"⏰ 最近活跃: <code>{latest_active_time}</code>\n"
            f"🛡️ 签名状态: <code>{signature_status}</code>\n\n"
            f"🔋 能量: <code>剩余: {energy} / {energy_limit}</code>\n"
            f"🌈 带宽: <code>剩余: {bandwidth} / {bandwidth_limit}</code>\n\n"
            f"💵 USDT余额: <code>{usdt_balance:.4f} USDT</code>\n"
            f"💰 TRX余额: <code>{balance_trx:.4f} TRX</code>"
        )
        
        # 构建底部按钮
        keyboard = [
            [
                InlineKeyboardButton("收款二维码", callback_data=f"qrcode_{address}"),
                InlineKeyboardButton("交易记录", callback_data=f"txhistory_{address}_1")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 发送图片和消息
        from io import BytesIO
        await update.message.reply_photo(
            photo=BytesIO(image_bytes),
            caption=message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        logger.info(f"[TRC20] 成功发送防篡改验证卡片: {address}")
        
    except Exception as e:
        logger.error(f"[TRC20] 查询地址信息发生错误: {e}", exc_info=True)
        await update.message.reply_text("❌ 查询地址信息时发生错误，请稍后重试")


async def qrcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理收款二维码按钮点击"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    # 从callback_data中提取地址
    callback_data = query.data
    if not callback_data.startswith("qrcode_"):
        return
    
    address = callback_data.replace("qrcode_", "")
    
    # 生成二维码 - 返回字节流
    from ..services.qrcode_generator import QRCodeGenerator
    from io import BytesIO
    
    generator = QRCodeGenerator()
    qrcode_bytes = generator.generate_address_qrcode(address)
    
    # 直接发送二维码图片（无需临时文件）
    await query.message.reply_photo(
        photo=BytesIO(qrcode_bytes),
        caption=f"地址: <code>{address}</code>",
        parse_mode='HTML'
    )


async def txhistory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理交易记录按钮点击（分页显示）"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    # 从callback_data中提取地址和页码
    callback_data = query.data
    if not callback_data.startswith("txhistory_"):
        return
    
    parts = callback_data.split("_")
    if len(parts) != 3:
        return
    
    address = parts[1]
    page = int(parts[2])
    
    # 获取交易记录（每次获取20条）
    transactions = await ExchangeService.get_tron_transactions(address, limit=20)
    
    if not transactions:
        await query.message.reply_text("❌ 获取交易记录失败")
        return
    
    # 调试：打印第一条交易数据结构
    import logging
    logger = logging.getLogger(__name__)
    if transactions:
        logger.info(f"交易记录API返回: {transactions[0]}")
    
    # 计算分页
    per_page = 10  # 每页显示10条
    total_pages = (len(transactions) + per_page - 1) // per_page
    
    # 确保页码在有效范围内
    page = max(1, min(page, total_pages))
    
    # 获取当前页的交易记录
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, len(transactions))
    page_transactions = transactions[start_idx:end_idx]
    
    # 格式化交易记录
    from datetime import datetime
    
    lines = [
        f"📄 当前页码: 第 {page} 页 / 共 {total_pages} 页\n",
        "<pre>",
        "|时间|类型|地址|金额|",
        "|----|----|----|----|"
    ]
    
    for tx in page_transactions:
        # 解析TRC20 Transfers API返回的数据
        timestamp = tx.get('block_ts', 0)
        tx_time = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "N/A"
        
        # TRC20 Transfers API返回的数据结构
        from_address = tx.get('from_address', 'N/A')
        to_address = tx.get('to_address', 'N/A')
        
        # 获取金额和代币信息
        raw_amount = tx.get('quant', '0')
        token_info = tx.get('tokenInfo', {})
        token_abbr = token_info.get('tokenAbbr', 'USDT')
        
        # 计算金额（USDT精度为6位小数）
        decimals = 6  # TRC20 USDT通常是6位小数
        amount_value = float(raw_amount) / (10 ** decimals)
        amount = f"{amount_value:.2f} {token_abbr}"
        
        # 判断转入/转出
        if to_address == address:
            tx_type = "转入"
            counterparty_address = from_address
        else:
            tx_type = "支出"
            counterparty_address = to_address
        
        # 新格式：时间一行 + 类型，下一行显示地址 + 金额
        lines.append(f"|{tx_time}|{tx_type}|")
        lines.append(f"|{counterparty_address}|{amount}|")
    
    lines.append("</pre>")
    
    message = "\n".join(lines)
    
    # 构建翻页按钮
    keyboard = []
    if total_pages > 1:
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("上一页", callback_data=f"txhistory_{address}_{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("下一页", callback_data=f"txhistory_{address}_{page+1}"))
        keyboard.append(buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    # 发送或编辑消息
    await query.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')


async def query_trc20_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查询TRC20地址交易记录"""
    if not update.message:
        return

    text = update.message.text.strip()

    # 从回复消息中获取地址
    if update.message.reply_to_message:
        text = update.message.reply_to_message.text.strip()

    # 检查是否为TRC20地址
    if not CommandParser.is_trc20_address(text):
        await update.message.reply_text("❌ 请提供有效的TRC20地址")
        return

    # 获取交易记录
    transactions = await ExchangeService.get_tron_transactions(text)

    if transactions:
        message = await ExchangeService.format_tron_transactions(transactions)
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("❌ 获取交易记录失败")


async def calculate_expression(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """计算功能"""
    if not update.message:
        return

    text = update.message.text.strip()

    # 提取表达式（去掉"计算"等前缀）
    if text.startswith("计算"):
        expression = text[2:].strip()
    else:
        return

    # 计算结果
    result = Calculator.evaluate_expression(expression)

    if result is not None:
        await update.message.reply_text(f"💡 计算结果: {expression} = {result}")
    else:
        await update.message.reply_text("❌ 表达式格式错误")


async def mention_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """通知所有人（@all）- 真正 @ 所有群成员（使用数据库索引）"""
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    
    try:
        # 获取 bot_id 用于数据库查询
        from ..utils.bot_id_middleware import get_current_bot_id
        from ..repositories.group_member_index_repo import GroupMemberIndexRepo
        from ..models import get_db
        
        bot_id = get_current_bot_id(context)
        
        # 构建通知消息（注意：使用 entities 时不能用 parse_mode，两者互斥）
        notification_text = "📢 群组通知\n\n"
        
        # 从数据库获取群成员列表
        async for db in get_db():
            members = await GroupMemberIndexRepo.get_all_group_members(
                db=db,
                bot_id=bot_id,
                group_id=chat_id,
                limit=100  # Telegram 限制一条消息最多 @100 人
            )
            
            # 获取群组成员总数
            try:
                member_count = await context.bot.get_chat_member_count(chat_id)
            except Exception as e:
                logger.warning(f"获取群组总人数失败: {e}")
                member_count = len(members)
            
            if members:
                # 构建提及文本和 MessageEntity 实体
                mention_parts = []
                entities = []
                current_offset = len(notification_text + f"全体成员请注意！（{len(members)} 人）\n\n")
                
                for member in members:
                    user_id = member['user_id']
                    username = member['username']
                    first_name = member['first_name']
                    
                    # 清理 username（去除 @ 前缀）
                    clean_username = username.lstrip('@') if username else None
                    
                    if clean_username:
                        mention = f"@{clean_username}"
                        mention_parts.append(mention)
                        
                        # 构造 telegram.User 对象用于 entity
                        from telegram import User
                        user = User(
                            id=user_id,
                            is_bot=False,
                            first_name=first_name or "用户",
                            username=clean_username
                        )
                        
                        # 使用 TEXT_MENTION 类型并提供完整 User 对象
                        entities.append(
                            MessageEntity(
                                type=MessageEntity.TEXT_MENTION,
                                offset=current_offset,
                                length=len(mention),
                                user=user
                            )
                        )
                    else:
                        # 没有 username 的用户，使用昵称
                        mention = first_name or '用户'
                        mention_parts.append(mention)
                    
                    current_offset += len(mention) + 1  # +1 for space
                
                notification_text += f"全体成员请注意！（{len(members)} 人）\n\n"
                notification_text += " ".join(mention_parts)
                
                # 使用 Markdown 模式发送，Telegram 会自动解析 @username
                # 同时保留 entities 作为备用
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=notification_text,
                    parse_mode="Markdown"
                )
            else:
                notification_text += f"全体成员请注意！（共 {member_count} 人）"
                await update.message.reply_text(notification_text)

    except Exception as e:
        logger.error(f"通知所有人失败: {e}", exc_info=True)
        await update.message.reply_text(f"❌ 操作失败: {str(e)}")


async def set_group_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置分组标签（群组命令方式）
    
    使用方式：在群组中发送 "设置分组 XXX"
    例如：设置分组 VIP客户
    
    注意：此处理器只匹配正则 r'^设置分组\s+.+'，不会误判其他消息
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    from sqlalchemy import select
    from ..models import Group, get_db
    from .operator import is_operator
    from ..utils.tenant_scope import scoped_query

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()

    # 提取分组名称（格式：设置分组 XXX）
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("❌ 请提供分组标签\n\n例如：设置分组 VIP客户")
        return
    
    tag = parts[1].strip()

    async for db in get_db():
        # 检查操作权限
        if not await is_operator(user.id, chat_id, db, context):
            await update.message.reply_text("❌ 您没有操作权限")
            return
        
        # 验证分组名称
        if not tag:
            await update.message.reply_text("❌ 分组名称不能为空")
            return
        
        if len(tag) > 50:
            await update.message.reply_text("❌ 分组名称不能超过50个字符")
            return

        # 更新群组配置
        query = scoped_query(Group, context).where(Group.group_id == chat_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if group:
            old_tag = group.group_tag or "未设置"
            group.group_tag = tag
            await db.commit()
            await update.message.reply_text(
                f"✅ 已设置分组\n\n"
                f"原分组：{old_tag}\n"
                f"新分组：{tag}"
            )
        else:
            await update.message.reply_text("❌ 群组未在数据库中，请先发送 /start 激活")


# ============================================================================
# 汇率查询核心功能（新架构）
# ============================================================================

async def _send_rate_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    exchange: str,
    payment_method: str = "all",
    is_callback: bool = False
):
    """
    发送或更新汇率报价消息
    
    Args:
        update: Telegram Update对象
        context: Telegram Context对象
        exchange: 交易所名称 (htx/binance)
        payment_method: 支付方式 (all/bank/alipay/wechat)
        is_callback: 是否是回调请求（编辑消息 vs 发送新消息）
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # 1. 尝试从缓存获取
        cache_key = f"{exchange}:{payment_method}"
        merchants = get_cached_rates(exchange, payment_method)
        
        if merchants is None:
            # 2. 缓存未命中，调用API
            logger.info(f"缓存未命中，请求API: {cache_key}")
            merchants = await get_exchange_rates(exchange, payment_method)
            
            if merchants:
                # 3. 缓存结果（60秒）
                cache_rates(exchange, payment_method, merchants, ttl=60)
                logger.info(f"已缓存数据: {cache_key}")
        else:
            logger.info(f"缓存命中: {cache_key}")
        
        if not merchants:
            error_msg = f"❌ 获取{exchange.upper()}报价失败"
            if is_callback and update.callback_query:
                await update.callback_query.answer(error_msg, show_alert=True)
            elif update.message:
                await update.message.reply_text(error_msg)
            return
        
        # 4. 格式化消息
        from datetime import datetime
        query_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message_text = RateFormatter.format_rate_message(
            exchange=exchange,
            merchants=merchants,
            payment_method=payment_method,
            query_time=query_time
        )
        
        # 5. 构建键盘
        reply_markup = KeyboardBuilder.build_rate_keyboard(exchange, payment_method)
        
        # 6. 发送或编辑消息
        if is_callback and update.callback_query:
            # 编辑原消息（使用HTML格式）
            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            # 回答回调（去除加载动画）
            await update.callback_query.answer()
        elif update.message:
            # 发送新消息（使用HTML格式）
            await update.message.reply_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
    
    except Exception as e:
        logger.error(f"发送汇率消息失败: {e}", exc_info=True)
        error_msg = "❌ 处理请求时发生错误"
        
        if is_callback and update.callback_query:
            await update.callback_query.answer(error_msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(error_msg)


async def handle_rate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理汇率查询的回调按钮点击
    callback_data 格式: rate:{exchange}:{method}
    """
    if not update.callback_query:
        return
    
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # 1. 解析回调数据
        callback_data = update.callback_query.data
        parsed = KeyboardBuilder.parse_callback_data(callback_data)
        
        if not parsed:
            logger.warning(f"无效的回调数据: {callback_data}")
            await update.callback_query.answer("❌ 无效的请求", show_alert=True)
            return
        
        exchange = parsed["exchange"]
        method = parsed["method"]
        
        logger.info(f"汇率回调: exchange={exchange}, method={method}")
        
        # 2. 发送更新后的消息
        await _send_rate_message(
            update=update,
            context=context,
            exchange=exchange,
            payment_method=method,
            is_callback=True
        )
    
    except Exception as e:
        logger.error(f"处理汇率回调失败: {e}", exc_info=True)
        await update.callback_query.answer("❌ 处理失败", show_alert=True)

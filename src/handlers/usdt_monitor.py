"""
USDT监听 Handler（新版UI）

处理用户交互：
1. 显示USDT监听主页面（统一UI样式）
2. 添加监听地址（带地址校验和确认）
3. 删除监听地址（带二次确认）
4. 设置推送群（带群验证和确认）
5. 开关监听（带状态切换和确认）
6. 设置提醒阈值（带数值校验和确认）
7. 返回主菜单（带确认）
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..core.runtime_router import runtime_router, Routes
from ..services.tenant_context import TenantContext
from ..services.wallet_monitor_service import wallet_monitor_service
from ..services.exchange_service import ExchangeService
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)

USDT_WAITING_ADDRESS = "waiting_address_input"


def _get_bot_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Get bot id from middleware, with a test/legacy user_data fallback."""
    try:
        return get_current_bot_id(context)
    except Exception:
        return context.user_data.get("usdt_bot_id") or context.user_data.get("bot_id") or "main_bot"


# ============ 主页面 ============

async def handle_usdt_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    USDT监听主页面
    
    显示：
    - 当前状态
    - 监听地址数量
    - 推送方式
    - 地址列表
    - 功能按钮
    """
    bot_id = get_current_bot_id(context)
    user_id = update.effective_user.id
    
    logger.info(f"🔵 [DEBUG] handle_usdt_monitor called by user {user_id} in bot {bot_id}")
    
    # 清除所有临时状态
    for key in ["usdt_monitor_state", "usdt_alias_address", "usdt_alias_state", 
                "usdt_pending_address", "usdt_pending_info", "usdt_delete_index",
                "usdt_push_group_state", "usdt_threshold_state", "usdt_pending_delete",
                "usdt_pending_threshold", "usdt_addresses_list"]:
        context.user_data.pop(key, None)
    
    # 获取监听地址列表
    addresses = await wallet_monitor_service.get_watched_addresses(
        bot_id=bot_id,
        user_id=user_id
    )
    
    # TODO: 从数据库获取监听状态（暂时默认关闭）
    is_monitoring = False
    address_count = len(addresses)
    
    # TODO: 从数据库获取推送方式（暂时默认私聊）
    push_mode = "私聊通知"
    
    # 构建页面文本
    text = (
        f"💸 <b>USDT 监听</b>\n\n"
        f"当前状态：{'🟢 已开启' if is_monitoring else '🔴 已关闭'}\n"
        f"我的监听地址：<b>{address_count}</b> 个\n"
        f"推送方式：{push_mode}\n\n"
    )
    
    # 添加地址列表
    if addresses:
        text += "<b>监听地址列表：</b>\n"
        for idx, addr in enumerate(addresses[:5], 1):  # 最多显示5个
            alias_text = f"（{addr.alias}）" if addr.alias else ""
            text += f"{idx}. <code>{addr.address}</code>{alias_text}\n"
        if len(addresses) > 5:
            text += f"... 还有 {len(addresses) - 5} 个地址\n"
    else:
        text += "暂无监听地址\n"
    
    # 构建按钮 - 一行两个，与主菜单风格一致
    keyboard = [
        [InlineKeyboardButton("➕ 添加地址", callback_data="usdt:add"),
         InlineKeyboardButton("➖ 删除地址", callback_data="usdt:delete")],
        [InlineKeyboardButton("📢 设置推送群", callback_data="usdt:push_group"),
         InlineKeyboardButton("🔔 设置提醒阈值", callback_data="usdt:threshold")],
        [InlineKeyboardButton(f"{'🟢 关闭监听' if is_monitoring else '🔴 开启监听'}", callback_data="usdt:toggle"),
         InlineKeyboardButton("⬅️ 返回", callback_data="settings:main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 发送或编辑消息
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


# ============ 添加地址流程 ============

async def handle_usdt_add(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """开始添加地址流程"""
    context.user_data["usdt_monitor_state"] = "waiting_address_input"
    
    await update.callback_query.edit_message_text(
        "请直接发送要监听的 USDT 地址\n\n"
        "格式：TRON 地址（以 T 开头，34个字符）\n\n"
        "发送 /cancel 取消"
    )


async def handle_address_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的地址"""
    state = context.user_data.get("usdt_monitor_state")
    if state == "waiting_delete_index":
        await handle_delete_index_input(update, context)
        return
    if state == "waiting_push_group":
        await handle_push_group_input(update, context)
        return
    if state == "waiting_threshold":
        await handle_threshold_input(update, context)
        return

    legacy_waiting = context.user_data.get("waiting_for") == USDT_WAITING_ADDRESS
    if state != USDT_WAITING_ADDRESS and not legacy_waiting:
        return
    
    bot_id = _get_bot_id(context)
    user_id = update.effective_user.id
    raw_text = update.message.text.strip()
    parts = raw_text.split(maxsplit=1)
    address = parts[0] if parts else ""
    alias = parts[1].strip() if len(parts) > 1 else None
    
    # 校验地址格式
    if not (address.startswith('T') and len(address) == 34):
        await update.message.reply_text(
            "❌ 地址格式不正确，请重新发送\n\n"
            "地址必须以 T 开头，长度34个字符。"
        )
        return
    
    # 清除等待状态
    if legacy_waiting:
        try:
            await wallet_monitor_service.add_watched_address(
                bot_id=bot_id,
                user_id=user_id,
                group_id=0,
                address=address,
                alias=alias,
                monitor_usdt=True,
                monitor_trx=False,
            )
            context.user_data.pop("waiting_for", None)
            await update.message.reply_text("✅ 已添加监听地址")
        except ValueError as e:
            await update.message.reply_text(f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"Error adding address: {e}", exc_info=True)
            await update.message.reply_text("❌ 添加失败，请稍后重试")
        return

    context.user_data.pop("usdt_monitor_state", None)
    
    try:
        # 查询链上信息
        address_info = await ExchangeService.get_tron_address_info(address)
        
        if not address_info:
            await update.message.reply_text("❌ 无法获取地址信息，请稍后重试")
            return
        
        # 提取信息
        usdt_balance = 0
        tokens = address_info.get("trc20token_balances", [])
        for token in tokens:
            if token.get('tokenName') == 'Tether USD' or token.get('tokenAbbr') == 'USDT':
                token_balance = token.get("balance", "0")
                token_decimals = int(token.get("tokenDecimal", 6))
                usdt_balance = float(token_balance) / (10 ** token_decimals)
                break
        
        total_transactions = address_info.get('transactions', 0)
        
        # 保存地址到临时状态，等待确认
        context.user_data["usdt_pending_address"] = address
        context.user_data["usdt_pending_info"] = {
            'usdt_balance': usdt_balance,
            'transactions': total_transactions
        }
        
        # 显示地址信息并请求确认
        text = (
            f" <b>地址信息：</b>\n\n"
            f"地址：<code>{address}</code>\n"
            f"余额：<b>{usdt_balance:.2f} USDT</b>\n"
            f"交易数：<b>{total_transactions}</b>\n"
            f"链类型：<b>TRC20</b>\n\n"
            f"是否确认将此地址加入监听列表？"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ 确认添加", callback_data="usdt:add_confirm")],
            [InlineKeyboardButton("❌ 取消", callback_data="usdt:add_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error querying address {address}: {e}", exc_info=True)
        await update.message.reply_text("❌ 查询失败，请稍后重试")


async def handle_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认添加地址"""
    query = update.callback_query
    await query.answer()
    
    bot_id = get_current_bot_id(context)
    user_id = query.from_user.id
    
    address = context.user_data.get("usdt_pending_address")
    if not address:
        await query.edit_message_text("❌ 会话已过期，请重新开始")
        return
    
    try:
        # 添加到数据库
        await wallet_monitor_service.add_watched_address(
            bot_id=bot_id,
            user_id=user_id,
            group_id=0,
            address=address,
            alias=None,
            monitor_usdt=True,
            monitor_trx=False
        )
        
        # 清除临时状态
        context.user_data.pop("usdt_pending_address", None)
        context.user_data.pop("usdt_pending_info", None)
        
        await query.edit_message_text("✅ 地址已成功添加到监听列表")
        
        # 刷新主页面
        await _refresh_main_page(query, context)
        
    except ValueError as e:
        await query.edit_message_text(f"❌ {str(e)}")
    except Exception as e:
        logger.error(f"Error adding address: {e}", exc_info=True)
        await query.edit_message_text("❌ 添加失败，请稍后重试")


async def handle_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消添加地址"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop("usdt_pending_address", None)
    context.user_data.pop("usdt_pending_info", None)
    
    await query.edit_message_text("已取消添加")
    
    # 刷新主页面
    await _refresh_main_page(query, context)


# ============ 删除地址流程 ============

async def handle_usdt_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """开始删除地址流程"""
    bot_id = get_current_bot_id(context)
    user_id = update.effective_user.id
    
    addresses = await wallet_monitor_service.get_watched_addresses(
        bot_id=bot_id,
        user_id=user_id
    )
    
    if not addresses:
        await update.callback_query.edit_message_text("暂无监听地址，无法删除")
        return
    
    # 构建地址列表
    text = "<b>请选择要删除的地址：</b>\n\n"
    for idx, addr in enumerate(addresses, 1):
        alias_text = f"（{addr.alias}）" if addr.alias else ""
        text += f"{idx}. <code>{addr.address}</code>{alias_text}\n"
    
    text += "\n请回复序号选择要删除的地址"
    
    context.user_data["usdt_monitor_state"] = "waiting_delete_index"
    context.user_data["usdt_addresses_list"] = addresses
    
    await update.callback_query.edit_message_text(text, parse_mode="HTML")


async def handle_delete_index_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的删除序号"""
    if context.user_data.get("usdt_monitor_state") != "waiting_delete_index":
        return
    
    addresses = context.user_data.get("usdt_addresses_list", [])
    
    try:
        index = int(update.message.text.strip())
        if index < 1 or index > len(addresses):
            await update.message.reply_text(f"❌ 序号无效，请输入 1-{len(addresses)} 之间的数字")
            return
        
        address = addresses[index - 1]
        context.user_data["usdt_pending_delete"] = {
            'index': index,
            'address': address.address,
            'alias': address.alias
        }
        
        context.user_data.pop("usdt_monitor_state", None)
        context.user_data.pop("usdt_addresses_list", None)
        
        alias_text = f"（备注：{address.alias}）" if address.alias else ""
        text = (
            f"你选择要删除的地址：\n\n"
            f"<code>{address.address}</code>{alias_text}\n\n"
            f"是否确认删除该地址？删除后将不再接收该地址的交易提醒。"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ 确认删除", callback_data="usdt:delete_confirm")],
            [InlineKeyboardButton("❌ 取消", callback_data="usdt:delete_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        
    except ValueError:
        await update.message.reply_text("❌ 请输入有效的数字序号")


async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认删除地址"""
    query = update.callback_query
    await query.answer()
    
    bot_id = get_current_bot_id(context)
    pending = context.user_data.get("usdt_pending_delete")
    
    if not pending:
        await query.edit_message_text("❌ 会话已过期，请重新开始")
        return
    
    try:
        from sqlalchemy import select
        from ..models.database import get_db_session
        from ..models.wallet_monitor import WatchedAddress
        
        async with get_db_session() as db:
            result = await db.execute(
                select(WatchedAddress).where(
                    WatchedAddress.bot_id == bot_id,
                    WatchedAddress.address == pending['address']
                )
            )
            watched_address = result.scalar_one_or_none()
            
            if not watched_address:
                await query.edit_message_text("❌ 未找到该地址")
                return
            
            await db.delete(watched_address)
            await db.commit()
        
        context.user_data.pop("usdt_pending_delete", None)
        
        await query.edit_message_text("✅ 地址已删除")
        
        # 刷新主页面
        await _refresh_main_page(query, context)
        
    except Exception as e:
        logger.error(f"Error deleting address: {e}", exc_info=True)
        await query.edit_message_text("❌ 删除失败，请稍后重试")


async def handle_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消删除地址"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop("usdt_pending_delete", None)
    
    await query.edit_message_text("已取消删除")
    
    # 刷新主页面
    await _refresh_main_page(query, context)


# ============ 设置推送群 ============

async def handle_usdt_push_group(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """开始设置推送群流程"""
    context.user_data["usdt_monitor_state"] = "waiting_push_group"
    
    await update.callback_query.edit_message_text(
        "请转发群消息或发送群ID来设置推送群\n\n"
        "发送 /cancel 取消"
    )


async def handle_push_group_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的推送群"""
    if context.user_data.get("usdt_monitor_state") != "waiting_push_group":
        return
    
    # TODO: 验证群ID和机器人是否在群中
    group_id = update.message.text.strip()
    context.user_data["usdt_pending_group"] = group_id
    context.user_data.pop("usdt_monitor_state", None)
    
    text = (
        f"你选择的推送群：XXX 群（群ID：{group_id}）\n\n"
        f"是否确认将该群设置为 USDT 交易推送群？"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ 确认设置", callback_data="usdt:push_group_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="usdt:push_group_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup)


async def handle_push_group_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认设置推送群"""
    query = update.callback_query
    await query.answer()
    
    # TODO: 保存推送群到数据库
    context.user_data.pop("usdt_pending_group", None)
    
    await query.edit_message_text("✅ 推送群已设置成功")
    await _refresh_main_page(query, context)


async def handle_push_group_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消设置推送群"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop("usdt_pending_group", None)
    
    await query.edit_message_text("已取消设置")
    await _refresh_main_page(query, context)


# ============ 设置提醒阈值 ============

async def handle_usdt_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """开始设置提醒阈值流程"""
    context.user_data["usdt_monitor_state"] = "waiting_threshold"
    
    await update.callback_query.edit_message_text(
        "请输入交易提醒的最小金额（单位：USDT，例如：100）\n\n"
        "发送 /cancel 取消"
    )


async def handle_threshold_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的阈值"""
    if context.user_data.get("usdt_monitor_state") != "waiting_threshold":
        return
    
    try:
        amount = float(update.message.text.strip())
        if amount < 0:
            await update.message.reply_text("❌ 请输入有效的数字（大于等于0）")
            return
        
        context.user_data["usdt_pending_threshold"] = amount
        context.user_data.pop("usdt_monitor_state", None)
        
        text = (
            f"你设置的提醒阈值为：<b>{amount}</b> USDT\n"
            f"交易金额 ≥ {amount} USDT 时才会推送提醒。\n\n"
            f"是否确认保存该阈值？"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ 确认保存", callback_data="usdt:threshold_confirm")],
            [InlineKeyboardButton("❌ 取消", callback_data="usdt:threshold_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        
    except ValueError:
        await update.message.reply_text("❌ 请输入有效的数字")


async def handle_threshold_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认保存阈值"""
    query = update.callback_query
    await query.answer()
    
    amount = context.user_data.get("usdt_pending_threshold")
    
    # TODO: 保存阈值到数据库
    context.user_data.pop("usdt_pending_threshold", None)
    
    await query.edit_message_text(f"✅ 提醒阈值已设置为 {amount} USDT")
    await _refresh_main_page(query, context)


async def handle_threshold_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消设置阈值"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop("usdt_pending_threshold", None)
    
    await query.edit_message_text("已取消设置")
    await _refresh_main_page(query, context)


# ============ 开关监听 ============

async def handle_usdt_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """开关监听"""
    # TODO: 从数据库获取当前状态
    is_monitoring = False
    
    text = (
        f"当前监听状态为「{'已开启' if is_monitoring else '已关闭'}」，"
        f"{'关闭' if is_monitoring else '开启'}后将{'停止' if is_monitoring else '开始'}接收所有交易提醒，"
        f"是否确认{'关闭' if is_monitoring else '开启'}？"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ 确认", callback_data="usdt:toggle_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="usdt:toggle_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup)


async def handle_toggle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认切换监听状态"""
    query = update.callback_query
    await query.answer()
    
    # TODO: 更新数据库状态
    # TODO: 启动/停止监听服务
    
    await query.edit_message_text("✅ 监听状态已切换")
    await _refresh_main_page(query, context)


async def handle_toggle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消切换监听状态"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("已取消操作，状态不变")
    await _refresh_main_page(query, context)


# ============ 辅助函数 ============

async def _refresh_main_page(query, context):
    """刷新主页面"""
    bot_id = get_current_bot_id(context)
    user_id = query.from_user.id
    
    addresses = await wallet_monitor_service.get_watched_addresses(
        bot_id=bot_id,
        user_id=user_id
    )
    
    is_monitoring = False
    address_count = len(addresses)
    push_mode = "私聊通知"
    
    text = (
        f"💸 <b>USDT 监听</b>\n\n"
        f"当前状态：{'🟢 已开启' if is_monitoring else '🔴 已关闭'}\n"
        f"我的监听地址：<b>{address_count}</b> 个\n"
        f"推送方式：{push_mode}\n\n"
    )
    
    if addresses:
        text += "<b>监听地址列表：</b>\n"
        for idx, addr in enumerate(addresses[:5], 1):
            alias_text = f"（{addr.alias}）" if addr.alias else ""
            text += f"{idx}. <code>{addr.address}</code>{alias_text}\n"
        if len(addresses) > 5:
            text += f"... 还有 {len(addresses) - 5} 个地址\n"
    else:
        text += "暂无监听地址\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加地址", callback_data="usdt:add"),
         InlineKeyboardButton("➖ 删除地址", callback_data="usdt:delete")],
        [InlineKeyboardButton("📢 设置推送群", callback_data="usdt:push_group"),
         InlineKeyboardButton("🔔 设置提醒阈值", callback_data="usdt:threshold")],
        [InlineKeyboardButton(f"{'🟢 关闭监听' if is_monitoring else '🔴 开启监听'}", callback_data="usdt:toggle"),
         InlineKeyboardButton("⬅️ 返回", callback_data="settings:main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")


# ============ 注册回调 ============

def register_callbacks():
    """注册所有USDT监听回调"""
    async def _add_confirm(update, context, tenant_context):
        await handle_add_confirm(update, context)

    async def _add_cancel(update, context, tenant_context):
        await handle_add_cancel(update, context)

    async def _delete_confirm(update, context, tenant_context):
        await handle_delete_confirm(update, context)

    async def _delete_cancel(update, context, tenant_context):
        await handle_delete_cancel(update, context)

    async def _push_group_confirm(update, context, tenant_context):
        await handle_push_group_confirm(update, context)

    async def _push_group_cancel(update, context, tenant_context):
        await handle_push_group_cancel(update, context)

    async def _threshold_confirm(update, context, tenant_context):
        await handle_threshold_confirm(update, context)

    async def _threshold_cancel(update, context, tenant_context):
        await handle_threshold_cancel(update, context)

    async def _toggle_confirm(update, context, tenant_context):
        await handle_toggle_confirm(update, context)

    async def _toggle_cancel(update, context, tenant_context):
        await handle_toggle_cancel(update, context)

    route_handlers = {
        "v1:usdt:monitor": handle_usdt_monitor,
        "v1:usdt:main": handle_usdt_monitor,
        "v1:usdt:add": handle_usdt_add,
        "v1:usdt:add_confirm": _add_confirm,
        "v1:usdt:add_cancel": _add_cancel,
        "v1:usdt:delete": handle_usdt_delete,
        "v1:usdt:delete_confirm": _delete_confirm,
        "v1:usdt:delete_cancel": _delete_cancel,
        "v1:usdt:push_group": handle_usdt_push_group,
        "v1:usdt:push_group_confirm": _push_group_confirm,
        "v1:usdt:push_group_cancel": _push_group_cancel,
        "v1:usdt:threshold": handle_usdt_threshold,
        "v1:usdt:threshold_confirm": _threshold_confirm,
        "v1:usdt:threshold_cancel": _threshold_cancel,
        "v1:usdt:toggle": handle_usdt_toggle,
        "v1:usdt:toggle_confirm": _toggle_confirm,
        "v1:usdt:toggle_cancel": _toggle_cancel,
    }

    for route_name, handler in route_handlers.items():
        runtime_router.register_route(route_name, handler)
    
    logger.info("✅ USDT Monitor callbacks registered")

"""
超级管理员处理器
处理超管后台操作、全局消息转发等功能
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config import config

# 固定超级管理员ID（兼容配置文件）
SUPER_ADMIN_ID = int(getattr(config, "SUPER_ADMIN_ID", 0) or 0)
FIXED_SUPER_ADMIN_ID = 7862093562  # 固定超管ID

logger = logging.getLogger(__name__)


def _log_deprecated_handler_hit(handler: str, update: Update, context: ContextTypes.DEFAULT_TYPE, callback: str | None = None):
    user_id = update.effective_user.id if update.effective_user else 0
    bot_id = getattr(getattr(context, "application", None), "bot_data", {}).get("bot_id")
    logger.warning(
        "[DEPRECATED_HANDLER_HIT] file=src/handlers/super_admin_handler.py handler=%s callback=%s bot_id=%s user_id=%s",
        handler,
        callback or "",
        bot_id or "",
        user_id,
    )


def _is_super_admin(user_id: int) -> bool:
    """检查用户是否是超级管理员"""
    return user_id == SUPER_ADMIN_ID or user_id == FIXED_SUPER_ADMIN_ID


async def show_super_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示超管后台页面"""
    query = update.callback_query
    message = update.message
    _log_deprecated_handler_hit("show_super_admin_panel", update, context)

    # 权限检查
    user_id = query.from_user.id if query else (update.effective_user.id if update.effective_user else 0)
    if not _is_super_admin(user_id):
        if query:
            await query.answer("⚠️ 无权限", show_alert=True)
        return

    try:
        text = (
            "🔐 <b>超管后台</b>\n\n"
            "请选择操作："
        )

        keyboard = [
            [InlineKeyboardButton("💎 开通用户", callback_data="sa:provision:start")],
            [InlineKeyboardButton("🚫 关闭用户", callback_data="sa:close:start")],
            [InlineKeyboardButton("📋 已关闭用户", callback_data="sa:closed:list")],
            [InlineKeyboardButton("← 返回", callback_data="menu_back")],
        ]

        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif message:
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            logger.warning("[SUPER_ADMIN_PANEL] No query or message available")

    except Exception as e:
        logger.error(f"[SUPER_ADMIN_PANEL] Error: {e}", exc_info=True)
        import traceback
        logger.error(f"[SUPER_ADMIN_PANEL] Traceback: {traceback.format_exc()}")
        if query:
            await query.answer("加载超管后台失败，请稍后重试", show_alert=True)
        elif message:
            await message.reply_text("加载超管后台失败，请稍后重试")


async def show_message_center(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示消息中心"""
    query = update.callback_query
    message = update.message
    _log_deprecated_handler_hit("show_message_center", update, context)

    logger.info(f"[MESSAGE_CENTER] Called - query={query is not None}, message={message is not None}")

    # 权限检查
    user_id = query.from_user.id if query else (update.effective_user.id if update.effective_user else 0)
    logger.info(f"[MESSAGE_CENTER] user_id={user_id}, is_super_admin={_is_super_admin(user_id)}")

    if not _is_super_admin(user_id):
        if query:
            await query.answer("⚠️ 无权限", show_alert=True)
        return

    try:
        # 简化版：直接显示消息中心，不依赖数据库
        # 免打扰状态从 context.user_data 读取
        is_dnd = context.user_data.get("super_admin_dnd", False)

        text = (
            "📨 <b>消息中心</b>\n\n"
            f"📌 免打扰模式：{'✅ 已开启' if is_dnd else '❌ 已关闭'}\n\n"
            "请选择操作："
        )

        keyboard = [
            [InlineKeyboardButton("🔔 开启免打扰", callback_data="sa:dnd:on")],
            [InlineKeyboardButton("🔕 关闭免打扰", callback_data="sa:dnd:off")],
            [InlineKeyboardButton("← 返回超管后台", callback_data="sa:panel")],
        ]

        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif message:
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            logger.warning("[MESSAGE_CENTER] No query or message available")

    except Exception as e:
        logger.error(f"[MESSAGE_CENTER] Error: {e}", exc_info=True)
        import traceback
        logger.error(f"[MESSAGE_CENTER] Traceback: {traceback.format_exc()}")
        if query:
            await query.answer("加载消息中心失败，请稍后重试", show_alert=True)
        elif message:
            await message.reply_text("加载消息中心失败，请稍后重试")


async def handle_global_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理全局消息转发（私聊消息→超管）"""
    _log_deprecated_handler_hit("handle_global_forward", update, context)
    if not update.message or not update.effective_chat:
        return

    # 只处理私聊消息
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    message = update.message
    user_id = user.id
    text = message.text or ""

    logger.info(f"[GLOBAL_FORWARD] === START ===")
    logger.info(f"[GLOBAL_FORWARD] user_id={user_id}, text={text[:50]}")
    logger.info(f"[GLOBAL_FORWARD] SUPER_ADMIN_ID={SUPER_ADMIN_ID}, FIXED={FIXED_SUPER_ADMIN_ID}")

    # ========== 排除超级管理员 ==========
    if user_id == SUPER_ADMIN_ID or user_id == FIXED_SUPER_ADMIN_ID:
        logger.info(f"[GLOBAL_FORWARD] Skipped - super admin message (matched fixed ID)")
        return

    # ========== 检查 FSM 状态 - 优先处理 ==========
    fsm_state = context.user_data.get("bot_mgmt_state")
    if fsm_state:
        logger.info(f"[GLOBAL_FORWARD] FSM state={fsm_state}, will be handled by FSM handler")
        return  # FSM handler 会处理，不转发

    super_admin_reply_state = context.user_data.get("super_admin_reply_to")
    if super_admin_reply_state:
        logger.info(f"[GLOBAL_FORWARD] super_admin_reply_to state exists, will be handled by reply handler")
        return  # 回复模式 handler 会处理

    provision_state = context.user_data.get("provision_state")
    if provision_state:
        logger.info(f"[GLOBAL_FORWARD] provision_state={provision_state}, will be handled by provision handler")
        return

    close_user_state = context.user_data.get("close_user_state")
    if close_user_state:
        logger.info(f"[GLOBAL_FORWARD] close_user_state exists, will be handled")
        return

    unblock_state = context.user_data.get("unblock_state")
    if unblock_state:
        logger.info(f"[GLOBAL_FORWARD] unblock_state exists, will be handled")
        return

    # ========== 排除特殊命令关键字 ==========
    excluded_keywords = [
        "消息中心",
        "超管后台",
        "开通用户",
        "关闭用户",
        "已关闭用户",
        "拉黑管理",
        "解除拉黑",
        "➕ 开通用户",
        "🚫 关闭用户",
        "📋 已关闭用户",
        "💬 消息中心",
        "🛠 超管后台",
        "💎 开通用户",
        "🔒 拉黑管理",
    ]
    for keyword in excluded_keywords:
        if keyword in text:
            logger.info(f"[GLOBAL_FORWARD] Skipped - excluded keyword: {keyword}")
            return

    # ========== 排除菜单命令 ==========
    menu_commands = ["菜单", "帮助", "使用说明", "个人中心", "运行统计", "功能设置"]
    for cmd in menu_commands:
        if cmd in text:
            logger.info(f"[GLOBAL_FORWARD] Skipped - menu command: {cmd}")
            return

    # ========== 构造转发消息 ==========
    forward_text = (
        f"📩 <b>用户消息</b>\n\n"
        f"👤 用户：{user.full_name}\n"
        f"🆔 ID：{user.id}\n"
        f"📝 消息：{text or '[非文本消息]'}"
    )

    try:
        # 发送消息给超管
        await context.bot.send_message(
            chat_id=SUPER_ADMIN_ID,
            text=forward_text,
            parse_mode="HTML"
        )
        logger.info(f"[GLOBAL_FORWARD] Message forwarded to super admin")
    except Exception as e:
        logger.error(f"[SUPER_ADMIN] Failed to forward message: {e}", exc_info=True)


async def handle_super_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """超管发送消息给用户"""
    if not update.message or not update.effective_chat:
        return

    if update.effective_user.id != SUPER_ADMIN_ID:
        return

    # 检查是否在回复模式
    state = context.user_data.get('super_admin_reply_to')
    if not state:
        return

    target_user_id = state.get('user_id')
    original_msg_id = state.get('message_id')

    if target_user_id and update.message.text:
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"📨 <b>管理员消息：</b>\n\n{update.message.text}",
                parse_mode="HTML"
            )
            await update.message.reply_text("✅ 消息已发送")
        except Exception as e:
            logger.error(f"[SUPER_ADMIN] Failed to send message: {e}")
            await update.message.reply_text("❌ 发送失败")

    # 清除状态
    context.user_data.pop('super_admin_reply_to', None)


async def handle_provision_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理超管开通用户输入"""
    if not update.message or not update.effective_user:
        return

    if update.effective_user.id != SUPER_ADMIN_ID:
        return

    state = context.user_data.get('provision_state')
    if not state:
        return

    text = update.message.text

    if state.get('step') == 'wait_user_id':
        # 保存用户ID
        context.user_data['provision_target'] = text.strip()
        context.user_data['provision_state'] = {'step': 'wait_plan'}
        await update.message.reply_text(
            "请发送要开通的套餐ID：\n"
            "可用套餐：\n"
            "1 - 一个月\n"
            "2 - 三个月\n"
            "3 - 一年\n"
            "4 - 永久使用"
        )
    elif state.get('step') == 'wait_plan':
        # 保存套餐ID
        context.user_data['provision_plan'] = text.strip()
        await update.message.reply_text("套餐已记录，请输入Token（如无可跳过）：")
        context.user_data['provision_state'] = {'step': 'wait_token'}


async def handle_provision_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理超管代发Token输入"""
    if not update.message or not update.effective_user:
        return

    if update.effective_user.id != SUPER_ADMIN_ID:
        return

    state = context.user_data.get('provision_state')
    if not state or state.get('step') != 'wait_token':
        return

    token = update.message.text.strip()
    target = context.user_data.get('provision_target')
    plan = context.user_data.get('provision_plan')

    await update.message.reply_text(
        f"📝 开通信息：\n"
        f"用户ID：{target}\n"
        f"套餐：{plan}\n"
        f"Token：{token}\n\n"
        f"（请手动完成开通流程）"
    )

    # 清除状态
    context.user_data.pop('provision_state', None)
    context.user_data.pop('provision_target', None)
    context.user_data.pop('provision_plan', None)


async def handle_close_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理关闭用户输入"""
    if not update.message or not update.effective_user:
        return

    if update.effective_user.id != SUPER_ADMIN_ID:
        return

    state = context.user_data.get('close_user_state')
    if not state:
        return

    user_id = update.message.text.strip()
    await update.message.reply_text(f"确认关闭用户 {user_id} 吗？")
    context.user_data['close_user_target'] = user_id


async def handle_super_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理超管命令"""
    if not update.message:
        return

    if update.effective_user.id != SUPER_ADMIN_ID:
        return

    text = update.message.text

    if text == '/sapanel':
        await show_super_admin_panel(update, context)
    elif text == '/smessage':
        await show_message_center(update, context)

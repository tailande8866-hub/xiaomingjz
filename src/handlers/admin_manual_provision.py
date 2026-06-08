"""
Admin Manual Provision Handler - 超管手动开通套餐处理器

功能流程：
1. 权限验证：检查是否主Bot + 超级管理员 + 私聊
2. 用户状态查询：解析@用户，查询是否已有机器人
3. 新开通流程：选择套餐 → 输入Token → 验证Token → 创建Bot → 激活订阅 → 启动Bot
4. 续费流程：选择机器人 → 选择套餐 → 激活订阅（更新到期时间）
5. 通知双方：超管和用户都收到通知

命令格式：
- 私聊回复"开通"后输入@username或user_id
- 私聊回复"取消"可中断流程
"""
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from config import config
from ..utils.role_checker import get_user_role, UserRole
from ..services.manual_provision_service import manual_provision_service

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    """
    转义HTML特殊字符，防止Telegram解析错误
    
    Args:
        text: 原始文本
    
    Returns:
        转义后的文本
    """
    if not isinstance(text, str):
        text = str(text)
    return text.replace('<', '&lt;').replace('>', '&gt;')


# FSM状态常量
STATE_WAITING_PLAN_SELECTION = "manual_provision_waiting_plan"
STATE_WAITING_TOKEN_INPUT = "manual_provision_waiting_token"
STATE_WAITING_RENEWAL_PLAN = "manual_provision_renewal_plan"
STATE_WAITING_NEW_BOT_SELECT = "manual_provision_new_bot_select"


async def handle_manual_provision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理"开通"命令（私聊）
    
    用法：
    - 私聊回复"开通"（等待输入用户）
    - 私聊回复"开通 @username" 或 "开通 user_id"（直接处理）
    """
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    telegram_id = user.id
    
    logger.info(f"[PROVISION] User {telegram_id} triggered handle_manual_provision")
    
    # ✅ 权限检查1：仅限主Bot
    bot_id = "main_bot" if os.environ.get("IS_MAIN_BOT", "true").lower() != "false" else getattr(config, 'INSTANCE_ID', None)
    logger.info(f"[PROVISION] bot_id={bot_id}, is_main_bot={bot_id == 'main_bot'}")
    if bot_id != "main_bot":
        logger.warning(f"[PROVISION] Rejected: not main bot")
        return
    
    # ✅ 权限检查2：仅限超级管理员
    role = await get_user_role(telegram_id, bot_id=bot_id)
    logger.info(f"[PROVISION] User {telegram_id} role={role}, is_super_admin={role == UserRole.SUPER_ADMIN}")
    if role != UserRole.SUPER_ADMIN:
        logger.warning(f"[PROVISION] Rejected: user is not super admin, role={role}")
        return
    
    # ✅ 权限检查3：仅限私聊
    if update.effective_chat.type != 'private':
        logger.warning(f"[PROVISION] Rejected: not private chat, type={update.effective_chat.type}")
        return
    
    # 检查是否以"开通"开头
    text = update.message.text.strip()
    if not text.startswith("开通"):
        return
    
    # 提取参数（如果有）
    parts = text.split()
    if len(parts) > 1:
        # 有参数，直接处理
        target_identifier = parts[1]
        logger.info(f"[PROVISION] User {telegram_id} sent provision with target: {target_identifier}")
        await _process_target_user(update, context, target_identifier)
        return
    
    # 没有参数，等待用户输入
    context.user_data['provision_state'] = STATE_WAITING_PLAN_SELECTION
    
    await update.message.reply_text(
        "请输入要开通的用户：\n\n"
        "格式：\n"
        "@username\n"
        "或 user_id\n\n"
        "例如：\n"
        "@xiaomingjz\n"
        "123456789\n\n"
        "发送 取消 可取消操作",
        parse_mode='HTML'
    )


async def _process_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target_identifier: str):
    """处理目标用户（解析、查询、显示选项）"""
    if not update.message or not update.effective_user:
        return
    
    # 解析目标用户ID
    target_telegram_id = await manual_provision_service.resolve_user_id(target_identifier)
    if not target_telegram_id:
        await update.message.reply_text(
            f" 无法找到用户：{target_identifier}\n\n"
            "请确保用户名正确或以@开头",
            parse_mode='HTML'
        )
        return
    
    # 获取目标用户信息
    try:
        chat = await context.bot.get_chat(target_telegram_id)
        target_username = chat.username or f"User_{target_telegram_id}"
        target_name = chat.first_name or target_username
    except Exception as e:
        logger.warning(f"Failed to get user info for {target_telegram_id}: {e}")
        target_username = f"User_{target_telegram_id}"
        target_name = target_username
    
    # 查询用户是否已有机器人
    user_bots = await manual_provision_service.query_user_bots(target_telegram_id)
    
    # 保存上下文
    context.user_data['provision_target_id'] = target_telegram_id
    context.user_data['provision_target_username'] = target_username
    context.user_data['provision_target_name'] = target_name
    
    if user_bots and len(user_bots) > 0:
        # ✅ 已有机器人 - 进入续费流程
        await _show_renewal_options(update, context, user_bots)
    else:
        # ✅ 没有机器人 - 进入新开通流程
        await _show_plans_for_new_bot(update, context)


async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一处理开通流程中的所有消息输入（用户标识 + Token）"""
    if not update.message or not update.effective_user:
        return
    
    state = context.user_data.get('provision_state')
    
    # ✅ 状态1：等待输入用户标识
    if state == STATE_WAITING_PLAN_SELECTION:
        target_identifier = update.message.text.strip()
        await _process_target_user(update, context, target_identifier)
        return
    
    # ✅ 状态2：等待输入Bot Token
    if state == STATE_WAITING_TOKEN_INPUT:
        token = update.message.text.strip()
        
        # 验证Token格式（简单验证）
        if ':' not in token or len(token) < 20:
            await update.message.reply_text(
                "❌ Bot Token 格式不正确\n\n"
                "请重新输入正确的 Bot Token：",
                parse_mode='HTML'
            )
            return
        
        logger.info(f"[TOKEN_INPUT] Token format valid, length={len(token)}")
        
        # 保存Token
        context.user_data['bot_token'] = token
        
        # 获取Bot信息
        try:
            from telegram import Bot
            bot = Bot(token=token)
            logger.info(f"[TOKEN_INPUT] Calling get_me() for token validation...")
            bot_info = await bot.get_me()
            logger.info(f"[TOKEN_INPUT] get_me() succeeded: username={bot_info.username}")
            
            bot_username = bot_info.username
            bot_name = bot_info.first_name or bot_username
            
            context.user_data['bot_username'] = bot_username
            context.user_data['bot_name'] = bot_name
            
            target_name = context.user_data.get('provision_target_name', '未知用户')
            plan_id = context.user_data.get('selected_plan_id')
            
            # 获取套餐信息
            from ..services.saas_auto_service import saas_auto_service
            plans = await saas_auto_service.get_active_plans()
            plan = next((p for p in plans if p.id == plan_id), None)
            
            # 确认信息
            msg = (
                f"✅ <b>请确认以下信息</b>\n\n"
                f"👤 目标用户：{target_name}\n"
                f" 套餐：{plan.name if plan else '未知'}\n"
                f"💰 价格：{plan.price if plan else 0} USDT\n"
                f"⏳ 时长：{plan.duration_days if plan else 0} 天\n\n"
                f"🤖 Bot：@{bot_username} ({bot_name})\n\n"
                f"请点击下方按钮确认："
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ 确认开通", callback_data="manual_provision_confirm_create"),
                    InlineKeyboardButton("❌ 取消", callback_data="manual_provision_cancel")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"[TOKEN_INPUT] Failed to validate token: {e}")
            await update.message.reply_text(
                f"❌ Bot Token 无效或无法连接\n\n"
                f"错误信息：{str(e)[:100]}\n\n"
                f"请检查 Token 是否正确，或重新输入：",
                parse_mode='HTML'
            )
        
        return
    
    # ✅ 不在任何流程中，忽略消息
    logger.debug(f"[PROVISION_INPUT] User {update.effective_user.id} sent message but not in provision flow, state={state}")
    return


# ✅ 保留旧函数名作为别名，但不再使用
handle_token_input = handle_user_input


async def _show_plans_for_new_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示套餐列表（新开通流程）"""
    from ..services.saas_auto_service import saas_auto_service
    
    plans = await saas_auto_service.get_active_plans()
    
    if not plans:
        await update.message.reply_text(
            "❌ 暂无可用套餐，请联系管理员。",
            parse_mode='HTML'
        )
        return
    
    target_name = context.user_data.get('provision_target_name', '未知用户')
    
    # 构建消息
    msg = (
        f"🆕 <b>为新用户开通套餐</b>\n\n"
        f"👤 目标用户：{target_name}\n\n"
        f"请选择套餐："
    )
    
    # 构建按钮
    keyboard = []
    for plan in plans:
        price_text = f"{plan.price} USDT" if plan.price > 0 else "免费"
        button_text = f"{plan.name} - {price_text} ({plan.duration_days}天)"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"manual_provision_select_plan_{plan.id}"
            )
        ])
    
    # 添加取消按钮
    keyboard.append([
        InlineKeyboardButton("❌ 取消", callback_data="manual_provision_cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')


async def _show_renewal_options(update: Update, context: ContextTypes.DEFAULT_TYPE, user_bots: list):
    """显示续费选项（已有机器人）"""
    target_name = context.user_data.get('provision_target_name', '未知用户')
    
    # 构建消息
    msg = (
        f"♻️ <b>为用户续费套餐</b>\n\n"
        f"👤 目标用户：{target_name}\n\n"
        f"该用户已有 {len(user_bots)} 个机器人：\n\n"
    )
    
    # 列出所有机器人
    for i, bot in enumerate(user_bots[:5], 1):  # 最多显示5个
        status_emoji = "✅" if bot.status == "running" else "❌"
        msg += f"{i}. {status_emoji} @{bot.bot_username} - {bot.bot_name}\n"
    
    if len(user_bots) > 5:
        msg += f"... 还有 {len(user_bots) - 5} 个机器人\n"
    
    msg += "\n请选择要续费的机器人："
    
    # 构建按钮
    keyboard = []
    for bot in user_bots[:5]:
        button_text = f"@{bot.bot_username}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"manual_provision_select_bot_{bot.instance_id}"
            )
        ])
    
    # 添加取消按钮
    keyboard.append([
        InlineKeyboardButton("❌ 取消", callback_data="manual_provision_cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')


async def handle_plan_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理套餐选择回调（新开通流程）"""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("manual_provision_select_plan_"):
        return
    
    plan_id_str = query.data.replace("manual_provision_select_plan_", "")
    
    try:
        plan_id = int(plan_id_str)
    except ValueError:
        await query.edit_message_text("❌ 无效的套餐ID", parse_mode='HTML')
        return
    
    # 保存选择的套餐ID
    context.user_data['selected_plan_id'] = plan_id
    context.user_data['provision_state'] = STATE_WAITING_TOKEN_INPUT
    
    # 获取套餐信息
    from ..services.saas_auto_service import saas_auto_service
    plans = await saas_auto_service.get_active_plans()
    plan = next((p for p in plans if p.id == plan_id), None)
    
    if not plan:
        await query.edit_message_text("❌ 套餐不存在", parse_mode='HTML')
        return
    
    target_name = context.user_data.get('provision_target_name', '未知用户')
    
    # 提示输入Bot Token
    msg = (
        f"✅ 已选择套餐：<b>{plan.name}</b>\n"
        f"💰 价格：{plan.price} USDT\n"
        f"⏳ 时长：{plan.duration_days} 天\n\n"
        f"👤 目标用户：{target_name}\n\n"
        f"请输入 Bot Token：\n\n"
        f"💡 提示：\n"
        f"• 从 @BotFather 获取 Bot Token\n"
        f"• Token 格式类似：123456789:ABCdefGHIjklMNOpqrsTUVwxyz\n"
        f"• 发送 取消 可取消操作"
    )
    
    await query.edit_message_text(msg, parse_mode='HTML')


async def handle_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理Bot Token输入"""
    if not update.message or not update.effective_user:
        return
    
    # 检查状态
    state = context.user_data.get('provision_state')
    if state != STATE_WAITING_TOKEN_INPUT:
        logger.warning(f"[TOKEN_INPUT] State mismatch: expected {STATE_WAITING_TOKEN_INPUT}, got {state}")
        logger.warning(f"[TOKEN_INPUT] This message may have been intercepted by another handler")
        return
    
    logger.info(f"[TOKEN_INPUT] State matched, processing token...")
    
    token = update.message.text.strip()
    
    # 验证Token格式（简单验证）
    if ':' not in token or len(token) < 20:
        await update.message.reply_text(
            "❌ Bot Token 格式不正确\n\n"
            "请重新输入正确的 Bot Token：",
            parse_mode='HTML'
        )
        return
    
    logger.info(f"[TOKEN_INPUT] Token format valid, length={len(token)}")
    
    # 保存Token
    context.user_data['bot_token'] = token
    
    # 获取Bot信息
    try:
        from telegram import Bot
        bot = Bot(token=token)
        logger.info(f"[TOKEN_INPUT] Calling get_me() for token validation...")
        bot_info = await bot.get_me()
        logger.info(f"[TOKEN_INPUT] get_me() succeeded: username={bot_info.username}")
        
        bot_username = bot_info.username
        bot_name = bot_info.first_name or bot_username
        
        context.user_data['bot_username'] = bot_username
        context.user_data['bot_name'] = bot_name
        
        target_name = context.user_data.get('provision_target_name', '未知用户')
        plan_id = context.user_data.get('selected_plan_id')
        
        # 获取套餐信息
        from ..services.saas_auto_service import saas_auto_service
        plans = await saas_auto_service.get_active_plans()
        plan = next((p for p in plans if p.id == plan_id), None)
        
        # 确认信息
        msg = (
            f"✅ <b>请确认以下信息</b>\n\n"
            f"👤 目标用户：{target_name}\n"
            f"📦 套餐：{plan.name if plan else '未知'}\n"
            f"🤖 Bot名称：{bot_name}\n"
            f"👤 Bot用户名：@{bot_username}\n\n"
            f"确认后将执行以下操作：\n"
            f"1. 创建Bot实例\n"
            f"2. 激活订阅\n"
            f"3. 自动启动Bot\n\n"
            f"请点击下方按钮确认："
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ 确认创建", callback_data="manual_provision_confirm_create"),
                InlineKeyboardButton("❌ 取消", callback_data="manual_provision_cancel")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"[TOKEN_INPUT] Failed to get bot info: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ 无法获取Bot信息：{str(e)}\n\n"
            "请检查Token是否正确，或重新输入：",
            parse_mode='HTML'
        )


async def handle_confirm_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认创建Bot并激活订阅"""
    query = update.callback_query
    await query.answer()
    
    if query.data != "manual_provision_confirm_create":
        return
    
    # 获取所有必要信息
    target_telegram_id = context.user_data.get('provision_target_id')
    target_username = context.user_data.get('provision_target_username')
    bot_token = context.user_data.get('bot_token')
    bot_username = context.user_data.get('bot_username')
    bot_name = context.user_data.get('bot_name')
    plan_id = context.user_data.get('selected_plan_id')
    operator_id = update.effective_user.id
    
    # 调试：检查哪个字段缺失
    missing_fields = []
    if not target_telegram_id:
        missing_fields.append("target_telegram_id")
    if not bot_token:
        missing_fields.append("bot_token")
    if not bot_username:
        missing_fields.append("bot_username")
    if not bot_name:
        missing_fields.append("bot_name")
    if not plan_id:
        missing_fields.append("plan_id")
    
    if missing_fields:
        logger.error(f"[CONFIRM_CREATE] Missing fields: {missing_fields}")
        logger.error(f"[CONFIRM_CREATE] user_data: {context.user_data}")
        await query.edit_message_text(
            f"❌ 创建信息不完整，请重新开始。\n\n缺失字段：{', '.join(missing_fields)}",
            parse_mode='HTML'
        )
        _clear_provision_state(context)
        return
    
    # 显示创建中提示
    await query.edit_message_text(
        "🔄 <b>正在创建机器人...</b>\n\n"
        "请稍候，这可能需要几分钟时间...",
        parse_mode='HTML'
    )
    
    try:
        # 1. 创建Bot实例
        success, message, bot_creation = await manual_provision_service.manual_create_bot(
            telegram_id=target_telegram_id,
            username=target_username,
            bot_token=bot_token,
            bot_username=bot_username,
            bot_name=bot_name,
            operator_id=operator_id
        )
        
        if not success:
            # ✅ 关键修复:清理错误消息中的 HTML 标签
            safe_message = _escape_html(message)
            await query.edit_message_text(
                f"❌ 创建Bot失败\n\n{safe_message}",
                parse_mode='HTML'
            )
            _clear_provision_state(context)
            return
        
        # 2. 激活订阅
        success, sub_message = await manual_provision_service.manual_activate_subscription(
            telegram_id=target_telegram_id,
            username=target_username,
            plan_id=plan_id,
            operator_id=operator_id
        )
        
        if not success:
            # ✅ 关键修复:清理错误消息中的 HTML 标签
            safe_sub_message = _escape_html(sub_message)
            await query.edit_message_text(
                f"⚠️ Bot创建成功，但订阅激活失败\n\n"
                f"Bot信息：{message}\n\n"
                f"订阅错误：{safe_sub_message}",
                parse_mode='HTML'
            )
            _clear_provision_state(context)
            return
        
        # 3. 成功通知超管
        success_msg = (
            f"🎉 <b>手动开通成功！</b>\n\n"
            f"👤 目标用户：{target_username}\n"
            f"🤖 Bot名称：{bot_name}\n"
            f"👤 Bot用户名：@{bot_username}\n"
            f"📦 套餐：{sub_message}\n\n"
            f"✅ Bot已自动启动\n"
            f"✅ 订阅已激活\n\n"
            f"💡 提示：\n"
            f"• 用户可以立即开始使用 @{bot_username}\n"
            f"• 系统已发送通知给用户"
        )
        
        # 极简版按钮
        keyboard = [
            [InlineKeyboardButton("🛠 超管后台", callback_data="sa:panel"),
             InlineKeyboardButton("📋 已关闭用户", callback_data="sa:closed:list")],
            [InlineKeyboardButton("💬 消息中心", callback_data="sa:message_center"),
             InlineKeyboardButton("🔙 返回", callback_data="sa:panel")],
        ]
        await query.edit_message_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
        # 4. 通知目标用户
        try:
            from ..handlers.bot_management_handler import _build_bot_manage_scene_text, render_bot_manage_buttons
            notify_msg = _build_bot_manage_scene_text(bot_creation, "created_success")
            await context.bot.send_message(
                chat_id=target_telegram_id,
                text=notify_msg,
                reply_markup=render_bot_manage_buttons(bot_creation.instance_id, target_telegram_id, "created_success"),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.warning(f"Failed to notify user {target_telegram_id}: {e}")
        
    except Exception as e:
        logger.error(f"Error in confirm_create: {e}", exc_info=True)
        # ✅ 关键修复:清理错误消息中的 HTML 标签
        # 防止异常对象(如 <BotCreation at 0x...>)被 Telegram 解析为 HTML 标签
        safe_error = _escape_html(str(e))
        await query.edit_message_text(
            f"❌ 创建过程中发生错误：{safe_error}",
            parse_mode='HTML'
        )
    
    finally:
        _clear_provision_state(context)


async def handle_bot_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理机器人选择回调（续费流程）"""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("manual_provision_select_bot_"):
        return
    
    instance_id = query.data.replace("manual_provision_select_bot_", "")
    
    # 保存选择的Bot ID
    context.user_data['selected_bot_instance_id'] = instance_id
    context.user_data['provision_state'] = STATE_WAITING_RENEWAL_PLAN
    
    # 显示套餐列表
    from ..services.saas_auto_service import saas_auto_service
    
    plans = await saas_auto_service.get_active_plans()
    
    if not plans:
        await query.edit_message_text(
            "❌ 暂无可用套餐，请联系管理员。",
            parse_mode='HTML'
        )
        return
    
    target_name = context.user_data.get('provision_target_name', '未知用户')
    
    # 构建消息
    msg = (
        f"♻️ <b>为机器人续费</b>\n\n"
        f"👤 目标用户：{target_name}\n"
        f"🤖 机器人：@{instance_id}\n\n"
        f"请选择续费套餐："
    )
    
    # 构建按钮
    keyboard = []
    for plan in plans:
        price_text = f"{plan.price} USDT" if plan.price > 0 else "免费"
        button_text = f"{plan.name} - {price_text} ({plan.duration_days}天)"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"manual_provision_renewal_plan_{plan.id}"
            )
        ])
    
    # 添加取消按钮
    keyboard.append([
        InlineKeyboardButton("❌ 取消", callback_data="manual_provision_cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='HTML')


async def handle_renewal_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理续费套餐选择回调"""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("manual_provision_renewal_plan_"):
        return
    
    plan_id_str = query.data.replace("manual_provision_renewal_plan_", "")
    
    try:
        plan_id = int(plan_id_str)
    except ValueError:
        await query.edit_message_text("❌ 无效的套餐ID", parse_mode='HTML')
        return
    
    # 获取所有必要信息
    target_telegram_id = context.user_data.get('provision_target_id')
    target_username = context.user_data.get('provision_target_username')
    instance_id = context.user_data.get('selected_bot_instance_id')
    operator_id = update.effective_user.id
    
    if not all([target_telegram_id, target_username, instance_id]):
        await query.edit_message_text(
            "❌ 续费信息不完整，请重新开始。",
            parse_mode='HTML'
        )
        _clear_provision_state(context)
        return
    
    # 获取套餐信息
    from ..services.saas_auto_service import saas_auto_service
    plans = await saas_auto_service.get_active_plans()
    plan = next((p for p in plans if p.id == plan_id), None)
    
    if not plan:
        await query.edit_message_text("❌ 套餐不存在", parse_mode='HTML')
        return
    
    # 确认信息
    msg = (
        f"✅ <b>请确认续费信息</b>\n\n"
        f"👤 目标用户：{target_username}\n"
        f"🤖 机器人：@{instance_id}\n"
        f"📦 套餐：{plan.name}\n"
        f"💰 价格：{plan.price} USDT\n"
        f"⏳ 时长：{plan.duration_days} 天\n\n"
        f"点击确认后将为该用户续费套餐。"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认续费", callback_data="manual_provision_confirm_renewal"),
            InlineKeyboardButton("❌ 取消", callback_data="manual_provision_cancel")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='HTML')


async def handle_confirm_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认续费"""
    query = update.callback_query
    await query.answer()
    
    if query.data != "manual_provision_confirm_renewal":
        return
    
    # 获取所有必要信息
    target_telegram_id = context.user_data.get('provision_target_id')
    target_username = context.user_data.get('provision_target_username')
    plan_id = context.user_data.get('selected_plan_id')
    operator_id = update.effective_user.id
    
    if not all([target_telegram_id, target_username, plan_id]):
        await query.edit_message_text(
            "❌ 续费信息不完整，请重新开始。",
            parse_mode='HTML'
        )
        _clear_provision_state(context)
        return
    
    # 显示处理中提示
    await query.edit_message_text(
        "🔄 <b>正在处理续费...</b>\n\n"
        "请稍候...",
        parse_mode='HTML'
    )
    
    try:
        # 激活/续费订阅
        success, message = await manual_provision_service.manual_activate_subscription(
            telegram_id=target_telegram_id,
            username=target_username,
            plan_id=plan_id,
            operator_id=operator_id
        )
        
        if not success:
            await query.edit_message_text(
                f"❌ 续费失败\n\n{message}",
                parse_mode='HTML'
            )
            _clear_provision_state(context)
            return
        
        # 成功通知超管
        success_msg = (
            f"🎉 <b>续费成功！</b>\n\n"
            f"👤 目标用户：{target_username}\n"
            f"📦 套餐：{message}\n\n"
            f"✅ 订阅已延长\n\n"
            f"💡 提示：\n"
            f"• 用户的机器人可以继续正常使用\n"
            f"• 系统已发送通知给用户"
        )
        
        # 极简版按钮
        keyboard = [
            [InlineKeyboardButton("🛠 超管后台", callback_data="sa:panel"),
             InlineKeyboardButton("📋 已关闭用户", callback_data="sa:closed:list")],
            [InlineKeyboardButton("💬 消息中心", callback_data="sa:message_center"),
             InlineKeyboardButton("🔙 返回", callback_data="sa:panel")],
        ]
        await query.edit_message_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
        # 通知目标用户
        try:
            notify_msg = (
                f"🎉 <b>恭喜！您的套餐已续费</b>\n\n"
                f"📦 套餐：{message}\n\n"
                f"✅ 您的机器人可以继续正常使用！\n\n"
                f"💡 提示：\n"
                f"• 如有问题请联系客服：@xiaomingjz"
            )
            
            await context.bot.send_message(
                chat_id=target_telegram_id,
                text=notify_msg,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.warning(f"Failed to notify user {target_telegram_id}: {e}")
        
    except Exception as e:
        logger.error(f"Error in confirm_renewal: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ 续费过程中发生错误：{str(e)}",
            parse_mode='HTML'
        )
    
    finally:
        _clear_provision_state(context)


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消操作 - 支持回调按钮和 /cancel 命令"""
    # 检查是回调还是命令
    if update.callback_query:
        # 回调按钮取消
        query = update.callback_query
        await query.answer()
        
        if query.data != "manual_provision_cancel":
            return
        
        _clear_provision_state(context)
        
        await query.edit_message_text(
            "❌ 操作已取消",
            parse_mode='HTML'
        )
    elif update.message:
        # /cancel 命令取消
        provision_state = context.user_data.get('provision_state')
        
        if not provision_state:
            # 没有处于任何流程，忽略
            return
        
        logger.info(f"[CANCEL] User {update.effective_user.id} cancelled provision flow")
        _clear_provision_state(context)
        
        await update.message.reply_text(
            "❌ 操作已取消\n\n"
            "如果重新开始，请发送 开通",
            parse_mode='HTML'
        )


def _clear_provision_state(context: ContextTypes.DEFAULT_TYPE):
    """清理FSM状态"""
    keys_to_clear = [
        'provision_target_id',
        'provision_target_username',
        'provision_target_name',
        'selected_plan_id',
        'selected_bot_instance_id',
        'bot_token',
        'bot_username',
        'bot_name',
        'provision_state'
    ]
    
    cleared_keys = []
    for key in keys_to_clear:
        if key in context.user_data:
            context.user_data.pop(key, None)
            cleared_keys.append(key)
    
    logger.info(f"Provision state cleared. Cleared keys: {cleared_keys}")
    logger.debug(f"Remaining user_data keys after cleanup: {list(context.user_data.keys())}")


def register_manual_provision_handlers(application):
    """注册手动开通套餐的Handlers"""
    
    # ✅ 使用MessageHandler匹配私聊文本命令（支持带参数）
    # 只允许以“开通”开头，避免普通消息误入开通状态机。
    application.add_handler(MessageHandler(
        filters.Regex(r'^开通(?:\s|$)') & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_manual_provision
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r'^取消$') & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_cancel
    ))
    
    # Callback Handlers
    application.add_handler(CallbackQueryHandler(handle_plan_selection_callback, pattern=r'^manual_provision_select_plan_'))
    application.add_handler(CallbackQueryHandler(handle_bot_selection_callback, pattern=r'^manual_provision_select_bot_'))
    application.add_handler(CallbackQueryHandler(handle_renewal_plan_callback, pattern=r'^manual_provision_renewal_plan_'))
    application.add_handler(CallbackQueryHandler(handle_confirm_create, pattern=r'^manual_provision_confirm_create$'))
    application.add_handler(CallbackQueryHandler(handle_confirm_renewal, pattern=r'^manual_provision_confirm_renewal$'))
    application.add_handler(CallbackQueryHandler(handle_cancel, pattern=r'^manual_provision_cancel$'))
    
    # Message Handler for all provision flow input (user identifier + token)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_user_input
    ))
    
    logger.info("Manual provision handlers registered")

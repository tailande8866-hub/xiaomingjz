"""
SaaS购买流程处理器
处理套餐选择、支付、自动创建Bot
"""
import asyncio
import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..services.saas_auto_service import saas_auto_service
from ..services.account_status_service import account_status_service
from ..services.usdt_payment_service import usdt_service
from ..utils.role_checker import get_user_role, UserRole
from ..utils.rate_limiter import rate_limit_confirm_payment, rate_limit_create_bot, rate_limit_payment
from ..utils.state_manager import clear_state

logger = logging.getLogger(__name__)


def _mask_token_for_log(token: str) -> str:
    if not token:
        return "<empty>"
    if ":" not in token:
        return f"{token[:3]}***"
    prefix, suffix = token.split(":", 1)
    return f"{prefix}:***{suffix[-4:]}" if len(suffix) > 4 else f"{prefix}:***"


async def _send_or_edit(update: Update, text: str, reply_markup=None):
    """兼容底部菜单消息和内联按钮回调的输出。"""
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')


def _format_datetime(value) -> str:
    if not value:
        return "未记录"
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def _format_bot_name(bot_info) -> str:
    name = bot_info.bot_name or bot_info.bot_username or bot_info.instance_id
    if bot_info.bot_username:
        return f"{_escape_html(name)} (@{_escape_html(bot_info.bot_username)})"
    return _escape_html(name)


def _get_plain_bot_token(bot_info) -> str | None:
    token = bot_info.bot_token
    if not token:
        return None
    try:
        from ..utils.token_encryptor import token_encryptor
        return token_encryptor.decrypt_from_base64(token)
    except Exception:
        return token


async def _validate_bot_token(token: str) -> tuple[bool, dict | None, str | None]:
    """调用 Telegram getMe 检查 Token 是否仍然可用。"""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=10
            )
            result = response.json()
        if not result.get("ok"):
            return False, None, result.get("description", "Token invalid")
        return True, result.get("result", {}), None
    except Exception as e:
        logger.warning(f"Validate bot token failed: {e}")
        return False, None, str(e)


async def _is_bot_token_valid(bot_info) -> bool:
    token = _get_plain_bot_token(bot_info)
    if not token:
        return False
    ok, bot_data, _ = await _validate_bot_token(token)
    if ok:
        try:
            from sqlalchemy import select
            from ..models import BotCreation, get_db_session

            async with get_db_session() as db:
                result = await db.execute(select(BotCreation).where(BotCreation.instance_id == bot_info.instance_id))
                bot_record = result.scalar_one_or_none()
                if bot_record:
                    bot_record.token_status = "normal"
                    bot_record.token_invalid_reason = None
                    bot_record.lifecycle_status = "ACTIVE"
                    if bot_record.status in ("stopped", "error", "failed", "expired"):
                        bot_record.status = "running"
                    if bot_data:
                        bot_record.bot_username = bot_data.get("username") or bot_record.bot_username
                        bot_record.bot_name = bot_data.get("first_name") or bot_record.bot_name
                    await db.commit()
        except Exception:
            logger.error("[SAAS_TOKEN] failed to sync valid token status for %s", getattr(bot_info, "instance_id", None), exc_info=True)
    return ok


async def _get_subscription_and_plan(telegram_id: int):
    from sqlalchemy import select
    from ..models import PricingPlan, Subscription, get_db_session

    async with get_db_session() as db:
        result = await db.execute(
            select(Subscription)
            .where(Subscription.telegram_id == telegram_id)
            .order_by(Subscription.updated_at.desc())
        )
        subscription = result.scalar_one_or_none()
        plan = None
        if subscription:
            plan_result = await db.execute(select(PricingPlan).where(PricingPlan.id == subscription.plan_id))
            plan = plan_result.scalar_one_or_none()
    return subscription, plan


def _package_name(subscription, plan) -> str:
    if plan and plan.name:
        return plan.name
    if subscription and subscription.plan_name:
        return subscription.plan_name
    if subscription:
        return {
            30: "1个月",
            90: "3个月",
            365: "1年",
            3650: "永久",
        }.get(subscription.plan_id, "当前套餐")
    return "暂无套餐"


def _package_status(subscription, bot_info) -> str:
    now = datetime.utcnow()
    expire_time = bot_info.expire_time or (subscription.expire_date if subscription else None)
    if expire_time and expire_time.replace(tzinfo=None) < now:
        return "已到期"
    if subscription and subscription.status == "active":
        return "正常"
    if bot_info.lifecycle_status:
        return bot_info.lifecycle_status
    return "未订阅"


def _plan_button_text(plan) -> str:
    price = plan.price
    if plan.duration_days == 30:
        return f"1个月 | {price} USDT"
    if plan.duration_days == 90:
        return f"3个月 | {price} USDT"
    if plan.duration_days == 365:
        return f"🔥 1年 | {price} USDT"
    if plan.duration_days >= 3650:
        return f"✨ 永久 | {price} USDT"
    return f"{plan.name} | {price} USDT"


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


async def handle_create_renew_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    【创建续费】统一入口
    根据用户是否已创建 Bot 自动判断走创建流程还是续费流程
    
    流程：
    1. ✅ 首先检查当前是否在子 Bot 里，且当前 Bot 是用户创建的 → 直接显示续费页面
    2. 检查用户是否已创建 Bot
    3. 未创建 → 显示创建流程的套餐选择（可爱版文案）
    4. 已创建 → 显示续费流程的套餐选择（可爱版文案）
    """
    try:
        user = update.effective_user
        telegram_id = user.id
        account_status = await account_status_service.resolve(telegram_id, None)

        # ✅ 第一步：检查当前 Bot 是否是用户的
        # 尝试获取当前 bot_id
        try:
            from ..utils.bot_id_middleware import get_current_bot_id
            current_bot_id = get_current_bot_id(context)
            logger.info(f"[SAAS_ENTRY] Current Bot ID: {current_bot_id}")
            
            # 查询当前 Bot 信息
            from ..models import BotCreation, get_db_session
            async with get_db_session() as db:
                from sqlalchemy import select
                query = select(BotCreation).where(BotCreation.instance_id == current_bot_id)
                result = await db.execute(query)
                current_bot = result.scalar_one_or_none()

                if current_bot and current_bot.telegram_id == telegram_id:
                    # ✅ 当前 Bot 就是用户创建的 → 直接走续费流程
                    logger.info(f"[SAAS_ENTRY] User is on their own Bot {current_bot_id}, showing renew page")
                    await _route_existing_bot_renewal(update, context, current_bot)
                    return
        except Exception as e:
            logger.warning(f"[SAAS_ENTRY] Could not check current Bot: {e}")

        if account_status.active_bot:
            logger.info(
                "[SAAS_ENTRY] Unified account status found existing bot %s for user %s, showing renew page",
                account_status.active_bot.instance_id,
                telegram_id,
            )
            await _route_existing_bot_renewal(update, context, account_status.active_bot)
            return

        # ✅ 第二步：回退方案 - 检查用户是否已经创建过机器人
        user_bots = await saas_auto_service.get_user_bots(telegram_id)
        
        if user_bots and len(user_bots) > 0:
            # 已创建过 Bot → 走续费流程
            valid_bots = [bot for bot in user_bots if getattr(bot, "lifecycle_status", None) != "DELETED"]
            await _route_existing_bot_renewal(update, context, valid_bots[0] if valid_bots else user_bots[0])
        else:
            # 未创建过 Bot → 走创建流程
            await _show_create_pricing_plans(update, context)
            
    except Exception as e:
        logger.error(f"Error in handle_create_renew_entry: {e}", exc_info=True)
        try:
            await _send_or_edit(update,
                "❌ <b>处理请求时出现错误</b>\n\n"
                "请稍后重试，或联系客服：@xiaomingjz"
            )
        except Exception:
            pass


async def _show_create_pricing_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    显示创建 Bot 的套餐列表（可爱版文案）
    """
    try:
        # 查询可用套餐
        plans = await saas_auto_service.get_active_plans()
        
        if not plans:
            await _send_or_edit(update, "❌ 暂无可用套餐，请联系客服：@xiaomingjz")
            return
        
        # 可爱版创建文案
        text = (
            "💡 <b>来创建属于你自己的专属记账Bot啦～</b>\n"
            "仅支持 TRC20-USDT 支付哦\n\n"
            "✨ <b>创建成功后你可以拥有：</b>\n"
            "• 一只完全属于你自己的独立小机器人\n"
            "• 随便更换它的头像和名字\n"
            "• 独立后台，所有数据自己说了算\n"
            "• 群组记账功能无限制随便用\n\n"
            "快来选一个套餐吧👇"
        )
        
        # 构建套餐按钮
        keyboard = []
        for plan in plans:
            button_text = _plan_button_text(plan)
            callback_data = f"select_plan_{plan.id}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 设置用户状态为创建模式
        context.user_data['flow_mode'] = 'create'
        
        await _send_or_edit(update, text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in _show_create_pricing_plans: {e}", exc_info=True)
        await _send_or_edit(update, "❌ 加载套餐失败，请稍后重试")


async def _route_existing_bot_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_info):
    """已有机器人入口：Token 有效显示续费套餐，失效则进入重绑流程。"""
    token_valid = await _is_bot_token_valid(bot_info)
    if token_valid:
        await _show_renew_pricing_plans(update, context, bot_info)
        return
    await _show_token_rebind_prompt(update, context, bot_info)


async def _show_token_rebind_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_info):
    context.user_data['rebinding_bot_token'] = True
    context.user_data['rebind_bot_instance_id'] = bot_info.instance_id
    clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')

    text = (
        "⚠️ <b>检测到你的机器人Token已失效</b>\n\n"
        "请重新发送一次你的Bot Token，我们会自动恢复你的到期时间和数据，无需重新续费哦～\n\n"
        f"🤖 当前机器人：{_format_bot_name(bot_info)}\n"
        f"🆔 机器人ID：<code>{bot_info.instance_id}</code>\n\n"
        "把新的 Token 直接发到这里就可以啦。"
    )
    await _send_or_edit(update, text)


async def _sync_renewed_bot_expire(context: ContextTypes.DEFAULT_TYPE, telegram_id: int):
    """续费成功后同步 BotCreation 的到期时间，生命周期恢复为 ACTIVE。"""
    renew_bot_id = context.user_data.get('renew_bot_id')
    if not renew_bot_id:
        return

    from sqlalchemy import and_, select
    from ..models import BotCreation, Subscription, get_db_session

    async with get_db_session() as db:
        sub_result = await db.execute(
            select(Subscription).where(
                and_(Subscription.telegram_id == telegram_id, Subscription.status == "active")
            )
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription:
            return

        bot_result = await db.execute(
            select(BotCreation).where(
                and_(
                    BotCreation.instance_id == renew_bot_id,
                    (BotCreation.telegram_id == telegram_id) | (BotCreation.super_admin_id == telegram_id)
                )
            )
        )
        bot_record = bot_result.scalar_one_or_none()
        if not bot_record:
            return

        bot_record.expire_time = subscription.expire_date
        bot_record.lifecycle_status = "ACTIVE"
        bot_record.grace_period_end = None
        bot_record.archived_at = None
        if bot_record.status in ("stopped", "error", "expired"):
            bot_record.status = "created"


async def _show_renew_pricing_plans(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_info):
    """
    显示续费 Bot 的套餐列表（可爱版文案）
    """
    try:
        from ..services.token_check_service import token_check_service
        
        # 获取Token状态
        token_status = getattr(bot_info, 'token_status', 'normal')
        
        subscription, plan = await _get_subscription_and_plan(bot_info.telegram_id)
        expire_time = bot_info.expire_time or (subscription.expire_date if subscription else None)
        package_name = _package_name(subscription, plan)
        status = _package_status(subscription, bot_info)
        
        # Token失效时显示特殊页面
        if token_status == 'invalid':
            text = (
                "💖 <b>给你的专属记账Bot续费啦～</b>\n"
                f"🤖 机器人名称：{_format_bot_name(bot_info)}\n"
                f"🆔 机器人ID：<code>{bot_info.instance_id}</code>\n"
                f"📅 当前到期时间：{_format_datetime(expire_time)}\n"
                f"💡 当前套餐：{_escape_html(package_name)}（{_escape_html(status)}）\n"
                f"🔑 Token状态：❌ 已失效\n\n"
                "⚠️ 无法继续续费，请先重新绑定Token！\n\n"
                "直接回复新的 Bot Token，即可自动恢复到期时间与所有数据，无需重新购买。\n\n"
                "绑定成功后，机器人将立即恢复正常，届时可以继续续费~"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔁 重新输入Token", callback_data="rebind_token")],
                [InlineKeyboardButton("⬅️ 返回菜单", callback_data="menu:close")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 设置重绑状态
            await token_check_service.handle_token_invalid(bot_info.instance_id, update.effective_user.id, context)
            context.user_data['rebinding_bot_token'] = True
            context.user_data['rebind_bot_instance_id'] = bot_info.instance_id
            
            await _send_or_edit(update, text, reply_markup=reply_markup)
            return
        
        # Token正常时显示续费页面
        plans = await saas_auto_service.get_active_plans()
        
        if not plans:
            await _send_or_edit(update, "❌ 暂无可用套餐，请联系客服：@xiaomingjz")
            return

        text = (
            "💖 <b>给你的专属记账Bot续费啦～</b>\n"
            f"🤖 机器人名称：{_format_bot_name(bot_info)}\n"
            f"🆔 机器人ID：<code>{bot_info.instance_id}</code>\n"
            f"📅 当前到期时间：{_format_datetime(expire_time)}\n"
            f"💡 当前套餐：{_escape_html(package_name)}（{_escape_html(status)}）\n"
            f"🔑 Token状态：✅ 正常\n\n"
            "这是为你自己的机器人续费哦～\n\n"
            "仅支持 TRC20-USDT 支付哦✨\n\n"
            "续费成功后可以继续享受：\n"
            "• 你的专属小机器人正常使用\n"
            "• 头像、名称、设置全部保留\n"
            "• 数据不会丢失，无缝继续使用\n"
            "• 群组记账功能持续在线\n\n"
            "选个套餐给它续命吧👇"
        )
        
        # 构建套餐按钮
        keyboard = []
        for plan in plans:
            button_text = _plan_button_text(plan)
            callback_data = f"select_plan_{plan.id}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 设置用户状态为续费模式
        context.user_data['flow_mode'] = 'renew'
        context.user_data['renew_bot_id'] = bot_info.instance_id

        await _send_or_edit(update, text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in _show_renew_pricing_plans: {e}", exc_info=True)
        await _send_or_edit(update, "❌ 加载套餐失败，请稍后重试")


async def handle_create_bot_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理"创建机器人"按钮点击（兼容代理函数）
    
    ⚠️ 已迁移：此函数现在作为代理，实际逻辑在 handle_create_renew_entry
    保留此函数是为了兼容旧代码引用（menu_adapter.py 等）
    
    Phase 1 兼容方案：旧入口 → 新入口
    """
    logger.info(f"[COMPAT] handle_create_bot_click called, forwarding to handle_create_renew_entry")
    await handle_create_renew_entry(update, context)


async def show_pricing_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    显示套餐列表（完整开通流程）
    1. 查询用户是否创建过bot
    2. 已创建则提示续费，未创建则引导创建
    """
    try:
        logger.info(f"show_pricing_plans called for user {update.effective_user.id}")
        await handle_create_renew_entry(update, context)
        return
        
        # 🆕 获取当前用户信息
        user = update.effective_user
        telegram_id = user.id
        username = user.username or str(telegram_id)
        
        # 🆕 查询用户是否已经创建过机器人
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
        user_bots = await saas_auto_service.get_user_bots(telegram_id)
        
        plans = await saas_auto_service.get_active_plans()
        logger.info(f"Got {len(plans)} plans from get_active_plans()")
        
        if not plans:
            logger.warning("No active plans found, showing error message")
            await update.message.reply_text(
                "❌ 暂无可用套餐，请联系管理员。",
                parse_mode='HTML'
            )
            return
        
        logger.info(f"Displaying {len(plans)} plans to user")
        
        # 获取机器人用户名
        bot_username = context.bot.username
        
        # 🆕 根据用户是否创建过bot，构建不同的消息
        if user_bots and len(user_bots) > 0:
            # ✅ 已创建过机器人 - 提示续费
            bot_info = user_bots[0]
            
            # 查询订阅状态
            subscription = await saas_auto_service.get_user_subscription(telegram_id)
            
            if subscription and subscription.status == 'active':
                # 计算剩余天数
                from datetime import timezone
                now = datetime.utcnow()
                expire_date = subscription.expire_date
                remaining_days = (expire_date - now).days
                
                status_msg = (
                    f"💡 <b>开通续费仅支持TRC20-USDT</b>\n\n"
                    f"✅ 您已创建过机器人，当前处于<b>续费模式</b>\n\n"
                    f"🤖 您的机器人：@{bot_info.bot_username}\n"
                    f"📅 订阅到期时间：{expire_date.strftime('%Y-%m-%d %H:%M')}\n"
                    f"⏳ 剩余天数：{remaining_days} 天\n\n"
                    f"✅ 选择下方套餐即可立即续费，延长使用时间\n\n"
                    f"@{bot_username}"
                )
            else:
                status_msg = (
                    f"💡 <b>开通续费仅支持TRC20-USDT</b>\n\n"
                    f"✅ 您已创建过机器人，但订阅已过期或未激活\n\n"
                    f"🤖 您的机器人：@{bot_info.bot_username}\n\n"
                    f"✅ 选择下方套餐即可重新激活或续费\n\n"
                    f"@{bot_username}"
                )
        else:
            # ❌ 未创建过机器人 - 提示创建
            status_msg = (
                f"💡 <b>开通续费仅支持TRC20-USDT</b>\n\n"
                f"✅ 可享受无限制使用群记账功能(不限群数量)请选择(续费套餐按钮)\n"
                f"按指定金额付款后自动成功续费\n\n"
                f"✅ 注意,当前机器人为定制版本机器人,续费给当前机器人!\n\n"
                f"@{bot_username}"
            )
        
        # 构建内联按钮（按照图片样式）
        buttons = []
        for plan in plans:
            # 根据套餐时长生成按钮文本
            duration = plan.duration_days
            price = plan.price
            
            if duration == 30:
                button_text = f"1个月 | {price} USDT"
            elif duration == 90:
                button_text = f"3个月 | {price} USDT"
            elif duration == 365:
                button_text = f"🔥 1年 | {price} USDT"
            elif duration >= 3650:  # 永久
                button_text = f"✨ 永久 | {price} USDT"
            else:
                button_text = f"{plan.name} | {price} USDT"
            
            buttons.append([InlineKeyboardButton(
                button_text,
                callback_data=f"select_plan_{plan.id}"
            )])
        
        keyboard = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(status_msg, parse_mode='HTML', reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in show_pricing_plans: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ <b>处理您的请求时出现错误</b>\n\n"
                f"错误信息：{str(e)}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass


async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理套餐选择回调"""
    try:
        query = update.callback_query
        await query.answer()
        
        # 检查是否配置了USDT收款地址
        if not usdt_service.payment_address:
            await query.edit_message_text(
                "❌ <b>支付功能暂未配置</b>\n\n"
                "请先配置 USDT 收款地址后才能使用支付功能。\n\n"
                "如有疑问，请联系管理员。",
                parse_mode='HTML'
            )
            return
        
        # 解析套餐ID
        plan_id = int(query.data.replace('select_plan_', ''))
        user = update.effective_user
        telegram_id = user.id
        username = user.username or str(telegram_id)
        
        # 获取套餐信息
        from sqlalchemy import select
        from ..models import PricingPlan, get_db
        
        async for db in get_db():
            try:
                query_stmt = select(PricingPlan).where(PricingPlan.id == plan_id)
                result = await db.execute(query_stmt)
                plan = result.scalar_one_or_none()
                
                if not plan:
                    await query.edit_message_text(
                        "❌ 套餐不存在，请重新选择。",
                        parse_mode='HTML'
                    )
                    return
                
                # 生成支付订单
                order = await usdt_service.generate_payment_order(
                    telegram_id=telegram_id,
                    username=username,
                    plan_id=plan_id,
                    amount=plan.price
                )
                
                # 保存订单信息到用户数据
                context.user_data['pending_order'] = order
                context.user_data['selected_plan_id'] = plan_id
                
                # 显示支付信息（🆕 使用动态金额）
                dynamic_amount = order['amount']
                base_amount = order.get('base_amount', plan.price)
                
                # 格式化金额显示，保留6位小数
                formatted_amount = f"{dynamic_amount:.6f}"
                
                payment_msg = f"💳 <b>支付订单</b>\n\n"
                payment_msg += f"📦 套餐：{plan.name}\n"
                payment_msg += f"💰 基础金额：<b>{base_amount} USDT</b>\n"
                payment_msg += f"🎯 实际支付：<code>{formatted_amount} USDT</code>\n"
                payment_msg += f"⏱️ 时长：{plan.duration_days} 天\n"
                payment_msg += f"🤖 可创建：{plan.max_bots} 个机器人\n\n"
                payment_msg += f"<b>⚠️ 重要提示：</b>\n"
                payment_msg += f"请务必支付 <b>精确金额</b>（含小数点后6位）\n"
                payment_msg += f"这样才能确保系统正确匹配您的订单\n\n"
                payment_msg += f"<b>支付方式：</b>\n"
                payment_msg += f"1️⃣ 复制下方收款地址\n"
                payment_msg += f"2️⃣ 使用钱包发送 <code>{formatted_amount} USDT</code>\n"
                payment_msg += f"3️⃣ 网络选择：<b>TRON (TRC20)</b>\n\n"
                payment_msg += f"<code>{order['payment_address']}</code>\n\n"
                payment_msg += f"📝 备注：{order['memo']}\n\n"
                payment_msg += f"💡 提示：\n"
                payment_msg += f"• 订单号：{order['order_id']}\n"
                payment_msg += f"• 有效期：30分钟\n"
                payment_msg += f"• 支付后请点击「我已支付」按钮\n"
                payment_msg += f"• 系统会自动检测并激活订阅"
                
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ 我已支付", callback_data="confirm_payment")],
                    [InlineKeyboardButton("❌ 取消订单", callback_data="cancel_payment")]
                ])
                
                await query.edit_message_text(payment_msg, parse_mode='HTML', reply_markup=keyboard)
                
            except Exception as e:
                logger.error(f"Error handling plan selection: {e}", exc_info=True)
                await query.edit_message_text(
                    "❌ 处理订单时出错，请稍后重试。",
                    parse_mode='HTML'
                )
            finally:
                break
    except Exception as e:
        logger.error(f"Error in handle_plan_selection: {e}", exc_info=True)
        query = update.callback_query
        try:
            await query.edit_message_text(
                f"❌ <b>处理您的请求时出现错误</b>\n\n"
                f"错误信息：{str(e)}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass


@rate_limit_confirm_payment
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    确认支付并激活订阅（5秒限流）
    使用TronScan API检测真实支付，或测试模式跳过验证
    """
    try:
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        telegram_id = user.id
        username = user.username or str(telegram_id)
        
        # 获取订单信息
        order = context.user_data.get('pending_order')
        plan_id = context.user_data.get('selected_plan_id')
        
        if not order or not plan_id:
            await query.edit_message_text(
                "❌ 订单信息不存在，请重新选择套餐。",
                parse_mode='HTML'
            )
            return
        
        order_id = order['order_id']
        amount = order['amount']
        
        # 检查测试模式
        test_mode = os.getenv('PAYMENT_TEST_MODE', 'false').lower() == 'true'
        
        if test_mode:
            # 测试模式：显示测试提示
            await query.edit_message_text(
                "🧪 <b>测试模式 - 模拟支付</b>\n\n"
                "系统正在模拟支付流程...\n\n"
                "💡 这是本地测试环境，无需真实转账\n"
                "⏱️ 请稍候，模拟处理中...",
                parse_mode='HTML'
            )
            
            # 调用测试模式的支付检测（会自动延迟）
            payment_detected, tx_info = await usdt_service.check_payment_received(
                order_id=order_id,
                expected_amount=amount
            )
        else:
            # 正式模式：显示处理中提示
            await query.edit_message_text(
                " <b>正在验证支付...</b>\n\n"
                "请稍候，系统正在查询链上交易...\n\n"
                "⚠️ 这可能需要10-30秒",
                parse_mode='HTML'
            )
            
            # 调用TronScan API检测支付（最多重试5次，每次间隔5秒）
            payment_detected = False
            tx_info = None
            
            for attempt in range(5):
                try:
                    payment_detected, tx_info = await usdt_service.check_payment_received(
                        order_id=order_id,
                        expected_amount=amount
                    )
                    
                    if payment_detected:
                        break
                    
                    # 等待5秒后重试
                    if attempt < 4:
                        await asyncio.sleep(5)
                        
                except Exception as e:
                    logger.error(f"Payment check attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(5)
        
        if payment_detected and tx_info:
            # 支付成功，激活订阅
            success, message = await usdt_service.activate_subscription(
                telegram_id=telegram_id,
                username=username,
                plan_id=plan_id
            )
            
            if success:
                # 清除订单信息（使用统一的状态管理工具）
                clear_state(context, 'pending_order', 'selected_plan_id')
                
                # 判断当前流程模式（创建或续费）
                flow_mode = context.user_data.get('flow_mode', 'create')
                
                if flow_mode == 'renew':
                    renew_bot_id = context.user_data.get('renew_bot_id')
                    await _sync_renewed_bot_expire(context, telegram_id)
                    from ..handlers.bot_management_handler import render_bot_manage_buttons
                    from ..models import BotCreation, get_db_session
                    from sqlalchemy import select
                    target_bot = None
                    if renew_bot_id:
                        async with get_db_session() as db:
                            target_bot = (await db.execute(
                                select(BotCreation).where(BotCreation.instance_id == renew_bot_id)
                            )).scalar_one_or_none()
                    clear_state(context, 'flow_mode', 'renew_bot_id')
                    success_msg = (
                        "✅ <b>续费成功啦！🎉</b>\n\n"
                        "你的专属记账Bot服务时长已更新\n"
                        f"{message}\n\n"
                        "可以继续安心使用所有功能咯~"
                    )
                    reply_markup = render_bot_manage_buttons(
                        renew_bot_id or getattr(target_bot, "instance_id", ""),
                        telegram_id,
                        "renewed_success",
                    )
                    await query.edit_message_text(success_msg, reply_markup=reply_markup, parse_mode='HTML')
                else:
                    # 创建流程 - 超小白版 Token 引导
                    success_msg = (
                        "✅ <b>恭喜你支付成功啦！🎉</b>\n\n"
                        "现在只需要跟着步骤做，就能拥有你的专属小机器人～\n\n"
                        "1️⃣ 在 Telegram 搜索打开 @BotFather\n"
                        "2️⃣ 发送指令 /newbot，按提示设置机器人名字和用户名\n"
                        "3️⃣ 创建完成后，@BotFather 会发给你一串 Token 密钥\n"
                        "4️⃣ 把这一整串密钥完整复制，直接发给我就可以咯\n\n"
                        "我收到后会自动帮你配置好一切～\n"
                        "头像、名字、记账功能全部一键搞定，不用你动手哦！"
                    )
                    
                    # 设置用户状态为等待 Bot Token，直接让用户可以发送
                    context.user_data['creating_bot'] = True
                    context.user_data['bot_step'] = 'waiting_token'
                    clear_state(context, 'flow_mode', 'renew_bot_id')
                    
                    await query.edit_message_text(success_msg, parse_mode='HTML')
            else:
                # 支付成功但激活失败
                await query.edit_message_text(
                    f"💸 <b>支付失败哦，请重新选择套餐试试～</b>\n\n"
                    f"{message}\n\n"
                    f"如有疑问，请联系客服：@xiaomingjz",
                    parse_mode='HTML'
                )
        else:
            # 未检测到支付
            await query.edit_message_text(
                "💸 <b>支付失败哦，请重新选择套餐试试～</b>\n\n"
                "系统在30秒内未检测到您的转账。\n\n"
                "可能的原因：\n"
                "• 还未完成转账\n"
                "• 转账金额不正确\n"
                "• 网络延迟，请稍后重试\n\n"
                "如果已完成转账，请等待几分钟后再次点击「我已支付」。\n\n"
                "如有疑问，请联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
    
    except Exception as e:
        logger.error(f"Error in confirm_payment: {e}", exc_info=True)
        query = update.callback_query
        try:
            await query.edit_message_text(
                f"❌ <b>处理支付时出错</b>\n\n"
                f"错误信息：{str(e)}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass


async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消支付"""
    query = update.callback_query
    await query.answer()
    
    # 清除订单信息（使用统一的状态管理工具）
    clear_state(context, 'pending_order', 'selected_plan_id')
    
    await query.edit_message_text(
        "❌ 已取消订单。",
        parse_mode='HTML'
    )


@rate_limit_payment
async def start_create_bot_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始创建机器人流程（5秒限流）- 超小白版引导"""
    try:
        query = update.callback_query
        await query.answer()
        
        # 超小白版 Token 引导
        msg = (
            "✅ <b>恭喜你支付成功啦！🎉</b>\n\n"
            "现在只需要跟着步骤做，就能拥有你的专属小机器人～\n\n"
            "1️⃣ 在 Telegram 搜索打开 @BotFather\n"
            "2️⃣ 发送指令 /newbot，按提示设置机器人名字和用户名\n"
            "3️⃣ 创建完成后，@BotFather 会发给你一串 Token 密钥\n"
            "4️⃣ 把这一整串密钥完整复制，直接发给我就可以咯\n\n"
            "我收到后会自动帮你配置好一切～\n"
            "头像、名字、记账功能全部一键搞定，不用你动手哦！\n\n"
            "💡 <b>Token 格式示例：</b>\n"
            "<code>123456789:ABCdefGhIjklMnoPqRsTuVwXyZ</code>"
        )
        
        # 设置用户状态为等待Bot Token
        context.user_data['creating_bot'] = True
        context.user_data['bot_step'] = 'waiting_token'
        
        await query.edit_message_text(msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in start_create_bot_flow: {e}", exc_info=True)
        query = update.callback_query
        try:
            await query.edit_message_text(
                f"❌ <b>处理您的请求时出现错误</b>\n\n"
                f"错误信息：{str(e)}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass


async def show_create_bot_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        
        msg = "🤖 <b>创建机器人</b>\n\n"
        msg += f"您好 {user.first_name or user.username}！\n\n"
        msg += "请提供您的机器人信息：\n\n"
        msg += "1️⃣ 首先，请发送您的 <b>Bot Token</b>\n"
        msg += "   （从 @BotFather 获取）\n\n"
        msg += "发送格式：\n"
        msg += "<code>123456789:ABCdefGhIjklMnoPqRsTuVwXyZ</code>\n\n"
        msg += "💡 提示：如果还没有创建Bot，请先联系 @BotFather 创建。"
        
        # 设置用户状态为等待Bot Token
        context.user_data['creating_bot'] = True
        context.user_data['bot_step'] = 'waiting_token'
        
        await update.message.reply_text(msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in show_create_bot_flow: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ <b>处理您的请求时出现错误</b>\n\n"
                f"错误信息：{str(e)}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass


async def handle_bot_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理Bot Token输入
    验证Token并获取机器人信息
    """
    try:
        user = update.effective_user
        incoming_text = update.message.text if update.message else ""
        logger.info(
            "[DEBUG] handle_bot_token_input CALLED! message_text=%s",
            _mask_token_for_log(incoming_text),
        )
        
        # ✅ 关键修复：检查是否处于provision流程（手动开通套餐）
        # 如果是，则不拦截消息，让 admin_manual_provision.handle_token_input 处理
        provision_state = context.user_data.get('provision_state')
        if provision_state:
            logger.debug(f"[SAAS_TOKEN_INPUT] User in provision state: {provision_state}, skipping saas_purchase handler")
            return  # 不拦截，让专用的 handler 处理

        if not context.user_data.get('rebinding_bot_token'):
            try:
                from sqlalchemy import select
                from ..models import BotCreation, get_db_session

                async with get_db_session() as db:
                    result = await db.execute(
                        select(BotCreation).where(
                            BotCreation.rebind_status == 'waiting',
                            BotCreation.rebind_user_id == user.id
                        ).order_by(BotCreation.rebind_started_at.desc())
                    )
                    pending_rebind = result.scalar_one_or_none()

                if pending_rebind:
                    logger.info(f"[SAAS_TOKEN_INPUT] Resuming pending rebind flow for user {user.id}, bot_id={pending_rebind.instance_id}")
                    context.user_data['rebinding_bot_token'] = True
                    context.user_data['rebind_bot_instance_id'] = pending_rebind.instance_id
            except Exception as e:
                logger.warning(f"[SAAS_TOKEN_INPUT] Failed to resume pending rebind state: {e}")

        if context.user_data.get('rebinding_bot_token'):
            await _handle_rebind_bot_token_input(update, context)
            return
        
        # 检查用户状态 - 只有在等待Bot Token时才处理
        creating_bot = context.user_data.get('creating_bot')
        bot_step = context.user_data.get('bot_step')
        
        logger.info(
            "handle_bot_token_input called: creating_bot=%s, bot_step=%s, text=%s",
            creating_bot,
            bot_step,
            _mask_token_for_log(incoming_text),
        )
        
        text = update.message.text.strip()

        if not creating_bot or bot_step != 'waiting_token':
            logger.debug(
                "Ignoring token input outside waiting_token state: creating_bot=%s, bot_step=%s",
                creating_bot,
                bot_step,
            )
            return
        
        token = update.message.text.strip()
        
        logger.info(f"Processing token for user {user.id} ({user.username})")
        
        # 验证Token格式
        if not _is_valid_bot_token(token):
            await update.message.reply_text(
                "❌ <b>这个Token不对哦，请检查后重新发我～</b>\n\n"
                "Token 应该是类似这样的格式：\n"
                "<code>123456789:ABCdefGhIjklMnoPqRsTuVwXyZ</code>\n\n"
                "💡 提示：从 @BotFather 那里完整复制过来哦～",
                parse_mode='HTML'
            )
            return
        
        # 验证Token并获取机器人信息
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=10
            )
            result = response.json()
            
            if not result.get('ok'):
                await update.message.reply_text(
                    "❌ <b>这个Token不对哦，请检查后重新发我～</b>\n\n"
                    "可能是：\n"
                    "• Token 复制不完整\n"
                    "• 这个 Token 已经被撤销了\n"
                    "• @BotFather 那边还没创建好\n\n"
                    "请重新去 @BotFather 获取一个新的 Token 发给我～",
                    parse_mode='HTML'
                )
                return
            
            bot_info = result['result']
            bot_username = bot_info['username']
            bot_name = bot_info['first_name']
            
            # 保存信息到用户数据
            context.user_data['bot_token'] = token
            context.user_data['bot_username'] = bot_username
            context.user_data['bot_name'] = bot_name
            context.user_data['bot_step'] = 'confirming'
            
            # 显示确认信息
            confirm_msg = f"✅ <b>机器人信息已获取！</b>\n\n"
            confirm_msg += f"🤖 机器人名称：{bot_name}\n"
            confirm_msg += f"👤 用户名：@{bot_username}\n\n"
            confirm_msg += "请确认是否使用此机器人？\n\n"
            confirm_msg += "回复 <b>确认</b> 继续创建\n"
            confirm_msg += "回复 <b>取消</b> 重新输入"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ 确认创建", callback_data="confirm_create_bot")],
                [InlineKeyboardButton("❌ 取消", callback_data="cancel_create_bot")]
            ])
            
            await update.message.reply_text(confirm_msg, parse_mode='HTML', reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"Error validating bot token: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ <b>验证Bot Token时出错</b>\n\n"
            f"错误信息：{str(e)}\n\n"
            "请稍后重试，或联系客服：@xiaomingjz",
            parse_mode='HTML'
        )


async def _handle_rebind_bot_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理已有机器人 Token 失效后的重绑输入。"""
    user = update.effective_user
    token = update.message.text.strip()
    instance_id = context.user_data.get('rebind_bot_instance_id')

    if not instance_id:
        clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')
        await update.message.reply_text("❌ 重绑状态已失效，请重新点击「创建续费」。", parse_mode='HTML')
        return

    if not _is_valid_bot_token(token):
        await update.message.reply_text(
            "❌ <b>这个Token格式不对哦，请重新发送完整 Token～</b>\n\n"
            "<code>123456789:ABCdefGhIjklMnoPqRsTuVwXyZ</code>",
            parse_mode='HTML'
        )
        return

    ok, bot_info_result, error = await _validate_bot_token(token)
    if not ok or not bot_info_result:
        await update.message.reply_text(
            "❌ <b>这个Token仍然不可用</b>\n\n"
            f"{_escape_html(error or 'Token 校验失败')}\n\n"
            "请从 @BotFather 重新生成后再发送一次。",
            parse_mode='HTML'
        )
        return

    from sqlalchemy import select
    from ..models import BotCreation, get_db_session

    async with get_db_session() as db:
        result = await db.execute(select(BotCreation).where(BotCreation.instance_id == instance_id))
        bot_record = result.scalar_one_or_none()

        if not bot_record or (bot_record.telegram_id != user.id and bot_record.super_admin_id != user.id):
            clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')
            await update.message.reply_text("❌ 未找到你的机器人记录，请重新点击「创建续费」。", parse_mode='HTML')
            return

        new_username = bot_info_result.get('username')
        new_name = bot_info_result.get('first_name') or new_username

        if bot_record.bot_username and new_username and bot_record.bot_username.lower() != new_username.lower():
            await update.message.reply_text(
                "❌ <b>Token 不属于原来的机器人</b>\n\n"
                f"当前记录：@{_escape_html(bot_record.bot_username)}\n"
                f"你发送的是：@{_escape_html(new_username)}\n\n"
                "请发送原机器人在 @BotFather 重新生成的 Token。",
                parse_mode='HTML'
            )
            return

        original_expire_time = bot_record.expire_time
        parent_bot_id = bot_record.parent_bot_id

    from ..services.token_check_service import token_check_service

    msg = await update.message.reply_text(
        "正在重绑 Token 并恢复机器人...\n\n系统会保留原有到期时间、群组权限和数据。",
        parse_mode='HTML'
    )

    success, message = await token_check_service.process_rebind_token(instance_id, user.id, token)
    clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')

    if success:
        await msg.edit_text(
            "✅ <b>Token 重绑成功！</b>\n\n"
            f"🤖 机器人名称：{_escape_html(new_name)}\n"
            f"👤 用户名：@{_escape_html(new_username)}\n"
            f"⏰ 原到期时间已保留：{_format_datetime(original_expire_time)}\n\n"
            "数据、套餐和群组权限都已保留。",
            parse_mode='HTML'
        )
    else:
        if message == '重绑状态已结束':
            await msg.edit_text("已退出 Token 重绑状态。", parse_mode='HTML')
        else:
            await msg.edit_text(
                f"❌ <b>Token 重绑失败</b>\n\n{_escape_html(message)}",
                parse_mode='HTML'
            )
    return

    msg = await update.message.reply_text(
        "🔄 <b>正在重绑 Token 并恢复机器人...</b>\n\n请稍候，系统会保留原有到期时间和数据。",
        parse_mode='HTML'
    )

    success, message, updated_bot = await saas_auto_service.create_bot_instance(
        telegram_id=user.id,
        username=user.username or str(user.id),
        bot_token=token,
        bot_username=new_username,
        bot_name=new_name,
        parent_bot_id=parent_bot_id,
        expire_time=original_expire_time,
    )

    if success:
        async with get_db_session() as db:
            result = await db.execute(select(BotCreation).where(BotCreation.instance_id == instance_id))
            bot_record = result.scalar_one_or_none()
            if bot_record:
                bot_record.expire_time = original_expire_time
                bot_record.lifecycle_status = "ACTIVE"
                bot_record.status = "running"
                bot_record.status_message = "Token rebound"

        clear_state(context, 'rebinding_bot_token', 'rebind_bot_instance_id')
        await msg.edit_text(
            "✅ <b>Token 重绑成功！</b>\n\n"
            f"🤖 机器人名称：{_escape_html(new_name)}\n"
            f"👤 用户名：@{_escape_html(new_username)}\n"
            f"📅 原到期时间已恢复：{_format_datetime(original_expire_time)}\n\n"
            "你的数据、套餐和群组配置都已保留，无需重新购买哦～",
            parse_mode='HTML'
        )
    else:
        await msg.edit_text(
            f"❌ <b>Token 重绑失败</b>\n\n{_escape_html(message)}",
            parse_mode='HTML'
        )


async def handle_confirm_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理用户回复的确认文本（"确认"或"取消"）
    """
    try:
        # 检查用户状态
        if not context.user_data.get('creating_bot') or context.user_data.get('bot_step') != 'confirming':
            return
        
        user = update.effective_user
        text = update.message.text.strip().lower()
        
        if text in ['确认', 'confirm']:
            # 用户确认，执行创建
            await _execute_bot_creation(update, context)
        elif text in ['取消', 'cancel']:
            # 用户取消
            clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')
            await update.message.reply_text(
                "❌ 已取消创建机器人。",
                parse_mode='HTML'
            )
        else:
            # 无效输入
            await update.message.reply_text(
                "请输入 <b>确认</b> 继续创建，或 <b>取消</b> 重新开始。",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error in handle_confirm_text: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ <b>处理您的请求时出现错误</b>\n\n"
                f"错误信息：{str(e)}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass
        # 清除状态
        clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')


async def _execute_bot_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    执行机器人创建流程
    """
    try:
        user = update.effective_user
        telegram_id = user.id
        
        # 获取保存的信息
        bot_token = context.user_data.get('bot_token')
        bot_username = context.user_data.get('bot_username')
        bot_name = context.user_data.get('bot_name')
        
        if not all([bot_token, bot_username, bot_name]):
            await update.message.reply_text(
                "❌ 创建信息不完整，请重新开始。",
                parse_mode='HTML'
            )
            clear_state(context, 'creating_bot', 'bot_step')
            return
        
        # 显示创建中提示
        msg = await update.message.reply_text(
            "🔄 <b>正在创建机器人...</b>\n\n"
            "请稍候，这可能需要几分钟时间...",
            parse_mode='HTML'
        )
        
        # 创建机器人实例
        success, message, bot_creation = await saas_auto_service.create_bot_instance(
            telegram_id=telegram_id,
            username=user.username or str(telegram_id),
            bot_token=bot_token,
            bot_username=bot_username,
            bot_name=bot_name
        )
        
        if success:
            # 清除用户数据（使用统一的状态管理工具）
            clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')

            from ..handlers.bot_management_handler import _build_bot_manage_scene_text, render_bot_manage_buttons
            success_msg = _build_bot_manage_scene_text(bot_creation, "created_success")
            reply_markup = render_bot_manage_buttons(bot_creation.instance_id, telegram_id, "created_success")
            await msg.edit_text(success_msg, reply_markup=reply_markup, parse_mode='HTML')
            
        else:
            # 创建失败
            # ✅ 关键修复:清理错误消息中的 HTML 标签
            safe_message = _escape_html(message)
            await msg.edit_text(
                f"❌ <b>创建失败</b>\n\n{safe_message}",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error in _execute_bot_creation: {e}", exc_info=True)
        try:
            # ✅ 关键修复:清理错误消息中的 HTML 标签
            safe_error = _escape_html(str(e))
            await update.message.reply_text(
                f"❌ <b>处理您的请求时出现错误</b>\n\n"
                f"错误信息：{safe_error}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass
        # 清除状态
        clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')


@rate_limit_create_bot
async def confirm_create_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认创建机器人（10秒限流）"""
    try:
        user = update.effective_user
        telegram_id = user.id
        
        query = update.callback_query
        await query.answer()
        
        # ✅ 关键修复：获取保存的信息并判空
        bot_token = context.user_data.get('bot_token')
        bot_username = context.user_data.get('bot_username')
        bot_name = context.user_data.get('bot_name')
        
        logger.info(f"confirm_create_bot called for user {telegram_id}")
        logger.info(f"bot_token_set={bool(bot_token)}, bot_username={bot_username}, bot_name={bot_name}")
        
        if not all([bot_token, bot_username, bot_name]):
            logger.warning(f"Missing bot data: token={bool(bot_token)}, username={bool(bot_username)}, name={bool(bot_name)}")
            await query.edit_message_text(
                "❌ 创建信息不完整，请重新开始。",
                parse_mode='HTML'
            )
            clear_state(context, 'creating_bot', 'bot_step')
            return
        
        # 显示创建中提示
        await query.edit_message_text(
            " <b>正在创建机器人...</b>\n\n"
            "请稍候，这可能需要几分钟时间...",
            parse_mode='HTML'
        )
        
        # ✅ 关键修复：防御性解包，确保 create_bot_instance 返回有效的三元组
        # 🆕 从 context.user_data 中获取 parent_bot_id（支持无限裂变）
        parent_bot_id = context.user_data.get('parent_bot_id')
        
        result = await saas_auto_service.create_bot_instance(
            telegram_id=telegram_id,
            username=user.username or str(telegram_id),
            bot_token=bot_token,
            bot_username=bot_username,
            bot_name=bot_name,
            parent_bot_id=parent_bot_id  # 🆕 支持无限裂变
        )
        
        # 验证返回值
        if not result or len(result) != 3:
            logger.error(f"create_bot_instance returned invalid result: {result}")
            await query.edit_message_text(
                "❌ 创建机器人时发生未知错误，请稍后重试。",
                parse_mode='HTML'
            )
            clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')
            return
        
        success, message, bot_creation = result
        
        if success:
            # ✅ 关键修复：区分是创建成功还是 Token 更新成功
            is_token_update = "Token 已更新" in message or "token updated" in message.lower()
            
            if is_token_update:
                success_msg = f"✅ <b>Token 更新成功！</b>\n\n"
                success_msg += f"🤖 机器人名称：{bot_name}\n"
                success_msg += f"👤 用户名：@{bot_username}\n\n"
                success_msg += f"{message}\n\n"
                success_msg += "💡 提示：\n"
                success_msg += "• 机器人已使用新 Token 重新连接\n"
                success_msg += "• 如果之前无法使用，现在应该可以正常使用了"
            else:
                from ..handlers.bot_management_handler import _build_bot_manage_scene_text
                success_msg = _build_bot_manage_scene_text(bot_creation, "created_success")
            
            # 清除用户数据（使用统一的状态管理工具）
            clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')
            from ..handlers.bot_management_handler import render_bot_manage_buttons
            await query.edit_message_text(
                success_msg,
                parse_mode='HTML',
                reply_markup=render_bot_manage_buttons(bot_creation.instance_id, telegram_id, "created_success")
            )
            
        else:
            # 创建失败 - ✅ 关键修复：清理错误消息中的 HTML 标签
            # 防止 SQLAlchemy 对象（如 <BotCreation at 0x...>）被 Telegram 解析为 HTML 标签
            safe_message = str(message).replace('<', '&lt;').replace('>', '&gt;')
            await query.edit_message_text(
                f" <b>创建失败</b>\n\n{safe_message}",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error in confirm_create_bot: {e}", exc_info=True)
        query = update.callback_query
        try:
            # ✅ 关键修复:清理错误消息中的 HTML 标签
            safe_error = _escape_html(str(e))
            await query.edit_message_text(
                f"❌ <b>处理您的请求时出现错误</b>\n\n"
                f"错误信息：{safe_error}\n\n"
                f"请稍后重试，或联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
        except Exception:
            pass
        # 清除状态
        clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')


async def cancel_create_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消创建机器人"""
    query = update.callback_query
    await query.answer()
    
    # 清除用户数据（使用统一的状态管理工具）
    clear_state(context, 'creating_bot', 'bot_step', 'bot_token', 'bot_username', 'bot_name')
    
    await query.edit_message_text(
        "❌ 已取消创建机器人。",
        parse_mode='HTML'
    )


def _is_valid_bot_token(token: str) -> bool:
    """验证Bot Token格式"""
    # Bot Token格式: 数字:字母数字字符串
    import re
    pattern = r'^\d+:[A-Za-z0-9_-]+$'
    return bool(re.match(pattern, token))

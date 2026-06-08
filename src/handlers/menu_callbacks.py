"""
菜单按钮回调处理器
处理底部键盘菜单的点击事件

⚠️ DEPRECATED - 旧架构实现
此文件已迁移到新架构,请参考:
- ui_schema_registry.py (UI路由)
- runtime_router.py (命令处理)
- capability_system.py (权限控制)

新功能请使用新架构开发
预计删除时间: 2026-Q3
"""
import asyncio
import html
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ContextTypes
from sqlalchemy import and_, select, func

from ..utils.role_checker import get_user_role, UserRole
from ..utils.permission_checker import PermissionChecker
from ..utils.tenant_scope import scoped_query
from ..utils.bot_id_middleware import get_current_bot_id
from ..models import get_db_session

logger = logging.getLogger(__name__)


def _settings_markup(context: ContextTypes.DEFAULT_TYPE, keyboard):
    from ..utils.settings_guard import create_settings_session, wrap_settings_markup

    return wrap_settings_markup(InlineKeyboardMarkup(keyboard), create_settings_session(context))



async def handle_usage_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理使用说明 - 显示帮助中心首页（分类索引）"""
    from src.services.help_builder import build_help_page
    from src.keyboards.help_keyboard import help_keyboard
    
    # 显示 index 页面：只显示提示信息，不显示分类详情
    await update.message.reply_text(
        build_help_page("index"),
        parse_mode="HTML",
        reply_markup=help_keyboard("index")
    )


async def handle_contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理联系客服"""
    bot_name = context.bot.first_name if context.bot else "记账机器人"
    await update.message.reply_text(
        f"💼 <b>联系客服</b>\n\n{bot_name}售后技术\n\n"
        "Telegram: @xiaomingjz\n\n如有任何问题，请随时联系！",
        parse_mode='HTML'
    )


async def handle_apply_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理申请试用 - 普通用户点击申请试用按钮"""
    bot_name = context.bot.first_name if context.bot else "记账机器人"
    # 试用配置（硬编码，不依赖配置文件）
    trial_days = 8  # 试用8天
    trial_max_groups = 5  # 最多管理5个群组

    text = (
        f"📝 <b>申请试用</b>\n\n"
        f"感谢您对{bot_name}的关注！\n\n"
        f"💡 <b>试用说明：</b>\n"
        f"• 试用期为 {trial_days} 天（一次性）\n"
        f"• 最多管理 {trial_max_groups} 个群组\n"
        f"• 每位用户仅限申请一次\n"
        f"• 到期后无法续期，请购买正式套餐\n\n"
        f"👇 请选择操作："
    )

    keyboard = [
        [InlineKeyboardButton("✅ 立即申请试用", callback_data="trial:apply")],
        [InlineKeyboardButton("💰 直接购买套餐", callback_data="billing:self_renew")],
        [InlineKeyboardButton("💬 联系客服咨询", callback_data="contact:support")],
    ]

    reply_markup = _settings_markup(context, keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')


async def handle_self_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理自助续费 - 检查是否为当前 Bot 的超级管理员
    
    流程：
    1. 检查当前用户是否为该 Bot 的超级管理员
    2. 如果不是超管，提示并引导创建自己的机器人
    3. 如果是超管，显示当前 Bot 信息和续费套餐
    """
    from ..services.saas_auto_service import saas_auto_service
    from ..utils.role_checker import UserRole
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select
    from ..models import Subscription, BotCreation, get_db_session
    from datetime import datetime
    
    user = update.effective_user
    telegram_id = user.id
    bot_id = get_current_bot_id(context)
    
    # 步骤1：检查当前用户是否为该 Bot 的超级管理员或 Bot 拥有者
    user_role = await get_user_role(telegram_id, bot_id=bot_id)
    
    if user_role not in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER]:
        # 步骤2：不是超级管理员或 Bot 拥有者，提示并引导
        await update.message.reply_text(
            "❌ <b>你不是当前机器人的拥有者</b>\n\n"
            "只有创建机器人时的超级管理员或 Bot 拥有者才可续费。\n\n"
            "💡 您可以创建自己的机器人：\n"
            "点击底部菜单「🤖 创建机器人」按钮，即可拥有专属的记账机器人！",
            parse_mode='HTML'
        )
        return
    
    # 步骤3：是超级管理员，查询当前 Bot 信息
    async with get_db_session() as db:
        # 查询当前 Bot 的创建记录
        query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        result = await db.execute(query)
        bot_record = result.scalar_one_or_none()
        
        if not bot_record:
            await update.message.reply_text(
                "❌ 未找到当前机器人的信息，请联系客服：@xiaomingjz",
                parse_mode='HTML'
            )
            return
        
        # 查询用户的订阅信息
        query = select(Subscription).where(Subscription.telegram_id == telegram_id)
        result = await db.execute(query)
        subscription = result.scalar_one_or_none()
        
        # 构建当前 Bot 信息
        bot_info_msg = f"🤖 <b>当前机器人信息</b>\n\n"
        bot_info_msg += f"名称：{bot_record.bot_name or '未设置'}\n"
        bot_info_msg += f"用户名：@{bot_record.bot_username}\n\n"
        
        if subscription and subscription.status == 'active':
            # 计算剩余天数
            now = datetime.utcnow()
            expire_date = subscription.expire_date
            remaining_days = (expire_date - now).days
            
            if remaining_days < 0:
                remaining_days = 0
                status_text = "已过期"
            else:
                status_text = f"剩余 {remaining_days} 天"
            
            # 套餐名称映射
            package_names = {
                30: "月付",
                90: "季付",
                365: "年付",
                3650: "永久"
            }
            current_package = package_names.get(subscription.plan_id, "未知")
            
            bot_info_msg += f"当前套餐：{current_package}\n"
            bot_info_msg += f"到期时间：{expire_date.strftime('%Y-%m-%d %H:%M')}\n"
            bot_info_msg += f"状态：{status_text}\n\n"
        else:
            bot_info_msg += f"当前套餐：未订阅\n"
            bot_info_msg += f"状态：需要续费\n\n"
        
        bot_info_msg += f"请选择续费套餐："
        
        await update.message.reply_text(bot_info_msg, parse_mode='HTML')
        
        # 步骤4：显示续费套餐
        from .saas_purchase import show_pricing_plans
        await show_pricing_plans(update, context)


async def _detect_user_identity(user_id: int, bot_id: str, db) -> dict:
    """
    动态识别用户身份（7种身份）
    返回 dict: {
        'identity': str,  # 身份类型
        'role_name': str, # 角色名称（用于显示）
        'role_tip': str,  # 角色提示（仅管理员显示）
        'bot_creation': BotCreation | None,
        'subscription': Subscription | None,
        'is_expired': bool,
        'days_left': int,
        'expire_time': str,
        'package_type': str,
        'service_status': str,
        'bot_username': str,
        'bot_name': str,
    }
    """
    from ..models.saas_auto import BotCreation, Subscription
    from datetime import timezone
    
    result = {
        'identity': 'normal_user',
        'role_name': '正常使用者',
        'role_tip': '',
        'bot_creation': None,
        'subscription': None,
        'is_expired': False,
        'days_left': 0,
        'expire_time': 'N/A',
        'package_type': '暂无套餐',
        'service_status': '无订阅',
        'bot_username': 'N/A',
        'bot_name': 'N/A',
    }
    
    try:
        # 1. 检查超级管理员（固定ID）
        if user_id == 7862093562:
            result['identity'] = 'super_admin'
            result['role_name'] = '超级管理员'
            # 超级管理员查询自己的机器人
            bot_creation = None
            if bot_id:
                current_query = select(BotCreation).where(BotCreation.instance_id == bot_id)
                current_result = await db.execute(current_query)
                bot_creation = current_result.scalars().first()
                if bot_creation and getattr(bot_creation, 'super_admin_id', None) != user_id:
                    bot_creation = None
            if not bot_creation:
                bot_query = (
                    select(BotCreation)
                    .where(BotCreation.super_admin_id == user_id)
                    .order_by(BotCreation.created_at.desc())
                )
                bot_result = await db.execute(bot_query)
                bot_creation = bot_result.scalars().first()
            if bot_creation:
                result['bot_creation'] = bot_creation
                result['bot_username'] = f"@{bot_creation.bot_username}" if bot_creation.bot_username else 'N/A'
                result['bot_name'] = bot_creation.bot_name or 'N/A'
                if bot_creation.expire_time:
                    expire_date = bot_creation.expire_time
                    if getattr(expire_date, 'tzinfo', None):
                        expire_date = expire_date.astimezone(timezone.utc).replace(tzinfo=None)
                    result['days_left'] = (expire_date - datetime.utcnow()).days
                    result['expire_time'] = expire_date.strftime('%Y-%m-%d %H:%M')
                    result['package_type'] = '全功能版'
                    result['service_status'] = '✅ 正常'
                    result['is_expired'] = result['days_left'] <= 0
                else:
                    result['expire_time'] = '永久有效'
                    result['package_type'] = '全功能版'
                    result['service_status'] = '✅ 正常'
            return result
        
        # 2. 获取当前 Bot 信息
        bot_query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        bot_result = await db.execute(bot_query)
        current_bot = bot_result.scalar_one_or_none()
        
        if not current_bot:
            from ..services.account_status_service import account_status_service
            owned_bots = await account_status_service.get_owned_bots(user_id, db)
            if owned_bots:
                current_bot = owned_bots[0]
            else:
                return result
        
        result['bot_username'] = f"@{current_bot.bot_username}" if current_bot.bot_username else 'N/A'
        result['bot_name'] = current_bot.bot_name or 'N/A'
        
        # 3. 检查是否是 Bot 创建者
        from ..services.account_status_service import account_status_service
        owned_bots = await account_status_service.get_owned_bots(user_id, db)
        owned_bot = next((bot for bot in owned_bots if bot.instance_id == bot_id), None)
        if not owned_bot and owned_bots:
            owned_bot = owned_bots[0]
        if owned_bot:
            current_bot = owned_bot
            result['bot_creation'] = current_bot
            result['bot_username'] = f"@{current_bot.bot_username}" if current_bot.bot_username else 'N/A'
            result['bot_name'] = current_bot.bot_name or 'N/A'

        if owned_bot or current_bot.telegram_id == user_id:
            result['identity'] = 'bot_creator'
            result['role_name'] = 'Bot创建者'
            # 查询订阅信息
            sub_query = select(Subscription).where(
                and_(
                    Subscription.telegram_id == user_id,
                    Subscription.status == "active"
                )
            )
            sub_result = await db.execute(sub_query)
            subscription = sub_result.scalar_one_or_none()
            if subscription:
                result['subscription'] = subscription
                expire_date = subscription.expire_date
                if expire_date:
                    if getattr(expire_date, 'tzinfo', None):
                        expire_date = expire_date.astimezone(timezone.utc).replace(tzinfo=None)
                    result['days_left'] = (expire_date - datetime.utcnow()).days
                    result['expire_time'] = expire_date.strftime('%Y-%m-%d %H:%M')
                    result['package_type'] = subscription.package_name or '标准套餐'
                    result['is_expired'] = result['days_left'] <= 0
                    if result['is_expired']:
                        result['service_status'] = '❌ 已到期'
                    else:
                        result['service_status'] = '✅ 正常'
            else:
                # 无订阅但有 Bot，可能是手动创建的
                result['identity'] = 'manual_bot_user'
                result['role_name'] = '手动开通Bot用户'
                if current_bot.expire_time:
                    expire_date = current_bot.expire_time
                    if getattr(expire_date, 'tzinfo', None):
                        expire_date = expire_date.astimezone(timezone.utc).replace(tzinfo=None)
                    result['days_left'] = (expire_date - datetime.utcnow()).days
                    result['expire_time'] = expire_date.strftime('%Y-%m-%d %H:%M')
                    result['package_type'] = '独立Bot'
                    result['is_expired'] = result['days_left'] <= 0
                    if result['is_expired']:
                        result['service_status'] = '❌ 已到期'
                    else:
                        result['service_status'] = '✅ 正常'
            return result
        
        # 4. 检查是否是 Bot 添加的管理员
        from ..models.admin import Admin
        admin_query = select(Admin).where(
            and_(
                Admin.user_id == user_id,
                Admin.bot_id == bot_id,
                Admin.is_active.is_(True)
            )
        )
        admin_result = await db.execute(admin_query)
        admin = admin_result.scalar_one_or_none()
        
        if admin:
            result['identity'] = 'bot_admin'
            result['role_name'] = '机器人管理员'
            result['role_tip'] = '仅拥有管理权限，无机器人所有权'
            if current_bot.expire_time:
                expire_date = current_bot.expire_time
                if getattr(expire_date, 'tzinfo', None):
                    expire_date = expire_date.astimezone(timezone.utc).replace(tzinfo=None)
                result['days_left'] = (expire_date - datetime.utcnow()).days
                result['expire_time'] = expire_date.strftime('%Y-%m-%d %H:%M')
                result['is_expired'] = result['days_left'] <= 0
                if result['is_expired']:
                    result['service_status'] = '❌ 已到期'
                else:
                    result['service_status'] = '✅ 正常'
            return result
        
        # 5. 检查全局操作员
        from ..models.admin import GroupOperator
        global_op_query = select(GroupOperator).where(
            and_(
                GroupOperator.user_id == user_id,
                GroupOperator.is_global.is_(True)
            )
        )
        global_op_result = await db.execute(global_op_query)
        if global_op_result.scalar_one_or_none():
            result['identity'] = 'global_operator'
            result['role_name'] = '全局操作员'
            return result
        
        # 6. 检查群组记账员
        group_op_query = select(GroupOperator).where(GroupOperator.user_id == user_id)
        group_op_result = await db.execute(group_op_query)
        if group_op_result.scalars().first():
            result['identity'] = 'group_operator'
            result['role_name'] = '群组记账员'
            return result
        
        # 7. 默认普通用户
        result['identity'] = 'normal_user'
        result['role_name'] = '普通用户'
        
    except Exception as e:
        logger.warning(f"[_detect_user_identity] Error: {e}", exc_info=True)
    
    return result


async def _get_bot_status(bot_id: str, db) -> dict:
    """
    获取机器人运行状态和Token状态
    返回 dict: {
        'run_status': str,   # ✅正常运行 / ❌异常
        'token_status': str, # ✅有效 / ❌失效
    }
    """
    from ..models.saas_auto import BotCreation
    
    result = {
        'run_status': '❌ 异常',
        'token_status': '❌ 失效',
    }
    
    try:
        bot_query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        bot_result = await db.execute(bot_query)
        bot_creation = bot_result.scalar_one_or_none()
        
        if bot_creation:
            # 运行状态判断
            if bot_creation.status == 'running' and bot_creation.last_heartbeat:
                from datetime import timedelta
                if datetime.utcnow() - bot_creation.last_heartbeat < timedelta(minutes=5):
                    result['run_status'] = '✅ 正常运行'
            
            # Token状态判断
            if bot_creation.token_status == 'normal':
                result['token_status'] = '✅ 有效'
            elif bot_creation.token_status == 'invalid':
                result['token_status'] = '❌ 失效'
            else:
                result['token_status'] = '🔄 检测中'
                
    except Exception as e:
        logger.warning(f"[_get_bot_status] Error: {e}", exc_info=True)
    
    return result


def _get_personal_center_buttons(identity: str, bot_id: str) -> InlineKeyboardMarkup:
    """
    根据用户身份返回个人中心按钮
    仅以下身份显示机器人管理按钮：
    - super_admin
    - bot_creator
    - manual_bot_user
    """
    keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data="back_to_main_menu")]]

    return InlineKeyboardMarkup(keyboard)


async def handle_personal_center(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    个人中心 - 动态识别用户身份，显示对应文案
    7种身份：超级管理员、Bot创建者、手动开通Bot用户、Bot添加的管理员、全局操作员、群组记账员、普通用户、已到期用户
    """
    query = update.callback_query
    message = update.message

    try:
        if not update.effective_user:
            if query:
                await query.answer("无法获取用户信息", show_alert=True)
            return

        if query:
            await query.answer()

        user = update.effective_user
        user_id = user.id
        username = html.escape(user.username or "未设置")

        bot_id = get_current_bot_id(context)

        async with get_db_session() as db:
            # 1. 动态识别用户身份
            identity_info = await _detect_user_identity(user_id, bot_id, db)
            
            # 2. 获取机器人状态
            bot_status = await _get_bot_status(bot_id, db)
            
            # 提取信息
            identity = identity_info['identity']
            role_name = identity_info['role_name']
            role_tip = identity_info['role_tip']
            is_expired = identity_info['is_expired']
            days_left = identity_info['days_left']
            expire_time = identity_info['expire_time']
            package_type = identity_info['package_type']
            service_status = identity_info['service_status']
            bot_username = identity_info['bot_username']
            bot_name = identity_info['bot_name']
            run_status = bot_status['run_status']
            token_status = bot_status['token_status']
            
            # 根据身份生成不同文案
            text = ""
            
            # 【1】超级管理员
            if identity == 'super_admin':
                text = (
                    f"👤 个人中心 - {role_name}\n"
                    f"🆔 用户ID：{user_id}\n"
                    f"👤 用户名：@{username}\n"
                    f"💎 权限：{role_name}\n"
                    f"🤖 所属机器人：{bot_username}\n"
                    f"📅 到期时间：{expire_time}\n"
                    f"📦 当前版本：{package_type}\n\n"
                    f"🤖 机器人状态\n"
                    f"运行状态：{run_status}\n"
                    f"Token状态：{token_status}"
                )
            
            # 【2】Bot创建者
            elif identity == 'bot_creator':
                text = (
                    f"👤 个人中心 - {role_name}\n"
                    f"🆔 用户ID：{user_id}\n"
                    f"👤 用户名：@{username}\n"
                    f"📦 当前套餐：{package_type}\n"
                    f"⏳ 剩余时长：{days_left} 天\n"
                    f"📅 到期时间：{expire_time}\n"
                    f"🤖 所属机器人：{bot_username}\n\n"
                    f"🤖 机器人状态\n"
                    f"运行状态：{run_status}\n"
                    f"Token状态：{token_status}"
                )
            
            # 【3】手动开通Bot用户
            elif identity == 'manual_bot_user':
                text = (
                    f"👤 个人中心\n"
                    f"🆔 用户ID：{user_id}\n"
                    f"👤 用户名：@{username}\n"
                    f"📦 当前套餐：{package_type}\n"
                    f"⏳ 剩余时长：{days_left} 天\n"
                    f"📅 到期时间：{expire_time}\n"
                    f"🤖 所属机器人：{bot_username}\n\n"
                    f"🤖 机器人状态\n"
                    f"运行状态：{run_status}\n"
                    f"Token状态：{token_status}"
                )
            
            # 【4】Bot添加的管理员
            elif identity == 'bot_admin':
                text = (
                    f"👤 个人中心 - {role_name}\n"
                    f"🆔 用户ID：{user_id}\n"
                    f"👤 用户名：@{username}\n"
                    f"🤖 当前使用：{bot_username}\n"
                    f"⚠️ {role_tip}\n\n"
                    f"🤖 机器人状态\n"
                    f"运行状态：{run_status}\n"
                    f"Token状态：{token_status}\n\n"
                    f"🥳 拥有专属机器人有多香：\n"
                    f"✅ 名字、头像随便改，打造你的专属风格\n"
                    f"✅ 数据完全独立，隐私稳稳不泄露\n"
                    f"✅ 可设管理员，分工超灵活\n"
                    f"✅ 多群组、定时、播报功能全都有\n"
                    f"✅ 独立运行超稳定，不受别人影响\n"
                    f"✅ 功能全开，想怎么用就怎么用\n\n"
                    f"✨ 拥有一台只属于你的记账Bot，个性拉满又安心～\n\n"
                    f"🆕 创建我的专属机器人"
                )
            
            # 【5】全局操作员 / 群组记账员 / 普通用户
            elif identity in ['global_operator', 'group_operator', 'normal_user']:
                text = (
                    f"👤 个人中心\n"
                    f"🆔 用户ID：{user_id}\n"
                    f"👤 用户名：@{username}\n"
                    f"📌 当前身份：{role_name}\n\n"
                    f"🥳 拥有专属机器人有多香：\n"
                    f"✅ 名字、头像随便改，打造你的专属风格\n"
                    f"✅ 数据完全独立，隐私稳稳不泄露\n"
                    f"✅ 可设管理员，分工超灵活\n"
                    f"✅ 多群组、定时、播报功能全都有\n"
                    f"✅ 独立运行超稳定，不受别人影响\n"
                    f"✅ 功能全开，想怎么用就怎么用\n\n"
                    f"✨ 拥有一台只属于你的记账Bot，个性拉满又安心～\n\n"
                    f"🆕 创建我的专属机器人"
                )
            
            # 【6】已到期用户
            elif is_expired:
                text = (
                    f"👤 个人中心\n"
                    f"🆔 用户ID：{user_id}\n"
                    f"👤 用户名：@{username}\n"
                    f"📦 服务状态：{service_status}\n\n"
                    f"⏸️ 你的机器人服务已到期\n"
                    f"部分功能已受限，为了数据安全记得及时续费哦～\n\n"
                    f"💥 续费后立刻恢复全部快乐：\n"
                    f"✅ 记账功能正常用，流水不耽误\n"
                    f"✅ 机器人满血复活，稳定在线\n"
                    f"✅ 历史数据完整保留，不丢一条\n"
                    f"✅ 高级功能全部解锁，爽感拉满\n"
                    f"✅ 群组配置一键恢复，不用重设"
                )
            
            # 生成按钮
            keyboard = _get_personal_center_buttons(identity, bot_id)
            
            # 到期用户特殊按钮
            if is_expired and identity in ['bot_creator', 'manual_bot_user', 'super_admin']:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 立即续费", callback_data="renew_subscription")],
                    [InlineKeyboardButton("⬅️ 返回", callback_data="back_to_main_menu")]
                ])
            
            # 管理员/普通用户特殊按钮（引导创建机器人）
            if identity in ['bot_admin', 'global_operator', 'group_operator', 'normal_user']:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆕 创建我的专属机器人", callback_data="create_bot_start")],
                    [InlineKeyboardButton("⬅️ 返回", callback_data="back_to_main_menu")]
                ])

        if query:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
        elif message:
            await message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)
        else:
            logger.warning("[PERSONAL_CENTER] No query or message available to respond with")

    except Exception as e:
        logger.error(f"[PERSONAL_CENTER] Error: {e}", exc_info=True)
        import traceback
        logger.error(f"[PERSONAL_CENTER] Traceback: {traceback.format_exc()}")
        try:
            if query:
                await query.answer("加载个人中心失败，请稍后重试", show_alert=True)
            elif message:
                await message.reply_text("加载个人中心失败，请稍后重试")
        except Exception as e2:
            logger.error(f"[PERSONAL_CENTER] Fallback error handler also failed: {e2}")


async def handle_runtime_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    运行统计 - 只显示数据统计和运行状态，不包含个人信息
    不同身份显示不同数据：
    - 超级管理员：全局视角
    - Bot创建者：子Bot视角
    - 普通管理员：运营视角
    - 普通用户：个人使用视角
    """
    if not update.effective_user:
        return
    
    query = update.callback_query
    message = update.message
    
    if query:
        await query.answer()
    
    user = update.effective_user
    user_id = user.id
    
    # 获取当前 bot_id
    bot_id = get_current_bot_id(context)
    
    # 获取用户角色
    user_role = await get_user_role(user_id, bot_id=bot_id)
    
    # 导入模型
    from ..models.group import Group
    from ..models.saas_auto import BotCreation, Admin
    from ..models.database import get_db_session
    from sqlalchemy import select, and_, func
    
    async with get_db_session() as db:
        # 根据身份获取不同数据
        if user_role == UserRole.SUPER_ADMIN:
            # 超级管理员：全局视角
            # 获取全局群组数（所有Bot的）
            group_query = select(func.count(Group.id))
            group_result = await db.execute(group_query)
            group_num = group_result.scalar() or 0
            
            # 获取全局用户数（私聊用户）
            user_query = select(func.count(BotCreation.id))
            user_result = await db.execute(user_query)
            user_num = user_result.scalar() or 0
            
            # 获取平台管理员数
            admin_query = select(func.count(Admin.id))
            admin_result = await db.execute(admin_query)
            admin_num = admin_result.scalar() or 0
            
            # 获取今日账单数（全局）
            today = datetime.utcnow().date()
            from ..models.transaction import Transaction
            bill_query = select(func.count(Transaction.id)).where(
                Transaction.created_at >= datetime.combine(today, datetime.min.time())
            )
            bill_result = await db.execute(bill_query)
            bill_num = bill_result.scalar() or 0
            
            # 构建超级管理员文案
            text = (
                "📊 系统运行小统计\n"
                f"👥 授权群组：{group_num} 个  💬 私聊客户：{user_num} 人\n"
                f"🛠 平台管理员：{admin_num} 人  📝 今日账单：{bill_num} 笔\n"
                "🤖 机器人乖乖运行中✨\n"
                "💎 身份：超级管理员"
            )
        
        elif user_role == UserRole.BOT_OWNER:
            # Bot创建者：子Bot视角
            # 获取当前Bot的授权群组数
            group_query = select(func.count(Group.id)).where(
                Group.bot_id == bot_id,
                Group.is_active.is_(True)
            )
            group_result = await db.execute(group_query)
            group_num = group_result.scalar() or 0
            
            # 获取当前Bot的私聊用户数（这里简化处理，实际可能需要其他表）
            user_num = group_num  # 简化处理
            
            # 获取当前Bot的管理员数
            admin_query = select(func.count(Admin.id)).where(
                Admin.bot_id == bot_id
            )
            admin_result = await db.execute(admin_query)
            admin_num = admin_result.scalar() or 0
            
            # 获取今日记账数（当前Bot）
            today = datetime.utcnow().date()
            from ..models.transaction import Transaction
            bill_query = select(func.count(Transaction.id)).where(
                and_(
                    Transaction.bot_id == bot_id,
                    Transaction.created_at >= datetime.combine(today, datetime.min.time())
                )
            )
            bill_result = await db.execute(bill_query)
            bill_num = bill_result.scalar() or 0
            
            # 构建Bot创建者文案
            text = (
                "📊 机器人运行小统计\n"
                f"👥 我的授权群组：{group_num} 个  💬 我的私聊用户：{user_num} 人\n"
                f"🛠 我的管理员：{admin_num} 人  📝 今日记账：{bill_num} 笔\n"
                "🤖 你的机器人在线状态超棒🥳\n"
                "💡 数据只属于这个 Bot 哦～"
            )
        
        elif user_role == UserRole.ADMIN:
            # 普通管理员：运营视角
            # 获取管理员负责的群组数（这里简化处理）
            group_query = select(func.count(Group.id)).where(
                Group.bot_id == bot_id,
                Group.is_active.is_(True)
            )
            group_result = await db.execute(group_query)
            group_num = group_result.scalar() or 0
            
            # 获取今日互动用户数（简化处理）
            user_num = group_num  # 简化处理
            
            # 获取今日账单数（当前Bot）
            today = datetime.utcnow().date()
            from ..models.transaction import Transaction
            bill_query = select(func.count(Transaction.id)).where(
                and_(
                    Transaction.bot_id == bot_id,
                    Transaction.created_at >= datetime.combine(today, datetime.min.time())
                )
            )
            bill_result = await db.execute(bill_query)
            bill_num = bill_result.scalar() or 0
            
            # 构建普通管理员文案
            text = (
                "📊 运营小数据\n"
                f"👥 我管的群组：{group_num} 个  💬 今日互动用户：{user_num} 人\n"
                f"📝 今日账单：{bill_num} 笔\n"
                "🤖 服务状态：正常可用☁️"
            )
        
        else:
            # 普通用户：个人使用视角
            # 获取今日账单数（当前用户）
            today = datetime.utcnow().date()
            from ..models.transaction import Transaction
            bill_query = select(func.count(Transaction.id)).where(
                and_(
                    Transaction.bot_id == bot_id,
                    Transaction.user_id == user_id,
                    Transaction.created_at >= datetime.combine(today, datetime.min.time())
                )
            )
            bill_result = await db.execute(bill_query)
            bill_num = bill_result.scalar() or 0
            
            # 构建普通用户文案
            text = (
                "📊 我的使用小记录\n"
                f"📝 今日记账：{bill_num} 笔\n"
                "🤖 机器人在为你好好服务哦🌸"
            )
        
        if query:
            await query.edit_message_text(text, parse_mode='HTML')
        elif message:
            await message.reply_text(text, parse_mode='HTML')


# ==================== 广播功能状态管理 ====================

def _clear_broadcast_state(context: ContextTypes.DEFAULT_TYPE):
    """
    清空所有广播相关状态（最关键，必须做）
    
    核心状态（5个KEY）：
    - broadcast_target: all / groups
    - broadcast_selected_group_ids: 选中的分组 ID 列表 [id1, id2, ...]
    - broadcast_selected_group_names: 选中的分组名称列表 ["name1", "name2", ...]
    - waiting_broadcast_msg: 是否等待输入
    - broadcast_msg: 临时消息内容
    """
    context.user_data.pop("broadcast_target", None)
    context.user_data.pop("broadcast_group_id", None)
    context.user_data.pop("broadcast_group_name", None)
    context.user_data.pop("broadcast_selected_group_ids", None)
    context.user_data.pop("broadcast_selected_group_names", None)
    context.user_data.pop("waiting_broadcast_msg", None)
    context.user_data.pop("broadcast_msg", None)
    # 兼容旧字段
    context.user_data.pop("selected_groups", None)
    context.user_data.pop("waiting_for_broadcast_content", None)
    context.user_data.pop("broadcast_type", None)
    context.user_data.pop("broadcast_selected_broadcast_groups", None)
    context.user_data.pop("broadcast_wait_start_time", None)
    context.user_data.pop("last_broadcast_input_time", None)


async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群发广播 - 使用新的 GroupTag 系统
    
    流程：选择目标 → 锁定分组 → 等待消息 → 确认消息 → 选择模式 → 发送 → 清空状态
    """
    from ..utils.role_checker import get_user_role, UserRole
    from config import config
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from ..models.database import get_db_session
    from ..models.group import Group, GroupTag
    from ..utils.bot_id_middleware import get_current_bot_id
    from sqlalchemy import select, and_, func
    
    user = update.effective_user
    query = update.callback_query
    bot_id = get_current_bot_id(context)
    user_role = await get_user_role(user.id, bot_id=bot_id)
    if user_role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.BOT_OWNER]:
        from ..utils.settings_guard import LOCKED_FEATURE_MESSAGE
        if query and query.message:
            await query.answer(LOCKED_FEATURE_MESSAGE, show_alert=True)
            return
        logger.warning(f"[BROADCAST PERMISSION] 权限拒绝 - User ID: {user.id}, Role: {user_role}")
        
        await update.message.reply_text(
            "❌ 无权限访问'群发广播'\n\n"
            "这是管理功能，仅机器人管理员可以使用。\n\n"
            "💡 你可以：\n"
            "• 联系机器人管理员获取权限\n"
            "• 创建属于自己的机器人\n\n"
            "📩 联系客服：@xiaomingjz"
        )
        return
    
    # ✅ 核心优化：清空所有广播相关状态，确保每次都是全新开始
    _clear_broadcast_state(context)
    
    # 🆕 默认选中“默认”分组（如果有）
    from ..services.group_tag_service import DEFAULT_BROADCAST_GROUP_TAG
    async with get_db_session() as db:
        default_tag_query = select(GroupTag).where(
            and_(
                GroupTag.bot_id == bot_id,
                GroupTag.tag_name == DEFAULT_BROADCAST_GROUP_TAG,
                GroupTag.is_active.is_(True)
            )
        )
        default_tag_result = await db.execute(default_tag_query)
        default_tag = default_tag_result.scalar_one_or_none()
        
        if default_tag:
            # 设置默认选中“默认”分组
            context.user_data["broadcast_target"] = "groups"
            context.user_data["broadcast_selected_group_ids"] = [default_tag.id]
            context.user_data["broadcast_selected_group_names"] = [DEFAULT_BROADCAST_GROUP_TAG]
            logger.info(f"[BROADCAST] 默认选中分组: {DEFAULT_BROADCAST_GROUP_TAG} (id={default_tag.id})")
    
    # ✅ Broadcast Preflight Health Check - 自动健康检查（静默执行）
    # 不再显示"正在检测群组状态"提示，直接执行健康检查
    
    try:
        bot_id = get_current_bot_id(context)
        async with get_db_session() as db:
            all_groups = await db.execute(
                select(Group).where(
                    (Group.is_active.is_(True)) & 
                    ((Group.bot_id == bot_id) | (Group.bot_id == None))
                )
            )
            all_groups = all_groups.scalars().all()
        
        valid_groups = []
        kicked_groups = []      # 已被踢出
        left_groups = []        # 主动离开
        no_permission_groups = []  # 无发言权限
        other_error_groups = []    # 其他错误
        
        for group in all_groups:
            try:
                bot_member = await context.bot.get_chat_member(group.group_id, context.bot.id)
                status = bot_member.status
                
                if status in ["kicked"]:
                    kicked_groups.append(group)
                elif status in ["left"]:
                    left_groups.append(group)
                elif status in ["restricted"]:
                    # 检查是否有发言权限
                    if not bot_member.can_send_messages:
                        no_permission_groups.append(group)
                    else:
                        valid_groups.append(group)
                else:
                    valid_groups.append(group)
                    
            except Exception as e:
                error_str = str(e).lower()
                if "chat not found" in error_str or "bot was kicked" in error_str:
                    kicked_groups.append(group)
                elif "bot is not a member" in error_str:
                    left_groups.append(group)
                else:
                    other_error_groups.append(group)
                    logger.warning(f"⚠️ 群组 {group.group_id} 检测异常: {e}")
        
        # 更新数据库中的无效群组状态
        invalid_groups = kicked_groups + left_groups + no_permission_groups + other_error_groups
        if invalid_groups:
            async with get_db_session() as db:
                for group in invalid_groups:
                    group.is_active = False
                    # ✅ 清除分组配置（重新进群后会重置为默认分组）
                    group.broadcast_group_id = None
                    # ✅ 同时清除 group_tag，确保分组统计准确
                    group.group_tag = None
                    db.add(group)
                await db.commit()
            logger.info(f"✅ 已自动清理 {len(invalid_groups)} 个异常群组，并清除分组配置和 group_tag")
        
        # 保存检测结果到 user_data
        context.user_data["health_check_result"] = {
            "valid": len(valid_groups),
            "kicked": len(kicked_groups),
            "left": len(left_groups),
            "no_permission": len(no_permission_groups),
            "other_error": len(other_error_groups),
            "total_checked": len(all_groups)
        }
        
        logger.info(f"📊 健康检查结果：有效 {len(valid_groups)} | 被踢 {len(kicked_groups)} | 离开 {len(left_groups)} | 无权限 {len(no_permission_groups)} | 其他 {len(other_error_groups)}")
        
    except Exception as e:
        logger.error(f"⚠️ 群组健康检查失败: {e}", exc_info=True)
        error_text = f"❌ 群发广播健康检查失败：{e}"
        if query and query.message:
            await query.edit_message_text(error_text)
        elif update.message:
            await update.message.reply_text(error_text)
        return
    
    # 获取所有 GroupTag 分组（新架构）
    try:
        async with get_db_session() as db:
            # 查询当前 Bot 的所有启用分组
            tags_query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.is_active.is_(True)
                )
            ).order_by(GroupTag.tag_name)
            tags_result = await db.execute(tags_query)
            broadcast_groups = tags_result.scalars().all()
            
            # 统计每个分组下的群组数量
            groups_by_broadcast = {}
            for tag in broadcast_groups:
                count_query = select(func.count(Group.id)).where(
                    and_(
                        Group.bot_id == bot_id,
                        Group.group_tag == tag.tag_name,
                        Group.is_active.is_(True)
                    )
                )
                count_result = await db.execute(count_query)
                count = count_result.scalar() or 0
                groups_by_broadcast[tag.tag_name] = count
                logger.info(f"[Broadcast] 分组 '{tag.tag_name}' 下有 {count} 个群组")
    except Exception as e:
        logger.error(f"[BROADCAST ERROR] 获取分组失败: {e}")
        broadcast_groups = []
        groups_by_broadcast = {}
    
    # 构建菜单按钮
    keyboard = []
    
    # 获取当前选中的目标（如果有）
    current_target = context.user_data.get("broadcast_target")
    selected_group_ids = context.user_data.get("broadcast_selected_group_ids", [])  # ✅ 使用新字段
    
    # 第一行：📢 所有群组广播
    if current_target == "all":
        keyboard.append([InlineKeyboardButton("✅ 所有群组广播", callback_data="broadcast_target_all")])
    else:
        keyboard.append([InlineKeyboardButton("📢 所有群组广播", callback_data="broadcast_target_all")])
    
    # 第二行起：显示所有分组（一行2个）
    if broadcast_groups:
        row = []
        for tag in broadcast_groups:
            # 获取该分组的群组数量
            group_count = groups_by_broadcast.get(tag.tag_name, 0)
            
            # ✅ 如果当前选中的是这个分组，显示✅（支持多选）
            if tag.id in selected_group_ids:
                row.append(InlineKeyboardButton(f"✅ {tag.tag_name} ({group_count})", callback_data=f"broadcast_target_group_{tag.id}"))
            else:
                row.append(InlineKeyboardButton(f"👥 {tag.tag_name} ({group_count})", callback_data=f"broadcast_target_group_{tag.id}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
    
    # 最后一行：根据是否已选择目标，动态显示按钮
    if current_target or selected_group_ids:  # 已选择目标（all 或 groups）
        keyboard.append([
            InlineKeyboardButton("✍️ 开始输入广播内容", callback_data="broadcast_start_input"),
            InlineKeyboardButton("← 返回", callback_data="broadcast_cancel")
        ])
    else:  # 未选择目标，显示禁用状态
        keyboard.append([
            InlineKeyboardButton(" 请选择分组", callback_data="no_action"),
            InlineKeyboardButton("← 返回", callback_data="broadcast_cancel")
        ])
    
    reply_markup = _settings_markup(context, keyboard)
    
    # 构建健康检查报告
    health_result = context.user_data.get("health_check_result", {})
    valid_count = health_result.get("valid", 0)
    kicked_count = health_result.get("kicked", 0)
    left_count = health_result.get("left", 0)
    no_perm_count = health_result.get("no_permission", 0)
    other_count = health_result.get("other_error", 0)
    total_invalid = kicked_count + left_count + no_perm_count + other_count
    
    message = "📢 <b>群发广播</b>\n\n"
    message += "🔍 <b>健康检查完成</b>\n\n"
    message += f"✅ 有效群组：<b>{valid_count}</b>\n"
    if kicked_count > 0:
        message += f"❌ 已被踢出：<b>{kicked_count}</b>\n"
    if left_count > 0:
        message += f"🚪 已离开：<b>{left_count}</b>\n"
    if no_perm_count > 0:
        message += f"🚫 无发言权限：<b>{no_perm_count}</b>\n"
    if other_count > 0:
        message += f"⚠️ 其他异常：<b>{other_count}</b>\n"
    
    if total_invalid > 0:
        message += f"\n💡 已自动清理 <b>{total_invalid}</b> 个异常群组\n"
    
    message += "\n请选择广播目标：\n"
    message += "•  所有群组广播 - 向所有授权群组发送\n"
    if broadcast_groups:
        message += f"• 👥 分组广播 - 从 {len(broadcast_groups)} 个分组中选择\n"
    else:
        message += "• 👥 暂无可用分组\n"
    
    # ✅ 发送消息和按钮
    if query and query.message:
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理功能设置 - 显示内联按钮菜单（一行一个，点击时检查权限）
    
    使用新的 callback_data 格式：module:action
    所有入口统一可见，点击时再进行权限识别
    """
    
    try:
        user = update.effective_user
        if not user:
            logger.warning("[handle_settings] No effective user found")
            return
        
        from ..utils.bot_id_middleware import get_current_bot_id
        bot_id = get_current_bot_id(context)
        from ..utils.settings_guard import create_settings_session, get_settings_identity, wrap_settings_markup
        user_role, role_display, _, _ = await get_settings_identity(int(user.id), bot_id)
        
        # 获取机器人用户名
        bot_username = context.bot.username if context.bot else "Unknown"
        
        settings_text = (
            f"@{bot_username}\n\n"
            f"👤 当前身份：{role_display}\n"
            "✨ 功能菜单已解锁，点击按钮开始配置吧~\n"
            "💡 点击下方按钮，开启功能设置~"
        )
        keyboard = [
            [InlineKeyboardButton("🧵 话题模式", callback_data="topic:show"),
             InlineKeyboardButton("👥 我的群组", callback_data="mygroups:show")],
            [InlineKeyboardButton("📢 用户广播", callback_data="broadcast_users:show"),
             InlineKeyboardButton("📣 群发广播", callback_data="show_broadcast")],
            [InlineKeyboardButton("📂 分组管理", callback_data="v1:group:manage"),
             InlineKeyboardButton("🤖 进群消息", callback_data="botjoin:show")],
            [InlineKeyboardButton("✂️ 日切设置", callback_data="daycut:show"),
             InlineKeyboardButton("📊 记账条数", callback_data="display:show")],
            [InlineKeyboardButton("👤 昵称显示", callback_data="showname:show"),
             InlineKeyboardButton("👋 入群欢迎", callback_data="welcome:show")],
            [InlineKeyboardButton("💬 关键词", callback_data="keyword:show"),
             InlineKeyboardButton("👥 加管理员", callback_data="admin:show")],
            [InlineKeyboardButton("🔐 授权群组", callback_data="auth:group:show"),
             InlineKeyboardButton("🍀 更名检测", callback_data="rename:show")],
            [InlineKeyboardButton("⏰ 定时消息", callback_data="timed:show"),
             InlineKeyboardButton("📢 广告位", callback_data="ad:show")],
            [InlineKeyboardButton("⬅️ 返回", callback_data="menu:close")],
        ]
        
        reply_markup = wrap_settings_markup(InlineKeyboardMarkup(keyboard), create_settings_session(context))
        
        # 支持从 message 或 callback_query 调用
        if update.message:
            await update.message.reply_text(settings_text, reply_markup=reply_markup, parse_mode='HTML')
        elif update.callback_query:
            await update.callback_query.edit_message_text(settings_text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            logger.warning("[handle_settings] Neither message nor callback_query available")
    
    except Exception as e:
        logger.error(f"[handle_settings] Error: {e}", exc_info=True)
        # 异常兜底：返回友好提示
        error_text = "⚠️ 加载功能设置菜单时出现错误，请稍后重试或联系客服。"
        try:
            if update.callback_query:
                await update.callback_query.answer(error_text, show_alert=True)
            elif update.message:
                await update.message.reply_text(error_text)
        except Exception as inner_e:
            logger.error(f"[handle_settings] Failed to send error message: {inner_e}")


async def _auto_delete_message(message, delay: int = 3):
    """
    自动删除消息
    
    Args:
        message: Telegram Message 对象
        delay: 延迟秒数（默认3秒）
    """
    import asyncio
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        # 忽略删除失败（可能已经被用户删除）
        pass


async def _countdown_and_delete(message, total_seconds: int = 3):
    """
    带倒计时的自动删除消息
    
    Args:
        message: Telegram Message 对象
        total_seconds: 总秒数（默认3秒）
    """
    import asyncio
    try:
        # 每秒更新一次倒计时提示
        for remaining in range(total_seconds, 0, -1):
            await asyncio.sleep(1)
            try:
                await message.edit_text(f"❌ 已取消此次广播（{remaining}秒后自动销毁）")
            except Exception:
                # 如果编辑失败（可能已被删除），直接退出
                break
        
        # 最后删除消息
        await asyncio.sleep(0.5)  # 稍微等待一下
        await message.delete()
    except Exception as e:
        # 忽略删除失败（可能已经被用户删除）
        pass


async def handle_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群发广播回调 - 企业级标准实现
    
    支持的回调：
    - show_broadcast: 重新打开广播菜单
    - broadcast_target_all: 选择所有群组
    - broadcast_target_group_{id}: 选择特定分组
    - broadcast_start_input: 开始输入广播内容
    - broadcast_cancel: 取消广播
    - broadcast_forward: 转发模式发送
    - broadcast_send: 发送模式发送
    """
    query = update.callback_query
    await query.answer()
    data = context.user_data.get("_settings_unwrapped_callback_data") or query.data
    
    # ==================== 群发广播相关回调（企业级标准） ====================
    
    if data == "show_broadcast":
        await handle_broadcast(update, context)
        return
    
    elif data == "broadcast_target_all":
        # 【第二步-A】选择「所有群组广播」- 直接使用健康检查结果
        from ..utils.bot_id_middleware import get_current_bot_id
        from ..models.database import get_db_session
        from ..models.group import Group
        from sqlalchemy import select
            
        bot_id = get_current_bot_id(context)
        
        # ✅ 获取健康检查结果
        health_result = context.user_data.get("health_check_result", {})
        valid_count = health_result.get("valid", 0)
        total_invalid = health_result.get("kicked", 0) + health_result.get("left", 0) + health_result.get("no_permission", 0) + health_result.get("other_error", 0)
        
        if valid_count == 0:
            await query.edit_message_text("❌ 没有可用的有效群组，请先添加群组")
            return
        
        # 设置状态
        context.user_data["broadcast_target"] = "all"
        context.user_data["broadcast_selected_group_ids"] = []  # 清空选中的分组列表
        context.user_data["broadcast_selected_group_names"] = []
        context.user_data["valid_groups_count"] = valid_count
        context.user_data["filtered_groups_count"] = total_invalid
            
        # 重新获取所有分组，生成带✅标记的新按钮布局
        try:
            async with get_db_session() as db:
                from ..models.group import GroupTag
                from sqlalchemy import and_
                tags_query = select(GroupTag).where(
                    and_(
                        GroupTag.bot_id == bot_id,
                        GroupTag.is_active.is_(True)
                    )
                ).order_by(GroupTag.tag_name)
                tags_result = await db.execute(tags_query)
                broadcast_groups = tags_result.scalars().all()
        except Exception as e:
            logger.error(f"[BROADCAST ERROR] 获取分组失败: {e}")
            broadcast_groups = []
                    
        # 重新构建按钮布局
        keyboard = []
                    
        # 第一行：所有群组广播（已选中）+ 显示有效数量
        keyboard.append([InlineKeyboardButton(f"✅ 所有群组广播 ({valid_count})", callback_data="broadcast_target_all")])
                    
        # ✅ 选择"所有群组广播"后，不显示分组列表（旧架构残留代码，已移除）
        # 第二行起：显示所有分组的代码已被删除
            
        # 最后一行：✍️ 开始输入 + ← 返回
        keyboard.append([
            InlineKeyboardButton("✍️ 开始输入广播内容", callback_data="broadcast_start_input"),
            InlineKeyboardButton("← 返回", callback_data="broadcast_cancel")
        ])
            
        reply_markup = _settings_markup(context, keyboard)
            
        # 构建提示消息
        msg_text = f"✅ 已选择【所有授权群组】\n"
        msg_text += f"\n📊 检测结果："
        msg_text += f"\n• 有效群组：{valid_count} 个"
        if total_invalid > 0:
            msg_text += f"\n• 已过滤：{total_invalid} 个失效群组（已自动更新状态）"
        msg_text += f"\n\n请点击「️ 开始输入广播内容」继续"
            
        await query.edit_message_text(msg_text, reply_markup=reply_markup)
    
    elif data.startswith("broadcast_target_group_"):
        # 【第二步-B】选择某个分组（支持多选）
        group_id = int(data.replace("broadcast_target_group_", ""))
        
        from ..utils.bot_id_middleware import get_current_bot_id
        from ..models.database import get_db_session
        from ..models.group import GroupTag
        from sqlalchemy import select, and_
        
        bot_id = get_current_bot_id(context)
        
        async with get_db_session() as db:
            tag_query = select(GroupTag).where(
                and_(
                    GroupTag.id == group_id,
                    GroupTag.bot_id == bot_id,
                    GroupTag.is_active.is_(True)
                )
            )
            tag_result = await db.execute(tag_query)
            group_tag = tag_result.scalar_one_or_none()
        
        if not group_tag:
            await query.answer("❌ 分组不存在", show_alert=True)
            return
        
        # ✅ 获取当前选中的分组列表
        selected_ids = context.user_data.get("broadcast_selected_group_ids", [])
        selected_names = context.user_data.get("broadcast_selected_group_names", [])
        
        # ✅ 切换选中状态（如果已选中则取消，否则添加）
        if group_id in selected_ids:
            # 取消选中
            index = selected_ids.index(group_id)
            selected_ids.pop(index)
            selected_names.pop(index)
            action_text = "已取消选择"
        else:
            # 添加选中
            selected_ids.append(group_id)
            selected_names.append(group_tag.tag_name)
            action_text = "已选择"
        
        # ✅ 更新状态
        context.user_data["broadcast_target"] = "groups" if selected_ids else "none"
        context.user_data["broadcast_selected_group_ids"] = selected_ids
        context.user_data["broadcast_selected_group_names"] = selected_names
        
        # ✅ 重新获取所有分组，生成带✅标记的新按钮布局
        try:
            async with get_db_session() as db:
                tags_query = select(GroupTag).where(
                    and_(
                        GroupTag.bot_id == bot_id,
                        GroupTag.is_active.is_(True)
                    )
                ).order_by(GroupTag.tag_name)
                tags_result = await db.execute(tags_query)
                broadcast_groups = tags_result.scalars().all()
                
                # ✅ 统计每个分组的群组数量（在同一个 db 会话中）
                from ..models.group import Group
                groups_by_tag = {}
                for tag in broadcast_groups:
                    count_query = select(func.count(Group.id)).where(
                        and_(
                            Group.bot_id == bot_id,
                            Group.group_tag == tag.tag_name,
                            Group.is_active.is_(True)
                        )
                    )
                    count_result = await db.execute(count_query)
                    count = count_result.scalar() or 0
                    groups_by_tag[tag.tag_name] = count
        except Exception as e:
            logger.error(f"[BROADCAST ERROR] 获取分组失败: {e}")
            broadcast_groups = []
            groups_by_tag = {}
        
        # 重新构建按钮布局
        keyboard = []
        
        # 第一行：所有群组广播（未选中）
        keyboard.append([InlineKeyboardButton("📢 所有群组广播", callback_data="broadcast_target_all")])
        
        # 第二行起：显示所有分组（一行2个）
        if broadcast_groups:
            row = []
            for tag in broadcast_groups:
                # 获取该分组的群组数量
                group_count = groups_by_tag.get(tag.tag_name, 0)
                # 如果当前选中的是这个分组，显示✅
                if tag.id in selected_ids:
                    row.append(InlineKeyboardButton(f"✅ {tag.tag_name} ({group_count})", callback_data=f"broadcast_target_group_{tag.id}"))
                else:
                    row.append(InlineKeyboardButton(f"👥 {tag.tag_name} ({group_count})", callback_data=f"broadcast_target_group_{tag.id}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
        
        # 最后一行：根据是否已选择分组，动态显示按钮
        if selected_ids:  # 已选择至少一个分组
            keyboard.append([
                InlineKeyboardButton("✍️ 开始输入广播内容", callback_data="broadcast_start_input"),
                InlineKeyboardButton("← 返回", callback_data="broadcast_cancel")
            ])
        else:  # 未选择任何分组，显示禁用状态
            keyboard.append([
                InlineKeyboardButton(" 请选择广播目标", callback_data="no_action"),
                InlineKeyboardButton("← 返回", callback_data="broadcast_cancel")
            ])
        
        reply_markup = _settings_markup(context, keyboard)
        
        # 构建提示消息
        if selected_ids:
            msg_text = f"{action_text}【{group_tag.tag_name}】\n\n"
            msg_text += f"📋 已选择 {len(selected_ids)} 个分组：\n"
            for name in selected_names:
                msg_text += f"• {name}\n"
            msg_text += f"\n请点击「✅ 开始输入广播内容」继续"
        else:
            msg_text = f"{action_text}【{group_tag.tag_name}】\n\n"
            msg_text += f"⚠️ 当前未选择任何分组\n\n"
            msg_text += f"请选择至少一个分组，或点击「📢 所有群组广播」"
        
        await query.edit_message_text(msg_text, reply_markup=reply_markup)
    
    elif data == "broadcast_start_input":
        # 【第三步】点击「✅ 开始输入广播内容」
        broadcast_target = context.user_data.get("broadcast_target")
        
        if not broadcast_target:
            await query.answer("请先选择广播目标！", show_alert=True)
            return
        
        # ✅ 设置等待状态
        context.user_data["waiting_broadcast_msg"] = True
        
        import time
        context.user_data["broadcast_wait_start_time"] = time.time()
        
        logger.info(f"[BROADCAST STEP 3] User {update.effective_user.id} clicked start input, broadcast_target={broadcast_target}")
        
        await query.edit_message_text(
            "📝 <b>请发送广播内容</b>\n\n"
            "您可以发送：\n"
            "• 文字消息\n"
            "• 图片/视频\n"
            "• 转发其他消息\n\n"
            "⏰ 5分钟内未发送将自动取消",
            parse_mode='HTML'
        )
    
    elif data == "broadcast_cancel":
        # 【第七步】取消广播 - 清空所有状态
        await query.answer()
        _clear_broadcast_state(context)
        # ✅ 返回功能设置菜单
        from ..handlers.menu import _show_settings_main
        await _show_settings_main(query, context)
    
    elif data == "broadcast_forward":
        # 【第五步-A】选择转发模式
        await query.answer()
        context.user_data["broadcast_mode"] = "forward"
        await _execute_broadcast(update, context)
    
    elif data == "broadcast_send":
        # 【第五步-B】选择发送模式
        await query.answer()
        context.user_data["broadcast_mode"] = "send"
        await _execute_broadcast(update, context)


async def handle_broadcast_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    【第四步】用户发送广播消息

    触发：私聊文本 / 图片 / 转发
    判断：waiting_broadcast_msg.is_(True) 或 broadcast_users_waiting_input.is_(True)
    保存：broadcast_msg（消息对象）
    展示：确认界面
    """
    if not update.message or not update.effective_user:
        return

    msg = update.message
    user_data = context.user_data

    # 🆕 广播用户功能：检查是否在等待用户广播输入（优先级高于群发广播）
    if user_data.get('broadcast_users_waiting_input'):
        from .menu import _handle_broadcast_users_input
        logger.info(f"[USER BROADCAST] User {update.effective_user.id} is in broadcast_users_waiting_input, delegating")
        result = await _handle_broadcast_users_input(update, context)
        if result:
            return

    # 🆕 编辑状态检查（文本输入，优先级高于群发广播）
    # 所有 edit_state 在此统一处理，防止 block=True 拦截后续 handler
    from ..utils.state_manager import (
        get_edit_state, clear_edit_state, check_edit_state_timeout,
        EDIT_STATE_WELCOME_TEXT, EDIT_STATE_WELCOME_BUTTONS, EDIT_STATE_WELCOME_LIST_ADD,
        EDIT_STATE_ADD_KEYWORD, EDIT_STATE_ADD_KEYWORD_REPLY,
        EDIT_STATE_KEYWORD_EDIT
    )
    state, data = await get_edit_state(context)

    # 超时校验
    if state and await check_edit_state_timeout(context):
        await msg.reply_text("⏰ <b>会话已超时失效</b>\n\n请重新进入配置界面。", parse_mode="HTML")
        return

    if state == EDIT_STATE_WELCOME_BUTTONS and msg.text:
        logger.info(f"[WELCOME EDIT] User {update.effective_user.id} is in welcome buttons edit state")
        from .menu import _handle_welcome_buttons_input
        await _handle_welcome_buttons_input(update, context)
        return

    if state == EDIT_STATE_WELCOME_LIST_ADD:
        logger.info(f"[WELCOME EDIT] User {update.effective_user.id} is in welcome list add state")
        from .menu import _handle_welcome_list_input
        result = await _handle_welcome_list_input(update, context)
        if result:
            return


    # 🆕 广告设置状态检查
    if context.user_data.get('ad_state'):
        logger.info(f"[AD SETTINGS] User {update.effective_user.id} is in ad state, delegating")
        from .ad_handler import handle_ad_text_input
        result = await handle_ad_text_input(update, context)
        if result:
            return

    # 🆕 管理员添加状态检查（用户输入ID或转发消息时触发）
    if context.user_data.get('waiting_admin_add'):
        # 确保有消息内容才处理（防止 callback query 等情况）
        if not msg:
            logger.warning(f"[ADMIN ADD] User {update.effective_user.id} has waiting_admin_add but no message, clearing state")
            context.user_data.pop('waiting_admin_add', None)
            context.user_data.pop('admin_add_user_id', None)
            context.user_data.pop('admin_add_username', None)
            return
        logger.info(f"[ADMIN ADD] User {update.effective_user.id} is in admin add state, delegating")
        from .menu import handle_admin_add_input
        return await handle_admin_add_input(update, context)

    logger.info(f"[BROADCAST MSG INPUT] User {update.effective_user.id} sent message, waiting_broadcast_msg={user_data.get('waiting_broadcast_msg')}")
    
    # ✅ 关键修复：忽略"开通"和"取消"消息，让它们传递给专用 handler
    if msg.text and (msg.text.strip().startswith("开通") or msg.text.strip() == "取消"):
        logger.info(f"[BROADCAST MSG INPUT] Ignoring '{msg.text}' to let provision handler process it")
        return
    
    # ✅ 优化：如果用户处于其他流程（如provision），直接跳过让对应Handler处理
    if user_data.get('provision_state'):
        logger.info(f"[BROADCAST MSG INPUT] User is in provision flow, skipping")
        return
    
    # 检查是否在等待广播消息
    if not user_data.get("waiting_broadcast_msg"):
        logger.info(f"[BROADCAST MSG INPUT] Not waiting for broadcast message, ignoring")
        return
    
    # 超时检测：如果超过 5 分钟未输入，自动取消
    import time
    wait_start_time = user_data.get("broadcast_wait_start_time", 0)
    current_time = time.time()
    if wait_start_time > 0 and (current_time - wait_start_time) > 300:  # 5分钟 = 300秒
        logger.warning(f"[BROADCAST TIMEOUT] User {update.effective_user.id} 超时，自动取消")
        _clear_broadcast_state(context)
        await msg.reply_text("⏰ 操作超时，请重新开始广播流程。")
        return
    
    # 防抖：防止重复点击
    last_input_time = user_data.get("last_broadcast_input_time", 0)
    current_time = time.time()
    if current_time - last_input_time < 1.0:  # 1秒内不允许重复输入
        logger.warning(f"[BROADCAST DEBOUNCE] User {update.effective_user.id} 尝试重复输入")
        return
    user_data["last_broadcast_input_time"] = current_time

    # ✅ 关闭等待状态
    user_data["waiting_broadcast_msg"] = False
    
    # 保存广播内容
    user_data["broadcast_msg"] = msg
    
    # 获取目标群组列表
    broadcast_target = user_data.get("broadcast_target", "all")
    selected_group_ids = user_data.get("broadcast_selected_group_ids", [])
    selected_group_names = user_data.get("broadcast_selected_group_names", [])
    
    # 根据目标类型获取群组列表
    from ..utils.bot_id_middleware import get_current_bot_id
    from ..models.database import get_db_session
    from ..models.group import Group, GroupTag
    from sqlalchemy import select, and_
    
    bot_id = get_current_bot_id(context)
    
    async with get_db_session() as db:
        if broadcast_target == "all":
            # 所有群组
            groups_query = scoped_query(Group, context).where(
                Group.is_active.is_(True)
            ).order_by(Group.group_name)
            target_group_name = "所有授权群组"
            user_data["broadcast_target_group_name"] = target_group_name
        elif broadcast_target == "groups" and selected_group_ids:
            # 指定多个分组 - 使用新的 GroupTag 系统
            # 先获取所有选中的 GroupTag 的 tag_name
            tags_query = select(GroupTag).where(
                and_(
                    GroupTag.id.in_(selected_group_ids),
                    GroupTag.bot_id == bot_id,
                    GroupTag.is_active.is_(True)
                )
            )
            tags_result = await db.execute(tags_query)
            group_tags = tags_result.scalars().all()
            
            if not group_tags:
                await msg.reply_text("❌ 选中的分组不存在或已禁用")
                _clear_broadcast_state(context)
                return
            
            # 获取所有选中的 tag_name
            tag_names = [tag.tag_name for tag in group_tags]
            target_group_name = ", ".join(selected_group_names)
            user_data["broadcast_target_group_name"] = target_group_name
            
            # 使用 tag_name 筛选群组（支持多个分组）
            groups_query = scoped_query(Group, context).where(
                Group.is_active.is_(True),
                Group.group_tag.in_(tag_names)
            ).order_by(Group.group_name)
        else:
            # 没有选择任何目标
            await msg.reply_text("❌ 请先选择广播目标（所有群组或至少一个分组）")
            _clear_broadcast_state(context)
            return
        
        groups_result = await db.execute(groups_query)
        target_groups = groups_result.scalars().all()
    
    if not target_groups:
        await msg.reply_text("❌ 没有可用的目标群组")
        _clear_broadcast_state(context)
        return
    
    # ✅ 新增：提前检测并过滤已不在群中的群组
    valid_groups = []
    invalid_groups = []
    
    progress_msg = await msg.reply_text(f"🔍 正在检测 {len(target_groups)} 个群组的有效性...\n请稍候...")
    
    for group in target_groups:
        try:
            # 检查机器人是否在群内
            bot_member = await context.bot.get_chat_member(group.group_id, context.bot.id)
            # Telegram API 返回的 status 是字符串："creator", "administrator", "member", "restricted", "left", "kicked"
            if bot_member.status in ["kicked", "left"]:
                invalid_groups.append(group)
                logger.info(f"[BROADCAST PRE-CHECK] Bot 不在群组 {group.group_id} ({group.group_name})，status={bot_member.status}，已过滤")
            else:
                valid_groups.append(group)
        except Exception as e:
            # 无法访问的群组也过滤掉
            invalid_groups.append(group)
            error_str = str(e).lower()
            if "chat not found" in error_str or "bot was kicked" in error_str:
                logger.info(f"[BROADCAST PRE-CHECK] 群组 {group.group_id} ({group.group_name}) 已失效，已过滤")
            else:
                logger.warning(f"[BROADCAST PRE-CHECK] 无法访问群组 {group.group_id} ({group.group_name}): {e}")
    
    # 删除进度消息
    try:
        await progress_msg.delete()
    except Exception:
        pass
    
    # 如果没有有效群组，直接返回
    if not valid_groups:
        await msg.reply_text(
            f"❌ 没有可用的目标群组\n\n"
            f"检测到 {len(invalid_groups)} 个群组机器人已不在其中，\n"
            f"请先将 Bot 重新添加到这些群组。"
        )
        _clear_broadcast_state(context)
        return
    
    # 如果有无效群组，记录日志
    if invalid_groups:
        logger.info(
            f"[BROADCAST PRE-CHECK] 过滤了 {len(invalid_groups)} 个无效群组："
            f"{[f'{g.group_name}({g.group_id})' for g in invalid_groups[:5]]}"
        )
    
    # 保存选中的群组 ID（只保存有效群组）
    selected_group_ids = {g.group_id for g in valid_groups}
    user_data["selected_groups"] = selected_group_ids
    user_data["total_groups"] = len(target_groups)  # 保存原始总数用于日志

    # ==============================================
    # 👇 构建预览消息
    # ==============================================
    preview_text = ""

    # 1. 如果是转发消息，显示转发来源
    if msg.forward_from:
        preview_text += f"{msg.forward_from.full_name}\n"
    elif msg.forward_from_chat:
        preview_text += f"{msg.forward_from_chat.title}\n"

    # 2. 显示内容本身（文字 / 图片说明 / 视频说明）
    content = msg.text or msg.caption or "[图片/视频/文件]"
    preview_text += f"{content}\n\n"

    # 3. 固定格式
    total_original = user_data.get("total_groups", len(valid_groups))
    filtered_count = total_original - len(valid_groups)
    
    preview_text += f"广播分组：{target_group_name}\n"
    preview_text += f"总群组数：{total_original} 个"
    
    # 如果有过滤的群组，显示提示
    if filtered_count > 0:
        preview_text += f"\n✅ 有效群组：{len(valid_groups)} 个（已自动过滤 {filtered_count} 个不在群中的）"

    # ==============================================
    # 👇 底部按钮：取消 + 转发模式 + 发送模式
    # ==============================================
    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="broadcast_cancel")],
        [
            InlineKeyboardButton("👤 转发模式", callback_data="broadcast_forward"),
            InlineKeyboardButton("🤖 发送模式", callback_data="broadcast_send")
        ]
    ]

    await msg.reply_text(
        preview_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # 重要：必须返回，否则会继续执行后续代码
    return


async def _execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    【第六步】执行广播
    
    根据选择的模式（forward/send）调用对应的处理函数
    """
    broadcast_mode = context.user_data.get("broadcast_mode")
    
    if not broadcast_mode:
        await update.callback_query.edit_message_text("❌ 未选择发送模式")
        return
    
    # 调用对应的处理函数
    if broadcast_mode == "forward":
        await do_broadcast_forward(update, context)
    elif broadcast_mode == "send":
        await do_broadcast_send(update, context)
    else:
        await update.callback_query.edit_message_text("❌ 未知的发送模式")


async def do_broadcast_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行转发模式（保留原发送人，带来源）- 生产可用版"""
    query = update.callback_query
    await query.answer()

    from telegram import ChatMember
    
    msg = context.user_data.get("broadcast_msg")
    selected = context.user_data.get("selected_groups", set())
    target_group_name = context.user_data.get("broadcast_target_group_name", "未知分组")

    if not msg or not selected:
        await query.edit_message_text("❌ 广播内容或群组不能为空")
        return

    total_count = len(selected)
    success_count = 0
    fail_count = 0
    failed_groups = []  # 记录失败的群组
    
    # 发送延迟配置（防 Flood）
    SEND_DELAY = 1.2 if total_count > 30 else 0.8  # 大群组用更长延迟
    FAIL_DELAY = 0.4  # 失败后短延迟

    # ✅ 显示发送进度（忽略Telegram的"消息未修改"错误）
    try:
        await query.edit_message_text(f"⏳ 正在以【转发模式】发送到 {total_count} 个群组…\n请稍候...")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"[BROADCAST ERROR] 编辑进度消息失败: {e}")

    for chat_id in selected:
        try:
            # ✅ 前置检查已在预览阶段完成，这里直接发送
            # 但保留异常捕获以处理网络波动等临时问题

            # 转发模式：保留原作者、头像、来源
            await context.bot.forward_message(
                chat_id=chat_id,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id
            )
            success_count += 1
            await asyncio.sleep(SEND_DELAY)  # 正常延迟
            
        except Exception as e:
            logger.error(f"[BROADCAST FORWARD ERROR] 转发到群组 {chat_id} 失败: {e}")
            fail_count += 1
            
            # 简单分类失败原因
            error_msg = str(e).lower()
            if "bot was blocked" in error_msg or "forbidden" in error_msg:
                reason = "无权限"
            elif "chat not found" in error_msg:
                reason = "不在群中"
            else:
                reason = "未知异常"
            
            failed_groups.append(f"{chat_id}({reason})")
            await asyncio.sleep(FAIL_DELAY)  # 失败后短延迟

    # ✅ 问题1和问题3修复：构建结果文案，显示详细反馈
    mode_str = "转发模式"
    result_text = (
        f"✅ 广播发送完成！\n\n"
        f"📢 广播分组：{target_group_name}\n"
        f"📹 发送模式：{mode_str}\n"
        f"📊 总群数：{total_count}\n"
        f"✅ 成功：{success_count}\n"
        f"❌ 失败：{fail_count}"
    )
    
    # 只显示前5个失败的群组
    if failed_groups:
        result_text += f"\n\n❌ 失败的群组（前5个）：\n"
        for fg in failed_groups[:5]:
            result_text += f"• {fg}\n"
        if len(failed_groups) > 5:
            result_text += f"...还有 {len(failed_groups) - 5} 个"

    # ✅ 删除进度消息
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"[BROADCAST ERROR] 删除进度消息失败: {e}")
    
    # ✅ 弹出完整成功反馈
    await update.effective_message.reply_text(result_text, parse_mode='HTML')
    
    # 记录广播日志
    from ..utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    logger.info(
        f"[BROADCAST COMPLETE] bot_id={bot_id}, user_id={query.from_user.id}, "
        f"group={target_group_name}, mode={mode_str}, total={total_count}, success={success_count}, fail={fail_count}"
    )
    
    # 清空状态
    _clear_broadcast_state(context)


async def do_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行发送模式（机器人身份发送，不带来源）- 生产可用版"""
    query = update.callback_query
    await query.answer()

    from telegram import ChatMember
    
    msg = context.user_data.get("broadcast_msg")
    selected = context.user_data.get("selected_groups", set())
    target_group_name = context.user_data.get("broadcast_target_group_name", "未知分组")

    if not msg or not selected:
        await query.edit_message_text("❌ 广播内容或群组不能为空")
        return

    total_count = len(selected)
    success_count = 0
    fail_count = 0
    failed_groups = []  # 记录失败的群组
    
    # 发送延迟配置（防 Flood）
    SEND_DELAY = 1.2 if total_count > 30 else 0.8  # 大群组用更长延迟
    FAIL_DELAY = 0.4  # 失败后短延迟

    # ✅ 显示发送进度（忽略Telegram的"消息未修改"错误）
    try:
        await query.edit_message_text(f"⏳ 正在以【发送模式】发送到 {total_count} 个群组…\n请稍候...")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"[BROADCAST ERROR] 编辑进度消息失败: {e}")

    for chat_id in selected:
        try:
            # ✅ 前置检查已在预览阶段完成，这里直接发送
            # 但保留异常捕获以处理网络波动等临时问题

            # 发送模式：机器人自己发，不显示原作者（使用 copy_message 更稳定）
            await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id
            )
            success_count += 1
            await asyncio.sleep(SEND_DELAY)  # 正常延迟
            
        except Exception as e:
            logger.error(f"[BROADCAST SEND ERROR] 发送到群组 {chat_id} 失败: {e}")
            fail_count += 1
            
            # 简单分类失败原因
            error_msg = str(e).lower()
            if "bot was blocked" in error_msg or "forbidden" in error_msg:
                reason = "无权限"
            elif "chat not found" in error_msg:
                reason = "不在群中"
            else:
                reason = "未知异常"
            
            failed_groups.append(f"{chat_id}({reason})")
            await asyncio.sleep(FAIL_DELAY)  # 失败后短延迟

    # ✅ 问题1和问题3修复：构建结果文案，显示详细反馈
    mode_str = "发送模式"
    result_text = (
        f"✅ 广播发送完成！\n\n"
        f"📢 广播分组：{target_group_name}\n"
        f"📹 发送模式：{mode_str}\n"
        f" 总群数：{total_count}\n"
        f"✅ 成功：{success_count}\n"
        f"❌ 失败：{fail_count}"
    )
    
    # 只显示前5个失败的群组
    if failed_groups:
        result_text += f"\n\n❌ 失败的群组（前5个）：\n"
        for fg in failed_groups[:5]:
            result_text += f"• {fg}\n"
        if len(failed_groups) > 5:
            result_text += f"...还有 {len(failed_groups) - 5} 个"

    # ✅ 删除进度消息
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"[BROADCAST ERROR] 删除进度消息失败: {e}")
    
    # ✅ 弹出完整成功反馈
    await update.effective_message.reply_text(result_text, parse_mode='HTML')
    
    # 记录广播日志
    from ..utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    logger.info(
        f"[BROADCAST COMPLETE] bot_id={bot_id}, user_id={query.from_user.id}, "
        f"group={target_group_name}, mode={mode_str}, total={total_count}, success={success_count}, fail={fail_count}"
    )
    
    # 清空状态
    _clear_broadcast_state(context)





async def handle_runtime_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    运行统计 - 按身份显示不同的统计信息
    不包含个人信息
    """
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    user_id = user.id
    
    # 获取当前 bot_id
    bot_id = get_current_bot_id(context)
    
    # 获取用户角色
    user_role = await get_user_role(user_id, bot_id=bot_id)
    
    # 获取统计数据
    from ..models import Group, Admin, Transaction, get_db_session
    from sqlalchemy import select, and_, func
    from datetime import datetime, date
    
    async with get_db_session() as db:
        try:
            # 1. 授权群组数量（当前Bot的所有群组）
            groups_query = select(func.count(Group.id)).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.is_active.is_(True)
                )
            )
            groups_result = await db.execute(groups_query)
            group_count = groups_result.scalar() or 0
            
            # 2. 今日账单数量
            today = date.today()
            today_start = datetime(today.year, today.month, today.day)
            today_end = datetime(today.year, today.month, today.day, 23, 59, 59)
            
            tx_query = select(func.count(Transaction.id)).where(
                and_(
                    Transaction.bot_id == bot_id,
                    Transaction.created_at >= today_start,
                    Transaction.created_at <= today_end
                )
            )
            tx_result = await db.execute(tx_query)
            today_tx_count = tx_result.scalar() or 0
            
            if user_role == UserRole.SUPER_ADMIN:
                # 超级管理员：显示全局数据
                from ..models import PrivateChatUser
                
                # 私聊客户数量
                customers_query = select(func.count(PrivateChatUser.id)).where(
                    PrivateChatUser.bot_id == bot_id
                )
                customers_result = await db.execute(customers_query)
                customer_count = customers_result.scalar() or 0
                
                # 平台管理员数量
                admins_query = select(func.count(Admin.id)).where(
                    and_(
                        Admin.bot_id == bot_id,
                        Admin.is_active.is_(True)
                    )
                )
                admins_result = await db.execute(admins_query)
                admin_count = admins_result.scalar() or 0
                
                text = (
                    "📊 系统运行小统计\n\n"
                    f"👥 授权群组：{group_count} 个\n"
                    f"💬 私聊客户：{customer_count} 人\n"
                    f"🛠 平台管理员：{admin_count} 人\n"
                    f"📝 今日账单：{today_tx_count} 笔\n\n"
                    "🤖 机器人乖乖运行中✨\n"
                    "💎 身份：超级管理员"
                )
            
            elif user_role == UserRole.BOT_OWNER:
                # Bot创建者：显示当前Bot数据
                from ..models import PrivateChatUser
                
                # 我的私聊用户数量
                customers_query = select(func.count(PrivateChatUser.id)).where(
                    PrivateChatUser.bot_id == bot_id
                )
                customers_result = await db.execute(customers_query)
                customer_count = customers_result.scalar() or 0
                
                # 我的管理员数量
                admins_query = select(func.count(Admin.id)).where(
                    and_(
                        Admin.bot_id == bot_id,
                        Admin.is_active.is_(True)
                    )
                )
                admins_result = await db.execute(admins_query)
                admin_count = admins_result.scalar() or 0
                
                text = (
                    "📊 机器人运行小统计\n\n"
                    f"👥 我的授权群组：{group_count} 个\n"
                    f"💬 我的私聊用户：{customer_count} 人\n"
                    f"🛠 我的管理员：{admin_count} 人\n"
                    f"📝 今日记账：{today_tx_count} 笔\n\n"
                    "🤖 你的机器人在线状态超棒🥳\n"
                    "💡 数据只属于这个 Bot 哦～"
                )
            
            elif user_role == UserRole.ADMIN:
                # 普通管理员：显示负责的群组数据
                text = (
                    "📊 运营小数据\n\n"
                    f"👥 我管的群组：{group_count} 个\n"
                    f"💬 今日互动用户：0 人\n"
                    f"📝 今日账单：{today_tx_count} 笔\n\n"
                    "🤖 服务状态：正常可用☁️"
                )
            
            else:
                # 普通用户：显示自己的今日账单数
                # 查询该用户的今日账单数
                user_tx_query = select(func.count(Transaction.id)).where(
                    and_(
                        Transaction.bot_id == bot_id,
                        Transaction.created_at >= today_start,
                        Transaction.created_at <= today_end
                    )
                )
                user_tx_result = await db.execute(user_tx_query)
                user_tx_count = user_tx_result.scalar() or 0
                
                text = (
                    "📊 我的使用小记录\n\n"
                    f"📝 今日记账：{user_tx_count} 笔\n\n"
                    "🤖 机器人在为你好好服务哦🌸"
                )
            
            await update.message.reply_text(text)
            
        except Exception as e:
            logger.error(f"Error in handle_runtime_stats: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ 获取运行统计失败，请稍后重试。\n\n"
                f"错误信息：{str(e)}"
            )

async def handle_personal_center(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """新版个人中心文案。"""
    from ..models import BotCreation, get_db_session
    from ..utils.bot_id_middleware import get_current_bot_id
    from .bot_management_handler import render_bot_manage_buttons

    query = update.callback_query
    message = update.message

    try:
        if not update.effective_user:
            return

        if query:
            await query.answer()

        user = update.effective_user
        user_id = user.id
        username = f"@{html.escape(user.username)}" if user.username else "@无"
        bot_id = get_current_bot_id(context)

        async with get_db_session() as db:
            identity_info = await _detect_user_identity(user_id, bot_id, db)
            bot_status = await _get_bot_status(bot_id, db)
            identity = identity_info["identity"]
            role_name = identity_info["role_name"]
            role_tip = identity_info["role_tip"]
            is_expired = identity_info["is_expired"]
            days_left = identity_info["days_left"]
            expire_time = identity_info["expire_time"]
            package_type = identity_info["package_type"]
            service_status = identity_info["service_status"]
            bot_username = identity_info["bot_username"]

            current_bot_result = await db.execute(
                select(BotCreation).where(BotCreation.instance_id == bot_id)
            )
            current_bot = current_bot_result.scalar_one_or_none()

            managed_bot = identity_info.get("bot_creation") if identity in {"bot_creator", "manual_bot_user"} else current_bot
            if not managed_bot and identity in {"super_admin", "bot_creator", "manual_bot_user"}:
                from ..services.account_status_service import account_status_service
                owned_bots = await account_status_service.get_owned_bots(user_id, db)
                managed_bot = owned_bots[0] if owned_bots else None
            if identity in {"bot_creator", "manual_bot_user"} and managed_bot and managed_bot.telegram_id != user_id:
                managed_bot = identity_info.get("bot_creation") or managed_bot

            run_status = bot_status["run_status"]
            token_status = bot_status["token_status"]
            if managed_bot:
                if getattr(managed_bot, "status", "") == "running":
                    run_status = "✅ 正常运行"
                elif getattr(managed_bot, "status", ""):
                    run_status = getattr(managed_bot, "status")
                if getattr(managed_bot, "token_status", "") == "normal":
                    token_status = "✅ 正常"
                elif getattr(managed_bot, "token_status", "") == "invalid":
                    token_status = "❌ 已失效"

            if identity == "super_admin":
                text = (
                    "👤 个人中心 - 超级管理员\n"
                    f"🆔 用户ID：<code>{user_id}</code>\n"
                    f"👤 用户名：{username}\n"
                    "💎 权限：超级管理员\n"
                    f"🤖 所属机器人：{bot_username}\n"
                    "📅 到期时间：永久有效\n"
                    "📦 当前版本：全功能版\n\n"
                    "🤖 机器人状态\n"
                    f"运行状态：{run_status}\n"
                    f"Token状态：{token_status}"
                )
            elif identity in {"bot_creator", "manual_bot_user"}:
                text = (
                    f"👤 个人中心 - {role_name}\n"
                    f"🆔 用户ID：<code>{user_id}</code>\n"
                    f"👤 用户名：{username}\n"
                    f"📦 当前套餐：{package_type}\n"
                    f"🔖 订阅状态：{service_status}\n"
                    f"⏳ 剩余有效期：{days_left} 天\n"
                    f"📅 到期时间：{expire_time}\n"
                    f"🤖 所属机器人：{bot_username}\n\n"
                    "🤖 机器人状态\n"
                    f"运行状态：{run_status}\n"
                    f"Token状态：{token_status}"
                )
            else:
                text = (
                    "👤 个人中心\n"
                    f"🆔 用户ID：<code>{user_id}</code>\n"
                    f"👤 用户名：{username}\n"
                    f"📌 当前身份：{role_name}\n\n"
                    f"{role_tip or '开通专属Bot后可解锁完整功能与独立数据。'}\n\n"
                    "✨ 拥有专属机器人后可享受：\n"
                    "• 独立机器人与独立数据\n"
                    "• 功能设置、广播、广告等完整能力\n"
                    "• 专属续费、管理与机器人状态控制"
                )

        if is_expired and identity in {"super_admin", "bot_creator", "manual_bot_user"}:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 立即续费", callback_data="v1:saas:create_bot")],
                [InlineKeyboardButton("⬅️ 返回", callback_data="back_to_main_menu")],
            ])
        elif identity in {"super_admin", "bot_creator", "manual_bot_user"} and managed_bot:
            keyboard = render_bot_manage_buttons(managed_bot.instance_id, user_id, "created_success")
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 创建续费", callback_data="v1:saas:create_bot")],
                [InlineKeyboardButton("⬅️ 返回", callback_data="back_to_main_menu")],
            ])

        if query:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        elif message:
            await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        traceback.print_exc()
        logger.error("[PERSONAL_CENTER_V2] failed", exc_info=True)
        if query:
            await query.answer("加载个人中心失败，请稍后重试", show_alert=True)
        elif message:
            await message.reply_text("加载个人中心失败，请稍后重试")
_legacy_detect_user_identity = _detect_user_identity


async def _detect_user_identity(user_id: int, bot_id: str, db) -> dict:
    info = await _legacy_detect_user_identity(user_id, bot_id, db)
    if info.get("identity") in {"bot_creator", "manual_bot_user"}:
        if info.get("package_type") in {"独立Bot", "暂无套餐"}:
            info["package_type"] = "全功能版"
        if info.get("service_status") in {"无订阅", "✅ 正常"} or info.get("identity") == "manual_bot_user":
            info["service_status"] = "超管手动开通"
    return info

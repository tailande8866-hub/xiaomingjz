"""
管理员手动开通订阅Handler
支持超管为主Bot手动给客户开通套餐（线下付款场景）
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from ..models import Subscription, PricingPlan, get_db_session
from config import config

logger = logging.getLogger(__name__)


def _is_main_bot_runtime() -> bool:
    return os.environ.get("IS_MAIN_BOT", "true").lower() != "false"


# 套餐时长映射
PLAN_DURATION_MAP = {
    "1": 30,      # 1个月
    "3": 90,      # 3个月
    "12": 365,    # 1年
    "permanent": 99999  # 永久
}


async def handle_manual_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理手动开通订阅命令
    
    用法：/activate <用户ID或@username> <套餐ID>
    例如：/activate 123456789 1
    """
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    telegram_id = user.id
    
    # 检查是否是主Bot的超级管理员
    if not _is_main_bot_runtime():
        await update.message.reply_text(
            "❌ 此命令仅限主机器人使用",
            parse_mode='HTML'
        )
        return
    
    # 检查是否是超级管理员
    if telegram_id != config.SUPER_ADMIN_ID:
        await update.message.reply_text(
            "❌ 权限不足\n\n只有超级管理员可以使用此命令",
            parse_mode='HTML'
        )
        return
    
    # 解析参数
    text = update.message.text.strip()
    parts = text.split()
    
    if len(parts) < 3:
        await show_activate_help(update)
        return
    
    target_identifier = parts[1]  # 用户ID或@username
    plan_id_str = parts[2]  # 套餐ID
    
    # 获取目标用户的Telegram ID
    target_telegram_id = await resolve_user_id(context, target_identifier)
    if not target_telegram_id:
        await update.message.reply_text(
            f"❌ 无法找到用户：{target_identifier}\n\n请确认用户ID或用户名正确",
            parse_mode='HTML'
        )
        return
    
    # 获取套餐信息
    async with get_db_session() as db:
        try:
            query = select(PricingPlan).where(PricingPlan.id == int(plan_id_str))
            result = await db.execute(query)
            plan = result.scalar_one_or_none()
            
            if not plan:
                await update.message.reply_text(
                    f"❌ 套餐ID {plan_id_str} 不存在\n\n请先使用 /plans 查看可用套餐",
                    parse_mode='HTML'
                )
                return
            
            # 执行手动开通
            success, message = await manual_activate_subscription(
                telegram_id=target_telegram_id,
                plan_id=plan.id,
                operator_id=telegram_id
            )
            
            if success:
                # 获取用户信息用于显示
                try:
                    target_user = await context.bot.get_chat(target_telegram_id)
                    target_name = target_user.first_name or target_user.username or str(target_telegram_id)
                except Exception:
                    target_name = str(target_telegram_id)
                
                await update.message.reply_text(
                    f"✅ <b>手动开通成功！</b>\n\n"
                    f"👤 用户：{target_name}\n"
                    f"📦 套餐：{plan.name}\n"
                    f"💰 价格：{plan.price} USDT\n"
                    f"⏱️ 时长：{plan.duration_days} 天\n\n"
                    f"{message}\n\n"
                    "🛠️ <b>相关操作</b>\n"
                    "您可以继续执行以下操作：",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛠 超管后台", callback_data="sa:panel"),
                         InlineKeyboardButton("💬 消息中心", callback_data="sa:message_center")],
                        [InlineKeyboardButton("🔙 返回", callback_data="sa:panel")]
                    ]),
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    f"❌ 开通失败\n\n{message}",
                    parse_mode='HTML'
                )
                
        except ValueError:
            await update.message.reply_text(
                "❌ 套餐ID必须是数字",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error in handle_manual_activate: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ 处理命令时出错\n\n{str(e)}",
                parse_mode='HTML'
            )


async def resolve_user_id(context: ContextTypes.DEFAULT_TYPE, identifier: str) -> Optional[int]:
    """解析用户标识符，返回Telegram ID"""
    try:
        if identifier.startswith('@'):
            # 是用户名
            username = identifier[1:]
            chat = await context.bot.get_chat(username)
            return chat.id
        else:
            # 是数字ID
            return int(identifier)
    except (ValueError, Exception) as e:
        logger.error(f"Error resolving user ID '{identifier}': {e}")
        return None


async def manual_activate_subscription(
    telegram_id: int,
    plan_id: int,
    operator_id: int
) -> tuple[bool, str]:
    """
    手动开通/续费订阅
    
    Returns:
        (success, message)
    """
    try:
        async with get_db_session() as db:
            # 获取套餐信息
            query = select(PricingPlan).where(PricingPlan.id == plan_id)
            result = await db.execute(query)
            plan = result.scalar_one_or_none()
            
            if not plan:
                return False, "套餐不存在"
            
            # 检查是否已有活跃订阅
            existing_query = select(Subscription).where(
                and_(
                    Subscription.telegram_id == telegram_id,
                    Subscription.status == "active"
                )
            )
            existing_result = await db.execute(existing_query)
            existing_sub = existing_result.scalar_one_or_none()
            
            now = datetime.utcnow()
            
            if existing_sub:
                # 续费：延长到期时间
                if existing_sub.expire_date > now:
                    # 从当前到期时间开始延长
                    new_expire_date = existing_sub.expire_date + timedelta(days=plan.duration_days)
                else:
                    # 已过期，从现在开始
                    new_expire_date = now + timedelta(days=plan.duration_days)
                
                existing_sub.plan_id = plan_id
                existing_sub.plan_name = plan.name
                existing_sub.expire_date = new_expire_date
                existing_sub.updated_at = now
                
                action = "续费"
            else:
                # 新订阅
                # 获取用户信息
                try:
                    chat = None  # 暂时不获取，避免阻塞
                except Exception:
                    pass
                
                subscription = Subscription(
                    telegram_id=telegram_id,
                    username=f"User_{telegram_id}",
                    plan_id=plan_id,
                    plan_name=plan.name,
                    status="active",
                    start_date=now,
                    expire_date=now + timedelta(days=plan.duration_days),
                    auto_renew=False,
                    bots_created=0,
                    total_groups=0
                )
                db.add(subscription)
                action = "开通"
            
            await db.commit()
            
            return True, f"订阅{action}成功！有效期至 {subscription.expire_date.strftime('%Y-%m-%d %H:%M:%S')}"
            
    except Exception as e:
        logger.error(f"Error in manual_activate_subscription: {e}", exc_info=True)
        return False, f"激活失败: {str(e)}"


async def show_activate_help(update: Update):
    """显示激活命令帮助"""
    help_text = """📝 <b>手动开通订阅命令</b>

用法：/activate &lt;用户ID或@username&gt; &lt;套餐ID&gt;

示例：
• /activate 123456789 1
• /activate @username 1

查看可用套餐：/plans

⚠️ 注意：
• 仅限主机器人超级管理员使用
• 此命令无需付款，直接开通订阅
• 适合线下付款场景
"""
    await update.message.reply_text(help_text, parse_mode='HTML')


async def handle_manual_extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理手动延长订阅命令（续费）
    
    用法：/extend <用户ID或@username> <套餐ID>
    """
    if not update.message or not update.effective_user:
        return
    
    user = update.effective_user
    telegram_id = user.id
    
    # 检查权限
    if not _is_main_bot_runtime():
        await update.message.reply_text("❌ 此命令仅限主机器人使用", parse_mode='HTML')
        return
    
    if telegram_id != config.SUPER_ADMIN_ID:
        await update.message.reply_text("❌ 权限不足", parse_mode='HTML')
        return
    
    # 解析参数
    text = update.message.text.strip()
    parts = text.split()
    
    if len(parts) < 3:
        await update.message.reply_text(
            "用法：/extend <用户ID或@username> <套餐ID>",
            parse_mode='HTML'
        )
        return
    
    target_identifier = parts[1]
    plan_id_str = parts[2]
    
    # 获取目标用户ID
    target_telegram_id = await resolve_user_id(context, target_identifier)
    if not target_telegram_id:
        await update.message.reply_text(f"❌ 无法找到用户：{target_identifier}", parse_mode='HTML')
        return
    
    # 执行续费
    try:
        plan_id = int(plan_id_str)
    except ValueError:
        await update.message.reply_text("❌ 套餐ID必须是数字", parse_mode='HTML')
        return
    
    success, message = await manual_activate_subscription(
        telegram_id=target_telegram_id,
        plan_id=plan_id,
        operator_id=telegram_id
    )
    
    if success:
        await update.message.reply_text(
            f"✅ <b>续费成功！</b>\n\n{message}\n\n"
            "🛠️ <b>相关操作</b>\n"
            "您可以继续执行以下操作：",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛠 超管后台", callback_data="sa:panel"),
                 InlineKeyboardButton("💬 消息中心", callback_data="sa:message_center")],
                [InlineKeyboardButton("🔙 返回", callback_data="sa:panel")]
            ]),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(f"❌ 续费失败\n\n{message}", parse_mode='HTML')

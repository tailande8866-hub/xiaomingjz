"""
额度管理命令处理器

提供以下命令：
- /setquota 或 "设置额度" - 设置群组额度
- /disablequota 或 "关闭额度设置" - 禁用额度监控
"""
import logging
import re
from telegram import Update
from telegram.ext import ContextTypes

from ..services.quota_service import quota_service
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import get_user_role, UserRole
from ..utils.permission_checker import require_authorized_group

logger = logging.getLogger(__name__)


@require_authorized_group
async def cmd_set_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    设置群组额度
    
    用法：
    - /setquota 100
    - /setquota 100u
    - 设置额度 100
    - 设置额度 100u
    
    参数：
    - 数字：额度上限
    - 可选后缀 'u' 或 'U'：表示 USDT 币种，否则使用默认币种
    """
    if not update.message or not update.effective_chat:
        return
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 仅支持群组
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此命令仅支持在群组中使用")
        return
    
    # 获取 bot_id
    bot_id = get_current_bot_id(context)
    
    # 检查权限（OPERATOR 及以上）
    role = await get_user_role(user.id, chat_id, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系群组管理员或操作员。"
        )
        return
    
    # 解析命令文本
    text = update.message.text.strip()
    
    # 匹配命令格式
    match = re.search(r'(?:设置额度|/setquota)\s+(\d+(?:\.\d+)?)([uU]?)', text)
    
    if not match:
        await update.message.reply_text(
            "❌ 格式错误\n\n"
            "正确用法：\n"
            "• 设置额度 100\n"
            "• 设置额度 100u\n"
            "• /setquota 100\n"
            "• /setquota 100u\n\n"
            "说明：添加 'u' 后缀表示 USDT 币种"
        )
        return
    
    amount_str = match.group(1)
    currency_suffix = match.group(2).lower()
    
    # 转换为浮点数
    try:
        amount = float(amount_str)
    except ValueError:
        await update.message.reply_text("❌ 无效的额度数值")
        return
    
    # 确定币种
    currency = "USDT" if currency_suffix == 'u' else "CNY"
    
    # 调用服务设置额度
    success, message = await quota_service.set_quota(
        group_id=chat_id,
        bot_id=bot_id,
        amount=amount,
        currency=currency
    )
    
    await update.message.reply_text(message)


@require_authorized_group
async def cmd_disable_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    关闭额度设置
    
    用法：
    - /disablequota
    - 关闭额度设置
    """
    if not update.message or not update.effective_chat:
        return
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 仅支持群组
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此命令仅支持在群组中使用")
        return
    
    # 获取 bot_id
    bot_id = get_current_bot_id(context)
    
    # 检查权限（OPERATOR 及以上）
    role = await get_user_role(user.id, chat_id, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]:
        await update.message.reply_text(
            "❌ 您没有权限执行此操作\n\n"
            "请联系群组管理员或操作员。"
        )
        return
    
    # 调用服务禁用额度
    success, message = await quota_service.disable_quota(
        group_id=chat_id,
        bot_id=bot_id
    )
    
    await update.message.reply_text(message)


def register_quota_commands(application):
    """
    注册额度管理命令
    
    Args:
        application: Telegram Application 实例
    """
    from telegram.ext import CommandHandler, MessageHandler, filters
    
    # 注册命令
    application.add_handler(CommandHandler("setquota", cmd_set_quota))
    application.add_handler(CommandHandler("disablequota", cmd_disable_quota))
    
    # 注册中文命令（MessageHandler）
    application.add_handler(MessageHandler(
        filters.Regex(r'^设置额度\s+.+') & filters.ChatType.GROUPS,
        cmd_set_quota
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r'^关闭额度设置$') & filters.ChatType.GROUPS,
        cmd_disable_quota
    ))
    
    logger.info("✅ Quota commands registered")

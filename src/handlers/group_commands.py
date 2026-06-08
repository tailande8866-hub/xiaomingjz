"""
群组管理命令处理器

功能：
1. 群组管理员发送 "机器人退群" 命令，机器人清除数据并退出群组
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import get_user_role, UserRole
from ..models import Group, Transaction, UserConfig, get_db_session
from sqlalchemy import delete, and_

logger = logging.getLogger(__name__)


async def cmd_leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    群组管理员发送 "机器人退群" 命令，机器人清除数据并退出群组
    
    用法：在群组中发送 "机器人退群"
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 仅允许群组使用
    if chat_id > 0:
        return  # 私聊不处理
    
    bot_id = get_current_bot_id(context)
    
    # 检查用户权限：只有管理员或操作员可以执行
    role = await get_user_role(user.id, chat_id, bot_id)
    if role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]:
        logger.warning(f"用户 {user.id} 尝试执行退群命令但权限不足 (role={role})")
        return
    
    # 确认命令文本
    text = update.message.text.strip()
    if text != "机器人退群":
        return
    
    logger.info(f"🚪 群组 {chat_id} 收到退群命令，执行者: {user.username or user.first_name} (ID: {user.id})")
    
    # 发送确认消息
    confirm_message = await update.message.reply_text(
        "⚠️ <b>正在执行退群操作...</b>\n\n"
        "1. 清除群组数据\n"
        "2. 删除交易记录\n"
        "3. 删除用户配置\n"
        "4. 退出群组\n\n"
        "请稍候..."
    )
    
    try:
        # 🆕 先通知管理员（在删除数据之前）
        from ..services.group_state_sync_engine import group_state_sync_engine
        await group_state_sync_engine._notify_admins(chat_id, "removed", bot_id, context)
        logger.info(f"   📢 已发送退群通知给管理员")
        
        async with get_db_session() as db:
            # 1. 删除该群组的所有交易记录
            tx_delete_stmt = delete(Transaction).where(
                and_(
                    Transaction.bot_id == bot_id,
                    Transaction.group_id == chat_id
                )
            )
            tx_result = await db.execute(tx_delete_stmt)
            tx_count = tx_result.rowcount
            logger.info(f"   🗑️ 已删除 {tx_count} 条交易记录")
            
            # 2. 删除该群组的所有用户配置
            config_delete_stmt = delete(UserConfig).where(
                and_(
                    UserConfig.bot_id == bot_id,
                    UserConfig.group_id == chat_id
                )
            )
            config_result = await db.execute(config_delete_stmt)
            config_count = config_result.rowcount
            logger.info(f"   🗑️ 已删除 {config_count} 条用户配置")
            
            # 3. 删除群组记录
            group_delete_stmt = delete(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.group_id == chat_id
                )
            )
            group_result = await db.execute(group_delete_stmt)
            group_count = group_result.rowcount
            logger.info(f"   🗑️ 已删除 {group_count} 条群组记录")
            
            await db.commit()
            
            logger.info(f"✅ 群组 {chat_id} 数据清理完成")
        
        # 发送最终消息
        final_message = (
            f"✅ <b>数据清理完成</b>\n\n"
            f"• 删除交易记录: {tx_count} 条\n"
            f"• 删除用户配置: {config_count} 条\n"
            f"• 删除群组记录: {group_count} 条\n\n"
            f"机器人将在 3 秒后退出群组..."
        )
        
        await confirm_message.edit_text(final_message, parse_mode='HTML')
        
        # 等待3秒后退出
        import asyncio
        await asyncio.sleep(3)
        
        # 退出群组
        await context.bot.leave_chat(chat_id)
        logger.info(f"🚪 机器人已退出群组 {chat_id}")
        
    except Exception as e:
        logger.error(f"❌ 退群操作失败: {e}", exc_info=True)
        await confirm_message.edit_text(
            f"❌ <b>退群操作失败</b>\n\n"
            f"错误信息: {str(e)}\n\n"
            f"请联系技术支持。",
            parse_mode='HTML'
        )


def register_group_commands(application):
    """
    注册群组管理命令
    
    Args:
        application: Telegram Application 实例
    """
    # 机器人退群命令
    application.add_handler(MessageHandler(filters.Regex(r'^机器人退群$'), cmd_leave_group))
    
    logger.info("✅ 群组管理命令已注册")

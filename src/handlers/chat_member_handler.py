"""
群组状态变更处理器 - 监听机器人自身被踢/退群/重新进群（增强版）
"""
import logging
from telegram import Update, ChatMemberUpdated, ChatMember
from telegram.ext import ContextTypes, ChatMemberHandler

from ..utils.bot_id_middleware import get_current_bot_id
from ..services.group_state_sync_engine import group_state_sync_engine

logger = logging.getLogger(__name__)


async def handle_bot_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理机器人自身的聊天成员状态变更（增强版）
    
    场景：
    1. 机器人被踢出群组 (member.kicked)
    2. 机器人主动退群 (member.left)
    3. 机器人被重新邀请进群 (member.joined)
    4. 机器人从受限恢复 (member.restricted -> member.member/administrator)
    """
    if not update.my_chat_member:
        logger.debug("No my_chat_member in update, skipping")
        return
    
    chat_member_update: ChatMemberUpdated = update.my_chat_member
    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status
    chat_id = chat_member_update.chat.id
    chat_title = chat_member_update.chat.title or "Unknown"
    
    # ✅ 使用 bot_id middleware 获取当前 bot_id
    bot_id = get_current_bot_id(context)
    
    logger.info(f"🔔 Bot status changed in chat {chat_id} ({chat_title}): {old_status} -> {new_status}")
    
    # 🆕 发布群组状态变更事件
    try:
        from ..core.event_publisher import publish_group_status_changed
        await publish_group_status_changed(
            group_id=chat_id,
            bot_id=bot_id,
            old_status=old_status,
            new_status=new_status
        )
    except Exception as e:
        logger.error(f"Failed to publish group status change event: {e}")
    
    # 只处理群组（忽略私聊）
    if chat_id > 0:
        logger.debug(f"Ignoring private chat {chat_id}")
        return
    
    # ✅ 使用状态同步引擎
    # 👤 获取拉 bot 进群的用户（from_user 表示执行操作的用户）
    from_user = chat_member_update.from_user
    await group_state_sync_engine.handle_status_change(
        chat_id, 
        old_status, 
        new_status, 
        bot_id, 
        context,
        from_user=from_user
    )


def register_chat_member_handler(application):
    """
    注册 my_chat_member 处理器
    
    Args:
        application: Telegram Application 实例
    """
    handler = ChatMemberHandler(handle_bot_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    application.add_handler(handler)
    logger.info("ChatMember handler registered for bot status changes")

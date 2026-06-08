"""
入群欢迎语事件处理器 - 监听新用户进群事件

同时使用两种方式监听：
1. MessageHandler 监听 new_chat_members 服务消息（不需要管理员权限）
2. ChatMemberHandler 监听 chat_member 事件（需要管理员权限，更可靠）

当有新用户加入群组时，自动发送入群欢迎语。
内置去重缓存，5秒内同一用户同一群组只发一次。
"""
import logging
import time
from telegram import Update, ChatMemberUpdated
from telegram.ext import ContextTypes, MessageHandler, filters, ChatMemberHandler

from ..services.join_welcome_service import join_welcome_service
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)

# 去重缓存：key=(chat_id, user_id) → timestamp
_sent_cache = {}
_CACHE_TTL = 5  # 5秒内同一用户不去重


def _should_send(chat_id: int, user_id: int) -> bool:
    """检查是否应该发送欢迎语（去重）"""
    key = (chat_id, user_id)
    now = time.time()
    if key in _sent_cache and now - _sent_cache[key] < _CACHE_TTL:
        logger.debug(f"[JOIN_WELCOME] 去重跳过: user={user_id} in chat={chat_id}")
        return False
    _sent_cache[key] = now
    # 清理过期缓存
    expired = [k for k, v in _sent_cache.items() if now - v >= _CACHE_TTL]
    for k in expired:
        del _sent_cache[k]
    return True


async def _send_welcome(chat_id: int, new_user, context: ContextTypes.DEFAULT_TYPE):
    """发送欢迎语的核心逻辑"""
    if new_user.is_bot:
        logger.debug(f"[JOIN_WELCOME] 跳过机器人: {new_user.username}")
        return

    if not _should_send(chat_id, new_user.id):
        return

    try:
        bot_id = get_current_bot_id(context)
    except Exception as e:
        logger.error(f"[JOIN_WELCOME] 获取 bot_id 失败: {e}", exc_info=True)
        return

    logger.info(f"[JOIN_WELCOME] 新成员进群: {new_user.username or new_user.first_name} "
                f"(ID: {new_user.id}), chat={chat_id}, bot={bot_id}")

    try:
        await join_welcome_service.send_join_welcome(
            chat_id=chat_id,
            bot_id=bot_id,
            new_user=new_user,
            context=context
        )
    except Exception as e:
        logger.error(f"[JOIN_WELCOME] 发送欢迎语失败 (user={new_user.id}): {e}", exc_info=True)


async def handle_new_chat_members_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 new_chat_members 服务消息（方式1：MessageHandler）"""
    logger.info(f"[JOIN_WELCOME] handle_new_chat_members_message 被调用! "
                f"has_message={update.message is not None}, "
                f"has_new_members={update.message and update.message.new_chat_members is not None}")

    if not update.message or not update.message.new_chat_members:
        if update.message:
            logger.info(f"[JOIN_WELCOME] 消息无 new_chat_members, "
                        f"chat={update.message.chat.id}, "
                        f"text={str(update.message.text)[:50] if update.message.text else 'None'}")
        return

    chat_id = update.message.chat.id
    new_members = update.message.new_chat_members

    logger.info(f"[JOIN_WELCOME] new_chat_members 服务消息: {len(new_members)} 人, chat={chat_id}")

    for new_user in new_members:
        await _send_welcome(
            chat_id=chat_id,
            new_user=new_user,
            context=context
        )


async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 chat_member 事件（方式2：ChatMemberHandler）"""
    if not update.chat_member:
        logger.debug("[JOIN_WELCOME] No chat_member in update")
        return

    chat_member_update: ChatMemberUpdated = update.chat_member
    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status

    logger.info(f"[JOIN_WELCOME] chat_member 事件: {old_status} -> {new_status}")

    # 检测新成员加入：旧状态不是成员，新状态是成员
    valid_old_statuses = ['left', 'kicked', 'restricted']
    valid_new_statuses = ['member', 'administrator', 'creator']

    if old_status in valid_old_statuses and new_status in valid_new_statuses:
        chat_id = chat_member_update.chat.id
        new_user = chat_member_update.new_chat_member.user
        logger.info(f"[JOIN_WELCOME] 检测到新成员加入 (chat_member 事件): "
                    f"{new_user.username or new_user.first_name}(ID: {new_user.id}), chat={chat_id}")
        await _send_welcome(
            chat_id=chat_id,
            new_user=new_user,
            context=context
        )


def register_join_welcome_handler(application):
    """
    注册入群欢迎语事件处理器

    同时使用两种监听方式以确保可靠性：
    1. MessageHandler 监听 new_chat_members 服务消息
    2. ChatMemberHandler 监听 chat_member 事件

    Args:
        application: Telegram Application 实例
    """
    # 方式1：MessageHandler 监听 new_chat_members 消息
    message_handler = MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        handle_new_chat_members_message,
        block=False
    )
    application.add_handler(message_handler, group=-1)
    logger.info("✅ [JOIN_WELCOME] MessageHandler(StatusUpdate.NEW_CHAT_MEMBERS) 已注册")

    # 方式2：ChatMemberHandler 监听 chat_member 事件
    chat_member_handler = ChatMemberHandler(
        handle_chat_member_update,
        ChatMemberHandler.CHAT_MEMBER
    )
    application.add_handler(chat_member_handler)
    logger.info("✅ [JOIN_WELCOME] ChatMemberHandler(CHAT_MEMBER) 已注册")

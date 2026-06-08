"""
群组成员索引处理器
监听所有群聊消息，自动将用户信息保存到数据库
支持 @username 添加操作人功能
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from sqlalchemy import and_, select

from ..repositories.group_member_index_repo import GroupMemberIndexRepo
from ..utils.bot_id_middleware import get_current_bot_id
from ..models import GroupMemberIndex
from ..models.database import get_db
from ..services.global_config_service import global_config_service

logger = logging.getLogger(__name__)


async def handle_group_message_for_index(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群聊消息，自动更新群成员索引到数据库
    
    这是 User Index Pipeline 的关键一环：
    用户发消息 → 自动保存到 group_member_index 表
    """
    # 安全检查
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    # 只处理群聊（不包括私聊）
    if update.effective_chat.type not in ['group', 'supergroup']:
        return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    logger.debug(f"消息处理器触发: chat_id={chat_id}, type={update.effective_chat.type}, user={user.id}, username={user.username}")
    
    try:
        # 获取当前 bot_id
        bot_id = get_current_bot_id(context)
        logger.debug(f"获取到 bot_id={bot_id}")
        
        if not bot_id:
            logger.warning("无法获取 bot_id，跳过群成员索引")
            return
        
        logger.info(f"准备保存群成员索引: bot_id={bot_id}, group_id={chat_id}, user_id={user.id}, username={user.username}")
        
        # 异步保存到数据库（不阻塞其他处理器）
        async for db in get_db():
            existing_result = await db.execute(
                select(GroupMemberIndex).where(
                    and_(
                        GroupMemberIndex.bot_id == bot_id,
                        GroupMemberIndex.group_id == chat_id,
                        GroupMemberIndex.user_id == user.id
                    )
                )
            )
            existing_member = existing_result.scalar_one_or_none()

            if existing_member:
                await _send_profile_change_alerts(
                    update=update,
                    context=context,
                    db=db,
                    bot_id=bot_id,
                    old_username=existing_member.username or "",
                    new_username=(user.username or "").lower().lstrip("@"),
                    old_first_name=existing_member.first_name or "",
                    new_first_name=user.first_name or "",
                )

            logger.debug(f"开始 upsert_member")
            await GroupMemberIndexRepo.upsert_member(
                db=db,
                bot_id=bot_id,
                group_id=chat_id,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name
            )
            logger.debug(f"准备 commit")
            await db.commit()
            logger.debug(f"commit 完成")
            break  # 只执行一次
            
        logger.info(
            f"✅ 群成员索引已保存: bot_id={bot_id}, "
            f"group_id={chat_id}, user_id={user.id}, "
            f"username=@{user.username}"
        )
        
    except Exception as e:
        logger.error(f"❌ 群成员索引保存失败: {e}", exc_info=True)
        # 不抛出异常，避免影响其他处理器


async def _send_profile_change_alerts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db,
    bot_id: str,
    old_username: str,
    new_username: str,
    old_first_name: str,
    new_first_name: str,
):
    """基于群消息中的最新用户资料，检测昵称/用户名变化并按开关提醒。"""
    chat = update.effective_chat
    user = update.effective_user

    username_changed = old_username != new_username
    nickname_changed = old_first_name != new_first_name

    if not username_changed and not nickname_changed:
        return

    nickname_enabled = await global_config_service.get_config(db, bot_id, "nickname_monitor_enabled")
    username_enabled = await global_config_service.get_config(db, bot_id, "username_monitor_enabled")

    from datetime import datetime

    if username_changed and (username_enabled if isinstance(username_enabled, bool) else False):
        old_display = f"@{old_username}" if old_username else "无"
        new_display = f"@{new_username}" if new_username else "无"
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "📢 <b>用户名变更提醒</b>\n\n"
                f"用户ID: <code>{user.id}</code>\n"
                f"旧用户名: {old_display}\n"
                f"新用户名: {new_display}\n"
                f"群: {chat.title or '未知群组'}\n"
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            ),
            parse_mode="HTML",
        )

    if nickname_changed and (nickname_enabled if isinstance(nickname_enabled, bool) else False):
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "📢 <b>昵称变更提醒</b>\n\n"
                f"用户ID: <code>{user.id}</code>\n"
                f"旧昵称: {old_first_name or '无'}\n"
                f"新昵称: {new_first_name or '无'}\n"
                f"群: {chat.title or '未知群组'}\n"
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            ),
            parse_mode="HTML",
        )


def register_group_member_index_handler(application):
    """
    注册群成员索引处理器
    
    优先级：group=-1（最高优先级，最先执行）
    非阻塞：block=False（不影响其他处理器）
    
    使用 group=-1 确保这个 handler 在所有其他 handlers 之前执行，
    这样用户发送消息时，会首先被保存到数据库，
    然后才能被 @username 查询到。
    """
    handler = MessageHandler(
        filters.ALL,  # 捕获所有消息类型
        handle_group_message_for_index,
        block=False  # 非阻塞，不影响其他处理器
    )
    
    # 使用 group=-1 确保最高优先级执行（在所有 handler 之前）
    application.add_handler(handler, group=-1)
    
    logger.info("✅ 群成员索引自动更新处理器已注册 (priority=-1, non-blocking)")

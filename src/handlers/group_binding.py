"""
群组绑定分组命令处理器

功能：
1. 在群组中发送 "绑定分组 <分组名>" 命令
2. 自动查询/创建分组
3. 更新群组的 group_tag 字段
4. 发布事件通知私聊端刷新 UI
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models.database import get_db_session
from ..models.group import Group, GroupTag, DEFAULT_BROADCAST_GROUP_TAG
from ..core.event_bus import event_bus, EventType, Event
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.role_checker import get_user_role, UserRole

logger = logging.getLogger(__name__)


async def handle_bind_group_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群组绑定分组命令
    
    命令格式：绑定分组 <分组名>
    例如：绑定分组 财务组
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 检查是否为群组聊天
    if chat_id > 0:
        await update.message.reply_text(
            "⚠️ 此功能仅在群组中可用\n\n"
            "请在群组中使用此命令。"
        )
        return

    # 获取 bot_id
    bot_id = get_current_bot_id(context)
    
    # 解析命令：绑定分组 <分组名>
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2 or parts[0] != "绑定分组":
        return  # 不是绑定分组命令，跳过
    
    tag_name = parts[1].strip()
    
    if not tag_name:
        await update.message.reply_text("❌ 分组名称不能为空")
        return
    
    if len(tag_name) > 50:
        await update.message.reply_text("❌ 分组名称不能超过50个字符")
        return
    
    logger.info(f"[Bot: {bot_id}] User {user.id} binding group {chat_id} to tag '{tag_name}'")
    
    async with get_db_session() as db:
        try:
            # Step 1: 查询或创建分组
            query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == tag_name,
                    GroupTag.is_active.is_(True)
                )
            )
            result = await db.execute(query)
            group_tag = result.scalar_one_or_none()
            
            if not group_tag:
                # 分组不存在，自动创建
                logger.info(f"[Bot: {bot_id}] Creating new group tag: {tag_name}")
                group_tag = GroupTag(
                    bot_id=bot_id,
                    tag_name=tag_name,
                    created_by=user.id,
                    is_active=True
                )
                db.add(group_tag)
                await db.flush()  # 获取 ID
                
                # 发布分组创建事件
                await event_bus.publish(Event(
                    event_type=EventType.GROUP_TAG_CREATED,
                    data={
                        "bot_id": bot_id,
                        "tag_id": group_tag.id,
                        "tag_name": tag_name,
                        "created_by": user.id
                    },
                    bot_id=bot_id
                ))
            
            # Step 2: 查询或创建群组记录
            query = select(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.group_id == chat_id
                )
            )
            result = await db.execute(query)
            group = result.scalar_one_or_none()
            
            if not group:
                # 群组记录不存在，创建新记录
                logger.info(f"[Bot: {bot_id}] Creating new group record: {chat_id}")
                group = Group(
                    bot_id=bot_id,
                    group_id=chat_id,
                    group_name=update.effective_chat.title or f"Group_{chat_id}",
                    group_tag=tag_name
                )
                db.add(group)
            else:
                # 更新群组的分组标签
                old_tag = group.group_tag
                group.group_tag = tag_name
                logger.info(f"[Bot: {bot_id}] Updated group {chat_id} tag from '{old_tag}' to '{tag_name}'")
            
            await db.commit()
            
            # Step 3: 发布群组绑定事件
            await event_bus.publish(Event(
                event_type=EventType.GROUP_BOUND_TO_TAG,
                data={
                    "bot_id": bot_id,
                    "group_id": chat_id,
                    "group_name": update.effective_chat.title or f"Group_{chat_id}",
                    "tag_name": tag_name,
                    "operator_id": user.id
                },
                bot_id=bot_id
            ))
            
            # Step 4: 回复确认消息
            await update.message.reply_text(
                f"✅ 已将本群组绑定到【{tag_name}】\n\n"
                f"💡 私聊中的「分组管理」将自动同步更新"
            )
            
        except Exception as e:
            await db.rollback()
            logger.error(f"[Bot: {bot_id}] Failed to bind group to tag: {e}", exc_info=True)
            await update.message.reply_text("❌ 绑定分组失败，请稍后重试")


async def handle_unbind_group_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群组解绑分组命令（可选功能）
    
    命令格式：解绑分组
    """
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # 检查是否为群组聊天
    if chat_id > 0:
        await update.message.reply_text(
            "⚠️ 此功能仅在群组中可用\n\n"
            "请在群组中使用此命令。"
        )
        return

    # 获取 bot_id
    bot_id = get_current_bot_id(context)
    
    logger.info(f"[Bot: {bot_id}] User {user.id} unbinding group {chat_id}")
    
    async with get_db_session() as db:
        try:
            # 查询群组记录
            query = select(Group).where(
                and_(
                    Group.bot_id == bot_id,
                    Group.group_id == chat_id
                )
            )
            result = await db.execute(query)
            group = result.scalar_one_or_none()
            
            if not group or not group.group_tag:
                await update.message.reply_text("❌ 本群组未绑定任何分组")
                return
            
            old_tag = group.group_tag
            group.group_tag = None
            await db.commit()
            
            # 发布解绑事件
            await event_bus.publish(Event(
                event_type=EventType.GROUP_UNBOUND_FROM_TAG,
                data={
                    "bot_id": bot_id,
                    "group_id": chat_id,
                    "old_tag_name": old_tag,
                    "operator_id": user.id
                },
                bot_id=bot_id
            ))
            
            await update.message.reply_text(f"✅ 已解除与【{old_tag}】的绑定")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"[Bot: {bot_id}] Failed to unbind group from tag: {e}", exc_info=True)
            await update.message.reply_text("❌ 解绑分组失败，请稍后重试")

"""
分组管理处理器 - ChatOps 模式
"""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from src.models.database import get_db_session
from src.models.group import GroupTag, Group, DEFAULT_BROADCAST_GROUP_TAG
from src.core.event_bus import event_bus, EventType, Event
from src.utils.bot_id_middleware import get_current_bot_id
from src.utils.role_checker import get_user_role, UserRole
import logging

logger = logging.getLogger(__name__)


async def add_group_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    添加分组并绑定当前群组（ChatOps 模式）
    
    权限要求：管理员/操作人/超管/Bot拥有者
    流程：
    1. 解析命令：添加分组 <分组名>
    2. 校验权限
    3. 创建新分组
    4. 自动绑定当前群组
    5. 设置当前群为该分组默认群
    6. 返回成功提示
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

    # ✅ 权限校验：只有管理员/操作人/超管/Bot拥有者可以添加分组
    role = await get_user_role(user.id, bot_id)
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER, UserRole.ADMIN, UserRole.OPERATOR]
    if role not in allowed_roles:
        await update.message.reply_text(
            "❌ 权限不足\n\n"
            "只有管理员或操作人才能添加分组。\n\n"
            f"你的角色：{role.value if hasattr(role, 'value') else role}"
        )
        logger.warning(f"[PERMISSION_DENIED] User {user.id} (role={role}) tried to add group tag")
        return

    text = update.message.text.strip()
    
    # 解析分组名称：添加分组 名字
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ 格式错误\n\n"
            "使用方法：添加分组 名字\n"
            "例如：添加分组 VIP群"
        )
        return
    
    tag_name = parts[1].strip()
    
    if not tag_name:
        await update.message.reply_text("❌ 分组名称不能为空")
        return
    
    # ✅ 禁止创建名为"默认"的分组（系统内置）
    if tag_name == DEFAULT_BROADCAST_GROUP_TAG:
        await update.message.reply_text(
            f"❌ 「{DEFAULT_BROADCAST_GROUP_TAG}」是系统内置分组，不能创建同名分组\n\n"
            f" 提示：所有新群组会自动分配到「{DEFAULT_BROADCAST_GROUP_TAG}」分组"
        )
        return
    
    if len(tag_name) > 50:
        await update.message.reply_text("❌ 分组名称不能超过50个字符")
        return

    async with get_db_session() as db:
        try:
            # 检查是否已存在同名分组（带 bot_id 过滤）
            query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == tag_name,
                    GroupTag.is_active.is_(True)
                )
            )
            result = await db.execute(query)
            existing_tag = result.scalar_one_or_none()
            
            if existing_tag:
                # 分组已存在，直接绑定当前群组
                logger.info(f"[GROUP_TAG] Tag '{tag_name}' already exists, binding group {chat_id}")
                group = await _get_or_create_group(db, bot_id, chat_id, update.effective_chat.title)
                group.group_tag = tag_name
                await db.commit()
                
                # 发布分组绑定事件
                await event_bus.publish(Event(
                    event_type=EventType.GROUP_TAG_UPDATED,
                    data={
                        "bot_id": bot_id,
                        "chat_id": chat_id,
                        "tag_name": tag_name
                    },
                    bot_id=bot_id
                ))
                
                await update.message.reply_text(
                    f"✅ 已将本群组绑定到【{tag_name}】分组\n\n"
                    f"💡 私聊中的「分组管理」将自动同步更新"
                )
                return
            
            # 创建新分组
            logger.info(f"[GROUP_TAG] Creating new tag: {tag_name} for bot {bot_id}")
            new_tag = GroupTag(
                bot_id=bot_id,
                tag_name=tag_name,
                created_by=user.id,
                is_active=True
            )
            
            db.add(new_tag)
            await db.flush()  # 获取 ID
            
            # 将当前群组绑定到新创建的分组
            group = await _get_or_create_group(db, bot_id, chat_id, update.effective_chat.title)
            group.group_tag = tag_name
            
            await db.commit()
            
            # 发布分组创建事件
            await event_bus.publish(Event(
                event_type=EventType.GROUP_TAG_CREATED,
                data={
                    "bot_id": bot_id,
                    "tag_id": new_tag.id,
                    "tag_name": tag_name,
                    "created_by": user.id
                },
                bot_id=bot_id
            ))
            
            await update.message.reply_text(
                f"✅ 已创建分组【{tag_name}】并绑定本群组\n\n"
                f"💡 私聊中的「分组管理」将自动同步更新"
            )
            
        except Exception as e:
            await db.rollback()
            logger.error(f"[GROUP_TAG] Failed to add group tag: {e}", exc_info=True)
            await update.message.reply_text(f"❌ 添加分组失败，请稍后重试\n\n错误信息：{str(e)}")


async def delete_group_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除分组"""
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

    text = update.message.text.strip()
    
    # 解析分组名称：删除分组 名字
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ 格式错误\n\n"
            "使用方法：删除分组 名字\n"
            "例如：删除分组 VIP群"
        )
        return
    
    tag_name = parts[1].strip()
    
    if not tag_name:
        await update.message.reply_text("❌ 分组名称不能为空")
        return
    
    # ✅ 禁止删除“默认”分组（系统内置）
    if tag_name == DEFAULT_BROADCAST_GROUP_TAG:
        await update.message.reply_text(
            f"❌ 不能删除系统内置的「{DEFAULT_BROADCAST_GROUP_TAG}」分组\n\n"
            f"💡 提示：这是新群组的默认归属，无法删除"
        )
        return

    async with get_db_session() as db:
        try:
            # 查找分组（带 bot_id 过滤）
            query = select(GroupTag).where(
                and_(
                    GroupTag.bot_id == bot_id,
                    GroupTag.tag_name == tag_name
                )
            )
            result = await db.execute(query)
            tag = result.scalar_one_or_none()
            
            if not tag:
                await update.message.reply_text(f"❌ 分组「{tag_name}」不存在")
                return
            
            # 删除分组
            await db.delete(tag)
            await db.commit()
            
            # 发布分组删除事件
            await event_bus.publish(Event(
                event_type=EventType.GROUP_TAG_DELETED,
                data={
                    "bot_id": bot_id,
                    "tag_name": tag_name,
                    "deleted_by": user.id
                },
                bot_id=bot_id
            ))
            
            await update.message.reply_text(f"✅ 已删除分组：{tag_name}")
            
        except Exception as e:
            await db.rollback()
            raise


async def list_group_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查看本群绑定的分组（简化版）
    
    只显示当前群组绑定的分组，不显示所有分组列表
    """
    if not update.message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    # 检查是否为群组聊天
    if chat_id > 0:
        await update.message.reply_text(
            "⚠️ 此功能仅在群组中可用\n\n"
            "请在群组中使用此命令。"
        )
        return

    # 获取 bot_id
    bot_id = get_current_bot_id(context)

    async with get_db_session() as db:
        # 查询当前群组的分组信息
        group = await _get_or_create_group(db, bot_id, chat_id, update.effective_chat.title)
        
        # 获取本群绑定的分组
        current_tag = group.group_tag or DEFAULT_BROADCAST_GROUP_TAG
        
        message = (
            f"📋 **本群分组信息**\n\n"
            f"当前绑定分组：<b>【{current_tag}】</b>\n\n"
            f"💡 提示：\n"
            f"• 使用「添加分组 名字」可创建并绑定新分组\n"
        )
        
        await update.message.reply_text(message, parse_mode="HTML")


async def _get_or_create_group(db, bot_id: str, chat_id: int, group_name: str = None) -> Group:
    """
    获取或创建群组记录（辅助函数）
    
    如果群组不存在，则自动创建并设置默认分组
    """
    query = select(Group).where(
        and_(
            Group.bot_id == bot_id,
            Group.group_id == chat_id  # ✅ 修复：使用 group_id 而非 chat_id
        )
    )
    result = await db.execute(query)
    group = result.scalar_one_or_none()
    
    if not group:
        # 自动创建群组记录
        logger.info(f"[GROUP] Creating new group record: {chat_id}")
        group = Group(
            bot_id=bot_id,
            group_id=chat_id,  # ✅ 修复：使用 group_id 字段
            group_name=group_name or f"Group_{chat_id}",
            group_tag=DEFAULT_BROADCAST_GROUP_TAG  # 默认分组
        )
        db.add(group)
        await db.flush()
    
    return group

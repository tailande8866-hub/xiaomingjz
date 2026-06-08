"""
管理员管理功能
用于超级管理员添加/删除管理员
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models import Admin, get_db
from ..repositories.bot_management_repo import BotAdminRepository
from ..utils.role_checker import get_user_role, UserRole
from ..utils.tenant_scope import scoped_query, scoped_insert

logger = logging.getLogger(__name__)


async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    添加管理员
    用法：回复要添加的人的消息，然后发送 "添加管理员"
    """
    user_id = update.effective_user.id
    
    # 获取当前 bot_id
    from ..utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    
    # 检查是否为超级管理员
    user_role = await get_user_role(user_id, bot_id)
    if user_role != UserRole.SUPER_ADMIN:
        await update.message.reply_text(
            "⚠️ 权限不足！只有超级管理员才能添加管理员。",
            parse_mode='HTML'
        )
        return
    
    # 检查是否回复了消息
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ 请回复要添加为管理员的用户消息，然后发送「添加管理员」",
            parse_mode='HTML'
        )
        return
    
    # 获取被回复的用户信息
    replied_user = update.message.reply_to_message.from_user
    target_user_id = replied_user.id
    target_username = replied_user.username
    target_first_name = replied_user.first_name
    target_last_name = replied_user.last_name
    
    # 检查是否已经是管理员
    async for db in get_db():
        try:
            query = scoped_query(Admin, context).where(
                and_(
                    Admin.user_id == target_user_id,
                    Admin.is_active.is_(True)
                )
            )
            result = await db.execute(query)
            existing_admin = result.scalar_one_or_none()
            
            if existing_admin:
                await update.message.reply_text(
                    f"⚠️ 用户 {target_first_name or target_username} 已经是管理员了。",
                    parse_mode='HTML'
                )
                return
            
            # 创建新管理员
            new_admin = Admin(
                bot_id=bot_id,
                user_id=target_user_id,
                username=target_username,
                first_name=target_first_name,
                last_name=target_last_name,
                is_active=True,
                permissions=None,  # 使用默认权限
                added_by=user_id,
                added_by_username=update.effective_user.username,
                note="由超级管理员添加"
            )
            
            db.add(new_admin)
            await db.flush()  # 获取id
            await BotAdminRepository(db).create_or_update_admin(
                bot_id=bot_id,
                user_id=target_user_id,
                role="admin",
                username=target_username,
                first_name=target_first_name,
            )
            
            # 🆕 记录审计日志
            try:
                from ..services.audit_service import audit_service
                await audit_service.log(
                    user_id=user_id,
                    action="admin.add",
                    bot_id=bot_id,
                    username=update.effective_user.username,
                    details={
                        "target_user_id": target_user_id,
                        "target_username": target_username,
                        "target_name": target_first_name
                    },
                    status="success"
                )
            except Exception as e:
                logger.error(f"Failed to log audit: {e}")
            
            await update.message.reply_text(
                f"✅ 成功添加管理员！\n\n"
                f"👤 用户名：{target_first_name or target_username}\n"
                f"🆔 Telegram ID：{target_user_id}\n"
                f"️ 角色：管理员\n\n"
                f"该用户现在可以使用广播、分组广播、关键词回复等功能。",
                parse_mode='HTML'
            )
            
            logger.info(f"Admin {user_id} added new admin {target_user_id}")
            
        except Exception as e:
            logger.error(f"Error adding admin: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ 添加管理员失败：{str(e)}",
                parse_mode='HTML'
            )
        finally:
            break


async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    删除管理员
    用法：回复要删除的人的消息，然后发送 "删除管理员"
    """
    user_id = update.effective_user.id
    
    # 获取当前 bot_id
    from ..utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    
    # 检查是否为超级管理员
    user_role = await get_user_role(user_id, bot_id)
    if user_role != UserRole.SUPER_ADMIN:
        await update.message.reply_text(
            "⚠️ 权限不足！只有超级管理员才能删除管理员。",
            parse_mode='HTML'
        )
        return
    
    # 检查是否回复了消息
    if not update.message.reply_to_message:
        await update.message.reply_text(
            " 请回复要删除的管理员消息，然后发送「删除管理员」",
            parse_mode='HTML'
        )
        return
    
    # 获取被回复的用户信息
    replied_user = update.message.reply_to_message.from_user
    target_user_id = replied_user.id
    
    # 查找并删除管理员
    async for db in get_db():
        try:
            query = scoped_query(Admin, context).where(
                and_(
                    Admin.user_id == target_user_id,
                    Admin.is_active.is_(True)
                )
            )
            result = await db.execute(query)
            admin = result.scalar_one_or_none()
            
            if not admin:
                await update.message.reply_text(
                    f"❌ 用户 {replied_user.first_name or replied_user.username} 不是管理员。",
                    parse_mode='HTML'
                )
                return
            
            # 删除管理员（设置为非活跃）
            admin.is_active = False
            await db.flush()
            
            # 🆕 记录审计日志
            try:
                from ..services.audit_service import audit_service
                await audit_service.log(
                    user_id=user_id,
                    action="admin.remove",
                    bot_id=bot_id,
                    username=update.effective_user.username,
                    details={
                        "target_user_id": target_user_id,
                        "target_username": replied_user.username
                    },
                    status="success"
                )
            except Exception as e:
                logger.error(f"Failed to log audit: {e}")
            
            await update.message.reply_text(
                f"✅ 成功删除管理员！\n\n"
                f"👤 用户名：{replied_user.first_name or replied_user.username}\n"
                f"🆔 Telegram ID：{target_user_id}\n\n"
                f"该用户的管理员权限已被移除。",
                parse_mode='HTML'
            )
            
            logger.info(f"Admin {user_id} removed admin {target_user_id}")
            
        except Exception as e:
            logger.error(f"Error removing admin: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ 删除管理员失败：{str(e)}",
                parse_mode='HTML'
            )
        finally:
            break


async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查看管理员列表
    用法：发送 "查看管理员"
    """
    user_id = update.effective_user.id
    
    # 获取当前 bot_id
    from ..utils.bot_id_middleware import get_current_bot_id
    bot_id = get_current_bot_id(context)
    
    # 检查是否为超级管理员
    user_role = await get_user_role(user_id, bot_id)
    if user_role != UserRole.SUPER_ADMIN:
        await update.message.reply_text(
            "⚠️ 权限不足！只有超级管理员才能查看管理员列表。",
            parse_mode='HTML'
        )
        return
    
    # 查询所有管理员
    async for db in get_db():
        try:
            query = scoped_query(Admin, context).where(Admin.is_active.is_(True))
            result = await db.execute(query)
            admins = result.scalars().all()
            
            if not admins:
                await update.message.reply_text(
                    "📋 当前没有管理员。\n\n请使用「添加管理员」命令添加。",
                    parse_mode='HTML'
                )
                return
            
            # 构建管理员列表消息（简洁版）
            admin_list = f"👥 管理员（{len(admins)}）\n\n"
            
            for admin in admins:
                name = admin.first_name or admin.username or f"ID:{admin.user_id}"
                admin_list += f"{name}｜{admin.user_id}\n"
            
            admin_list += "\n权限：群管理 / 广播 / 日切 / 关键词\n"
            admin_list += "创建机器人：仅超管"
            
            await update.message.reply_text(
                admin_list,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Error listing admins: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ 查看管理员列表失败：{str(e)}",
                parse_mode='HTML'
            )
        finally:
            break

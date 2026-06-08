"""
权限自动继承系统

职责：
1. 从 BotCreation 表读取 super_admin_id
2. 检查 Admin 表中是否已存在该管理员
3. 如果不存在，创建新的管理员记录
4. 授予完整的初始权限（包括创建下级 Bot 的权限，支持无限裂变）
"""
import logging
from sqlalchemy import select, and_

from ..models import BotCreation, Admin, get_db_session

logger = logging.getLogger(__name__)


class PermissionInheritanceSystem:
    """
    权限自动继承系统
    
    确保每个新创建的 Bot 的创建者自动成为超级管理员
    """
    
    async def inherit_permissions(self, bot_id: str, bot_token: str, application_or_bot):
        """
        执行权限继承
        
        Args:
            bot_id: Bot 实例 ID
            bot_token: Bot Token (可能已加密)
            application_or_bot: Telegram Application 或 Bot 实例
        """
        async with get_db_session() as db:
            # Step 1: 查询 Bot 创建记录
            # ✅ 修复:使用 instance_id 而不是 bot_token 查询
            # 因为 bot_token 可能已被加密,导致查询失败
            query = select(BotCreation).where(
                BotCreation.instance_id == bot_id
            )
            result = await db.execute(query)
            bot_creation = result.scalar_one_or_none()
            
            if not bot_creation:
                logger.warning(f"No bot creation record for {bot_id}")
                return
            
            super_admin_id = bot_creation.super_admin_id
            logger.info(f"🔑 Inheriting permissions for admin {super_admin_id} in bot {bot_id}")
            
            # Step 2: 检查是否已存在
            existing_query = select(Admin).where(
                and_(
                    Admin.user_id == super_admin_id,
                    Admin.bot_id == bot_id
                )
            )
            existing_result = await db.execute(existing_query)
            existing_admin = existing_result.scalar_one_or_none()
            
            if existing_admin:
                logger.info(f"✅ Permissions already inherited for admin {super_admin_id}")
                return
            
            # Step 3: 获取用户信息
            try:
                # 支持 Bot 对象或 Application 对象
                bot_obj = application_or_bot.bot if hasattr(application_or_bot, 'bot') else application_or_bot
                user = await bot_obj.get_chat(super_admin_id)
                username = user.username
                first_name = user.first_name
                last_name = user.last_name
            except Exception as e:
                logger.warning(f"Could not fetch user info: {e}")
                username = None
                first_name = None
                last_name = None
            
            # Step 4: 创建管理员记录
            new_admin = Admin(
                user_id=super_admin_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                bot_id=bot_id,  # 租户隔离
                can_create_bot=True,  # ✅ 允许创建下级 Bot（支持无限裂变分销）
                can_manage_admins=True,
                can_manage_group_members=True,
                can_broadcast=True,
                can_set_day_cut=True,
                can_set_keywords=True,
                added_by=super_admin_id,
                added_by_username=username,
                is_active=True,
                note=f"Bot 创建者（自动继承权限）- 层级: {bot_creation.tree_depth}"
            )
            
            db.add(new_admin)
            await db.commit()
            
            logger.info(f"✅ Permissions inherited for admin {super_admin_id} in bot {bot_id}")
            
            # 🆕 发布管理员添加事件
            try:
                from ..core.event_publisher import publish_admin_added
                admin_permissions = {
                    'can_create_bot': True,  # ✅ 支持无限裂变
                    'can_manage_admins': True,
                    'can_manage_group_members': True,
                    'can_broadcast': True,
                    'can_set_day_cut': True,
                    'can_set_keywords': True,
                }
                await publish_admin_added(
                    user_id=super_admin_id,
                    bot_id=bot_id,
                    admin_permissions=admin_permissions
                )
            except Exception as e:
                logger.error(f"Failed to publish admin added event: {e}")


# 全局实例
permission_inheritance_system = PermissionInheritanceSystem()

"""
系统启动引导服务

职责：
1. 初始化系统基础数据
2. 检查并补齐缺失数据
3. 确保系统完整性

使用场景：
- 首次启动
- 数据库重置后
- 数据迁移后
- 系统升级后
"""
import logging
import os
from sqlalchemy import select, and_
from datetime import datetime

from ..models import BotCreation, Admin, get_db_session
from config import config

logger = logging.getLogger(__name__)


class SystemBootstrapService:
    """
    系统启动引导服务
    
    双保险机制：
    1. 启动时补齐基础数据（A 初始化自愈）
    2. 运行时防炸兜底（B Context兜底）
    """

    async def run(self, bot=None):
        """
        执行系统启动引导
        
        Args:
            bot: Telegram Bot 实例（可选）
        """
        logger.info("🚀 System Bootstrap Service starting...")
        
        try:
            # 1. 确保主 Bot 记录存在
            await self.ensure_master_bot(bot)
            
            # 2. 确保超级管理员存在
            await self.ensure_super_admin(bot)
            
            logger.info("✅ System Bootstrap Service completed")
            
        except Exception as e:
            logger.error(f"❌ System Bootstrap Service failed: {e}", exc_info=True)
            # 启动引导失败不阻断启动，让运行时兜底处理
    
    async def ensure_master_bot(self, bot=None) -> BotCreation:
        """
        确保主 Bot 记录存在
        
        Args:
            bot: Telegram Bot 实例（可选）
            
        Returns:
            BotCreation 记录
        """
        bot_id = 'main_bot' if os.environ.get("IS_MAIN_BOT", "true").lower() != "false" else (config.INSTANCE_ID if hasattr(config, 'INSTANCE_ID') and config.INSTANCE_ID else 'main_bot')
        super_admin_id = config.SUPER_ADMIN_ID
        
        async with get_db_session() as db:
            # 查询是否已存在
            query = select(BotCreation).where(BotCreation.instance_id == bot_id)
            result = await db.execute(query)
            bot_creation = result.scalar_one_or_none()
            
            if bot_creation:
                logger.info(f"✅ Master bot record exists: {bot_id}")
                return bot_creation
            
            # 获取 bot 信息
            bot_username = None
            bot_name = None
            if bot:
                try:
                    me = await bot.get_me()
                    bot_username = me.username
                    bot_name = me.first_name
                except Exception as e:
                    logger.warning(f"Could not get bot info: {e}")
            
            # 创建主 Bot 记录
            bot_creation = BotCreation(
                telegram_id=super_admin_id,
                bot_token=config.BOT_TOKEN,
                bot_username=bot_username or config.BOT_USERNAME,
                bot_name=bot_name or "Master Bot",
                instance_id=bot_id,
                instance_dir=None,  # 主 Bot 没有实例目录
                db_path=None,  # 主 Bot 使用默认数据库
                env_path=None,  # 主 Bot 使用默认环境变量
                status="running",
                super_admin_id=super_admin_id,
                config_json=None,
                # 树状结构
                parent_bot_id=None,  # 主 Bot 是根节点
                root_bot_id=None,  # 主 Bot 是根节点
                tree_depth=0,  # 根节点深度为 0
                # 版本信息
                core_version="1.0.0",
                ui_version="1.0.0",
                permission_version="1.0.0",
                # 生命周期
                lifecycle_status="ACTIVE",
                expire_time=None,  # 主 Bot 永不过期
            )
            
            db.add(bot_creation)
            await db.commit()
            
            logger.info(f"✅ Master bot record created: {bot_id}")
            return bot_creation
    
    async def ensure_super_admin(self, bot=None) -> Admin:
        """
        确保超级管理员存在
        
        Args:
            bot: Telegram Bot 实例（可选）
            
        Returns:
            Admin 记录
        """
        bot_id = 'main_bot' if os.environ.get("IS_MAIN_BOT", "true").lower() != "false" else (config.INSTANCE_ID if hasattr(config, 'INSTANCE_ID') and config.INSTANCE_ID else 'main_bot')
        super_admin_id = config.SUPER_ADMIN_ID
        
        async with get_db_session() as db:
            # 查询是否已存在
            query = select(Admin).where(
                and_(
                    Admin.user_id == super_admin_id,
                    Admin.bot_id == bot_id
                )
            )
            result = await db.execute(query)
            admin = result.scalars().first()
            
            if admin:
                logger.info(f"✅ Super admin exists: {super_admin_id}")
                return admin
            
            # 获取用户信息
            username = None
            first_name = None
            last_name = None
            if bot:
                try:
                    user = await bot.get_chat(super_admin_id)
                    username = user.username
                    first_name = user.first_name
                    last_name = user.last_name
                except Exception as e:
                    logger.warning(f"Could not fetch super admin info: {e}")
            
            # 创建超级管理员记录
            admin = Admin(
                bot_id=bot_id,
                user_id=super_admin_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_active=True,
                # 完整权限
                can_create_bot=True,
                can_manage_admins=True,
                can_manage_group_members=True,
                can_broadcast=True,
                can_set_day_cut=True,
                can_set_keywords=True,
                can_billing=True,
                can_query=True,
                can_settings=True,
                can_renew=True,
                added_by=super_admin_id,
                added_by_username=username or "system",
                note="超级管理员（系统自动创建）",
                # 非试用管理员
                is_trial=False,
                group_limit=0,  # 0 表示无限制
                expire_time=None,  # 永不过期
            )
            
            db.add(admin)
            await db.commit()
            
            logger.info(f"✅ Super admin created: {super_admin_id}")
            return admin
    
    async def auto_repair_bot_creation(self, bot_id: str, bot=None) -> BotCreation:
        """
        自动修复 BotCreation 记录（运行时兜底）
        
        Args:
            bot_id: Bot 实例 ID
            bot: Telegram Bot 实例（可选）
            
        Returns:
            BotCreation 记录
        """
        logger.warning(f"🛠️ Auto-repairing bot creation record for: {bot_id}")
        
        # 如果是主 Bot，使用 ensure_master_bot
        if bot_id == 'main_bot':
            return await self.ensure_master_bot(bot)
        
        # 对于子 Bot，创建最小化记录
        async with get_db_session() as db:
            bot_creation = BotCreation(
                telegram_id=0,  # 未知
                bot_token="unknown",
                bot_username=None,
                bot_name=f"Repaired Bot {bot_id}",
                instance_id=bot_id,
                instance_dir=None,
                db_path=None,
                env_path=None,
                status="unknown",
                super_admin_id=config.SUPER_ADMIN_ID,
                config_json=None,
                parent_bot_id=None,
                root_bot_id=bot_id,
                tree_depth=0,
                core_version="1.0.0",
                ui_version="1.0.0",
                permission_version="1.0.0",
                lifecycle_status="ACTIVE",
                expire_time=None,
            )
            
            db.add(bot_creation)
            await db.commit()
            
            logger.info(f"✅ Bot creation record repaired: {bot_id}")
            return bot_creation


# 全局实例
system_bootstrap_service = SystemBootstrapService()

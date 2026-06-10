"""
SaaS自动化售卖服务
实现套餐管理、购买流程、自动创建Bot实例
"""
import os
import json
import shutil
import asyncio
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_

from ..models import PricingPlan, Subscription, BotCreation, get_db_session, get_db
from .bot_instance_manager import bot_instance_manager

logger = logging.getLogger(__name__)


def _safe_json_object(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


class SaaSAutoService:
    """SaaS自动化售卖服务"""
    
    def __init__(self):
        # 🔥 使用新的 instances/ 目录（Docker 数据卷挂载，更新时保留）
        self.base_instances_dir = Path(__file__).parent.parent.parent / "instances"
        # 兼容旧目录（迁移期间）
        self.legacy_instances_dir = Path(__file__).parent.parent.parent / "bot_instances"
    
    async def get_active_plans(self) -> list:
        """获取所有启用的套餐"""
        logger.info("Starting to fetch active plans from database...")
        
        async with get_db_session() as db:
            try:
                query = select(PricingPlan).where(
                    and_(
                        PricingPlan.is_active.is_(True)
                    )
                ).order_by(PricingPlan.display_order)
                result = await db.execute(query)
                plans = result.scalars().all()
                logger.info(f"Found {len(plans)} active plans: {[p.name for p in plans]}")
            except Exception as e:
                logger.error(f"Error getting plans: {e}", exc_info=True)
                plans = []
        
        return plans
    
    async def get_user_subscription(self, telegram_id: int) -> Optional[Subscription]:
        """获取用户订阅信息"""
        logger.info(f"Getting subscription for telegram_id={telegram_id}")
        
        async with get_db_session() as db:
            try:
                query = select(Subscription).where(
                    and_(
                        Subscription.telegram_id == telegram_id,
                        Subscription.status == "active"
                    )
                )
                result = await db.execute(query)
                subscription = result.scalar_one_or_none()
                
                logger.info(f"Found subscription: {subscription}")
                
                # 检查是否过期
                if subscription and subscription.expire_date < datetime.utcnow():
                    logger.warning(f"Subscription expired: {subscription.expire_date} < {datetime.utcnow()}")
                    subscription.status = "expired"
                    await db.commit()
                    return None
                
                logger.info(f"Returning subscription: {subscription}")
                return subscription
            except Exception as e:
                logger.error(f"Error getting subscription: {e}", exc_info=True)
                return None
    
    async def can_create_bot(self, telegram_id: int) -> tuple[bool, str]:
        """检查用户是否可以创建机器人"""
        subscription = await self.get_user_subscription(telegram_id)
        
        if not subscription:
            return False, "您还没有订阅任何套餐，请先购买套餐"
        
        # 检查是否达到机器人数量限制
        async with get_db_session() as db:
            try:
                query = select(PricingPlan).where(PricingPlan.id == subscription.plan_id)
                result = await db.execute(query)
                plan = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Error getting plan: {e}", exc_info=True)
                return False, "查询套餐信息失败"
        
        if not plan:
            return False, "套餐信息错误"
        
        if subscription.bots_created >= plan.max_bots:
            return False, f"您的套餐最多只能创建 {plan.max_bots} 个机器人"
        
        return True, "可以创建"
    
    async def create_bot_instance(
        self,
        telegram_id: int,
        username: str,
        bot_token: str,
        bot_username: str,
        bot_name: str,
        parent_bot_id: Optional[str] = None,  # 🆕 父 Bot ID，支持无限裂变
        order_id: Optional[str] = None,  # 🆕 订单号（用于防重放）
        expire_time: Optional[datetime] = None  # 🆕 套餐到期时间（用于生命周期管理）
    ) -> tuple[bool, str, Optional[BotCreation]]:
        """
        自动创建 Bot 实例（带完整错误处理和回滚机制）
            
        Args:
            telegram_id: 用户 Telegram ID
            username: 用户名
            bot_token: Bot Token
            bot_username: Bot 用户名
            bot_name: Bot 名称
            parent_bot_id: 父 Bot 的 instance_id（可选，None 表示直接由 Master 创建）
            
        Returns:
            (success, message, bot_creation)
        """
        import uuid
        instance_id = None
        instance_dir = None
        
        try:
            # ✅ 新增：订单防重放检查（如果提供了 order_id）
            if order_id:
                async for db in get_db():
                    try:
                        query = select(BotCreation).where(BotCreation.order_id == order_id)
                        result = await db.execute(query)
                        existing_order_bot = result.scalar_one_or_none()
                        
                        if existing_order_bot:
                            logger.warning(f"🔒 Order {order_id} already used by bot {existing_order_bot.instance_id}")
                            return False, f"❌ 订单已使用\n\n该订单号已用于创建 Bot @{existing_order_bot.bot_username}\n请勿重复提交订单", None
                        break
                    except Exception as e:
                        logger.error(f"Error checking order: {e}")
                        return False, f"订单验证失败：{str(e)}", None
            
            # ✅ 新增：验证 Token 并获取 Bot 信息
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://api.telegram.org/bot{bot_token}/getMe",
                        timeout=10
                    )
                    result = response.json()
                    
                    if not result.get('ok'):
                        error_msg = result.get('description', 'Unknown error')
                        logger.error(f"Token verification failed: {error_msg}")
                        return False, f"❌ Token 校验失败：{error_msg}\n\n请检查 Token 是否正确，或重新从 @BotFather 获取。", None
                    
                    bot_info = result.get('result', {})
                    verified_bot_id = bot_info.get('id')
                    verified_username = bot_info.get('username')
                    verified_first_name = bot_info.get('first_name', '')
                    
                    logger.info(f"✅ Token valid: @{verified_username} (ID: {verified_bot_id})")
                    
                    # ✅ 关键修复：如果用户输入的 username 与 Token 对应的实际 username 不一致，使用实际的
                    if verified_username != bot_username:
                        logger.warning(f"Username mismatch: input={bot_username}, actual={verified_username}")
                        bot_username = verified_username
                        bot_name = verified_first_name or verified_username
                        
            except Exception as e:
                logger.exception(f"TOKEN VERIFY FAILED: {e}")
                return False, f"❌ Token 校验失败：{str(e)}\n\n请检查网络连接或稍后重试。", None
            
            # 1. 检查是否已存在相同username的Bot
            async for db in get_db():
                try:
                    query = select(BotCreation).where(BotCreation.bot_username == bot_username)
                    result = await db.execute(query)
                    existing = result.scalar_one_or_none()
                    
                    # ✅ 修复：如果Bot已存在，允许重新生成Token后更新记录
                    if existing:
                        logger.info(f"Bot @{bot_username} already exists, updating token and restarting")
                        # 如果存在，更新 Token 和状态
                        # ✅ 关键修复：existing 已在当前会话中，可以直接使用
                        from ..utils.token_encryptor import token_encryptor
                        existing.telegram_id = telegram_id
                        existing.super_admin_id = telegram_id
                        existing.bot_name = bot_name
                        existing.bot_username = bot_username
                        existing.bot_token = token_encryptor.encrypt_to_base64(bot_token)
                        existing.status = 'running'
                        existing.status_message = 'Token updated'
                        existing.token_status = 'normal'
                        existing.token_invalid_reason = None
                        existing.lifecycle_status = 'ACTIVE'
                        existing.rebind_status = 'none'
                        existing.rebind_user_id = None
                        existing.rebind_started_at = None
                        existing.config_json = json.dumps({
                            **_safe_json_object(existing.config_json),
                            "owner_user_id": telegram_id,
                            "bot_username": bot_username,
                            "bot_name": bot_name,
                        })
                        existing.updated_at = datetime.now()
                        from ..repositories.bot_management_repo import BotAdminRepository
                        await BotAdminRepository(db).create_or_update_admin(
                            bot_id=existing.instance_id,
                            user_id=telegram_id,
                            role="owner",
                            username=username,
                            first_name=username,
                        )
                        await db.commit()
                        await db.refresh(existing)
                        
                        # ✅ 关键修复：同步更新 .env 文件
                        try:
                            if existing.instance_dir:
                                env_path = Path(existing.instance_dir) / ".env"
                                if env_path.exists():
                                    # 生成新的 .env 文件内容
                                    env_content = self._generate_env_file(
                                        bot_token=bot_token,
                                        bot_username=bot_username,
                                        telegram_id=telegram_id,
                                        instance_id=existing.instance_id
                                    )
                                    env_path.write_text(env_content, encoding="utf-8")
                                    logger.info(f"✅ Updated .env file for {existing.instance_id}")
                                else:
                                    logger.warning(f".env file not found: {env_path}")
                        except Exception as e:
                            logger.error(f"Failed to update .env file: {e}")
                        
                        # 重启 Bot 实例
                        try:
                            if existing.instance_id and self.is_bot_running(existing.instance_id):
                                # 先停止旧实例
                                await self.stop_bot_instance(existing.instance_id)
                            
                            # 启动新实例（使用新 Token）
                            await self.start_bot_instance(
                                instance_id=existing.instance_id,
                                telegram_id=telegram_id,
                                bot_username=bot_username,
                                bot_name=bot_name,
                                bot_token=bot_token,
                                parent_bot_id=parent_bot_id
                            )
                            
                            message = f"✅ Bot @{bot_username} Token 已更新并重启"
                            return True, message, existing
                        except Exception as e:
                            logger.error(f"Failed to restart bot after token update: {e}")
                            message = f"⚠️ Token 已更新，但重启失败：{str(e)}"
                            return True, message, existing
                    else:
                        # Bot 不存在，继续创建新实例流程
                        break
                except Exception as e:
                    logger.error(f"Error checking existing bot: {e}", exc_info=True)
                    return False, f"检查 Bot 失败：{str(e)}", None
            
            # 2. 生成实例ID
            instance_id = f"bot_{uuid.uuid4().hex[:8]}"
            
            # 3. 创建实例目录（带冲突检测）
            instance_dir = self.base_instances_dir / instance_id
            max_retries = 5
            retry_count = 0
            
            while instance_dir.exists() and retry_count < max_retries:
                # 如果目录已存在，重新生成ID
                instance_id = f"bot_{uuid.uuid4().hex[:8]}"
                instance_dir = self.base_instances_dir / instance_id
                retry_count += 1
            
            if retry_count >= max_retries:
                return False, "实例ID生成失败，请稍后重试", None
            
            instance_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created instance directory: {instance_dir}")
            
            # 4. 创建基本文件（不使用模板复制）
            try:
                # ✅ 关键修复：直接创建 start.py，不依赖模板目录
                await self._create_basic_files(instance_dir)
                logger.info(f"Created basic files in {instance_dir}")
            except Exception as e:
                logger.error(f"Error copying template: {e}", exc_info=True)
                # 回滚：删除已创建的目录
                if instance_dir and instance_dir.exists():
                    shutil.rmtree(instance_dir, ignore_errors=True)
                    logger.info(f"Rolled back: deleted {instance_dir}")
                return False, f"复制模板文件失败: {str(e)}", None
            
            # 5. 生成.env文件
            try:
                env_content = self._generate_env_file(bot_token, bot_username, telegram_id, instance_id)
                env_path = instance_dir / ".env"
                env_path.write_text(env_content, encoding="utf-8")
                logger.info(f"Generated .env file: {env_path}")
            except Exception as e:
                logger.error(f"Error generating .env: {e}", exc_info=True)
                # 回滚
                if instance_dir and instance_dir.exists():
                    shutil.rmtree(instance_dir, ignore_errors=True)
                return False, f"生成配置文件失败: {str(e)}", None
            
            # 6. 创建start.py
            try:
                start_content = self._generate_start_file(instance_id, bot_token)
                start_path = instance_dir / "start.py"
                start_path.write_text(start_content, encoding="utf-8")
                logger.info(f"Generated start.py: {start_path}")
            except Exception as e:
                logger.error(f"Error generating start.py: {e}", exc_info=True)
                # 回滚
                if instance_dir and instance_dir.exists():
                    shutil.rmtree(instance_dir, ignore_errors=True)
                return False, f"生成启动脚本失败: {str(e)}", None
            
            # 7. 数据库路径
            db_path = instance_dir / f"{instance_id}.db"
            
            # 🆕 8. 确定树状结构信息
            if parent_bot_id:
                # 子 Bot 创建：继承父 Bot 的 root_bot_id
                async for db in get_db():
                    try:
                        query = select(BotCreation).where(BotCreation.instance_id == parent_bot_id)
                        result = await db.execute(query)
                        parent_bot = result.scalar_one_or_none()
                        
                        if not parent_bot:
                            logger.warning(f"Parent bot {parent_bot_id} not found, creating as root bot")
                            root_bot_id = instance_id
                            tree_depth = 0
                        else:
                            root_bot_id = parent_bot.root_bot_id or parent_bot_id
                            tree_depth = parent_bot.tree_depth + 1
                            logger.info(f"🌳 Creating child bot at depth {tree_depth}")
                        break
                    except Exception as e:
                        logger.error(f"Error querying parent bot: {e}")
                        root_bot_id = instance_id
                        tree_depth = 0
            else:
                # 直接由 Master 创建
                root_bot_id = instance_id
                tree_depth = 0
                logger.info(f"🌱 Creating root-level bot")
            
            # 9. 🆕 加密 Bot Token
            try:
                from ..utils.token_encryptor import token_encryptor
                encrypted_token = token_encryptor.encrypt_to_base64(bot_token)
                logger.info(f"Bot token encrypted for {instance_id}")
            except Exception as e:
                logger.error(f"Failed to encrypt bot token: {e}", exc_info=True)
                # 回滚
                if instance_dir and instance_dir.exists():
                    shutil.rmtree(instance_dir, ignore_errors=True)
                return False, f"Token 加密失败: {str(e)}", None
            
            # 10. 保存到数据库
            from ..models.saas_auto import BotLifecycleStatus
            
            bot_creation = BotCreation(
                telegram_id=telegram_id,
                bot_token=encrypted_token,  # 🆕 保存加密后的 Token
                bot_username=bot_username,
                bot_name=bot_name,
                instance_id=instance_id,
                instance_dir=str(instance_dir),
                db_path=str(db_path),
                env_path=str(env_path),
                status="creating",
                super_admin_id=telegram_id,  # 用户自己就是超级管理员
                parent_bot_id=parent_bot_id,  # 🆕
                root_bot_id=root_bot_id,      # 🆕
                tree_depth=tree_depth,        # 🆕
                core_version="1.0.0",         # 🆕
                ui_version="1.0.0",           # 🆕
                permission_version="1.0.0",   # 🆕
                order_id=order_id,  # 🆕 订单号（防重放）
                lifecycle_status=BotLifecycleStatus.ACTIVE,  # 🆕 生命周期状态
                expire_time=expire_time,  # 🆕 套餐到期时间
                last_activity_at=datetime.utcnow(),  # 🆕 最后活动时间
                config_json=json.dumps({
                    "owner_user_id": telegram_id,
                    "bot_username": bot_username,
                    "bot_name": bot_name,
                    "created_by": username,
                    "parent_bot_id": parent_bot_id,
                    "root_bot_id": root_bot_id,
                    "tree_depth": tree_depth
                })
            )
            
            # ✅ 关键修复：使用 get_db() 生成器替代 get_db_session()
            # 初始化返回值
            result_tuple = (False, "未知错误", None)
            
            async for db in get_db():
                try:
                    db.add(bot_creation)
                    await db.flush()  # 获取ID
                    from ..repositories.bot_management_repo import BotAdminRepository
                    await BotAdminRepository(db).create_or_update_admin(
                        bot_id=instance_id,
                        user_id=telegram_id,
                        role="owner",
                        username=username,
                        first_name=username,
                    )
                    await db.commit()  # ✅ 先提交到数据库
                    await db.refresh(bot_creation)  # ✅ 刷新对象获取最新状态
                    logger.info(f"Saved bot creation record to database: {instance_id}")
                    
                    # ✅ 启动前再次验证数据库记录存在
                    # select 已在文件顶部导入（第14行）
                    verify_query = select(BotCreation).where(BotCreation.instance_id == instance_id)
                    verify_result = await db.execute(verify_query)
                    if not verify_result.scalar_one_or_none():
                        raise Exception("Bot creation record not found in database after commit")
                    
                    # 9. 启动Bot（使用新的实例管理器）
                    try:
                        success = await bot_instance_manager.start_bot_instance(bot_creation)
                        
                        if not success:
                            bot_creation.status = "error"
                            await db.commit()

                            # 回滚：删除目录和数据库记录
                            if instance_dir and instance_dir.exists():
                                shutil.rmtree(instance_dir, ignore_errors=True)

                            # 删除数据库记录
                            await db.delete(bot_creation)
                            await db.commit()

                            result_tuple = (False, "Bot启动失败", None)
                            return result_tuple

                        # 验证Bot是否成功启动（等待3秒）
                        await asyncio.sleep(3)
                        
                        # 检查进程是否还在运行
                        health = await bot_instance_manager.check_health(instance_id)
                        
                        if health['is_healthy']:
                            bot_creation.status = "running"
                            bot_creation.started_at = datetime.utcnow()
                            logger.info(f"Bot {instance_id} started successfully")
                            
                            # 🆕 记录审计日志
                            try:
                                from ..services.audit_service import audit_service
                                await audit_service.log(
                                    user_id=telegram_id,
                                    action="bot.create",
                                    bot_id=instance_id,
                                    username=username,
                                    details={
                                        "bot_username": bot_username,
                                        "bot_name": bot_name,
                                        "parent_bot_id": parent_bot_id,
                                        "root_bot_id": root_bot_id
                                    },
                                    status="success"
                                )
                            except Exception as e:
                                logger.error(f"Failed to log audit: {e}")
                            
                            # 🆕 发布 Bot 创建和启动事件
                            try:
                                from ..core.event_publisher import publish_bot_created, publish_bot_started
                                await publish_bot_created(
                                    bot_id=instance_id,
                                    root_bot_id=root_bot_id,
                                    owner_id=telegram_id,
                                    instance_dir=str(instance_dir)
                                )
                                await publish_bot_started(
                                    bot_id=instance_id,
                                    root_bot_id=root_bot_id
                                )
                            except Exception as e:
                                logger.error(f"Failed to publish bot events: {e}")
                        else:
                            bot_creation.status = "error"
                            logger.error(f"Bot {instance_id} health check failed: {health['message']}")
                            await db.commit()
                            result_tuple = (False, f"Bot启动后健康检查失败: {health['message']}", None)
                            return result_tuple
                        
                        await db.commit()
                        
                        # ✅ 10. 更新订阅统计
                        await self._update_subscription_stats(telegram_id)
                        
                        result_tuple = (True, "机器人创建成功！", bot_creation)
                        
                    except Exception as e:
                        logger.error(f"Error starting bot: {e}", exc_info=True)
                        bot_creation.status = "error"
                        await db.commit()
                        
                        # 回滚：删除目录和数据库记录
                        if instance_dir and instance_dir.exists():
                            shutil.rmtree(instance_dir, ignore_errors=True)
                        
                        # 删除数据库记录
                        await db.delete(bot_creation)
                        await db.commit()
                        
                        result_tuple = (False, f"Bot启动失败: {str(e)}", None)
                    
                except Exception as e:
                    logger.error(f"Error saving bot creation: {e}", exc_info=True)
                    await db.rollback()
                    result_tuple = (False, f"保存数据库失败: {str(e)}", None)
            
            return result_tuple
        
        except Exception as e:
            logger.error(f"Error creating bot instance: {e}", exc_info=True)
            
            # 最终回滚：确保清理所有资源
            if instance_dir and instance_dir.exists():
                try:
                    shutil.rmtree(instance_dir, ignore_errors=True)
                    logger.info(f"Final rollback: deleted {instance_dir}")
                except Exception as cleanup_error:
                    logger.error(f"Error during cleanup: {cleanup_error}")
            
            return False, f"创建失败: {str(e)}", None
    
    async def _create_basic_files(self, instance_dir: Path):
        """创建基本文件（当模板不存在时）"""
        # 创建start.py
        start_content = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"
子机器人启动脚本 - 模板
此文件会被复制到新创建的Bot实例中
\"\"\"
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 获取当前脚本所在目录（即实例目录）
instance_dir = Path(__file__).parent

# 加载实例目录下的 .env 文件
env_file = instance_dir / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)

# ✅ 关键修复：子机器人必须使用绝对路径访问主数据库
# 这样所有子机器人都能访问 BotCreation 表进行健康检查
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///app/data/accounting_bot.db"

# 添加父目录到路径（项目根目录）
sys.path.insert(0, str(parent_dir))

# 切换工作目录到实例目录
os.chdir(str(instance_dir))

# 导入并运行机器人
from src.bot import main

if __name__ == "__main__":
    main()
"""
        (instance_dir / "start.py").write_text(start_content, encoding="utf-8")
    
    def _generate_env_file(self, bot_token: str, bot_username: str, telegram_id: int, instance_id: str) -> str:
        """生成.env文件内容 → 统一调用 EnvGenerator"""
        from .env_generator import generate_env_content
        return generate_env_content(
            bot_token=bot_token,
            instance_id=instance_id,
            bot_owner_id=telegram_id,
            bot_username=bot_username,
        )
    
    def _generate_start_file(self, instance_id: str, bot_token: str) -> str:
        """生成start.py内容"""
        # 使用单引号避免与 docstring 冲突
        docstring = '"""子机器人启动脚本 - {instance_id}"""'
        return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
{docstring.format(instance_id=instance_id)}
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 获取当前脚本所在目录（即实例目录）
instance_dir = Path(__file__).parent

# 加载实例目录下的 .env 文件
env_file = instance_dir / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)

# 关键修复：如果没有 .env 文件，从目录名读取 INSTANCE_ID
if not os.environ.get("INSTANCE_ID"):
    # 从实例目录名获取 instance_id
    instance_id_from_dir = instance_dir.name
    if instance_id_from_dir.startswith("bot_"):
        os.environ["INSTANCE_ID"] = instance_id_from_dir
        print(f"Set INSTANCE_ID from directory name: {{instance_id_from_dir}}")

# 关键修复：子机器人必须使用父目录的主数据库
# 这样所有子机器人都能访问 BotCreation 表进行健康检查
# instance_dir = bot_instances/bot_xxx
# parent_dir = bot_instances
# project_root = 项目根目录 (AAAJIZHANG-main)
parent_dir = instance_dir.parent
project_root = parent_dir.parent  # 再往上一级才是项目根目录

def _sqlite_url_path_exists(database_url: str) -> bool:
    if not database_url.startswith("sqlite"):
        return True
    raw_path = database_url.split("///", 1)[-1]
    return Path(raw_path).exists()

configured_db_url = os.environ.get("SHARED_DATABASE_URL") or os.environ.get("DATABASE_URL")
if configured_db_url and _sqlite_url_path_exists(configured_db_url):
    shared_db_url = configured_db_url
else:
    test_db_path = project_root / "accounting_bot_test.db"
    main_db_path = project_root / "accounting_bot.db"
    shared_db_path = test_db_path if test_db_path.exists() else main_db_path
    shared_db_url = f"sqlite+aiosqlite:///{{shared_db_path}}"

os.environ["DATABASE_URL"] = shared_db_url
os.environ["SHARED_DATABASE_URL"] = shared_db_url

# 添加项目根目录到路径
sys.path.insert(0, str(project_root))

# 切换工作目录到实例目录
os.chdir(str(instance_dir))

# 导入并运行机器人
from src.bot import main

if __name__ == "__main__":
    main()
'''

    async def _update_subscription_stats(self, telegram_id: int):
        """更新订阅统计"""
        async for db in get_db():
            try:
                query = select(Subscription).where(Subscription.telegram_id == telegram_id)
                result = await db.execute(query)
                subscription = result.scalar_one_or_none()
                
                if subscription:
                    subscription.bots_created += 1
                    await db.flush()
            except Exception as e:
                logger.error(f"Error updating subscription stats: {e}", exc_info=True)
    
    async def get_user_bots(self, telegram_id: int) -> list:
        """获取用户创建的所有机器人"""
        bots = []  # ✅ 初始化返回值
        
        async for db in get_db():
            try:
                from .account_status_service import account_status_service
                return await account_status_service.get_owned_bots(telegram_id, db)
            except Exception as e:
                logger.error(f"Error getting user bots: {e}", exc_info=True)
                return []
        
        return bots  # ✅ 统一在循环外返回
    
    def is_bot_running(self, instance_id: str) -> bool:
        """检查 Bot 是否正在运行"""
        import psutil
        try:
            for proc in psutil.process_iter(['pid', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and any(instance_id in str(arg) for arg in cmdline):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        except Exception as e:
            logger.error(f"Error checking bot status: {e}")
            return False
    
    async def stop_bot_instance(self, instance_id: str) -> bool:
        """停止 Bot 实例"""
        try:
            return await bot_instance_manager.stop_bot_instance(instance_id)
        except Exception as e:
            logger.error(f"Error stopping bot {instance_id}: {e}")
            return False
    
    async def start_bot_instance(
        self,
        instance_id: str,
        telegram_id: int,
        bot_username: str,
        bot_name: str,
        bot_token: str,
        parent_bot_id: Optional[str] = None
    ) -> bool:
        """启动 Bot 实例"""
        try:
            # 从数据库查询 BotCreation 记录
            async for db in get_db():
                query = select(BotCreation).where(BotCreation.instance_id == instance_id)
                result = await db.execute(query)
                bot_creation = result.scalar_one_or_none()
                
                if not bot_creation:
                    logger.error(f"Bot creation record not found: {instance_id}")
                    return False
                
                # 更新 Token（如果不同）
                if bot_creation.bot_token != bot_token:
                    from ..utils.token_encryptor import token_encryptor
                    bot_creation.bot_token = token_encryptor.encrypt_to_base64(bot_token)
                    await db.commit()
                
                break
            
            # 使用 bot_instance_manager 启动
            return await bot_instance_manager.start_bot_instance(bot_creation)
        except Exception as e:
            logger.error(f"Error starting bot {instance_id}: {e}", exc_info=True)
            return False


# 全局服务实例
saas_auto_service = SaaSAutoService()

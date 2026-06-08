"""
子 Bot 自动初始化引擎

职责：
1. 验证 Token 有效性
2. 生成唯一 instance_id
3. 创建实例目录结构
4. 生成 .env 配置文件
5. 复制启动脚本
6. 初始化数据库表结构
7. 启动 Bot 进程并监控
8. 注册到树状结构
"""
import os
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from telegram import Bot
from sqlalchemy import select

from ..models import BotCreation, PricingPlan, get_db_session
from ..services.bot_instance_manager import bot_instance_manager
from ..utils.database_url import get_shared_database_path, get_shared_database_url

logger = logging.getLogger(__name__)


class BotInitializationEngine:
    """
    子 Bot 自动初始化引擎
    
    支持无限裂变：每个 Bot 都可以创建子 Bot，形成树状结构
    """
    
    # ⚠️ ENV_TEMPLATE 已废弃，统一使用 env_generator.EnvGenerator
    # 保留此属性仅为向后兼容，实际生成逻辑已迁移到 env_generator.py
    ENV_TEMPLATE = None
    
    async def initialize_bot(
        self, 
        creator_telegram_id: int, 
        bot_token: str, 
        plan: PricingPlan,
        parent_bot_id: Optional[str] = None
    ) -> BotCreation:
        """
        完整的 Bot 初始化流程
        
        Args:
            creator_telegram_id: 创建者 Telegram ID
            bot_token: Bot Token
            plan: 购买的套餐
            parent_bot_id: 父 Bot 的 instance_id（可选，None 表示直接由 Master 创建）
            
        Returns:
            BotCreation 记录
        """
        logger.info(f"🚀 Starting bot initialization for user {creator_telegram_id}")
        
        try:
            # Step 1: 验证 Token
            bot_info = await self._validate_token(bot_token)
            logger.info(f"✅ Token validated: @{bot_info.username}")
            
            # Step 2: 生成 instance_id
            instance_id = self._generate_instance_id(bot_token)
            
            # Step 3: 确定树状结构信息
            if parent_bot_id:
                # 🆕 子 Bot 创建：继承父 Bot 的 root_bot_id
                parent_bot = await self._get_bot_creation(parent_bot_id)
                if not parent_bot:
                    raise ValueError(f"Parent bot {parent_bot_id} not found")
                
                root_bot_id = parent_bot.root_bot_id or parent_bot_id
                tree_depth = parent_bot.tree_depth + 1
                logger.info(f"🌳 Creating child bot at depth {tree_depth}")
            else:
                # 直接由 Master 创建
                root_bot_id = instance_id
                tree_depth = 0
                logger.info(f"🌱 Creating root-level bot")
            
            # Step 4: 创建目录结构
            instance_dir = await self._create_instance_directory(instance_id)
            
            # Step 5: 生成配置文件
            shared_db_path = get_shared_database_path()
            db_path = str(shared_db_path) if shared_db_path else str(Path(instance_dir) / "data" / "accounting_bot.db")
            await self._generate_env_file(
                instance_dir, 
                bot_token, 
                instance_id,
                creator_telegram_id,
                db_path,
                parent_bot_id,
                root_bot_id,
                tree_depth
            )
            
            # Step 6: 复制启动脚本
            await self._copy_start_script(instance_dir)
            
            # Step 7: 初始化数据库
            await self._init_database(db_path)
            
            # Step 8: 创建 BotCreation 记录
            bot_creation = await self._create_bot_record(
                telegram_id=creator_telegram_id,
                bot_token=bot_token,
                bot_username=bot_info.username,
                instance_id=instance_id,
                instance_dir=str(instance_dir),
                db_path=db_path,
                parent_bot_id=parent_bot_id,
                root_bot_id=root_bot_id,
                tree_depth=tree_depth,
                plan=plan
            )
            
            # Step 9: 启动 Bot 进程
            success = await bot_instance_manager.start_bot_instance(bot_creation)
            
            if not success:
                raise Exception("Failed to start bot process")
            
            logger.info(f"✅ Bot {instance_id} initialized successfully (depth={tree_depth})")
            return bot_creation
            
        except Exception as e:
            logger.error(f"❌ Bot initialization failed: {e}", exc_info=True)
            raise
    
    async def _validate_token(self, bot_token: str):
        """验证 Bot Token 是否有效"""
        try:
            temp_bot = Bot(bot_token)
            bot_info = await temp_bot.get_me()
            logger.info(f"✅ Token valid: @{bot_info.username} (ID: {bot_info.id})")
            return bot_info
        except Exception as e:
            raise ValueError(f"Invalid bot token: {e}")
    
    def _generate_instance_id(self, bot_token: str) -> str:
        """
        生成唯一的 instance_id
        
        使用 bot_token 的哈希值作为 instance_id，确保唯一性
        """
        hash_value = hashlib.md5(bot_token.encode()).hexdigest()[:8]
        return f"bot_{hash_value}"
    
    async def _get_bot_creation(self, instance_id: str) -> Optional[BotCreation]:
        """获取 Bot 创建记录"""
        async with get_db_session() as db:
            query = select(BotCreation).where(BotCreation.instance_id == instance_id)
            result = await db.execute(query)
            return result.scalar_one_or_none()
    
    async def _create_instance_directory(self, instance_id: str) -> Path:
        """创建实例目录结构"""
        base_dir = Path("bot_instances") / instance_id
        data_dir = base_dir / "data"
        
        # 创建目录
        base_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📁 Created instance directory: {base_dir}")
        return base_dir
    
    async def _generate_env_file(
        self,
        instance_dir: Path,
        bot_token: str,
        instance_id: str,
        telegram_id: int,
        db_path: str,
        parent_bot_id: Optional[str],
        root_bot_id: str,
        tree_depth: int
    ):
        """生成 .env 配置文件 → 统一调用 EnvGenerator"""
        from .env_generator import ensure_env_file
        await ensure_env_file(
            instance_dir=str(instance_dir),
            bot_token=bot_token,
            instance_id=instance_id,
            bot_owner_id=telegram_id,
            database_url=get_shared_database_url(),
        )
    
    async def _copy_start_script(self, instance_dir: Path):
        """复制启动脚本"""
        template_script = Path("bot_instances/template_bot/start.py")
        
        if not template_script.exists():
            raise FileNotFoundError(f"Template start script not found: {template_script}")
        
        target_script = instance_dir / "start.py"
        
        # 读取模板内容
        with open(template_script, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 写入目标文件
        with open(target_script, "w", encoding="utf-8") as f:
            f.write(content)
        
        logger.info(f"📄 Copied start script: {target_script}")
    
    async def _init_database(self, db_path: str):
        """
        初始化数据库表结构
        
        注意：这里不需要实际创建表，因为 Bot 启动时会自动执行 init_db()
        只需要确保数据库文件存在即可
        """
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 创建空的数据库文件
        if not db_file.exists():
            db_file.touch()
            logger.info(f"🗄️ Created empty database: {db_path}")
    
    async def _create_bot_record(
        self,
        telegram_id: int,
        bot_token: str,
        bot_username: str,
        instance_id: str,
        instance_dir: str,
        db_path: str,
        parent_bot_id: Optional[str],
        root_bot_id: str,
        tree_depth: int,
        plan: PricingPlan
    ) -> BotCreation:
        """创建 BotCreation 数据库记录"""
        # 生成配置快照
        config_snapshot = json.dumps({
            "plan_id": plan.id,
            "plan_name": plan.name,
            "max_bots": plan.max_bots,
            "max_groups_per_bot": plan.max_groups_per_bot,
            "created_at": datetime.utcnow().isoformat()
        })
        
        bot_creation = BotCreation(
            telegram_id=telegram_id,
            bot_token=bot_token,
            bot_username=bot_username,
            instance_id=instance_id,
            instance_dir=instance_dir,
            db_path=db_path,
            env_path=str(Path(instance_dir) / ".env"),
            status="creating",
            super_admin_id=telegram_id,
            parent_bot_id=parent_bot_id,
            root_bot_id=root_bot_id,
            tree_depth=tree_depth,
            core_version="1.0.0",
            ui_version="1.0.0",
            permission_version="1.0.0",
            config_snapshot=config_snapshot,
            created_at=datetime.utcnow()
        )
        
        async with get_db_session() as db:
            db.add(bot_creation)
            await db.commit()
            await db.refresh(bot_creation)
        
        logger.info(f"💾 Created BotCreation record: {instance_id}")
        return bot_creation


# 全局实例
bot_initialization_engine = BotInitializationEngine()

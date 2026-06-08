"""
机器人状态管理 Repository
"""
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, desc

from ..models.bot_management import BotOperationLog, BotAdmin
from ..models.saas_auto import BotCreation

logger = logging.getLogger(__name__)


class BotOperationLogRepository:
    """机器人操作日志 Repository"""

    def __init__(self, db_session):
        self.db = db_session

    async def create_log(self, bot_id: str, operator_user_id: int, action: str,
                         status: str, message: str = None,
                         old_value: dict = None, new_value: dict = None) -> BotOperationLog:
        """创建操作日志"""
        log = BotOperationLog(
            bot_id=bot_id,
            operator_user_id=operator_user_id,
            action=action,
            status=status,
            message=message,
            old_value=json.dumps(old_value) if old_value else None,
            new_value=json.dumps(new_value) if new_value else None,
            created_at=datetime.utcnow()
        )
        self.db.add(log)
        await self.db.commit()
        return log

    async def get_logs_by_bot(self, bot_id: str, limit: int = 50) -> List[BotOperationLog]:
        """获取Bot的操作日志"""
        query = select(BotOperationLog).where(
            BotOperationLog.bot_id == bot_id
        ).order_by(desc(BotOperationLog.created_at)).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()


class BotAdminRepository:
    """Bot管理员 Repository"""

    def __init__(self, db_session):
        self.db = db_session

    async def get_owner(self, bot_id: str) -> Optional[BotAdmin]:
        """获取Bot的所有者"""
        query = select(BotAdmin).where(
            and_(
                BotAdmin.bot_id == bot_id,
                BotAdmin.role == "owner",
                BotAdmin.is_active.is_(True)
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_admins(self, bot_id: str, exclude_owner: bool = False) -> List[BotAdmin]:
        """获取Bot的所有管理员"""
        conditions = [
            BotAdmin.bot_id == bot_id,
            BotAdmin.is_active.is_(True)
        ]
        if exclude_owner:
            conditions.append(BotAdmin.role != "owner")

        query = select(BotAdmin).where(and_(*conditions))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_admin_by_user_id(self, bot_id: str, user_id: int) -> Optional[BotAdmin]:
        """根据用户ID获取管理员"""
        query = select(BotAdmin).where(
            and_(
                BotAdmin.bot_id == bot_id,
                BotAdmin.user_id == user_id,
                BotAdmin.is_active.is_(True)
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_or_update_admin(self, bot_id: str, user_id: int, role: str,
                                     username: str = None, first_name: str = None) -> BotAdmin:
        """创建或更新管理员"""
        existing = await self.get_admin_by_user_id(bot_id, user_id)
        if existing:
            existing.role = role
            existing.username = username
            existing.first_name = first_name
            existing.updated_at = datetime.utcnow()
            await self.db.commit()
            return existing

        admin = BotAdmin(
            bot_id=bot_id,
            user_id=user_id,
            role=role,
            username=username,
            first_name=first_name,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        self.db.add(admin)
        await self.db.commit()
        return admin

    async def transfer_ownership(self, bot_id: str, old_owner_id: int, new_owner_id: int) -> bool:
        """转移所有权"""
        try:
            # 1. 旧owner降级为admin
            old_owner = await self.get_admin_by_user_id(bot_id, old_owner_id)
            if old_owner:
                old_owner.role = "admin"
                old_owner.updated_at = datetime.utcnow()
            elif old_owner_id:
                await self.create_or_update_admin(bot_id, old_owner_id, "admin")

            # 2. 新owner升级
            new_owner = await self.get_admin_by_user_id(bot_id, new_owner_id)
            if new_owner:
                new_owner.role = "owner"
                new_owner.updated_at = datetime.utcnow()
            else:
                # 如果不存在，创建新的owner记录
                await self.create_or_update_admin(bot_id, new_owner_id, "owner")

            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"[BotAdminRepository] Transfer ownership failed: {e}")
            await self.db.rollback()
            return False


class BotManagementRepository:
    """Bot管理 Repository"""

    def __init__(self, db_session):
        self.db = db_session

    async def get_bot_creation(self, bot_id: str) -> Optional[BotCreation]:
        """获取Bot创建记录"""
        query = select(BotCreation).where(BotCreation.instance_id == bot_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_bot_status(self, bot_id: str, run_status: str = None,
                                token_status: str = None, last_error: str = None) -> bool:
        """更新Bot状态"""
        try:
            bot = await self.get_bot_creation(bot_id)
            if not bot:
                return False

            if run_status:
                bot.status = run_status
                if run_status == "running":
                    bot.started_at = datetime.utcnow()
                elif run_status in ["stopped", "disconnected"]:
                    bot.stopped_at = datetime.utcnow()

            if token_status:
                bot.token_status = token_status

            if last_error:
                bot.token_invalid_reason = last_error

            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"[BotManagementRepository] Update status failed: {e}")
            await self.db.rollback()
            return False

    async def update_bot_token(self, bot_id: str, new_token: str,
                               new_username: str, new_name: str) -> bool:
        """更新Bot Token"""
        try:
            from ..utils.token_encryptor import token_encryptor
            bot = await self.get_bot_creation(bot_id)
            if not bot:
                return False

            bot.bot_token = token_encryptor.encrypt_to_base64(new_token)
            bot.bot_username = new_username
            bot.bot_name = new_name
            bot.token_status = "normal"
            bot.status = "running"
            bot.lifecycle_status = "ACTIVE"
            bot.token_invalid_reason = None
            bot.token_checked_at = datetime.utcnow()
            bot.rebind_status = "none"
            bot.rebind_user_id = None
            bot.rebind_started_at = None

            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"[BotManagementRepository] Update token failed: {e}")
            await self.db.rollback()
            return False

    async def disable_bot(self, bot_id: str) -> bool:
        """停用Bot（不删除数据）"""
        try:
            bot = await self.get_bot_creation(bot_id)
            if not bot:
                return False

            bot.status = "disabled"
            bot.token_status = "disabled"
            bot.lifecycle_status = "SUSPENDED"
            bot.stopped_at = datetime.utcnow()

            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"[BotManagementRepository] Disable bot failed: {e}")
            await self.db.rollback()
            return False

    async def disconnect_bot(self, bot_id: str) -> bool:
        """断开Bot（暂停运行，保留数据）"""
        try:
            bot = await self.get_bot_creation(bot_id)
            if not bot:
                return False

            bot.status = "disconnected"
            bot.stopped_at = datetime.utcnow()

            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"[BotManagementRepository] Disconnect bot failed: {e}")
            await self.db.rollback()
            return False

    async def update_owner(self, bot_id: str, new_owner_id: int) -> bool:
        """更新Bot所有者"""
        try:
            bot = await self.get_bot_creation(bot_id)
            if not bot:
                return False

            bot.telegram_id = new_owner_id
            bot.super_admin_id = new_owner_id
            try:
                config = json.loads(bot.config_json) if bot.config_json else {}
                if not isinstance(config, dict):
                    config = {}
                config["owner_user_id"] = new_owner_id
                bot.config_json = json.dumps(config)
            except Exception:
                bot.config_json = json.dumps({"owner_user_id": new_owner_id})

            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"[BotManagementRepository] Update owner failed: {e}")
            await self.db.rollback()
            return False

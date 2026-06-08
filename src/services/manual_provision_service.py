"""
Manual Provision Service - 超管手动开通套餐服务

功能：
1. 超管通过私聊手动为客户开通/续费套餐
2. 支持新开通和续费两种场景
3. 完全复用现有的 create_bot_instance 和 activate_subscription 逻辑
4. 记录审计日志，追踪所有手动操作

权限要求：
- 仅限主机器人（main_bot）
- 仅限超级管理员
- 仅限私聊
"""
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy import select, and_

from ..models import (
    BotCreation, Subscription, PricingPlan, get_db_session
)
from ..services.saas_auto_service import saas_auto_service
from ..services.usdt_payment_service import usdt_service
from config import config

logger = logging.getLogger(__name__)


class ManualProvisionService:
    """超管手动开通套餐服务"""
    
    async def resolve_user_id(self, identifier: str) -> Optional[int]:
        """
        解析用户标识符，返回Telegram ID
        
        Args:
            identifier: 用户标识符（@username 或 user_id）
        
        Returns:
            Telegram ID，失败返回None
        """
        try:
            if identifier.startswith('@'):
                # 是用户名
                username = identifier[1:]
                from telegram import Bot
                bot = Bot(token=config.BOT_TOKEN)
                chat = await bot.get_chat(username)
                return chat.id
            else:
                # 是数字ID
                return int(identifier)
        except (ValueError, Exception) as e:
            logger.error(f"Error resolving user ID '{identifier}': {e}")
            return None
    
    async def query_user_bots(self, telegram_id: int) -> list:
        """
        查询用户已创建的机器人列表
        
        Args:
            telegram_id: 用户Telegram ID
        
        Returns:
            BotCreation列表
        """
        async with get_db_session() as db:
            try:
                query = select(BotCreation).where(
                    BotCreation.telegram_id == telegram_id
                ).order_by(BotCreation.created_at.desc())
                
                result = await db.execute(query)
                bots = result.scalars().all()
                
                logger.info(f"User {telegram_id} has {len(bots)} bots")
                return bots
            except Exception as e:
                logger.error(f"Error querying user bots: {e}", exc_info=True)
                return []
    
    async def query_user_subscription(self, telegram_id: int) -> Optional[Subscription]:
        """
        查询用户订阅信息
        
        Args:
            telegram_id: 用户Telegram ID
        
        Returns:
            Subscription对象，不存在返回None
        """
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
                
                # 检查是否过期
                if subscription and subscription.expire_date < datetime.utcnow():
                    subscription.status = "expired"
                    await db.commit()
                    return None
                
                return subscription
            except Exception as e:
                logger.error(f"Error querying subscription: {e}", exc_info=True)
                return None
    
    async def manual_activate_subscription(
        self,
        telegram_id: int,
        username: str,
        plan_id: int,
        operator_id: int
    ) -> Tuple[bool, str]:
        """
        手动激活/续费订阅（复用usdt_payment_service的逻辑）
        
        Args:
            telegram_id: 目标用户Telegram ID
            username: 用户名
            plan_id: 套餐ID
            operator_id: 操作员ID（超管）
        
        Returns:
            (success, message)
        """
        try:
            # 复用现有的 activate_subscription 方法
            success, message = await usdt_service.activate_subscription(
                telegram_id=telegram_id,
                username=username,
                plan_id=plan_id
            )
            
            if success:
                # ✅ 记录审计日志
                await self._log_audit(
                    operator_id=operator_id,
                    target_user_id=telegram_id,
                    action="manual_activate",
                    details={
                        "plan_id": plan_id,
                        "message": message
                    }
                )
            
            return success, message
            
        except Exception as e:
            logger.error(f"Error in manual_activate_subscription: {e}", exc_info=True)
            return False, f"激活失败: {str(e)}"
    
    async def manual_create_bot(
        self,
        telegram_id: int,
        username: str,
        bot_token: str,
        bot_username: str,
        bot_name: str,
        operator_id: int
    ) -> Tuple[bool, str, Optional[BotCreation]]:
        """
        手动创建Bot实例（复用saas_auto_service的逻辑）
        
        Args:
            telegram_id: 目标用户Telegram ID
            username: 用户名
            bot_token: Bot Token
            bot_username: Bot用户名
            bot_name: Bot名称
            operator_id: 操作员ID（超管）
        
        Returns:
            (success, message, bot_creation)
        """
        try:
            # 复用现有的 create_bot_instance 方法
            success, message, bot_creation = await saas_auto_service.create_bot_instance(
                telegram_id=telegram_id,
                username=username,
                bot_token=bot_token,
                bot_username=bot_username,
                bot_name=bot_name,
                parent_bot_id=None  # 手动开通的Bot没有父Bot
            )
            
            if success:
                # ✅ 记录审计日志
                await self._log_audit(
                    operator_id=operator_id,
                    target_user_id=telegram_id,
                    action="manual_create_bot",
                    details={
                        "bot_username": bot_username,
                        "bot_name": bot_name,
                        "instance_id": bot_creation.instance_id if bot_creation else None
                    }
                )
            
            return success, message, bot_creation
            
        except Exception as e:
            logger.error(f"Error in manual_create_bot: {e}", exc_info=True)
            return False, f"创建Bot失败: {str(e)}", None
    
    async def _log_audit(
        self,
        operator_id: int,
        target_user_id: int,
        action: str,
        details: dict
    ):
        """
        记录审计日志
        
        Args:
            operator_id: 操作员ID（超管）
            target_user_id: 目标用户ID
            action: 操作类型（manual_activate / manual_create_bot）
            details: 详细信息
        """
        try:
            from ..services.audit_service import audit_service
            
            await audit_service.log(
                user_id=operator_id,
                action=action,
                bot_id="main_bot",
                username=f"Operator_{operator_id}",
                details={
                    "target_user_id": target_user_id,
                    **details
                },
                status="success"
            )
            
            logger.info(
                f"Audit log recorded: operator={operator_id}, "
                f"target={target_user_id}, action={action}"
            )
        except Exception as e:
            logger.error(f"Failed to log audit: {e}", exc_info=True)
            # 审计日志失败不影响主流程


# 全局服务实例
manual_provision_service = ManualProvisionService()

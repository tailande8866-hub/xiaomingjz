"""
Bot 生命周期管理服务

职责：
1. 定期检查 Bot 到期状态
2. 自动转换生命周期状态（ACTIVE → SUSPENDED → ARCHIVED → DELETED）
3. 更新最后活动时间
4. 清理已删除的 Bot 实例
5. 发送到期提醒通知
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, and_, update

from ..models.saas_auto import BotCreation, BotLifecycleStatus, LifecycleConfig
from ..models.database import get_db_session
from .bot_instance_manager import bot_instance_manager

logger = logging.getLogger(__name__)


class BotLifecycleManager:
    """Bot 生命周期管理器"""
    
    async def check_and_update_lifecycle(self):
        """
        检查并更新所有 Bot 的生命周期状态
        
        执行流程：
        1. ACTIVE → SUSPENDED：套餐到期
        2. SUSPENDED → ARCHIVED：宽限期结束（7天）
        3. ARCHIVED → DELETED：长期不续费（180天）
        4. 发送到期提醒通知
        """
        logger.info("🔄 Starting lifecycle status check...")
        
        async with get_db_session() as db:
            try:
                now = datetime.utcnow()
                
                # === 0. 发送到期提醒通知 ===
                await self._send_expiration_reminders(db, now)
                
                # === 1. ACTIVE → SUSPENDED：套餐到期 ===
                expired_bots = await db.execute(
                    select(BotCreation).where(
                        and_(
                            BotCreation.lifecycle_status == BotLifecycleStatus.ACTIVE,
                            BotCreation.expire_time.isnot(None),
                            BotCreation.expire_time <= now
                        )
                    )
                )
                expired_bots = expired_bots.scalars().all()
                
                for bot in expired_bots:
                    grace_end = now + timedelta(days=LifecycleConfig.GRACE_PERIOD_DAYS)
                    
                    await db.execute(
                        update(BotCreation)
                        .where(BotCreation.instance_id == bot.instance_id)
                        .values(
                            lifecycle_status=BotLifecycleStatus.SUSPENDED,
                            grace_period_end=grace_end
                        )
                    )
                    
                    logger.warning(
                        f"⚠️ Bot {bot.instance_id} expired! "
                        f"Status: ACTIVE → SUSPENDED, "
                        f"Grace period until: {grace_end}"
                    )
                
                if expired_bots:
                    logger.info(f"✅ Suspended {len(expired_bots)} expired bots")
                
                # === 2. SUSPENDED → ARCHIVED：宽限期结束 ===
                grace_expired_bots = await db.execute(
                    select(BotCreation).where(
                        and_(
                            BotCreation.lifecycle_status == BotLifecycleStatus.SUSPENDED,
                            BotCreation.grace_period_end.isnot(None),
                            BotCreation.grace_period_end <= now
                        )
                    )
                )
                grace_expired_bots = grace_expired_bots.scalars().all()
                
                for bot in grace_expired_bots:
                    await db.execute(
                        update(BotCreation)
                        .where(BotCreation.instance_id == bot.instance_id)
                        .values(
                            lifecycle_status=BotLifecycleStatus.ARCHIVED,
                            archived_at=now
                        )
                    )
                    
                    logger.warning(
                        f"📦 Bot {bot.instance_id} grace period ended! "
                        f"Status: SUSPENDED → ARCHIVED"
                    )
                    
                    # ✅ 实现：真正停止 Bot 实例（释放资源）
                    try:
                        await bot_instance_manager.stop_bot_instance(bot.instance_id)
                        logger.info(f"✅ Stopped bot instance: {bot.instance_id}")
                    except Exception as e:
                        logger.error(f"Failed to stop bot {bot.instance_id}: {e}")
                
                if grace_expired_bots:
                    logger.info(f"✅ Archived {len(grace_expired_bots)} bots after grace period")
                
                # === 3. ARCHIVED → DELETED：长期不续费 ===
                delete_candidate_bots = await db.execute(
                    select(BotCreation).where(
                        and_(
                            BotCreation.lifecycle_status == BotLifecycleStatus.ARCHIVED,
                            BotCreation.archived_at.isnot(None),
                            BotCreation.archived_at <= now - timedelta(days=LifecycleConfig.DELETE_AFTER_DAYS)
                        )
                    )
                )
                delete_candidate_bots = delete_candidate_bots.scalars().all()
                
                for bot in delete_candidate_bots:
                    await db.execute(
                        update(BotCreation)
                        .where(BotCreation.instance_id == bot.instance_id)
                        .values(lifecycle_status=BotLifecycleStatus.DELETED)
                    )
                    
                    logger.warning(
                        f"🗑️ Bot {bot.instance_id} marked for deletion! "
                        f"Status: ARCHIVED → DELETED"
                    )
                    
                    # TODO: 真正删除 Bot 实例和数据
                    # await self._delete_bot_instance(bot.instance_id)
                
                if delete_candidate_bots:
                    logger.info(f"✅ Marked {len(delete_candidate_bots)} bots for deletion")
                
                # === 提交事务 ===
                await db.commit()
                
                total_changes = len(expired_bots) + len(grace_expired_bots) + len(delete_candidate_bots)
                logger.info(f"✅ Lifecycle check completed. Total changes: {total_changes}")
                
            except Exception as e:
                logger.error(f"❌ Error in lifecycle check: {e}", exc_info=True)
                await db.rollback()
    
    async def update_last_activity(self, instance_id: str):
        """
        更新 Bot 的最后活动时间
        
        Args:
            instance_id: Bot 实例 ID
        """
        async with get_db_session() as db:
            try:
                await db.execute(
                    update(BotCreation)
                    .where(BotCreation.instance_id == instance_id)
                    .values(last_activity_at=datetime.utcnow())
                )
                await db.commit()
            except Exception as e:
                logger.error(f"Error updating last activity for {instance_id}: {e}")
    
    async def _send_expiration_reminders(self, db, now: datetime):
        """
        发送到期提醒通知
        
        提醒时机：
        1. 到期前7天
        2. 到期当天
        3. 宽限期结束前1天
        
        Args:
            db: 数据库会话
            now: 当前时间
        """
        try:
            from telegram import Bot
            from config import config
            
            # 创建主 Bot 对象用于发送消息
            main_bot = Bot(token=config.BOT_TOKEN)
            
            # === 1. 到期前7天提醒 ===
            seven_days_later = now + timedelta(days=7)
            expiring_soon_query = select(BotCreation).where(
                and_(
                    BotCreation.lifecycle_status == BotLifecycleStatus.ACTIVE,
                    BotCreation.expire_time.isnot(None),
                    BotCreation.expire_time <= seven_days_later,
                    BotCreation.expire_time > now
                )
            )
            expiring_soon_result = await db.execute(expiring_soon_query)
            expiring_soon_bots = expiring_soon_result.scalars().all()
            
            for bot in expiring_soon_bots:
                days_left = (bot.expire_time - now).days
                
                # 构建提醒消息
                reminder_msg = (
                    f"⚠️ <b>Bot @{bot.bot_username} 即将到期</b>\n\n"
                    f"您的 Bot <code>@{bot.bot_username}</code> 将在 <b>{days_left} 天后</b> 到期。\n\n"
                    f"📅 到期时间：{bot.expire_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"💡 为避免服务中断，请及时续费。\n\n"
                    f"👉 点击底部菜单「个人中心」进行续费"
                )
                
                try:
                    # 发送给 Bot 拥有者
                    await main_bot.send_message(
                        chat_id=bot.super_admin_id,
                        text=reminder_msg,
                        parse_mode="HTML"
                    )
                    logger.info(f"📧 Sent 7-day expiration reminder to user {bot.super_admin_id} for bot {bot.instance_id}")
                except Exception as e:
                    logger.error(f"Failed to send reminder to {bot.super_admin_id}: {e}")
            
            if expiring_soon_bots:
                logger.info(f"✅ Sent {len(expiring_soon_bots)} 7-day expiration reminders")
            
            # === 2. 到期当天提醒 ===
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            expiring_today_query = select(BotCreation).where(
                and_(
                    BotCreation.lifecycle_status == BotLifecycleStatus.ACTIVE,
                    BotCreation.expire_time.isnot(None),
                    BotCreation.expire_time >= today_start,
                    BotCreation.expire_time < today_end
                )
            )
            expiring_today_result = await db.execute(expiring_today_query)
            expiring_today_bots = expiring_today_result.scalars().all()
            
            for bot in expiring_today_bots:
                # 构建紧急提醒消息
                urgent_msg = (
                    f"🚨 <b>Bot @{bot.bot_username} 今日到期！</b>\n\n"
                    f"您的 Bot <code>@{bot.bot_username}</code> <b>今天</b>将到期。\n\n"
                    f"⏰ 到期时间：{bot.expire_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"❗ 如不续费，Bot 将进入暂停状态，业务功能将关闭。\n\n"
                    f"👉 立即点击底部菜单「个人中心」续费"
                )
                
                try:
                    await main_bot.send_message(
                        chat_id=bot.super_admin_id,
                        text=urgent_msg,
                        parse_mode="HTML"
                    )
                    logger.info(f"📧 Sent today expiration reminder to user {bot.super_admin_id} for bot {bot.instance_id}")
                except Exception as e:
                    logger.error(f"Failed to send urgent reminder to {bot.super_admin_id}: {e}")
            
            if expiring_today_bots:
                logger.info(f"✅ Sent {len(expiring_today_bots)} today expiration reminders")
            
            # === 3. 宽限期结束前1天提醒 ===
            one_day_later = now + timedelta(days=1)
            grace_ending_query = select(BotCreation).where(
                and_(
                    BotCreation.lifecycle_status == BotLifecycleStatus.SUSPENDED,
                    BotCreation.grace_period_end.isnot(None),
                    BotCreation.grace_period_end >= now,
                    BotCreation.grace_period_end <= one_day_later
                )
            )
            grace_ending_result = await db.execute(grace_ending_query)
            grace_ending_bots = grace_ending_result.scalars().all()
            
            for bot in grace_ending_bots:
                hours_left = int((bot.grace_period_end - now).total_seconds() / 3600)
                
                # 构建最后提醒消息
                final_msg = (
                    f"🔴 <b>Bot @{bot.bot_username} 即将归档！</b>\n\n"
                    f"您的 Bot <code>@{bot.bot_username}</code> 已进入暂停状态。\n\n"
                    f"⏳ 宽限期剩余：<b>{hours_left} 小时</b>\n\n"
                    f"❗ 宽限期结束后，Bot 将被归档并停止运行。\n"
                    f"   - 数据仍保留，但无法使用\n"
                    f"   - 需要重新激活才能恢复\n\n"
                    f"👉 立即续费以恢复服务"
                )
                
                try:
                    await main_bot.send_message(
                        chat_id=bot.super_admin_id,
                        text=final_msg,
                        parse_mode="HTML"
                    )
                    logger.info(f"📧 Sent grace period ending reminder to user {bot.super_admin_id} for bot {bot.instance_id}")
                except Exception as e:
                    logger.error(f"Failed to send final reminder to {bot.super_admin_id}: {e}")
            
            if grace_ending_bots:
                logger.info(f"✅ Sent {len(grace_ending_bots)} grace period ending reminders")
        
        except Exception as e:
            logger.error(f"Error sending expiration reminders: {e}", exc_info=True)
    
    async def get_active_bots(self) -> list:
        """
        获取所有处于 ACTIVE 状态的 Bot
        
        Returns:
            BotCreation 列表
        """
        async with get_db_session() as db:
            try:
                query = select(BotCreation).where(
                    BotCreation.lifecycle_status == BotLifecycleStatus.ACTIVE
                )
                result = await db.execute(query)
                return result.scalars().all()
            except Exception as e:
                logger.error(f"Error getting active bots: {e}")
                return []
    
    async def get_suspended_bots(self) -> list:
        """获取所有处于 SUSPENDED 状态的 Bot"""
        async with get_db_session() as db:
            try:
                query = select(BotCreation).where(
                    BotCreation.lifecycle_status == BotLifecycleStatus.SUSPENDED
                )
                result = await db.execute(query)
                return result.scalars().all()
            except Exception as e:
                logger.error(f"Error getting suspended bots: {e}")
                return []
    
    async def reactivate_bot(self, instance_id: str, new_expire_time: datetime):
        """
        重新激活已暂停的 Bot（用户续费后调用）
        
        Args:
            instance_id: Bot 实例 ID
            new_expire_time: 新的到期时间
        """
        async with get_db_session() as db:
            try:
                # 1. 查询 Bot 信息
                query = select(BotCreation).where(BotCreation.instance_id == instance_id)
                result = await db.execute(query)
                bot = result.scalar_one_or_none()
                
                if not bot:
                    logger.error(f"Bot {instance_id} not found")
                    return False
                
                # 2. 更新生命周期状态
                await db.execute(
                    update(BotCreation)
                    .where(BotCreation.instance_id == instance_id)
                    .values(
                        lifecycle_status=BotLifecycleStatus.ACTIVE,
                        expire_time=new_expire_time,
                        grace_period_end=None,
                        archived_at=None,
                        last_activity_at=datetime.utcnow()
                    )
                )
                await db.commit()
                
                logger.info(f"✅ Bot {instance_id} reactivated! New expire time: {new_expire_time}")
                
                # ✅ 实现：重新启动 Bot 实例
                if bot.lifecycle_status in [BotLifecycleStatus.SUSPENDED, BotLifecycleStatus.ARCHIVED]:
                    try:
                        # 从数据库重新加载 Bot 信息
                        await db.refresh(bot)
                        success = await bot_instance_manager.start_bot_instance(bot)
                        
                        if success:
                            logger.info(f"✅ Successfully restarted bot instance: {instance_id}")
                        else:
                            logger.error(f"Failed to restart bot instance: {instance_id}")
                    except Exception as e:
                        logger.error(f"Error restarting bot {instance_id}: {e}")
                
                return True
                
            except Exception as e:
                logger.error(f"Error reactivating bot {instance_id}: {e}")
                await db.rollback()
                return False


# 全局实例
bot_lifecycle_manager = BotLifecycleManager()

"""
定时任务服务
"""
from datetime import datetime, time
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, false
from telegram import Bot
import logging

from ..models import Group, get_db
from .billing_service import BillingService

logger = logging.getLogger(__name__)


class ScheduleService:
    """定时任务服务类"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()

    async def start(self):
        """启动定时任务"""
        # 启动调度器
        self.scheduler.start()

        # 加载所有群组的日切任务
        async for db in get_db():
            await self.load_day_cut_tasks(db)
        
        # 添加SaaS订单清理任务（每小时执行一次）
        self.scheduler.add_job(
            self._cleanup_expired_orders,
            CronTrigger(hour='*'),  # 每小时执行
            id='cleanup_expired_orders',
            name='清理过期支付订单',
            replace_existing=True
        )
        logger.info("Scheduled task added: cleanup expired orders (hourly)")
        
        # 🆕 添加Token心跳检测任务（每4小时执行一次）
        self.scheduler.add_job(
            self._token_heartbeat_check,
            CronTrigger(hour='*/4'),  # 每4小时执行
            id='token_heartbeat_check',
            name='Token心跳检测',
            replace_existing=True
        )
        logger.info("Scheduled task added: token heartbeat check (every 4 hours)")

    async def stop(self):
        """停止定时任务"""
        self.scheduler.shutdown()

    async def load_day_cut_tasks(self, db):
        """加载所有群组的日切任务"""
        query = select(Group).where(Group.day_cut_time.is_not(None))
        result = await db.execute(query)
        groups = result.scalars().all()

        for group in groups:
            await self.add_day_cut_task(group)

    async def add_day_cut_task(self, group: Group):
        """
        添加日切任务

        Args:
            group: 群组对象
        """
        if not group.day_cut_time:
            return

        # 创建任务ID
        job_id = f"day_cut_{group.group_id}"

        # 移除已存在的任务
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # 添加新任务
        trigger = CronTrigger(
            hour=group.day_cut_time.hour,
            minute=group.day_cut_time.minute,
            second=0
        )

        self.scheduler.add_job(
            self.execute_day_cut,
            trigger=trigger,
            args=[group.group_id],
            id=job_id,
            replace_existing=True
        )

    async def remove_day_cut_task(self, group_id: int):
        """
        移除日切任务

        Args:
            group_id: 群组ID
        """
        job_id = f"day_cut_{group_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    async def execute_day_cut(self, group_id: int):
        """
        执行日切操作

        Args:
            group_id: 群组ID
        """
        try:
            async for db in get_db():
                # 获取群组信息
                query = select(Group).where(Group.group_id == group_id)
                result = await db.execute(query)
                group = result.scalar_one_or_none()

                if not group or not group.is_active:
                    return

                # 创建每日汇总
                today = datetime.utcnow()
                daily_summary = await BillingService.create_daily_summary(
                    db=db,
                    group_id=group_id,
                    summary_date=today
                )

                # 标记所有未标记的交易记录为当前日切周期
                from sqlalchemy import update
                from ..models import Transaction
                
                stmt = (
                    update(Transaction)
                    .where(
                        Transaction.group_id == group_id,
                        Transaction.day_cut_date.is_(None),
                        Transaction.is_deleted.is_(False)
                    )
                    .values(day_cut_date=today)
                )
                await db.execute(stmt)
                
                # 更新最后日切时间
                group.last_day_cut = today
                await db.commit()

                # 发送日切通知
                message = self._format_day_cut_message(daily_summary, group)
                await self.bot.send_message(
                    chat_id=group_id,
                    text=message,
                    parse_mode='HTML'
                )

        except Exception as e:
            print(f"Error executing day cut for group {group_id}: {e}")

    def _format_day_cut_message(self, daily_summary, group: Group) -> str:
        """
        格式化日切消息

        Args:
            daily_summary: 每日汇总对象
            group: 群组对象

        Returns:
            格式化的消息文本
        """
        lines = [
            "🌙 <b>日切汇总</b>",
            "=" * 30,
            "",
            f"📅 日期: {daily_summary.summary_date.strftime('%Y-%m-%d')}",
            f"🏢 群组: {group.group_name}",
            "",
            "<b>💰 入款统计</b>",
            f"  笔数: {daily_summary.total_deposit_count}",
            f"  总额: {daily_summary.total_deposit_amount:.2f} USDT",
            f"  人民币: ¥{daily_summary.total_deposit_cny:.2f}",
            "",
            "<b>💸 下发统计</b>",
            f"  笔数: {daily_summary.total_withdraw_count}",
            f"  总额: {daily_summary.total_withdraw_amount:.2f} USDT",
            f"  人民币: ¥{daily_summary.total_withdraw_cny:.2f}",
            "",
            f"<b>📦 寄存: ¥{daily_summary.total_storage_amount:.2f}</b>",
            f"<b>💵 手续费: ¥{daily_summary.total_fee_amount:.2f}</b>",
            "",
            f"<b>📈 净额: ¥{daily_summary.net_amount:.2f}</b>",
        ]

        return "\n".join(lines)
    
    async def _cleanup_expired_orders(self):
        """
        清理过期订单（定时任务）
        """
        try:
            from .usdt_payment_service import usdt_service
            await usdt_service.cleanup_expired_orders()
        except Exception as e:
            logger.error(f"Error in cleanup_expired_orders task: {e}", exc_info=True)

    async def manual_day_cut(self, group_id: int):
        """
        鎵嬪姩鎵ц鏃ュ垏

        Args:
            group_id: 缇ょ粍ID
        """
        await self.execute_day_cut(group_id)
    
    async def _token_heartbeat_check(self):
        """
        Token心跳检测任务 - 每4小时检测一次活跃Bot的Token有效性
        """
        try:
            from .token_check_service import token_check_service
            await token_check_service.heartbeat_check()
        except Exception as e:
            logger.error(f"Error in token_heartbeat_check task: {e}", exc_info=True)

"""Background manager for dual-mode timed messages."""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Iterable, Optional, Set

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, select
from telegram import Bot
from telegram.error import RetryAfter

from ..models import Group, GroupTag, TimedMessageSendLog, TimedMessageSetting, get_db_session
from ..models.enums import GroupStatus

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 300


class TimedMessageManager:
    """Create, restore, refresh and cancel timed message jobs for one bot."""

    def __init__(self, bot: Bot, bot_id: str):
        self.bot = bot
        self.bot_id = bot_id
        self.scheduler = AsyncIOScheduler()
        self._started = False

    async def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
        self._started = True
        await self.restore_enabled_jobs()
        logger.info("TimedMessageManager started for bot_id=%s", self.bot_id)

    async def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self._started = False
        logger.info("TimedMessageManager stopped for bot_id=%s", self.bot_id)

    def _job_id(self, scope_type: str, scope_id: Optional[int]) -> str:
        return f"timed_message:{self.bot_id}:{scope_type}:{scope_id or 'global'}"

    async def restore_enabled_jobs(self):
        async with get_db_session() as db:
            result = await db.execute(
                select(TimedMessageSetting).where(
                    and_(
                        TimedMessageSetting.bot_id == self.bot_id,
                        TimedMessageSetting.enabled.is_(True),
                    )
                )
            )
            settings = result.scalars().all()
        for setting in settings:
            self.refresh_job(setting)

    def refresh_job(self, setting: TimedMessageSetting):
        job_id = self._job_id(setting.scope_type, setting.group_id)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        if not setting.enabled:
            return

        interval = max(int(setting.interval_seconds or MIN_INTERVAL_SECONDS), MIN_INTERVAL_SECONDS)
        self.scheduler.add_job(
            self.execute_setting,
            trigger="interval",
            seconds=interval,
            args=[setting.id],
            id=job_id,
            name=f"定时消息 {setting.scope_type}:{setting.group_id or 'global'}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Timed message job refreshed: %s interval=%s", job_id, interval)

    async def refresh_setting(self, setting_id: int):
        async with get_db_session() as db:
            setting = await db.get(TimedMessageSetting, setting_id)
            if not setting:
                return
            self.refresh_job(setting)

    async def cancel_setting(self, scope_type: str, scope_id: Optional[int]):
        job_id = self._job_id(scope_type, scope_id)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info("Timed message job canceled: %s", job_id)

    async def execute_setting(self, setting_id: int):
        async with get_db_session() as db:
            setting = await db.get(TimedMessageSetting, setting_id)
            if not setting or not setting.enabled:
                return
            content = (setting.content or "").strip()
            if not content:
                return

            target_groups = await self._resolve_target_groups(db, setting)
            sent_group_ids: Set[int] = set()
            for group in target_groups:
                if group.group_id in sent_group_ids:
                    continue
                sent_group_ids.add(group.group_id)
                await self._send_one(db, setting, group, content)

            setting.last_sent_at = datetime.now()

    async def _resolve_target_groups(self, db, setting: TimedMessageSetting) -> Iterable[Group]:
        base_conditions = [
            Group.bot_id == self.bot_id,
            Group.is_active.is_(True),
            Group.status == GroupStatus.ACTIVE.value,
        ]

        if setting.scope_type == "group":
            tag = await db.get(GroupTag, setting.group_id)
            if not tag or tag.bot_id != self.bot_id or not tag.is_active:
                return []
            result = await db.execute(
                select(Group).where(and_(*base_conditions, Group.group_tag == tag.tag_name))
            )
            return result.scalars().all()

        enabled_tag_names = await self._enabled_group_timer_tag_names(db)
        conditions = list(base_conditions)
        if enabled_tag_names:
            conditions.append(~Group.group_tag.in_(enabled_tag_names))
        result = await db.execute(select(Group).where(and_(*conditions)))
        return result.scalars().all()

    async def _enabled_group_timer_tag_names(self, db) -> Set[str]:
        result = await db.execute(
            select(GroupTag.tag_name)
            .join(TimedMessageSetting, TimedMessageSetting.group_id == GroupTag.id)
            .where(
                and_(
                    TimedMessageSetting.bot_id == self.bot_id,
                    TimedMessageSetting.scope_type == "group",
                    TimedMessageSetting.enabled.is_(True),
                    GroupTag.bot_id == self.bot_id,
                    GroupTag.is_active.is_(True),
                )
            )
        )
        return set(result.scalars().all())

    async def _send_one(self, db, setting: TimedMessageSetting, group: Group, content: str):
        status = "success"
        error_message = None
        try:
            await self.bot.send_message(chat_id=group.group_id, text=content)
        except RetryAfter as exc:
            retry_after = int(getattr(exc, "retry_after", 1) or 1)
            await asyncio.sleep(max(1, retry_after))
            try:
                await self.bot.send_message(chat_id=group.group_id, text=content)
            except Exception as retry_exc:
                status = "failed"
                error_message = str(retry_exc)[:1000]
        except Exception as exc:
            status = "failed"
            error_message = str(exc)[:1000]

        db.add(
            TimedMessageSendLog(
                bot_id=self.bot_id,
                target_group_id=group.group_id,
                scope_type=setting.scope_type,
                scope_id=setting.group_id,
                status=status,
                error_message=error_message,
                sent_at=datetime.now(),
            )
        )


async def refresh_application_timed_message_job(application, setting_id: int):
    manager = getattr(application, "timed_message_manager", None)
    if manager:
        await manager.refresh_setting(setting_id)


async def cancel_application_timed_message_job(application, scope_type: str, scope_id: Optional[int]):
    manager = getattr(application, "timed_message_manager", None)
    if manager:
        await manager.cancel_setting(scope_type, scope_id)

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, desc, or_, select

from ..models import Admin, BotAdmin, BotCreation, Subscription, TrialRecord, get_db_session

logger = logging.getLogger(__name__)


@dataclass
class EffectiveAccountStatus:
    tier: str
    package_name: str
    status_text: str
    expire_time: Optional[datetime]
    days_left: int
    group_limit: int
    active_bot: Optional[BotCreation]
    active_subscription: Optional[Subscription]
    is_trial: bool
    is_full: bool
    is_super_admin: bool
    needs_token_rebind: bool


class AccountStatusService:
    TRIAL_GROUP_LIMIT = 5

    @staticmethod
    def _is_usable_bot(bot: BotCreation, now: datetime) -> bool:
        lifecycle_status = (getattr(bot, "lifecycle_status", "") or "").upper()
        status = (getattr(bot, "status", "") or "").lower()
        expire_time = getattr(bot, "expire_time", None)

        if lifecycle_status == "DELETED":
            return False
        if expire_time and expire_time <= now:
            return False
        return status in {"creating", "running", "stopped", "error"} or lifecycle_status in {"", "ACTIVE", "SUSPENDED", "ARCHIVED"}

    async def get_owned_bots(self, user_id: int, db=None) -> list[BotCreation]:
        """Return bots owned by user, including legacy bot_admins owner records."""
        user_id = int(user_id)
        should_close = db is None
        if should_close:
            session_cm = get_db_session()
            db = await session_cm.__aenter__()

        try:
            direct_result = await db.execute(
                select(BotCreation)
                .where(
                    or_(
                        BotCreation.telegram_id == user_id,
                        BotCreation.super_admin_id == user_id,
                    )
                )
                .order_by(desc(BotCreation.created_at))
            )
            bots_by_id = {bot.instance_id: bot for bot in direct_result.scalars().all()}

            try:
                owner_link_result = await db.execute(
                    select(BotCreation)
                    .join(BotAdmin, BotAdmin.bot_id == BotCreation.instance_id)
                    .where(
                        and_(
                            BotAdmin.user_id == user_id,
                            BotAdmin.role == "owner",
                            BotAdmin.is_active.is_(True),
                        )
                    )
                    .order_by(desc(BotCreation.created_at))
                )
                for bot in owner_link_result.scalars().all():
                    bots_by_id[bot.instance_id] = bot
            except Exception:
                logger.error("[ACCOUNT_STATUS] bot_admins owner lookup failed for user_id=%s", user_id, exc_info=True)

            return sorted(
                bots_by_id.values(),
                key=lambda bot: bot.created_at or datetime.min,
                reverse=True,
            )
        finally:
            if should_close:
                await session_cm.__aexit__(None, None, None)

    async def resolve(self, user_id: int, bot_id: str | None = None) -> EffectiveAccountStatus:
        if int(user_id) == 7862093562:
            return EffectiveAccountStatus(
                tier="super_admin",
                package_name="超级管理员",
                status_text="正常",
                expire_time=None,
                days_left=999999,
                group_limit=999999,
                active_bot=None,
                active_subscription=None,
                is_trial=False,
                is_full=True,
                is_super_admin=True,
                needs_token_rebind=False,
            )

        now = datetime.utcnow()
        async with get_db_session() as db:
            user_bots = await self.get_owned_bots(int(user_id), db)
            active_bot = next((bot for bot in user_bots if self._is_usable_bot(bot, now)), None)
            if not active_bot and user_bots:
                active_bot = user_bots[0]

            sub_result = await db.execute(
                select(Subscription)
                .where(Subscription.telegram_id == int(user_id))
                .order_by(desc(Subscription.updated_at))
            )
            subscription = sub_result.scalars().first()
            if subscription and subscription.status == "active" and subscription.expire_date and subscription.expire_date <= now:
                subscription.status = "expired"
                subscription = None

            trial_admin = None
            if bot_id:
                trial_admin_result = await db.execute(
                    select(Admin).where(
                        and_(
                            Admin.bot_id == bot_id,
                            Admin.user_id == int(user_id),
                            Admin.is_active.is_(True),
                            Admin.is_trial.is_(True),
                        )
                    )
                )
                trial_admin = trial_admin_result.scalar_one_or_none()

            trial_record = None
            if bot_id:
                trial_record_result = await db.execute(
                    select(TrialRecord).where(
                        and_(
                            TrialRecord.bot_id == bot_id,
                            TrialRecord.user_id == int(user_id),
                            TrialRecord.expire_time > now,
                        )
                    )
                )
                trial_record = trial_record_result.scalar_one_or_none()

            if active_bot:
                expire_time = active_bot.expire_time or (subscription.expire_date if subscription else None)
                days_left = max(0, (expire_time - now).days) if expire_time else 0
                needs_token_rebind = (
                    (active_bot.token_status or "").lower() == "invalid"
                    or (active_bot.rebind_status or "").lower() == "waiting"
                )
                return EffectiveAccountStatus(
                    tier="full",
                    package_name="全功能版",
                    status_text="正常" if not expire_time or expire_time > now else "已过期",
                    expire_time=expire_time,
                    days_left=days_left,
                    group_limit=999999,
                    active_bot=active_bot,
                    active_subscription=subscription,
                    is_trial=False,
                    is_full=True,
                    is_super_admin=False,
                    needs_token_rebind=needs_token_rebind,
                )

            if trial_admin or trial_record:
                expire_time = getattr(trial_admin, "expire_time", None) or getattr(trial_record, "expire_time", None)
                days_left = max(0, (expire_time - now).days) if expire_time else 0
                return EffectiveAccountStatus(
                    tier="trial",
                    package_name="试用版",
                    status_text="正常" if not expire_time or expire_time > now else "已过期",
                    expire_time=expire_time,
                    days_left=days_left,
                    group_limit=self.TRIAL_GROUP_LIMIT,
                    active_bot=None,
                    active_subscription=subscription,
                    is_trial=True,
                    is_full=False,
                    is_super_admin=False,
                    needs_token_rebind=False,
                )

            if subscription and subscription.status == "active":
                expire_time = subscription.expire_date
                days_left = max(0, (expire_time - now).days) if expire_time else 0
                return EffectiveAccountStatus(
                    tier="pending_full",
                    package_name="全功能版",
                    status_text="待绑定Token",
                    expire_time=expire_time,
                    days_left=days_left,
                    group_limit=999999,
                    active_bot=None,
                    active_subscription=subscription,
                    is_trial=False,
                    is_full=False,
                    is_super_admin=False,
                    needs_token_rebind=False,
                )

            return EffectiveAccountStatus(
                tier="none",
                package_name="未开通",
                status_text="未激活",
                expire_time=None,
                days_left=0,
                group_limit=self.TRIAL_GROUP_LIMIT,
                active_bot=None,
                active_subscription=None,
                is_trial=False,
                is_full=False,
                is_super_admin=False,
                needs_token_rebind=False,
            )


account_status_service = AccountStatusService()

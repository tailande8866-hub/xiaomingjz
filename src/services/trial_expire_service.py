"""
试用到期处理服务

职责：
1. 定时扫描已过期试用管理员
2. 自动移除管理员权限
3. 发送到期通知
"""
import logging
from datetime import datetime
from sqlalchemy import select, and_
from typing import List

from ..models import Admin, TrialRecord, get_db_session

logger = logging.getLogger(__name__)


class TrialExpireService:
    """试用到期处理服务"""

    async def scan_and_expire_trials(self, bot=None):
        """
        扫描并处理已过期试用

        Args:
            bot: Bot 实例（用于发送通知）
        """
        logger.info("🔍 开始扫描试用到期管理员...")

        expired_count = 0
        now = datetime.utcnow()

        try:
            async with get_db_session() as session:
                # 1. 查询所有已过期且未处理的试用管理员
                stmt = select(Admin).where(
                    and_(
                        Admin.is_trial.is_(True),
                        Admin.is_active.is_(True),
                        Admin.expire_time <= now
                    )
                )
                result = await session.execute(stmt)
                expired_admins = result.scalars().all()

                if not expired_admins:
                    logger.info("✅ 没有需要处理的过期试用管理员")
                    return 0

                logger.info(f"📋 发现 {len(expired_admins)} 个过期试用管理员")

                for admin in expired_admins:
                    try:
                        await self._expire_trial_admin(admin, bot)
                        expired_count += 1
                    except Exception as e:
                        logger.error(f"处理试用管理员 {admin.user_id} 到期失败: {e}", exc_info=True)

                await session.commit()

                logger.info(f"✅ 试用到期处理完成，共处理 {expired_count} 个管理员")
                return expired_count

        except Exception as e:
            logger.error(f"扫描试用到期失败: {e}", exc_info=True)
            return 0

    async def _expire_trial_admin(self, admin: Admin, bot=None):
        """
        处理单个试用管理员到期

        Args:
            admin: 试用管理员记录
            bot: Bot 实例（用于发送通知）
        """
        logger.info(f"⏰ 处理试用管理员到期: bot_id={admin.bot_id}, user_id={admin.user_id}")

        # 1. 移除管理员权限
        admin.is_active = False
        admin.is_trial = False
        admin.note = f"{admin.note or ''}\n试用已到期，管理员身份自动取消（{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}）"

        logger.info(f"   ✅ 已移除管理员权限: user_id={admin.user_id}")

        # 2. 发送到期通知
        if bot:
            await self._send_expire_notification(bot, admin)

    async def _send_expire_notification(self, bot, admin: Admin):
        """
        发送试用到期通知

        Args:
            bot: Bot 实例
            admin: 试用管理员记录
        """
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            message = (
                f"⏰ <b>试用已结束</b>\n\n"
                f"您的管理员试用权限已到期。\n"
                f"管理员身份已自动取消。\n\n"
                f"如需继续使用，请购买正式套餐。"
            )

            keyboard = [
                [InlineKeyboardButton("💰 购买套餐", callback_data="billing:self_renew")],
                [InlineKeyboardButton("🤖 创建BOT", callback_data="saas:create_bot")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await bot.send_message(
                chat_id=admin.user_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

            logger.info(f"   📨 已发送到期通知给用户 {admin.user_id}")

        except Exception as e:
            logger.error(f"发送到期通知失败: {e}")


# 全局实例
trial_expire_service = TrialExpireService()


async def trial_expire_scan_job(context=None):
    """
    定时任务入口

    建议每小时运行一次
    """
    logger.info("🕐 执行试用到期扫描任务...")

    # 获取 bot 实例
    bot = None
    if context and hasattr(context, 'bot'):
        bot = context.bot

    service = TrialExpireService()
    count = await service.scan_and_expire_trials(bot)

    logger.info(f"🕐 试用到期扫描任务完成，处理 {count} 个过期试用")

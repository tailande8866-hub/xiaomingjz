"""
用户广播服务 - 向用户批量发送私聊消息
"""
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from telegram import Message, InputMediaPhoto, InputMediaDocument, InputMediaVideo
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, distinct

from ..models.database import get_db_session
from ..models.group import PrivateChatUser

logger = logging.getLogger(__name__)


class UserBroadcastService:
    """用户广播服务 - 负责向用户私聊批量发送消息"""

    @staticmethod
    async def get_target_users(
        broadcast_target: str,
        bot_id: Optional[str] = None
    ) -> List[int]:
        """
        获取目标用户ID列表

        Args:
            broadcast_target: 广播目标 'this_bot' 或 'all_bots'
            bot_id: 机器人ID（用于多租户隔离）

        Returns:
            目标用户ID列表
        """
        async with get_db_session() as db:
            if broadcast_target == 'this_bot':
                # 获取当前 Bot 的所有私聊用户
                query = select(distinct(PrivateChatUser.user_id)).where(
                    PrivateChatUser.bot_id == bot_id
                )
                result = await db.execute(query)
                user_ids = result.scalars().all()

            elif broadcast_target == 'all_bots':
                # 获取所有 Bot 的所有私聊用户（跨租户）
                query = select(distinct(PrivateChatUser.user_id))
                result = await db.execute(query)
                user_ids = result.scalars().all()
            else:
                user_ids = []

            logger.info(f"[USER_BROADCAST] 获取{broadcast_target}用户列表：{len(user_ids)}人")
            return user_ids

    @staticmethod
    async def send_broadcast(
        context: ContextTypes.DEFAULT_TYPE,
        user_ids: List[int],
        message_content: Dict,
        progress_callback=None,
        stop_check=None
    ) -> Dict[str, int]:
        """
        发送用户广播消息

        Args:
            context: Bot上下文
            user_ids: 目标用户ID列表
            message_content: 消息内容（包含text、photo、video等）
            progress_callback: 进度回调函数
            stop_check: 中断检查函数，返回 True 时停止后续发送

        Returns:
            发送结果统计 {'success': int, 'fail': int, 'total': int}
        """
        success_count = 0
        fail_count = 0
        total = len(user_ids)
        failed_user_ids = []  # 记录失败的用户ID
        processed_count = 0
        stopped = False

        logger.info(f"[USER_BROADCAST] 开始向{total}个用户发送广播...")

        for idx, user_id in enumerate(user_ids):
            if stop_check and stop_check():
                stopped = True
                logger.info(f"[USER_BROADCAST] 收到中断信号，已处理 {processed_count}/{total}")
                break

            try:
                # 根据消息类型发送
                if message_content.get('type') == 'text':
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message_content.get('text') or message_content.get('content', ''),
                        parse_mode=message_content.get('parse_mode', 'HTML')
                    )
                elif message_content.get('type') == 'photo':
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=message_content.get('file_id'),
                        caption=message_content.get('caption', ''),
                        parse_mode=message_content.get('parse_mode', 'HTML')
                    )
                elif message_content.get('type') == 'video':
                    await context.bot.send_video(
                        chat_id=user_id,
                        video=message_content.get('file_id'),
                        caption=message_content.get('caption', ''),
                        parse_mode=message_content.get('parse_mode', 'HTML')
                    )
                elif message_content.get('type') == 'document':
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=message_content.get('file_id'),
                        caption=message_content.get('caption', ''),
                        parse_mode=message_content.get('parse_mode', 'HTML')
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message_content.get('text') or message_content.get('content', ''),
                        parse_mode='HTML'
                    )

                success_count += 1
                processed_count += 1
                logger.debug(f"[USER_BROADCAST] 发送给用户{user_id}成功")

                # 每发送一次都检查进度回调
                if progress_callback:
                    await progress_callback(success_count + fail_count, total)

                # 限速：0.5-1秒/条，避免触发Telegram限流
                if idx < total - 1:
                    await asyncio.sleep(0.5)

            except Exception as e:
                error_msg = str(e).lower()
                logger.warning(f"[USER_BROADCAST] 发送给用户{user_id}失败：{str(e)}")
                fail_count += 1
                processed_count += 1
                failed_user_ids.append(user_id)

                # 调用进度回调
                if progress_callback:
                    await progress_callback(success_count + fail_count, total)

        result = {
            'success': success_count,
            'fail': fail_count,
            'total': total,
            'processed': processed_count,
            'stopped': stopped,
            'failed_user_ids': failed_user_ids
        }

        logger.info(f"[USER_BROADCAST] 发送完成：成功{success_count}/{total}，失败{fail_count}")
        return result

    @staticmethod
    async def build_broadcast_summary(
        broadcast_target: str,
        success_count: int = 0,
        fail_count: int = 0,
        total_count: int = 0
    ) -> str:
        """
        构建广播摘要消息

        Args:
            broadcast_target: 广播目标 'this_bot' 或 'all_bots'
            success_count: 成功数量
            fail_count: 失败数量
            total_count: 总数

        Returns:
            摘要消息文本
        """
        message = "🎉 <b>广播发送完成</b>\n\n"

        # 广播目标
        if broadcast_target == 'this_bot':
            message += "📊 目标用户：当前Bot的所有用户\n"
        elif broadcast_target == 'all_bots':
            message += "📊 目标用户：所有Bot的所有用户\n"

        # 统计信息
        message += f"\n📈 发送统计：\n"
        message += f"• 目标用户：<b>{total_count}</b> 人\n"
        message += f"• 发送成功：<b>{success_count}</b> 人\n"

        if fail_count > 0:
            message += f"• 发送失败：<b>{fail_count}</b> 人（含用户已屏蔽/封禁）\n"

        message += f"\n✅ 发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        return message

"""
Token检测服务 - 提供Token有效性检测、失效处理、重绑流程等功能

三层检测机制：
1. 用户点击【创建续费】/【个人中心】时检测
2. 用户触发关键命令时检测
3. 后台心跳任务定时检测
"""
import logging
import re
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any
from sqlalchemy import select

from telegram import Update
from telegram.ext import ContextTypes

from ..models import get_db_session, BotCreation, TokenCheckLog
from ..utils.token_encryptor import token_encryptor

logger = logging.getLogger(__name__)

# 超级管理员ID
SUPER_ADMIN_ID = 7862093562

# Token格式正则
TOKEN_PATTERN = re.compile(r'^\d+:[\w-]+$')

# 判定失效的HTTP状态码
INVALID_TOKEN_CODES = {401, 404}

# 限流状态码
RATE_LIMIT_CODES = {429}


class TokenCheckService:
    """Token检测服务"""

    @staticmethod
    def _write_rebound_env(bot: BotCreation, token: str, bot_username: str):
        if not bot or not bot.instance_id:
            return

        instance_dir = Path(bot.instance_dir) if bot.instance_dir else None
        if not instance_dir or not instance_dir.exists():
            project_root = Path(__file__).resolve().parents[2]
            for candidate in (
                project_root / "instances" / bot.instance_id,
                project_root / "bot_instances" / bot.instance_id,
            ):
                if candidate.exists():
                    instance_dir = candidate
                    break

        if not instance_dir:
            logger.warning("[TOKEN_REBIND] No instance directory found for %s", bot.instance_id)
            return

        try:
            from .env_generator import generate_env_content

            env_path = instance_dir / ".env"
            env_content = generate_env_content(
                bot_token=token,
                instance_id=bot.instance_id,
                bot_owner_id=int(bot.telegram_id),
                bot_username=bot_username or bot.bot_username or "",
                super_admin_id=int(bot.super_admin_id or SUPER_ADMIN_ID),
            )
            env_path.write_text(env_content, encoding="utf-8")
            logger.info("[TOKEN_REBIND] Updated .env for %s at %s", bot.instance_id, env_path)
        except Exception as e:
            logger.error("[TOKEN_REBIND] Failed to update .env for %s: %s", bot.instance_id, e, exc_info=True)

    @staticmethod
    async def check_token(bot_id: str, check_type: str = 'command', user_id: int = None) -> Tuple[bool, Optional[str]]:
        """
        检测Bot Token是否有效
        
        Args:
            bot_id: Bot实例ID
            check_type: 检测类型: renew / profile / command / heartbeat / rebind
            user_id: 触发检测的用户ID
            
        Returns:
            (是否有效, 错误信息)
        """
        async with get_db_session() as db:
            query = BotCreation.__table__.select().where(BotCreation.instance_id == bot_id)
            result = await db.execute(query)
            bot = result.mappings().first()
            
            if not bot:
                await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', 'Bot not found')
                return False, 'Bot不存在'
            
            encrypted_token = bot['bot_token']
            if not encrypted_token:
                await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', 'Token not found')
                return False, 'Token不存在'
            
            try:
                token = token_encryptor.decrypt_from_base64(encrypted_token)
            except Exception as e:
                logger.error(f"Failed to decrypt token for bot {bot_id}: {e}")
                await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', 'Token decrypt failed')
                return False, 'Token解密失败'
            
            return await TokenCheckService._verify_token(db, bot_id, token, check_type, user_id)
    
    @staticmethod
    async def _verify_token(db, bot_id: str, token: str, check_type: str, user_id: int = None) -> Tuple[bool, Optional[str]]:
        """
        调用Telegram API验证Token
        
        Returns:
            (是否有效, 错误信息)
        """
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                result = response.json()
                
                if result.get('ok'):
                    await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'success', None)
                    await TokenCheckService._update_token_status(db, bot_id, 'normal', None)
                    return True, None
                else:
                    error_code = result.get('error_code')
                    description = result.get('description', 'Unknown error')
                    
                    # 判断是否是限流
                    if error_code in RATE_LIMIT_CODES:
                        # 429限流不判定为失效，只是暂时无法验证
                        await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', f"Rate limited: {description}")
                        return True, None  # 限流时不判定失效
                    
                    # 判断是否是Token失效
                    if error_code in INVALID_TOKEN_CODES or 'invalid' in description.lower():
                        await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', description)
                        await TokenCheckService._update_token_status(db, bot_id, 'invalid', description)
                        return False, description
                    
                    # 其他错误也不判定为失效
                    await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', description)
                    return True, None
                    
        except httpx.HTTPError as e:
            # 网络错误不判定为失效
            logger.warning(f"Network error checking token for bot {bot_id}: {e}")
            await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', f"Network error: {str(e)}")
            return True, None
        except Exception as e:
            logger.error(f"Unexpected error checking token for bot {bot_id}: {e}")
            await TokenCheckService._write_log(db, bot_id, user_id, check_type, 'failed', str(e))
            return True, None
    
    @staticmethod
    async def _write_log(db, bot_id: str, user_id: Optional[int], check_type: str, status: str, error_message: Optional[str]):
        """写入检测日志"""
        log = TokenCheckLog(
            bot_id=bot_id,
            user_id=user_id,
            check_type=check_type,
            status=status,
            error_message=error_message[:1000] if error_message else None
        )
        db.add(log)
        await db.flush()
    
    @staticmethod
    async def _update_token_status(db, bot_id: str, status: str, reason: Optional[str]):
        """更新Token状态"""
        await db.execute(
            BotCreation.__table__.update()
            .where(BotCreation.instance_id == bot_id)
            .values(
                token_status=status,
                token_invalid_reason=reason,
                token_checked_at=datetime.utcnow()
            )
        )
        await db.flush()
    
    @staticmethod
    async def handle_token_invalid(bot_id: str, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """
        处理Token失效情况
        
        1. 更新token_status = invalid
        2. 写入token_check_logs
        3. 设置rebind_status = waiting
        4. 通知用户
        """
        async with get_db_session() as db:
            # 更新状态
            await db.execute(
                BotCreation.__table__.update()
                .where(BotCreation.instance_id == bot_id)
                .values(
                    token_status='invalid',
                    lifecycle_status='SUSPENDED',
                    status='stopped',
                    token_checked_at=datetime.utcnow(),
                    rebind_status='waiting',
                    rebind_user_id=user_id,
                    rebind_started_at=datetime.utcnow()
                )
            )
            
            # 写入日志
            await TokenCheckService._write_log(db, bot_id, user_id, 'invalid', 'failed', 'Token invalid')
            
            await db.commit()

        try:
            from ..services.bot_instance_manager import bot_instance_manager
            await bot_instance_manager.stop_bot_instance(bot_id)
        except Exception as e:
            logger.error(f"Failed to stop bot after token invalidation for {bot_id}: {e}", exc_info=True)
    
    @staticmethod
    async def can_rebind(bot_id: str, user_id: int) -> bool:
        """
        检查用户是否有权限重绑Token
        
        Returns:
            True: 有权限
            False: 无权限
        """
        if user_id == SUPER_ADMIN_ID:
            return True
        
        async with get_db_session() as db:
            query = BotCreation.__table__.select().where(BotCreation.instance_id == bot_id)
            result = await db.execute(query)
            bot = result.mappings().first()
            
            if bot and (bot['super_admin_id'] == user_id or bot['telegram_id'] == user_id):
                return True
            
            return False
    
    @staticmethod
    async def process_rebind_token(bot_id: str, user_id: int, new_token: str) -> Tuple[bool, str]:
        return await TokenCheckService._process_rebind_token_v2(bot_id, user_id, new_token)

    @staticmethod
    async def _process_rebind_token_v2(bot_id: str, user_id: int, new_token: str) -> Tuple[bool, str]:
        """处理 Token 重绑，保留原实例、群组权限、到期时间和数据。"""
        if not bot_id:
            return False, '重绑状态已结束'

        if not await TokenCheckService.can_rebind(bot_id, user_id):
            return False, '您没有权限执行此操作'

        if not TOKEN_PATTERN.match(new_token):
            return False, 'Token格式不正确，请检查后重新输入'

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"https://api.telegram.org/bot{new_token}/getMe")
                result = response.json()

            if not result.get('ok'):
                description = result.get('description', 'Token无效')
                return False, f"Token无效: {description}"

            bot_info = result.get('result', {})
            bot_name = bot_info.get('first_name', '未知')
            bot_username = bot_info.get('username', '')
        except Exception as e:
            logger.error(f"Failed to verify new token: {e}", exc_info=True)
            return False, f"验证Token失败: {str(e)}"

        async with get_db_session() as db:
            encrypted_new_token = token_encryptor.encrypt_to_base64(new_token)

            result = await db.execute(
                select(BotCreation).where(
                    BotCreation.bot_token == encrypted_new_token,
                    BotCreation.instance_id != bot_id
                )
            )
            if result.scalar_one_or_none():
                return False, '此Token已被其他机器人使用'

            result = await db.execute(select(BotCreation).where(BotCreation.instance_id == bot_id))
            bot_record = result.scalar_one_or_none()
            if not bot_record:
                return False, '重绑状态已结束'

            waiting_for_user = (
                bot_record.rebind_status == 'waiting'
                and bot_record.rebind_user_id == user_id
            )
            invalid_or_stopped = (
                str(bot_record.token_status or '').lower() == 'invalid'
                or str(bot_record.lifecycle_status or '').upper() == 'SUSPENDED'
                or str(bot_record.status or '').lower() in {'stopped', 'error', 'failed'}
            )
            if not waiting_for_user and not invalid_or_stopped:
                return False, '重绑状态已结束'

            TokenCheckService._write_rebound_env(bot_record, new_token, bot_username)

            bot_record.bot_token = encrypted_new_token
            bot_record.bot_name = bot_name
            bot_record.bot_username = bot_username
            bot_record.token_status = 'normal'
            bot_record.lifecycle_status = 'ACTIVE'
            bot_record.status = 'running'
            bot_record.token_invalid_reason = None
            bot_record.token_checked_at = datetime.utcnow()
            bot_record.rebind_status = 'none'
            bot_record.rebind_user_id = None
            bot_record.rebind_started_at = None

            await TokenCheckService._write_log(db, bot_id, user_id, 'rebind', 'success', None)
            await db.commit()

            try:
                from ..services.bot_instance_manager import bot_instance_manager
                await bot_instance_manager.start_bot_instance(bot_record)
            except Exception as e:
                logger.error(f"Failed to restart bot after token rebind for {bot_id}: {e}", exc_info=True)

            return True, bot_name

    @staticmethod
    async def _process_rebind_token_legacy(bot_id: str, user_id: int, new_token: str) -> Tuple[bool, str]:
        # Deprecated duplicate kept temporarily for later deletion.
        """
        处理Token重绑
        
        Args:
            bot_id: Bot实例ID
            user_id: 用户ID
            new_token: 新Token
            
        Returns:
            (是否成功, 消息)
        """
        # 校验权限
        if not await TokenCheckService.can_rebind(bot_id, user_id):
            return False, '您没有权限执行此操作'
        
        # 校验Token格式
        if not TOKEN_PATTERN.match(new_token):
            return False, 'Token格式不正确，请检查后重新输入'
        
        # 验证Token是否有效
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"https://api.telegram.org/bot{new_token}/getMe")
                result = response.json()
                
                if not result.get('ok'):
                    error_code = result.get('error_code')
                    description = result.get('description', 'Token无效')
                    return False, f"Token无效: {description}"
                
                bot_info = result.get('result', {})
                bot_name = bot_info.get('first_name', '未知')
                bot_username = bot_info.get('username', '')
        except Exception as e:
            logger.error(f"Failed to verify new token: {e}")
            return False, f"验证Token失败: {str(e)}"
        
        # 检查新Token是否已被其他Bot使用
        async with get_db_session() as db:
            # 检查Token是否已存在
            encrypted_new_token = token_encryptor.encrypt_to_base64(new_token)
            
            query = BotCreation.__table__.select().where(
                BotCreation.bot_token == encrypted_new_token,
                BotCreation.instance_id != bot_id
            )
            result = await db.execute(query)
            if result.first():
                return False, '此Token已被其他机器人使用'
            
            # 检查是否正在重绑中
            query = BotCreation.__table__.select().where(
                BotCreation.instance_id == bot_id,
                BotCreation.rebind_status == 'waiting',
                BotCreation.rebind_user_id == user_id
            )
            result = await db.execute(query)
            if not result.first():
                return False, '重绑状态已结束'
            
            # 更新Bot记录
            await db.execute(
                BotCreation.__table__.update()
                .where(BotCreation.instance_id == bot_id)
                .values(
                    bot_token=encrypted_new_token,
                    bot_name=bot_name,
                    bot_username=bot_username,
                    token_status='normal',
                    lifecycle_status='ACTIVE',
                    status='running',
                    token_invalid_reason=None,
                    token_checked_at=datetime.utcnow(),
                    rebind_status='none',
                    rebind_user_id=None,
                    rebind_started_at=None
                )
            )
            
            # 写入日志
            await TokenCheckService._write_log(db, bot_id, user_id, 'rebind', 'success', None)
            
            await db.commit()

            try:
                from ..services.bot_instance_manager import bot_instance_manager
                result = await db.execute(select(BotCreation).where(BotCreation.instance_id == bot_id))
                updated_bot = result.scalar_one_or_none()
                if updated_bot:
                    await bot_instance_manager.start_bot_instance(updated_bot)
            except Exception as e:
                logger.error(f"Failed to restart bot after token rebind for {bot_id}: {e}", exc_info=True)

            return True, bot_name
    
    @staticmethod
    async def cancel_rebind(bot_id: str):
        """取消重绑状态"""
        async with get_db_session() as db:
            await db.execute(
                BotCreation.__table__.update()
                .where(BotCreation.instance_id == bot_id)
                .values(
                    rebind_status='none',
                    rebind_user_id=None,
                    rebind_started_at=None
                )
            )
            await db.commit()
    
    @staticmethod
    async def get_bot_info(bot_id: str) -> Optional[Dict[str, Any]]:
        """获取Bot信息"""
        async with get_db_session() as db:
            query = BotCreation.__table__.select().where(BotCreation.instance_id == bot_id)
            result = await db.execute(query)
            bot = result.mappings().first()
            
            if bot:
                return {
                    'bot_name': bot['bot_name'] or bot['bot_username'] or '未知',
                    'bot_id': bot['instance_id'],
                    'expire_time': bot['expire_time'],
                    'token_status': bot['token_status'],
                    'rebind_status': bot['rebind_status'],
                    'rebind_user_id': bot['rebind_user_id'],
                    'super_admin_id': bot['super_admin_id']
                }
            return None
    
    @staticmethod
    async def should_notify_user(bot_id: str) -> bool:
        """检查是否应该通知用户（24小时内最多通知一次）"""
        async with get_db_session() as db:
            query = BotCreation.__table__.select().where(BotCreation.instance_id == bot_id)
            result = await db.execute(query)
            bot = result.mappings().first()
            
            if not bot:
                return False
            
            last_notified = bot['token_invalid_notified_at']
            if last_notified:
                if datetime.utcnow() - last_notified < timedelta(hours=24):
                    return False
            
            return True
    
    @staticmethod
    async def update_notified_time(bot_id: str):
        """更新通知时间"""
        async with get_db_session() as db:
            await db.execute(
                BotCreation.__table__.update()
                .where(BotCreation.instance_id == bot_id)
                .values(token_invalid_notified_at=datetime.utcnow())
            )
            await db.commit()
    
    @staticmethod
    async def heartbeat_check():
        """后台心跳检测任务"""
        logger.info("Starting token heartbeat check...")
        
        async with get_db_session() as db:
            # 查询需要检测的Bot
            four_hours_ago = datetime.utcnow() - timedelta(hours=4)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            
            query = BotCreation.__table__.select().where(
                BotCreation.lifecycle_status == 'ACTIVE',
                (BotCreation.last_activity_at >= seven_days_ago) | (BotCreation.last_activity_at.is_(None)),
                (BotCreation.token_status != 'invalid') | (BotCreation.token_checked_at.is_(None)) | (BotCreation.token_checked_at < four_hours_ago)
            )
            result = await db.execute(query)
            bots = result.mappings().all()
            
            logger.info(f"Found {len(bots)} bots to check")
            
            for bot in bots:
                bot_id = bot['instance_id']
                logger.debug(f"Checking token for bot {bot_id}")
                
                try:
                    encrypted_token = bot['bot_token']
                    if encrypted_token:
                        try:
                            token = token_encryptor.decrypt_from_base64(encrypted_token)
                            await TokenCheckService._verify_token(db, bot_id, token, 'heartbeat', None)
                        except Exception as e:
                            logger.error(f"Failed to check token for bot {bot_id}: {e}")
                    
                    # 限制检测频率，避免限流
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error checking bot {bot_id}: {e}")
        
        logger.info("Token heartbeat check completed")


token_check_service = TokenCheckService()

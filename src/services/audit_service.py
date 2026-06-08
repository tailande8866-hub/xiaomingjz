"""
审计日志服务（轻量级）

职责：快速记录关键操作
"""
import logging
from typing import Dict, Optional, Any
from ..models.audit_log import AuditLog
from ..models.database import get_db

logger = logging.getLogger(__name__)


class AuditService:
    """审计日志服务（单例）"""
    
    async def log(
        self,
        user_id: int,
        action: str,
        bot_id: Optional[str] = None,
        username: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ):
        """
        记录审计日志
        
        Args:
            user_id: 用户 ID
            action: 操作类型（例如："admin.add", "bot.create"）
            bot_id: Bot instance_id
            username: 用户名
            details: 操作详情（JSON）
            status: 操作状态（success/failed）
            error_message: 错误信息
        """
        try:
            audit_log = AuditLog(
                user_id=user_id,
                username=username,
                bot_id=bot_id,
                action=action,
                details=details,
                status=status,
                error_message=error_message,
            )
            
            async for db in get_db():
                db.add(audit_log)
                await db.commit()
                logger.debug(f"Audit log: user={user_id}, action={action}, status={status}")
                break
                
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}", exc_info=True)
            # 审计日志失败不应该影响主业务流程


# 全局单例
audit_service = AuditService()

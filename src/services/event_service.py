"""
Event Service - 金融审计事件服务

所有交易相关操作都会通过此服务记录事件
用于：审计、风控、对账、监控、数据分析

核心原则：
- Append-only（只增不改）
- 不允许 UPDATE/DELETE
- 完整的事件流（Event Stream）
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from ..models.transaction_event import TransactionEvent, TransactionEventType, ActorType

logger = logging.getLogger(__name__)


class EventService:
    """
    事件服务类
    
    负责记录所有交易相关事件
    所有方法都是 append-only，不修改历史数据
    """
    
    @staticmethod
    async def log_event(
        db,
        bot_id: str,
        trace_id: str,
        event_type: TransactionEventType,
        group_id: int,
        transaction_id: Optional[int] = None,
        parent_trace_id: Optional[str] = None,
        operator_id: Optional[int] = None,
        actor_type: ActorType = ActorType.USER,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TransactionEvent:
        """
        记录事件（通用方法）
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
            trace_id: 交易追踪ID
            event_type: 事件类型
            group_id: 群组ID
            transaction_id: 关联的交易ID
            parent_trace_id: 父交易trace_id
            operator_id: 操作者ID
            actor_type: 参与者类型
            old_status: 旧状态
            new_status: 新状态
            metadata: 元数据
            
        Returns:
            创建的事件对象
        """
        event = TransactionEvent(
            event_id=str(uuid.uuid4()),
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            bot_id=bot_id,
            transaction_id=transaction_id,
            group_id=group_id,
            event_type=event_type.value,
            old_status=old_status,
            new_status=new_status,
            operator_id=operator_id,
            actor_type=actor_type.value,
            event_data=metadata or {},
            created_at=datetime.utcnow()
        )
        
        db.add(event)
        await db.commit()
        await db.refresh(event)
        
        logger.info(
            f"[BOT:{bot_id}] Event logged: type={event_type.value}, "
            f"trace_id={trace_id}, event_id={event.event_id}"
        )
        
        return event
    
    @staticmethod
    async def log_transaction_created(
        db,
        bot_id: str,
        trace_id: str,
        transaction_id: int,
        group_id: int,
        operator_id: int,
        amount: float,
        currency: str,
        transaction_type: str
    ):
        """记录交易创建事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            event_type=TransactionEventType.CREATED,
            group_id=group_id,
            transaction_id=transaction_id,
            operator_id=operator_id,
            actor_type=ActorType.USER,
            metadata={
                "amount": amount,
                "currency": currency,
                "transaction_type": transaction_type
            }
        )
    
    @staticmethod
    async def log_transaction_revoked(
        db,
        bot_id: str,
        trace_id: str,
        parent_trace_id: str,
        transaction_id: int,
        reversal_transaction_id: int,
        group_id: int,
        operator_id: int,
        reason: str = ""
    ):
        """记录交易撤销事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            event_type=TransactionEventType.REVOKED,
            group_id=group_id,
            transaction_id=transaction_id,
            operator_id=operator_id,
            actor_type=ActorType.USER,
            metadata={
                "reversal_transaction_id": reversal_transaction_id,
                "reason": reason
            }
        )
    
    @staticmethod
    async def log_idempotency_blocked(
        db,
        bot_id: str,
        trace_id: str,
        idempotency_key: str,
        group_id: int,
        existing_transaction_id: int
    ):
        """记录幂等拦截事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            event_type=TransactionEventType.RETRY_BLOCKED,
            group_id=group_id,
            transaction_id=existing_transaction_id,
            actor_type=ActorType.SYSTEM,
            metadata={
                "idempotency_key": idempotency_key,
                "message": "Duplicate request blocked by idempotency check"
            }
        )
    
    @staticmethod
    async def log_transaction_failed(
        db,
        bot_id: str,
        trace_id: str,
        group_id: int,
        error_message: str,
        operator_id: Optional[int] = None
    ):
        """记录交易失败事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            event_type=TransactionEventType.FAILED,
            group_id=group_id,
            operator_id=operator_id,
            actor_type=ActorType.SYSTEM,
            metadata={
                "error": error_message
            }
        )
    
    @staticmethod
    async def log_query(
        db,
        bot_id: str,
        trace_id: str,
        group_id: int,
        operator_id: int,
        query_params: Optional[Dict[str, Any]] = None
    ):
        """记录查询事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            event_type=TransactionEventType.QUERY,
            group_id=group_id,
            operator_id=operator_id,
            actor_type=ActorType.USER,
            metadata=query_params or {}
        )
    
    @staticmethod
    async def log_export(
        db,
        bot_id: str,
        trace_id: str,
        group_id: int,
        operator_id: int,
        export_format: str = "csv"
    ):
        """记录导出事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            event_type=TransactionEventType.EXPORT,
            group_id=group_id,
            operator_id=operator_id,
            actor_type=ActorType.USER,
            metadata={
                "format": export_format
            }
        )
    
    @staticmethod
    async def log_status_changed(
        db,
        bot_id: str,
        trace_id: str,
        transaction_id: int,
        group_id: int,
        old_status: str,
        new_status: str,
        operator_id: Optional[int] = None,
        reason: str = ""
    ):
        """记录状态变更事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            event_type=TransactionEventType.STATUS_CHANGED,
            group_id=group_id,
            transaction_id=transaction_id,
            operator_id=operator_id,
            actor_type=ActorType.SYSTEM if not operator_id else ActorType.USER,
            old_status=old_status,
            new_status=new_status,
            metadata={
                "reason": reason
            }
        )
    
    @staticmethod
    async def log_summary_updated(
        db,
        bot_id: str,
        trace_id: str,
        group_id: int,
        summary_data: Dict[str, Any]
    ):
        """记录汇总更新事件"""
        return await EventService.log_event(
            db=db,
            bot_id=bot_id,
            trace_id=trace_id,
            event_type=TransactionEventType.SUMMARY_UPDATED,
            group_id=group_id,
            actor_type=ActorType.SYSTEM,
            metadata=summary_data
        )

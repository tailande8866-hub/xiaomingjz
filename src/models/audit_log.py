"""
审计日志模型（轻量级）

职责：记录所有关键操作，用于安全审计和问题追踪。
"""
from sqlalchemy import Column, Integer, String, DateTime, JSON, Index
from sqlalchemy.sql import func
from .database import Base


class AuditLog(Base):
    """审计日志表（简化版）"""
    
    __tablename__ = 'audit_logs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    bot_id = Column(String(64), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)  # 操作类型
    details = Column(JSON, nullable=True)  # 操作详情
    status = Column(String(20), nullable=False, default='success')  # success/failed
    error_message = Column(String(500), nullable=True)
    
    __table_args__ = (
        Index('idx_audit_user_action', 'user_id', 'action'),
        Index('idx_audit_bot_action', 'bot_id', 'action'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'user_id': self.user_id,
            'username': self.username,
            'bot_id': self.bot_id,
            'action': self.action,
            'details': self.details,
            'status': self.status,
            'error_message': self.error_message,
        }

"""
群组成员索引模型
用于记录群里发送过消息的用户，支持 @username 添加操作人
多租户隔离：bot_id + group_id + username 联合唯一索引
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class GroupMemberIndex(Base):
    """群组成员索引 - 记录群里发送过消息的用户（多租户隔离）"""
    __tablename__ = "group_member_index"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 群组信息
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID")
    
    # 用户信息
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户Telegram ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), index=True, comment="用户名（小写，不带@）")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), comment="用户名字")
    
    # 时间戳
    last_seen_at: Mapped[datetime] = mapped_column(default=datetime.now, comment="最后活动时间")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now, comment="首次记录时间")
    
    # 创建唯一索引（bot_id, group_id, username 联合索引，username 小写）
    __table_args__ = (
        Index('idx_bot_group_username', 'bot_id', 'group_id', 'username', unique=True),
        Index('idx_bot_group_user', 'bot_id', 'group_id', 'user_id', unique=True),
    )
    
    def __repr__(self):
        return f"<GroupMemberIndex(bot_id={self.bot_id}, group_id={self.group_id}, user_id={self.user_id}, username={self.username})>"

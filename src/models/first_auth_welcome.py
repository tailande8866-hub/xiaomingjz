"""
首次授权欢迎语配置模型 - 多租户隔离
"""
from typing import Optional
from sqlalchemy import String, BigInteger, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class FirstAuthWelcomeConfig(Base):
    """首次授权欢迎语配置模型 - 多租户隔离
    
    用于存储当超管/管理员拉 Bot 进群时自动发送的欢迎语配置
    每个 bot_id 只有一条配置记录
    """
    __tablename__ = "first_auth_welcome_configs"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(
        String(50), 
        index=True, 
        unique=True,
        comment="所属机器人实例ID（唯一约束，每个Bot只有一条配置）"
    )
    
    # 欢迎语内容
    welcome_text: Mapped[Optional[str]] = mapped_column(
        String(1000), 
        nullable=True, 
        default="",
        comment="欢迎语文本内容（支持占位符：{username}、{group_name}）"
    )
    
    # 消息类型配置
    welcome_type: Mapped[str] = mapped_column(
        String(20), 
        default="text",
        comment="消息类型: text/photo/video/animation"
    )
    
    # 媒体文件配置
    file_id: Mapped[Optional[str]] = mapped_column(
        String(255), 
        nullable=True,
        comment="媒体文件ID（Telegram file_id）"
    )
    
    caption: Mapped[Optional[str]] = mapped_column(
        String(1000), 
        nullable=True,
        comment="媒体说明文字"
    )
    
    parse_mode: Mapped[Optional[str]] = mapped_column(
        String(10), 
        nullable=True, 
        default="HTML",
        comment="解析模式: HTML/Markdown"
    )
    
    # 开关配置
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, 
        default=False,
        comment="是否启用首次授权欢迎语"
    )
    
    # 审计字段
    updated_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, 
        nullable=True,
        comment="最后更新者用户ID"
    )

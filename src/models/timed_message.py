"""Timed message settings and send logs."""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TimedMessageSetting(Base):
    """Dual-mode timed message setting."""

    __tablename__ = "timed_message_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)  # global / group
    group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)  # GroupTag.id for group scope
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class TimedMessageSendLog(Base):
    """Timed message delivery log."""

    __tablename__ = "timed_message_send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    target_group_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success / failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

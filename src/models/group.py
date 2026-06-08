"""
群组相关数据模型
"""
from datetime import datetime, time
from typing import Optional
from sqlalchemy import String, BigInteger, Boolean, Float, Integer, Time, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .enums import GroupStatus


# ============================================================================
# 系统常量定义
# ============================================================================

# 默认广播分组名称（系统内置，不可删除、不可重命名）
DEFAULT_BROADCAST_GROUP_TAG = "默认"


class Group(Base):
    """群组模型 - 多租户隔离"""
    __tablename__ = "groups"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 基本信息
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="Telegram群组ID")
    group_name: Mapped[str] = mapped_column(String(255), comment="群组名称")
    group_type: Mapped[str] = mapped_column(String(50), default="group", comment="群组类型: group, supergroup, channel")

    # 状态配置
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="记账是否开启")
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否禁言模式（下课）")

    # 显示配置
    display_mode: Mapped[str] = mapped_column(String(20), default="pure", comment="显示模式: pure(纯净), reply(显示回复人), operator(显示操作人)")
    currency_mode: Mapped[str] = mapped_column(String(20), default="single", comment="币种模式: single(单币), dual(双币)")
    currency_display: Mapped[str] = mapped_column(String(10), default="USDT", comment="显示的币种")
    pin_enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用置顶")
    deposit_display_count: Mapped[int] = mapped_column(Integer, default=5, comment="入款显示条数")
    withdraw_display_count: Mapped[int] = mapped_column(Integer, default=5, comment="下发显示条数")
    category_enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用账单分类")

    # 参数配置
    exchange_rate: Mapped[float] = mapped_column(Float, default=7.3, comment="默认汇率")
    fee_rate: Mapped[float] = mapped_column(Float, default=3, comment="默认费率(%)")
    real_time_rate: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否使用实时汇率")

    # 日切配置
    day_cut_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True, comment="日切时间")
    last_day_cut: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="上次日切时间")

    # 操作人配置
    all_members_operator: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否全员可操作")

    # 其他配置
    group_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="分组标签")
    withdraw_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="下发地址")

    # 广告配置
    top_ad: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="顶部广告")
    welcome_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="欢迎广告语")
    
    # 📡 广播分组
    broadcast_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="所属广播分组 ID")
    
    # 👤 邀请者信息（拉 bot 进群的用户）
    invited_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="邀请 bot 进群的用户ID")
    invited_by_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="邀请者用户名")
    
    # 🔐 群组状态（SaaS 生命周期管理）
    status: Mapped[str] = mapped_column(String(20), default=GroupStatus.PENDING.value, comment="群组状态: PENDING/ACTIVE/UNAUTHORIZED/EXPIRED/DISABLED")
    
    # 🎉 首次授权欢迎语标记
    first_welcome_sent: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已发送首次授权欢迎语")
    
    # ⚠️ 取消授权提示标记（只发送一次）
    unauthorized_notice_sent: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已发送取消授权提示")
    
    # 👋 入群欢迎语配置（新用户进群时发送）
    join_welcome_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="入群欢迎语（群组级别，覆盖全局）")
    join_welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用入群欢迎语")
    
    # ️ 冒充管理员检测配置
    impersonation_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用冒充管理员检测")
    
    #  入群欢迎语媒体配置
    join_welcome_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="text", comment="欢迎语类型: text/photo/video/animation/document")
    join_welcome_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="媒体文件ID（Telegram file_id）")
    join_welcome_caption: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="媒体说明文字")
    join_welcome_parse_mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, comment="解析模式: HTML/Markdown")


class GroupOperator(Base):
    """群组操作人模型 - 多租户隔离"""
    __tablename__ = "group_operators"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名字")
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否全局操作人")


class UserConfig(Base):
    """用户个人配置模型（群组内）- 多租户隔离"""
    __tablename__ = "user_configs"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名字")

    # 个人费率配置
    exchange_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="个人汇率")
    fee_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="个人费率(%)")


class PrivateChatUser(Base):
    """私聊用户模型 - 记录所有和机器人私聊过的用户（多租户隔离）"""
    __tablename__ = "private_chat_users"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="Telegram用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名字")
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="姓氏")
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, comment="语言代码")
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否为机器人")


class CustomKeyword(Base):
    """自定义关键词回复模型 - 多租户隔离"""
    __tablename__ = "custom_keywords"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID（0表示全局关键词）")
    keyword: Mapped[str] = mapped_column(String(100), comment="关键词")
    reply_text: Mapped[str] = mapped_column(String(1000), comment="回复内容")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    created_by: Mapped[int] = mapped_column(BigInteger, index=True, comment="创建者用户ID")


class CustomButton(Base):
    """自定义按钮模型 - 多租户隔离"""
    __tablename__ = "custom_buttons"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID（0表示全局按钮）")
    button_text: Mapped[str] = mapped_column(String(100), comment="按钮文本")
    button_url: Mapped[str] = mapped_column(String(500), comment="按钮链接")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序顺序")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    created_by: Mapped[int] = mapped_column(BigInteger, index=True, comment="创建者用户ID")


class AdminGlobalConfig(Base):
    """管理员全局配置模型 - 用于存储机器人的全局默认设置"""
    __tablename__ = "admin_global_configs"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 配置键值对
    config_key: Mapped[str] = mapped_column(String(100), index=True, comment="配置键")
    config_value: Mapped[str] = mapped_column(String(1000), comment="配置值（JSON格式）")
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="配置说明")
    updated_by: Mapped[int] = mapped_column(BigInteger, comment="最后更新者用户ID")
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, comment="更新时间")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")

    __table_args__ = (
        UniqueConstraint('bot_id', 'config_key', name='uix_bot_config_key'),
    )


class GroupTag(Base):
    """分组标签模型 - 多租户隔离"""
    __tablename__ = "group_tags"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")

    tag_name: Mapped[str] = mapped_column(String(50), comment="分组名称")
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="分组描述")
    created_by: Mapped[int] = mapped_column(BigInteger, comment="创建者用户ID")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")


class ImpersonationWhitelist(Base):
    """冒充管理员白名单模型 - 多租户隔离"""
    __tablename__ = "impersonation_whitelist"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="Telegram用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="昵称")
    added_by: Mapped[int] = mapped_column(BigInteger, comment="添加者用户ID")
    added_at: Mapped[datetime] = mapped_column(default=datetime.now, comment="添加时间")
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="添加原因")


class AdminNicknameCache(Base):
    """管理员昵称缓存表 - 用于冒充管理员检测"""
    __tablename__ = "admin_nickname_cache"

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID")
    admin_user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="管理员用户ID")
    admin_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="管理员用户名")
    admin_nickname: Mapped[str] = mapped_column(String(255), comment="管理员昵称")
    admin_status: Mapped[str] = mapped_column(String(50), comment="管理员身份(creator/administrator)")
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now, comment="更新时间")


class TopicForwardMap(Base):
    """群组话题模式消息映射 - 用于管理员在群里回复后转回私聊用户"""
    __tablename__ = "topic_forward_maps"

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    target_group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="转发目标群组ID")
    group_message_id: Mapped[int] = mapped_column(Integer, index=True, comment="目标群组中的消息ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="私聊用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="私聊用户名")


class AdSettings(Base):
    """广告配置模型 - 多租户隔离"""
    __tablename__ = "ad_settings"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 广告状态
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="广告是否启用")
    
    # 抬头广告
    header_text: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="抬头广告文本")
    header_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="抬头广告链接")
    
    # 尾页广告
    footer_text: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="尾页广告文本")
    footer_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="尾页广告链接")
    
    # 🎯 唯一约束：每个 bot 只有一条配置记录
    __table_args__ = (
        UniqueConstraint('bot_id', name='uix_ad_settings_bot_id'),
    )


class AdButton(Base):
    """广告按钮模型 - 多租户隔离"""
    __tablename__ = "ad_buttons"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 按钮配置
    button_text: Mapped[str] = mapped_column(String(100), comment="按钮文本")
    button_url: Mapped[str] = mapped_column(String(500), comment="按钮链接")
    
    # 排序和状态
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序顺序")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    
    # 创建信息
    created_by: Mapped[int] = mapped_column(BigInteger, comment="创建者用户ID")


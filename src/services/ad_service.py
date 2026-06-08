"""
广告服务类 - 处理广告配置和展示逻辑
"""
import logging
import re
from typing import List, Optional, Tuple
from sqlalchemy import select, and_

from ..models import get_db_session
from ..models.group import AdSettings, AdButton

logger = logging.getLogger(__name__)


class AdService:
    """广告服务类"""

    @staticmethod
    async def get_or_create_settings(db, bot_id: str) -> AdSettings:
        """
        获取或创建广告配置
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
            
        Returns:
            AdSettings 对象
        """
        query = select(AdSettings).where(AdSettings.bot_id == bot_id)
        result = await db.execute(query)
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = AdSettings(
                bot_id=bot_id,
                enabled=False,
                header_text=None,
                header_link=None,
                footer_text=None,
                footer_link=None
            )
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
            logger.info(f"[AD] Created new ad settings for bot: {bot_id}")
        
        return settings

    @staticmethod
    async def update_settings(db, bot_id: str, **kwargs) -> AdSettings:
        """
        更新广告配置
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
            **kwargs: 要更新的字段
            
        Returns:
            AdSettings 对象
        """
        settings = await AdService.get_or_create_settings(db, bot_id)
        
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        await db.commit()
        await db.refresh(settings)
        logger.info(f"[AD] Updated ad settings for bot: {bot_id}")
        return settings

    @staticmethod
    async def get_ad_buttons(db, bot_id: str) -> List[AdButton]:
        """
        获取广告按钮列表
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
            
        Returns:
            AdButton 列表
        """
        query = select(AdButton).where(
            and_(
                AdButton.bot_id == bot_id,
                AdButton.enabled.is_(True)
            )
        ).order_by(AdButton.sort_order)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def add_ad_button(
        db,
        bot_id: str,
        button_text: str,
        button_url: str,
        created_by: int
    ) -> AdButton:
        """
        添加广告按钮
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
            button_text: 按钮文本
            button_url: 按钮链接
            created_by: 创建者用户ID
            
        Returns:
            AdButton 对象
        """
        # 获取最大排序
        query = select(AdButton).where(AdButton.bot_id == bot_id)
        result = await db.execute(query)
        buttons = result.scalars().all()
        max_sort = max([b.sort_order for b in buttons], default=-1)
        
        button = AdButton(
            bot_id=bot_id,
            button_text=button_text,
            button_url=button_url,
            sort_order=max_sort + 1,
            enabled=True,
            created_by=created_by
        )
        db.add(button)
        await db.commit()
        await db.refresh(button)
        
        logger.info(f"[AD] Added new ad button for bot: {bot_id}")
        return button

    @staticmethod
    async def update_ad_button(
        db,
        button_id: int,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None
    ) -> Optional[AdButton]:
        """
        更新广告按钮
        
        Args:
            db: 数据库会话
            button_id: 按钮ID
            button_text: 新按钮文本
            button_url: 新按钮链接
            
        Returns:
            AdButton 对象或 None
        """
        query = select(AdButton).where(AdButton.id == button_id)
        result = await db.execute(query)
        button = result.scalar_one_or_none()
        
        if not button:
            return None
        
        if button_text is not None:
            button.button_text = button_text
        if button_url is not None:
            button.button_url = button_url
        
        await db.commit()
        await db.refresh(button)
        logger.info(f"[AD] Updated ad button: {button_id}")
        return button

    @staticmethod
    async def delete_ad_button(db, button_id: int) -> bool:
        """
        删除广告按钮
        
        Args:
            db: 数据库会话
            button_id: 按钮ID
            
        Returns:
            是否成功
        """
        query = select(AdButton).where(AdButton.id == button_id)
        result = await db.execute(query)
        button = result.scalar_one_or_none()
        
        if not button:
            return False
        
        await db.delete(button)
        await db.commit()
        logger.info(f"[AD] Deleted ad button: {button_id}")
        return True

    @staticmethod
    async def get_ad_button(db, button_id: int) -> Optional[AdButton]:
        """
        获取单个广告按钮
        
        Args:
            db: 数据库会话
            button_id: 按钮ID
            
        Returns:
            AdButton 对象或 None
        """
        query = select(AdButton).where(AdButton.id == button_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def validate_url(url: str) -> bool:
        """
        验证URL格式
        
        Args:
            url: 链接地址
            
        Returns:
            是否有效
        """
        if not url or not url.strip():
            return False
        
        url = url.strip()
        
        # 检查是否为@用户名
        if url.startswith('@') and len(url) > 1:
            return True
        
        # 检查是否为有效的http/https链接
        pattern = r'^https?://[^\s<>"\']+$'
        if re.match(pattern, url):
            return True
        
        return False

    @staticmethod
    def format_url_for_tg(url: str) -> str:
        """
        格式化URL以适应Telegram
        
        Args:
            url: 原始URL
            
        Returns:
            格式化后的URL
        """
        if not url:
            return url
        
        url = url.strip()
        
        # 处理@用户名
        if url.startswith('@'):
            # 直接返回，用于在文本中直接显示
            return url
        
        # 如果不是http开头，添加https://
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'https://' + url
        
        return url

    @staticmethod
    async def get_ad_content(db, bot_id: str) -> dict:
        """
        获取广告内容，用于账单显示
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
            
        Returns:
            包含广告内容的字典
        """
        settings = await AdService.get_or_create_settings(db, bot_id)
        
        if not settings.enabled:
            return {
                'enabled': False,
                'header_text': None,
                'header_link': None,
                'footer_text': None,
                'footer_link': None,
                'buttons': []
            }
        
        buttons = await AdService.get_ad_buttons(db, bot_id)
        
        return {
            'enabled': True,
            'header_text': settings.header_text,
            'header_link': settings.header_link,
            'footer_text': settings.footer_text,
            'footer_link': settings.footer_link,
            'buttons': [
                {
                    'text': b.button_text,
                    'url': AdService.format_url_for_tg(b.button_url)
                }
                for b in buttons
            ]
        }

    @staticmethod
    async def delete_all_ads(db, bot_id: str) -> None:
        """
        删除所有广告（清空配置）
        
        Args:
            db: 数据库会话
            bot_id: 机器人ID
        """
        # 删除按钮
        query = select(AdButton).where(AdButton.bot_id == bot_id)
        result = await db.execute(query)
        buttons = result.scalars().all()
        for button in buttons:
            await db.delete(button)
        
        # 重置配置
        settings = await AdService.get_or_create_settings(db, bot_id)
        settings.enabled = False
        settings.header_text = None
        settings.header_link = None
        settings.footer_text = None
        settings.footer_link = None
        
        await db.commit()
        logger.info(f"[AD] Cleared all ads for bot: {bot_id}")

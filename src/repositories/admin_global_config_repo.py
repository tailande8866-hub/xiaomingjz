"""
Admin Global Config Repository - 全局配置数据访问层

所有查询自动注入 bot_id，确保数据隔离
"""
from typing import Optional, Dict, Any, List
from sqlalchemy import select, and_
import json

from .base_repo import BaseRepo
from src.models.group import AdminGlobalConfig


class AdminGlobalConfigRepo(BaseRepo[AdminGlobalConfig]):
    """
    全局配置 Repository
    
    使用示例：
        repo = AdminGlobalConfigRepo(session, bot_id)
        
        # 获取配置
        config = await repo.get_config("welcome_message")
        
        # 设置配置
        await repo.set_config("welcome_message", {"text": "欢迎！"}, "欢迎语")
    """
    
    @property
    def model_class(self):
        return AdminGlobalConfig
    
    async def get_config(self, config_key: str) -> Optional[Dict[str, Any]]:
        """
        获取全局配置
        
        Args:
            config_key: 配置键
            
        Returns:
            配置值的字典或 None
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    self.model_class.config_key == config_key,
                    self.model_class.is_active.is_(True)
                )
            )
        )
        result = await self.session.execute(stmt)
        config = result.scalar_one_or_none()
        
        if config:
            return {
                "key": config.config_key,
                "value": json.loads(config.config_value),
                "description": config.description,
                "updated_by": config.updated_by,
                "updated_at": config.updated_at.isoformat()
            }
        return None
    
    async def set_config(
        self,
        config_key: str,
        config_value: Dict[str, Any],
        description: str = None,
        updated_by: int = None
    ) -> AdminGlobalConfig:
        """
        设置或更新全局配置
        
        Args:
            config_key: 配置键
            config_value: 配置值（字典）
            description: 配置说明
            updated_by: 更新者用户ID
            
        Returns:
            AdminGlobalConfig 对象
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    self.model_class.config_key == config_key
                )
            )
        )
        result = await self.session.execute(stmt)
        config = result.scalar_one_or_none()
        
        if config:
            # 更新现有配置
            config.config_value = json.dumps(config_value, ensure_ascii=False)
            if description:
                config.description = description
            if updated_by:
                config.updated_by = updated_by
        else:
            # 创建新配置
            config = AdminGlobalConfig(
                bot_id=self.bot_id,
                config_key=config_key,
                config_value=json.dumps(config_value, ensure_ascii=False),
                description=description,
                updated_by=updated_by or 0,
                is_active=True
            )
            self.session.add(config)
        
        await self.session.flush()
        return config
    
    async def delete_config(self, config_key: str) -> bool:
        """
        删除全局配置
        
        Args:
            config_key: 配置键
            
        Returns:
            是否删除成功
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    self.model_class.config_key == config_key
                )
            )
        )
        result = await self.session.execute(stmt)
        config = result.scalar_one_or_none()
        
        if config:
            await self.session.delete(config)
            await self.session.flush()
            return True
        return False
    
    async def list_configs(self) -> List[Dict[str, Any]]:
        """
        获取所有全局配置列表
        
        Returns:
            配置列表
        """
        stmt = (
            select(self.model_class)
            .where(
                and_(
                    self.model_class.bot_id == self.bot_id,
                    self.model_class.is_active.is_(True)
                )
            )
            .order_by(self.model_class.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        configs = result.scalars().all()
        
        return [
            {
                "key": config.config_key,
                "value": json.loads(config.config_value),
                "description": config.description,
                "updated_by": config.updated_by,
                "updated_at": config.updated_at.isoformat()
            }
            for config in configs
        ]
    
    async def get_all_configs_dict(self) -> Dict[str, Any]:
        """
        获取所有配置为字典格式（便于使用）
        
        Returns:
            {config_key: config_value} 字典
        """
        configs = await self.list_configs()
        return {config["key"]: config["value"] for config in configs}

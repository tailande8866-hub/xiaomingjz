"""
全局配置服务 - 实现配置优先级逻辑

配置优先级：群组配置 > 全局配置 > 默认值
"""
import logging
from typing import Optional, Dict, Any

from ..repositories.group_repo import GroupRepo
from ..repositories.admin_global_config_repo import AdminGlobalConfigRepo
from ..models.group import Group
from ..utils.bot_id_middleware import get_current_bot_id
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class GlobalConfigService:
    """
    全局配置服务
    
    实现配置优先级查询：
    1. 首先检查群组是否有单独配置
    2. 如果群组没有配置，使用全局配置
    3. 如果全局配置也没有，使用默认值
    """
    
    def __init__(self):
        pass
    
    def _get_default_config(self, config_key: str) -> Any:
        """
        获取默认配置值

        Args:
            config_key: 配置键

        Returns:
            默认值
        """
        defaults = {
            # 显示配置
            "show_member_name": False,  # 是否显示记账成员名字
            "deposit_show_name": False,  # 入款显示名字开关
            "withdraw_show_name": False,  # 下发显示名字开关
            "group_tag_enabled": True,  # 记账分组功能
            "day_cut_enabled": False,  # 日切账单
            "usdt_verify_enabled": False,  # USDT地址验证
            "xlsx_enabled": False,  # xlsx账单显示
            "rename_notify_enabled": False,  # 用户更名检测通知
            "welcome_ad_enabled": False,  # 入群欢迎广告
            "keyword_reply_enabled": True,  # 自定义关键词回复
            "trx_exchange_enabled": False,  # 能量TRX兑换功能

            # 群组&成员设置 - 更名检测相关
            "nickname_monitor_enabled": False,  # 监听昵称变更
            "username_monitor_enabled": False,  # 监听用户名变更
            "impersonation_detection_enabled": True,  # 冒充管理员检测开关

            # 其他配置
            "welcome_message": "",  # 欢迎语内容
            "welcome_message_list": [],  # 欢迎语列表
            "top_ad": "",  # 顶部广告
            "custom_keywords": [],  # 自定义关键词列表
        }

        return defaults.get(config_key)
    
    async def get_config(
        self,
        db,
        bot_id: str,
        config_key: str,
        group_id: Optional[int] = None
    ) -> Any:
        """
        获取配置（带优先级）
        
        优先级：群组配置 > 全局配置 > 默认值
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            config_key: 配置键
            group_id: 群组ID（可选，如果提供则检查群组配置）
            
        Returns:
            配置值
        """
        try:
            # 1. 检查群组配置
            if group_id:
                group_repo = GroupRepo(db, bot_id)
                group = await group_repo.get_by_group_id(group_id)
                
                if group:
                    # 根据配置键从群组对象中获取对应字段
                    group_value = self._get_group_config_value(group, config_key)
                    if group_value is not None:
                        logger.debug(f"Using group config for {config_key}: {group_value}")
                        return group_value
            
            # 2. 检查全局配置
            global_repo = AdminGlobalConfigRepo(db, bot_id)
            global_config = await global_repo.get_config(config_key)

            if global_config and "value" in global_config:
                value = global_config["value"]
                # 如果配置值是字典格式
                if isinstance(value, dict):
                    # 如果是布尔开关类配置，返回 enabled 字段
                    if "enabled" in value and len(value) == 1:
                        logger.debug(f"Using global config for {config_key}: {value['enabled']}")
                        return value["enabled"]
                    # 如果是数值/字符串存储格式 {"value": xxx}，解包返回实际值
                    if "value" in value and len(value) == 1:
                        actual_value = value["value"]
                        logger.debug(f"Using global config for {config_key}: {actual_value}")
                        return actual_value
                    # 如果是复杂对象，返回整个字典
                    logger.debug(f"Using global config for {config_key}: {value}")
                    return value
                # 直接返回值（字符串、数字等）
                logger.debug(f"Using global config for {config_key}: {value}")
                return value
            
            # 3. 返回默认值
            default_value = self._get_default_config(config_key)
            logger.debug(f"Using default config for {config_key}: {default_value}")
            return default_value
            
        except Exception as e:
            logger.error(f"Error getting config {config_key}: {e}", exc_info=True)
            return self._get_default_config(config_key)
    
    def _get_group_config_value(self, group: Group, config_key: str) -> Any:
        """
        从群组对象中获取对应的配置值

        Args:
            group: 群组对象
            config_key: 配置键

        Returns:
            配置值或 None（如果群组没有该配置）
        """
        # 配置键到群组字段的映射
        field_mapping = {
            "show_member_name": None,  # 群组没有此字段，需要使用全局配置
            "group_tag_enabled": lambda g: g.group_tag is not None,
            "day_cut_enabled": lambda g: g.day_cut_time is not None,
            "usdt_verify_enabled": lambda g: g.withdraw_address is not None,
            "xlsx_enabled": None,  # 需要全局配置
            "rename_notify_enabled": None,  # 需要全局配置
            "welcome_ad_enabled": lambda g: g.welcome_message is not None and len(g.welcome_message) > 0,
            "keyword_reply_enabled": None,  # 需要检查数据库
            "trx_exchange_enabled": None,  # 需要全局配置
            "nickname_monitor_enabled": None,  # 需要全局配置
            "username_monitor_enabled": None,  # 需要全局配置
            "impersonation_detection_enabled": None,  # 需要全局配置
        }

        if config_key in field_mapping:
            mapper = field_mapping[config_key]
            if mapper is None:
                return None  # 群组没有此配置
            return mapper(group)

        return None
    
    async def set_global_config(
        self,
        db,
        bot_id: str,
        config_key: str,
        config_value: Any,
        description: str = None,
        updated_by: int = None
    ) -> bool:
        """
        设置全局配置
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            config_key: 配置键
            config_value: 配置值
            description: 配置说明
            updated_by: 更新者用户ID
            
        Returns:
            是否成功
        """
        try:
            global_repo = AdminGlobalConfigRepo(db, bot_id)
            
            # 将值包装为字典（布尔值用 enabled 字段，其他类型直接存储）
            if isinstance(config_value, dict):
                value_dict = config_value
            elif isinstance(config_value, bool):
                value_dict = {"enabled": config_value}
            else:
                # 字符串、数字等直接存储
                value_dict = {"value": config_value}
            
            await global_repo.set_config(
                config_key=config_key,
                config_value=value_dict,
                description=description,
                updated_by=updated_by
            )
            
            logger.info(f"Global config set: {config_key} = {config_value} by user {updated_by}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting global config {config_key}: {e}", exc_info=True)
            return False
    
    async def delete_global_config(
        self,
        db,
        bot_id: str,
        config_key: str
    ) -> bool:
        """
        删除全局配置（恢复为默认值）
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            config_key: 配置键
            
        Returns:
            是否成功
        """
        try:
            global_repo = AdminGlobalConfigRepo(db, bot_id)
            success = await global_repo.delete_config(config_key)
            
            if success:
                logger.info(f"Global config deleted: {config_key}")
            return success
            
        except Exception as e:
            logger.error(f"Error deleting global config {config_key}: {e}", exc_info=True)
            return False
    
    async def list_all_configs(
        self,
        db,
        bot_id: str
    ) -> Dict[str, Any]:
        """
        获取所有全局配置
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            
        Returns:
            配置字典
        """
        try:
            global_repo = AdminGlobalConfigRepo(db, bot_id)
            return await global_repo.get_all_configs_dict()
        except Exception as e:
            logger.error(f"Error listing global configs: {e}", exc_info=True)
            return {}


# 全局服务实例
global_config_service = GlobalConfigService()

"""
.env 文件验证器 + 自动修复器

🔥 运行时保护：确保所有子BOT的.env文件格式正确
🔥 自动修复：检测并修复历史BOT的脏.env文件
🔥 强制约束：env错误时阻止BOT启动（或自动修复后再启动）
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from ..utils.database_url import get_shared_database_url

logger = logging.getLogger(__name__)


@dataclass
class EnvValidationResult:
    """.env 验证结果"""
    is_valid: bool
    errors: list
    warnings: list
    can_auto_repair: bool
    missing_fields: list
    wrong_values: dict


class EnvValidator:
    """
    .env 文件验证器
    
    验证规则：
    1. 必须字段：BOT_TOKEN, INSTANCE_ID, SUPER_ADMIN_ID, BOT_OWNER_ID, DATABASE_URL
    2. SUPER_ADMIN_ID 必须是全局超管ID（不是BOT拥有者ID）
    3. BOT_OWNER_ID 必须是该BOT的创建者ID
    """
    
    REQUIRED_FIELDS = [
        'BOT_TOKEN',
        'INSTANCE_ID', 
        'SUPER_ADMIN_ID',
        'BOT_OWNER_ID',
        'SHARED_DATABASE_URL',
        'DATABASE_URL',
        'IS_MAIN_BOT'
    ]
    
    @classmethod
    def parse_env_file(cls, env_path: str) -> Dict[str, str]:
        """解析 .env 文件为字典"""
        env_vars = {}
        path = Path(env_path)
        
        if not path.exists():
            return env_vars
        
        content = path.read_text(encoding='utf-8')
        
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
        
        return env_vars
    
    @classmethod
    def validate_env(
        cls,
        env_path: str,
        expected_bot_owner_id: int,
        expected_instance_id: str
    ) -> EnvValidationResult:
        """
        验证 .env 文件
        
        Args:
            env_path: .env 文件路径
            expected_bot_owner_id: 期望的 BOT_OWNER_ID（从数据库获取）
            expected_instance_id: 期望的 INSTANCE_ID（从数据库获取）
        
        Returns:
            EnvValidationResult
        """
        errors = []
        warnings = []
        missing_fields = []
        wrong_values = {}
        
        # 1. 文件是否存在
        if not Path(env_path).exists():
            errors.append(f".env 文件不存在: {env_path}")
            return EnvValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                can_auto_repair=True,
                missing_fields=cls.REQUIRED_FIELDS,
                wrong_values=wrong_values
            )
        
        # 2. 解析 .env
        env_vars = cls.parse_env_file(env_path)
        
        # 3. 检查必须字段
        for field in cls.REQUIRED_FIELDS:
            if field not in env_vars or not env_vars[field]:
                missing_fields.append(field)
        
        if missing_fields:
            errors.append(f"缺少必须字段: {missing_fields}")
        
        # 4. 检查 SUPER_ADMIN_ID 是否正确
        super_admin_id = env_vars.get('SUPER_ADMIN_ID', '0')
        global_super_admin = cls._get_global_super_admin()
        
        try:
            if int(super_admin_id) != global_super_admin:
                wrong_values['SUPER_ADMIN_ID'] = {
                    'current': super_admin_id,
                    'expected': global_super_admin,
                    'issue': 'SUPER_ADMIN_ID 不是全局超管ID，可能是BOT拥有者ID'
                }
                errors.append(f"SUPER_ADMIN_ID 错误: 当前={super_admin_id}, 应为={global_super_admin}")
        except ValueError:
            wrong_values['SUPER_ADMIN_ID'] = {
                'current': super_admin_id,
                'expected': global_super_admin,
                'issue': 'SUPER_ADMIN_ID 不是有效的数字'
            }
            errors.append(f"SUPER_ADMIN_ID 格式错误: {super_admin_id}")
        
        # 5. 检查 BOT_OWNER_ID 是否匹配
        bot_owner_id = env_vars.get('BOT_OWNER_ID', '0')
        try:
            if int(bot_owner_id) != expected_bot_owner_id:
                wrong_values['BOT_OWNER_ID'] = {
                    'current': bot_owner_id,
                    'expected': expected_bot_owner_id,
                    'issue': 'BOT_OWNER_ID 与数据库记录不匹配'
                }
                errors.append(f"BOT_OWNER_ID 不匹配: 当前={bot_owner_id}, 应为={expected_bot_owner_id}")
        except ValueError:
            wrong_values['BOT_OWNER_ID'] = {
                'current': bot_owner_id,
                'expected': expected_bot_owner_id,
                'issue': 'BOT_OWNER_ID 不是有效的数字'
            }
            errors.append(f"BOT_OWNER_ID 格式错误: {bot_owner_id}")
        
        # 6. 检查 INSTANCE_ID 是否匹配
        instance_id = env_vars.get('INSTANCE_ID', '')
        if instance_id != expected_instance_id:
            wrong_values['INSTANCE_ID'] = {
                'current': instance_id,
                'expected': expected_instance_id,
                'issue': 'INSTANCE_ID 与数据库记录不匹配'
            }
            errors.append(f"INSTANCE_ID 不匹配: 当前={instance_id}, 应为={expected_instance_id}")
        
        # 7. 检查 DATABASE_URL / SHARED_DATABASE_URL
        expected_database_url = get_shared_database_url()
        shared_database_url = env_vars.get('SHARED_DATABASE_URL', '')
        database_url = env_vars.get('DATABASE_URL', '')

        if shared_database_url != expected_database_url:
            wrong_values['SHARED_DATABASE_URL'] = {
                'current': shared_database_url,
                'expected': expected_database_url,
                'issue': 'SHARED_DATABASE_URL 未指向当前统一数据库'
            }
            errors.append("SHARED_DATABASE_URL 不匹配统一数据库")

        if database_url != expected_database_url:
            wrong_values['DATABASE_URL'] = {
                'current': database_url,
                'expected': expected_database_url,
                'issue': 'DATABASE_URL 未指向当前统一数据库'
            }
            errors.append("DATABASE_URL 不匹配统一数据库")

        # 8. 检查 IS_MAIN_BOT
        is_main_bot = env_vars.get('IS_MAIN_BOT', '')
        if is_main_bot.lower() != 'false':
            wrong_values['IS_MAIN_BOT'] = {
                'current': is_main_bot,
                'expected': 'false',
                'issue': '子BOT的 IS_MAIN_BOT 必须为 false'
            }
            errors.append(f"IS_MAIN_BOT 错误: 当前={is_main_bot}, 应为=false")
        
        is_valid = len(errors) == 0
        can_auto_repair = len(missing_fields) > 0 or len(wrong_values) > 0
        
        return EnvValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            can_auto_repair=can_auto_repair,
            missing_fields=missing_fields,
            wrong_values=wrong_values
        )
    
    @classmethod
    def _get_global_super_admin(cls) -> int:
        """获取全局超管ID"""
        try:
            from config import config
            config_val = getattr(config, 'SUPER_ADMIN_ID', 0)
        except Exception:
            config_val = 0
        
        env_val = os.getenv('SUPER_ADMIN_ID', '0')
        
        try:
            return int(config_val) or int(env_val)
        except (ValueError, TypeError):
            return 0


class EnvAutoRepair:
    """
    .env 文件自动修复器
    
    自动修复场景：
    1. .env 文件缺失 → 重新生成
    2. SUPER_ADMIN_ID 错误 → 修正为全局超管ID
    3. BOT_OWNER_ID 缺失/错误 → 修正为数据库记录值
    4. 必须字段缺失 → 补全
    """
    
    @classmethod
    async def repair_env(
        cls,
        instance_dir: str,
        bot_token: str,
        instance_id: str,
        bot_owner_id: int,
        bot_username: str = "",
        backup_old: bool = True
    ) -> bool:
        """
        自动修复 .env 文件
        
        Args:
            instance_dir: 实例目录
            bot_token: Bot Token（明文）
            instance_id: 实例ID
            bot_owner_id: BOT拥有者ID（从数据库获取的正确值）
            bot_username: Bot用户名
            backup_old: 是否备份旧的.env文件
        
        Returns:
            True=修复成功, False=修复失败
        """
        from .env_generator import ensure_env_file
        
        dir_path = Path(instance_dir)
        env_path = dir_path / ".env"
        
        logger.warning(f"[EnvAutoRepair] 🔧 开始修复 .env: {env_path}")
        
        # 1. 备份旧文件
        if backup_old and env_path.exists():
            backup_path = dir_path / ".env.backup"
            try:
                backup_path.write_text(env_path.read_text(encoding='utf-8'), encoding='utf-8')
                logger.info(f"[EnvAutoRepair] 💾 已备份旧.env: {backup_path}")
            except Exception as e:
                logger.warning(f"[EnvAutoRepair] ⚠️ 备份失败: {e}")
        
        # 2. 删除错误的.env（如果存在）
        if env_path.exists():
            try:
                env_path.unlink()
                logger.info(f"[EnvAutoRepair] 🗑️ 已删除错误的.env")
            except Exception as e:
                logger.error(f"[EnvAutoRepair] ❌ 删除旧.env失败: {e}")
                return False
        
        # 3. 重新生成正确的.env
        success = await ensure_env_file(
            instance_dir=instance_dir,
            bot_token=bot_token,
            instance_id=instance_id,
            bot_owner_id=bot_owner_id,
            bot_username=bot_username,
        )
        
        if success:
            logger.info(f"[EnvAutoRepair] ✅ .env 修复成功: {env_path}")
        else:
            logger.error(f"[EnvAutoRepair] ❌ .env 修复失败: {env_path}")
        
        return success
    
    @classmethod
    async def validate_and_repair(
        cls,
        instance_dir: str,
        bot_token: str,
        instance_id: str,
        bot_owner_id: int,
        bot_username: str = "",
        auto_repair: bool = True
    ) -> Tuple[bool, EnvValidationResult]:
        """
        验证并自动修复 .env
        
        Args:
            auto_repair: 验证失败时是否自动修复
        
        Returns:
            (是否有效/修复成功, 验证结果)
        """
        env_path = Path(instance_dir) / ".env"
        
        # 1. 验证
        result = EnvValidator.validate_env(
            env_path=str(env_path),
            expected_bot_owner_id=bot_owner_id,
            expected_instance_id=instance_id
        )
        
        if result.is_valid:
            logger.info(f"[EnvAutoRepair] ✅ .env 验证通过: {env_path}")
            return True, result
        
        # 2. 验证失败，尝试修复
        if auto_repair and result.can_auto_repair:
            logger.warning(f"[EnvAutoRepair] ⚠️ .env 验证失败，尝试自动修复...")
            logger.warning(f"[EnvAutoRepair] 错误: {result.errors}")
            
            repaired = await cls.repair_env(
                instance_dir=instance_dir,
                bot_token=bot_token,
                instance_id=instance_id,
                bot_owner_id=bot_owner_id,
                bot_username=bot_username,
            )
            
            if repaired:
                # 重新验证
                result = EnvValidator.validate_env(
                    env_path=str(env_path),
                    expected_bot_owner_id=bot_owner_id,
                    expected_instance_id=instance_id
                )
                return result.is_valid, result
        
        return False, result

"""
汇率数据缓存服务
使用内存缓存 + TTL过期机制
生产环境建议替换为Redis
"""
import time
import logging
from typing import Optional, Any, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateCacheService:
    """汇率数据缓存服务"""
    
    # 缓存存储 {key: {"data": value, "expire_at": timestamp}}
    _cache: Dict[str, Dict[str, Any]] = {}
    
    # 默认缓存时间（秒）
    DEFAULT_TTL = 60  # 1分钟
    
    @staticmethod
    def get(key: str) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            key: 缓存键
        
        Returns:
            缓存的数据，如果不存在或已过期则返回None
        """
        if key not in RateCacheService._cache:
            return None
        
        cache_item = RateCacheService._cache[key]
        
        # 检查是否过期
        if time.time() > cache_item["expire_at"]:
            logger.debug(f"缓存过期: {key}")
            del RateCacheService._cache[key]
            return None
        
        logger.debug(f"缓存命中: {key}")
        return cache_item["data"]
    
    @staticmethod
    def set(key: str, value: Any, ttl: int = None) -> None:
        """
        设置缓存数据
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），默认使用DEFAULT_TTL
        """
        if ttl is None:
            ttl = RateCacheService.DEFAULT_TTL
        
        expire_at = time.time() + ttl
        
        RateCacheService._cache[key] = {
            "data": value,
            "expire_at": expire_at
        }
        
        logger.debug(f"缓存设置: {key} (TTL: {ttl}s)")
    
    @staticmethod
    def delete(key: str) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
        
        Returns:
            是否成功删除
        """
        if key in RateCacheService._cache:
            del RateCacheService._cache[key]
            logger.debug(f"缓存删除: {key}")
            return True
        return False
    
    @staticmethod
    def clear() -> None:
        """清空所有缓存"""
        RateCacheService._cache.clear()
        logger.info("缓存已清空")
    
    @staticmethod
    def get_stats() -> Dict[str, int]:
        """
        获取缓存统计信息
        
        Returns:
            包含缓存数量等信息的字典
        """
        now = time.time()
        valid_count = sum(
            1 for item in RateCacheService._cache.values()
            if item["expire_at"] > now
        )
        
        return {
            "total_keys": len(RateCacheService._cache),
            "valid_keys": valid_count
        }


# 便捷函数
def get_cached_rates(exchange: str, payment_method: str = "all") -> Optional[list]:
    """
    从缓存获取汇率数据
    
    Args:
        exchange: 交易所名称
        payment_method: 支付方式
    
    Returns:
        缓存的汇率数据
    """
    key = f"rates:{exchange}:{payment_method}"
    return RateCacheService.get(key)


def cache_rates(exchange: str, payment_method: str, data: list, ttl: int = None) -> None:
    """
    缓存汇率数据
    
    Args:
        exchange: 交易所名称
        payment_method: 支付方式
        data: 汇率数据
        ttl: 缓存时间（秒）
    """
    key = f"rates:{exchange}:{payment_method}"
    RateCacheService.set(key, data, ttl)


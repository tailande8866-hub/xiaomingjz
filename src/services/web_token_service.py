"""
Web Token 服务
生成和验证临时访问 Token
"""
import jwt
import time
from datetime import datetime, timedelta
from typing import Optional, Dict
from config.enhanced_config import config_manager


class WebTokenService:
    """Web 访问 Token 服务"""
    
    def __init__(self):
        self.secret_key = config_manager.web.secret_key
        # 从环境变量读取，默认 24 小时
        self.expiry_hours = int(__import__('os').getenv('WEB_TOKEN_EXPIRY_HOURS', '24'))
    
    def generate_token(
        self,
        bot_id: str,
        chat_id: int,
        user_id: Optional[int] = None
    ) -> str:
        """
        生成临时访问 Token
        
        Args:
            bot_id: Bot ID
            chat_id: 群组 ID
            user_id: 用户 ID（可选）
        
        Returns:
            JWT Token 字符串
        """
        payload = {
            'bot_id': bot_id,
            'chat_id': chat_id,
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=self.expiry_hours),
            'iat': datetime.utcnow()
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm='HS256')
        return token
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """
        验证 Token
        
        Args:
            token: JWT Token 字符串
        
        Returns:
            解码后的 payload，验证失败返回 None
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            print(f"[WebToken] Token expired")
            return None
        except jwt.InvalidTokenError as e:
            print(f"[WebToken] Invalid token: {e}")
            return None
    
    def generate_web_url(
        self,
        bot_id: str,
        chat_id: int,
        base_url: str = None
    ) -> str:
        """
        生成完整的 Web 访问 URL
        
        Args:
            bot_id: Bot ID
            chat_id: 群组 ID
            base_url: Web 基础 URL（从配置读取）
        
        Returns:
            完整的 URL 字符串
        """
        if not base_url:
            import os
            base_url = os.getenv('WEB_BASE_URL', 'http://localhost:8081')
        
        token = self.generate_token(bot_id, chat_id)
        return f"{base_url}/?chatid={chat_id}&token={token}"


# 单例实例
web_token_service = WebTokenService()

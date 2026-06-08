"""
Token 加密工具

职责：
1. 加密 Bot Token（使用 Fernet 对称加密）
2. 解密 Bot Token
3. 生成加密密钥

这是生产环境的安全要求，防止 Bot Token 明文存储在数据库中。
"""
import os
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class TokenEncryptor:
    """
    Token 加密器（单例）
    
    使用 Fernet 对称加密算法加密/解密 Bot Token。
    """
    
    def __init__(self):
        # 从环境变量获取加密密钥
        encryption_key = os.getenv('BOT_TOKEN_ENCRYPTION_KEY')
        
        if not encryption_key:
            # 如果没有配置密钥，生成一个新密钥（仅用于开发环境）
            logger.warning(
                "BOT_TOKEN_ENCRYPTION_KEY not set in environment. "
                "Generating a new key for development purposes. "
                "Please set this in production!"
            )
            encryption_key = Fernet.generate_key().decode()
            logger.info("Generated a development encryption key; store it in BOT_TOKEN_ENCRYPTION_KEY before restart")
        
        self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        logger.info("TokenEncryptor initialized")
    
    def encrypt(self, token: str) -> bytes:
        """
        加密 Token
        
        Args:
            token: 明文 Token
            
        Returns:
            加密后的 Token（bytes）
        """
        if not token:
            raise ValueError("Token cannot be empty")
        
        encrypted = self.cipher.encrypt(token.encode())
        logger.debug(f"Token encrypted (length: {len(encrypted)})")
        return encrypted
    
    def decrypt(self, encrypted_token: bytes) -> str:
        """
        解密 Token
        
        Args:
            encrypted_token: 加密后的 Token（bytes）
            
        Returns:
            明文 Token
        """
        if not encrypted_token:
            raise ValueError("Encrypted token cannot be empty")
        
        try:
            decrypted = self.cipher.decrypt(encrypted_token).decode()
            logger.debug(f"Token decrypted (length: {len(decrypted)})")
            return decrypted
        except Exception as e:
            logger.error(f"Failed to decrypt token: {e}", exc_info=True)
            raise ValueError(f"Invalid encrypted token: {e}")
    
    def encrypt_to_base64(self, token: str) -> str:
        """
        加密 Token 并返回 Base64 字符串（方便存储）
        
        Args:
            token: 明文 Token
            
        Returns:
            加密后的 Token（Base64 字符串）
        """
        encrypted_bytes = self.encrypt(token)
        return encrypted_bytes.decode('utf-8')
    
    def decrypt_from_base64(self, encrypted_token_str: str) -> str:
        """
        从 Base64 字符串解密 Token
        
        Args:
            encrypted_token_str: 加密后的 Token（Base64 字符串）
            
        Returns:
            明文 Token
        """
        encrypted_bytes = encrypted_token_str.encode('utf-8')
        return self.decrypt(encrypted_bytes)
    
    @staticmethod
    def generate_key() -> str:
        """
        生成新的加密密钥
        
        Returns:
            加密密钥（字符串）
        """
        key = Fernet.generate_key().decode()
        logger.info("Generated new encryption key")
        return key


# 全局单例
token_encryptor = TokenEncryptor()

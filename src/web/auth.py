"""
Web Token 认证中间件
"""
from functools import wraps
from flask import request, jsonify
from src.services.web_token_service import web_token_service


def token_required(f):
    """Token 验证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get('token')
        chat_id = request.args.get('chatId')
        
        if not token:
            return jsonify({'error': 'Token is required'}), 401
        
        if not chat_id:
            return jsonify({'error': 'Chat ID is required'}), 401
        
        # 验证 Token
        payload = web_token_service.verify_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # 校验 chat_id 是否匹配
        if str(payload.get('chat_id')) != str(chat_id):
            return jsonify({'error': 'Chat ID mismatch'}), 403
        
        # 将 payload 传递给视图函数
        request.token_payload = payload
        return f(*args, **kwargs)
    
    return decorated

"""
Web 账单系统 - Flask 应用入口
"""
import os
import sys

# 添加项目根目录到路径（必须在其他 import 之前）
_base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from src.web.routes import register_routes
from config.enhanced_config import config_manager
import logging

logger = logging.getLogger(__name__)


def create_app():
    """创建 Flask 应用"""
    # 获取模板和静态文件路径
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    template_folder = os.path.join(base_dir, 'src', 'web', 'templates')
    static_folder = os.path.join(base_dir, 'static')
    
    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder
    )
    
    # 启用 CORS
    CORS(app)
    
    # 加载配置
    app.config['SECRET_KEY'] = config_manager.web.secret_key
    
    # 注册路由
    register_routes(app)
    
    # 错误处理
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal error: {error}")
        return jsonify({'error': 'Internal server error'}), 500
    
    return app


if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    app = create_app()
    
    print(f"🚀 Starting Web Bill System...")
    print(f"📍 URL: http://{config_manager.web.host}:{config_manager.web.port}")
    
    app.run(
        host=config_manager.web.host,
        port=config_manager.web.port,
        debug=False
    )

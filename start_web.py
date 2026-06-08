"""
Web 账单系统启动脚本
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(__file__))

from src.web.app import create_app
from config.enhanced_config import config_manager
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == '__main__':
    if not config_manager.web.enabled:
        print("❌ Web system is disabled in config")
        sys.exit(1)
    
    app = create_app()
    
    print(f"🚀 Starting Web Bill System...")
    print(f"📍 URL: http://{config_manager.web.host}:{config_manager.web.port}")
    print(f"🔑 Token Expiry: {os.getenv('WEB_TOKEN_EXPIRY_HOURS', '24')} hours")
    
    app.run(
        host=config_manager.web.host,
        port=config_manager.web.port,
        debug=False
    )

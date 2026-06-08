"""
健康检查 Handler

职责：
提供轻量级 /health 命令，检查关键组件状态

检查项：
1. 数据库连接
2. Event Queue 状态
3. Runtime 状态
4. Telegram API 连通性

使用方法：
发送 /health 命令
"""
import logging
import time
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import text

from ..models import get_db_session

logger = logging.getLogger(__name__)


async def handle_health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理 /health 命令
    
    权限要求：
    - 仅限超级管理员
    - 仅限私聊
    
    返回系统健康状态报告
    """
    if not update.message:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # ✅ 权限检查：仅限私聊
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ 此命令仅限私聊使用")
        return
    
    # ✅ 权限检查：仅限超级管理员
    from ..utils.role_checker import get_user_role, UserRole
    from ..utils.bot_id_middleware import get_current_bot_id
    
    bot_id = get_current_bot_id(context)
    role = await get_user_role(user_id, chat_id, bot_id)
    
    if role not in [UserRole.SUPER_ADMIN, UserRole.BOT_OWNER]:
        await update.message.reply_text("❌ 此命令仅限超级管理员使用")
        return
    
    # 开始检查
    start_time = time.time()
    status_items = []  # 状态项目列表
    anomalies = []  # 异常详情列表
    overall_status = "🟢"  # 默认正常
    
    # ==================== 1. 数据库检查 ====================
    try:
        async with get_db_session() as db:
            result = await db.execute(text("SELECT 1"))
            result.scalar()
                
            # 获取数据库大小（SQLite）
            import os
            db_path = "accounting_bot.db"
            if os.path.exists(db_path):
                db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
                status_items.append(f"💾 数据库：✅ 正常（{db_size_mb:.2f} MB）")
            else:
                status_items.append(f"💾 数据库：⚠️ 文件不存在")
                anomalies.append("• 数据库文件不存在")
                overall_status = "🟡"
    except Exception as e:
        overall_status = ""
        status_items.append(f"💾 数据库：❌ 异常")
        anomalies.append(f"• 数据库连接失败：{str(e)}")
        logger.error(f"Database health check failed: {e}", exc_info=True)
    
    # ==================== 2. Event Queue 检查 ====================
    try:
        from ..core.event_pipeline import event_pipeline
        
        queue_size = event_pipeline.queue.qsize() if hasattr(event_pipeline, 'queue') else 0
        max_size = event_pipeline.max_queue_size if hasattr(event_pipeline, 'max_queue_size') else 10000
        
        if queue_size < max_size * 0.8:
            status_items.append(f"📥 事件队列：✅ 正常（{queue_size}/{max_size}）")
        elif queue_size < max_size:
            status_items.append(f"📥 事件队列：⚠️ 队列积压（{queue_size}/{max_size}）")
            anomalies.append(f"• 事件队列积压：{queue_size}/{max_size}")
            overall_status = "🟡"
        else:
            status_items.append(f"📥 事件队列：❌ 已满（{queue_size}/{max_size}）")
            anomalies.append(f"• 事件队列已满：{queue_size}/{max_size}")
            overall_status = "🟡"
    except Exception as e:
        status_items.append(f"📥 事件队列：⚠️ 无法检查")
        anomalies.append(f"• 事件队列检查失败：{str(e)}")
        overall_status = "🟡"
        logger.warning(f"Event Queue health check failed: {e}")
    
    # ==================== 3. Bot 运行检查 ====================
    try:
        from ..core.bot_factory import bot_factory
            
        active_bots = len(bot_factory.active_bots) if hasattr(bot_factory, 'active_bots') else 0
        total_bots = len(bot_factory.bot_configs) if hasattr(bot_factory, 'bot_configs') else 0
        
        status_items.append(f"🤖 Bot运行：✅ 正常")
    except Exception as e:
        status_items.append(f"🤖 Bot运行：⚠️ 模块加载失败")
        anomalies.append(f"• bot_factory 模块导入失败")
        anomalies.append(f"• 错误信息：{str(e)}")
        overall_status = "🟡"
        logger.warning(f"Runtime health check failed: {e}")
    
    # ==================== 4. Telegram API 检查 ====================
    try:
        # 尝试获取 Bot 信息
        bot_info = await context.bot.get_me()
        status_items.append(f"📡 Telegram：✅ 已连接")
    except Exception as e:
        overall_status = "🟡"
        status_items.append(f"📡 Telegram：❌ 连接失败")
        anomalies.append(f"• Telegram API 连接失败：{str(e)}")
        logger.error(f"Telegram API health check failed: {e}", exc_info=True)
    
    # ==================== 5. 内存使用检查 ====================
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / (1024 * 1024)
        
        if memory_mb < 200:
            status_items.append(f"💿 内存使用：✅ {memory_mb:.2f} MB")
        elif memory_mb < 500:
            status_items.append(f"💿 内存使用：✅ {memory_mb:.2f} MB")
        else:
            status_items.append(f"💿 内存使用：️ 占用过高（{memory_mb:.2f} MB）")
            anomalies.append(f"• 内存占用过高：{memory_mb:.2f} MB")
            overall_status = "🟡"
    except ImportError:
        status_items.append(f"💿 内存使用：️ psutil 未安装")
        anomalies.append("• psutil 未安装，无法检测内存")
        overall_status = "🟡"
    except Exception as e:
        status_items.append(f"💿 内存使用：⚠️ 无法检查")
        anomalies.append(f"• 内存检查失败：{str(e)}")
        overall_status = ""
        logger.warning(f"Memory check failed: {e}")
    
    # ==================== 6. 运行时间检查 ====================
    try:
        uptime_seconds = time.time() - context.bot_data.get('start_time', time.time())
        
        # 格式化为 X 天 X 小时
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        
        if days > 0:
            status_items.append(f"⏱️ 运行时间：{days} 天 {hours} 小时")
        elif hours > 0:
            status_items.append(f"⏱️ 运行时间：{hours} 小时")
        else:
            status_items.append(f"⏱️ 运行时间：{int(uptime_seconds)} 秒")
    except Exception:
        status_items.append(f"⏱️ 运行时间：未知")
    
    # ==================== 计算总耗时 ====================
    elapsed_ms = int((time.time() - start_time) * 1000)
    
    # ==================== 构建回复消息 ====================
    # 获取 Bot 名称
    try:
        bot_info = await context.bot.get_me()
        bot_name = bot_info.first_name or "记账机器人"
    except Exception:
        bot_name = "记账机器人"
    
    # 构建基础消息
    response_lines = [
        f"🏥 系统健康检查",
        f"",
    ]
    
    # 系统状态
    if overall_status == "":
        response_lines.append(f"🟢 系统状态：正常运行")
    else:
        response_lines.append(f"🟡 系统状态：部分异常")
    
    response_lines.append(f"")
    
    # 状态详情
    response_lines.extend(status_items)
    
    response_lines.append(f"")
    response_lines.append(f"⚡️ 检测耗时：{elapsed_ms} ms")
    
    # 异常详情（如果有）
    if anomalies:
        response_lines.append(f"")
        response_lines.append(f"📌 异常详情")
        response_lines.extend(anomalies)
        if overall_status == "🟢":
            overall_status = "🟡"
    
    response_lines.append(f"")
    response_lines.append(f"📖 状态说明")
    response_lines.append(f"🟢 正常：所有服务运行稳定")
    response_lines.append(f" 异常：部分功能受到影响")
    response_lines.append(f"🔴 故障：核心服务不可用")
    
    response_lines.append(f"")
    response_lines.append(f"🤖 {bot_name}")
    
    response_text = "\n".join(response_lines)
    
    # 发送回复
    await update.message.reply_text(response_text, parse_mode="HTML")
    
    # 记录日志
    logger.info(f"Health check completed: status={overall_status}, elapsed={elapsed_ms}ms")


# 注册到 bot.py 或 main.py
# application.add_handler(CommandHandler("health", handle_health_check))

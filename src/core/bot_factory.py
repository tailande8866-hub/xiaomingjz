"""
Bot Factory - 统一的 Bot 实例工厂

核心思想：
- 所有 Bot 共享同一套功能内核
- 通过配置区分不同 Bot 的行为
- 支持 Polling 和 Webhook 两种模式
"""
import logging
import os
from datetime import datetime
import httpx
import urllib.request
from telegram import Update, BotCommand
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    PicklePersistence
)

from config import config
from ..models import init_db, close_db
from ..services.schedule_service import ScheduleService
from ..handlers import basic, operator, billing, settings, query, menu, advanced
from ..handlers import group_tags, calculator, menu_callbacks, admin_manage, saas_purchase, custom, internal_admin
from ..handlers import custom_keyword, usdt_monitor
from ..handlers import chat_member_handler, health_check  # 🆕 添加健康检查
from ..handlers.auth_commands import register_auth_commands  # 🆕 授权管理命令（插件式）
from ..handlers.join_welcome_handler import register_join_welcome_handler  # 🆕 入群欢迎语事件处理器
from ..utils import install_callback_alert_patch
from ..utils.logging_config import setup_production_logging, log_startup_info, log_shutdown_info

logger = logging.getLogger(__name__)


class DirectHTTPXRequest(HTTPXRequest):
    """Disable system proxy inheritance for Telegram polling/send requests."""

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(trust_env=False, **self._client_kwargs)


def _detect_telegram_proxy() -> str | None:
    proxies = urllib.request.getproxies()
    return proxies.get("https") or proxies.get("http")


def _get_runtime_bot_id(application: Application | None = None, is_main_bot: bool | None = None) -> str:
    if is_main_bot is None:
        is_main_bot = os.environ.get("IS_MAIN_BOT", "true").lower() != "false"
    if is_main_bot:
        return "main_bot"
    if application is not None:
        try:
            bot_id = application.bot_data.get("bot_id")
            if bot_id:
                return bot_id
        except Exception:
            pass
    return config.INSTANCE_ID if getattr(config, "INSTANCE_ID", None) else "main_bot"


class BotFactory:
    """
    Bot 工厂类
    
    负责：
    1. 创建 Bot 实例（Application）
    2. 注册所有 handlers
    3. 配置生命周期钩子（post_init/post_shutdown）
    """
    
    @staticmethod
    def create_application(bot_token: str, is_main_bot: bool = False) -> Application:
        """
        创建 Telegram Bot Application
        
        Args:
            bot_token: Bot Token
            is_main_bot: 是否为主机器人（影响部分功能）
        
        Returns:
            Application 实例
        """
        logger.info(f"Creating bot application (main_bot={is_main_bot})")
        
        # 🆕 初始化日志上下文
        try:
            from ..utils.log_context import setup_log_context
            setup_log_context()
        except Exception as e:
            logger.warning(f"Failed to setup log context: {e}")
        
        try:
            install_callback_alert_patch()
        except Exception as e:
            logger.warning(f"Failed to install callback alert patch: {e}")
        
        # 创建 Application
        # ✅ 添加 PicklePersistence 以持久化 user_data，确保状态在消息之间保持
        import os
        from pathlib import Path
        
        # 创建bot_data目录存储持久化数据
        bot_data_dir = Path(__file__).parent.parent.parent / 'bot_data'
        bot_data_dir.mkdir(exist_ok=True)
        
        # 使用bot_id作为持久化文件名，支持多租户隔离
        persistence_file = bot_data_dir / f'persistence_{bot_token[:8]}.pickle'
        
        persistence = PicklePersistence(filepath=str(persistence_file))
        proxy_url = _detect_telegram_proxy()
        logger.info(f"Telegram proxy detected for PTB requests: {proxy_url or 'direct'}")
        request = DirectHTTPXRequest(
            connection_pool_size=32,
            proxy=proxy_url,
            connect_timeout=20.0,
            read_timeout=15.0,
            write_timeout=15.0,
            pool_timeout=30.0,
            http_version="1.1",
        )
        get_updates_request = DirectHTTPXRequest(
            connection_pool_size=8,
            proxy=proxy_url,
            connect_timeout=20.0,
            read_timeout=12.0,
            write_timeout=12.0,
            pool_timeout=20.0,
            http_version="1.1",
        )
        
        logger.info(f"📦 PicklePersistence enabled: {persistence_file}")
        
        application = (
            Application.builder()
            .token(bot_token)
            .request(request)
            .get_updates_request(get_updates_request)
            .persistence(persistence)
            .post_init(lambda app: BotFactory._post_init(app, is_main_bot))
            .post_shutdown(BotFactory._post_shutdown)
            .build()
        )
        
        # ⭐ 注册 Bot ID Middleware（自动注入 bot_id）
        from src.utils.bot_id_middleware import BotIdMiddleware
        BotIdMiddleware.inject_bot_id(application)
        
        # 注册 handlers
        BotFactory._register_handlers(application, is_main_bot)
        
        # 注册错误处理器
        application.add_error_handler(BotFactory._error_handler)
        
        logger.info("Bot application created successfully")
        return application
    
    @staticmethod
    async def _post_init(application: Application, is_main_bot: bool = False):
        """
        应用初始化后的操作
        
        Args:
            application: Application 实例
            is_main_bot: 是否为主机器人
        """
        runtime_bot_id = _get_runtime_bot_id(application, is_main_bot)
        application.bot_data['bot_id'] = runtime_bot_id

        # ⭐ 设置 Bot 菜单命令（所有 Bot 统一）
        await BotFactory._set_bot_commands(application.bot)
        
        # 初始化数据库
        await init_db()
        logger.info("Database initialized")
        
        # 🆕 自动初始化默认套餐（如果表中没有数据）
        try:
            from scripts.init_saas_plans import init_default_plans
            await init_default_plans()
            logger.info("Default pricing plans initialized (if needed)")
        except Exception as e:
            logger.warning(f"Failed to initialize default pricing plans: {e}")
        
        # 优化数据库索引（仅首次启动时执行）
        try:
            from ..models.db_optimizer import optimize_database
            optimization_result = await optimize_database()
            logger.info(
                f"Database optimization completed: "
                f"{optimization_result['indexes_created']} indexes created, "
                f"{optimization_result['indexes_already_exists']} already exist"
            )
        except Exception as e:
            logger.warning(f"Database optimization skipped: {e}")
        
        # 🏷️ 初始化默认分组标签（使用新架构 GroupTag）
        try:
            from ..services.group_tag_service import GroupTagService
            default_tag = await GroupTagService.ensure_default_tag(
                bot_id=runtime_bot_id,
                created_by=0  # 系统创建
            )
            logger.info(
                f"Default group tag initialized: {default_tag.tag_name} "
                f"(id={default_tag.id}, bot_id={runtime_bot_id})"
            )
        except Exception as e:
            logger.warning(f"Default group tag initialization skipped: {e}")
        
        # ✅ 新增：默认分组自动补偿（确保每个 Bot 都有默认分组）
        try:
            from ..services.default_group_compensator import DefaultGroupCompensator
            compensator = DefaultGroupCompensator()
            await compensator.ensure_default_group(runtime_bot_id)
            logger.info(f"✅ Default group compensation completed for bot {runtime_bot_id}")
        except Exception as e:
            logger.error(f"❌ Default group compensation failed: {e}", exc_info=True)
        
        # ✅ 系统启动时自动清理无效群组（使用新架构 GroupTag）
        try:
            from ..services.group_tag_service import GroupTagService
            clean_result = await GroupTagService.sync_group_status(
                bot=application.bot,
                bot_id=runtime_bot_id
            )
            logger.info(
                f"Startup group cleanup completed: "
                f"valid={clean_result['valid']}, "
                f"cleaned={clean_result['cleaned']}, "
                f"synced={clean_result['synced']}"
            )
        except Exception as e:
            logger.warning(f"Startup group cleanup skipped: {e}")

        # 🆕 自动刷新所有群组的管理员昵称缓存（冒充管理员检测用）
        try:
            from ..handlers.member_rename_handler import refresh_all_groups_admin_cache
            refreshed_count = await refresh_all_groups_admin_cache(
                application.bot,
                runtime_bot_id
            )
            logger.info(f"✅ Admin nickname cache refreshed for {refreshed_count} groups on startup")
        except Exception as e:
            logger.warning(f"Startup admin cache refresh skipped: {e}")
        
        # ✅ 系统启动引导（双保险机制）
        try:
            from ..services.system_bootstrap_service import system_bootstrap_service
            await system_bootstrap_service.run(application.bot)
            logger.info("✅ System bootstrap completed")
        except Exception as e:
            logger.error(f"❌ System bootstrap failed: {e}", exc_info=True)
        
        # ✅ 初始化超级管理员（从 BotCreation 表读取 super_admin_id）
        try:
            await BotFactory._initialize_super_admin(application.bot)
        except Exception as e:
            logger.warning(f"Super admin initialization skipped: {e}")
        
        # 🔥 Phase 3: 子 BOT 启动心跳上报
        if not is_main_bot:
            try:
                from ..services.heartbeat import create_heartbeat_task
                heartbeat = create_heartbeat_task(runtime_bot_id, interval=30)
                asyncio.create_task(heartbeat.start())
                logger.info(f"💓 [Phase 3] 子 BOT 心跳上报已启动: {runtime_bot_id}")
            except Exception as e:
                logger.warning(f"子 BOT 心跳启动失败: {e}")
        
        # 初始化定时任务服务（仅主机器人需要）
        # 双模式定时消息：每个主/子 Bot 都需要独立恢复自己的任务。
        try:
            from ..services.timed_message_manager import TimedMessageManager
            bot_id = application.bot_data.get('bot_id') or runtime_bot_id
            timed_manager = TimedMessageManager(application.bot, bot_id)
            application.timed_message_manager = timed_manager
            await timed_manager.start()
            logger.info(f"Timed message manager started for bot {bot_id}")
        except Exception as e:
            logger.error(f"Timed message manager startup failed: {e}", exc_info=True)

        if is_main_bot:
            schedule_service = ScheduleService(application.bot)
            application.schedule_service = schedule_service
            await schedule_service.start()
            logger.info("Schedule service started")
            
            # 启动限流记录清理任务
            # ⚠️ 临时禁用：start_rate_limit_cleanup 函数尚未实现
            # from ..utils.rate_limiter import start_rate_limit_cleanup
            # await start_rate_limit_cleanup(application)
            # logger.info("Rate limit cleanup task started")
            
            # ✅ 启动群组清理定时任务（每天凌晨3点执行，使用新架构 GroupTag）
            try:
                from ..services.group_tag_service import GroupTagService
                
                async def daily_group_cleanup():
                    """每日群组清理任务"""
                    try:
                        clean_result = await GroupTagService.sync_group_status(
                            bot=application.bot,
                            bot_id=runtime_bot_id
                        )
                        logger.info(
                            f"Daily group cleanup completed: "
                            f"valid={clean_result['valid']}, "
                            f"cleaned={clean_result['cleaned']}, "
                            f"synced={clean_result['synced']}"
                        )
                    except Exception as e:
                        logger.error(f"Daily group cleanup failed: {e}", exc_info=True)
                
                # 添加定时任务：每天凌晨3点执行
                schedule_service.scheduler.add_job(
                    daily_group_cleanup,
                    trigger='cron',
                    hour=3,
                    minute=0,
                    id='daily_group_cleanup',
                    name='每日群组清理',
                    replace_existing=True
                )
                logger.info("Daily group cleanup task scheduled (every day at 03:00)")
            except Exception as e:
                logger.warning(f"Daily group cleanup task setup failed: {e}")
            
            # 启动 Bot 实例管理器周期性任务
            from ..services.bot_instance_manager import bot_instance_manager
            await bot_instance_manager.start_periodic_tasks(application)
            logger.info("Bot instance manager periodic tasks started")

            # 🆕 注册试用到期扫描定时任务（每小时运行一次）
            try:
                from ..services.trial_expire_service import trial_expire_scan_job
                schedule_service.scheduler.add_job(
                    trial_expire_scan_job,
                    trigger='interval',
                    hours=1,
                    id='trial_expire_scan',
                    name='试用到期扫描',
                    replace_existing=True
                )
                logger.info("Trial expire scan task scheduled (every hour)")
            except Exception as e:
                logger.warning(f"Trial expire scan task setup failed: {e}")
            
            # 🆕 启动 Event Pipeline（事件管道保护层）
            try:
                from ..core.event_pipeline import event_pipeline
                await event_pipeline.start()
                logger.info("Event pipeline started (with Queue, Deduplication, Retry, DLQ, Rate Limit)")
            except Exception as e:
                logger.error(f"Failed to start event pipeline: {e}", exc_info=True)
            
            # 🆕 初始化 Runtime State Store（统一运行时状态存储）
            try:
                from ..core.runtime_state_store import runtime_state_store
                logger.info("Runtime State Store initialized (unified tenant runtime state management)")
            except Exception as e:
                logger.error(f"Failed to initialize runtime state store: {e}", exc_info=True)
            
            # 💰 启动 USDT 监听服务（用户私有级别）
            try:
                from ..services.usdt_listen_service import init_usdt_service
                usdt_service = init_usdt_service(application.bot)
                await usdt_service.start()
                logger.info("💰 USDT Listen Service started (TRC20 USDT monitoring for users)")
            except Exception as e:
                logger.error(f"Failed to start usdt listen service: {e}", exc_info=True)
            
            # 启动监控系统
            from ..utils.monitoring import start_bot_monitoring
            from config import config_manager
            admin_ids = [config_manager.telegram.super_admin_id] if config_manager.telegram.super_admin_id else []
            asyncio.create_task(start_bot_monitoring(application.bot, admin_ids, interval=60))
            logger.info("Bot monitoring system started")
            
            # 🔥 终极永久方案：主 Bot 启动后自动启动所有子 Bot
            try:
                logger.info("🚀 [终极方案] 主 Bot 启动完成，开始自动恢复所有子 Bot...")
                await BotFactory._start_all_child_bots()
            except Exception as e:
                logger.error(f"❌ 自动启动子 Bot 失败: {e}", exc_info=True)
            
            # 🔥 双重保障：异步再次提交恢复任务，避免启动早期依赖未就绪
            try:
                asyncio.create_task(BotFactory._start_all_child_bots())
                logger.info("🚀 [双重保障] 已提交异步任务启动所有子 Bot")
            except Exception as e:
                logger.error(f"❌ 异步启动子 Bot 任务提交失败: {e}", exc_info=True)
            
            # 🔥 Phase 3: 启动 SystemSupervisor（系统总控 + 自愈内核）
            try:
                from ..services.system_supervisor import system_supervisor
                asyncio.create_task(system_supervisor.start())
                logger.info("🚀 [Phase 3] SystemSupervisor 已启动（自愈内核）")
            except Exception as e:
                logger.error(f"❌ SystemSupervisor 启动失败: {e}", exc_info=True)
    
    @staticmethod
    async def _start_all_child_bots():
        """
        🔥 终极永久方案：自动启动所有 ACTIVE 状态的子 Bot
        保证：以后每次更新 → 主 Bot + 子 Bot 全部正常
        """
        from ..services.bot_instance_manager import bot_instance_manager
        
        try:
            logger.info("🚀 [ChildRestore] 开始执行子 Bot 自动恢复")
            results = await bot_instance_manager.load_all_running_bots()
            logger.info(
                "🚀 [ChildRestore] 自动恢复结果 total=%s started=%s failed=%s",
                results.get("total", 0),
                results.get("started", 0),
                results.get("failed", 0),
            )
            if results.get("details"):
                logger.info("🚀 [ChildRestore] 详细结果: %s", results["details"])
                
        except Exception as e:
            logger.error(f"⚠️ 自动启动子 Bot 时出错: {e}", exc_info=True)
    
    @staticmethod
    async def _set_bot_commands(bot):
        """
        ⭐ 设置 Bot 菜单命令（所有 Bot 统一）
        
        Args:
            bot: Telegram Bot 实例
        """
        try:
            commands = [
                BotCommand("start", "🚀 开始使用"),
                BotCommand("help", "❓ 查看帮助"),
                BotCommand("status", "📊 系统状态"),
            ]
            
            await bot.set_my_commands(commands)
            logger.info(f"Bot commands set successfully for @{bot.username}")
            
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}", exc_info=True)
    
    @staticmethod
    async def _initialize_super_admin(bot):
        """
        ✅ 初始化超级管理员（使用权限继承系统）
        
        当子 Bot 启动时，自动将创建者添加到 Admin 表，确保其拥有管理权限。
        
        Args:
            bot: Telegram Bot 实例
        """
        from ..services.permission_inheritance_system import permission_inheritance_system
        
        bot_id = "main_bot" if os.environ.get("IS_MAIN_BOT", "true").lower() != "false" else (config.INSTANCE_ID if hasattr(config, 'INSTANCE_ID') and config.INSTANCE_ID else str(bot.id))
        logger.info(f"Initializing super admin for bot {bot_id} (@{bot.username})")
        
        # ✅ 使用权限继承系统（传入 bot 作为 application 的替代）
        await permission_inheritance_system.inherit_permissions(bot_id, bot.token, bot)
    
    @staticmethod
    async def _post_shutdown(application: Application):
        """
        应用关闭时的清理操作
        
        Args:
            application: Application 实例
        """
        # 停止定时任务
        if hasattr(application, 'schedule_service') and application.schedule_service:
            await application.schedule_service.stop()
            logger.info("Schedule service stopped")

        if hasattr(application, 'timed_message_manager') and application.timed_message_manager:
            await application.timed_message_manager.stop()
            logger.info("Timed message manager stopped")
        
        # 🆕 停止 Event Pipeline
        try:
            from ..core.event_pipeline import event_pipeline
            await event_pipeline.stop()
            logger.info("Event pipeline stopped")
        except Exception as e:
            logger.error(f"Failed to stop event pipeline: {e}", exc_info=True)
        
        # 💰 停止 USDT 监听服务（用户私有级别）
        try:
            from ..services.usdt_listen_service import get_usdt_service
            usdt_service = get_usdt_service()
            if usdt_service:
                await usdt_service.stop()
                logger.info("💰 USDT Listen Service stopped")
        except Exception as e:
            logger.error(f"Failed to stop usdt listen service: {e}", exc_info=True)
        
        # 🆕 清理 Runtime State Store（可选，保留状态以便下次启动）
        try:
            from ..core.runtime_state_store import runtime_state_store
            # 注意：这里不清理状态，因为状态应该在内存中持久化
            # 如果需要清理，可以调用：await runtime_state_store.clear_global_state()
            logger.info("Runtime State Store preserved (in-memory state)")
        except Exception as e:
            logger.error(f"Failed to preserve runtime state store: {e}", exc_info=True)
        
        # 关闭数据库连接
        await close_db()
        logger.info("Database closed")
        
        # 记录关闭信息
        log_shutdown_info(logger)
    
    @staticmethod
    def _register_handlers(application: Application, is_main_bot: bool = False):
        """
        注册所有命令处理器（按优先级分组）
        
        Args:
            application: Application 实例
            is_main_bot: 是否为主机器人（影响 SaaS 功能的注册）
        """
        logger.info("Registering handlers...")
        
        # 🆕 群成员索引自动更新处理器（支持 @username 添加操作人）
        # ⚠️ 必须在最前面注册，group=-1 确保最高优先级
        from ..handlers.group_member_index_handler import register_group_member_index_handler
        register_group_member_index_handler(application)
        
        # ====================================================================
        # 第一优先级：具体命令（正则匹配，最精确）
        # ⚠️ DEPRECATED - 旧架构 Handler 注册
        # 这些 handler 已迁移到新架构 (UI Schema Engine + Runtime Router)
        # 保留作为向后兼容,预计 2026-Q3 删除
        # ====================================================================
        
        # Deprecated duplicate: saas_purchase.handle_bot_token_input owns Token rebind input now.
        # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, basic.handle_token_rebind_message, block=False), group=1)

        # 🆕 机器人状态管理面板 - 重置Token输入处理
        from ..handlers.bot_management_handler import handle_reset_token_input
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_reset_token_input,
            block=False
        ), group=2)
        
        # 基础命令
        application.add_handler(CommandHandler("start", basic.start_billing))
        application.add_handler(CommandHandler("stop", basic.stop_billing))
        
        # ✅ 新高级帮助中心
        from src.handlers.help_handler import show_help, handle_help_callback
        application.add_handler(CommandHandler("help", show_help))
        application.add_handler(CommandHandler("cancel", basic.handle_group_tag_cancel_command))
        application.add_handler(MessageHandler(filters.Regex(r'^帮助$'), show_help))
        
        # 帮助中心回调切页
        application.add_handler(CallbackQueryHandler(handle_help_callback, pattern="^help_"))
        
        application.add_handler(CommandHandler("status", basic.show_system_status))
        application.add_handler(CommandHandler("health", health_check.handle_health_check))  # 🆕 健康检查
        application.add_handler(CommandHandler("cancel_broadcast", menu.cancel_broadcast_command))  # 🆕 中断广播
        application.add_handler(MessageHandler(filters.Regex(r'^开始$'), basic.start_billing))
        application.add_handler(MessageHandler(filters.Regex(r'^停止$'), basic.stop_billing))
        application.add_handler(MessageHandler(filters.Regex(r'^上课$'), basic.unmute_group))
        application.add_handler(MessageHandler(filters.Regex(r'^下课$'), basic.mute_group))
        
        # 账单操作命令
        application.add_handler(CommandHandler("bill", billing.show_bills))
        application.add_handler(CommandHandler("mybill", billing.show_my_bills))
        application.add_handler(CommandHandler("revoke", billing.revoke_by_reply))
        
        # 操作人管理
        application.add_handler(CommandHandler("listop", operator.show_operators))  # 🆕 查看操作人（可点击）
        application.add_handler(MessageHandler(filters.Regex(r'^添加操作人'), operator.add_operator))
        application.add_handler(MessageHandler(filters.Regex(r'^删除操作人'), operator.remove_operator))
        application.add_handler(MessageHandler(filters.Regex(r'^显示操作人$'), operator.show_operators))
        application.add_handler(MessageHandler(filters.Regex(r'^设置全员$'), operator.enable_all_members))
        application.add_handler(MessageHandler(filters.Regex(r'^取消全员$'), operator.disable_all_members))
        application.add_handler(MessageHandler(filters.Regex(r'^显示全局操作人$'), operator.show_global_operators))
        application.add_handler(MessageHandler(filters.Regex(r'^添加全局操作人'), operator.add_global_operator))
        application.add_handler(MessageHandler(filters.Regex(r'^删除全局操作人'), operator.remove_global_operator))
        
        # 内部管理员管理（仅限私聊 + 全局权限人）
        # ⚠️ 合并相似正则，避免重复注册
        application.add_handler(MessageHandler(
            filters.Regex(r'^(添加内部成员|添加管理员)'),
            internal_admin.add_admin
        ))
        application.add_handler(MessageHandler(
            filters.Regex(r'^(删除内部成员|删除管理员)'),
            internal_admin.remove_admin
        ))
        application.add_handler(MessageHandler(
            filters.Regex(r'^(查看内部成员|查看内部管理员|查看管理员)'),
            internal_admin.show_admins
        ))
        application.add_handler(MessageHandler(filters.Regex(r'^/USERINFO$'), internal_admin.user_info))
        
        # 🆕 授权管理命令（必须在计算器之前注册，避免被拦截）
        # 原因：授权消息如"授权 -5108524003"包含减号，会被计算器handler匹配
        register_auth_commands(application)
        
        # 数值计算（必须在账单操作之前注册）
        # ✅ 修复：排除命令消息（以/开头的消息），避免拦截 /provision 等命令
        application.add_handler(MessageHandler(
            filters.Regex(r'^(?!.*:)\s*[\d\(\.][\d\s\+\-\*\/\.\(\)]*[\+\-\*\/][\d\s\+\-\*\/\.\(\)]*$'),
            calculator.handle_calculation
        ), group=-20)
        
        # 账单操作
        application.add_handler(MessageHandler(filters.Regex(r'^\+([\d\+\-\.\(\)\s]+)'), billing.handle_deposit), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^(?!.*下发).+?\+([\d\+\-\.\(\)\s]+)'), billing.handle_deposit), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^-(\d+(?:\.\d+)?)(?:\s+.*)?$'), billing.handle_deposit), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^(入款|上分|收)\s*[\d\+\-\.\(\)\s]+[uU]?(?:\s+.*)?$'), billing.handle_deposit), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^\d+(?:\.\d+)?[uU](?:\s+.*)?$'), billing.handle_deposit), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^下发[\d\+\-\.\(\)\s]+'), billing.handle_withdraw), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^.+?下发[\d\+\-\.\(\)\s]+'), billing.handle_withdraw), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^(下分|支)\s*[\d\+\-\.\(\)\s]+[uU]?(?:\s+.*)?$'), billing.handle_withdraw), group=-19)
        application.add_handler(MessageHandler(filters.Regex(r'^P[+-]\d+'), billing.handle_storage), group=-19)
        
        # 账单查询（已移除：全部账单、账单汇总、完整账单）
        application.add_handler(MessageHandler(filters.Regex(r'^(显示账单|查看账单)$'), billing.show_bills), group=-18)
        application.add_handler(MessageHandler(filters.Regex(r'^我$'), billing.show_my_bills), group=-18)
        
        # 账单管理
        application.add_handler(MessageHandler(filters.Regex(r'^撤销入款$'), billing.revoke_deposit))
        application.add_handler(MessageHandler(filters.Regex(r'^撤销下发$'), billing.revoke_withdraw))
        application.add_handler(MessageHandler(filters.Regex(r'^撤销$'), billing.revoke_by_reply))
        application.add_handler(MessageHandler(filters.Regex(r'^删除账单$'), billing.delete_bills))
        application.add_handler(MessageHandler(filters.Regex(r'^保存账单$'), billing.save_bills))
        
        # 参数设置
        application.add_handler(MessageHandler(filters.Regex(r'^设置汇率\d+'), settings.set_exchange_rate))
        application.add_handler(MessageHandler(filters.Regex(r'^设置.+?汇率\d+'), settings.set_exchange_rate))
        application.add_handler(MessageHandler(filters.Regex(r'^设置费率\d+'), settings.set_fee_rate))
        application.add_handler(MessageHandler(filters.Regex(r'^设置.+?费率\d+'), settings.set_fee_rate))
        # 查看/删除用户配置功能已取消
        
        # 显示设置
        application.add_handler(MessageHandler(filters.Regex(r'^设置(入款|下发)条数\d+$'), settings.set_display_count))
        # 切换币种功能已取消（默认只有USDT）
        application.add_handler(MessageHandler(filters.Regex(r'^(记账置顶|置顶关闭|开启置顶|关闭置顶)$'), settings.toggle_pin))
        application.add_handler(MessageHandler(filters.Regex(r'^(纯净模式|显示回复人|显示入账人)$'), settings.toggle_display_mode))
        application.add_handler(MessageHandler(filters.Regex(r'^设置日切时间') & filters.ChatType.PRIVATE, settings.set_day_cut_time))
        application.add_handler(MessageHandler(filters.Regex(r'^查看日切') & filters.ChatType.PRIVATE, settings.show_day_cut))
        application.add_handler(MessageHandler(filters.Regex(r'^关闭日切') & filters.ChatType.PRIVATE, settings.close_day_cut))
        application.add_handler(MessageHandler(filters.Regex(r'^设置日切时间') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        application.add_handler(MessageHandler(filters.Regex(r'^查看日切') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        application.add_handler(MessageHandler(filters.Regex(r'^关闭日切') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        application.add_handler(MessageHandler(filters.Regex(r'^群组配置$'), settings.show_group_config))
        
        # 🆕 额度管理命令
        from ..handlers.quota_commands import cmd_set_quota, cmd_disable_quota
        application.add_handler(MessageHandler(
            filters.Regex(r'^(设置额度|/setquota)'),
            cmd_set_quota
        ))
        # ✅ 修复：移除 $ 结尾，允许命令后有空格
        application.add_handler(MessageHandler(
            filters.Regex(r'^(关闭额度设置|/disablequota)'),
            cmd_disable_quota
        ))
        
        #  入群欢迎语配置命令（已迁移到面板系统，保留旧命令作为兼容）
        # 旧命令将在 2026-Q3 删除
        # 新架构使用: welcome_panel.py + 内联按钮面板
        
        # 下发地址
        application.add_handler(MessageHandler(filters.Regex(r'^设置下发地址'), settings.set_withdraw_address))
        application.add_handler(MessageHandler(filters.Regex(r'^删除下发地址'), settings.delete_withdraw_address))
        application.add_handler(MessageHandler(filters.Regex(r'^下发地址$'), settings.show_withdraw_address))
        
        # 分组管理
        application.add_handler(MessageHandler(filters.Regex(r'^添加分组'), group_tags.add_group_tag))
        application.add_handler(MessageHandler(filters.Regex(r'^删除分组'), group_tags.delete_group_tag))
        application.add_handler(MessageHandler(filters.Regex(r'^查看分组$'), group_tags.list_group_tags))
        
        # 📡 广播分组管理（已废弃，使用 GroupTag 新架构）
        # application.add_handler(CommandHandler('create_broadcast_group', broadcast_group.handle_create_broadcast_group))
        # application.add_handler(CommandHandler('delete_broadcast_group', broadcast_group.handle_delete_broadcast_group))
        # application.add_handler(CommandHandler('broadcast_groups', broadcast_group.handle_broadcast_group_list))
        
        # 查询功能
        application.add_handler(MessageHandler(filters.Regex(r'^h0$'), query.query_huobi_price))
        application.add_handler(MessageHandler(filters.Regex(r'^b0$'), query.query_binance_price))
        
        # 🆕 群组TRC20地址自动识别 - 只在群组中生效
        # 识别格式：以T开头的34位地址
        application.add_handler(MessageHandler(
            filters.Regex(r'^T[A-Za-z0-9]{33}$') & filters.ChatType.GROUPS,
            query.query_trc20_address
        ))
        
        application.add_handler(MessageHandler(filters.Regex(r'^计算.+'), query.calculate_expression))
        
        # 汇率查询回调处理（筛选按钮）
        application.add_handler(CallbackQueryHandler(query.handle_rate_callback, pattern=r'^rate:'))
        
        # 辅助功能
        application.add_handler(MessageHandler(filters.Regex(r'^通知所有人$'), query.mention_all))
        
        # ✅ 模式1：群组命令方式（快速操作）
        # 只匹配"设置分组 XXX"格式，精确、快速、不误判
        application.add_handler(MessageHandler(
            filters.Regex(r'^设置分组\s+.+') & filters.ChatType.GROUPS,
            query.set_group_tag
        ))
        
        # 九宫格菜单按钮处理器 - 🆕 已迁移到 UI Schema Engine
        # 旧代码：硬编码的 MessageHandler（已废弃）
        # 新代码：使用 UI Schema + Runtime Router 动态路由
        from ..core.ui_schema_registry import register_ui_schema_routes
        from ..core.runtime_router import runtime_router
        
        register_ui_schema_routes()
        
        # 🆕 初始化分组管理事件监听器（实现私聊和群组数据同步）
        from ..core.event_bus import event_bus
        from ..core.group_tag_event_listener import init_group_tag_event_listener
        init_group_tag_event_listener(event_bus)
        logger.info("✅ Group tag event listener initialized")
        
        # 🆕 注册授权管理命令（插件式接入，默认不生效）
        # ⚠️ 注意：已在上方第430行注册过，此处删除重复注册
        
        # 🆕 注册群组管理命令（退群等功能）
        from ..handlers.group_commands import register_group_commands
        register_group_commands(application)
        
        # 🆕 阶段 2：注册菜单适配层（将旧 handler 适配到新架构）
        from ..handlers.menu_adapter import register_menu_adapters
        register_menu_adapters(runtime_router)
        logger.info("✅ Menu adapter routes registered")

        # 🆕 注册 USDT 监听回调（新版）
        usdt_monitor.register_callbacks()
        logger.info("✅ USDT monitor callbacks registered")
        
        # 🆕 群组绑定分组命令处理器
        from ..handlers.group_binding import handle_bind_group_tag, handle_unbind_group_tag
        application.add_handler(MessageHandler(
            filters.Regex(r'^绑定分组\s+.+$'),
            handle_bind_group_tag
        ))
        application.add_handler(MessageHandler(
            filters.Regex(r'^解绑分组$'),
            handle_unbind_group_tag
        ))
        logger.info("✅ Group binding commands registered")
        
        # 捕获所有菜单按钮文本，通过 Runtime Router 路由
        # 匹配所有可能的菜单按钮文本（包括带 emoji 和不带 emoji 的版本）
        # 根据脑图权限设计：
        # - 超级管理员/Bot创建者: 使用说明、广播用户、运行统计、分组管理、功能设置、群发广播、个人中心、能量TRX、USDT监听
        # - 管理员: 使用说明、创建续费、运行统计、分组管理、功能设置、群发广播、个人中心、能量TRX、USDT监听
        # - 普通用户: 使用说明、创建续费、功能设置、联系客服、能量TRX、USDT监听
        application.add_handler(MessageHandler(
            filters.Regex(r'^(📖 使用说明|使用说明|📢 广播用户|广播用户|💰 创建续费|创建续费|📊 运行统计|运行统计|📁 分组管理|分组管理|⚙️ 功能设置|功能设置|📝 申请试用|申请试用|👤 个人中心|个人中心|⚡ 能量TRX|能量TRX|💰 USDT监听|USDT监听|💬 联系客服|联系客服|✂️ 全局日切设置|全局日切设置|📊 全局记账条数设置|全局记账条数设置|👤 全局记账成员名字显示|全局记账成员名字显示|👋 全局入群欢迎语|全局入群欢迎语|💬 全局关键词设置|全局关键词设置|🍀 用户更名检测|用户更名检测|👥 添加管理员|添加管理员|🔐 授权群组|授权群组|💬 消息中心|消息中心|🛠 超管后台|超管后台)$'),
            runtime_router.handle_update
        ))

        # 🆕 注册 CallbackQueryHandler 处理所有 v1: 开头的回调（USDT监听等内联按钮）
        application.add_handler(CallbackQueryHandler(
            runtime_router.handle_update,
            pattern=r'^(v1:|usdt:)'
        ))
        logger.info("✅ Runtime router callback handler registered for v1: and legacy usdt: routes")
        
        # 自定义功能处理器（合并相似正则）
        application.add_handler(MessageHandler(
            filters.Regex(r'^(添加自定义按钮 |添加按钮 |设置按钮 )') & filters.ChatType.PRIVATE,
            custom.handle_custom_button
        ))
        application.add_handler(MessageHandler(filters.Regex(r'^删除按钮') & filters.ChatType.PRIVATE, custom.handle_custom_button))
        application.add_handler(MessageHandler(
            filters.Regex(r'^(显示按钮$|查看按钮$)') & filters.ChatType.PRIVATE,
            custom.handle_custom_button
        ))
        application.add_handler(MessageHandler(filters.Regex(r'^创建账单按钮方式$') & filters.ChatType.PRIVATE, custom.handle_custom_button))
        application.add_handler(MessageHandler(filters.Regex(r'^(添加自定义按钮 |添加按钮 |设置按钮 )') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        application.add_handler(MessageHandler(filters.Regex(r'^删除按钮') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        application.add_handler(MessageHandler(filters.Regex(r'^(显示按钮$|查看按钮$)') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        
        # 🆕 欢迎语管理命令（新版面板系统）
        from ..handlers.welcome_panel import handle_welcome_command, welcome_panel_callback, handle_welcome_content
        application.add_handler(MessageHandler(filters.Regex(r'^设置欢迎语$') & filters.ChatType.PRIVATE, handle_welcome_command))
        application.add_handler(MessageHandler(filters.Regex(r'^设置欢迎语$') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        
        # 欢迎词面板回调处理器
        application.add_handler(CallbackQueryHandler(welcome_panel_callback, pattern=r'^welcome_'))

        # 欢迎词内容接收处理器（高优先级，group=1）
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_welcome_content,
            block=False
        ), group=1)

        # 💰 USDT监听 - 优化版（完全无二次确认）
        # 处理所有USDT相关的消息输入（添加地址、删除地址、设置推送群）
        # 放在欢迎语处理器之后，避免拦截欢迎语输入
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            usdt_monitor.handle_address_input
        ), group=2)
        
        # 🆕 首次授权欢迎语管理命令（新版面板系统）
        from ..handlers.first_auth_welcome_panel import handle_first_auth_welcome_command, first_auth_welcome_panel_callback, handle_first_auth_welcome_content
        # 首次欢迎语配置功能已取消
        
        # 首次授权欢迎语面板回调处理器
        application.add_handler(CallbackQueryHandler(first_auth_welcome_panel_callback, pattern=r'^first_auth_welcome_'))
        
        # 首次授权欢迎语内容接收处理器（高优先级，group=1）
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_first_auth_welcome_content,
            block=False
        ), group=1)

        # 🆕 高优先级私聊状态输入处理器
        # 这些处理器必须在通用文本处理器之前运行，否则会被前面的泛匹配 handler 抢走。
        from ..handlers import ad_handler
        from ..handlers import bot_group_features
        from ..handlers import topic_mode_handler
        application.add_handler(MessageHandler(
            filters.Regex(r'^(?!\d+:[A-Za-z0-9_-]{20,}$)(?!开通)(?!取消$)[\s\S]*$') & (filters.TEXT | filters.FORWARDED) & filters.ChatType.PRIVATE & ~filters.COMMAND,
            menu_callbacks.handle_broadcast_message_input,
            block=False
        ), group=-8)
        application.add_handler(MessageHandler(
            filters.Regex(r'^(?!\d+:[A-Za-z0-9_-]{20,}$)(?!开通)(?!取消$)[\s\S]*$') & filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
            basic.handle_group_tag_rename_input,
            block=False
        ), group=-7)
        application.add_handler(MessageHandler(
            filters.Regex(r'^(?!\d+:[A-Za-z0-9_-]{20,}$)(?!开通)(?!取消$)[\s\S]*$') & filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
            basic.handle_group_tag_create_input,
            block=False
        ), group=-6)
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
            bot_group_features.handle_private_input,
            block=False
        ), group=-5)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            ad_handler.handle_ad_text_input,
            block=False
        ), group=-4)
        application.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO) & filters.ChatType.PRIVATE & ~filters.COMMAND,
            menu.handle_edit_mode_message,
            block=False
        ), group=-3)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            menu.handle_admin_add_input,
            block=False
        ), group=-2)

        # 🆕 我的群组 / 机器人进群消息 / 群组话题模式
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND & (filters.ChatType.GROUPS),
            bot_group_features.handle_group_reply
        ), group=3)
        # 🆕 管理员私聊bot自动转发给活跃目标用户
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
            topic_mode_handler.handle_admin_private_message
        ), group=4)
        # 🆕 话题模式 - 机器人被拉入群组检测（startgroup=topic_mode）
        application.add_handler(MessageHandler(
            filters.Regex(r'^/start\s+topic_mode'),
            topic_mode_handler.handle_topic_group_join
        ), group=1)
        
        # ====================================================================
        # 🆕 超级管理员功能（全局消息转发、拉黑管理、超管后台）
        # ====================================================================
        from ..handlers import super_admin_v2_handler
        
        # 1. 全局消息转发（私聊消息→超管）- 高优先级
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
            super_admin_v2_handler.handle_global_forward,
            block=False
        ), group=5)
        
        # 2. 超管私聊状态输入（只注册一次，避免重复回复）
        application.add_handler(MessageHandler(
            filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE,
            super_admin_v2_handler.handle_super_admin_private_message,
            block=False
        ), group=6)
        
        # ====================================================================
        # 💬 关键词回复处理器（优化版）
        # ====================================================================
        
        # 关键词配置命令（统一入口：私聊和群组都使用相同命令）
        application.add_handler(MessageHandler(
            filters.Regex(r'^关键词配置$') & filters.ChatType.PRIVATE,
            custom.handle_keyword_config
        ))
        
        # 创建关键词命令
        application.add_handler(MessageHandler(
            filters.Regex(r'^创建关键词') & filters.ChatType.PRIVATE,
            custom.handle_keyword_config
        ))
        
        # 删除关键词命令
        application.add_handler(MessageHandler(
            filters.Regex(r'^删除关键词') & filters.ChatType.PRIVATE,
            custom.handle_keyword_config
        ))
        application.add_handler(MessageHandler(filters.Regex(r'^关键词配置$') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        application.add_handler(MessageHandler(filters.Regex(r'^创建关键词') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        application.add_handler(MessageHandler(filters.Regex(r'^删除关键词') & filters.ChatType.GROUPS, settings.prompt_private_global_settings))
        
        # 查看关键词命令（私聊专用）
        application.add_handler(MessageHandler(
            filters.Regex(r'^(查看关键词|关键词列表)$') & filters.ChatType.PRIVATE,
            custom_keyword.handle_view_keywords_command
        ))
        application.add_handler(CallbackQueryHandler(
            custom_keyword.handle_private_keyword_callback,
            pattern=r'^private_keyword_'
        ))
        application.add_handler(CallbackQueryHandler(
            custom_keyword.handle_delete_keyword_callback,
            pattern=r'^del_kw_'
        ))
        
        # ====================================================================
        # 第二优先级：带状态检查的等待输入处理器（按业务逻辑分组）
        # ====================================================================
        # ✅ 重要：这些处理器都有内部状态检查，只在特定状态下响应
        # 🚨 关键修复：必须把带状态的 handler 放在 check_and_reply_keyword 之前，
        #         因为如果 check_and_reply_keyword 先执行并 return，
        #         消息不会自动传递给后续的 handler
        # 🚨 关键修复：多个状态 handler 之间，必须按业务优先级排序！
        #         第一个匹配的 handler 会拦截消息，即使它 return
        #         所以要把更具体/更优先的状态放在前面
        
        # 2. SaaS 创建机器人流程
        # ✅ 只在私聊中响应，且有状态检查
        # ✅ 关键修复：这个处理器专门处理 Bot Token，所以要能匹配 Token 格式！
        # ✅ 重要：这个handler必须在 check_and_reply_keyword 之前注册，确保优先处理Token
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE & filters.ChatType.PRIVATE,
            saas_purchase.handle_bot_token_input,
            block=False
        ))

        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE & filters.ChatType.PRIVATE,
            saas_purchase.handle_confirm_text,
            block=False
        ))
        
        # ✅ 广播用户消息输入处理器（必须在关键词处理器之前，内部有状态检查）
        application.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO) & filters.ChatType.PRIVATE & ~filters.COMMAND,
            menu.handle_broadcast_users_message,
            block=False
        ))

        # ====================================================================
        #  🆕 超管手动开通套餐功能（必须在 check_and_reply_keyword 之前注册）
        # ====================================================================
        # 原因：check_and_reply_keyword 会拦截所有文本消息，必须先让专用 handler 处理
        from ..handlers.admin_manual_provision import register_manual_provision_handlers
        register_manual_provision_handlers(application)
        
        # ====================================================================
        #  关键词自动回复监听器（重要！）
        # ====================================================================
        # 这个处理器会在所有消息上检查是否有匹配的关键词并自动回复
        # 优先级：群关键词 > 全局关键词
        # ✅ 注意：它内部会检查等待状态，如果处于等待状态会 return 让消息继续传递
        # ✅ 关键修复：排除Bot Token格式（数字:字母），避免拦截provision流程的Token输入
        application.add_handler(MessageHandler(
            filters.Regex(r'^(?!\d+:[A-Za-z0-9_-]{20,}$)[\s\S]*$') & filters.TEXT & ~filters.COMMAND,
            custom.check_and_reply_keyword,
            block=False
        ))
        
        # 3. 群组管理相关（有状态检查）
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, advanced.handle_ad_content_input, block=False))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, advanced.handle_group_broadcast_message, block=False))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, advanced.handle_group_broadcast_selection, block=False))
        # ✅ 模式2：私聊交互方式（安全操作）
        # 带状态检查的全局TEXT处理器，只在私聊中响应
        application.add_handler(MessageHandler(
            filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
            advanced.handle_group_tag_input,
            block=False
        ))

        # 4. 机器人设置相关（有状态检查）
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, advanced.handle_bot_settings_input, block=False))

        # 8. 最后兜底：通用广播消息等待
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, advanced.handle_broadcast_message, block=False))
        
        # @all 命令
        application.add_handler(MessageHandler(filters.Regex(r'^(通知所有人|@all|@everyone)$'), custom.handle_mention_all))
        
        # ====================================================================
        # Callback 查询处理器
        # ====================================================================
        
        application.add_handler(CallbackQueryHandler(
            super_admin_v2_handler.handle_super_admin_callback,
            pattern=r'^sa:'
        ))

        # 菜单按钮回调
        application.add_handler(CallbackQueryHandler(menu.menu_callback, pattern=r'^menu_'))
        # 🆕 修改 pattern 支持新的 callback_data 格式 (module:action)
        application.add_handler(CallbackQueryHandler(menu.handle_sub_menu_callback,
            pattern=r'^(s:|query_|settings_|menu_back|quick_|daycut_set_|daycut_disable|display_deposit_|display_withdraw_|showname_deposit_toggle|showname_withdraw_toggle|daycut:|display:|showname:|welcome:|keyword:|admin:|auth:|authgroup:|rename:|groupmember:|impersonation:|settings:|menu:|delete_menu|export_bills|broadcast_users:|show_broadcast|broadcast_target_|broadcast_start_input|broadcast_cancel|broadcast_forward|broadcast_send|mygroups:|botjoin:|topic:|topic_cs:|timed:|timedmsg:|ad:|sa:|bot_mgmt:)'))
        
        # 使用说明回调
        application.add_handler(CallbackQueryHandler(basic.show_help_guide_callback, pattern=r'^show_help_guide$'))
        
        # 🆕 分组管理回调
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_detail_callback,
            pattern=r'^group_tag_detail_'
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_manage_callback,
            pattern=r'^group_tag_manage_'
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_add_callback,
            pattern=r'^group_tag_add_(?!select_)'  # 排除 group_tag_add_select_
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_add_select_callback,
            pattern=r'^group_tag_add_select_'
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_remove_callback,
            pattern=r'^group_tag_remove_(?!select_)'  # 排除 group_tag_remove_select_
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_remove_select_callback,
            pattern=r'^group_tag_remove_select_'
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_create_callback,
            pattern=r'^group_tag_create$'
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_rename_callback,
            pattern=r'^group_tag_rename_'
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_delete_callback,
            pattern=r'^group_tag_delete_(?!list$)'
        ))
        # 🆕 分组管理 - 删除分组列表
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_delete_list_callback,
            pattern=r'^group_tag_delete_list$'
        ))
        # 🆕 分组管理 - 分页
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_page_callback,
            pattern=r'^group_tag_page_'
        ))
        # 🆕 分组管理 - 关闭
        application.add_handler(CallbackQueryHandler(
            basic.handle_group_tag_close_callback,
            pattern=r'^group_tag_close$'
        ))
        application.add_handler(CallbackQueryHandler(
            basic.handle_back_to_group_manage_callback,
            pattern=r'^back_to_group_manage$'
        ))
        #  返回主菜单回调（删除当前消息并重新显示主菜单）
        application.add_handler(CallbackQueryHandler(
            basic.handle_back_to_main_menu_callback,
            pattern=r'^back_to_main_menu$'
        ))
        
        # 日切时间设置回调（排除全局日切设置的回调）
        application.add_handler(CallbackQueryHandler(settings.day_cut_callback, pattern=r'^daycut_(?!set_|disable)'))
        
        # 实时汇率设置回调
        application.add_handler(CallbackQueryHandler(settings.real_time_rate_callback, pattern=r'^rate_'))
        
        # 收款二维码回调
        application.add_handler(CallbackQueryHandler(query.qrcode_callback, pattern=r'^qrcode_'))
        
        # 交易记录回调
        application.add_handler(CallbackQueryHandler(query.txhistory_callback, pattern=r'^txhistory_'))
        
        # 👥 群组状态变更处理器（监听机器人被踢/退群/重新进群）
        chat_member_handler.register_chat_member_handler(application)
        
        #  入群欢迎语事件处理器（监听新用户进群）
        register_join_welcome_handler(application)
        

        
        # 🆕 群组成员更名检测通知处理器
        from ..handlers.member_rename_handler import register_member_rename_handler
        register_member_rename_handler(application)
        
        # 🆕 SaaS 购买流程（支持无限裂变）
        application.add_handler(MessageHandler(filters.Regex(r'^(套餐|/plans)$'), saas_purchase.show_pricing_plans))
        application.add_handler(CallbackQueryHandler(saas_purchase.handle_plan_selection, pattern=r'^select_plan_'))
        application.add_handler(CallbackQueryHandler(saas_purchase.confirm_payment, pattern=r'^confirm_payment$'))
        application.add_handler(CallbackQueryHandler(saas_purchase.cancel_payment, pattern=r'^cancel_payment$'))
        application.add_handler(CallbackQueryHandler(saas_purchase.start_create_bot_flow, pattern=r'^start_create_bot$'))
        application.add_handler(CallbackQueryHandler(saas_purchase.confirm_create_bot, pattern=r'^confirm_create_bot$'))
        application.add_handler(CallbackQueryHandler(saas_purchase.cancel_create_bot, pattern=r'^cancel_create_bot$'))
        
        # ✅ 删除账单二次确认回调
        from ..handlers.billing import confirm_delete_bills_callback, cancel_delete_bills_callback
        application.add_handler(CallbackQueryHandler(confirm_delete_bills_callback, pattern=r'^confirm_delete_bills_'))
        application.add_handler(CallbackQueryHandler(cancel_delete_bills_callback, pattern=r'^cancel_delete_bills$'))
        
        # 🆕 管理员手动开通订阅命令（仅主机器人超管可用，支持线下付款场景）
        from ..handlers.admin_manual_activate import handle_manual_activate, handle_manual_extend
        application.add_handler(CommandHandler("activate", handle_manual_activate))
        application.add_handler(CommandHandler("extend", handle_manual_extend))
        
        # 🆕 申请试用页面按钮回调（立即申请试用、直接购买套餐、联系客服咨询）
        application.add_handler(CallbackQueryHandler(menu.handle_trial_apply_callback, pattern=r'^trial:apply$'))
        application.add_handler(CallbackQueryHandler(menu.handle_billing_self_renew_callback, pattern=r'^billing:self_renew$'))
        application.add_handler(CallbackQueryHandler(menu.handle_contact_support_callback, pattern=r'^contact:support$'))
        
        # ⚠️ 注意：register_manual_provision_handlers 已在上方第670行之前注册
        # 原因：必须在 check_and_reply_keyword 之前注册，否则消息会被拦截
        
        logger.info("All handlers registered successfully")
    
    @staticmethod
    async def _error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        错误处理器
            
        Args:
            update: Update 对象
            context: Context 对象
        """
        # ✅ 忽略 Telegram 的 "Message is not modified" 错误（这是 Telegram 的优化机制，不是真正的错误）
        error_str = str(context.error)
        if "Message is not modified" in error_str or "message is not modified" in error_str.lower():
            logger.debug(f"[IGNORED] Telegram message not modified error (Telegram optimization)")
            return
            
        # 🔍 添加详细的错误日志和堆栈跟踪
        import traceback
        tb_str = traceback.format_exception(type(context.error), context.error, context.error.__traceback__)
        logger.error(f"Update {update} caused error {context.error}")
        logger.error(f"Full traceback:\n{''.join(tb_str)}")
        try:
            if context.chat_data.pop('_accounting_committed', None):
                logger.error(
                    "[ACCOUNTING_DEBUG] post_commit_error_suppressed=true\n"
                    "handler=BotFactory._error_handler\n"
                    "error_traceback=%s",
                    ''.join(tb_str),
                )
                return
        except Exception:
            logger.error("Failed to check accounting committed flag", exc_info=True)

        try:
            message = update.effective_message if update else None
            reply_message = getattr(message, "reply_to_message", None)
            reply_user = getattr(reply_message, "from_user", None)
            text = (getattr(message, "text", None) or "").strip()
            if reply_user and getattr(reply_user, "is_bot", False) and reply_user.id != context.bot.id:
                from ..utils.parser import CommandParser

                if CommandParser.is_accounting_command(text) or CommandParser.is_pure_math_expression(text):
                    logger.error(
                        "[ACCOUNTING_DEBUG] cross_bot_reply_error_suppressed=true\n"
                        "handler=BotFactory._error_handler\n"
                        "reply_bot_id=%s\n"
                        "current_bot_id=%s\n"
                        "text=%s\n"
                        "error_traceback=%s",
                        reply_user.id,
                        context.bot.id,
                        text,
                        ''.join(tb_str),
                    )
                    return
        except Exception:
            logger.error("Failed to apply cross-bot accounting suppression", exc_info=True)
            
        # 如果有消息，尝试回复错误信息
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    " 处理您的请求时出现错误，请稍后重试。"
                )
            except Exception:
                pass


# 导入 asyncio（在类定义之后，避免循环导入）
import asyncio

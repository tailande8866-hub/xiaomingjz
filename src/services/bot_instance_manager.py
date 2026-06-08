"""
SaaS Bot实例管理器

提供完整的Bot实例生命周期管理：
- 进程监控和自动重启
- 健康检查
- 资源限制
- 订阅到期自动停止
- 定期清理无效实例
"""
import os
import sys
import json
import time
import asyncio
import logging
import re
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from sqlalchemy import select, and_, or_, update

from ..models import BotCreation, Subscription, PricingPlan, get_db, get_db_session

logger = logging.getLogger(__name__)


class BotInstanceManager:
    """
    Bot实例管理器
    
    负责：
    1. 启动和停止Bot实例
    2. 监控进程健康状态
    3. 自动重启崩溃的进程
    4. 订阅到期自动停止
    5. 清理无效实例
    """
    
    def __init__(self):
        # ⭐ Runtime Registry - 完整的运行时状态管理
        self.runtime_registry: Dict[str, dict] = {}  # {instance_id: runtime_info}
        
        # 存储运行中的进程: {instance_id: process_info}
        self.running_processes: Dict[str, dict] = {}
        
        # 进程重启计数: {instance_id: restart_count}
        self.restart_counts: Dict[str, int] = {}
        
        # 重启时间窗口记录: {instance_id: [timestamp1, timestamp2, ...]}
        self.restart_timestamps: Dict[str, list] = {}
        
        # 最大重启次数（本地测试时禁用，运营时启用）
        self.max_restart_count = None  # None表示无限制
        
        # ⭐ 重启限流策略：5分钟内最多重启3次（本地测试时禁用）
        self.restart_window_seconds = 0  # ⭐ 本地测试：0表示禁用时间窗口
        self.max_restarts_in_window = None  # ⭐ 本地测试：None表示无限制
        
        # 健康检查间隔（秒）
        self.health_check_interval = 30  # ⭐ 从60秒缩短到30秒，更快发现问题
        
        # 订阅检查间隔（秒）
        self.subscription_check_interval = 3600  # 每小时
        
        # 重启间隔（本地测试时禁用，运营时启用）
        self.restart_delay = 0  # 0表示立即重启，无延迟
        
        # ⭐ 心跳超时阈值（秒）- 超过此时间未更新心跳视为异常
        self.heartbeat_timeout = 90  # 90秒（3倍于正常心跳间隔）
        
    def resolve_runtime_instance_dir(self, bot_creation: BotCreation) -> Path:
        """Resolve an instance directory that actually exists in the current runtime."""
        candidates: list[Path] = []
        if bot_creation.instance_dir:
            candidates.append(Path(bot_creation.instance_dir))

        project_root = Path(__file__).resolve().parents[2]
        candidates.extend([
            project_root / "instances" / bot_creation.instance_id,
            project_root / "bot_instances" / bot_creation.instance_id,
            Path("instances") / bot_creation.instance_id,
            Path("bot_instances") / bot_creation.instance_id,
        ])

        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate.resolve()
            except Exception:
                continue

        preferred = (project_root / "instances" / bot_creation.instance_id).resolve()
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred

    async def _discover_recoverable_bots_from_filesystem(self, db, existing_instance_ids: set[str]) -> list[BotCreation]:
        """
        从实例目录扫描可恢复的子 Bot。

        适用于数据库记录丢失、但 bot_instances/instances 目录仍保留的场景。
        会在数据库中补建缺失的 BotCreation 和 owner 管理员记录，再返回可启动对象。
        """
        from ..repositories.bot_management_repo import BotAdminRepository
        from ..services.env_validator import EnvValidator
        from ..utils.token_encryptor import token_encryptor

        discovered: list[BotCreation] = []
        seen_instance_ids = set(existing_instance_ids)
        project_root = Path(__file__).resolve().parents[2]
        search_roots = [
            project_root / "bot_instances",
            project_root / "instances",
            Path("bot_instances"),
            Path("instances"),
        ]
        token_pattern = re.compile(r"^\d+:[A-Za-z0-9_-]+$")

        for root in search_roots:
            if not root.exists():
                continue

            for instance_dir in root.iterdir():
                if not instance_dir.is_dir():
                    continue

                if instance_dir.name in {"template_bot", "__pycache__"}:
                    continue

                env_path = instance_dir / ".env"
                start_path = instance_dir / "start.py"
                if not env_path.exists():
                    logger.warning(
                        "[BotInstanceManager] Skip filesystem recovery for %s: missing .env (%s)",
                        instance_dir.name,
                        env_path,
                    )
                    continue

                if not start_path.exists():
                    logger.warning(
                        "[BotInstanceManager] Skip filesystem recovery for %s: missing start.py (%s)",
                        instance_dir.name,
                        start_path,
                    )
                    continue

                try:
                    env_vars = EnvValidator.parse_env_file(str(env_path))
                    instance_id = (env_vars.get("INSTANCE_ID") or instance_dir.name or "").strip()
                    if not instance_id or instance_id == "main_bot" or instance_id in seen_instance_ids:
                        continue

                    bot_token = (env_vars.get("BOT_TOKEN") or "").strip()
                    bot_username = (env_vars.get("BOT_USERNAME") or "").strip()
                    owner_raw = (
                        env_vars.get("OWNER_USER_ID")
                        or env_vars.get("BOT_OWNER_ID")
                        or ""
                    ).strip()
                    if not bot_token:
                        logger.warning(
                            "[BotInstanceManager] Skip filesystem recovery for %s: missing BOT_TOKEN",
                            instance_id,
                        )
                        continue

                    if not token_pattern.match(bot_token):
                        logger.warning(
                            "[BotInstanceManager] Skip filesystem recovery for %s: invalid BOT_TOKEN format",
                            instance_id,
                        )
                        continue

                    if not bot_username:
                        logger.warning(
                            "[BotInstanceManager] Skip filesystem recovery for %s: missing BOT_USERNAME",
                            instance_id,
                        )
                        continue

                    if not owner_raw:
                        logger.warning(
                            "[BotInstanceManager] Skip filesystem recovery for %s: missing OWNER_USER_ID/BOT_OWNER_ID",
                            instance_id,
                        )
                        continue

                    try:
                        owner_user_id = int(owner_raw)
                    except ValueError:
                        logger.warning(
                            "[BotInstanceManager] Skip filesystem recovery for %s: invalid OWNER_USER_ID/BOT_OWNER_ID=%s",
                            instance_id,
                            owner_raw,
                        )
                        continue

                    super_admin_raw = (env_vars.get("SUPER_ADMIN_ID") or owner_raw).strip()
                    try:
                        super_admin_id = int(super_admin_raw)
                    except ValueError:
                        super_admin_id = owner_user_id

                    existing_result = await db.execute(
                        select(BotCreation).where(BotCreation.instance_id == instance_id)
                    )
                    existing_bot = existing_result.scalar_one_or_none()
                    if existing_bot:
                        existing_lifecycle = str(getattr(existing_bot, "lifecycle_status", "") or "").upper()
                        existing_token_status = str(getattr(existing_bot, "token_status", "") or "").lower()
                        if existing_lifecycle != "ACTIVE" or existing_token_status == "invalid":
                            logger.warning(
                                "[BotInstanceManager] Skip filesystem recovery for %s: database record exists but is inactive/token-invalid (lifecycle=%s token=%s)",
                                instance_id,
                                existing_lifecycle or "unknown",
                                existing_token_status or "unknown",
                            )
                            continue
                        seen_instance_ids.add(instance_id)
                        discovered.append(existing_bot)
                        continue

                    encrypted_token = token_encryptor.encrypt_to_base64(bot_token)
                    bot_username_value = bot_username or None
                    bot_name = (env_vars.get("BOT_NAME") or bot_username or instance_id).strip()
                    parent_bot_id = (env_vars.get("PARENT_BOT_ID") or "").strip() or None
                    root_bot_id = (env_vars.get("ROOT_BOT_ID") or "").strip() or instance_id
                    try:
                        tree_depth = int(env_vars.get("TREE_DEPTH") or 1)
                    except ValueError:
                        tree_depth = 1

                    bot_creation = BotCreation(
                        telegram_id=owner_user_id,
                        bot_token=encrypted_token,
                        bot_username=bot_username_value,
                        bot_name=bot_name,
                        instance_id=instance_id,
                        instance_dir=str(instance_dir),
                        db_path=str(instance_dir / f"{instance_id}.db") if (instance_dir / f"{instance_id}.db").exists() else None,
                        env_path=str(env_path),
                        status=env_vars.get("BOT_STATUS") or "running",
                        process_id=None,
                        super_admin_id=super_admin_id,
                        config_json=json.dumps({
                            "owner_user_id": owner_user_id,
                            "bot_username": bot_username,
                            "bot_name": bot_name,
                            "recovered_from_filesystem": True,
                        }),
                        parent_bot_id=parent_bot_id,
                        root_bot_id=root_bot_id,
                        tree_depth=tree_depth,
                        core_version="1.0.0",
                        ui_version="1.0.0",
                        permission_version="1.0.0",
                        lifecycle_status=(env_vars.get("LIFECYCLE_STATUS") or "ACTIVE").upper(),
                        expire_time=None,
                        token_status=(env_vars.get("TOKEN_STATUS") or "normal").lower(),
                    )

                    db.add(bot_creation)
                    await db.flush()

                    await BotAdminRepository(db).create_or_update_admin(
                        bot_id=instance_id,
                        user_id=owner_user_id,
                        role="owner",
                        username=bot_username_value,
                        first_name=bot_name,
                    )
                    await db.commit()

                    discovered.append(bot_creation)
                    seen_instance_ids.add(instance_id)
                    logger.info(
                        "[BotInstanceManager] Recovered bot from filesystem: %s (@%s) owner=%s dir=%s",
                        instance_id,
                        bot_username or "unknown",
                        owner_user_id,
                        instance_dir,
                    )
                except Exception as e:
                    logger.error(
                        "[BotInstanceManager] Failed to recover bot from %s: %s",
                        instance_dir,
                        e,
                        exc_info=True,
                    )

        return discovered

    async def start_bot_instance(self, bot_creation: BotCreation) -> bool:
        """
        启动Bot实例（带资源限制和监控 + 幂等控制 + .env验证修复）
        
        Args:
            bot_creation: Bot创建记录
        
        Returns:
            是否成功启动
        """
        from .bot_instance_registry import bot_instance_registry
        from .env_validator import EnvAutoRepair
        from ..utils.token_encryptor import token_encryptor
        
        try:
            instance_id = bot_creation.instance_id
            resolved_instance_dir = self.resolve_runtime_instance_dir(bot_creation)
            if bot_creation.instance_dir != str(resolved_instance_dir):
                logger.warning(
                    f"[BotInstanceManager] Rebinding instance_dir for {instance_id}: "
                    f"{bot_creation.instance_dir} -> {resolved_instance_dir}"
                )
                bot_creation.instance_dir = str(resolved_instance_dir)
                bot_creation.env_path = str(resolved_instance_dir / ".env")
            
            # 🔥 Phase 2-3: 幂等控制 - 检查是否可以启动
            if not bot_instance_registry.can_start(instance_id):
                logger.warning(f"[BotInstanceManager] ❌ BOT {instance_id} 已在运行中或正在启动，跳过")
                return True  # 返回True表示"已运行"，不是错误
            
            # 🔥 Phase 2-1: .env 验证和自动修复
            try:
                decrypted_token = token_encryptor.decrypt_from_base64(bot_creation.bot_token)
                env_valid, env_result = await EnvAutoRepair.validate_and_repair(
                    instance_dir=str(resolved_instance_dir),
                    bot_token=decrypted_token,
                    instance_id=bot_creation.instance_id,
                    bot_owner_id=bot_creation.telegram_id,
                    bot_username=bot_creation.bot_username or "",
                    auto_repair=True
                )
                if not env_valid:
                    logger.error(f"[BotInstanceManager] ❌ BOT {instance_id} .env 验证失败且无法修复: {env_result.errors}")
                    return False
            except Exception as e:
                logger.error(f"[BotInstanceManager] ❌ BOT {instance_id} .env 验证异常: {e}")
                return False
            
            # 🔥 Phase 2-3: 标记为启动中
            if not bot_instance_registry.mark_starting(instance_id):
                logger.warning(f"[BotInstanceManager] ❌ BOT {instance_id} 无法标记为 starting，可能已在运行中")
                return True
            
            # ✅ 关键修复：启动前先检查并停止可能存在的旧进程
            if bot_creation.process_id:
                try:
                    import psutil
                    if psutil.pid_exists(bot_creation.process_id):
                        old_process = psutil.Process(bot_creation.process_id)
                        # 检查是否是 Python 进程
                        if 'python' in old_process.name().lower():
                            logger.warning(f"Found old process for {instance_id} (PID: {bot_creation.process_id}), stopping it...")
                            old_process.terminate()
                            old_process.wait(timeout=5)
                            logger.info(f"Old process stopped successfully")
                except Exception as e:
                    logger.warning(f"Failed to stop old process: {e}")
            
            # 检查是否已经在运行（旧逻辑，保留作为双重检查）
            if instance_id in self.running_processes:
                proc_info = self.running_processes[instance_id]
                if proc_info['process'].poll() is None:
                    logger.warning(f"Bot {instance_id} is already running")
                    # 同步 registry 状态
                    bot_instance_registry.mark_running(instance_id, proc_info['process'])
                    return True
                else:
                    # 进程已结束，清理旧记录
                    del self.running_processes[instance_id]
            
            # 构建启动命令
            start_script = resolved_instance_dir / "start.py"
            
            if not start_script.exists():
                logger.error(f"Start script not found: {start_script}")
                return False
            
            # 设置资源限制（Windows下有限支持）
            if os.name == 'nt':
                # Windows: 使用 DETACHED_PROCESS 或 CREATE_NO_WINDOW
                # 关键修复：将子Bot日志输出到文件，便于调试
                stdout_file = open(str(resolved_instance_dir / "bot.log"), "a", encoding="utf-8")
                stderr_file = open(str(resolved_instance_dir / "error.log"), "a", encoding="utf-8")
                
                process = subprocess.Popen(
                    [sys.executable, str(start_script)],
                    cwd=str(resolved_instance_dir),
                    stdout=stdout_file,  # 输出到日志文件
                    stderr=stderr_file,  # 错误输出到日志文件
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
            else:
                # Linux/Mac: 使用setsid和资源限制
                # 🔥 关键修复：将子Bot日志输出到文件，避免PIPE阻塞
                stdout_file = open(str(resolved_instance_dir / "bot.log"), "a", encoding="utf-8")
                stderr_file = open(str(resolved_instance_dir / "error.log"), "a", encoding="utf-8")
                
                process = subprocess.Popen(
                    [sys.executable, str(start_script)],
                    cwd=str(resolved_instance_dir),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    stdin=subprocess.DEVNULL,
                    preexec_fn=os.setsid,
                    close_fds=True
                )
            
            # 🔥 Phase 2-3: 标记为运行中
            bot_instance_registry.mark_running(instance_id, process)
            
            # 记录进程信息（旧逻辑，保留兼容）
            process_info = {
                'process': process,
                'pid': process.pid,
                'started_at': datetime.utcnow(),
                'last_check': datetime.utcnow(),
                'restart_count': self.restart_counts.get(instance_id, 0)
            }
            self.running_processes[instance_id] = process_info
            
            # ⭐ 初始化 Runtime Registry
            now = datetime.utcnow()
            self.runtime_registry[instance_id] = {
                'runtime_status': 'running',
                'runtime_started_at': now,
                'runtime_last_heartbeat': now,
                'runtime_restart_count': self.restart_counts.get(instance_id, 0),
                'runtime_pid': process.pid,
                'runtime_bot_username': bot_creation.bot_username,
                'runtime_telegram_id': bot_creation.telegram_id,
                'runtime_instance_dir': str(resolved_instance_dir),
                'runtime_created_at': now,
                'runtime_health_score': 100  # 健康度评分（0-100）
            }
            
            logger.info(f"✅ Runtime registry initialized for {instance_id}")
            
            # 更新数据库记录
            bot_creation.status = "running"
            bot_creation.process_id = process.pid
            bot_creation.started_at = datetime.utcnow()
            bot_creation.last_heartbeat = datetime.utcnow()
            
            try:
                async with get_db_session() as db:
                    await db.execute(
                        update(BotCreation)
                        .where(BotCreation.instance_id == instance_id)
                        .values(
                            instance_dir=str(resolved_instance_dir),
                            env_path=str(resolved_instance_dir / ".env"),
                            status="running",
                            process_id=process.pid,
                            started_at=datetime.utcnow(),
                            last_heartbeat=datetime.utcnow(),
                        )
                    )
                    await db.commit()
            except Exception as e:
                logger.error(f"Error updating bot status: {e}", exc_info=True)
            
            logger.info(f"Bot {instance_id} started with PID {process.pid}")
            return True
            
        except Exception as e:
            logger.error(f"Error starting bot {bot_creation.instance_id}: {e}", exc_info=True)
            # 🔥 Phase 2-3: 标记为失败
            bot_instance_registry.mark_failed(bot_creation.instance_id, str(e))
            bot_creation.status = "error"
            return False
    
    async def stop_bot_instance(self, instance_id: str, force: bool = False) -> bool:
        """
        停止Bot实例
        
        Args:
            instance_id: 实例ID
            force: 是否强制停止
        
        Returns:
            是否成功停止
        """
        from .bot_instance_registry import bot_instance_registry
        
        # 🔥 Phase 2-3: 标记为停止中
        bot_instance_registry.mark_stopping(instance_id)
        
        try:
            # 从数据库中获取Bot信息
            async with get_db_session() as db:
                query = select(BotCreation).where(BotCreation.instance_id == instance_id)
                result = await db.execute(query)
                bot_creation = result.scalar_one_or_none()
                
                if not bot_creation:
                    logger.error(f"Bot {instance_id} not found in database")
                    return False
                
                # 尝试从运行列表中停止
                if instance_id in self.running_processes:
                    proc_info = self.running_processes[instance_id]
                    process = proc_info['process']
                    
                    if force:
                        # 强制终止
                        process.kill()
                        logger.info(f"Force killed bot {instance_id} (PID: {process.pid})")
                    else:
                        # 优雅终止
                        process.terminate()
                        try:
                            process.wait(timeout=10)  # 等待10秒
                            logger.info(f"Gracefully stopped bot {instance_id} (PID: {process.pid})")
                        except subprocess.TimeoutExpired:
                            process.kill()
                            logger.warning(f"Bot {instance_id} didn't stop gracefully, force killed")
                    
                    # 清理运行列表
                    del self.running_processes[instance_id]
                    
                    # ⭐ 清理 Runtime Registry
                    if instance_id in self.runtime_registry:
                        runtime_info = self.runtime_registry[instance_id]
                        runtime_info['runtime_status'] = 'stopped'
                        runtime_info['runtime_stopped_at'] = datetime.utcnow()
                        logger.info(f"✅ Runtime registry updated for {instance_id}: stopped")
                
                # 🔥 Phase 2-3: 标记为已停止
                bot_instance_registry.mark_stopped(instance_id)
                
                # 更新数据库状态
                bot_creation.status = "stopped"
                bot_creation.stopped_at = datetime.utcnow()
                await db.flush()
                
                logger.info(f"Bot {instance_id} stopped successfully")
                return True
        
        except Exception as e:
            logger.error(f"Error in stop_bot_instance: {e}", exc_info=True)
            return False
    
    async def check_health(self, instance_id: str) -> dict:
        """
        检查Bot实例健康状态（增强版 - 包含心跳检测和僵尸进程检测）
        
        Args:
            instance_id: 实例ID
        
        Returns:
            健康状态信息
        """
        result = {
            'instance_id': instance_id,
            'is_healthy': False,
            'status': 'unknown',
            'message': '',
            'health_score': 0,
            'is_zombie': False
        }
        
        try:
            # 从数据库获取Bot信息
            async with get_db_session() as db:
                query = select(BotCreation).where(BotCreation.instance_id == instance_id)
                result_query = await db.execute(query)
                bot_creation = result_query.scalar_one_or_none()
                
                if not bot_creation:
                    result['message'] = 'Bot not found in database'
                    return result
                
                result['status'] = bot_creation.status
                
                # ⭐ 检查是否在 Runtime Registry 中
                if instance_id not in self.runtime_registry:
                    result['is_healthy'] = False
                    result['message'] = 'Not in runtime registry'
                    result['health_score'] = 0
                    return result
                
                runtime_info = self.runtime_registry[instance_id]
                now = datetime.utcnow()
                
                # ⭐ 检查进程是否在运行列表中
                if instance_id in self.running_processes:
                    proc_info = self.running_processes[instance_id]
                    process = proc_info['process']
                    
                    # 检查进程是否还在运行
                    poll_result = process.poll()
                    
                    if poll_result is None:
                        # ✅ 进程正在运行
                        
                        # ⭐ 计算心跳超时
                        last_heartbeat = runtime_info.get('runtime_last_heartbeat')
                        if last_heartbeat:
                            heartbeat_age = (now - last_heartbeat).total_seconds()
                            
                            if heartbeat_age > self.heartbeat_timeout:
                                # ⚠️ 心跳超时 - 可能是Polling卡死
                                result['is_healthy'] = False
                                result['is_zombie'] = True
                                result['message'] = f'Heartbeat timeout ({heartbeat_age:.0f}s > {self.heartbeat_timeout}s)'
                                result['health_score'] = 20
                                runtime_info['runtime_status'] = 'zombie'
                                logger.warning(
                                    f"⚠️ Bot {instance_id} is ZOMBIE: "
                                    f"heartbeat age={heartbeat_age:.0f}s, "
                                    f"PID={process.pid}"
                                )
                                
                                # 尝试自动重启僵尸进程
                                await self._auto_restart(instance_id, bot_creation)
                            else:
                                # ✅ 心跳正常
                                result['is_healthy'] = True
                                result['message'] = 'Running normally'
                                result['health_score'] = 100
                                runtime_info['runtime_status'] = 'running'
                                
                                # 更新心跳时间
                                runtime_info['runtime_last_heartbeat'] = now
                                bot_creation.last_heartbeat = now
                                await db.flush()
                        else:
                            # 首次检查，没有心跳记录
                            result['is_healthy'] = True
                            result['message'] = 'Running (first check)'
                            result['health_score'] = 80
                            runtime_info['runtime_last_heartbeat'] = now
                    else:
                        # ❌ 进程已退出
                        result['is_healthy'] = False
                        result['message'] = f'Process exited with code {poll_result}'
                        result['health_score'] = 0
                        runtime_info['runtime_status'] = 'crashed'
                        bot_creation.status = 'crashed'
                        await db.flush()
                        
                        # 尝试自动重启
                        await self._auto_restart(instance_id, bot_creation)
                else:
                    # ❌ 不在运行列表中
                    if bot_creation.status == 'running':
                        result['is_healthy'] = False
                        result['message'] = 'Process not tracked but marked as running'
                        result['health_score'] = 0
                        runtime_info['runtime_status'] = 'lost'
                        bot_creation.status = 'unknown'
                        await db.flush()
                    else:
                        result['is_healthy'] = False
                        result['message'] = f'Status: {bot_creation.status}'
                        result['health_score'] = 0
                
                # 更新 Runtime Registry 的健康度评分
                runtime_info['runtime_health_score'] = result['health_score']
                
                return result
        
        except Exception as e:
            logger.error(f"Error in check_health: {e}", exc_info=True)
            result['message'] = str(e)
            result['health_score'] = 0
            return result
    
    async def _auto_restart(self, instance_id: str, bot_creation: BotCreation):
        """
        自动重启Bot实例（带重启限流策略）
        
        Args:
            instance_id: 实例ID
            bot_creation: Bot创建记录
        """
        try:
            now = time.time()
            
            # ⭐ 本地测试模式：禁用重启限流
            if self.max_restarts_in_window is None or self.restart_window_seconds == 0:
                logger.debug(f"Restart rate limiting disabled (local test mode)")
            else:
                # ⭐ 运营模式：启用重启限流
                # 初始化重启时间窗口记录
                if instance_id not in self.restart_timestamps:
                    self.restart_timestamps[instance_id] = []
                
                # 清理过期的重启记录（超出时间窗口的）
                window_start = now - self.restart_window_seconds
                self.restart_timestamps[instance_id] = [
                    ts for ts in self.restart_timestamps[instance_id]
                    if ts > window_start
                ]
                
                # 检查重启频率限制
                recent_restarts = len(self.restart_timestamps[instance_id])
                
                if recent_restarts >= self.max_restarts_in_window:
                    logger.error(
                        f"🚫 Restart rate limit exceeded for {instance_id}: "
                        f"{recent_restarts} restarts in {self.restart_window_seconds}s "
                        f"(max: {self.max_restarts_in_window}). "
                        f"Stopping auto-restart to prevent restart storm."
                    )
                    
                    bot_creation.status = "restart_limited"
                    
                    try:
                        async with get_db_session() as db:
                            await db.flush()
                    except Exception:
                        pass
                    
                    return
            
            # 本地测试模式：无限制重启
            if self.max_restart_count is None:
                restart_count = self.restart_counts.get(instance_id, 0)
                self.restart_counts[instance_id] = restart_count + 1
                
                # ⭐ 记录重启时间戳
                self.restart_timestamps[instance_id].append(now)
                
                logger.info(
                    f"Auto restarting bot {instance_id} "
                    f"(attempt {restart_count + 1}, unlimited mode, "
                    f"{len(self.restart_timestamps[instance_id])} restarts in window)"
                )
                
                # 本地测试：无延迟立即重启
                if self.restart_delay > 0:
                    await asyncio.sleep(self.restart_delay)
                
                # 重新启动
                success = await self.start_bot_instance(bot_creation)
                
                if success:
                    logger.info(f"✅ Bot {instance_id} restarted successfully")
                else:
                    logger.error(f"❌ Failed to restart bot {instance_id}")
                return
            
            # 运营模式：检查总重启次数
            restart_count = self.restart_counts.get(instance_id, 0)
            
            if restart_count >= self.max_restart_count:
                logger.error(
                    f"Bot {instance_id} has restarted {restart_count} times, "
                    f"reached max limit ({self.max_restart_count}). Stopping."
                )
                bot_creation.status = "failed"
                
                try:
                    async with get_db_session() as db:
                        await db.flush()
                except Exception:
                    pass
                
                return
            
            # 增加重启计数
            self.restart_counts[instance_id] = restart_count + 1
            
            # ⭐ 记录重启时间戳
            self.restart_timestamps[instance_id].append(now)
            
            logger.info(
                f"Auto restarting bot {instance_id} "
                f"(attempt {restart_count + 1}/{self.max_restart_count}, "
                f"{len(self.restart_timestamps[instance_id])} restarts in window)"
            )
            
            # 等待延迟后重启
            if self.restart_delay > 0:
                await asyncio.sleep(self.restart_delay)
            
            # 重新启动
            success = await self.start_bot_instance(bot_creation)
            
            if success:
                logger.info(f"✅ Bot {instance_id} restarted successfully")
            else:
                logger.error(f"❌ Failed to restart bot {instance_id}")
                
        except Exception as e:
            logger.error(f"Error auto restarting bot {instance_id}: {e}", exc_info=True)
    
    async def check_all_bots_health(self) -> dict:
        """
        检查所有Bot实例的健康状态
        
        Returns:
            健康检查结果
        """
        results = {
            'total': 0,
            'healthy': 0,
            'unhealthy': 0,
            'details': []
        }
        
        try:
            # 获取所有标记为running的Bot
            async with get_db_session() as db:
                query = select(BotCreation).where(
                    and_(
                        BotCreation.lifecycle_status == "ACTIVE",
                        (BotCreation.token_status.is_(None) | (BotCreation.token_status != "invalid")),
                        (BotCreation.expire_time.is_(None) | (BotCreation.expire_time > datetime.utcnow())),
                        BotCreation.instance_id != "main_bot",
                    )
                )
                result_query = await db.execute(query)
                bots = result_query.scalars().all()
                
                results['total'] = len(bots)
                
                for bot in bots:
                    health = await self.check_health(bot.instance_id)
                    results['details'].append(health)
                    
                    if health['is_healthy']:
                        results['healthy'] += 1
                    else:
                        results['unhealthy'] += 1
                
                return results
        
        except Exception as e:
            logger.error(f"Error in check_all_bots_health: {e}", exc_info=True)
            # 返回默认结果而不是None
            return results
        
        # 如果意外到达这里，也返回默认结果
        return results
    
    async def stop_expired_subscriptions(self) -> dict:
        """
        停止订阅到期的Bot实例
        
        Returns:
            停止结果统计
        """
        results = {
            'checked': 0,
            'stopped': 0,
            'errors': 0,
            'details': []
        }
        
        try:
            # 获取所有活跃的订阅
            async with get_db_session() as db:
                now = datetime.utcnow()
                
                # 查找已过期的活跃订阅
                query = select(Subscription).where(
                    and_(
                        Subscription.status == "active",
                        Subscription.expire_date < now
                    )
                )
                result_query = await db.execute(query)
                expired_subscriptions = result_query.scalars().all()
                
                results['checked'] = len(expired_subscriptions)
                
                for subscription in expired_subscriptions:
                    telegram_id = subscription.telegram_id
                    
                    # 检查是否为管理员（管理员的机器人不受订阅限制）
                    from ..utils.internal_member_checker import is_admin
                    if await is_admin(telegram_id):
                        logger.info(f"Skipping expired subscription check for admin: {telegram_id}")
                        # 更新订阅状态为expired，但不停止机器人
                        subscription.status = "expired"
                        await db.flush()
                        continue
                    
                    # 更新订阅状态
                    subscription.status = "expired"
                    
                    # 查找该用户的所有Bot
                    bots_query = select(BotCreation).where(
                        and_(
                            BotCreation.telegram_id == telegram_id,
                            BotCreation.status.in_(["running", "creating"])
                        )
                    )
                    bots_result = await db.execute(bots_query)
                    user_bots = bots_result.scalars().all()
                    
                    # 停止每个Bot
                    for bot in user_bots:
                        try:
                            success = await self.stop_bot_instance(bot.instance_id)
                            
                            if success:
                                results['stopped'] += 1
                                results['details'].append({
                                    'instance_id': bot.instance_id,
                                    'telegram_id': telegram_id,
                                    'action': 'stopped'
                                })
                                logger.info(
                                    f"Stopped bot {bot.instance_id} "
                                    f"(subscription expired for user {telegram_id})"
                                )
                            else:
                                results['errors'] += 1
                                
                        except Exception as e:
                            results['errors'] += 1
                            logger.error(
                                f"Error stopping bot {bot.instance_id}: {e}",
                                exc_info=True
                            )
                    
                    await db.flush()
                
                return results
        
        except Exception as e:
            logger.error(f"Error in stop_expired_subscriptions: {e}", exc_info=True)
            return results
    
    async def cleanup_invalid_instances(self) -> dict:
        """
        清理无效的Bot实例
        
        清理条件：
        1. 状态为error/failed超过7天
        2. 进程不存在但状态仍为running
        3. 目录不存在
        
        Returns:
            清理结果统计
        """
        results = {
            'checked': 0,
            'cleaned': 0,
            'errors': 0,
            'details': []
        }
        
        try:
            async with get_db_session() as db:
                now = datetime.utcnow()
                seven_days_ago = now - timedelta(days=7)
                
                # 查找需要清理的Bot
                query = select(BotCreation).where(
                    or_(
                        # 状态为error/failed超过7天
                        and_(
                            BotCreation.status.in_(["error", "failed"]),
                            BotCreation.updated_at < seven_days_ago
                        ),
                        # 状态为stopped超过30天
                        and_(
                            BotCreation.status == "stopped",
                            BotCreation.stopped_at < (now - timedelta(days=30))
                        )
                    )
                )
                result_query = await db.execute(query)
                invalid_bots = result_query.scalars().all()
                
                results['checked'] = len(invalid_bots)
                
                for bot in invalid_bots:
                    try:
                        instance_id = bot.instance_id
                        instance_dir = Path(bot.instance_dir)
                        
                        # 删除目录
                        if instance_dir.exists():
                            import shutil
                            shutil.rmtree(instance_dir, ignore_errors=True)
                            logger.info(f"Deleted directory for bot {instance_id}")
                        
                        # 从运行列表中移除
                        if instance_id in self.running_processes:
                            del self.running_processes[instance_id]
                        
                        # 从数据库删除记录
                        await db.delete(bot)
                        
                        results['cleaned'] += 1
                        results['details'].append({
                            'instance_id': instance_id,
                            'action': 'cleaned'
                        })
                        
                        logger.info(f"Cleaned up invalid bot {instance_id}")
                        
                    except Exception as e:
                        results['errors'] += 1
                        logger.error(
                            f"Error cleaning up bot {bot.instance_id}: {e}",
                            exc_info=True
                        )
                
                await db.commit()
                return results
        
        except Exception as e:
            logger.error(f"Error in cleanup_invalid_instances: {e}", exc_info=True)
            return results
    
    async def load_all_running_bots(self) -> dict:
        """
        加载并启动数据库中所有标记为running的Bot实例
        
        Returns:
            加载结果统计
        """
        results = {
            'total': 0,
            'started': 0,
            'failed': 0,
            'details': []
        }
        
        try:
            # 获取所有标记为running的Bot
            async with get_db_session() as db:
                query = select(BotCreation).where(
                    and_(
                        BotCreation.lifecycle_status == "ACTIVE",
                        (BotCreation.token_status.is_(None) | (BotCreation.token_status != "invalid")),
                        (BotCreation.expire_time.is_(None) | (BotCreation.expire_time > datetime.utcnow())),
                        BotCreation.instance_id != "main_bot",
                    )
                )
                result_query = await db.execute(query)
                bots = result_query.scalars().all()
                existing_instance_ids = {bot.instance_id for bot in bots}

                recovered_bots = await self._discover_recoverable_bots_from_filesystem(db, existing_instance_ids)
                if recovered_bots:
                    recovered_ids = {bot.instance_id for bot in recovered_bots}
                    bots.extend([bot for bot in recovered_bots if bot.instance_id not in existing_instance_ids])
                    logger.info(
                        "Recovered %s bots from filesystem fallback: %s",
                        len(recovered_ids - existing_instance_ids),
                        sorted(recovered_ids - existing_instance_ids),
                    )
                
                results['total'] = len(bots)
                logger.info(f"Found {len(bots)} bots to load from database")
                
                for bot in bots:
                    try:
                        instance_id = bot.instance_id
                        logger.info(
                            "Loading bot: %s (@%s) status=%s lifecycle=%s token=%s instance_dir=%s",
                            instance_id,
                            bot.bot_username,
                            getattr(bot, "status", None),
                            getattr(bot, "lifecycle_status", None),
                            getattr(bot, "token_status", None),
                            getattr(bot, "instance_dir", None),
                        )
                        
                        # 检查是否已经在运行
                        if instance_id in self.running_processes:
                            proc_info = self.running_processes[instance_id]
                            if proc_info['process'].poll() is None:
                                logger.info(f"Bot {instance_id} already running, skipping")
                                results['started'] += 1
                                continue
                        
                        # 启动Bot实例
                        success = await self.start_bot_instance(bot)
                        
                        if success:
                            results['started'] += 1
                            logger.info(f"✅ Bot {instance_id} started successfully")
                        else:
                            results['failed'] += 1
                            logger.error(f"❌ Failed to start bot {instance_id}")
                        
                        # 等待一下，避免同时启动太多进程
                        await asyncio.sleep(1)
                        
                    except Exception as e:
                        results['failed'] += 1
                        logger.error(f"Error loading bot {bot.instance_id}: {e}", exc_info=True)
                
                return results
        
        except Exception as e:
            logger.error(f"Error in load_all_running_bots: {e}", exc_info=True)
            return results
    
    async def start_periodic_tasks(self, application):
        """
        启动周期性任务
        
        Args:
            application: Telegram应用实例
        """
        from apscheduler.triggers.interval import IntervalTrigger
        
        # 健康检查任务（每分钟）
        health_check_job = application.job_queue.run_repeating(
            lambda context: asyncio.create_task(self._periodic_health_check()),
            interval=self.health_check_interval,
            first=60,
            name="bot_health_check"
        )
        logger.info(f"Bot health check task started (every {self.health_check_interval}s)")
        
        # 订阅检查任务（每小时）
        subscription_check_job = application.job_queue.run_repeating(
            lambda context: asyncio.create_task(self._periodic_subscription_check()),
            interval=self.subscription_check_interval,
            first=300,  # 5分钟后首次执行
            name="subscription_check"
        )
        logger.info(f"Subscription check task started (every {self.subscription_check_interval}s)")
        
        # 清理任务（每天凌晨3点）
        from apscheduler.triggers.cron import CronTrigger
        cleanup_job = application.job_queue.run_daily(
            lambda context: asyncio.create_task(self._periodic_cleanup()),
            time=datetime.strptime("03:00", "%H:%M").time(),
            name="cleanup_invalid_instances"
        )
        logger.info("Daily cleanup task started (at 03:00)")
        
        # 🆕 数据漂移检测任务（每天凌晨4点执行）
        drift_check_job = application.job_queue.run_daily(
            lambda context: asyncio.create_task(self._periodic_drift_check()),
            time=datetime.strptime("04:00", "%H:%M").time(),
            name="daily_drift_check"
        )
        logger.info("Daily drift check task started (at 04:00)")
        
        return {
            'health_check': health_check_job,
            'subscription_check': subscription_check_job,
            'cleanup': cleanup_job,
            'drift_check': drift_check_job  # 🆕
        }
    
    async def _periodic_health_check(self):
        """周期性健康检查"""
        try:
            results = await self.check_all_bots_health()
            
            # 检查results是否为None或不是字典
            if results is None or not isinstance(results, dict):
                logger.warning("Health check returned invalid result")
                return
            
            if results.get('unhealthy', 0) > 0:
                logger.warning(
                    f"Health check: {results.get('healthy', 0)}/{results.get('total', 0)} bots healthy, "
                    f"{results.get('unhealthy', 0)} unhealthy"
                )
            else:
                logger.debug(
                    f"Health check: All {results.get('total', 0)} bots healthy"
                )
                
        except Exception as e:
            logger.error(f"Error in periodic health check: {e}", exc_info=True)
    
    async def _periodic_subscription_check(self):
        """周期性订阅检查"""
        try:
            results = await self.stop_expired_subscriptions()
            
            if results['stopped'] > 0:
                logger.info(
                    f"Subscription check: Stopped {results['stopped']} bots "
                    f"({results['errors']} errors)"
                )
            else:
                logger.debug("Subscription check: No expired subscriptions")
                
        except Exception as e:
            logger.error(f"Error in periodic subscription check: {e}", exc_info=True)
    
    async def _periodic_cleanup(self):
        """周期性清理"""
        try:
            results = await self.cleanup_invalid_instances()
            
            if results['cleaned'] > 0:
                logger.info(
                    f"Cleanup: Cleaned {results['cleaned']} invalid instances "
                    f"({results['errors']} errors)"
                )
            else:
                logger.debug("Cleanup: No invalid instances found")
                
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}", exc_info=True)
    
    async def _periodic_drift_check(self):
        """🆕 周期性数据漂移检测（每天凌晨4点执行）"""
        try:
            from .data_drift_prevention import data_drift_prevention_system
            
            logger.info("🔍 Starting daily drift check...")
            results = await data_drift_prevention_system.run_full_check()
            
            if results['total_issues'] > 0:
                logger.warning(
                    f"📊 Drift check completed: "
                    f"{results['total_issues']} issues found, "
                    f"{results['fixed_issues']} issues fixed"
                )
                
                # 如果有未修复的问题，发送告警
                if results['total_issues'] > results['fixed_issues']:
                    logger.error(
                        f"⚠️ Drift check warning: "
                        f"{results['total_issues'] - results['fixed_issues']} issues NOT fixed!"
                    )
            else:
                logger.info("✅ Drift check completed: No issues found")
                
        except Exception as e:
            logger.error(f"Error in periodic drift check: {e}", exc_info=True)
    
    def get_running_count(self) -> int:
        """获取运行中的Bot数量"""
        count = 0
        for instance_id, proc_info in self.running_processes.items():
            if proc_info['process'].poll() is None:
                count += 1
        return count
    
    def get_all_running_instances(self) -> List[str]:
        """获取所有运行中的实例ID"""
        running = []
        for instance_id, proc_info in self.running_processes.items():
            if proc_info['process'].poll() is None:
                running.append(instance_id)
        return running
    
    def get_runtime_status(self) -> dict:
        """
        ⭐ 获取所有Bot的运行时状态（用于监控面板）
        
        Returns:
            完整的运行时状态信息
        """
        now = datetime.utcnow()
        status = {
            'total_bots': len(self.runtime_registry),
            'running_bots': 0,
            'zombie_bots': 0,
            'crashed_bots': 0,
            'stopped_bots': 0,
            'lost_bots': 0,
            'bots': []
        }
        
        for instance_id, runtime_info in self.runtime_registry.items():
            bot_status = {
                'instance_id': instance_id,
                'bot_username': runtime_info.get('runtime_bot_username', 'unknown'),
                'telegram_id': runtime_info.get('runtime_telegram_id', 0),
                'status': runtime_info.get('runtime_status', 'unknown'),
                'health_score': runtime_info.get('runtime_health_score', 0),
                'pid': runtime_info.get('runtime_pid', None),
                'started_at': runtime_info.get('runtime_started_at'),
                'last_heartbeat': runtime_info.get('runtime_last_heartbeat'),
                'restart_count': runtime_info.get('runtime_restart_count', 0),
                'uptime_seconds': 0,
                'heartbeat_age_seconds': 0
            }
            
            # 计算运行时间
            if runtime_info.get('runtime_started_at'):
                uptime = (now - runtime_info['runtime_started_at']).total_seconds()
                bot_status['uptime_seconds'] = int(uptime)
            
            # 计算心跳年龄
            if runtime_info.get('runtime_last_heartbeat'):
                heartbeat_age = (now - runtime_info['runtime_last_heartbeat']).total_seconds()
                bot_status['heartbeat_age_seconds'] = int(heartbeat_age)
            
            # 统计各种状态的Bot数量
            bot_state = runtime_info.get('runtime_status', 'unknown')
            if bot_state == 'running':
                status['running_bots'] += 1
            elif bot_state == 'zombie':
                status['zombie_bots'] += 1
            elif bot_state == 'crashed':
                status['crashed_bots'] += 1
            elif bot_state == 'stopped':
                status['stopped_bots'] += 1
            elif bot_state == 'lost':
                status['lost_bots'] += 1
            
            status['bots'].append(bot_status)
        
        return status


# 全局实例管理器
bot_instance_manager = BotInstanceManager()

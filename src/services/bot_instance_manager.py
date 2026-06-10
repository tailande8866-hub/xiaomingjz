"""
SaaS Bot瀹炰緥绠＄悊鍣?
鎻愪緵瀹屾暣鐨凚ot瀹炰緥鐢熷懡鍛ㄦ湡绠＄悊锛?- 杩涚▼鐩戞帶鍜岃嚜鍔ㄩ噸鍚?- 鍋ュ悍妫€鏌?- 璧勬簮闄愬埗
- 璁㈤槄鍒版湡鑷姩鍋滄
- 瀹氭湡娓呯悊鏃犳晥瀹炰緥
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
    Bot瀹炰緥绠＄悊鍣?    
    璐熻矗锛?    1. 鍚姩鍜屽仠姝ot瀹炰緥
    2. 鐩戞帶杩涚▼鍋ュ悍鐘舵€?    3. 鑷姩閲嶅惎宕╂簝鐨勮繘绋?    4. 璁㈤槄鍒版湡鑷姩鍋滄
    5. 娓呯悊鏃犳晥瀹炰緥
    """
    
    def __init__(self):
        # 猸?Runtime Registry - 瀹屾暣鐨勮繍琛屾椂鐘舵€佺鐞?        self.runtime_registry: Dict[str, dict] = {}  # {instance_id: runtime_info}
        
        # 瀛樺偍杩愯涓殑杩涚▼: {instance_id: process_info}
        self.running_processes: Dict[str, dict] = {}
        
        # 杩涚▼閲嶅惎璁℃暟: {instance_id: restart_count}
        self.restart_counts: Dict[str, int] = {}
        
        # 閲嶅惎鏃堕棿绐楀彛璁板綍: {instance_id: [timestamp1, timestamp2, ...]}
        self.restart_timestamps: Dict[str, list] = {}
        
        # 鏈€澶ч噸鍚鏁帮紙鏈湴娴嬭瘯鏃剁鐢紝杩愯惀鏃跺惎鐢級
        self.max_restart_count = None  # None琛ㄧず鏃犻檺鍒?        
        # 猸?閲嶅惎闄愭祦绛栫暐锛?鍒嗛挓鍐呮渶澶氶噸鍚?娆★紙鏈湴娴嬭瘯鏃剁鐢級
        self.restart_window_seconds = 0  # 猸?鏈湴娴嬭瘯锛?琛ㄧず绂佺敤鏃堕棿绐楀彛
        self.max_restarts_in_window = None  # 猸?鏈湴娴嬭瘯锛歂one琛ㄧず鏃犻檺鍒?        
        # 鍋ュ悍妫€鏌ラ棿闅旓紙绉掞級
        self.health_check_interval = 30  # 猸?浠?0绉掔缉鐭埌30绉掞紝鏇村揩鍙戠幇闂
        
        # 璁㈤槄妫€鏌ラ棿闅旓紙绉掞級
        self.subscription_check_interval = 3600  # 姣忓皬鏃?        
        # 閲嶅惎闂撮殧锛堟湰鍦版祴璇曟椂绂佺敤锛岃繍钀ユ椂鍚敤锛?        self.restart_delay = 0  # 0琛ㄧず绔嬪嵆閲嶅惎锛屾棤寤惰繜
        
        # 猸?蹇冭烦瓒呮椂闃堝€硷紙绉掞級- 瓒呰繃姝ゆ椂闂存湭鏇存柊蹇冭烦瑙嗕负寮傚父
        self.heartbeat_timeout = 90  # 90绉掞紙3鍊嶄簬姝ｅ父蹇冭烦闂撮殧锛?        
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
        浠庡疄渚嬬洰褰曟壂鎻忓彲鎭㈠鐨勫瓙 Bot銆?
        閫傜敤浜庢暟鎹簱璁板綍涓㈠け銆佷絾 bot_instances/instances 鐩綍浠嶄繚鐣欑殑鍦烘櫙銆?        浼氬湪鏁版嵁搴撲腑琛ュ缓缂哄け鐨?BotCreation 鍜?owner 绠＄悊鍛樿褰曪紝鍐嶈繑鍥炲彲鍚姩瀵硅薄銆?        """
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
        鍚姩Bot瀹炰緥锛堝甫璧勬簮闄愬埗鍜岀洃鎺?+ 骞傜瓑鎺у埗 + .env楠岃瘉淇锛?        
        Args:
            bot_creation: Bot鍒涘缓璁板綍
        
        Returns:
            鏄惁鎴愬姛鍚姩
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
            
            # Phase 2-3: check whether startup is allowed
            if not bot_instance_registry.can_start(instance_id):
                logger.warning(f"[BotInstanceManager] BOT {instance_id} is already running or starting, skipping")
                return True
            # Phase 2-1: validate and auto-repair .env
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
                    logger.error(f"[BotInstanceManager] 鉂?BOT {instance_id} .env 楠岃瘉澶辫触涓旀棤娉曚慨澶? {env_result.errors}")
                    return False
            except Exception as e:
                logger.error(f"[BotInstanceManager] 鉂?BOT {instance_id} .env 楠岃瘉寮傚父: {e}")
                return False
            
            # 馃敟 Phase 2-3: 鏍囪涓哄惎鍔ㄤ腑
            if not bot_instance_registry.mark_starting(instance_id):
                logger.warning(f"[BotInstanceManager] 鉂?BOT {instance_id} 鏃犳硶鏍囪涓?starting锛屽彲鑳藉凡鍦ㄨ繍琛屼腑")
                return True
            
            # 鉁?鍏抽敭淇锛氬惎鍔ㄥ墠鍏堟鏌ュ苟鍋滄鍙兘瀛樺湪鐨勬棫杩涚▼
            if bot_creation.process_id:
                try:
                    import psutil
                    if psutil.pid_exists(bot_creation.process_id):
                        old_process = psutil.Process(bot_creation.process_id)
                        # 妫€鏌ユ槸鍚︽槸 Python 杩涚▼
                        if 'python' in old_process.name().lower():
                            logger.warning(f"Found old process for {instance_id} (PID: {bot_creation.process_id}), stopping it...")
                            old_process.terminate()
                            old_process.wait(timeout=5)
                            logger.info(f"Old process stopped successfully")
                except Exception as e:
                    logger.warning(f"Failed to stop old process: {e}")
            
            # 妫€鏌ユ槸鍚﹀凡缁忓湪杩愯锛堟棫閫昏緫锛屼繚鐣欎綔涓哄弻閲嶆鏌ワ級
            if instance_id in self.running_processes:
                proc_info = self.running_processes[instance_id]
                if proc_info['process'].poll() is None:
                    logger.warning(f"Bot {instance_id} is already running")
                    # 鍚屾 registry 鐘舵€?                    bot_instance_registry.mark_running(instance_id, proc_info['process'])
                    # sync runtime registry state
                    bot_instance_registry.mark_running(instance_id, proc_info['process'])
                else:
                    # 杩涚▼宸茬粨鏉燂紝娓呯悊鏃ц褰?                    del self.running_processes[instance_id]
                    # process already exited, clean stale runtime record
                    del self.running_processes[instance_id]
            # 鏋勫缓鍚姩鍛戒护
            start_script = resolved_instance_dir / "start.py"
            
            if not start_script.exists():
                logger.error(f"Start script not found: {start_script}")
                return False
            
            # 璁剧疆璧勬簮闄愬埗锛圵indows涓嬫湁闄愭敮鎸侊級
            if os.name == 'nt':
                # Windows: 浣跨敤 DETACHED_PROCESS 鎴?CREATE_NO_WINDOW
                # 鍏抽敭淇锛氬皢瀛怋ot鏃ュ織杈撳嚭鍒版枃浠讹紝渚夸簬璋冭瘯
                stdout_file = open(str(resolved_instance_dir / "bot.log"), "a", encoding="utf-8")
                stderr_file = open(str(resolved_instance_dir / "error.log"), "a", encoding="utf-8")
                
                process = subprocess.Popen(
                    [sys.executable, str(start_script)],
                    cwd=str(resolved_instance_dir),
                    stdout=stdout_file,  # 杈撳嚭鍒版棩蹇楁枃浠?                    stderr=stderr_file,  # 閿欒杈撳嚭鍒版棩蹇楁枃浠?                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
            else:
                # Linux/Mac: 浣跨敤setsid鍜岃祫婧愰檺鍒?                # 馃敟 鍏抽敭淇锛氬皢瀛怋ot鏃ュ織杈撳嚭鍒版枃浠讹紝閬垮厤PIPE闃诲
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
            
            # 馃敟 Phase 2-3: 鏍囪涓鸿繍琛屼腑
            bot_instance_registry.mark_running(instance_id, process)
            
            # 璁板綍杩涚▼淇℃伅锛堟棫閫昏緫锛屼繚鐣欏吋瀹癸級
            process_info = {
                'process': process,
                'pid': process.pid,
                'started_at': datetime.utcnow(),
                'last_check': datetime.utcnow(),
                'restart_count': self.restart_counts.get(instance_id, 0)
            }
            self.running_processes[instance_id] = process_info

            await asyncio.sleep(1.5)
            quick_exit_code = process.poll()
            if quick_exit_code is not None:
                bot_log_path = resolved_instance_dir / "bot.log"
                error_log_path = resolved_instance_dir / "error.log"

                def _read_tail(path: Path) -> str:
                    if not path.exists():
                        return ""
                    try:
                        return path.read_text(encoding="utf-8", errors="ignore")[-4000:]
                    except Exception:
                        return ""

                logger.error(
                    "[BotInstanceManager] BOT %s exited immediately with code %s\nBOT.LOG:\n%s\nERROR.LOG:\n%s",
                    instance_id,
                    quick_exit_code,
                    _read_tail(bot_log_path) or "<empty>",
                    _read_tail(error_log_path) or "<empty>",
                )
                self.running_processes.pop(instance_id, None)
                self.runtime_registry.pop(instance_id, None)
                bot_instance_registry.mark_failed(instance_id, f"quick_exit:{quick_exit_code}")
                return False
            
            # 猸?鍒濆鍖?Runtime Registry
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
                'runtime_health_score': 100,
            }
            
            logger.info(f"鉁?Runtime registry initialized for {instance_id}")
            
            # 鏇存柊鏁版嵁搴撹褰?            bot_creation.status = "running"
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
            # 馃敟 Phase 2-3: 鏍囪涓哄け璐?            bot_instance_registry.mark_failed(bot_creation.instance_id, str(e))
            bot_creation.status = "error"
            return False
    
    async def stop_bot_instance(self, instance_id: str, force: bool = False) -> bool:
        """
        鍋滄Bot瀹炰緥
        
        Args:
            instance_id: 瀹炰緥ID
            force: 鏄惁寮哄埗鍋滄
        
        Returns:
            鏄惁鎴愬姛鍋滄
        """
        from .bot_instance_registry import bot_instance_registry
        
        # 馃敟 Phase 2-3: 鏍囪涓哄仠姝腑
        bot_instance_registry.mark_stopping(instance_id)
        
        try:
            # 浠庢暟鎹簱涓幏鍙朆ot淇℃伅
            async with get_db_session() as db:
                query = select(BotCreation).where(BotCreation.instance_id == instance_id)
                result = await db.execute(query)
                bot_creation = result.scalar_one_or_none()
                
                if not bot_creation:
                    logger.error(f"Bot {instance_id} not found in database")
                    return False
                
                # 灏濊瘯浠庤繍琛屽垪琛ㄤ腑鍋滄
                if instance_id in self.running_processes:
                    proc_info = self.running_processes[instance_id]
                    process = proc_info['process']
                    
                    if force:
                        # 寮哄埗缁堟
                        process.kill()
                        logger.info(f"Force killed bot {instance_id} (PID: {process.pid})")
                    else:
                        # 浼橀泤缁堟
                        process.terminate()
                        try:
                            process.wait(timeout=10)  # 绛夊緟10绉?                            logger.info(f"Gracefully stopped bot {instance_id} (PID: {process.pid})")
                        except subprocess.TimeoutExpired:
                            process.kill()
                            logger.warning(f"Bot {instance_id} didn't stop gracefully, force killed")
                    
                    # 娓呯悊杩愯鍒楄〃
                    del self.running_processes[instance_id]
                    
                    # 猸?娓呯悊 Runtime Registry
                    if instance_id in self.runtime_registry:
                        runtime_info = self.runtime_registry[instance_id]
                        runtime_info['runtime_status'] = 'stopped'
                        runtime_info['runtime_stopped_at'] = datetime.utcnow()
                        logger.info(f"鉁?Runtime registry updated for {instance_id}: stopped")
                
                # 馃敟 Phase 2-3: 鏍囪涓哄凡鍋滄
                bot_instance_registry.mark_stopped(instance_id)
                
                # 鏇存柊鏁版嵁搴撶姸鎬?                bot_creation.status = "stopped"
                bot_creation.stopped_at = datetime.utcnow()
                await db.flush()
                
                logger.info(f"Bot {instance_id} stopped successfully")
                return True
        
        except Exception as e:
            logger.error(f"Error in stop_bot_instance: {e}", exc_info=True)
            return False
    
    async def check_health(self, instance_id: str) -> dict:
        """
        妫€鏌ot瀹炰緥鍋ュ悍鐘舵€侊紙澧炲己鐗?- 鍖呭惈蹇冭烦妫€娴嬪拰鍍靛案杩涚▼妫€娴嬶級
        
        Args:
            instance_id: 瀹炰緥ID
        
        Returns:
            鍋ュ悍鐘舵€佷俊鎭?        """
        result = {
            'instance_id': instance_id,
            'is_healthy': False,
            'status': 'unknown',
            'message': '',
            'health_score': 0,
            'is_zombie': False
        }
        
        try:
            # 浠庢暟鎹簱鑾峰彇Bot淇℃伅
            async with get_db_session() as db:
                query = select(BotCreation).where(BotCreation.instance_id == instance_id)
                result_query = await db.execute(query)
                bot_creation = result_query.scalar_one_or_none()
                
                if not bot_creation:
                    result['message'] = 'Bot not found in database'
                    return result
                
                result['status'] = bot_creation.status
                
                # Check whether the bot exists in the runtime registry
                if instance_id not in self.runtime_registry:
                    result['is_healthy'] = False
                    result['message'] = 'Not in runtime registry'
                    result['health_score'] = 0
                    return result
                
                runtime_info = self.runtime_registry[instance_id]
                now = datetime.utcnow()
                
                # Check whether the bot exists in the running process list
                if instance_id in self.running_processes:
                    proc_info = self.running_processes[instance_id]
                    process = proc_info['process']
                    
                    # Check whether the process is still alive
                    poll_result = process.poll()
                    
                    if poll_result is None:
                        # 鉁?杩涚▼姝ｅ湪杩愯
                        
                        # 猸?璁＄畻蹇冭烦瓒呮椂
                        last_heartbeat = runtime_info.get('runtime_last_heartbeat')
                        if last_heartbeat:
                            heartbeat_age = (now - last_heartbeat).total_seconds()
                            
                            if heartbeat_age > self.heartbeat_timeout:
                                # 鈿狅笍 蹇冭烦瓒呮椂 - 鍙兘鏄疨olling鍗℃
                                result['is_healthy'] = False
                                result['is_zombie'] = True
                                result['message'] = f'Heartbeat timeout ({heartbeat_age:.0f}s > {self.heartbeat_timeout}s)'
                                result['health_score'] = 20
                                runtime_info['runtime_status'] = 'zombie'
                                logger.warning(
                                    f"鈿狅笍 Bot {instance_id} is ZOMBIE: "
                                    f"heartbeat age={heartbeat_age:.0f}s, "
                                    f"PID={process.pid}"
                                )
                                
                                # 灏濊瘯鑷姩閲嶅惎鍍靛案杩涚▼
                                await self._auto_restart(instance_id, bot_creation)
                            else:
                                # 鉁?蹇冭烦姝ｅ父
                                result['is_healthy'] = True
                                result['message'] = 'Running normally'
                                result['health_score'] = 100
                                runtime_info['runtime_status'] = 'running'
                                
                                # 鏇存柊蹇冭烦鏃堕棿
                                runtime_info['runtime_last_heartbeat'] = now
                                bot_creation.last_heartbeat = now
                                await db.flush()
                        else:
                            # 棣栨妫€鏌ワ紝娌℃湁蹇冭烦璁板綍
                            result['is_healthy'] = True
                            result['message'] = 'Running (first check)'
                            result['health_score'] = 80
                            runtime_info['runtime_last_heartbeat'] = now
                    else:
                        # Process has exited
                        result['is_healthy'] = False
                        result['message'] = f'Process exited with code {poll_result}'
                        result['health_score'] = 0
                        runtime_info['runtime_status'] = 'crashed'
                        bot_creation.status = 'crashed'
                        await db.flush()
                        
                        # 灏濊瘯鑷姩閲嶅惎
                        await self._auto_restart(instance_id, bot_creation)
                else:
                    # Not present in the running process list
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
                
                # 鏇存柊 Runtime Registry 鐨勫仴搴峰害璇勫垎
                runtime_info['runtime_health_score'] = result['health_score']
                
                return result
        
        except Exception as e:
            logger.error(f"Error in check_health: {e}", exc_info=True)
            result['message'] = str(e)
            result['health_score'] = 0
            return result
    
    async def _auto_restart(self, instance_id: str, bot_creation: BotCreation):
        """
        鑷姩閲嶅惎Bot瀹炰緥锛堝甫閲嶅惎闄愭祦绛栫暐锛?        
        Args:
            instance_id: 瀹炰緥ID
            bot_creation: Bot鍒涘缓璁板綍
        """
        try:
            now = time.time()
            
            # Local test mode: disable restart rate limiting
            if self.max_restarts_in_window is None or self.restart_window_seconds == 0:
                logger.debug(f"Restart rate limiting disabled (local test mode)")
            else:
                # Runtime mode: enable restart rate limiting
                # Initialize restart window history
                if instance_id not in self.restart_timestamps:
                    self.restart_timestamps[instance_id] = []
                
                # 娓呯悊杩囨湡鐨勯噸鍚褰曪紙瓒呭嚭鏃堕棿绐楀彛鐨勶級
                window_start = now - self.restart_window_seconds
                self.restart_timestamps[instance_id] = [
                    ts for ts in self.restart_timestamps[instance_id]
                    if ts > window_start
                ]
                
                # Check restart rate limit
                recent_restarts = len(self.restart_timestamps[instance_id])
                
                if recent_restarts >= self.max_restarts_in_window:
                    logger.error(
                        f"馃毇 Restart rate limit exceeded for {instance_id}: "
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
            
            # 鏈湴娴嬭瘯妯″紡锛氭棤闄愬埗閲嶅惎
                self.restart_timestamps.setdefault(instance_id, [])
            if self.max_restart_count is None:
                restart_count = self.restart_counts.get(instance_id, 0)
                self.restart_counts[instance_id] = restart_count + 1
                
                # 猸?璁板綍閲嶅惎鏃堕棿鎴?                self.restart_timestamps[instance_id].append(now)
                
                logger.info(
                    f"Auto restarting bot {instance_id} "
                    f"(attempt {restart_count + 1}, unlimited mode, "
                    f"{len(self.restart_timestamps[instance_id])} restarts in window)"
                )
                
                # 鏈湴娴嬭瘯锛氭棤寤惰繜绔嬪嵆閲嶅惎
                if self.restart_delay > 0:
                    await asyncio.sleep(self.restart_delay)
                
                # 閲嶆柊鍚姩
                success = await self.start_bot_instance(bot_creation)
                
                if success:
                    logger.info(f"鉁?Bot {instance_id} restarted successfully")
                else:
                    logger.error(f"鉂?Failed to restart bot {instance_id}")
                return
            
            # 杩愯惀妯″紡锛氭鏌ユ€婚噸鍚鏁?            restart_count = self.restart_counts.get(instance_id, 0)
            
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
            self.restart_timestamps.setdefault(instance_id, [])
            
            # 澧炲姞閲嶅惎璁℃暟
            self.restart_counts[instance_id] = restart_count + 1
            
            # 猸?璁板綍閲嶅惎鏃堕棿鎴?            self.restart_timestamps[instance_id].append(now)
            
            logger.info(
                f"Auto restarting bot {instance_id} "
                f"(attempt {restart_count + 1}/{self.max_restart_count}, "
                f"{len(self.restart_timestamps[instance_id])} restarts in window)"
            )
            
            # Wait before restarting
            if self.restart_delay > 0:
                await asyncio.sleep(self.restart_delay)
            
            # 閲嶆柊鍚姩
            success = await self.start_bot_instance(bot_creation)
            
            if success:
                logger.info(f"鉁?Bot {instance_id} restarted successfully")
            else:
                logger.error(f"鉂?Failed to restart bot {instance_id}")
                
        except Exception as e:
            logger.error(f"Error auto restarting bot {instance_id}: {e}", exc_info=True)
    
    async def check_all_bots_health(self) -> dict:
        """
        妫€鏌ユ墍鏈塀ot瀹炰緥鐨勫仴搴风姸鎬?        
        Returns:
            鍋ュ悍妫€鏌ョ粨鏋?        """
        results = {
            'total': 0,
            'healthy': 0,
            'unhealthy': 0,
            'details': []
        }
        
        try:
            # 鑾峰彇鎵€鏈夋爣璁颁负running鐨凚ot
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
            # 杩斿洖榛樿缁撴灉鑰屼笉鏄疦one
            return results
        
        # 濡傛灉鎰忓鍒拌揪杩欓噷锛屼篃杩斿洖榛樿缁撴灉
        return results
    
    async def stop_expired_subscriptions(self) -> dict:
        """
        鍋滄璁㈤槄鍒版湡鐨凚ot瀹炰緥
        
        Returns:
            鍋滄缁撴灉缁熻
        """
        results = {
            'checked': 0,
            'stopped': 0,
            'errors': 0,
            'details': []
        }
        
        try:
            # 鑾峰彇鎵€鏈夋椿璺冪殑璁㈤槄
            async with get_db_session() as db:
                now = datetime.utcnow()
                
                # 鏌ユ壘宸茶繃鏈熺殑娲昏穬璁㈤槄
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
                    
                    # 妫€鏌ユ槸鍚︿负绠＄悊鍛橈紙绠＄悊鍛樼殑鏈哄櫒浜轰笉鍙楄闃呴檺鍒讹級
                    from ..utils.internal_member_checker import is_admin
                    if await is_admin(telegram_id):
                        logger.info(f"Skipping expired subscription check for admin: {telegram_id}")
                        # 鏇存柊璁㈤槄鐘舵€佷负expired锛屼絾涓嶅仠姝㈡満鍣ㄤ汉
                        subscription.status = "expired"
                        await db.flush()
                        continue
                    
                    # 鏇存柊璁㈤槄鐘舵€?                    subscription.status = "expired"
                    
                    # 鏌ユ壘璇ョ敤鎴风殑鎵€鏈塀ot
                    bots_query = select(BotCreation).where(
                        and_(
                            BotCreation.telegram_id == telegram_id,
                            BotCreation.status.in_(["running", "creating"])
                        )
                    )
                    bots_result = await db.execute(bots_query)
                    user_bots = bots_result.scalars().all()
                    
                    # 鍋滄姣忎釜Bot
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
        娓呯悊鏃犳晥鐨凚ot瀹炰緥
        
        娓呯悊鏉′欢锛?        1. 鐘舵€佷负error/failed瓒呰繃7澶?        2. 杩涚▼涓嶅瓨鍦ㄤ絾鐘舵€佷粛涓簉unning
        3. 鐩綍涓嶅瓨鍦?        
        Returns:
            娓呯悊缁撴灉缁熻
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
                
                # 鏌ユ壘闇€瑕佹竻鐞嗙殑Bot
                query = select(BotCreation).where(
                    or_(
                        # Status is error/failed for more than 7 days
                        and_(
                            BotCreation.status.in_(["error", "failed"]),
                            BotCreation.updated_at < seven_days_ago
                        ),
                        # Status is stopped for more than 30 days
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
                        
                        # 鍒犻櫎鐩綍
                        if instance_dir.exists():
                            import shutil
                            shutil.rmtree(instance_dir, ignore_errors=True)
                            logger.info(f"Deleted directory for bot {instance_id}")
                        
                        # 浠庤繍琛屽垪琛ㄤ腑绉婚櫎
                        if instance_id in self.running_processes:
                            del self.running_processes[instance_id]
                        
                        # 浠庢暟鎹簱鍒犻櫎璁板綍
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
        鍔犺浇骞跺惎鍔ㄦ暟鎹簱涓墍鏈夋爣璁颁负running鐨凚ot瀹炰緥
        
        Returns:
            鍔犺浇缁撴灉缁熻
        """
        results = {
            'total': 0,
            'started': 0,
            'failed': 0,
            'details': []
        }
        
        try:
            # 鑾峰彇鎵€鏈夋爣璁颁负running鐨凚ot
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
                        
                        # 妫€鏌ユ槸鍚﹀凡缁忓湪杩愯
                        if instance_id in self.running_processes:
                            proc_info = self.running_processes[instance_id]
                            if proc_info['process'].poll() is None:
                                logger.info(f"Bot {instance_id} already running, skipping")
                                results['started'] += 1
                                continue
                        
                        # 鍚姩Bot瀹炰緥
                        success = await self.start_bot_instance(bot)
                        
                        if success:
                            results['started'] += 1
                            logger.info(f"鉁?Bot {instance_id} started successfully")
                        else:
                            results['failed'] += 1
                            logger.error(f"鉂?Failed to start bot {instance_id}")
                        
                        # 绛夊緟涓€涓嬶紝閬垮厤鍚屾椂鍚姩澶杩涚▼
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
        鍚姩鍛ㄦ湡鎬т换鍔?        
        Args:
            application: Telegram搴旂敤瀹炰緥
        """
        from apscheduler.triggers.interval import IntervalTrigger
        
        # 鍋ュ悍妫€鏌ヤ换鍔★紙姣忓垎閽燂級
        health_check_job = application.job_queue.run_repeating(
            lambda context: asyncio.create_task(self._periodic_health_check()),
            interval=self.health_check_interval,
            first=60,
            name="bot_health_check"
        )
        logger.info(f"Bot health check task started (every {self.health_check_interval}s)")
        
        # 璁㈤槄妫€鏌ヤ换鍔★紙姣忓皬鏃讹級
        subscription_check_job = application.job_queue.run_repeating(
            lambda context: asyncio.create_task(self._periodic_subscription_check()),
            interval=self.subscription_check_interval,
            first=300,  # 5鍒嗛挓鍚庨娆℃墽琛?            name="subscription_check"
        )
        logger.info(f"Subscription check task started (every {self.subscription_check_interval}s)")
        
        # 娓呯悊浠诲姟锛堟瘡澶╁噷鏅?鐐癸級
        from apscheduler.triggers.cron import CronTrigger
        cleanup_job = application.job_queue.run_daily(
            lambda context: asyncio.create_task(self._periodic_cleanup()),
            time=datetime.strptime("03:00", "%H:%M").time(),
            name="cleanup_invalid_instances"
        )
        logger.info("Daily cleanup task started (at 03:00)")
        
        # 馃啎 鏁版嵁婕傜Щ妫€娴嬩换鍔★紙姣忓ぉ鍑屾櫒4鐐规墽琛岋級
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
            'drift_check': drift_check_job  # 馃啎
        }
    
    async def _periodic_health_check(self):
        """Periodic health check."""
        try:
            results = await self.check_all_bots_health()
            
            # Validate returned health-check payload
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
        """Periodic subscription check."""
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
        """Periodic cleanup."""
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
        """Periodic data-drift check."""
        try:
            from .data_drift_prevention import data_drift_prevention_system
            
            logger.info("馃攳 Starting daily drift check...")
            results = await data_drift_prevention_system.run_full_check()
            
            if results['total_issues'] > 0:
                logger.warning(
                    f"馃搳 Drift check completed: "
                    f"{results['total_issues']} issues found, "
                    f"{results['fixed_issues']} issues fixed"
                )
                
                # Alert if some issues remain unfixed
                if results['total_issues'] > results['fixed_issues']:
                    logger.error(
                        f"鈿狅笍 Drift check warning: "
                        f"{results['total_issues'] - results['fixed_issues']} issues NOT fixed!"
                    )
            else:
                logger.info("鉁?Drift check completed: No issues found")
                
        except Exception as e:
            logger.error(f"Error in periodic drift check: {e}", exc_info=True)
    
    def get_running_count(self) -> int:
        """鑾峰彇杩愯涓殑Bot鏁伴噺"""
        count = 0
        for instance_id, proc_info in self.running_processes.items():
            if proc_info['process'].poll() is None:
                count += 1
        return count
    
    def get_all_running_instances(self) -> List[str]:
        """鑾峰彇鎵€鏈夎繍琛屼腑鐨勫疄渚婭D"""
        running = []
        for instance_id, proc_info in self.running_processes.items():
            if proc_info['process'].poll() is None:
                running.append(instance_id)
        return running
    
    def get_runtime_status(self) -> dict:
        """
        猸?鑾峰彇鎵€鏈塀ot鐨勮繍琛屾椂鐘舵€侊紙鐢ㄤ簬鐩戞帶闈㈡澘锛?        
        Returns:
            瀹屾暣鐨勮繍琛屾椂鐘舵€佷俊鎭?        """
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
            
            # 璁＄畻杩愯鏃堕棿
            if runtime_info.get('runtime_started_at'):
                uptime = (now - runtime_info['runtime_started_at']).total_seconds()
                bot_status['uptime_seconds'] = int(uptime)
            
            # 璁＄畻蹇冭烦骞撮緞
            if runtime_info.get('runtime_last_heartbeat'):
                heartbeat_age = (now - runtime_info['runtime_last_heartbeat']).total_seconds()
                bot_status['heartbeat_age_seconds'] = int(heartbeat_age)
            
            # 缁熻鍚勭鐘舵€佺殑Bot鏁伴噺
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


# Global singleton instance manager
bot_instance_manager = BotInstanceManager()


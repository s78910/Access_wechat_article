from __future__ import annotations

import queue
import socket
import time
from datetime import datetime
from multiprocessing import Queue
from typing import Any

from src.core.config import AppRuntimeConfig, LOG_DIR, PROJECT_ROOT
from src.core.events import RuntimeLog
from src.core.file_logger import SessionFileLogger
from src.core.process_manager import ProcessManager
from src.modules.proxy.mitm_controller import run_mitm_worker
from src.modules.proxy.proxy_manager import ProxyManager
from src.modules.proxy.system_proxy import ProxySnapshot
from src.modules.window.wechat_detector import DEFAULT_WECHAT_HOME_SNAPSHOT
from src.modules.window.wechat_detector import WeChatHomeSnapshot
from src.modules.window.wechat_detector import detect_wechat_home_window
from src.workers.article_capture import CURRENT_MITM_TARGET_PROBE_PATH
from src.workers.article_capture import run_article_capture_worker


TRAFFIC_RATE_WINDOW_SECONDS = 5.0
TRAFFIC_HISTORY_SECONDS = 60.0
TRAFFIC_HISTORY_LIMIT = 40
MITM_READY_TIMEOUT_SECONDS = 5.0
MITM_READY_POLL_INTERVAL_SECONDS = 0.1
LONG_WAIT_TIMEOUT_THRESHOLD_SECONDS = 30.0
LONG_WAIT_TIMEOUT_FALLBACK_SECONDS = 10.0
ACCOUNT_NAME_PLACEHOLDER_MARKERS = (
    "等待识别",
    "未检测到",
    "检测到微信窗口",
    "已检测到公众号窗口",
    "无法读取主页内容",
    "主页窗口读取失败",
)


def wait_for_tcp_listener(
    host: str,
    port: int,
    *,
    timeout_seconds: float = MITM_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = MITM_READY_POLL_INTERVAL_SECONDS,
    connector=None,
) -> bool:
    """轮询 TCP 端口是否已可连接，用于确认 MITM 监听真正就绪后再点击文章。"""
    connect = connector or socket.create_connection
    deadline = time.monotonic() + max(0.01, float(timeout_seconds or 0.01))
    interval = max(0.0, float(poll_interval_seconds or 0.0))
    address = (str(host or "127.0.0.1"), int(port))

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False

        connection = None
        try:
            connection = connect(address, timeout=min(0.5, max(0.01, remaining)))
            return True
        except OSError:
            sleep_seconds = min(interval, max(0.0, deadline - time.monotonic()))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def resolve_wait_timeout_seconds(value: Any, *, default_seconds: float = MITM_READY_TIMEOUT_SECONDS) -> float:
    """统一收敛阻塞等待时间；配置超过 30 秒时降为 10 秒，避免界面长时间无反馈。"""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = float(default_seconds)

    if seconds <= 0:
        seconds = float(default_seconds)
    if seconds > LONG_WAIT_TIMEOUT_THRESHOLD_SECONDS:
        return LONG_WAIT_TIMEOUT_FALLBACK_SECONDS
    return seconds


class TaskManager:
    """任务总控：串起配置、系统代理、mitm worker、状态和日志。"""

    def __init__(
        self,
        config: AppRuntimeConfig | None = None,
        proxy_manager: ProxyManager | None = None,
        process_manager: ProcessManager | None = None,
        event_queue: Queue | None = None,
        capture_event_queue: Queue | None = None,
        file_logger: SessionFileLogger | None = None,
        home_detector=None,
    ) -> None:
        self.config = config or AppRuntimeConfig()
        self.proxy_manager = proxy_manager or ProxyManager(self.config.proxy)
        self.process_manager = process_manager or ProcessManager()
        self.event_queue = event_queue or Queue()
        self.capture_event_queue = capture_event_queue or Queue()
        self._started_at = datetime.now()
        self.file_logger = file_logger or SessionFileLogger(started_at=self._started_at)
        self.home_detector = home_detector or detect_wechat_home_window
        self._home_snapshot = DEFAULT_WECHAT_HOME_SNAPSHOT
        self._run_options = normalize_task_run_options(None)
        self._status = "idle"
        self._logs: list[dict] = []
        self._traffic_events: list[dict] = []
        self._traffic_history: list[dict] = []
        self._restore_mitm_after_collection = False
        self.refresh_home_snapshot()
        self._log("INFO", "应用后端已启动，等待用户开始采集任务")

    def start_task(self, options: dict | None = None) -> dict:
        self._drain_worker_events()
        if self._status == "running":
            return {
                "ok": False,
                "status": self._status,
                "message": "采集任务已经在运行",
            }

        self._run_options = normalize_task_run_options(options)
        self._log("INFO", "开始检测微信 PC 端公众号主页窗口")
        self.refresh_home_snapshot(activate=True)
        if self._home_snapshot.found:
            self._log("SUCCESS", f"已获取公众号主页信息：{self._home_snapshot.account_name}")
        elif self._can_try_capture_with_home_snapshot(self._home_snapshot):
            # 已确认存在微信窗口但主页文本暂不可读时，仍交给单篇抓取流程继续后台定位第一篇。
            self._log("WARN", self._home_snapshot.message or self._home_snapshot.description)
        else:
            self._log("WARN", self._home_snapshot.message or self._home_snapshot.description)
            payload = self.get_status(refresh_home=False)
            payload["ok"] = False
            payload["message"] = self._home_snapshot.message or self._home_snapshot.description
            return payload

        self._log("INFO", "开始启动采集任务")
        return self._start_article_capture_task()

    def stop_task(self) -> dict:
        return self.stop_collection_task()

    @staticmethod
    def _can_try_capture_with_home_snapshot(snapshot: WeChatHomeSnapshot) -> bool:
        return snapshot.status in {"content_unreadable", "content_only"}

    @staticmethod
    def _home_account_name_for_worker(snapshot: WeChatHomeSnapshot) -> str:
        """只把真实主页公众号名传给采集 worker，状态提示不再混入本地归档或 SQLite。"""
        if not snapshot.found:
            return ""
        account_name = str(snapshot.account_name or "").strip()
        if not account_name:
            return ""
        if any(marker in account_name for marker in ACCOUNT_NAME_PLACEHOLDER_MARKERS):
            return ""
        account_confidence = str(getattr(snapshot, "account_confidence", "") or "").strip().lower()
        account_source = str(getattr(snapshot, "account_source", "") or "").strip().lower()
        if account_confidence and account_confidence not in {"high", "medium"}:
            return ""
        if account_source == "content_list":
            return ""
        return account_name

    def _start_article_capture_task(self) -> dict:
        if self.process_manager.is_running("article_capture"):
            return {
                "ok": False,
                "status": self._status,
                "message": "采集任务已经在运行",
            }

        mitm_ready = self._ensure_mitm_ready_for_collection()
        if not mitm_ready["ok"]:
            return mitm_ready

        try:
            worker_config = self.config.proxy.to_worker_payload()
            worker_config.update(
                {
                    "proxy_host": self.config.proxy.host,
                    "proxy_port": self.config.proxy.port,
                    "db_path": str(self.config.storage.db_path),
                    "run_options": self._run_options,
                    "output_root": str(LOG_DIR / "article_capture"),
                    "storage_root": str(PROJECT_ROOT / "storages"),
                    "mitm_target_probe_path": str(CURRENT_MITM_TARGET_PROBE_PATH),
                }
            )
            account_name = self._home_account_name_for_worker(self._home_snapshot)
            if account_name:
                worker_config["account_name"] = account_name
            self.process_manager.start_worker(
                "article_capture",
                target=run_article_capture_worker,
                args=(self.event_queue, worker_config, self.capture_event_queue),
            )
            self._log("INFO", f"文章抓取 worker 已启动，目标 {self._run_options['recordLimit']} 篇")
        except Exception as exc:
            self._status = "error"
            self._log("ERROR", f"文章抓取 worker 启动失败：{exc}")
            self._restore_prepared_mitm_after_collection()
            return {
                "ok": False,
                "status": self._status,
                "message": str(exc),
            }

        self._log("INFO", "文章抓取任务不改动系统代理，沿用程序启动时的代理配置")

        self._status = "running"
        return self.get_status(refresh_home=False)

    def stop_collection_task(self) -> dict:
        self._drain_worker_events()
        article_stopped = False
        if self.process_manager.is_running("article_capture"):
            article_stopped = self.process_manager.stop_worker("article_capture")
        self._status = "stopped"
        if article_stopped:
            self._log("INFO", "文章抓取任务已停止，系统代理保持程序启动时的配置")
        else:
            self._log("INFO", "采集任务未运行，系统代理保持程序启动时的配置")
        return self.get_status(refresh_home=False)

    def start_mitm_proxy(self) -> dict:
        """启动 MITM 监听进程，不自动修改系统代理。"""
        self._drain_worker_events()
        if self.process_manager.is_running("mitm"):
            self._restore_mitm_after_collection = False
            payload = self.get_status(refresh_home=False)
            payload["message"] = "MITM 代理已经在运行"
            return payload

        external_listener = self._detect_external_mitm_listener()
        if external_listener:
            return external_listener

        try:
            self._start_mitm_worker(preserve_status=False)
            self._restore_mitm_after_collection = False
            if not self._wait_for_mitm_listener():
                message = f"MITM worker 已启动但端口未进入监听：{self.config.proxy.host}:{self.config.proxy.port}"
                self._log("ERROR", message)
                self.process_manager.stop_worker("mitm")
                return {
                    "ok": False,
                    "status": self._status,
                    "message": message,
                }
            self._log("INFO", f"MITM worker 已启动，监听 {self.config.proxy.host}:{self.config.proxy.port}")
            return self.get_status(refresh_home=False)
        except Exception as exc:
            self._status = "error"
            self._log("ERROR", f"MITM 代理启动失败：{exc}")
            self.process_manager.stop_all()
            return {
                "ok": False,
                "status": self._status,
                "message": str(exc),
            }

    def stop_mitm_proxy(self) -> dict:
        """停止 MITM 监听进程；系统代理只由启动配置或用户手动开关控制。"""
        self._drain_worker_events()
        self._restore_mitm_after_collection = False
        stopped = self.process_manager.stop_worker("mitm")
        self._status = "stopped"
        if stopped:
            self._log("INFO", "MITM 代理已停止，系统代理保持当前配置")
        else:
            self._log("INFO", "MITM 代理未运行，系统代理保持当前配置")
        return self.get_status(refresh_home=False)

    def enable_system_proxy(self) -> dict:
        """开启系统代理接管流量，要求 MITM 已在监听。"""
        self._drain_worker_events()
        if not self.process_manager.is_running("mitm"):
            self._log("WARN", "系统代理未开启：请先开启 MITM 代理")
            return {
                "ok": False,
                "status": self._status,
                "message": "请先开启 MITM 代理",
            }

        try:
            self.proxy_manager.start()
            self._log("INFO", f"系统代理已开启：{self.config.proxy.host}:{self.config.proxy.port}")
            return self.get_status(refresh_home=False)
        except Exception as exc:
            self._log("ERROR", f"系统代理开启失败：{exc}")
            return {
                "ok": False,
                "status": self._status,
                "message": str(exc),
            }

    def disable_system_proxy(self) -> dict:
        """恢复系统代理到启动前状态。"""
        self._drain_worker_events()
        self.proxy_manager.stop()
        self._log("INFO", "系统代理已恢复")
        return self.get_status(refresh_home=False)

    def shutdown(self) -> None:
        self._restore_mitm_after_collection = False
        try:
            if self.process_manager.is_running("article_capture"):
                self.process_manager.stop_worker("article_capture")
                self._log("INFO", "后端关闭时已停止文章采集 worker")
        except Exception as exc:
            self._log("ERROR", f"后端关闭时停止文章采集 worker 失败：{exc}")

        try:
            # 先恢复系统代理，避免 MITM 端口关闭后系统代理仍短暂指向本机端口。
            self.proxy_manager.stop()
            self._log("INFO", "后端关闭时已恢复系统代理")
        except Exception as exc:
            self._log("ERROR", f"后端关闭时恢复系统代理失败：{exc}")

        try:
            stopped = self.process_manager.stop_worker("mitm")
            if stopped:
                self._log("INFO", "后端关闭时已停止 MITM 代理")
            else:
                self._log("INFO", "后端关闭时 MITM 代理未运行")
        except Exception as exc:
            self._log("ERROR", f"后端关闭时停止 MITM 代理失败：{exc}")

        self._status = "stopped"

    def update_config(self, config: AppRuntimeConfig, config_path: str | None = None) -> dict:
        """保存配置后同步当前运行对象，后续启动 worker 会使用新配置。"""
        self.config = config
        self.proxy_manager.config = config.proxy
        if config_path:
            self._log("INFO", f"运行配置已保存：{config_path}")
        else:
            self._log("INFO", "运行配置已保存")
        return self.get_status(refresh_home=False)

    def get_status(self, refresh_home: bool = True) -> dict:
        self._drain_worker_events()
        if refresh_home:
            # 前端会轮询这个接口，先刷新主页快照才能把窗口识别结果实时填到页面。
            self.refresh_home_snapshot()

        workers = self.process_manager.running_workers()
        if self._status == "running" and "article_capture" not in workers:
            time.sleep(0.2)
            self._drain_worker_events()
            workers = self.process_manager.running_workers()
            if self._status == "running" and "article_capture" not in workers:
                self._status = "error"
                self._log("ERROR", "文章抓取 worker 已退出，MITM 监听保持当前状态；请检查采集日志后重新开始")
                self._log("INFO", "检测到采集 worker 异常退出，系统代理和 MITM 保持程序启动时的配置")
        elif self._status == "stopped":
            self._restore_prepared_mitm_after_collection()
            workers = self.process_manager.running_workers()

        configured_proxy_server = f"{self.config.proxy.host}:{self.config.proxy.port}"
        system_proxy_snapshot = self._get_system_proxy_snapshot(configured_proxy_server)

        return {
            "ok": self._status not in {"error"},
            "status": self._status,
            "proxy": {
                "host": self.config.proxy.host,
                "port": self.config.proxy.port,
                "enabled": bool(getattr(self.proxy_manager, "is_enabled", False)),
                "mitmEnabled": "mitm" in workers or "article_capture" in workers,
                "systemProxyEnabled": system_proxy_snapshot.enabled,
                "systemProxyActive": system_proxy_snapshot.enabled,
                "systemProxyServer": system_proxy_snapshot.server,
                "systemProxyReadable": system_proxy_snapshot.readable,
                "systemProxyReadError": system_proxy_snapshot.read_error,
                "configuredProxyServer": configured_proxy_server,
            },
            "config": {
                "autoSaveContent": self.config.app.auto_save_content,
                "autoCleanTempFiles": self.config.app.auto_clean_temp_files,
                "autoStartProxy": self.config.app.auto_start_proxy,
                "enableSystemProxy": self.config.proxy.enable_system_proxy,
                "startupDelaySeconds": self.config.proxy.startup_delay_seconds,
                "verificationUrl": self.config.proxy.verification_url,
            },
            "workers": workers,
            "home": self._home_snapshot.to_dict(),
            "runOptions": self._run_options,
            "dbPath": str(self.config.storage.db_path),
            "logPath": str(self.file_logger.path),
            "appStartedAt": self._started_at.isoformat(timespec="seconds"),
            "uptimeSeconds": max(0, int((datetime.now() - self._started_at).total_seconds())),
            "traffic": self._build_traffic_status(workers),
        }

    def _get_system_proxy_snapshot(self, configured_proxy_server: str) -> ProxySnapshot:
        """读取真实系统代理状态；读取失败时回退到程序内部状态，避免页面不可用。"""
        try:
            if hasattr(self.proxy_manager, "current_snapshot"):
                return self.proxy_manager.current_snapshot()
        except Exception as exc:
            return ProxySnapshot(enabled=False, server="", readable=False, read_error=str(exc))

        return ProxySnapshot(
            enabled=False,
            server="",
            readable=False,
            read_error="system proxy snapshot reader unavailable",
        )

    def _start_mitm_worker(self, *, preserve_status: bool) -> None:
        worker_config = self.config.proxy.to_worker_payload()
        worker_config["db_path"] = str(self.config.storage.db_path)
        worker_config["auto_save_content"] = self.config.app.auto_save_content
        worker_config["run_options"] = self._run_options
        worker_config["target_probe_path"] = str(CURRENT_MITM_TARGET_PROBE_PATH)
        self.process_manager.start_worker(
            "mitm",
            target=run_mitm_worker,
            args=(self.event_queue, worker_config, self.capture_event_queue),
        )
        # 代理监听只是采集前置环境，内部恢复时不能覆盖采集任务的最终状态。
        if not preserve_status and self._status != "running":
            self._status = "idle"

    def _ensure_mitm_ready_for_collection(self) -> dict:
        if self.process_manager.is_running("mitm"):
            if not self._wait_for_mitm_listener():
                message = f"MITM 进程存在但端口未就绪：{self.config.proxy.host}:{self.config.proxy.port}"
                self._log("ERROR", message)
                return {
                    "ok": False,
                    "status": self._status,
                    "message": message,
                }
            return {"ok": True, "started": False}

        if not self.config.app.auto_start_proxy:
            message = "MITM 代理未运行，请先在系统配置中开启代理监听"
            self._log("WARN", message)
            return {
                "ok": False,
                "status": self._status,
                "message": message,
            }

        external_listener = self._detect_external_mitm_listener()
        if external_listener:
            return external_listener

        try:
            self._start_mitm_worker(preserve_status=True)
            if not self._wait_for_mitm_listener():
                message = f"采集前启动 MITM 后端口未进入监听：{self.config.proxy.host}:{self.config.proxy.port}"
                self._log("ERROR", message)
                self.process_manager.stop_worker("mitm")
                return {
                    "ok": False,
                    "status": self._status,
                    "message": message,
                }
            self._log("INFO", "采集前检测到 MITM 未运行，已按启动配置恢复 MITM 监听且端口就绪")
            return {"ok": True, "started": True}
        except Exception as exc:
            self._status = "error"
            message = f"采集前启动 MITM 代理失败：{exc}"
            self._log("ERROR", message)
            return {
                "ok": False,
                "status": self._status,
                "message": message,
            }

    def _restore_prepared_mitm_after_collection(self) -> bool:
        if not self._restore_mitm_after_collection:
            return False
        if self.process_manager.is_running("article_capture"):
            return False
        if self.process_manager.is_running("mitm"):
            self._restore_mitm_after_collection = False
            return False

        try:
            self._start_mitm_worker(preserve_status=True)
        except Exception as exc:
            self._log("ERROR", f"采集结束后恢复预备 MITM 代理失败：{exc}")
            return False

        self._restore_mitm_after_collection = False
        if self._wait_for_mitm_listener():
            self._log("INFO", f"采集结束后已恢复预备 MITM 代理，监听 {self.config.proxy.host}:{self.config.proxy.port}")
        else:
            self._log("ERROR", f"采集结束后恢复预备 MITM 代理失败：端口未就绪 {self.config.proxy.host}:{self.config.proxy.port}")
            return False
        return True

    def _wait_for_mitm_listener(self) -> bool:
        configured_timeout = float(self.config.proxy.startup_delay_seconds or 0)
        timeout_seconds = configured_timeout if configured_timeout > 0 else MITM_READY_TIMEOUT_SECONDS
        return wait_for_tcp_listener(
            self.config.proxy.host,
            self.config.proxy.port,
            timeout_seconds=max(1.0, resolve_wait_timeout_seconds(timeout_seconds)),
            poll_interval_seconds=MITM_READY_POLL_INTERVAL_SECONDS,
        )

    def _detect_external_mitm_listener(self) -> dict | None:
        """端口已被非当前 TaskManager 管理的 MITM 占用时直接失败，避免任务队列和捕获队列串台。"""
        if not wait_for_tcp_listener(
            self.config.proxy.host,
            self.config.proxy.port,
            timeout_seconds=0.2,
            poll_interval_seconds=0,
        ):
            return None

        message = (
            f"MITM 端口已被当前后端之外的进程占用："
            f"{self.config.proxy.host}:{self.config.proxy.port}。"
            "请先停止旧的 dev_server.py / mitmproxy 进程后再启动，"
            "否则前端任务无法收到该 MITM 的捕获事件。"
        )
        self._status = "error"
        self._log("ERROR", message)
        return {
            "ok": False,
            "status": self._status,
            "message": message,
        }

    def refresh_home_snapshot(self, *, activate: bool = False) -> WeChatHomeSnapshot:
        next_snapshot = self._detect_home_snapshot(activate=activate)
        self._home_snapshot = self._merge_home_snapshot(self._home_snapshot, next_snapshot)
        return self._home_snapshot

    def _merge_home_snapshot(self, previous: WeChatHomeSnapshot, current: WeChatHomeSnapshot) -> WeChatHomeSnapshot:
        """主页滚动后只保留可见名称时，沿用上一轮完整资料，避免文章列表误覆盖。"""
        if not (current.found and current.status == "partial"):
            return current

        if not (previous.found and previous.status == "ready"):
            return current

        if previous.account_name == current.account_name:
            return WeChatHomeSnapshot(
                status="ready",
                status_label=previous.status_label,
                account_name=current.account_name,
                description=previous.description,
                original_count=previous.original_count,
                friend_follow_count=previous.friend_follow_count,
                found=True,
                message=current.message or previous.message,
                account_confidence=getattr(current, "account_confidence", "high"),
                account_source=getattr(current, "account_source", "profile_header"),
                visible_tabs=getattr(current, "visible_tabs", ()),
            )

        if self._looks_like_swapped_home_profile(previous, current):
            return WeChatHomeSnapshot(
                status="ready",
                status_label=previous.status_label,
                account_name=current.account_name,
                description=previous.account_name,
                original_count=previous.original_count,
                friend_follow_count=previous.friend_follow_count,
                found=True,
                message=current.message or previous.message,
                account_confidence=getattr(current, "account_confidence", "high"),
                account_source=getattr(current, "account_source", "profile_header"),
                visible_tabs=getattr(current, "visible_tabs", ()),
            )

        return previous

    def _looks_like_swapped_home_profile(
        self,
        previous: WeChatHomeSnapshot,
        current: WeChatHomeSnapshot,
    ) -> bool:
        """只有上一轮快照明显名称/简介互换时，才用当前局部名称执行纠偏。"""
        if previous.description != current.account_name:
            return False

        previous_name = str(previous.account_name or "").strip()
        previous_description = str(previous.description or "").strip()
        if not previous_name or not previous_description:
            return False

        # 真正的公众号名称通常更短，不会带完整句子结束符；长句更像简介。
        if len(previous_name) <= len(previous_description):
            return False
        if not any(punct in previous_name for punct in "。！？!?，,、；;：:"):
            return False
        if any(punct in previous_description for punct in "。！？!?"):
            return False

        return True

    def _detect_home_snapshot(self, *, activate: bool = False) -> WeChatHomeSnapshot:
        try:
            snapshot = self.home_detector(activate=activate)
        except TypeError as exc:
            if "activate" not in str(exc):
                raise
            # 兼容测试或旧调用方注入的无参检测函数。
            snapshot = self.home_detector()
        except Exception as exc:
            return WeChatHomeSnapshot(
                status="failed",
                status_label="采集异常",
                account_name="主页窗口读取失败",
                description=f"读取桌面窗口时发生异常：{exc}",
                original_count="未识别到",
                friend_follow_count="未识别到",
                found=False,
                message=str(exc),
            )

        if isinstance(snapshot, WeChatHomeSnapshot):
            return snapshot

        if isinstance(snapshot, dict):
            return WeChatHomeSnapshot(
                status=str(snapshot.get("status", "not_found")),
                status_label=str(snapshot.get("statusLabel", snapshot.get("status_label", "未检测到主页窗口"))),
                account_name=str(snapshot.get("accountName", snapshot.get("account_name", "未检测到微信 PC 公众号主页"))),
                description=str(snapshot.get("description", "未识别到主页简介")),
                original_count=str(snapshot.get("originalCount", snapshot.get("original_count", "未识别到"))),
                friend_follow_count=str(snapshot.get("friendFollowCount", snapshot.get("friend_follow_count", "未识别到"))),
                found=bool(snapshot.get("found", False)),
                message=str(snapshot.get("message", "")),
                account_confidence=str(snapshot.get("accountConfidence", snapshot.get("account_confidence", ""))),
                account_source=str(snapshot.get("accountSource", snapshot.get("account_source", ""))),
                visible_tabs=tuple(snapshot.get("visibleTabs", snapshot.get("visible_tabs", ())) or ()),
            )

        return DEFAULT_WECHAT_HOME_SNAPSHOT

    def get_logs(self, limit: int = 100) -> list[dict]:
        self._drain_worker_events()
        if limit <= 0:
            return []
        return self._logs[-limit:]

    def log_runtime_error(self, message: str, source: str = "runtime") -> None:
        """记录 pywebview 等运行期异常，供页面运行日志和本地日志文件同步展示。"""
        self._log("ERROR", str(message or "运行期异常"), source=source)

    def _log(self, level: str, message: str, source: str = "task") -> None:
        self._append_log(RuntimeLog(level=level, message=message, source=source).to_dict())

    def _append_log(self, event: dict) -> None:
        self._logs.append(event)
        try:
            self.file_logger.write(event)
        except Exception:
            return

    def _drain_worker_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
            if self._is_traffic_event(event):
                self._record_traffic_event(event)
            elif self._is_collection_status_event(event):
                self._record_collection_status_event(event)
            else:
                self._append_log(self._normalize_event(event))

    def _is_traffic_event(self, event: Any) -> bool:
        return isinstance(event, dict) and event.get("type") == "traffic"

    def _is_collection_status_event(self, event: Any) -> bool:
        return isinstance(event, dict) and event.get("type") == "collection_status"

    def _record_collection_status_event(self, event: dict) -> None:
        status = str(event.get("status") or "").strip()
        if status:
            self._status = status
        self._append_log(self._normalize_event(event))

    def _record_traffic_event(self, event: dict) -> None:
        try:
            timestamp = float(event.get("timestamp") or time.time())
        except (TypeError, ValueError):
            timestamp = time.time()

        self._traffic_events.append(
            {
                "timestamp": timestamp,
                "uploadBytes": max(0, int(event.get("uploadBytes") or 0)),
                "downloadBytes": max(0, int(event.get("downloadBytes") or 0)),
            }
        )
        self._prune_traffic_events(time.time())

    def _build_traffic_status(self, workers: list[str]) -> dict:
        now = time.time()
        self._prune_traffic_events(now)

        upload_rate = 0.0
        download_rate = 0.0
        if "mitm" in workers or "article_capture" in workers:
            window_start = now - TRAFFIC_RATE_WINDOW_SECONDS
            recent_events = [
                event
                for event in self._traffic_events
                if event["timestamp"] >= window_start
            ]
            upload_rate = sum(event["uploadBytes"] for event in recent_events) / TRAFFIC_RATE_WINDOW_SECONDS
            download_rate = sum(event["downloadBytes"] for event in recent_events) / TRAFFIC_RATE_WINDOW_SECONDS

        point = {
            "timestamp": round(now, 3),
            "time": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "uploadBytesPerSecond": round(upload_rate, 2),
            "downloadBytesPerSecond": round(download_rate, 2),
        }
        self._append_traffic_history_point(point)

        return {
            "uploadBytesPerSecond": point["uploadBytesPerSecond"],
            "downloadBytesPerSecond": point["downloadBytesPerSecond"],
            "uploadLabel": format_bytes_per_second(upload_rate),
            "downloadLabel": format_bytes_per_second(download_rate),
            "windowSeconds": int(TRAFFIC_RATE_WINDOW_SECONDS),
            "history": [
                {
                    "timestamp": item["timestamp"],
                    "time": item["time"],
                    "uploadBytesPerSecond": item["uploadBytesPerSecond"],
                    "downloadBytesPerSecond": item["downloadBytesPerSecond"],
                }
                for item in self._traffic_history
            ],
        }

    def _append_traffic_history_point(self, point: dict) -> None:
        if self._traffic_history and point["timestamp"] - self._traffic_history[-1]["timestamp"] < 1:
            self._traffic_history[-1] = point
        else:
            self._traffic_history.append(point)

        min_timestamp = point["timestamp"] - TRAFFIC_HISTORY_SECONDS
        self._traffic_history = [
            item
            for item in self._traffic_history
            if item["timestamp"] >= min_timestamp
        ][-TRAFFIC_HISTORY_LIMIT:]

    def _prune_traffic_events(self, now: float) -> None:
        min_timestamp = now - TRAFFIC_HISTORY_SECONDS
        self._traffic_events = [
            event
            for event in self._traffic_events
            if event["timestamp"] >= min_timestamp
        ]

    def _normalize_event(self, event: Any) -> dict:
        if isinstance(event, dict):
            normalized = RuntimeLog(
                level=str(event.get("level", "INFO")),
                message=str(event.get("message", "")),
                source=str(event.get("source", "worker")),
                created_at=str(event.get("createdAt", "")),
            ).to_dict()
            for key in (
                "type",
                "eventType",
                "phase",
                "substep",
                "status",
                "progress",
                "durationMs",
                "runId",
                "articleIndex",
                "meta",
            ):
                if key in event:
                    normalized[key] = event[key]
            return normalized

        return RuntimeLog(level="INFO", message=str(event), source="worker").to_dict()


def normalize_task_run_options(options: dict | None) -> dict:
    """统一前端传入的主服务运行参数，避免 worker 直接处理页面字段。"""
    data = options if isinstance(options, dict) else {}
    raw_selections = data.get("selections")
    selections = raw_selections if isinstance(raw_selections, dict) else {}

    try:
        record_limit = int(data.get("recordLimit", data.get("record_limit", 1)))
    except (TypeError, ValueError):
        record_limit = 1

    return {
        "recordLimit": max(0, record_limit),
        "selections": {
            "articleDetail": True,
            "commentInfo": bool(selections.get("commentInfo", True)),
        },
    }


def format_bytes_per_second(bytes_per_second: float) -> str:
    safe_value = max(0.0, float(bytes_per_second or 0))
    if safe_value <= 0:
        return "0 KB/s"

    kib = safe_value / 1024
    if kib < 1024:
        return f"{kib:.1f}".rstrip("0").rstrip(".") + " KB/s"

    mib = kib / 1024
    return f"{mib:.1f}".rstrip("0").rstrip(".") + " MB/s"

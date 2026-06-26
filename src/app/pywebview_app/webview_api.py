import json
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.config.runtime_config import save_runtime_config as write_runtime_config
from src.config.runtime_config import update_runtime_config_from_payload
from src.core.config import AppRuntimeConfig, DEFAULT_CONFIG_PATH, LOG_DIR
from src.core.task_manager import TaskManager
from src.modules.proxy.certificate import check_mitm_ca_certificate
from src.modules.proxy.certificate import delete_mitm_ca_certificates
from src.modules.proxy.certificate import install_mitm_ca_certificate
from src.modules.proxy.certificate import list_mitm_ca_certificates
from src.modules.proxy.https_probe import DEFAULT_HTTPS_TEST_URL
from src.modules.proxy.https_probe import test_https_proxy_connection
from src.modules.system.cache_cleaner import clear_directory_contents_except
from src.modules.system.env_checker import get_system_status
from src.modules.system.runtime_paths import build_runtime_paths
from src.modules.system.runtime_paths import resolve_runtime_path
from src.services.proxy_service import ProxyService
from src.services.task_service import TaskService

from .config import WEBVIEW_DIR, WINDOW_MIN_SIZE
from .window_content_size import calculate_outer_size_for_content, get_client_and_outer_size


def _coerce_json_payload(payload) -> dict:
    """把 pywebview 传来的 JSON 字符串转成字典；格式异常时回退为空配置。"""
    if isinstance(payload, dict):
        return payload
    try:
        loaded = json.loads(payload) if payload else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def open_file_in_explorer(path: Path) -> bool:
    """在 Windows Explorer 中打开文件所在目录，并选中目标日志文件。"""
    subprocess.Popen(["explorer.exe", f"/select,{path}"])
    return True


def open_directory_in_explorer(path: Path) -> bool:
    """在 Windows Explorer 中打开目录；目录不存在时由调用方先创建。"""
    subprocess.Popen(["explorer.exe", str(path)])
    return True


class WebviewApi:
    """提供给 Vue 页面调用的 Python API。"""

    def __init__(
        self,
        task_manager: TaskManager | None = None,
        runtime_config: AppRuntimeConfig | None = None,
        config_path: str | Path | None = None,
        auto_start: bool = False,
        ca_certificate_checker: Callable[[], dict] | None = None,
        ca_certificate_installer: Callable[[], dict] | None = None,
        ca_certificate_lister: Callable[[], dict] | None = None,
        ca_certificate_deleter: Callable[[list[str]], dict] | None = None,
        browser_opener: Callable[[str], bool] | None = None,
        file_selector: Callable[[Path], bool] | None = None,
        directory_opener: Callable[[Path], bool] | None = None,
        cache_dir: str | Path | None = None,
        proxy_connection_tester: Callable[[str, int, str], dict] | None = None,
    ):
        self._window = None
        self._is_shutting_down = False
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._task_manager = task_manager or TaskManager(config=runtime_config)
        self._runtime_config = runtime_config or getattr(self._task_manager, "config", AppRuntimeConfig())
        ca_cert_path = Path(self._runtime_config.proxy.confdir) / "mitmproxy-ca-cert.cer"
        self._ca_certificate_checker = ca_certificate_checker or (
            lambda: check_mitm_ca_certificate(current_ca_cert_path=ca_cert_path)
        )
        self._ca_certificate_installer = ca_certificate_installer or (
            lambda: install_mitm_ca_certificate(current_ca_cert_path=ca_cert_path)
        )
        self._ca_certificate_lister = ca_certificate_lister or list_mitm_ca_certificates
        self._ca_certificate_deleter = ca_certificate_deleter or delete_mitm_ca_certificates
        self._browser_opener = browser_opener or webbrowser.open
        self._file_selector = file_selector or open_file_in_explorer
        self._directory_opener = directory_opener or open_directory_in_explorer
        self._cache_dir = Path(cache_dir) if cache_dir else LOG_DIR
        self._proxy_connection_tester = proxy_connection_tester or test_https_proxy_connection
        self._task_service = TaskService(self._task_manager)
        self._proxy_service = ProxyService(self._task_manager)
        if auto_start:
            self._prepare_proxy_on_startup()

    def _prepare_proxy_on_startup(self) -> None:
        """应用启动时只准备代理环境，不触发主服务页的文章采集任务。"""
        try:
            proxy_result = self._proxy_service.start_mitm_proxy()
        except Exception as exc:
            self._log_runtime_error(f"应用启动时开启 MITM 代理失败：{exc}")
            return

        if not proxy_result.get("ok"):
            message = proxy_result.get("message") or "应用启动时开启 MITM 代理失败"
            self._log_runtime_error(str(message))
            return

        if not self._runtime_config.proxy.enable_system_proxy:
            return

        try:
            system_proxy_result = self._proxy_service.enable_system_proxy()
        except Exception as exc:
            self._log_runtime_error(f"应用启动时开启系统代理失败：{exc}")
            self._rollback_startup_mitm_proxy()
            return

        if not system_proxy_result.get("ok"):
            message = system_proxy_result.get("message") or "应用启动时开启系统代理失败"
            self._log_runtime_error(str(message))
            self._rollback_startup_mitm_proxy()

    def _rollback_startup_mitm_proxy(self) -> None:
        """系统代理接管失败时关闭已启动的 MITM，避免留下半启动代理环境。"""
        try:
            self._proxy_service.stop_mitm_proxy()
        except Exception as exc:
            self._log_runtime_error(f"启动回滚时关闭 MITM 代理失败：{exc}")

    def set_window(self, window) -> None:
        """绑定 pywebview 窗口，供前端请求调整窗口尺寸时使用。"""
        self._window = window

    def shutdown(self) -> None:
        """应用退出时释放 worker 并恢复系统代理，避免代理残留。"""
        self._is_shutting_down = True
        self._window = None
        self._task_service.shutdown()

    def get_status(self) -> str:
        """返回桌面端后端状态，前端可用于确认 pywebview 桥接是否可用。"""
        payload = {
            "ok": True,
            "status": "ready",
            "webviewExists": (WEBVIEW_DIR / "index.html").exists(),
            "serverTime": datetime.now().isoformat(timespec="seconds"),
            "environment": get_system_status(),
        }

        return json.dumps(payload, ensure_ascii=False)

    def start_task(self, task_payload=None) -> str:
        """启动采集链路；系统代理保持 main.py 启动时或用户手动设置的状态。"""
        try:
            payload = self._task_service.start_task(_coerce_json_payload(task_payload))
        except Exception as exc:
            message = f"start_task 调用失败：{exc}"
            self._log_runtime_error(message)
            payload = {
                "ok": False,
                "status": "error",
                "message": message,
            }
        return json.dumps(payload, ensure_ascii=False)

    def stop_task(self) -> str:
        """停止采集链路，不隐式改动系统代理。"""
        try:
            payload = self._task_service.stop_task()
        except Exception as exc:
            message = f"stop_task 调用失败：{exc}"
            self._log_runtime_error(message)
            payload = {"ok": False, "status": "error", "message": message}
        return json.dumps(payload, ensure_ascii=False)

    def start_mitm_proxy(self) -> str:
        """启动 MITM 代理监听进程。"""
        try:
            payload = self._proxy_service.start_mitm_proxy()
        except Exception as exc:
            message = f"start_mitm_proxy 调用失败：{exc}"
            self._log_runtime_error(message)
            payload = {"ok": False, "status": "error", "message": message}
        return json.dumps(payload, ensure_ascii=False)

    def stop_mitm_proxy(self) -> str:
        """停止 MITM 代理监听进程，不隐式改动系统代理。"""
        try:
            payload = self._proxy_service.stop_mitm_proxy()
        except Exception as exc:
            message = f"stop_mitm_proxy 调用失败：{exc}"
            self._log_runtime_error(message)
            payload = {"ok": False, "status": "error", "message": message}
        return json.dumps(payload, ensure_ascii=False)

    def enable_system_proxy(self) -> str:
        """开启系统代理接管流量。"""
        try:
            payload = self._proxy_service.enable_system_proxy()
        except Exception as exc:
            message = f"enable_system_proxy 调用失败：{exc}"
            self._log_runtime_error(message)
            payload = {"ok": False, "status": "error", "message": message}
        return json.dumps(payload, ensure_ascii=False)

    def disable_system_proxy(self) -> str:
        """恢复系统代理。"""
        try:
            payload = self._proxy_service.disable_system_proxy()
        except Exception as exc:
            message = f"disable_system_proxy 调用失败：{exc}"
            self._log_runtime_error(message)
            payload = {"ok": False, "status": "error", "message": message}
        return json.dumps(payload, ensure_ascii=False)

    def get_task_status(self) -> str:
        """读取任务状态，供页面轮询展示。"""
        try:
            payload = self._task_service.get_status()
        except Exception as exc:
            message = f"get_task_status 调用失败：{exc}"
            self._log_runtime_error(message)
            payload = {"ok": False, "status": "error", "message": message}
        return json.dumps(payload, ensure_ascii=False)

    def get_task_logs(self, limit: int = 100) -> str:
        """读取最近运行日志。"""
        try:
            safe_limit = max(1, min(500, int(limit)))
        except (TypeError, ValueError):
            safe_limit = 100

        payload = {
            "ok": True,
            "items": self._task_service.get_logs(safe_limit),
        }
        return json.dumps(payload, ensure_ascii=False)

    def open_current_runtime_log(self) -> str:
        """打开当前程序运行日志所在文件夹，并在 Explorer 中选中该日志文件。"""
        log_path = getattr(getattr(self._task_manager, "file_logger", None), "path", None)
        if not log_path:
            return json.dumps(
                {
                    "ok": False,
                    "status": "missing-log-path",
                    "message": "当前没有可打开的运行日志文件。",
                },
                ensure_ascii=False,
            )

        path = Path(log_path)
        if not path.exists():
            return json.dumps(
                {
                    "ok": False,
                    "status": "missing-log-file",
                    "logPath": str(path),
                    "logDir": str(path.parent),
                    "message": "当前运行日志文件尚不存在。",
                },
                ensure_ascii=False,
            )

        try:
            opened = bool(self._file_selector(path))
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "status": "open-failed",
                    "logPath": str(path),
                    "logDir": str(path.parent),
                    "message": f"打开运行日志失败：{exc}",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": opened,
                "status": "opened" if opened else "open-failed",
                "logPath": str(path),
                "logDir": str(path.parent),
                "message": "已打开当前运行日志。" if opened else "未能打开当前运行日志。",
            },
            ensure_ascii=False,
        )

    def get_runtime_paths(self) -> str:
        """返回系统配置页基础设置使用的真实运行目录。"""
        runtime_config = getattr(self._task_manager, "config", self._runtime_config)
        payload = {
            "ok": True,
            "status": "ok",
            "paths": build_runtime_paths(runtime_config),
        }
        return json.dumps(payload, ensure_ascii=False)

    def open_runtime_path(self, path_payload=None) -> str:
        """按目录 key 打开系统配置页中对应的本地文件夹。"""
        payload_data = _coerce_json_payload(path_payload)
        key = str(payload_data.get("key") or "").strip()
        runtime_config = getattr(self._task_manager, "config", self._runtime_config)

        try:
            target = resolve_runtime_path(runtime_config, key)
        except KeyError:
            return json.dumps(
                {
                    "ok": False,
                    "status": "invalid-key",
                    "key": key,
                    "message": f"未知目录类型：{key or '空'}",
                },
                ensure_ascii=False,
            )

        try:
            target.mkdir(parents=True, exist_ok=True)
            opened = bool(self._directory_opener(target))
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "status": "open-failed",
                    "key": key,
                    "path": str(target),
                    "message": f"打开目录失败：{exc}",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": opened,
                "status": "opened" if opened else "open-failed",
                "key": key,
                "path": str(target),
                "message": "已打开目录。" if opened else "未能打开目录。",
            },
            ensure_ascii=False,
        )

    def check_ca_certificate(self) -> str:
        """检测本机是否已经安装 mitmproxy CA 证书。"""
        try:
            payload = self._ca_certificate_checker()
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "unknown",
                "installed": False,
                "label": "无法检测",
                "message": f"检测 CA 证书失败：{exc}",
            }

        return json.dumps(payload, ensure_ascii=False)

    def install_ca_certificate(self) -> str:
        """把当前项目 mitmproxy CA 证书安装到当前用户根证书库。"""
        try:
            payload = self._ca_certificate_installer()
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "install-failed",
                "installed": False,
                "label": "安装失败",
                "message": f"安装 CA 证书失败：{exc}",
            }

        return json.dumps(payload, ensure_ascii=False)

    def open_ca_install_page(self) -> str:
        """在系统默认浏览器中打开 mitmproxy CA 证书安装页面。"""
        runtime_config = getattr(self._task_manager, "config", self._runtime_config)
        url = str(getattr(runtime_config.proxy, "verification_url", "http://mitm.it/") or "http://mitm.it/")

        try:
            opened = bool(self._browser_opener(url))
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "status": "open-failed",
                    "url": url,
                    "message": f"打开 CA 证书安装页面失败：{exc}",
                },
                ensure_ascii=False,
            )

        payload = {
            "ok": opened,
            "status": "opened" if opened else "open-failed",
            "url": url,
            "message": "已打开 CA 证书安装页面。" if opened else "未能打开 CA 证书安装页面。",
        }
        return json.dumps(payload, ensure_ascii=False)

    def list_mitm_ca_certificates(self) -> str:
        """检索当前系统中 mitmproxy 相关证书，供前端弹窗确认。"""
        try:
            payload = self._ca_certificate_lister()
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "query-failed",
                "count": 0,
                "certificates": [],
                "message": f"检索 MITM 证书失败：{exc}",
            }

        return json.dumps(payload, ensure_ascii=False)

    def delete_mitm_ca_certificates(self, certificate_payload=None) -> str:
        """按用户确认的指纹删除 mitmproxy 相关证书。"""
        try:
            payload_data = _coerce_json_payload(certificate_payload)
            thumbprints = payload_data.get("thumbprints", [])
            if not isinstance(thumbprints, list):
                thumbprints = []
            payload = self._ca_certificate_deleter([str(item) for item in thumbprints])
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "delete-failed",
                "deletedCount": 0,
                "skippedCount": 0,
                "deleted": [],
                "skipped": [],
                "message": f"删除 MITM 证书失败：{exc}",
            }

        return json.dumps(payload, ensure_ascii=False)

    def clear_runtime_cache(self) -> str:
        """清空项目 tmp 目录内容，保留 tmp 目录本身。"""
        try:
            current_log_path = getattr(getattr(self._task_manager, "file_logger", None), "path", None)
            keep_paths = [current_log_path] if current_log_path else []
            payload = clear_directory_contents_except(self._cache_dir, keep_paths)
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "clear-failed",
                "removedCount": 0,
                "keptCount": 0,
                "skippedCount": 0,
                "skipped": [],
                "message": f"清理缓存失败：{exc}",
            }

        return json.dumps(payload, ensure_ascii=False)

    def test_proxy_connection(self) -> str:
        """通过当前代理配置请求 HTTPS 页面，验证代理链路是否能获取内容。"""
        runtime_config = getattr(self._task_manager, "config", self._runtime_config)
        verification_url = str(getattr(runtime_config.proxy, "verification_url", "") or "")
        test_url = verification_url if verification_url.lower().startswith("https://") else DEFAULT_HTTPS_TEST_URL

        try:
            payload = self._proxy_connection_tester(
                runtime_config.proxy.host,
                runtime_config.proxy.port,
                test_url,
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "failed",
                "message": f"HTTPS 代理测试失败：{exc}",
                "url": test_url,
                "statusCode": 0,
                "bytesRead": 0,
            }

        return json.dumps(payload, ensure_ascii=False)

    def save_runtime_config(self, config_payload) -> str:
        """保存系统配置页传入的配置，并同步当前 TaskManager。"""
        try:
            current_config = getattr(self._task_manager, "config", AppRuntimeConfig())
            next_config = update_runtime_config_from_payload(config_payload, current_config)
            saved_path = write_runtime_config(next_config, self._config_path)
            self._runtime_config = next_config
            task_status = self._task_service.update_config(next_config, str(saved_path))
            payload = {
                "ok": True,
                "status": "saved",
                "configPath": str(saved_path),
                "taskStatus": task_status,
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "status": "save-failed",
                    "message": str(exc),
                    "configPath": str(self._config_path),
                },
                ensure_ascii=False,
            )

    def _log_runtime_error(self, message: str) -> None:
        try:
            self._task_service.log_runtime_error(message, source="webview")
        except Exception:
            return

    def resize_window_to_content(self, content_height: int | float) -> str:
        """按网页实际内容高度调整原生窗口高度，让页面铺满宽度后完整显示。"""
        if self._is_shutting_down:
            return json.dumps({"ok": False, "status": "window-disposed"}, ensure_ascii=False)

        if not self._window:
            return json.dumps({"ok": False, "status": "window-not-bound"}, ensure_ascii=False)

        try:
            safe_content_height = max(0, int(round(float(content_height))))
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "status": "invalid-content-height"}, ensure_ascii=False)

        try:
            client_size, outer_size = get_client_and_outer_size(self._window, WINDOW_MIN_SIZE)
            next_width, next_height = calculate_outer_size_for_content(
                outer_size=outer_size,
                client_size=client_size,
                content_height=safe_content_height,
                min_size=WINDOW_MIN_SIZE,
            )

            if (next_width, next_height) == outer_size:
                payload = {
                    "ok": True,
                    "status": "unchanged",
                    "width": next_width,
                    "height": next_height,
                }
                return json.dumps(payload, ensure_ascii=False)

            self._window.resize(next_width, next_height)
        except Exception as exc:
            message = f"窗口尺寸调整失败：{exc}"
            self._log_runtime_error(message)
            return json.dumps(
                {
                    "ok": False,
                    "status": "resize-failed",
                    "message": message,
                },
                ensure_ascii=False,
            )

        payload = {
            "ok": True,
            "status": "resized",
            "width": next_width,
            "height": next_height,
        }

        return json.dumps(payload, ensure_ascii=False)

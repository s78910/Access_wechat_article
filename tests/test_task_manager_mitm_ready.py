from __future__ import annotations

import tempfile
import unittest
import queue as thread_queue
from multiprocessing import Queue
from pathlib import Path
from unittest.mock import patch

from src.config.runtime_config import load_runtime_config, save_runtime_config, update_runtime_config_from_payload
from src.core.config import AppFeatureConfig, AppRuntimeConfig, MITMPROXY_CONF_DIR, ProxyConfig
from src.core import task_manager as task_manager_module
from src.core.task_manager import TaskManager, resolve_wait_timeout_seconds, wait_for_tcp_listener
from src.modules.proxy.system_proxy import ProxySnapshot
from src.workers.wechat_home import DEFAULT_WECHAT_HOME_SNAPSHOT, WeChatHomeSnapshot


class FakeProcessManager:
    def __init__(self) -> None:
        self.started_workers: list[str] = []

    def is_running(self, _name: str) -> bool:
        return False

    def start_worker(self, name: str, *_args, **_kwargs):
        self.started_workers.append(name)
        raise AssertionError("外部端口已占用时不应启动新的 MITM worker")

    def stop_worker(self, _name: str, timeout: float = 3) -> bool:
        return False

    def stop_all(self, timeout: float = 3) -> None:
        return None

    def running_workers(self) -> list[str]:
        return []


class FailingProxyManager:
    is_enabled = True

    def current_snapshot(self):
        raise RuntimeError("registry unavailable")


class TrackingProxyManager:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.is_enabled = False

    def start(self) -> ProxySnapshot:
        # 这里模拟用户手动点击“系统代理”开关后的真实接管动作。
        self.start_calls += 1
        self.is_enabled = True
        return ProxySnapshot(enabled=False, server="")

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_enabled = False

    def current_snapshot(self) -> ProxySnapshot:
        return ProxySnapshot(
            enabled=self.is_enabled,
            server="127.0.0.1:18000" if self.is_enabled else "",
        )


class OrderedProcessManager:
    def __init__(self, *, fail_stop_mitm: bool = False) -> None:
        self.fail_stop_mitm = fail_stop_mitm
        self.running = {"mitm", "article_capture"}
        self.calls: list[str] = []

    def is_running(self, name: str) -> bool:
        return name in self.running

    def start_worker(self, name: str, *_args, **_kwargs):
        self.calls.append(f"start_worker:{name}")
        self.running.add(name)

    def stop_worker(self, name: str, timeout: float = 3) -> bool:
        self.calls.append(f"stop_worker:{name}")
        if name == "mitm" and self.fail_stop_mitm:
            raise RuntimeError("MITM 停止失败")
        return bool(self.running.discard(name) is None)

    def stop_all(self, timeout: float = 3) -> None:
        self.calls.append("stop_all")
        self.running.clear()

    def running_workers(self) -> list[str]:
        return sorted(self.running)


class OrderedProxyManager:
    is_enabled = True

    def __init__(self, process_manager: OrderedProcessManager) -> None:
        self.process_manager = process_manager
        self.calls: list[str] = []

    def stop(self) -> None:
        self.calls.append("proxy.stop")
        self.process_manager.calls.append("proxy.stop")

    def current_snapshot(self):
        return FailingProxyManager().current_snapshot()


class NoopProxyManager:
    is_enabled = False

    def current_snapshot(self):
        return ProxySnapshot(enabled=False, server="")

    def stop(self) -> None:
        return None


class MemoryFileLogger:
    path = "memory.log"

    def __init__(self) -> None:
        self.written: list[dict] = []

    def write(self, event):
        self.written.append(dict(event))


class TaskManagerMitmReadyTest(unittest.TestCase):
    def test_wait_for_tcp_listener_retries_until_port_accepts_connection(self) -> None:
        calls = 0

        class FakeConnection:
            def close(self) -> None:
                return None

        def connector(_address, timeout=None):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise OSError("port not ready")
            return FakeConnection()

        ready = wait_for_tcp_listener(
            "127.0.0.1",
            18000,
            timeout_seconds=1,
            poll_interval_seconds=0,
            connector=connector,
        )

        self.assertTrue(ready)
        self.assertEqual(calls, 3)

    def test_wait_for_tcp_listener_returns_false_when_port_never_accepts_connection(self) -> None:
        calls = 0

        def connector(_address, timeout=None):
            nonlocal calls
            calls += 1
            raise OSError("port not ready")

        ready = wait_for_tcp_listener(
            "127.0.0.1",
            18000,
            timeout_seconds=0.01,
            poll_interval_seconds=0,
            connector=connector,
        )

        self.assertFalse(ready)
        self.assertGreater(calls, 0)

    def test_resolve_wait_timeout_caps_values_over_30_seconds_to_10_seconds(self) -> None:
        self.assertEqual(resolve_wait_timeout_seconds(60), 10.0)

    def test_runtime_config_loads_proxy_confdir_and_ssl_insecure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "custom.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "proxy:",
                        "  host: 127.0.0.1",
                        "  port: 18000",
                        "  confdir: ../.mitmproxy",
                        "  ssl_insecure: true",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_runtime_config(config_path)

            self.assertEqual(config.proxy.confdir, (config_path.parent / "../.mitmproxy").resolve())
            self.assertTrue(config.proxy.ssl_insecure)

    def test_default_proxy_config_uses_project_mitmproxy_confdir(self) -> None:
        config = load_runtime_config(Path("__missing_config__.yaml"))

        self.assertEqual(config.proxy.confdir, MITMPROXY_CONF_DIR)
        self.assertTrue(config.proxy.ssl_insecure)

    def test_runtime_config_loads_updates_and_saves_log_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "custom.yaml"
            config_path.write_text("log_level: WARN\n", encoding="utf-8")

            config = load_runtime_config(config_path)
            updated = update_runtime_config_from_payload({"logLevel": "DEBUG"}, config)
            saved_path = save_runtime_config(updated, config_path)
            reloaded = load_runtime_config(saved_path)

            self.assertEqual(config.app.log_level, "WARN")
            self.assertEqual(updated.app.log_level, "DEBUG")
            self.assertIn("log_level: DEBUG", saved_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded.app.log_level, "DEBUG")

    def test_runtime_config_loads_updates_and_saves_capture_timing_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "custom.yaml"
            config_path.write_text("request_interval_seconds: 4\nretry_count: 2\n", encoding="utf-8")

            config = load_runtime_config(config_path)
            updated = update_runtime_config_from_payload({"requestIntervalSeconds": 7, "retryCount": 3}, config)
            saved_path = save_runtime_config(updated, config_path)
            reloaded = load_runtime_config(saved_path)
            saved_text = saved_path.read_text(encoding="utf-8")

            self.assertEqual(config.app.request_interval_seconds, 4)
            self.assertEqual(config.app.retry_count, 2)
            self.assertEqual(updated.app.request_interval_seconds, 7)
            self.assertEqual(updated.app.retry_count, 3)
            self.assertIn("request_interval_seconds: 7", saved_text)
            self.assertIn("retry_count: 3", saved_text)
            self.assertEqual(reloaded.app.request_interval_seconds, 7)
            self.assertEqual(reloaded.app.retry_count, 3)

    def test_status_returns_capture_timing_options(self) -> None:
        manager = TaskManager(
            config=AppRuntimeConfig(app=AppFeatureConfig(request_interval_seconds=6, retry_count=4)),
            process_manager=FakeProcessManager(),
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        result = manager.get_status(refresh_home=False)

        self.assertEqual(result["config"]["requestIntervalSeconds"], 6)
        self.assertEqual(result["config"]["retryCount"], 4)

    def test_start_mitm_proxy_rejects_external_listener_before_spawning_worker(self) -> None:
        process_manager = FakeProcessManager()
        manager = TaskManager(
            config=AppRuntimeConfig(proxy=ProxyConfig(host="127.0.0.1", port=18000)),
            process_manager=process_manager,
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        with patch("src.core.task_manager.wait_for_tcp_listener", return_value=True):
            result = manager.start_mitm_proxy()

        self.assertFalse(result["ok"])
        self.assertEqual(process_manager.started_workers, [])
        self.assertIn("18000", result["message"])

    def test_status_does_not_replace_failed_system_proxy_read_with_configured_address(self) -> None:
        manager = TaskManager(
            config=AppRuntimeConfig(proxy=ProxyConfig(host="127.0.0.1", port=18000)),
            proxy_manager=FailingProxyManager(),
            process_manager=FakeProcessManager(),
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        result = manager.get_status(refresh_home=False)

        self.assertFalse(result["proxy"]["systemProxyReadable"])
        self.assertEqual(result["proxy"]["systemProxyServer"], "")
        self.assertEqual(result["proxy"]["systemProxyReadError"], "registry unavailable")

    def test_manual_system_proxy_enable_does_not_require_mitm_worker(self) -> None:
        proxy_manager = TrackingProxyManager()
        manager = TaskManager(
            config=AppRuntimeConfig(proxy=ProxyConfig(host="127.0.0.1", port=18000)),
            proxy_manager=proxy_manager,
            process_manager=FakeProcessManager(),
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        result = manager.enable_system_proxy()

        self.assertTrue(result["ok"])
        self.assertEqual(proxy_manager.start_calls, 1)
        self.assertTrue(result["proxy"]["systemProxyActive"])
        self.assertEqual(result["proxy"]["systemProxyServer"], "127.0.0.1:18000")

    def test_stop_during_start_prevents_article_worker_from_starting_after_home_detection(self) -> None:
        class RunningMitmProcessManager(FakeProcessManager):
            def __init__(self) -> None:
                super().__init__()
                self.running = {"mitm"}
                self.stopped_workers: list[str] = []

            def is_running(self, name: str) -> bool:
                return name in self.running

            def start_worker(self, name: str, *_args, **_kwargs):
                self.started_workers.append(name)
                self.running.add(name)

            def stop_worker(self, name: str, timeout: float = 3) -> bool:
                self.stopped_workers.append(name)
                self.running.discard(name)
                return True

            def running_workers(self) -> list[str]:
                return sorted(self.running)

        process_manager = RunningMitmProcessManager()
        manager: TaskManager | None = None

        def detector(**_kwargs):
            assert manager is not None
            manager.stop_task()
            return WeChatHomeSnapshot(
                status="ready",
                status_label="主页信息已获取",
                account_name="测试公众号",
                description="测试简介",
                original_count="1",
                friend_follow_count="0",
                found=True,
                account_confidence="high",
                account_source="profile_header",
            )

        manager = TaskManager(
            config=AppRuntimeConfig(app=AppFeatureConfig(auto_start_proxy=False)),
            proxy_manager=NoopProxyManager(),
            process_manager=process_manager,
            home_detector=detector,
        )

        with patch.object(manager, "_wait_for_mitm_listener", return_value=True):
            result = manager.start_task({"recordLimit": 1})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "stopped")
        self.assertNotIn("article_capture", process_manager.started_workers)

    def test_start_task_returns_to_stopped_when_mitm_port_is_not_ready(self) -> None:
        class RunningMitmProcessManager(FakeProcessManager):
            def is_running(self, name: str) -> bool:
                return name == "mitm"

            def running_workers(self) -> list[str]:
                return ["mitm"]

        manager = TaskManager(
            config=AppRuntimeConfig(app=AppFeatureConfig(auto_start_proxy=False)),
            proxy_manager=NoopProxyManager(),
            process_manager=RunningMitmProcessManager(),
            home_detector=lambda **_kwargs: WeChatHomeSnapshot(
                status="ready",
                status_label="主页信息已获取",
                account_name="测试公众号",
                description="测试简介",
                original_count="1",
                friend_follow_count="0",
                found=True,
                account_confidence="high",
                account_source="profile_header",
            ),
        )

        with patch.object(manager, "_wait_for_mitm_listener", return_value=False):
            result = manager.start_task({"recordLimit": 1})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(manager.get_status(refresh_home=False)["status"], "stopped")

    def test_start_task_returns_to_stopped_when_home_window_is_missing(self) -> None:
        manager = TaskManager(
            config=AppRuntimeConfig(app=AppFeatureConfig(auto_start_proxy=False)),
            proxy_manager=NoopProxyManager(),
            process_manager=FakeProcessManager(),
            home_detector=lambda **_kwargs: WeChatHomeSnapshot(
                status="not_found",
                status_label="未检测到主页窗口",
                account_name="未检测到微信 PC 公众号主页",
                description="请先打开公众号或服务号主页",
                original_count="未识别到",
                friend_follow_count="未识别到",
                found=False,
                message="请先打开公众号或服务号主页",
            ),
        )

        result = manager.start_task({"recordLimit": 1})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["message"], "请先打开公众号或服务号主页")

    def test_shutdown_stops_collection_restores_system_proxy_then_stops_mitm(self) -> None:
        process_manager = OrderedProcessManager()
        proxy_manager = OrderedProxyManager(process_manager)
        manager = TaskManager(
            config=AppRuntimeConfig(proxy=ProxyConfig(host="127.0.0.1", port=18000)),
            proxy_manager=proxy_manager,
            process_manager=process_manager,
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        manager.shutdown()

        self.assertEqual(
            process_manager.calls,
            [
                "stop_worker:article_capture",
                "proxy.stop",
                "stop_worker:mitm",
            ],
        )

    def test_shutdown_restores_system_proxy_even_when_mitm_stop_fails(self) -> None:
        process_manager = OrderedProcessManager(fail_stop_mitm=True)
        proxy_manager = OrderedProxyManager(process_manager)
        manager = TaskManager(
            config=AppRuntimeConfig(proxy=ProxyConfig(host="127.0.0.1", port=18000)),
            proxy_manager=proxy_manager,
            process_manager=process_manager,
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        manager.shutdown()

        self.assertIn("proxy.stop", process_manager.calls)
        self.assertLess(
            process_manager.calls.index("proxy.stop"),
            process_manager.calls.index("stop_worker:mitm"),
        )

    def test_status_reports_auth_captured_after_mitm_key_url_event(self) -> None:
        event_queue = Queue()
        event_queue.put(
            {
                "type": "auth_status",
                "source": "mitm",
                "level": "SUCCESS",
                "status": "captured",
                "statusLabel": "已获取鉴权",
                "hasKeyUrl": True,
                "urlRedacted": "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn",
                "urlSource": "request",
                "createdAt": "2026-06-21T15:30:00",
            }
        )
        manager = TaskManager(
            config=AppRuntimeConfig(proxy=ProxyConfig(host="127.0.0.1", port=18000)),
            process_manager=FakeProcessManager(),
            event_queue=event_queue,
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        result = manager.get_status(refresh_home=False)

        self.assertTrue(result["auth"]["hasKeyUrl"])
        self.assertEqual(result["auth"]["status"], "captured")
        self.assertEqual(result["auth"]["statusLabel"], "已获取鉴权")
        self.assertEqual(result["auth"]["lastKeyUrlSource"], "request")
        self.assertEqual(result["auth"]["lastKeyUrlAt"], "2026-06-21T15:30:00")
        self.assertNotIn("secret", result["auth"].get("lastKeyUrlRedacted", ""))

    def test_status_reports_auth_waiting_when_mitm_runs_without_key_url(self) -> None:
        class MitmOnlyProcessManager(FakeProcessManager):
            def running_workers(self) -> list[str]:
                return ["mitm"]

        manager = TaskManager(
            config=AppRuntimeConfig(proxy=ProxyConfig(host="127.0.0.1", port=18000)),
            process_manager=MitmOnlyProcessManager(),
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        result = manager.get_status(refresh_home=False)

        self.assertFalse(result["auth"]["hasKeyUrl"])
        self.assertEqual(result["auth"]["status"], "waiting")
        self.assertEqual(result["auth"]["statusLabel"], "等待鉴权")

    def test_task_manager_filters_runtime_and_file_logs_by_log_level(self) -> None:
        file_logger = MemoryFileLogger()
        manager = TaskManager(
            config=AppRuntimeConfig(app=AppFeatureConfig(log_level="WARN")),
            process_manager=FakeProcessManager(),
            file_logger=file_logger,
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        for level in ("DEBUG", "INFO", "SUCCESS", "WARN", "ERROR"):
            manager._append_log({"level": level, "message": f"{level} message", "source": "test"})

        self.assertEqual([item["level"] for item in manager.get_logs(20)], ["WARN", "ERROR"])
        self.assertEqual([item["level"] for item in file_logger.written], ["WARN", "ERROR"])
        self.assertEqual(manager.get_status(refresh_home=False)["config"]["logLevel"], "WARN")

    def test_runtime_logs_are_bounded_to_recent_events(self) -> None:
        limit = getattr(task_manager_module, "MAX_RUNTIME_LOGS", 5000)
        manager = TaskManager(
            process_manager=FakeProcessManager(),
            file_logger=MemoryFileLogger(),
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )

        for index in range(limit + 25):
            manager._append_log({"level": "INFO", "message": f"log-{index}", "source": "test"})

        self.assertLessEqual(len(manager._logs), limit)
        self.assertEqual(manager.get_logs(1)[0]["message"], f"log-{limit + 24}")
        self.assertEqual(manager._logs[0]["message"], "log-25")

    def test_collection_finish_prunes_logs_and_drops_stale_capture_events(self) -> None:
        completed_limit = getattr(task_manager_module, "COMPLETED_RUNTIME_LOGS", 1000)
        event_queue = thread_queue.Queue()
        capture_event_queue = thread_queue.Queue()
        manager = TaskManager(
            process_manager=FakeProcessManager(),
            event_queue=event_queue,
            capture_event_queue=capture_event_queue,
            file_logger=MemoryFileLogger(),
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )
        for index in range(completed_limit + 50):
            manager._append_log({"level": "INFO", "message": f"before-finish-{index}", "source": "test"})
        for index in range(3):
            capture_event_queue.put(
                {
                    "type": "article_main_html_captured",
                    "url": f"https://example.test/{index}",
                    "html_text": "x" * 1024,
                }
            )

        event_queue.put(
            {
                "type": "collection_status",
                "status": "stopped",
                "level": "INFO",
                "message": "collection stopped",
                "source": "article_capture",
            }
        )
        manager.get_status(refresh_home=False)

        self.assertLessEqual(len(manager._logs), completed_limit)
        self.assertEqual(manager.get_logs(1)[0]["message"], "collection stopped")
        with self.assertRaises(thread_queue.Empty):
            capture_event_queue.get_nowait()

    def test_manual_stop_clears_stale_capture_events(self) -> None:
        capture_event_queue = thread_queue.Queue()
        manager = TaskManager(
            process_manager=FakeProcessManager(),
            capture_event_queue=capture_event_queue,
            file_logger=MemoryFileLogger(),
            home_detector=lambda **_kwargs: DEFAULT_WECHAT_HOME_SNAPSHOT,
        )
        capture_event_queue.put({"type": "article_main_html_captured", "html_text": "x" * 1024})

        manager.stop_collection_task()

        with self.assertRaises(thread_queue.Empty):
            capture_event_queue.get_nowait()


if __name__ == "__main__":
    unittest.main()

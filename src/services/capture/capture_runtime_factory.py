from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config.app_config import AppConfig
from src.modules.processes.process_launcher import MultiprocessingProcessLauncher
from src.modules.system.windows_system_proxy import WindowsSystemProxy
from src.services.capture.mitm_process_control_service import MitmProcessControlService
from src.services.capture.single_article_capture_service import SingleArticleCaptureService
from src.services.capture.window_runtime_factory import WindowRuntimeFactory


class CaptureRuntimeFactory:
    """使用同一份内存配置装配真实 MITM 与单篇采集组件。"""

    def __init__(
        self,
        config: AppConfig,
        *,
        window_factory: WindowRuntimeFactory,
        launcher_factory: Callable[[], Any] = MultiprocessingProcessLauncher,
        system_proxy_factory: Callable[[], Any] = WindowsSystemProxy,
        process_control_factory: Callable[..., Any] = MitmProcessControlService,
        single_capture_factory: Callable[..., Any] = SingleArticleCaptureService,
    ) -> None:
        self._config = config
        self._window_factory = window_factory
        self._launcher_factory = launcher_factory
        self._system_proxy_factory = system_proxy_factory
        self._process_control_factory = process_control_factory
        self._single_capture_factory = single_capture_factory

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def window_factory(self) -> WindowRuntimeFactory:
        return self._window_factory

    def create_process_control(self) -> Any:
        """创建可跨多次 attempt 使用的父进程控制器；每次 attempt 仍新建子进程。"""
        if not self._config.proxy.enable_system_proxy:
            raise RuntimeError(
                "custom.yaml 已关闭 enable_system_proxy，不能创建真实 MITM 代理控制器"
            )
        return self._process_control_factory(
            launcher=self._launcher_factory(),
            fallback_system_proxy=self._system_proxy_factory(),
        )

    def create_single_article_service(
        self,
        *,
        cursor: Any,
        process_control: Any | None = None,
    ) -> Any:
        """装配一次文章捕获服务，不在这里执行点击、重试或文件保存。"""
        control = (
            process_control
            if process_control is not None
            else self.create_process_control()
        )
        return self._single_capture_factory(
            cursor=cursor,
            clicker=self._window_factory.create_clicker(),
            tabs=self._window_factory.create_tab_service(),
            process_control=control,
        )


__all__ = ["CaptureRuntimeFactory"]

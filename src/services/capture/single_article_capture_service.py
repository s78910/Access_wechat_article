from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping, Protocol

from src.config.app_config import AppConfig
from src.domain.enums import CaptureType, ErrorCode, TaskStatus
from src.domain.models import ArticleTarget, MitmCaptureResult, TaskContext
from src.domain.results import ServiceResult
from src.modules.window.article_clicker import ArticleClicker, ClickResult
from src.modules.window.home_article_cursor import HomeArticleCursor, TargetRefreshError
from src.modules.window.wechat_browser_tabs import (
    ArticleTabNotFoundError,
    WechatBrowserTabService,
)
from src.modules.window.window_models import BrowserTabInfo, WindowInfo
from src.services.capture.mitm_process_control_service import (
    MitmAttemptProcess,
    MitmProcessControlService,
    MitmProcessError,
)


@dataclass(frozen=True, slots=True)
class SingleCaptureSettings:
    proxy_address: str
    capture_config: dict[str, Any]
    ready_timeout_seconds: float
    result_timeout_seconds: float
    title_timeout_seconds: float
    title_poll_initial_interval_seconds: float
    title_poll_max_interval_seconds: float
    title_poll_interval_seconds: float
    title_stable_delay_seconds: float

    @classmethod
    def from_app_config(cls, config: AppConfig) -> SingleCaptureSettings:
        stable_delay = config.window.article_title_stable_delay_seconds
        capture_timeout = config.mitm_capture.capture_timeout_seconds
        return cls(
            proxy_address=f"{config.proxy.host}:{config.proxy.port}",
            capture_config={
                "host": config.proxy.host,
                "port": config.proxy.port,
                "confdir": str(config.proxy.confdir),
                "ssl_insecure": config.proxy.ssl_insecure,
                "ready_timeout_seconds": config.mitm_capture.ready_timeout_seconds,
                "capture_timeout_seconds": capture_timeout,
                "shutdown_timeout_seconds": config.mitm_capture.listener_shutdown_timeout_seconds,
            },
            ready_timeout_seconds=config.mitm_capture.ready_timeout_seconds,
            result_timeout_seconds=config.mitm_capture.result_timeout_seconds,
            title_timeout_seconds=config.window.article_open_timeout_seconds,
            title_poll_initial_interval_seconds=(
                config.window.article_title_poll_initial_interval_seconds
            ),
            title_poll_max_interval_seconds=(
                config.window.article_title_poll_max_interval_seconds
            ),
            title_poll_interval_seconds=config.window.article_title_poll_interval_seconds,
            title_stable_delay_seconds=stable_delay,
        )


@dataclass(frozen=True, slots=True)
class SingleArticleCaptureData:
    target: ArticleTarget
    article_tab: BrowserTabInfo
    click_result: ClickResult
    capture_result: MitmCaptureResult


class CaptureCursor(Protocol):
    def refresh_target(self, home_window: WindowInfo, target: ArticleTarget) -> ArticleTarget: ...


class CaptureClicker(Protocol):
    def click(self, target: ArticleTarget) -> ClickResult: ...


class CaptureTabs(Protocol):
    def capture_baseline(self) -> dict[str, str]: ...

    def wait_for_opened_article_tab(self, **kwargs: Any) -> BrowserTabInfo: ...

    def close_article_tab(
        self,
        selected: BrowserTabInfo,
        *,
        home_window_handle: int,
    ) -> None: ...


class CaptureProcessControl(Protocol):
    def start_attempt(self, **kwargs: Any) -> MitmAttemptProcess: ...


class SingleArticleCaptureService:
    """执行一次真实文章采集尝试；重试只能由上层任务编排决定。"""

    def __init__(
        self,
        *,
        cursor: CaptureCursor,
        clicker: CaptureClicker,
        tabs: CaptureTabs,
        process_control: CaptureProcessControl,
    ) -> None:
        self._cursor = cursor
        self._clicker = clicker
        self._tabs = tabs
        self._process_control = process_control

    def capture_once(
        self,
        *,
        context: TaskContext,
        attempt_id: str,
        home_window: WindowInfo,
        target: ArticleTarget,
        settings: SingleCaptureSettings,
        runtime_state: Any | None = None,
    ) -> ServiceResult[SingleArticleCaptureData]:
        started_at = time.monotonic()
        attempt: MitmAttemptProcess | None = None
        article_tab: BrowserTabInfo | None = None
        tab_closed = False
        attempt_finished = False
        worker_tracked = False
        try:
            _set_runtime_action(runtime_state, "选择待采集文章")
            refreshed_target = self._cursor.refresh_target(home_window, target)
            baseline = self._tabs.capture_baseline()
            _set_runtime_action(runtime_state, "启动代理捕获")
            attempt = self._process_control.start_attempt(
                task_id=context.task_id,
                attempt_id=attempt_id,
                proxy_lease_id=context.proxy_lease_id,
                proxy_address=settings.proxy_address,
                capture_config=settings.capture_config,
            )
            _call_runtime(runtime_state, "worker_started")
            worker_tracked = True
            attempt.wait_ready(timeout_seconds=settings.ready_timeout_seconds)
            _set_runtime_action(runtime_state, "点击文章")
            click_started = time.monotonic()
            click_result = self._clicker.click(refreshed_target)

            try:
                _set_runtime_action(runtime_state, "等待文章打开")
                article_tab = self._tabs.wait_for_opened_article_tab(
                    baseline=baseline,
                    timeout_seconds=settings.title_timeout_seconds,
                    stable_delay_seconds=settings.title_stable_delay_seconds,
                    poll_initial_interval_seconds=(
                        settings.title_poll_initial_interval_seconds
                    ),
                    poll_max_interval_seconds=settings.title_poll_max_interval_seconds,
                )
            except ArticleTabNotFoundError as exc:
                _record_runtime_stage(
                    runtime_state,
                    article_key=target.fingerprint,
                    stage="click",
                    label="点击文章",
                    status="failed",
                    duration_seconds=time.monotonic() - click_started,
                    message=str(exc),
                )
                # 窗口检测已经到截止时间，立即冻结并关闭本次 MITM，不再为捕获额外等待。
                attempt.stop_capture(timeout_seconds=settings.result_timeout_seconds)
                attempt_finished = True
                return ServiceResult.failure(
                    ErrorCode.ARTICLE_TITLE_MISMATCH,
                    str(exc),
                    duration_seconds=time.monotonic() - started_at,
                )
            _record_runtime_stage(
                runtime_state,
                article_key=target.fingerprint,
                stage="click",
                label="点击文章",
                status="success",
                duration_seconds=time.monotonic() - click_started,
                message=f"已派发点击并确认文章打开：{click_result.method}",
            )

            _set_runtime_action(runtime_state, "关闭文章标签")
            close_started = time.monotonic()
            try:
                self._tabs.close_article_tab(
                    article_tab,
                    home_window_handle=home_window.handle,
                )
            except Exception as exc:
                _record_runtime_stage(
                    runtime_state,
                    article_key=target.fingerprint,
                    stage="close",
                    label="关闭文章标签",
                    status="failed",
                    duration_seconds=time.monotonic() - close_started,
                    message=str(exc),
                )
                raise
            _record_runtime_stage(
                runtime_state,
                article_key=target.fingerprint,
                stage="close",
                label="关闭文章标签",
                status="success",
                duration_seconds=time.monotonic() - close_started,
                message="文章标签已关闭",
            )
            tab_closed = True
            capture_result = attempt.stop_capture(
                timeout_seconds=settings.result_timeout_seconds
            )
            attempt_finished = True
            if (
                capture_result.status is not TaskStatus.SUCCESS
                or capture_result.capture_type is CaptureType.NONE
            ):
                return ServiceResult.failure(
                    ErrorCode.CAPTURE_EMPTY,
                    capture_result.error_message or "未捕获到 HTML 或 reference",
                    duration_seconds=time.monotonic() - started_at,
                )
            return ServiceResult.success(
                SingleArticleCaptureData(
                    target=refreshed_target,
                    article_tab=article_tab,
                    click_result=click_result,
                    capture_result=capture_result,
                ),
                duration_seconds=time.monotonic() - started_at,
            )
        except TargetRefreshError as exc:
            return ServiceResult.failure(
                ErrorCode.ARTICLE_TITLE_MISMATCH,
                str(exc),
                duration_seconds=time.monotonic() - started_at,
            )
        except MitmProcessError as exc:
            attempt_finished = True
            return ServiceResult.failure(
                ErrorCode.MITM_NOT_READY,
                str(exc),
                duration_seconds=time.monotonic() - started_at,
            )
        except Exception as exc:
            return ServiceResult.failure(
                ErrorCode.WINDOW_NOT_FOUND,
                str(exc),
                duration_seconds=time.monotonic() - started_at,
            )
        finally:
            if article_tab is not None and not tab_closed:
                try:
                    self._tabs.close_article_tab(
                        article_tab,
                        home_window_handle=home_window.handle,
                    )
                except Exception:
                    pass
            if attempt is not None and not attempt_finished:
                attempt.cancel()
            if worker_tracked:
                _call_runtime(runtime_state, "worker_finished")


def _set_runtime_action(runtime_state: Any | None, action: str) -> None:
    _call_runtime(runtime_state, "set_action", action)


def _record_runtime_stage(
    runtime_state: Any | None,
    *,
    article_key: str,
    stage: str,
    label: str,
    status: str,
    duration_seconds: float,
    message: str,
) -> None:
    _call_runtime(
        runtime_state,
        "record_article_stage",
        article_key=article_key,
        stage=stage,
        label=label,
        status=status,
        duration_seconds=max(0.0, float(duration_seconds)),
        message=message,
    )


def _call_runtime(
    runtime_state: Any | None,
    method_name: str,
    *args: Any,
    **kwargs: Any,
) -> None:
    method = getattr(runtime_state, method_name, None)
    if callable(method):
        try:
            method(*args, **kwargs)
        except Exception:
            pass

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from src.domain.enums import CaptureType
from src.services.runtime.window_click_flow_diagnostic_service import (
    _card_record,
    _record_item,
)


DiagnosticUpdate = Callable[[dict[str, Any]], None]


class ArticleCardProbeService:
    """同步定位公众号主页，并读取当前可视区第一篇文章卡片。"""

    def __init__(
        self,
        *,
        config: Any,
        window_factory: Any,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._window_factory = window_factory
        self._monotonic = monotonic

    def read_first_visible_card(
        self,
        *,
        on_update: DiagnosticUpdate | None = None,
    ) -> dict[str, Any]:
        """返回可直接传给单篇 Huey 任务的公众号名和首篇卡片信息。"""

        started_at = self._monotonic()
        items: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        account_name = ""

        def publish(
            message: str,
            *,
            ok: bool = False,
            status: str = "running",
            tone: str = "info",
        ) -> dict[str, Any]:
            payload = _result(
                ok=ok,
                status=status,
                message=message,
                tone=tone,
                items=items,
                total_seconds=_elapsed(self._monotonic, started_at),
            )
            payload["accountName"] = account_name
            payload["records"] = list(records)
            if on_update is not None:
                on_update(payload)
            return payload

        publish("正在定位公众号主页窗口...")
        try:
            reader = self._window_factory.create_reader()
            home_window = self._window_factory.find_home_window(
                reader=reader,
                timeout_seconds=self._config.window.home_find_timeout_seconds,
            )
            if home_window is None:
                return publish(
                    "未找到公众号主页窗口，请先打开公众号主页。",
                    status="home-not-found",
                    tone="warning",
                )

            # 这里只读取首篇卡片作为 Huey 单篇任务输入，不做点击、MITM 或标签关闭。
            self._window_factory.create_home_guard().activate(home_window)
            try:
                home_info = self._window_factory.create_home_reader().read(home_window)
                account_name = str(_safe_attr(home_info, "account_name", "") or "")
            except Exception:
                account_name = ""
            publish("已定位公众号主页窗口，正在读取可视区第一篇文章卡片...")

            snapshot = self._window_factory.create_window_test_reader().read(
                home_window
            )
            if not snapshot.visible_cards:
                return publish(
                    "当前主页可视区没有识别到文章卡片。",
                    status="no-visible-card",
                    tone="warning",
                )

            record = _card_record(snapshot.visible_cards[0], index=1)
            # 单篇 Huey 任务只接收卡片快照，点击阶段需要主页窗口句柄。
            record["homeWindowHandle"] = int(getattr(home_window, "handle", 0) or 0)
            record["accountName"] = account_name
            records.append(record)
            items.append(_record_item(record))
            return publish(
                "已识别可视区第一篇文章卡片。",
                ok=True,
                status="completed",
                tone="success",
            )
        except Exception as exc:
            items.append({"label": "失败原因", "value": str(exc)})
            return publish(
                f"读取首篇文章卡片失败：{exc}",
                status="failed",
                tone="error",
            )


def _result(
    *,
    ok: bool,
    status: str,
    message: str,
    tone: str,
    items: list[dict[str, Any]],
    total_seconds: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "action": "single-article-detail",
        "title": "详情获取结果",
        "message": message,
        "tone": tone,
        "items": list(items),
        "captureType": CaptureType.NONE.value,
    }
    if total_seconds is not None:
        result["totalSeconds"] = round(float(total_seconds), 3)
    return result


def _safe_attr(value: Any, name: str, fallback: Any = "") -> Any:
    try:
        result = getattr(value, name)
    except Exception:
        return fallback
    return fallback if result is None else result


def _elapsed(monotonic: Callable[[], float], started_at: float) -> float:
    return max(0.0, monotonic() - started_at)


__all__ = ["ArticleCardProbeService"]

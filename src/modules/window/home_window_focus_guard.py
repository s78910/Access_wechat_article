from __future__ import annotations

from typing import Any, Callable

from src.modules.window.window_activator import activate_wechat_window_for_uia


WindowActivator = Callable[..., dict[str, Any]]


def ensure_home_window_readable(
    home_window: Any,
    config: dict[str, Any] | None = None,
    *,
    activate_window: WindowActivator = activate_wechat_window_for_uia,
) -> dict[str, Any]:
    """重新软激活主页窗口，让微信 UIA 控件树有机会恢复正文列表。"""
    data = config if isinstance(config, dict) else {}
    if not bool(data.get("homepage_focus_recover_enabled", True)):
        return {"ok": False, "reason": "disabled"}
    if home_window is None:
        return {"ok": False, "reason": "wechat_home_window_not_found"}

    delay_seconds = _resolve_focus_recover_delay_seconds(data)
    try:
        result = activate_window(home_window, delay_seconds=delay_seconds)
    except Exception as exc:
        return {"ok": False, "reason": "activate_failed", "error": str(exc)}
    return result if isinstance(result, dict) else {"ok": bool(result), "reason": "activated"}


def resolve_focus_recover_attempts(config: dict[str, Any] | None) -> int:
    data = config if isinstance(config, dict) else {}
    try:
        attempts = int(data.get("homepage_focus_recover_attempts", 2))
    except (TypeError, ValueError):
        attempts = 2
    return max(0, attempts)


def _resolve_focus_recover_delay_seconds(config: dict[str, Any]) -> float:
    try:
        seconds = float(
            config.get(
                "homepage_focus_recover_delay_seconds",
                config.get("wechat_home_activate_delay_seconds", 0.3),
            )
        )
    except (TypeError, ValueError):
        seconds = 0.3
    return max(0.0, seconds)


__all__ = ["ensure_home_window_readable", "resolve_focus_recover_attempts"]

from __future__ import annotations

from src.modules.window.wechat_detector import WeChatHomeSnapshot


DISPLAY_CACHED_STATUS_LABEL = "主页信息暂不可读，已沿用上次识别"
DISPLAY_UNAVAILABLE_STATUS_LABEL = "主页信息暂不可读，不影响采集"
DISPLAY_REFERENCE_MESSAGE = "展示信息仅供参考，不影响采集入库"


class HomeDisplayCache:
    """缓存主页状态区的可信展示信息，不参与采集、去重或入库判断。"""

    def __init__(self) -> None:
        self._last_trusted: WeChatHomeSnapshot | None = None

    def apply(self, snapshot: WeChatHomeSnapshot) -> WeChatHomeSnapshot:
        """根据最新检测结果返回页面展示用快照。"""
        if self._is_trusted_profile(snapshot):
            self._last_trusted = snapshot
            return snapshot

        if self._should_keep_last_trusted(snapshot):
            if self._last_trusted is not None:
                return self._build_cached_snapshot(snapshot)
            return self._build_unavailable_snapshot(snapshot)

        return snapshot

    @staticmethod
    def _is_trusted_profile(snapshot: WeChatHomeSnapshot) -> bool:
        if not snapshot.found:
            return False
        account_name = str(snapshot.account_name or "").strip()
        if not account_name:
            return False
        confidence = str(getattr(snapshot, "account_confidence", "") or "").strip().lower()
        source = str(getattr(snapshot, "account_source", "") or "").strip().lower()
        if confidence and confidence not in {"high", "medium"}:
            return False
        if source == "content_list":
            return False
        return snapshot.status in {"ready", "partial"}

    @staticmethod
    def _should_keep_last_trusted(snapshot: WeChatHomeSnapshot) -> bool:
        return snapshot.status in {"content_unreadable", "not_found", "failed", "dependency_missing"}

    def _build_cached_snapshot(self, current: WeChatHomeSnapshot) -> WeChatHomeSnapshot:
        cached = self._last_trusted
        if cached is None:
            return self._build_unavailable_snapshot(current)
        return WeChatHomeSnapshot(
            status="display_cached",
            status_label=DISPLAY_CACHED_STATUS_LABEL,
            account_name=cached.account_name,
            description=cached.description,
            original_count=cached.original_count,
            friend_follow_count=cached.friend_follow_count,
            found=False,
            message=DISPLAY_REFERENCE_MESSAGE,
            account_confidence="display_cache",
            account_source="display_cache",
            visible_tabs=cached.visible_tabs,
        )

    @staticmethod
    def _build_unavailable_snapshot(current: WeChatHomeSnapshot) -> WeChatHomeSnapshot:
        return WeChatHomeSnapshot(
            status="display_unavailable",
            status_label=DISPLAY_UNAVAILABLE_STATUS_LABEL,
            account_name="未读取到可信公众号名",
            description=DISPLAY_REFERENCE_MESSAGE,
            original_count="暂不可读",
            friend_follow_count="暂不可读",
            found=False,
            message=current.message or current.description,
            account_confidence="none",
            account_source="display_unavailable",
            visible_tabs=getattr(current, "visible_tabs", ()),
        )


__all__ = [
    "DISPLAY_CACHED_STATUS_LABEL",
    "DISPLAY_REFERENCE_MESSAGE",
    "DISPLAY_UNAVAILABLE_STATUS_LABEL",
    "HomeDisplayCache",
]

from __future__ import annotations

import ctypes
import json
import platform
import sys
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from src.core.config import PROJECT_ROOT, TMP_DIR
from src.workers.home_article_clicker import collect_article_click_targets
from src.workers.home_article_clicker import serialize_article_click_targets
from src.workers.wechat_home import _collect_best_wechat_texts
from src.workers.wechat_home import detect_wechat_home_window
from src.workers.wechat_home import parse_wechat_home_text


CONFIG = {
    # 诊断脚本只读取窗口，不点击、不滚动、不关闭任何微信窗口。
    "output_dir": str(TMP_DIR / "wechat_home_probe"),
    "max_depth": 14,
    "max_nodes_per_window": 6000,
    "max_nodes_per_child_window": 2500,
    "max_child_windows": 80,
    "max_top_windows_in_report": 120,
    "max_unique_texts_in_report": 1200,
    "max_tree_nodes_in_report": 2500,
    "include_non_wechat_top_windows": True,
}

WECHAT_PROCESS_NAMES = {"wechat.exe", "wechatappex.exe", "weixin.exe"}
WINDOW_TITLE_KEYWORDS = ("微信", "公众号", "服务号")


@dataclass(frozen=True)
class UiaNodeSnapshot:
    depth: int
    path: str
    name: str
    value: str
    control_type: str
    class_name: str
    automation_id: str
    hwnd: int
    rect: tuple[int, int, int, int]


def main() -> None:
    output_dir = Path(str(CONFIG["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = probe_wechat_home_windows(output_dir=output_dir, timestamp=timestamp)
    output_path = output_dir / f"wechat_home_probe_{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps(_build_console_summary(report, output_path), ensure_ascii=False, indent=2))


def probe_wechat_home_windows(*, output_dir: Path, timestamp: str) -> dict[str, Any]:
    if platform.system() != "Windows":
        return {
            "ok": False,
            "status": "unsupported_platform",
            "message": "当前脚本只支持 Windows UI Automation。",
            "platform": platform.platform(),
        }

    try:
        import uiautomation as auto
    except Exception as exc:
        return {
            "ok": False,
            "status": "uiautomation_unavailable",
            "message": f"无法导入 uiautomation：{exc}",
            "platform": platform.platform(),
        }

    root = _safe_call(auto.GetRootControl)
    if root is None:
        return {"ok": False, "status": "root_unavailable", "message": "无法读取 UIA RootControl。"}

    top_windows = _safe_call(root.GetChildren) or []
    top_window_summaries: list[dict[str, Any]] = []
    wechat_reports: list[dict[str, Any]] = []

    for index, window in enumerate(top_windows, 1):
        summary = _summarize_window(window, index=index)
        if bool(CONFIG.get("include_non_wechat_top_windows")) and len(top_window_summaries) < int(
            CONFIG["max_top_windows_in_report"]
        ):
            top_window_summaries.append(summary)

        if not _looks_like_wechat_candidate(summary):
            continue

        window_report = _probe_one_wechat_window(
            auto,
            window,
            summary=summary,
            output_dir=output_dir,
            timestamp=timestamp,
            index=len(wechat_reports) + 1,
        )
        wechat_reports.append(window_report)

    detected_snapshot = detect_wechat_home_window(activate=False).to_dict()
    return {
        "ok": True,
        "status": "ok",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "platform": platform.platform(),
        "detected_snapshot": detected_snapshot,
        "wechat_window_count": len(wechat_reports),
        "wechat_windows": wechat_reports,
        "top_windows": top_window_summaries,
        "notes": [
            "best_texts 来自当前正式读取策略，可直接判断服务号主页是否暴露正文文本。",
            "tree_nodes 和 child_window_scans 用于定位服务号窗口真实内容藏在哪个子 HWND 或控件层级。",
            "article_targets 是当前点击文章模块识别到的候选标题，不代表脚本执行了点击。",
        ],
    }


def _probe_one_wechat_window(
    auto: Any,
    window: Any,
    *,
    summary: dict[str, Any],
    output_dir: Path,
    timestamp: str,
    index: int,
) -> dict[str, Any]:
    max_depth = int(CONFIG["max_depth"])
    max_nodes = int(CONFIG["max_nodes_per_window"])

    tree_nodes = _walk_uia_tree(window, max_depth=max_depth, max_nodes=max_nodes)
    tree_texts = _unique_texts_from_nodes(tree_nodes)
    tree_snapshot = parse_wechat_home_text("\n".join(tree_texts)).to_dict()

    best_texts = _collect_best_wechat_texts(
        window,
        max_depth=max_depth,
        max_nodes=max_nodes,
        control_from_handle=auto.ControlFromHandle,
    )
    best_snapshot = parse_wechat_home_text("\n".join(best_texts)).to_dict()

    article_targets = collect_article_click_targets(
        window,
        max_depth=max_depth,
        max_nodes=max_nodes,
        control_from_handle=auto.ControlFromHandle,
        child_hwnds_provider=_enumerate_child_window_handles,
    )

    child_window_scans = _probe_child_windows(
        auto,
        parent_hwnd=int(summary.get("hwnd") or 0),
        output_dir=output_dir,
        timestamp=timestamp,
        window_index=index,
    )

    text_path = output_dir / f"wechat_home_probe_{timestamp}_window_{index:02d}_best_texts.txt"
    tree_path = output_dir / f"wechat_home_probe_{timestamp}_window_{index:02d}_tree.json"
    text_path.write_text("\n".join(best_texts), encoding="utf-8")
    tree_path.write_text(
        json.dumps([asdict(node) for node in tree_nodes], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return {
        **summary,
        "best_snapshot": best_snapshot,
        "tree_snapshot": tree_snapshot,
        "best_text_count": len(best_texts),
        "unique_tree_text_count": len(tree_texts),
        "best_texts": best_texts[: int(CONFIG["max_unique_texts_in_report"])],
        "tree_texts": tree_texts[: int(CONFIG["max_unique_texts_in_report"])],
        "tree_node_count": len(tree_nodes),
        "tree_nodes": [asdict(node) for node in tree_nodes[: int(CONFIG["max_tree_nodes_in_report"])]],
        "article_targets": serialize_article_click_targets(article_targets, limit=30),
        "child_window_scans": child_window_scans,
        "best_texts_path": str(text_path),
        "tree_path": str(tree_path),
    }


def _probe_child_windows(
    auto: Any,
    *,
    parent_hwnd: int,
    output_dir: Path,
    timestamp: str,
    window_index: int,
) -> list[dict[str, Any]]:
    if parent_hwnd <= 0:
        return []

    child_reports: list[dict[str, Any]] = []
    for child_index, child_hwnd in enumerate(_enumerate_child_window_handles(parent_hwnd), 1):
        if child_index > int(CONFIG["max_child_windows"]):
            break
        control = _safe_call(auto.ControlFromHandle, child_hwnd)
        if control is None:
            child_reports.append({"index": child_index, "hwnd": child_hwnd, "status": "control_unavailable"})
            continue

        nodes = _walk_uia_tree(
            control,
            max_depth=int(CONFIG["max_depth"]),
            max_nodes=int(CONFIG["max_nodes_per_child_window"]),
        )
        texts = _unique_texts_from_nodes(nodes)
        snapshot = parse_wechat_home_text("\n".join(texts)).to_dict()
        child_text_path = output_dir / (
            f"wechat_home_probe_{timestamp}_window_{window_index:02d}_child_{child_index:02d}_texts.txt"
        )
        child_text_path.write_text("\n".join(texts), encoding="utf-8")
        child_reports.append(
            {
                "index": child_index,
                "hwnd": child_hwnd,
                "node_count": len(nodes),
                "text_count": len(texts),
                "snapshot": snapshot,
                "texts": texts[:120],
                "texts_path": str(child_text_path),
            }
        )
    return child_reports


def _walk_uia_tree(control: Any, *, max_depth: int, max_nodes: int) -> list[UiaNodeSnapshot]:
    nodes: list[UiaNodeSnapshot] = []
    queue: deque[tuple[Any, int, str]] = deque([(control, 0, "0")])

    while queue and len(nodes) < max_nodes:
        current, depth, path = queue.popleft()
        nodes.append(
            UiaNodeSnapshot(
                depth=depth,
                path=path,
                name=str(_safe_get(current, "Name", "") or "").strip(),
                value=str(_safe_get(current, "Value", "") or "").strip(),
                control_type=str(_safe_get(current, "ControlTypeName", "") or "").strip(),
                class_name=str(_safe_get(current, "ClassName", "") or "").strip(),
                automation_id=str(_safe_get(current, "AutomationId", "") or "").strip(),
                hwnd=_safe_int(_safe_get(current, "NativeWindowHandle", 0)),
                rect=_rect_to_tuple(_safe_get(current, "BoundingRectangle", None)),
            )
        )
        if depth >= max_depth:
            continue
        children = _safe_call(current.GetChildren) or []
        for child_index, child in enumerate(children):
            if len(nodes) + len(queue) >= max_nodes:
                break
            queue.append((child, depth + 1, f"{path}.{child_index}"))
    return nodes


def _summarize_window(window: Any, *, index: int) -> dict[str, Any]:
    process_id = _safe_int(_safe_get(window, "ProcessId", 0))
    return {
        "index": index,
        "name": str(_safe_get(window, "Name", "") or "").strip(),
        "class_name": str(_safe_get(window, "ClassName", "") or "").strip(),
        "control_type": str(_safe_get(window, "ControlTypeName", "") or "").strip(),
        "hwnd": _safe_int(_safe_get(window, "NativeWindowHandle", 0)),
        "process_id": process_id,
        "process_name": _get_process_name(process_id),
        "rect": _rect_to_tuple(_safe_get(window, "BoundingRectangle", None)),
    }


def _looks_like_wechat_candidate(summary: dict[str, Any]) -> bool:
    name = str(summary.get("name") or "").strip()
    class_name = str(summary.get("class_name") or "").lower()
    process_name = str(summary.get("process_name") or "").lower()
    lower_name = name.lower()

    if "access wechat article" in lower_name or "visual studio code" in lower_name:
        return False
    if process_name in WECHAT_PROCESS_NAMES:
        return True
    if any(keyword in name for keyword in WINDOW_TITLE_KEYWORDS):
        return True
    return "chrome_widgetwin" in class_name and "wechat" in process_name


def _unique_texts_from_nodes(nodes: list[UiaNodeSnapshot]) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        for value in (node.name, node.value):
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            texts.append(text)
    return texts


def _enumerate_child_window_handles(parent_hwnd: int) -> list[int]:
    if parent_hwnd <= 0 or platform.system() != "Windows":
        return []

    user32 = ctypes.windll.user32
    child_hwnds: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        child_hwnds.append(int(hwnd))
        return True

    user32.EnumChildWindows(int(parent_hwnd), enum_proc(callback), 0)
    return child_hwnds


def _get_process_name(process_id: int) -> str:
    if process_id <= 0:
        return ""
    try:
        import psutil

        return str(psutil.Process(process_id).name() or "")
    except Exception:
        return _get_process_name_via_windows_api(process_id)


def _get_process_name_via_windows_api(process_id: int) -> str:
    if platform.system() != "Windows":
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(process_id))
    if not handle:
        return ""
    try:
        buffer_size = ctypes.c_ulong(4096)
        buffer = ctypes.create_unicode_buffer(buffer_size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(buffer_size))
        if not ok:
            return ""
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)


def _rect_to_tuple(rect: Any) -> tuple[int, int, int, int]:
    if isinstance(rect, (list, tuple)) and len(rect) == 4:
        return tuple(_safe_int(item) for item in rect)
    for names in (("left", "top", "right", "bottom"), ("Left", "Top", "Right", "Bottom")):
        values = [_safe_get(rect, name, None) for name in names]
        if all(value is not None for value in values):
            return tuple(_safe_int(item) for item in values)
    return (0, 0, 0, 0)


def _safe_get(obj: Any, attr_name: str, default: Any = "") -> Any:
    try:
        return getattr(obj, attr_name)
    except Exception:
        return default


def _safe_call(func: Any, *args: Any) -> Any:
    try:
        return func(*args)
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _build_console_summary(report: dict[str, Any], output_path: Path) -> dict[str, Any]:
    window_summaries = []
    for item in report.get("wechat_windows") or []:
        window_summaries.append(
            {
                "index": item.get("index"),
                "name": item.get("name"),
                "process_name": item.get("process_name"),
                "best_snapshot": item.get("best_snapshot"),
                "best_text_count": item.get("best_text_count"),
                "article_target_count": len(item.get("article_targets") or []),
                "best_texts_path": item.get("best_texts_path"),
            }
        )
    return {
        "ok": report.get("ok"),
        "status": report.get("status"),
        "wechat_window_count": report.get("wechat_window_count"),
        "detected_snapshot": report.get("detected_snapshot"),
        "windows": window_summaries,
        "output_path": str(output_path),
    }


if __name__ == "__main__":
    main()

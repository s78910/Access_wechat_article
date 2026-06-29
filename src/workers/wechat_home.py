from __future__ import annotations

import ctypes
import platform
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from src.modules.window.wechat_home_window_finder import is_wechat_home_window_candidate
from src.workers.wechat_window_activation import activate_wechat_window_for_uia


WECHAT_PROCESS_NAMES = {"wechat.exe", "wechatappex.exe", "weixin.exe"}
HOME_NAVIGATION_TABS = ("全部", "贴图", "文章", "视频号")


@dataclass(frozen=True)
class WeChatHomeSnapshot:
    """公众号主页窗口识别结果，用于主服务页运行状态区展示。"""

    status: str
    status_label: str
    account_name: str
    description: str
    original_count: str
    friend_follow_count: str
    found: bool = False
    message: str = ""
    account_confidence: str = "none"
    account_source: str = ""
    visible_tabs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "statusLabel": self.status_label,
            "accountName": self.account_name,
            "description": self.description,
            "originalCount": self.original_count,
            "friendFollowCount": self.friend_follow_count,
            "found": self.found,
            "message": self.message,
            "accountConfidence": self.account_confidence,
            "accountSource": self.account_source,
            "visibleTabs": list(self.visible_tabs),
        }


@dataclass(frozen=True)
class _UiaTextNode:
    """UIA 控件节点的最小文本快照，用于判断窗口正文是否可读。"""

    name: str
    value: str
    control_type: str
    class_name: str
    hwnd: int


@dataclass(frozen=True)
class _HomeTextSections:
    """把主页文本按“头部资料区 / 菜单区 / 内容区”切开，避免内容卡片污染账号识别。"""

    header_lines: list[str]
    menu_lines: list[str]
    content_lines: list[str]
    visible_tabs: tuple[str, ...]


DEFAULT_WECHAT_HOME_SNAPSHOT = WeChatHomeSnapshot(
    status="pending",
    status_label="待准备",
    account_name="等待识别，请先打开微信 PC 端公众号主页",
    description="点击开始运行后，将从桌面主页窗口读取",
    original_count="待获取",
    friend_follow_count="待获取",
    found=False,
)


def detect_wechat_home_window(*, activate: bool = False) -> WeChatHomeSnapshot:
    """尝试读取微信 PC 端公众号主页窗口；依赖缺失时返回可展示的明确状态。"""
    if platform.system() != "Windows":
        return _not_found_snapshot("当前系统不是 Windows，暂无法捕捉微信 PC 主页窗口")

    try:
        return _detect_with_uiautomation(activate=activate)
    except ModuleNotFoundError:
        return _detect_with_window_titles()
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


def parse_wechat_home_text(text: str) -> WeChatHomeSnapshot:
    """从窗口文本中提取公众号名称、简介、原创数量和朋友关注数量。"""
    lines = _normalize_lines(text.splitlines())
    sections = _split_home_text_sections(lines)
    profile_lines = sections.header_lines if sections.menu_lines else lines
    if sections.content_lines and not sections.menu_lines:
        profile_lines = sections.header_lines
    account_name = _pick_account_name_from_header(profile_lines)
    if not account_name and not sections.menu_lines:
        account_name = _pick_account_name(profile_lines)
    description = _pick_description_from_header(profile_lines, account_name)
    if not description and not sections.menu_lines:
        description = _pick_description(profile_lines, account_name)
    content_profile_lines = _profile_lines_from_menu_content(sections.content_lines)
    if content_profile_lines:
        content_account_name = _pick_account_name_from_header(content_profile_lines)
        if not content_account_name:
            content_account_name = _pick_video_channel_name(content_profile_lines)
        if content_account_name and (not account_name or _is_generic_home_window_title(account_name)):
            account_name = content_account_name

        content_description = _pick_description_from_header(content_profile_lines, account_name)
        if not content_description:
            content_description = _pick_description(content_profile_lines, account_name)
        if content_description and not description:
            description = content_description
    original_count = _extract_first_match(
        profile_lines,
        (
            r"(\d+)\s*篇原创",
            r"原创(?:文章)?[^\d]*(\d+)",
            r"(\d+)\s*(?:篇)?\s*原创",
        ),
    )
    if not original_count and content_profile_lines:
        original_count = _extract_first_match(
            content_profile_lines,
            (
                r"(\d+)\s*篇原创",
                r"原创(?:文章)?[^\d]*(\d+)",
                r"(\d+)\s*(?:篇)?\s*原创",
            ),
        )
    friend_follow_count = _extract_first_match(
        profile_lines,
        (
            r"(\d+)\s*(?:个)?朋友.*关注",
            r"朋友关注[^\d]*(\d+)",
        ),
    )
    if not friend_follow_count and content_profile_lines:
        friend_follow_count = _extract_first_match(
            content_profile_lines,
            (
                r"(\d+)\s*(?:个)?朋友.*关注",
                r"朋友关注[^\d]*(\d+)",
            ),
        )

    found = bool(account_name)
    has_content_list = bool(sections.content_lines) or _looks_like_scrolled_article_list(lines)
    is_partial = found and (has_content_list or bool(sections.menu_lines)) and not (
        description or original_count or friend_follow_count
    )
    if found:
        account_confidence = "high" if sections.menu_lines else "medium"
        account_source = "profile_header" if sections.menu_lines else "profile_text"
        status = "partial" if is_partial else "ready"
        status_label = "主页局部信息已获取" if is_partial else "主页信息已获取"
        message = ""
    elif has_content_list:
        account_confidence = "low"
        account_source = "content_list"
        status = "content_only"
        status_label = "已读取主页内容列表"
        message = "当前 UIA 文本只包含菜单和内容列表，未从主页头部识别到可信公众号名称"
    else:
        account_confidence = "none"
        account_source = ""
        status = "not_found"
        status_label = "未检测到主页窗口"
        message = ""

    return WeChatHomeSnapshot(
        status=status,
        status_label=status_label,
        account_name=account_name or "未识别到主页公众号名称",
        description="未识别到主页简介" if is_partial else (description or "未识别到主页简介"),
        original_count=original_count or ("无" if found else "未识别到"),
        friend_follow_count=friend_follow_count or ("无" if found else "未识别到"),
        found=found,
        message=message,
        account_confidence=account_confidence,
        account_source=account_source,
        visible_tabs=sections.visible_tabs,
    )


def _detect_with_uiautomation(
    auto_module: Any | None = None,
    *,
    activate: bool = False,
) -> WeChatHomeSnapshot:
    if auto_module is None:
        import uiautomation as auto_module

    root = auto_module.GetRootControl()
    windows = root.GetChildren()
    matched_window = False
    for window in windows:
        name = str(getattr(window, "Name", "") or "")
        class_name = str(getattr(window, "ClassName", "") or "")
        process_name = _get_process_name(_safe_int(getattr(window, "ProcessId", 0) or 0))
        if not _looks_like_wechat_window(name, class_name, process_name):
            continue

        matched_window = True
        if activate:
            activate_wechat_window_for_uia(window)
        texts = _collect_best_wechat_texts(
            window,
            max_depth=14,
            max_nodes=6000,
            control_from_handle=auto_module.ControlFromHandle,
        )
        snapshot = parse_wechat_home_text("\n".join(texts))
        if snapshot.found:
            return snapshot

    if matched_window:
        return _window_content_unreadable_snapshot()

    return _not_found_snapshot("未检测到已打开的微信 PC 公众号主页窗口")


def _detect_with_window_titles() -> WeChatHomeSnapshot:
    titles = _enumerate_window_titles()
    wechat_titles = [
        title
        for title in titles
        if str(title or "").strip() in {"公众号", "服务号", "订阅号"} or "微信公众号" in str(title or "")
    ]
    if not wechat_titles:
        return _not_found_snapshot("未检测到已打开的微信 PC 公众号主页窗口")

    return WeChatHomeSnapshot(
        status="dependency_missing",
        status_label="未检测到主页窗口",
        account_name="检测到微信窗口，但无法读取主页内容",
        description="当前环境缺少 uiautomation 依赖，暂不能自动提取公众号名称和简介",
        original_count="未识别到",
        friend_follow_count="未识别到",
        found=False,
        message="请安装 uiautomation 后重试桌面主页窗口识别",
    )


def _collect_best_wechat_texts(
    control,
    *,
    max_depth: int = 14,
    max_nodes: int = 6000,
    control_from_handle=None,
    child_hwnds_provider=None,
) -> list[str]:
    """读取微信窗口文本；顶层只暴露外壳时，继续从 Win32 子窗口兜底读取正文。"""
    best_nodes = _walk_uia_text_tree(control, max_depth=max_depth, max_nodes=max_nodes)

    if _looks_like_shell_only(best_nodes):
        parent_hwnd = _safe_int(_safe_get(control, "NativeWindowHandle", 0))
        get_control = control_from_handle or _control_from_handle
        get_child_hwnds = child_hwnds_provider or _enumerate_child_window_handles

        remaining_nodes = max(1, max_nodes - len(best_nodes))
        for child_hwnd in get_child_hwnds(parent_hwnd):
            if child_hwnd == parent_hwnd:
                continue

            child_control = _safe_call(get_control, child_hwnd)
            if child_control is None:
                continue

            child_nodes = _walk_uia_text_tree(
                child_control,
                max_depth=max_depth,
                max_nodes=remaining_nodes,
            )
            if _tree_quality_score(child_nodes) > _tree_quality_score(best_nodes):
                best_nodes = child_nodes
            if not _looks_like_shell_only(best_nodes):
                break

    return _texts_from_uia_nodes(best_nodes)


def _walk_uia_text_tree(control, *, max_depth: int, max_nodes: int) -> list[_UiaTextNode]:
    """广度优先读取 UIA 控件树，限制深度和节点数，避免微信内嵌页面读取卡死。"""
    if control is None or max_depth < 0 or max_nodes <= 0:
        return []

    nodes: list[_UiaTextNode] = []
    queue = deque([(control, 0)])

    while queue and len(nodes) < max_nodes:
        current, depth = queue.popleft()
        nodes.append(
            _UiaTextNode(
                name=str(_safe_get(current, "Name", "") or "").strip(),
                value=str(_safe_get(current, "Value", "") or "").strip(),
                control_type=str(_safe_get(current, "ControlTypeName", "") or "").strip(),
                class_name=str(_safe_get(current, "ClassName", "") or "").strip(),
                hwnd=_safe_int(_safe_get(current, "NativeWindowHandle", 0)),
            )
        )

        if depth >= max_depth:
            continue

        children = _safe_call(current.GetChildren)
        if not children:
            continue

        for child in children:
            if len(nodes) + len(queue) >= max_nodes:
                break
            queue.append((child, depth + 1))

    return nodes


def _collect_uia_texts(control, max_depth: int) -> list[str]:
    if max_depth < 0:
        return []

    values: list[str] = []
    for attr in ("Name", "Value"):
        value = str(getattr(control, attr, "") or "").strip()
        if value:
            values.append(value)

    try:
        children = control.GetChildren()
    except Exception:
        children = []

    for child in children:
        values.extend(_collect_uia_texts(child, max_depth - 1))

    return _normalize_lines(values)


def _texts_from_uia_nodes(nodes: list[_UiaTextNode]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        values.append(node.name)
        values.append(node.value)
    return _normalize_lines(values)


def _looks_like_shell_only(nodes: list[_UiaTextNode]) -> bool:
    if not nodes:
        return True
    texts = _texts_from_uia_nodes(nodes)
    if any(_looks_like_page_text(text) for text in texts):
        return False
    has_document = any(node.control_type == "DocumentControl" for node in nodes)
    return len(nodes) <= 40 or not has_document


def _tree_quality_score(nodes: list[_UiaTextNode]) -> int:
    texts = _texts_from_uia_nodes(nodes)
    page_hits = sum(1 for text in texts if _looks_like_page_text(text))
    named_nodes = sum(1 for node in nodes if node.name or node.value)
    document_hits = sum(1 for node in nodes if node.control_type == "DocumentControl")
    return page_hits * 10000 + document_hits * 1000 + named_nodes * 10 + len(nodes)


def _looks_like_page_text(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "原创内容",
            "朋友关注",
            "篇原创",
            "发消息",
            "已关注",
            "阅读",
            "今天",
            "昨天",
        )
    )


def _enumerate_window_titles() -> list[str]:
    user32 = ctypes.windll.user32
    titles: list[str] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            titles.append(title)
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return titles


def _enumerate_child_window_handles(parent_hwnd: int) -> list[int]:
    """枚举指定窗口下的 Win32 子窗口句柄，用于从内嵌渲染窗口读取 UIA 树。"""
    if parent_hwnd <= 0:
        return []

    user32 = ctypes.windll.user32
    child_hwnds: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        child_hwnds.append(int(hwnd))
        return True

    user32.EnumChildWindows(parent_hwnd, enum_proc(callback), 0)
    return child_hwnds


def _control_from_handle(hwnd: int):
    try:
        import uiautomation as auto

        return auto.ControlFromHandle(hwnd)
    except Exception:
        return None


def _safe_get(obj, attr_name: str, default=""):
    try:
        return getattr(obj, attr_name)
    except Exception:
        return default


def _safe_call(func, *args):
    try:
        return func(*args)
    except Exception:
        return None


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _get_process_name(process_id: int) -> str:
    if process_id <= 0:
        return ""
    try:
        import psutil

        return str(psutil.Process(process_id).name() or "")
    except Exception:
        return ""


def _looks_like_wechat_window(name: str, class_name: str, process_name: str = "") -> bool:
    return is_wechat_home_window_candidate(name, class_name, process_name)


def _not_found_snapshot(message: str) -> WeChatHomeSnapshot:
    return WeChatHomeSnapshot(
        status="not_found",
        status_label="未检测到主页窗口",
        account_name="未检测到微信 PC 公众号主页",
        description=message,
        original_count="未识别到",
        friend_follow_count="未识别到",
        found=False,
        message=message,
    )


def _window_content_unreadable_snapshot() -> WeChatHomeSnapshot:
    return WeChatHomeSnapshot(
        status="content_unreadable",
        status_label="已检测到主页窗口",
        account_name="已检测到公众号窗口，但无法读取主页内容",
        description="微信窗口当前未向 Windows UI Automation 暴露公众号主页正文，暂不能自动提取公众号名称和简介",
        original_count="未识别到",
        friend_follow_count="未识别到",
        found=False,
        message="已检测到公众号窗口，但未读取到可解析的主页文本",
    )


def _normalize_lines(lines: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        normalized.append(text)
    return normalized


def _split_home_text_sections(lines: list[str]) -> _HomeTextSections:
    menu_start = _find_primary_menu_start(lines)
    if menu_start < 0:
        content_start = _find_content_start_without_menu(lines)
        if content_start > 0:
            return _HomeTextSections(
                header_lines=lines[:content_start],
                menu_lines=[],
                content_lines=lines[content_start:],
                visible_tabs=(),
            )
        return _HomeTextSections(
            header_lines=lines,
            menu_lines=[],
            content_lines=[],
            visible_tabs=(),
        )

    menu_end = menu_start
    menu_lines: list[str] = []
    while menu_end < len(lines) and lines[menu_end] in HOME_NAVIGATION_TABS:
        menu_lines.append(lines[menu_end])
        menu_end += 1

    visible_tabs: list[str] = []
    for line in menu_lines:
        if line not in visible_tabs:
            visible_tabs.append(line)

    return _HomeTextSections(
        header_lines=lines[:menu_start],
        menu_lines=menu_lines,
        content_lines=lines[menu_end:],
        visible_tabs=tuple(visible_tabs),
    )


def _find_content_start_without_menu(lines: list[str]) -> int:
    """无菜单文本时，用第一条阅读/赞指标反推内容卡片起点，避免贴图标题污染主页资料。"""
    for index, line in enumerate(lines):
        if not _is_article_metric_line(line):
            continue
        if index <= 0:
            return -1

        content_start = index - 1
        if content_start - 1 >= 0 and _is_content_group_prefix_line(lines[content_start - 1]):
            content_start -= 1
        return content_start if content_start > 0 else -1
    return -1


def _is_content_group_prefix_line(line: str) -> bool:
    return line in {"今天", "昨天", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"} or _is_profile_date_line(line)


def _find_primary_menu_start(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line not in HOME_NAVIGATION_TABS:
            continue
        nearby_tabs = [item for item in lines[index : index + len(HOME_NAVIGATION_TABS) + 1] if item in HOME_NAVIGATION_TABS]
        if "全部" in nearby_tabs and len(set(nearby_tabs)) >= 2:
            return index
    return -1


def _profile_lines_from_menu_content(lines: list[str]) -> list[str]:
    """服务号 UIA 文本常把资料区排在菜单之后；只截取文章列表之前的资料片段。"""
    profile_lines: list[str] = []
    seen_profile_signal = False

    for line in lines:
        if line == "展开" or _is_profile_action_line(line) or _is_content_group_prefix_line(line):
            break
        if line == "正在加载..." and not seen_profile_signal:
            continue
        if _is_profile_stat_line(line) or re.search(r"^视频号\s*[:：]", line):
            seen_profile_signal = True
        elif seen_profile_signal and _is_profile_candidate_line(line):
            seen_profile_signal = True
        if seen_profile_signal:
            profile_lines.append(line)

    return profile_lines


def _pick_video_channel_name(lines: list[str]) -> str:
    for line in lines:
        match = re.search(r"^视频号\s*[:：]\s*(?P<name>.+?)\s*$", line)
        if not match:
            continue
        name = match.group("name").strip()
        if name and _looks_like_account_name(name):
            return name
    return ""


def _pick_account_name_from_header(lines: list[str]) -> str:
    candidates = [
        line
        for line in lines
        if _is_profile_candidate_line(line)
        and not _is_header_control_noise(line)
        and not _is_navigation_noise_line(line)
    ]
    for line in candidates:
        if _looks_like_account_name(line):
            return line
    return ""


def _pick_description_from_header(lines: list[str], account_name: str) -> str:
    skipped_account_name = False
    for line in lines:
        if line == account_name and not skipped_account_name:
            skipped_account_name = True
            continue
        if _is_header_control_noise(line) or _is_profile_noise(line) or _is_navigation_noise_line(line):
            continue
        if re.search(r"\d", line) and ("原创" in line or "朋友" in line or "关注" in line):
            continue
        if _looks_like_description(line):
            return line
    return ""


def _is_header_control_noise(line: str) -> bool:
    return line in {
        "公众号",
        "服务号",
        "微信",
        "Weixin",
        "WeChat",
        "搜索",
        "更多",
        "···",
        "...",
        "…",
        "最小化",
        "最大化",
        "关闭",
    }


def _pick_account_name(lines: list[str]) -> str:
    for candidate_lines in _profile_candidate_line_groups(lines):
        for line in candidate_lines:
            if _is_profile_noise(line):
                continue
            return line
    return ""


def _pick_description(lines: list[str], account_name: str) -> str:
    if _looks_like_scrolled_article_list(lines):
        return ""

    for candidate_lines in _profile_candidate_line_groups(lines):
        skipped_account_name = False
        for line in candidate_lines:
            if line == account_name and not skipped_account_name:
                skipped_account_name = True
                continue
            if _is_profile_noise(line):
                continue
            if re.search(r"\d", line) and ("原创" in line or "朋友" in line or "关注" in line):
                continue
            return line
    return ""


def _profile_candidate_line_groups(lines: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    stats_group = _profile_group_around_stats(lines)
    if stats_group:
        groups.append(stats_group)

    if _looks_like_scrolled_article_list(lines):
        title_group = _profile_group_from_scrolled_article_list(lines)
        if title_group:
            groups.append(title_group)
        return groups

    start_index = _profile_text_start_index(lines)
    end_index = _profile_description_end_index(lines, start_index)
    if start_index <= 0 and end_index >= len(lines) and not groups:
        return [lines]

    if start_index < end_index:
        groups.append(lines[start_index:end_index])
    if len(lines) > start_index:
        groups.append(lines[start_index:])
    groups.append(lines)
    return groups


def _profile_group_from_scrolled_article_list(lines: list[str]) -> list[str]:
    for line in lines:
        if _is_profile_candidate_line(line):
            return [line]
    return []


def _looks_like_scrolled_article_list(lines: list[str]) -> bool:
    if any(_is_profile_stat_line(line) for line in lines):
        return False

    has_article_tab = any(line in {"文章", "全部", "贴图"} for line in lines)
    has_article_date = any(_is_profile_date_line(line) for line in lines)
    has_article_metric = any(_is_article_metric_line(line) for line in lines)
    return has_article_tab and (has_article_date or has_article_metric)


def _is_navigation_noise_line(line: str) -> bool:
    return line in {"全部", "贴图", "文章", "视频号", "置顶", "展开"}


def _is_generic_home_window_title(line: str) -> bool:
    return line in {"公众号", "服务号", "微信"}


def _profile_group_around_stats(lines: list[str]) -> list[str]:
    """兼容账号名在统计前、简介在统计后的微信主页文本顺序。"""
    stat_index = -1
    for index, line in enumerate(lines):
        if _is_profile_stat_line(line):
            stat_index = index
            break

    if stat_index < 0:
        return []

    stat_end_index = stat_index
    while stat_end_index + 1 < len(lines) and _is_profile_stat_line(lines[stat_end_index + 1]):
        stat_end_index += 1

    pre_candidates = [
        line
        for line in lines[max(0, stat_index - 8) : stat_index]
        if _is_profile_candidate_line(line) and not _is_navigation_noise_line(line)
    ]
    post_candidates = _profile_candidates_after_stats(lines, stat_end_index + 1)

    if pre_candidates and post_candidates:
        return [pre_candidates[-1], post_candidates[0]]
    if len(pre_candidates) >= 2:
        return pre_candidates[-2:]
    if not pre_candidates and len(post_candidates) >= 2:
        ordered = _reorder_profile_candidates(post_candidates)
        if ordered:
            return ordered
    if pre_candidates:
        return [pre_candidates[-1]]
    if post_candidates:
        return [post_candidates[0]]
    return []


def _reorder_profile_candidates(lines: list[str]) -> list[str]:
    if not lines:
        return []

    first = lines[0]
    for candidate in lines[1:]:
        if _looks_like_account_name(candidate) and _looks_like_description(first):
            return [candidate, first]

    if len(lines) >= 2:
        return lines[:2]
    return [first]


def _profile_candidates_after_stats(lines: list[str], start_index: int) -> list[str]:
    candidates: list[str] = []
    for line in lines[start_index:]:
        if _is_article_content_line(line):
            if candidates:
                break
            continue
        if _is_profile_candidate_line(line):
            candidates.append(line)
            if len(candidates) >= 4:
                break
    return candidates


def _profile_text_start_index(lines: list[str]) -> int:
    """公众号资料通常紧跟原创/朋友关注统计和视频号文本，列表区内容需要跳过。"""
    for index, line in enumerate(lines):
        if _is_profile_stat_line(line):
            return min(len(lines), index + 1)
    return 0


def _profile_description_end_index(lines: list[str], start_index: int) -> int:
    for index in range(start_index, len(lines)):
        line = lines[index]
        if _is_profile_action_line(line):
            return index
    return len(lines)


def _is_profile_candidate_line(line: str) -> bool:
    return bool(line) and not _is_profile_noise(line)


def _is_profile_stat_line(line: str) -> bool:
    patterns = (
        r"\d+\s*篇原创",
        r"原创(?:文章|内容)?[^\d]*(\d+)",
        r"\d+\s*个朋友.*关注",
        r"朋友关注[^\d]*(\d+)",
    )
    return any(re.search(pattern, line) for pattern in patterns)


def _is_profile_action_line(line: str) -> bool:
    return line in {"已关注", "发消息", "关注", "取消关注"}


def _is_profile_date_line(line: str) -> bool:
    return bool(re.search(r"^(?:\d{4}年)?\d{1,2}月\d{1,2}日$", line))


def _is_article_metric_line(line: str) -> bool:
    return bool(re.search(r"阅读\s*[\d.]+(?:万)?\s*赞\s*\d+", line))


def _is_article_content_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    if _is_article_metric_line(text):
        return True
    return len(text) >= 18 and any(char in text for char in "，。！？!?")


def _looks_like_account_name(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    if len(text) > 18:
        return False
    if any(punct in text for punct in "。！？!?，,；;：:"):
        return False
    return True


def _looks_like_description(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    if any(punct in text for punct in "。！？!?"):
        return True
    return len(text) >= 14


def _is_profile_noise(line: str) -> bool:
    if _is_profile_date_line(line) or _is_profile_action_line(line) or _is_profile_stat_line(line):
        return True

    noise_keywords = {
        "公众号",
        "服务号",
        "微信",
        "Weixin",
        "WeChat",
        "MMUIRenderSubWindowHW",
        "系统",
        "最小化",
        "最大化",
        "还原",
        "关闭",
        "发消息",
        "进入公众号",
        "关注",
        "取消关注",
        "消息",
        "服务",
        "文章",
        "视频",
        "视频号",
        "全部",
        "贴图",
        "正在加载...",
        "已关注",
        "今天",
        "昨天",
        "置顶",
        "展开",
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
    }
    if line in noise_keywords:
        return True
    if re.search(r"^视频号\s*[:：]", line):
        return True
    if re.search(r"^\d+个内容$", line):
        return True
    if re.search(r"^\d+月\d+日$", line):
        return True
    return bool(re.search(r"(原创|朋友|关注).*\d|\d.*(原创|朋友|关注)", line))


def _extract_first_match(lines: list[str], patterns: tuple[str, ...]) -> str:
    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                groups = [group for group in match.groups() if group]
                if groups:
                    return groups[0]
    return ""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import time
from typing import Any

from src.modules.window.article_date_filter import (
    ArticleDateFilter,
    DateFilterDecision,
    normalize_home_date_text,
)
from src.modules.window.uia_window_test_reader import (
    Marker,
    UiaWindowTestArticleCard,
    UiaWindowTestDateSnapshot,
    UiaWindowTestSnapshot,
    cards_after_marker,
    snapshot_contains_marker,
)
from src.modules.window.wechat_home_window_finder import (
    WechatHomeWindowFindTimeout,
    WechatHomeWindowMinimized,
)


class WindowClickFlowDiagnosticService:
    """激活主页并按 UIA 日期组/文章卡片快照执行只读遍历诊断。"""

    def __init__(
        self,
        *,
        config: Any,
        window_factory: Any,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._window_factory = window_factory
        self._monotonic = monotonic
        self._sleep = sleep

    def run(
        self,
        *,
        max_records: int = 20,
        date_filter_mode: str = "all",
        start_date: str | None = None,
        end_date: str | None = None,
        stop_requested: Callable[[], bool] | None = None,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        trace_store: Any | None = None,
    ) -> dict[str, Any]:
        limit = max(0, int(max_records))
        date_filter = ArticleDateFilter.create(
            mode=date_filter_mode,
            start_date=start_date,
            end_date=end_date,
        )
        should_stop = stop_requested or (lambda: False)
        started_at = self._monotonic()
        account_name = ""
        records: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        counters = {"recognized": 0, "skipped": 0}
        marker: Marker | None = None

        def payload(
            *,
            ok: bool,
            status: str,
            message: str,
            tone: str,
            stopped_by_user: bool = False,
        ) -> dict[str, Any]:
            return _payload(
                ok=ok,
                status=status,
                message=message,
                tone=tone,
                limit=limit,
                account_name=account_name,
                records=records,
                events=events,
                counters=counters,
                date_filter_label=date_filter.label,
                stopped_by_user=stopped_by_user,
                total_seconds=_elapsed(self._monotonic, started_at),
            )

        def publish(message: str) -> None:
            if on_update is not None:
                on_update(
                    payload(
                        ok=False,
                        status="running",
                        message=message,
                        tone="info",
                    )
                )

        def trace(event: str, message: str, **details: Any) -> None:
            item = {
                "sequence": len(events) + 1,
                "event": event,
                "message": message,
                "details": details,
            }
            events.append(item)
            if trace_store is not None:
                trace_store.append_event(item)

        try:
            publish("正在定位公众号主页窗口")
            locator_reader = self._window_factory.create_reader()
            home_window = self._window_factory.find_home_window(
                reader=locator_reader,
                timeout_seconds=self._config.window.home_find_timeout_seconds,
            )
            if home_window is None:
                return payload(
                    ok=False,
                    status="home-not-found",
                    message="未找到公众号主页窗口，请先打开公众号主页",
                    tone="warning",
                )

            self._window_factory.create_home_guard().activate(home_window)
            trace("home-activated", "已激活公众号主页窗口", handle=home_window.handle)
            home_info = self._window_factory.create_home_reader().read(home_window)
            account_name = str(getattr(home_info, "account_name", "") or "")
            trace("home-read", "已读取公众号主页名称", accountName=account_name)

            snapshot_reader = self._window_factory.create_window_test_reader()
            scroller = self._window_factory.create_scroller()
            if date_filter.mode in {"after", "range"}:
                target_date = (
                    date_filter.start_date
                    if date_filter.mode == "after"
                    else date_filter.end_date
                )
                assert target_date is not None
                location_status = self._locate_start_date(
                    snapshot_reader,
                    scroller,
                    home_window,
                    target_date=target_date,
                    should_stop=should_stop,
                    publish=publish,
                    trace=trace,
                )
                if location_status == "stopped":
                    return payload(
                        ok=True,
                        status="stopped",
                        message="已停止目标日期定位",
                        tone="warning",
                        stopped_by_user=True,
                    )
                if location_status != "found":
                    return payload(
                        ok=False,
                        status="date-not-found",
                        message="主页已没有更多日期组，未定位到目标日期或更早内容",
                        tone="warning",
                    )

            snapshot = self._read_snapshot(
                snapshot_reader,
                home_window,
                stage="initial",
                trace=trace,
            )

            while limit == 0 or counters["recognized"] < limit:
                if should_stop():
                    return payload(
                        ok=True,
                        status="stopped",
                        message="已停止主页内容读取",
                        tone="warning",
                        stopped_by_user=True,
                    )

                visible = cards_after_marker(snapshot, marker)
                if marker is not None and not snapshot_contains_marker(snapshot, marker):
                    trace(
                        "marker-missing",
                        "滚动后未在 UIA 树中找到上一屏末尾卡片",
                        marker=list(marker),
                    )

                for card in visible:
                    marker = card.marker
                    decision = date_filter.decide(_card_published_date(card))
                    if decision is DateFilterDecision.SKIP:
                        counters["skipped"] += 1
                        trace(
                            "date-skipped",
                            "文章日期不符合筛选条件",
                            marker=list(card.marker),
                            dateFilter=date_filter.label,
                        )
                        continue
                    if decision is DateFilterDecision.STOP:
                        trace(
                            "date-boundary",
                            "已到达日期筛选边界",
                            marker=list(card.marker),
                            dateFilter=date_filter.label,
                        )
                        return payload(
                            ok=bool(records),
                            status="date-boundary",
                            message="已到达日期筛选边界，主页内容读取结束",
                            tone="success" if records else "warning",
                        )

                    record = _card_record(
                        card,
                        index=counters["recognized"] + 1,
                    )
                    records.append(record)
                    counters["recognized"] += 1
                    trace(
                        "article-recorded",
                        "已记录可视区文章卡片",
                        marker=list(card.marker),
                        visibleRect=list(card.visible_rect or ()),
                        clickPoint=list(card.click_point or ()),
                    )
                    publish(
                        f"已识别第 {counters['recognized']} 条文章，正在读取下一条"
                    )
                    if limit > 0 and counters["recognized"] >= limit:
                        return payload(
                            ok=True,
                            status="completed",
                            message=f"已达到主页内容读取上限 {limit} 条",
                            tone="success",
                        )

                if should_stop():
                    continue

                scrolled = scroller.scroll_down(home_window, visible_targets=[])
                trace(
                    "scroll-down",
                    "已发送主页向下滚动",
                    succeeded=bool(scrolled),
                    wheelSteps=int(self._config.window.scroll_wheel_steps),
                    marker=list(marker) if marker is not None else None,
                )
                if not scrolled:
                    return payload(
                        ok=bool(records),
                        status="scroll-failed",
                        message="主页滚动发送失败，内容读取结束",
                        tone="warning",
                    )
                self._sleep_if_positive(
                    self._config.window.scroll_initial_delay_seconds
                )

                snapshot = self._wait_for_following_cards(
                    snapshot_reader,
                    home_window,
                    marker=marker,
                    should_stop=should_stop,
                    trace=trace,
                    stage="after-scroll",
                )
                if cards_after_marker(snapshot, marker) and not snapshot.loading:
                    continue
                if should_stop():
                    continue

                bounced = False
                if bool(self._config.window.bounce_enabled):
                    for attempt in range(
                        1,
                        max(0, int(self._config.window.bounce_attempts)) + 1,
                    ):
                        trace(
                            "bounce-start",
                            "滚动后没有新文章，开始回弹滚动",
                            attempt=attempt,
                        )
                        up_ok = scroller.scroll(
                            home_window,
                            visible_targets=[],
                            direction="up",
                            wheel_steps=self._config.window.bounce_up_steps,
                        )
                        self._sleep_if_positive(
                            self._config.window.bounce_pause_seconds
                        )
                        down_ok = scroller.scroll(
                            home_window,
                            visible_targets=[],
                            direction="down",
                            wheel_steps=self._config.window.bounce_down_steps,
                        )
                        trace(
                            "bounce-finished",
                            "回弹滚动已发送",
                            attempt=attempt,
                            upSucceeded=bool(up_ok),
                            downSucceeded=bool(down_ok),
                            upSteps=int(self._config.window.bounce_up_steps),
                            downSteps=int(self._config.window.bounce_down_steps),
                        )
                        if not up_ok or not down_ok:
                            continue
                        self._sleep_if_positive(
                            self._config.window.scroll_initial_delay_seconds
                        )
                        snapshot = self._wait_for_following_cards(
                            snapshot_reader,
                            home_window,
                            marker=marker,
                            should_stop=should_stop,
                            trace=trace,
                            stage=f"after-bounce-{attempt}",
                        )
                        if cards_after_marker(snapshot, marker) and not snapshot.loading:
                            bounced = True
                            break
                if bounced:
                    continue

                return payload(
                    ok=bool(records),
                    status="completed" if records else "no-candidate",
                    message=(
                        "主页中没有更多符合条件的可视文章"
                        if records
                        else "当前主页未识别到可视文章卡片"
                    ),
                    tone="success" if records else "warning",
                )

            return payload(
                ok=True,
                status="completed",
                message=f"已达到主页内容读取上限 {limit} 条",
                tone="success",
            )
        except WechatHomeWindowFindTimeout:
            return payload(
                ok=False,
                status="home-find-timeout",
                message="定位公众号主页窗口超时，请确认主页已经打开",
                tone="warning",
            )
        except WechatHomeWindowMinimized:
            return payload(
                ok=False,
                status="home-minimized",
                message="检测到公众号主页窗口处于最小化状态，请先从任务栏打开主页",
                tone="warning",
            )
        except Exception as exc:
            return payload(
                ok=False,
                status="failed",
                message=f"主页内容读取失败：{exc}",
                tone="error",
            )

    def _read_snapshot(
        self,
        reader: Any,
        home_window: Any,
        *,
        stage: str,
        trace: Callable[..., None],
    ) -> UiaWindowTestSnapshot:
        started_at = self._monotonic()
        snapshot = reader.read(home_window)
        trace(
            "uia-snapshot",
            "已读取公众号主页 UIA 树",
            stage=stage,
            groupCount=len(snapshot.groups),
            cardCount=len(snapshot.all_cards),
            visibleCardCount=len(snapshot.visible_cards),
            contentViewport=list(snapshot.content_viewport),
            nodeCount=int(snapshot.node_count),
            loading=bool(snapshot.loading),
            durationSeconds=round(self._monotonic() - started_at, 3),
            visibleMarkers=[list(card.marker) for card in snapshot.visible_cards],
        )
        return snapshot

    def _locate_start_date(
        self,
        reader: Any,
        scroller: Any,
        home_window: Any,
        *,
        target_date: date,
        should_stop: Callable[[], bool],
        publish: Callable[[str], None],
        trace: Callable[..., None],
    ) -> str:
        """只使用日期组滚动定位，定位完成前不读取文章卡片。"""

        publish(f"正在定位目标日期 {target_date.isoformat()}")
        snapshot = self._read_date_snapshot(
            reader,
            home_window,
            stage="date-location-initial",
            trace=trace,
        )
        if _date_snapshot_reaches(snapshot, target_date):
            self._trace_start_date_found(snapshot, target_date=target_date, trace=trace)
            return "found"

        while not should_stop():
            previous_signature = _date_snapshot_signature(snapshot)
            wheel_steps, remaining_days = _date_seek_wheel_steps(
                snapshot,
                target_date=target_date,
                normal_steps=int(self._config.window.scroll_wheel_steps),
                max_steps=int(self._config.window.date_seek_max_steps),
            )
            scrolled = scroller.scroll(
                home_window,
                visible_targets=[],
                direction="down",
                wheel_steps=wheel_steps,
            )
            trace(
                "date-location-scroll",
                "目标日期定位已发送主页向下滚动",
                succeeded=bool(scrolled),
                wheelSteps=wheel_steps,
                remainingDays=remaining_days,
                targetDate=target_date.isoformat(),
            )
            if not scrolled:
                return "exhausted"
            self._sleep_if_positive(self._config.window.scroll_initial_delay_seconds)
            snapshot = self._wait_for_date_progress(
                reader,
                home_window,
                previous_signature=previous_signature,
                target_date=target_date,
                should_stop=should_stop,
                trace=trace,
                stage="date-location-after-scroll",
            )
            if not snapshot.loading and _date_snapshot_reaches(snapshot, target_date):
                self._trace_start_date_found(snapshot, target_date=target_date, trace=trace)
                return "found"
            if should_stop():
                return "stopped"
            if (
                not snapshot.loading
                and _date_snapshot_signature(snapshot) != previous_signature
            ):
                continue

            progressed = False
            if bool(self._config.window.bounce_enabled):
                for attempt in range(
                    1,
                    max(0, int(self._config.window.bounce_attempts)) + 1,
                ):
                    trace(
                        "date-location-bounce-start",
                        "日期定位滚动后没有变化，开始回弹滚动",
                        attempt=attempt,
                        targetDate=target_date.isoformat(),
                    )
                    up_ok = scroller.scroll(
                        home_window,
                        visible_targets=[],
                        direction="up",
                        wheel_steps=self._config.window.bounce_up_steps,
                    )
                    self._sleep_if_positive(self._config.window.bounce_pause_seconds)
                    down_ok = scroller.scroll(
                        home_window,
                        visible_targets=[],
                        direction="down",
                        wheel_steps=self._config.window.bounce_down_steps,
                    )
                    trace(
                        "date-location-bounce-finished",
                        "日期定位回弹滚动已发送",
                        attempt=attempt,
                        upSucceeded=bool(up_ok),
                        downSucceeded=bool(down_ok),
                    )
                    if not up_ok or not down_ok:
                        continue
                    self._sleep_if_positive(
                        self._config.window.scroll_initial_delay_seconds
                    )
                    snapshot = self._wait_for_date_progress(
                        reader,
                        home_window,
                        previous_signature=previous_signature,
                        target_date=target_date,
                        should_stop=should_stop,
                        trace=trace,
                        stage=f"date-location-after-bounce-{attempt}",
                    )
                    if (
                        not snapshot.loading
                        and _date_snapshot_reaches(snapshot, target_date)
                    ):
                        self._trace_start_date_found(
                            snapshot,
                            target_date=target_date,
                            trace=trace,
                        )
                        return "found"
                    if (
                        not snapshot.loading
                        and _date_snapshot_signature(snapshot) != previous_signature
                    ):
                        progressed = True
                        break
            if not progressed:
                return "exhausted"
        return "stopped"

    def _read_date_snapshot(
        self,
        reader: Any,
        home_window: Any,
        *,
        stage: str,
        trace: Callable[..., None],
    ) -> UiaWindowTestDateSnapshot:
        started_at = self._monotonic()
        snapshot = reader.read_date_groups(home_window)
        trace(
            "uia-date-snapshot",
            "已读取公众号主页 UIA 日期组",
            stage=stage,
            groupCount=len(snapshot.groups),
            visibleGroupCount=len(snapshot.visible_groups),
            contentViewport=list(snapshot.content_viewport),
            nodeCount=int(snapshot.node_count),
            loading=bool(snapshot.loading),
            durationSeconds=round(self._monotonic() - started_at, 3),
            visibleDates=[
                {
                    "dateText": group.date_text,
                    "publishedDate": group.published_date,
                }
                for group in snapshot.visible_groups
            ],
        )
        return snapshot

    def _wait_for_date_progress(
        self,
        reader: Any,
        home_window: Any,
        *,
        previous_signature: tuple[tuple[Any, ...], ...],
        target_date: date,
        should_stop: Callable[[], bool],
        trace: Callable[..., None],
        stage: str,
    ) -> UiaWindowTestDateSnapshot:
        started_at = self._monotonic()
        unchanged_timeout = max(
            0.0,
            float(self._config.window.unchanged_before_bounce_seconds),
        )
        lazy_timeout = max(
            unchanged_timeout,
            float(
                getattr(
                    self._config.window,
                    "lazy_load_timeout_seconds",
                    unchanged_timeout,
                )
            ),
        )
        deadline = started_at + unchanged_timeout
        lazy_deadline = started_at + lazy_timeout
        interval = max(0.0, float(self._config.window.scroll_probe_interval_seconds))
        max_interval = max(
            interval,
            float(self._config.window.scroll_probe_max_interval_seconds),
        )
        probe_count = 0
        loading_observed = False
        latest = self._read_date_snapshot(
            reader,
            home_window,
            stage=stage,
            trace=trace,
        )
        while not should_stop():
            loading_observed = loading_observed or bool(latest.loading)
            page_changed = _date_snapshot_signature(latest) != previous_signature
            target_reached = _date_snapshot_reaches(latest, target_date)
            now = self._monotonic()
            if loading_observed:
                # 一旦本轮见过懒加载，必须等加载消失且 UIA 已有推进，避免半加载快照进入下一轮。
                if not latest.loading and (page_changed or target_reached):
                    break
                effective_deadline = lazy_deadline
            else:
                if page_changed or target_reached:
                    break
                effective_deadline = deadline
            if now >= effective_deadline:
                break
            wait_seconds = min(interval, max(0.0, effective_deadline - now))
            self._sleep_if_positive(wait_seconds)
            latest = self._read_date_snapshot(
                reader,
                home_window,
                stage=stage,
                trace=trace,
            )
            probe_count += 1
            interval = min(max_interval, interval * 1.5) if interval > 0 else 0.01
        trace(
            "uia-date-observation-finished",
            "滚动后的 UIA 日期组观察阶段已结束",
            stage=stage,
            probeCount=probe_count + 1,
            pageChanged=_date_snapshot_signature(latest) != previous_signature,
            targetReached=_date_snapshot_reaches(latest, target_date),
            loadingObserved=loading_observed,
            loadingFinished=loading_observed and not latest.loading,
            durationSeconds=round(self._monotonic() - started_at, 3),
        )
        return latest

    @staticmethod
    def _trace_start_date_found(
        snapshot: UiaWindowTestDateSnapshot,
        *,
        target_date: date,
        trace: Callable[..., None],
    ) -> None:
        matched = next(
            (
                group
                for group in snapshot.groups
                if _group_published_date(group) is not None
                and _group_published_date(group) <= target_date
            ),
            None,
        )
        trace(
            "start-date-found",
            "已定位起始日期或首个更早日期组，开始读取文章卡片",
            targetDate=target_date.isoformat(),
            matchedDate=(matched.published_date if matched is not None else ""),
            matchedDateText=(matched.date_text if matched is not None else ""),
        )

    def _wait_for_following_cards(
        self,
        reader: Any,
        home_window: Any,
        *,
        marker: Marker | None,
        should_stop: Callable[[], bool],
        trace: Callable[..., None],
        stage: str,
    ) -> UiaWindowTestSnapshot:
        started_at = self._monotonic()
        unchanged_timeout = max(
            0.0,
            float(self._config.window.unchanged_before_bounce_seconds),
        )
        lazy_timeout = max(
            unchanged_timeout,
            float(getattr(self._config.window, "lazy_load_timeout_seconds", unchanged_timeout)),
        )
        deadline = started_at + unchanged_timeout
        lazy_deadline = started_at + lazy_timeout
        interval = max(0.0, float(self._config.window.scroll_probe_interval_seconds))
        max_interval = max(
            interval,
            float(self._config.window.scroll_probe_max_interval_seconds),
        )
        probe_count = 0
        loading_observed = False
        latest = self._read_snapshot(
            reader,
            home_window,
            stage=stage,
            trace=trace,
        )
        while not should_stop():
            loading_observed = loading_observed or bool(latest.loading)
            following_cards = cards_after_marker(latest, marker)
            now = self._monotonic()
            if loading_observed:
                # 新卡片可能先于 loading 提示消失，等完整加载周期结束后再交给收录逻辑。
                if not latest.loading and following_cards:
                    break
                effective_deadline = lazy_deadline
            else:
                if following_cards:
                    break
                effective_deadline = deadline
            if now >= effective_deadline:
                break
            wait_seconds = min(interval, max(0.0, effective_deadline - now))
            self._sleep_if_positive(wait_seconds)
            latest = self._read_snapshot(
                reader,
                home_window,
                stage=stage,
                trace=trace,
            )
            probe_count += 1
            interval = min(max_interval, interval * 1.5) if interval > 0 else 0.01
        trace(
            "uia-observation-finished",
            "滚动后的 UIA 观察阶段已结束",
            stage=stage,
            probeCount=probe_count + 1,
            markerFound=snapshot_contains_marker(latest, marker),
            newCardCount=len(cards_after_marker(latest, marker)),
            loadingObserved=loading_observed,
            loadingFinished=loading_observed and not latest.loading,
            durationSeconds=round(self._monotonic() - started_at, 3),
        )
        return latest

    def _sleep_if_positive(self, seconds: float) -> None:
        value = max(0.0, float(seconds))
        if value > 0:
            self._sleep(value)


def _card_published_date(card: UiaWindowTestArticleCard) -> date | None:
    return _published_date(
        str(card.published_date or ""),
        str(card.date_text or ""),
    )


def _group_published_date(group: Any) -> date | None:
    return _published_date(
        str(getattr(group, "published_date", "") or ""),
        str(getattr(group, "date_text", "") or ""),
    )


def _date_seek_wheel_steps(
    snapshot: UiaWindowTestDateSnapshot,
    *,
    target_date: date,
    normal_steps: int,
    max_steps: int,
) -> tuple[int, int | None]:
    """按当前最旧日期与目标日期的距离选择 18/12/6/3 级滚动步长。"""

    fine_steps = max(1, int(normal_steps))
    fast_steps = max(fine_steps, int(max_steps))
    published_dates = [
        published
        for published in (
            _group_published_date(group) for group in snapshot.groups
        )
        if published is not None
    ]
    if not published_dates:
        return fine_steps, None

    remaining_days = max(0, (min(published_dates) - target_date).days)
    near_steps = max(fine_steps, round(fast_steps / 3))
    medium_steps = max(near_steps, round(fast_steps * 2 / 3))
    if remaining_days >= 15:
        return fast_steps, remaining_days
    if remaining_days >= 8:
        return medium_steps, remaining_days
    if remaining_days >= 4:
        return near_steps, remaining_days
    return fine_steps, remaining_days


def _published_date(standard_date: str, date_text: str) -> date | None:
    if standard_date:
        try:
            return date.fromisoformat(standard_date)
        except ValueError:
            pass
    return normalize_home_date_text(date_text)


def _date_snapshot_reaches(
    snapshot: UiaWindowTestDateSnapshot,
    target_date: date,
) -> bool:
    return any(
        published is not None and published <= target_date
        for published in (
            _group_published_date(group) for group in snapshot.groups
        )
    )


def _date_snapshot_signature(
    snapshot: UiaWindowTestDateSnapshot,
) -> tuple[tuple[Any, ...], ...]:
    """坐标只用于判断本次滚动是否移动，不参与文章身份和去重。"""

    return tuple(
        (
            tuple(getattr(group, "runtime_id", ()) or ()),
            str(getattr(group, "published_date", "") or ""),
            str(getattr(group, "date_text", "") or ""),
            tuple(getattr(group, "visible_rect", None) or ()),
            tuple(getattr(group, "group_rect", None) or ()),
        )
        for group in snapshot.visible_groups
    )


def _card_record(card: UiaWindowTestArticleCard, *, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "status": "已识别",
        "title": card.title,
        "rawTitle": card.raw_title,
        "dateText": card.date_text,
        "publishedDate": card.published_date,
        "dateRect": card.date_rect,
        "titleRect": card.title_rect,
        "cardRect": card.card_rect,
        "visibleRect": card.visible_rect,
        "visibleHeight": card.visible_height,
        "clickPoint": card.click_point,
    }


def _payload(
    *,
    ok: bool,
    status: str,
    message: str,
    tone: str,
    limit: int,
    account_name: str,
    records: list[dict[str, Any]],
    events: list[dict[str, Any]],
    counters: dict[str, int],
    date_filter_label: str,
    stopped_by_user: bool,
    total_seconds: float,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "status": status,
        "action": "window-click-flow",
        "title": "主页内容读取结果",
        "message": message,
        "tone": tone,
        "items": [_record_item(record) for record in records],
        "records": list(records),
        "events": list(events),
        "recognizedCount": int(counters["recognized"]),
        "skippedCount": int(counters["skipped"]),
        "stoppedByUser": bool(stopped_by_user),
        "maxRecords": int(limit),
        "accountName": account_name,
        "dateFilterLabel": date_filter_label,
        "totalSeconds": total_seconds,
    }


def _record_item(record: dict[str, Any]) -> dict[str, Any]:
    index = int(record.get("index", 0) or 0)
    time_text = (
        f"{record.get('dateText', '')} / {record.get('publishedDate', '')}"
    ).strip(" /") or "未识别"
    cells = [
        {"label": "时间", "value": time_text},
        {"label": "标题", "value": str(record.get("title", "") or "未识别")},
        {
            "label": "标题原文",
            "value": str(record.get("rawTitle", "") or "未单独读取"),
        },
        {"label": "完整卡片坐标", "value": _rect(record.get("cardRect"))},
        {"label": "可视卡片坐标", "value": _rect(record.get("visibleRect"))},
        {
            "label": "可视高度",
            "value": f"{int(record.get('visibleHeight', 0) or 0)} px",
        },
        {"label": "中心点", "value": _point(record.get("clickPoint"))},
    ]
    return {
        "kind": "article",
        "tone": "success",
        "label": f"第 {index} 条文章",
        "value": "已识别",
        "cells": cells,
    }


def _rect(value: Any) -> str:
    try:
        left, top, right, bottom = value
        return f"({int(left)}, {int(top)}) - ({int(right)}, {int(bottom)})"
    except (TypeError, ValueError):
        return "未识别"


def _point(value: Any) -> str:
    try:
        x, y = value
        return f"({int(x)}, {int(y)})"
    except (TypeError, ValueError):
        return "未识别"


def _elapsed(monotonic: Callable[[], float], started_at: float) -> float:
    return round(max(0.0, monotonic() - started_at), 3)


__all__ = ["WindowClickFlowDiagnosticService"]

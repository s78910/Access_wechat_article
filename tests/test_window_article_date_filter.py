from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.domain.models import ArticleTarget
from src.modules.window.article_card_reader import (
    _TextNode,
    _nearest_card_date_node,
    _visible_range_targets,
    UiaArticleCardReader,
    display_article_title,
    is_article_title_text,
    merge_article_targets,
    normalize_window_text,
)
from src.modules.window.window_models import WindowInfo
from src.modules.window.article_date_filter import (
    ArticleDateFilter,
    DateFilterDecision,
    normalize_home_date_text,
)
from src.services.runtime.window_click_flow_diagnostic_service import (
    WindowClickFlowDiagnosticService,
)
from src.services.task.window_click_flow_huey_service import (
    WindowClickFlowConflictError,
)
from dev_server import (
    WindowClickFlowDiagnosticPayload,
    _start_window_click_flow_diagnostic_job,
    _stop_window_click_flow_diagnostic_job,
    _window_click_flow_diagnostic_job_payload,
    shutdown_backend,
)


class HomeDateNormalizationTests(unittest.TestCase):
    def test_normalizes_relative_and_absolute_home_dates(self) -> None:
        today = date(2026, 8, 13)

        self.assertEqual(normalize_home_date_text("今天", today=today), date(2026, 8, 13))
        self.assertEqual(normalize_home_date_text("昨天", today=today), date(2026, 8, 12))
        self.assertEqual(normalize_home_date_text("星期一", today=today), date(2026, 8, 10))
        self.assertEqual(normalize_home_date_text("8月2日", today=today), date(2026, 8, 2))
        self.assertEqual(normalize_home_date_text("12月31日", today=today), date(2025, 12, 31))
        self.assertEqual(normalize_home_date_text("2024年4月25日", today=today), date(2024, 4, 25))

    def test_returns_none_for_unrecognized_date(self) -> None:
        self.assertIsNone(normalize_home_date_text("刚刚", today=date(2026, 8, 13)))


class ArticleDateFilterTests(unittest.TestCase):
    def test_range_filter_includes_both_boundaries_and_stops_after_older_date(self) -> None:
        date_filter = ArticleDateFilter.create(
            mode="range",
            start_date="2026-08-01",
            end_date="2026-08-10",
        )

        self.assertEqual(date_filter.decide(date(2026, 8, 11)), DateFilterDecision.SKIP)
        self.assertEqual(date_filter.decide(date(2026, 8, 10)), DateFilterDecision.INCLUDE)
        self.assertEqual(date_filter.decide(date(2026, 8, 1)), DateFilterDecision.INCLUDE)
        self.assertEqual(date_filter.decide(date(2026, 7, 31)), DateFilterDecision.STOP)

    def test_before_filter_includes_current_page_until_cutoff_then_stops(self) -> None:
        date_filter = ArticleDateFilter.create(mode="before", end_date="2026-08-10")

        self.assertEqual(date_filter.decide(date(2026, 8, 11)), DateFilterDecision.INCLUDE)
        self.assertEqual(date_filter.decide(date(2026, 8, 10)), DateFilterDecision.INCLUDE)
        self.assertEqual(date_filter.decide(date(2026, 8, 9)), DateFilterDecision.STOP)

    def test_after_filter_skips_newer_dates_then_includes_start_and_older(self) -> None:
        date_filter = ArticleDateFilter.create(mode="after", start_date="2026-08-10")

        self.assertEqual(date_filter.decide(date(2026, 8, 13)), DateFilterDecision.SKIP)
        self.assertEqual(date_filter.decide(date(2026, 8, 10)), DateFilterDecision.INCLUDE)
        self.assertEqual(date_filter.decide(date(2026, 8, 9)), DateFilterDecision.INCLUDE)

    def test_missing_article_date_is_never_dispatched(self) -> None:
        date_filter = ArticleDateFilter.create(mode="all")

        self.assertEqual(date_filter.decide(None), DateFilterDecision.SKIP)


class WindowClickFlowPayloadTests(unittest.TestCase):
    def test_limits_window_reading_diagnostic_to_twenty_records(self) -> None:
        payload = WindowClickFlowDiagnosticPayload(maxRecords=100)

        self.assertEqual(payload.maxRecords, 20)

    def test_rejects_range_when_start_date_is_after_end_date(self) -> None:
        with self.assertRaises(ValueError):
            WindowClickFlowDiagnosticPayload(
                maxRecords=3,
                dateFilterMode="range",
                startDate="2026-08-10",
                endDate="2026-08-01",
            )

    def test_range_and_before_use_zero_as_unlimited_record_count(self) -> None:
        date_range = WindowClickFlowDiagnosticPayload(
            maxRecords=8,
            dateFilterMode="range",
            startDate="2026-08-01",
            endDate="2026-08-10",
        )
        before = WindowClickFlowDiagnosticPayload(
            maxRecords=4,
            dateFilterMode="before",
            endDate="2026-08-10",
        )

        self.assertEqual(date_range.maxRecords, 0)
        self.assertEqual(before.maxRecords, 0)

    def test_after_keeps_adjustable_record_count_and_single_boundary(self) -> None:
        after = WindowClickFlowDiagnosticPayload(
            maxRecords=5,
            dateFilterMode="after",
            startDate="2026-08-10",
        )

        self.assertEqual(after.maxRecords, 5)
        self.assertEqual(after.startDate, "2026-08-10")


class WeakArticleTitleTests(unittest.TestCase):
    def test_symbol_title_is_kept_as_article_title_candidate(self) -> None:
        self.assertTrue(is_article_title_text("."))

    def test_symbol_only_title_uses_placeholder_but_keeps_raw_text_separately(self) -> None:
        self.assertEqual(display_article_title("."), "xxx")
        self.assertEqual(display_article_title("正常文章标题"), "正常文章标题")


class ArticleCardDateGroupingTests(unittest.TestCase):
    @patch("src.modules.window.article_card_reader._visible_range_targets")
    @patch("src.modules.window.article_card_reader._get_visible_ranges")
    @patch("src.modules.window.article_card_reader.find_wechat_document_control")
    def test_text_pattern_success_skips_full_control_tree_scan(
        self,
        find_document: object,
        get_ranges: object,
        parse_ranges: object,
    ) -> None:
        target = _target("TextPattern 文章", "2026-08-14")
        find_document.return_value = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        get_ranges.return_value = [_FakeTextRange("今天", (10, 10, 80, 30))]
        parse_ranges.return_value = [target]
        reader = _NoControlTreeScanReader()
        home_window = WindowInfo(
            1,
            "测试公众号",
            "Chrome",
            "WeChat.exe",
            (0, 0, 500, 500),
            control=object(),
        )

        observation = reader.read_viewport(home_window, account_name="测试公众号")

        self.assertEqual(list(observation.targets), [target])

    @patch("src.modules.window.article_card_reader._visible_range_targets")
    @patch("src.modules.window.article_card_reader._get_visible_ranges")
    @patch("src.modules.window.article_card_reader.find_wechat_document_control")
    def test_text_pattern_candidate_keeps_loading_state(
        self,
        find_document: object,
        get_ranges: object,
        parse_ranges: object,
    ) -> None:
        target = _target("加载中的文章", "2026-08-14")
        find_document.return_value = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        get_ranges.return_value = [_FakeTextRange("正在加载...", (10, 10, 120, 30))]
        parse_ranges.return_value = [target]
        reader = _NoControlTreeScanReader()
        home_window = WindowInfo(
            1,
            "测试公众号",
            "Chrome",
            "WeChat.exe",
            (0, 0, 500, 500),
            control=object(),
        )

        observation = reader.read_viewport(home_window, account_name="测试公众号")

        self.assertTrue(observation.loading)

    @patch("src.modules.window.article_card_reader._get_visible_ranges")
    @patch("src.modules.window.article_card_reader.find_wechat_document_control")
    def test_text_pattern_observation_exposes_range_count_and_discarded_candidates(
        self,
        find_document: object,
        get_ranges: object,
    ) -> None:
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 1000))
        find_document.return_value = document
        get_ranges.return_value = [
            _FakeTextRange("今天", (10, 70, 80, 90)),
            _FakeTextRange("完整文章", (10, 100, 180, 120)),
            _FakeTextRange("阅读 20", (10, 130, 100, 150)),
            _FakeTextRange("视口底部文章", (10, 455, 180, 480)),
            _FakeTextRange("阅读 10", (10, 490, 100, 510)),
        ]
        home_window = WindowInfo(
            1,
            "测试公众号",
            "Chrome",
            "WeChat.exe",
            (0, 0, 500, 500),
            control=object(),
        )

        observation = _NoControlTreeScanReader().read_viewport(
            home_window,
            account_name="测试公众号",
        )

        self.assertEqual([target.title for target in observation.targets], ["完整文章"])
        self.assertEqual(observation.range_count, 5)
        self.assertEqual(len(observation.decisions), 1)
        self.assertEqual(observation.decisions[0]["titleFragment"], "视口底部文章")
        self.assertEqual(observation.decisions[0]["metricText"], "阅读 10")
        self.assertEqual(observation.decisions[0]["reason"], "阅读指标没有完整位于主页可视区")

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_navigation_row_excludes_home_header_from_first_article_title(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 14)
        ranges = [
            _FakeTextRange("GeenMedical", (479, 272, 683, 308)),
            _FakeTextRange("全部", (479, 324, 521, 351)),
            _FakeTextRange("贴图", (557, 324, 599, 351)),
            _FakeTextRange("文章", (635, 324, 677, 351)),
            _FakeTextRange("星期五", (503, 335, 557, 359)),
            _FakeTextRange("得知同龄人猝死后，", (662, 428, 851, 455)),
            _FakeTextRange("他开始写“遗书。”", (662, 461, 825, 488)),
            _FakeTextRange("阅读 16 赞 1", (503, 521, 616, 545)),
        ]
        document = SimpleNamespace(BoundingRectangle=(242, 254, 1271, 1849))
        home_window = WindowInfo(
            1,
            "微信",
            "Chrome_WidgetWin_0",
            "WeChatAppEx.exe",
            (231, 190, 1282, 1858),
        )

        targets = _visible_range_targets(
            document,
            account_name="GeenMedical",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].title, "得知同龄人猝死后,他开始写“遗书。”")
        self.assertEqual(targets[0].raw_title, "得知同龄人猝死后,他开始写“遗书。”")

    def test_date_group_applies_to_multiple_articles_until_next_date(self) -> None:
        date_node = _TextNode("今天", (10, 100, 80, 120), 1, "", None)
        metric = _TextNode("阅读 10", (10, 500, 100, 520), 1, "", None)

        self.assertIs(_nearest_card_date_node([date_node], metric), date_node)

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_obscured_date_can_group_visible_title_and_metric(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 13)
        ranges = [
            _FakeTextRange("全部\n文章\n视频号", (0, 0, 300, 60)),
            _FakeTextRange("今天", (10, 20, 80, 40)),
            _FakeTextRange("测试文章标题", (10, 70, 200, 100)),
            _FakeTextRange("阅读 10", (10, 110, 100, 130)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(
            handle=1,
            title="测试公众号",
            class_name="Chrome_WidgetWin_0",
            process_name="WeChat.exe",
            rect=(0, 0, 500, 500),
            control=None,
        )

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].date_text, "今天")
        self.assertEqual(targets[0].date_rect, (10, 20, 80, 40))
        self.assertEqual(targets[0].metric_rect, (10, 110, 100, 130))

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_visible_symbol_title_is_dispatched_with_placeholder(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 13)
        ranges = [
            _FakeTextRange("今天", (10, 70, 80, 90)),
            _FakeTextRange(".", (10, 100, 30, 120)),
            _FakeTextRange("阅读 10", (10, 130, 100, 150)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(targets[0].title, "xxx")
        self.assertEqual(targets[0].raw_title, ".")

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_metric_anchor_uses_unpositioned_previous_metric_and_ignores_expand(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 6)
        ranges = [
            _FakeTextRange("阅读 20", None),
            _FakeTextRange("8月6日", (10, 70, 80, 90)),
            _FakeTextRange("真实文章标题", (10, 100, 180, 120)),
            _FakeTextRange("展开", (10, 125, 40, 145)),
            _FakeTextRange("阅读 10", (10, 160, 100, 180)),
            _FakeTextRange("阅读 10", (10, 160, 100, 180)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].title, "真实文章标题")
        self.assertEqual(targets[0].raw_title, "真实文章标题")
        self.assertEqual(targets[0].metric_rect, (10, 160, 100, 180))
        self.assertEqual(targets[0].date_text, "8月6日")

    def test_document_range_fills_metric_missing_from_uia_nodes(self) -> None:
        uia_target = _target("第一篇", "2026-08-13")
        document_target = ArticleTarget(
            account_name="测试公众号",
            title="xxx",
            click_x=100,
            click_y=400,
            home_window_handle=100,
            fingerprint="document-hidden-date",
            date_text="今天",
            published_date="2026-08-13",
            metric_text="阅读 20",
            metric_rect=(80, 390, 160, 410),
        )

        merged = merge_article_targets([uia_target], [uia_target, document_target])

        self.assertEqual([item.title for item in merged], ["第一篇", "xxx"])

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_next_viewport_inherits_previous_date_group_when_date_is_fully_hidden(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 13)
        first_ranges = [
            _FakeTextRange("今天", (10, 70, 80, 90)),
            _FakeTextRange("第一篇", (10, 100, 120, 120)),
            _FakeTextRange("阅读 10", (10, 130, 100, 150)),
        ]
        next_ranges = [
            _FakeTextRange("阅读 10", None),
            _FakeTextRange("第二篇", (10, 70, 120, 90)),
            _FakeTextRange("阅读 20", (10, 100, 100, 120)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        first = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=first_ranges,
        )
        following = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=next_ranges,
            inherited_date_text=first[-1].date_text,
        )

        self.assertEqual(following[0].title, "第二篇")
        self.assertEqual(following[0].date_text, "今天")
        self.assertIsNone(following[0].date_rect)

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_discards_inherited_date_fragment_without_previous_metric_boundary(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 6)
        ranges = [
            _FakeTextRange("假如这是真的,这是要刷新人类科研记录啊!", (10, 70, 260, 100)),
            _FakeTextRange("阅读 2.1万 赞 35", (10, 110, 150, 130)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
            inherited_date_text="8月6日",
        )

        self.assertEqual(targets, [])

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_reports_title_fragment_when_inherited_date_candidate_is_discarded(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 6)
        decisions: list[dict[str, object]] = []
        ranges = [
            _FakeTextRange("假如这是真的,这是要刷新人类科研记录啊!", (10, 70, 260, 100)),
            _FakeTextRange("阅读 2.1万 赞 35", (10, 110, 150, 130)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
            inherited_date_text="8月6日",
            decision_sink=decisions.append,
        )

        self.assertEqual(targets, [])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["titleFragment"], "假如这是真的,这是要刷新人类科研记录啊!")
        self.assertEqual(decisions[0]["dateText"], "8月6日")
        self.assertEqual(decisions[0]["metricText"], "阅读 2.1万 赞 35")
        self.assertEqual(decisions[0]["reason"], "未检测到日期或前一阅读指标边界")

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_keeps_unpositioned_title_text_when_date_and_metric_confirm_boundary(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 6)
        ranges = [
            _FakeTextRange("8月6日", (10, 50, 80, 70)),
            _FakeTextRange("我的天啊,他,发文>4000篇!", None),
            _FakeTextRange("假如这是真的,这是要刷新人类科研记录啊!", (10, 80, 260, 110)),
            _FakeTextRange("阅读 2.1万 赞 35", (10, 120, 150, 140)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(
            targets[0].raw_title,
            "我的天啊,他,发文>4000篇!假如这是真的,这是要刷新人类科研记录啊!",
        )
        self.assertEqual(targets[0].date_text, "8月6日")
        self.assertEqual(targets[0].metric_text, "阅读 2.1万 赞 35")

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_recovers_full_title_from_visible_fragment_enclosing_control(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 7, 27)
        full_title = "喜大普奔！即日起：医生可以“投诉患者”啦！"
        ranges = [
            _FakeTextRange("7月27日", (10, 50, 80, 70)),
            _FakeTextRange(
                "啦！",
                (10, 80, 52, 108),
                enclosing_name=full_title,
            ),
            _FakeTextRange("阅读 3.3万 赞 334", (10, 120, 170, 145)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(len(targets), 1)
        normalized_full_title = normalize_window_text(full_title)
        self.assertEqual(targets[0].title, normalized_full_title)
        self.assertEqual(targets[0].raw_title, normalized_full_title)
        self.assertEqual(targets[0].title_rect, (10, 80, 52, 108))

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_discards_range_when_title_and_metric_share_the_same_rectangle(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 13)
        decisions: list[dict[str, object]] = []
        shared_rect = (10, 100, 200, 140)
        ranges = [
            _FakeTextRange("今天", (10, 70, 80, 90)),
            _FakeTextRange("滚动中的标题残片", shared_rect),
            _FakeTextRange("阅读 10", shared_rect),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
            decision_sink=decisions.append,
        )

        self.assertEqual(targets, [])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["titleFragment"], "滚动中的标题残片")
        self.assertEqual(decisions[0]["reason"], "标题与阅读指标坐标重合，页面可能仍在滚动")

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_discards_metric_outside_actual_home_viewport(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 13)
        ranges = [
            _FakeTextRange("今天", (10, 610, 80, 630)),
            _FakeTextRange("视口外文章", (10, 650, 180, 680)),
            _FakeTextRange("阅读 10", (10, 710, 100, 730)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 1000))
        home_window = WindowInfo(
            1,
            "测试公众号",
            "Chrome",
            "WeChat.exe",
            (0, 0, 500, 500),
        )

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(targets, [])

    @patch("src.modules.window.article_card_reader.normalize_home_date_text")
    def test_discards_metric_that_only_partially_intersects_home_viewport(
        self,
        normalize_date: object,
    ) -> None:
        normalize_date.return_value = date(2026, 8, 13)
        ranges = [
            _FakeTextRange("今天", (10, 430, 80, 450)),
            _FakeTextRange("视口底部文章", (10, 455, 180, 480)),
            _FakeTextRange("阅读 10", (10, 490, 100, 510)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 1000))
        home_window = WindowInfo(
            1,
            "测试公众号",
            "Chrome",
            "WeChat.exe",
            (0, 0, 500, 500),
        )

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
        )

        self.assertEqual(targets, [])

    def test_reports_metric_without_title_and_trailing_title_without_metric(self) -> None:
        decisions: list[dict[str, object]] = []
        ranges = [
            _FakeTextRange("今天", (10, 50, 80, 70)),
            _FakeTextRange("阅读 10", (10, 80, 100, 100)),
            _FakeTextRange("只有标题但没有阅读指标", (10, 120, 240, 150)),
        ]
        document = SimpleNamespace(BoundingRectangle=(0, 0, 500, 500))
        home_window = WindowInfo(1, "测试公众号", "Chrome", "WeChat.exe", (0, 0, 500, 500))

        targets = _visible_range_targets(
            document,
            account_name="测试公众号",
            home_window=home_window,
            visible_ranges=ranges,
            decision_sink=decisions.append,
        )

        self.assertEqual(targets, [])
        self.assertEqual(
            [decision["reason"] for decision in decisions],
            ["阅读指标前没有可用标题", "视口末尾标题没有对应的完整阅读指标"],
        )
        self.assertEqual(decisions[1]["titleFragment"], "只有标题但没有阅读指标")


class _FakeTextRange:
    def __init__(
        self,
        text: str,
        rect: tuple[int, int, int, int] | None,
        *,
        enclosing_name: str = "",
    ) -> None:
        self.text = text
        self.rect = rect
        self.enclosing_name = enclosing_name

    def GetText(self, _limit: int) -> str:
        return self.text

    def GetBoundingRectangles(self) -> tuple[tuple[int, int, int, int], ...]:
        return (self.rect,) if self.rect is not None else ()

    def GetEnclosingControl(self) -> object:
        return SimpleNamespace(Name=self.enclosing_name)


class _NoControlTreeScanReader(UiaArticleCardReader):
    def _collect_text_nodes(self, *args: object, **kwargs: object) -> list[_TextNode]:
        del args, kwargs
        raise AssertionError("TextPattern 成功时不应遍历完整 UIA 控件树")


class _FakeCursor:
    def __init__(
        self,
        targets: list[ArticleTarget],
        *,
        trace_event: dict[str, object] | None = None,
        trace_events: list[dict[str, object]] | None = None,
    ) -> None:
        self.targets = iter(targets)
        self.trace_events = list(trace_events or ([] if trace_event is None else [trace_event]))
        self.trace = None
        self.trace_sent = False

    def refresh_visible(self, _home_window: object) -> list[ArticleTarget]:
        if callable(self.trace) and self.trace_events and not self.trace_sent:
            self.trace_sent = True
            for event in self.trace_events:
                self.trace(event)
        return []

    def next_candidate(self, _home_window: object) -> ArticleTarget | None:
        return next(self.targets, None)

    def refresh_target(self, _home_window: object, target: ArticleTarget) -> ArticleTarget:
        return target

    def mark_processed(self, _target: ArticleTarget) -> None:
        return None


class _FakeClicker:
    def __init__(self) -> None:
        self.titles: list[str] = []

    def click(self, target: ArticleTarget) -> object:
        self.titles.append(target.title)
        return SimpleNamespace(method="test", click_x=target.click_x, click_y=target.click_y)


class _FakeTabs:
    def capture_baseline(self) -> object:
        return object()

    def wait_for_opened_article_tab(self, **_kwargs: object) -> object:
        return SimpleNamespace(title="文章标签")

    def close_article_tab(self, *_args: object, **_kwargs: object) -> None:
        return None


class _FakeGuard:
    def activate(self, _home_window: object) -> None:
        return None

    def ensure_target_clickable(self, _home_window: object, _target: object) -> None:
        return None


class _FakeWindowFactory:
    restore_focus_after_close = False

    def __init__(
        self,
        targets: list[ArticleTarget],
        *,
        trace_event: dict[str, object] | None = None,
        trace_events: list[dict[str, object]] | None = None,
    ) -> None:
        self.cursor = _FakeCursor(
            targets,
            trace_event=trace_event,
            trace_events=trace_events,
        )
        self.clicker = _FakeClicker()
        self.guard_created = False
        self.tabs_created = False
        self.clicker_created = False
        self.guard_activated = False

    def create_reader(self) -> object:
        return object()

    def find_home_window(self, **_kwargs: object) -> object:
        return SimpleNamespace(handle=100)

    def create_home_guard(self) -> _FakeGuard:
        self.guard_created = True
        guard = _FakeGuard()
        original_activate = guard.activate

        def activate(home_window: object) -> None:
            self.guard_activated = True
            original_activate(home_window)

        guard.activate = activate  # type: ignore[method-assign]
        return guard
        return _FakeGuard()

    def create_home_reader(self) -> object:
        return SimpleNamespace(read=lambda _window: SimpleNamespace(account_name="测试公众号"))

    def create_cursor(self, **kwargs: object) -> _FakeCursor:
        self.cursor.trace = kwargs.get("trace")
        return self.cursor

    def create_clicker(self) -> _FakeClicker:
        self.clicker_created = True
        return self.clicker

    def create_tab_service(self) -> _FakeTabs:
        self.tabs_created = True
        return _FakeTabs()


class _LegacyWindowClickFlowDateSelectionTests:
    """旧 HomeArticleCursor 窗口测试约束；新 UIA 卡片流程由独立测试覆盖。"""
    def test_repeated_real_scroll_operations_are_not_collapsed(self) -> None:
        scroll_event = {
            "event": "scroll-dispatch",
            "status": "success",
            "message": "向下滚动 5 步已发送",
            "details": {
                "direction": "down",
                "wheelSteps": 5,
                "succeeded": True,
            },
        }
        factory = _FakeWindowFactory(
            [_target("正常文章", "2026-08-10")],
            trace_events=[scroll_event, dict(scroll_event)],
        )
        window_config = SimpleNamespace(
            home_find_timeout_seconds=1,
        )

        result = WindowClickFlowDiagnosticService(
            config=SimpleNamespace(window=window_config),
            window_factory=factory,
        ).run(max_records=1)

        scroll_items = [
            event
            for event in result["events"]
            if event.get("kind") == "operation"
            and event.get("label") == "滚动操作"
        ]
        self.assertEqual(len(scroll_items), 2)

    def test_popup_items_only_contain_successfully_recognized_articles(self) -> None:
        trace_event = {
            "event": "viewport-read",
            "status": "success",
            "message": "第 1 次页面读取完成：识别 1 条，丢弃 1 条",
            "details": {
                "scanCount": 1,
                "rangeCount": 8,
                "targetCount": 1,
                "discardedCount": 1,
                "durationSeconds": 0.214,
            },
            "decisions": [
                {
                    "status": "discarded",
                    "titleFragment": "被裁切的候选标题",
                    "dateText": "8月10日",
                    "metricText": "阅读 8",
                    "reason": "阅读指标没有完整位于主页可视区",
                }
            ],
        }
        factory = _FakeWindowFactory(
            [_target("正常文章", "2026-08-10")],
            trace_event=trace_event,
        )
        updates: list[dict[str, object]] = []
        window_config = SimpleNamespace(
            home_find_timeout_seconds=1,
        )

        result = WindowClickFlowDiagnosticService(
            config=SimpleNamespace(window=window_config),
            window_factory=factory,
        ).run(max_records=1, on_update=updates.append)

        relevant = [
            event
            for event in result["events"]
            if event.get("kind") in {"operation", "discarded", "article"}
            and event.get("label") in {"页面读取", "丢弃候选", "第 1 条文章"}
        ]
        self.assertEqual(
            [(event["kind"], event["label"]) for event in relevant],
            [
                ("operation", "页面读取"),
                ("discarded", "丢弃候选"),
                ("article", "第 1 条文章"),
            ],
        )
        discarded = relevant[1]
        self.assertEqual(discarded["value"], "被裁切的候选标题")
        self.assertIn(
            {"label": "具体原因", "value": "阅读指标没有完整位于主页可视区"},
            discarded["cells"],
        )
        self.assertTrue(updates)
        self.assertTrue(
            all(
                item.get("kind") == "article"
                for update in updates
                for item in update["items"]
            )
        )
        self.assertEqual(
            [item.get("kind") for item in result["items"]],
            ["article"],
        )

    def test_date_filter_skip_is_recorded_with_title_and_reason(self) -> None:
        factory = _FakeWindowFactory(
            [
                _target("日期过新的文章", "2026-08-11"),
                _target("范围内文章", "2026-08-10"),
            ]
        )
        window_config = SimpleNamespace(
            home_find_timeout_seconds=1,
        )

        result = WindowClickFlowDiagnosticService(
            config=SimpleNamespace(window=window_config),
            window_factory=factory,
        ).run(
            max_records=1,
            date_filter_mode="range",
            start_date="2026-08-01",
            end_date="2026-08-10",
        )

        skipped = [
            event
            for event in result["events"]
            if event.get("kind") == "discarded"
            and event.get("value") == "日期过新的文章"
        ]
        self.assertEqual(len(skipped), 1)
        self.assertIn("不符合日期条件", skipped[0]["cells"][-1]["value"])

    def test_range_skips_newer_candidates_and_stops_before_older_candidates(self) -> None:
        targets = [
            _target("更新文章", "2026-08-11"),
            _target("范围上边界", "2026-08-10"),
            _target("范围下边界", "2026-08-01"),
            _target("已经过期", "2026-07-31"),
            _target("不应继续读取", "2026-07-01"),
        ]
        factory = _FakeWindowFactory(targets)
        window_config = SimpleNamespace(
            home_find_timeout_seconds=1,
            article_open_timeout_seconds=1,
            article_title_poll_interval_seconds=0.01,
            article_title_stable_delay_seconds=0,
        )

        result = WindowClickFlowDiagnosticService(
            config=SimpleNamespace(window=window_config),
            window_factory=factory,
        ).run(
            max_records=3,
            date_filter_mode="range",
            start_date="2026-08-01",
            end_date="2026-08-10",
        )

        self.assertEqual(factory.clicker.titles, [])
        self.assertEqual(result["status"], "date-boundary")
        self.assertEqual(result["recognizedCount"], 2)
        self.assertEqual(result["skippedCount"], 1)
        self.assertFalse(factory.guard_created)
        self.assertFalse(factory.guard_activated)
        self.assertFalse(factory.clicker_created)
        self.assertFalse(factory.tabs_created)
        self.assertNotIn("clickedCount", result)
        self.assertNotIn("openedCount", result)
        self.assertNotIn("closedCount", result)
        self.assertEqual(
            [item["title"] for item in result["records"]],
            ["范围上边界", "范围下边界"],
        )


class WindowClickFlowTraceStoreTests(unittest.TestCase):
    def test_trace_store_writes_raw_execution_events_and_final_result(self) -> None:
        try:
            from src.modules.system.window_diagnostic_trace_store import (
                WindowDiagnosticTraceStore,
            )
        except ModuleNotFoundError as exc:
            self.fail(f"窗口诊断记录模块尚未实现：{exc}")

        with TemporaryDirectory() as temp_dir:
            store = WindowDiagnosticTraceStore(
                temp_root=Path(temp_dir),
                job_id="window-click-flow-test001",
            )
            store.append_event(
                {
                    "event": "viewport-read",
                    "status": "loading",
                    "message": "页面读取完成",
                    "details": {"rangeCount": 8, "targetCount": 1},
                    "decisions": [{"status": "discarded", "reason": "标题缺失"}],
                }
            )
            store.append_event(
                {
                    "kind": "operation",
                    "tone": "success",
                    "label": "窗口定位",
                    "value": "已找到公众号主页窗口",
                }
            )
            store.write_result(
                {
                    "status": "completed",
                    "records": [{"title": "测试文章"}],
                    "events": [{"kind": "article", "value": "已识别"}],
                }
            )

            self.assertTrue(store.execution_log_path.is_file())
            self.assertTrue(store.result_path.is_file())
            self.assertTrue(store.trace_dir.is_relative_to(Path(temp_dir).resolve()))
            lines = [
                json.loads(line)
                for line in store.execution_log_path.read_text(encoding="utf-8").splitlines()
            ]
            line = lines[0]
            self.assertEqual(line["sequence"], 1)
            self.assertTrue(line["recordedAt"])
            self.assertEqual(line["details"]["rangeCount"], 8)
            self.assertEqual(line["decisions"][0]["reason"], "标题缺失")
            self.assertEqual(lines[1]["event"], "operation")
            self.assertEqual(lines[1]["status"], "success")
            self.assertEqual(lines[1]["message"], "已找到公众号主页窗口")
            self.assertEqual(lines[1]["details"], {})
            self.assertEqual(lines[1]["decisions"], [])
            result = json.loads(store.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["records"][0]["title"], "测试文章")
            self.assertEqual(result["events"][0]["kind"], "article")

    def test_start_get_and_stop_are_forwarded_to_huey_service(self) -> None:
        with TemporaryDirectory() as temp_dir:
            huey_service = _FakeWindowClickFlowHueyService(Path(temp_dir))
            backend = _trace_backend(Path(temp_dir), huey_service)
            initial = _start_window_click_flow_diagnostic_job(
                backend,
                WindowClickFlowDiagnosticPayload(maxRecords=3),
            )
            current = _window_click_flow_diagnostic_job_payload(
                backend,
                initial["jobId"],
            )
            stopped = _stop_window_click_flow_diagnostic_job(
                backend,
                initial["jobId"],
            )

            self.assertEqual(initial["items"], [])
            self.assertEqual(current["status"], "running")
            self.assertEqual(stopped["status"], "stop-requested")
            self.assertEqual(
                huey_service.start_calls,
                [
                    {
                        "max_records": 3,
                        "date_filter_mode": "all",
                        "start_date": None,
                        "end_date": None,
                    }
                ],
            )
            self.assertEqual(huey_service.get_calls, [initial["jobId"]])
            self.assertEqual(huey_service.stop_calls, [initial["jobId"]])
            trace_dir = Path(initial["traceDir"])
            self.assertTrue(trace_dir.is_relative_to(Path(temp_dir).resolve()))
            self.assertEqual(Path(initial["executionLogPath"]).name, "execution.jsonl")
            self.assertEqual(Path(initial["resultPath"]).name, "result.json")

    def test_conflict_and_missing_job_keep_http_error_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            huey_service = _FakeWindowClickFlowHueyService(Path(temp_dir))
            huey_service.start_error = WindowClickFlowConflictError("已有任务")
            backend = _trace_backend(Path(temp_dir), huey_service)

            conflict = _start_window_click_flow_diagnostic_job(
                backend,
                WindowClickFlowDiagnosticPayload(maxRecords=1),
            )
            missing_get = _window_click_flow_diagnostic_job_payload(
                backend,
                "window-click-flow-missing",
            )
            missing_stop = _stop_window_click_flow_diagnostic_job(
                backend,
                "window-click-flow-missing",
            )

            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(missing_get.status_code, 404)
            self.assertEqual(missing_stop.status_code, 404)

    def test_backend_shutdown_stops_huey_service(self) -> None:
        huey_service = _FakeWindowClickFlowHueyService(Path.cwd())
        backend = SimpleNamespace(
            offline_cache_service=None,
            window_click_flow_huey_service=huey_service,
            diagnostic_mitm_listener=None,
            active_task_id=None,
            append_log=lambda *_args, **_kwargs: None,
        )

        shutdown_backend(backend)

        self.assertEqual(huey_service.shutdown_calls, 1)


def _target(title: str, published_date: str) -> ArticleTarget:
    return ArticleTarget(
        account_name="测试公众号",
        title=title,
        click_x=100,
        click_y=200,
        home_window_handle=100,
        fingerprint=f"{published_date}-{title}",
        date_text=published_date,
        published_date=published_date,
        metric_text="阅读 10",
        metric_rect=(80, 190, 160, 210),
    )


class _FakeWindowClickFlowHueyService:
    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir.resolve()
        self.start_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.shutdown_calls = 0
        self.start_error: Exception | None = None
        self._job_id = "window-click-flow-test001"

    def start(self, **options) -> dict:
        self.start_calls.append(dict(options))
        if self.start_error is not None:
            raise self.start_error
        return self._payload()

    def _payload(self) -> dict:
        trace_dir = self.temp_dir / "window-click-flow" / self._job_id
        return {
            "ok": False,
            "status": "running",
            "jobId": self._job_id,
            "action": "window-click-flow",
            "title": "主页内容读取结果",
            "message": "正在等待Huey执行主页内容读取测试...",
            "tone": "info",
            "items": [],
            "traceDir": str(trace_dir),
            "executionLogPath": str(trace_dir / "execution.jsonl"),
            "resultPath": str(trace_dir / "result.json"),
        }

    def get(self, job_id: str) -> dict:
        self.get_calls.append(job_id)
        if job_id != self._job_id:
            raise KeyError(job_id)
        return self._payload()

    def stop(self, job_id: str) -> dict:
        self.stop_calls.append(job_id)
        if job_id != self._job_id:
            raise KeyError(job_id)
        return {**self._payload(), "status": "stop-requested"}

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _trace_backend(
    temp_dir: Path,
    huey_service: _FakeWindowClickFlowHueyService,
) -> SimpleNamespace:
    config = SimpleNamespace(storage=SimpleNamespace(temp_dir=temp_dir))
    return SimpleNamespace(
        runtime=SimpleNamespace(config=config),
        window_click_flow_huey_service=huey_service,
    )


if __name__ == "__main__":
    unittest.main()

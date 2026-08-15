from __future__ import annotations

import unittest
from unittest.mock import patch

from src.modules.window.article_card_reader import UiaArticleCardReader
from src.modules.window.uia_article_group_parser import UiaArticleGroupParser
from src.modules.window.window_models import WindowInfo
from src.services.runtime.window_click_flow_diagnostic_service import _record_item


Rect = tuple[int, int, int, int]


class UiaArticleGroupParserTests(unittest.TestCase):
    def test_parses_multiple_article_cards_from_one_date_group(self) -> None:
        document = _document(
            _date_group(
                "8月7日",
                (100, 70, 160, 90),
                _article_card(
                    "第一篇完整标题",
                    (100, 110, 320, 150),
                    "阅读 888 赞 16",
                    (100, 160, 230, 180),
                ),
                _article_card(
                    "第二篇完整标题",
                    (100, 210, 320, 250),
                    "阅读 244 赞 9",
                    (100, 260, 220, 280),
                ),
            )
        )

        observation = UiaArticleGroupParser().parse(
            document,
            viewport=(0, 0, 500, 500),
            content_top=60,
        )

        self.assertEqual(observation.group_count, 1)
        self.assertEqual(
            [card.raw_title for card in observation.cards],
            ["第一篇完整标题", "第二篇完整标题"],
        )
        self.assertEqual(
            [card.metric_text for card in observation.cards],
            ["阅读 888 赞 16", "阅读 244 赞 9"],
        )
        self.assertEqual(
            [card.date_text for card in observation.cards],
            ["8月7日", "8月7日"],
        )

    def test_uses_own_group_date_when_previous_date_node_is_offscreen(self) -> None:
        document = _document(
            _date_group(
                "昨天",
                (100, -40, 150, -20),
                _article_card(
                    "上一组文章",
                    (100, 90, 300, 125),
                    "阅读 10",
                    (100, 135, 180, 155),
                ),
                rect=(80, -60, 420, 180),
            ),
            _date_group(
                "8月7日",
                (100, 210, 160, 230),
                _article_card(
                    "下一组文章",
                    (100, 250, 300, 285),
                    "阅读 20",
                    (100, 295, 180, 315),
                ),
                rect=(80, 190, 420, 340),
            ),
        )

        observation = UiaArticleGroupParser().parse(
            document,
            viewport=(0, 0, 500, 500),
            content_top=60,
        )

        self.assertEqual(
            [(card.raw_title, card.date_text) for card in observation.cards],
            [("上一组文章", "昨天"), ("下一组文章", "8月7日")],
        )
        self.assertIsNone(observation.cards[0].date_rect)
        self.assertEqual(observation.cards[1].date_rect, (100, 210, 160, 230))

    def test_uses_leaf_text_control_once_when_parent_repeats_same_name(self) -> None:
        document = _document(
            _date_group(
                "今天",
                (100, 70, 150, 90),
                _article_card(
                    "不会重复拼接的完整标题",
                    (100, 110, 330, 150),
                    "阅读 30 赞 2",
                    (100, 160, 210, 180),
                ),
            )
        )

        observation = UiaArticleGroupParser().parse(
            document,
            viewport=(0, 0, 500, 500),
            content_top=60,
        )

        self.assertEqual(len(observation.cards), 1)
        self.assertEqual(observation.cards[0].raw_title, "不会重复拼接的完整标题")
        self.assertEqual(observation.cards[0].title_rect, (100, 110, 330, 150))

    def test_discards_card_when_metric_is_not_fully_inside_viewport(self) -> None:
        document = _document(
            _date_group(
                "今天",
                (100, 410, 150, 430),
                _article_card(
                    "屏幕底部文章",
                    (100, 450, 300, 480),
                    "阅读 40",
                    (100, 490, 180, 510),
                ),
                rect=(80, 390, 420, 530),
            )
        )

        observation = UiaArticleGroupParser().parse(
            document,
            viewport=(0, 0, 500, 500),
            content_top=60,
        )

        self.assertEqual(observation.cards, ())
        self.assertEqual(len(observation.decisions), 1)
        self.assertEqual(
            observation.decisions[0]["reason"],
            "阅读指标没有完整位于主页可视区",
        )
        self.assertEqual(observation.decisions[0]["titleFragment"], "屏幕底部文章")


class UiaArticleCardReaderIntegrationTests(unittest.TestCase):
    @patch(
        "src.modules.window.article_card_reader._visible_range_targets",
        side_effect=AssertionError("控件树成功时不能使用 TextPattern 划分文章"),
    )
    def test_control_tree_is_primary_when_text_pattern_contains_mixed_range(
        self,
        _parse_visible_ranges: object,
    ) -> None:
        document = _document(
            _date_group(
                "昨天",
                (100, -40, 150, -20),
                _article_card(
                    "上一组完整文章",
                    (100, 90, 300, 125),
                    "阅读 10",
                    (100, 135, 180, 155),
                ),
                rect=(80, -60, 420, 180),
            ),
            _date_group(
                "8月7日",
                (100, 210, 160, 230),
                _article_card(
                    "下一组完整文章",
                    (100, 250, 300, 285),
                    "阅读 20",
                    (100, 295, 180, 315),
                ),
                rect=(80, 190, 420, 340),
            ),
            visible_ranges=(
                _FakeTextRange("标题尾部\n阅读 10\n下一个标题开头", (100, 90, 300, 155)),
            ),
        )
        home_window = WindowInfo(
            1,
            "微信",
            "Chrome_WidgetWin_0",
            "WeChatAppEx.exe",
            (0, 0, 500, 500),
            control=document,
        )

        observation = UiaArticleCardReader().read_viewport(
            home_window,
            account_name="测试公众号",
        )

        self.assertEqual(
            [(target.raw_title, target.date_text) for target in observation.targets],
            [("上一组完整文章", "昨天"), ("下一组完整文章", "8月7日")],
        )
        self.assertIsNone(observation.targets[0].date_rect)
        self.assertEqual(observation.targets[0].metric_rect, (100, 135, 180, 155))

    def test_diagnostic_displays_card_visible_rect_and_center_point(self) -> None:
        item = _record_item(
            {
                "index": 1,
                "title": "测试文章",
                "rawTitle": "测试文章",
                "dateText": "昨天",
                "publishedDate": "2026-08-14",
                "dateRect": None,
                "titleRect": (100, 90, 300, 125),
                "cardRect": (80, 70, 420, 180),
                "visibleRect": (80, 80, 420, 180),
                "visibleHeight": 100,
                "clickPoint": (250, 130),
            }
        )

        values = {cell["label"]: cell["value"] for cell in item["cells"]}
        self.assertEqual(values["完整卡片坐标"], "(80, 70) - (420, 180)")
        self.assertEqual(values["可视卡片坐标"], "(80, 80) - (420, 180)")
        self.assertEqual(values["可视高度"], "100 px")
        self.assertEqual(values["中心点"], "(250, 130)")


class _FakeControl:
    def __init__(
        self,
        *,
        control_type: str,
        name: str = "",
        rect: Rect = (0, 0, 0, 0),
        children: tuple["_FakeControl", ...] = (),
        visible_ranges: tuple["_FakeTextRange", ...] = (),
    ) -> None:
        self.ControlTypeName = control_type
        self.Name = name
        self.BoundingRectangle = rect
        self.IsOffscreen = False
        self.AutomationId = ""
        self.NativeWindowHandle = 0
        self._children = children
        self._visible_ranges = visible_ranges

    def GetChildren(self) -> tuple["_FakeControl", ...]:
        return self._children

    def GetTextPattern(self) -> "_FakeTextPattern":
        return _FakeTextPattern(self._visible_ranges)


def _document(
    *children: _FakeControl,
    visible_ranges: tuple["_FakeTextRange", ...] = (),
) -> _FakeControl:
    return _FakeControl(
        control_type="DocumentControl",
        rect=(0, 0, 500, 1000),
        children=(_group(*children, rect=(50, -100, 450, 1000)),),
        visible_ranges=visible_ranges,
    )


def _date_group(
    date_text: str,
    date_rect: Rect,
    *cards: _FakeControl,
    rect: Rect = (80, 50, 420, 350),
) -> _FakeControl:
    date_row = _group(
        _leaf_text(date_text, date_rect),
        rect=(80, date_rect[1] - 10, 420, date_rect[3] + 10),
    )
    return _group(date_row, *cards, rect=rect)


def _article_card(
    title: str,
    title_rect: Rect,
    metric: str,
    metric_rect: Rect,
) -> _FakeControl:
    title_leaf = _leaf_text(title, title_rect)
    # Chromium 的 UIA 树会让父、子 TextControl 暴露相同 Name；只有叶子节点可信。
    title_parent = _FakeControl(
        control_type="TextControl",
        name=title,
        rect=(title_rect[0] - 1, title_rect[1] - 1, title_rect[2] + 1, title_rect[3] + 1),
        children=(title_leaf,),
    )
    metric_leaf = _leaf_text(metric, metric_rect)
    metric_group = _group(
        metric_leaf,
        rect=(metric_rect[0], metric_rect[1] - 1, metric_rect[2] + 20, metric_rect[3] + 1),
    )
    content_group = _group(
        title_parent,
        metric_group,
        rect=(title_rect[0], title_rect[1] - 5, title_rect[2] + 20, metric_rect[3] + 5),
    )
    thumbnail_group = _group(
        rect=(350, title_rect[1], 420, metric_rect[3]),
    )
    return _group(
        content_group,
        thumbnail_group,
        rect=(80, title_rect[1] - 10, 420, metric_rect[3] + 10),
    )


def _leaf_text(name: str, rect: Rect) -> _FakeControl:
    return _FakeControl(control_type="TextControl", name=name, rect=rect)


def _group(*children: _FakeControl, rect: Rect) -> _FakeControl:
    return _FakeControl(control_type="GroupControl", rect=rect, children=children)


class _FakeTextPattern:
    def __init__(self, visible_ranges: tuple["_FakeTextRange", ...]) -> None:
        self._visible_ranges = visible_ranges

    def GetVisibleRanges(self) -> tuple["_FakeTextRange", ...]:
        return self._visible_ranges


class _FakeTextRange:
    def __init__(self, text: str, rect: Rect) -> None:
        self._text = text
        self._rect = rect

    def GetText(self, _limit: int) -> str:
        return self._text

    def GetBoundingRectangles(self) -> tuple[Rect, ...]:
        return (self._rect,)


if __name__ == "__main__":
    unittest.main()

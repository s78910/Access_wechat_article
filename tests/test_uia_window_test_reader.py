from __future__ import annotations

import unittest
from unittest.mock import patch

from src.modules.window.uia_window_test_reader import UiaWindowTestReader
from src.modules.window.window_models import WindowInfo


Rect = tuple[int, int, int, int]


class UiaWindowTestReaderTests(unittest.TestCase):
    def test_date_group_read_uses_reverse_siblings_without_expanding_list(self) -> None:
        old_group = _date_group(
            "8月9日",
            _article_card("older visible article", rect=(80, 80, 420, 160)),
        )
        target_group = _date_group(
            "8月8日",
            _article_card("target article", rect=(80, 300, 420, 380)),
        )
        loading = _text("正在加载...", (220, 460, 300, 480))
        article_list = _group(
            old_group,
            target_group,
            loading,
            rect=(60, 60, 440, 500),
            forbid_get_children=True,
        )
        document = _document(
            _group(_navigation(), article_list, rect=(0, 0, 500, 500))
        )

        snapshot = UiaWindowTestReader().read_date_groups(_home_window(document))

        self.assertEqual(snapshot.content_viewport, (0, 60, 500, 500))
        self.assertEqual(
            [group.date_text for group in snapshot.groups],
            ["8月9日", "8月8日"],
        )
        self.assertEqual(article_list.get_children_calls, 0)
        self.assertEqual(snapshot.node_count, 3)
        self.assertTrue(snapshot.loading)

    def test_offscreen_loading_sentinel_is_not_active_loading(self) -> None:
        article_list = _group(
            _date_group(
                "8月14日",
                _article_card("target article", rect=(80, 100, 420, 180)),
            ),
            _text("正在加载...", (220, 900, 300, 930)),
            rect=(60, 60, 440, 930),
            forbid_get_children=True,
        )
        document = _document(_group(article_list, rect=(0, 0, 500, 500)))

        snapshot = UiaWindowTestReader().read_date_groups(_home_window(document))

        self.assertFalse(snapshot.loading)

    def test_load_more_control_is_not_active_loading(self) -> None:
        article_list = _group(
            _date_group(
                "8月14日",
                _article_card("target article", rect=(80, 100, 420, 180)),
            ),
            _text("加载更多", (220, 460, 300, 480)),
            rect=(60, 60, 440, 500),
            forbid_get_children=True,
        )
        document = _document(_group(article_list, rect=(0, 0, 500, 500)))

        snapshot = UiaWindowTestReader().read_date_groups(_home_window(document))

        self.assertFalse(snapshot.loading)

    def test_offscreen_loading_control_with_stale_visible_rect_is_not_active(self) -> None:
        article_list = _group(
            _date_group(
                "8月14日",
                _article_card("target article", rect=(80, 100, 420, 180)),
            ),
            _text("正在加载...", (220, 460, 300, 480), is_offscreen=True),
            rect=(60, 60, 440, 500),
            forbid_get_children=True,
        )
        document = _document(_group(article_list, rect=(0, 0, 500, 500)))

        snapshot = UiaWindowTestReader().read_date_groups(_home_window(document))

        self.assertFalse(snapshot.loading)

    def test_date_group_read_keeps_only_tail_window_around_viewport(self) -> None:
        offscreen_above = tuple(
            _date_group(
                "8月10日",
                _article_card(f"old-{index}", rect=(80, -5000 + index * 80, 420, -4940 + index * 80)),
                group_rect=(60, -5000 + index * 80, 440, -4940 + index * 80),
            )
            for index in range(40)
        )
        boundary_above = _date_group(
            "8月9日",
            _article_card("above", rect=(80, -50, 420, -20)),
            group_rect=(60, -50, 440, -20),
        )
        visible = _date_group(
            "8月9日",
            _article_card("visible", rect=(80, 100, 420, 180)),
            group_rect=(60, 100, 440, 180),
        )
        below = _date_group(
            "8月8日",
            _article_card("below", rect=(80, 520, 420, 600)),
            group_rect=(60, 520, 440, 600),
        )
        article_list = _group(
            *offscreen_above,
            boundary_above,
            visible,
            below,
            rect=(60, -5000, 440, 600),
            forbid_get_children=True,
        )
        document = _document(_group(article_list, rect=(0, 0, 500, 500)))

        snapshot = UiaWindowTestReader().read_date_groups(_home_window(document))

        self.assertEqual(
            [group.date_text for group in snapshot.groups],
            ["8月10日", "8月10日", "8月9日", "8月9日", "8月8日"],
        )
        self.assertEqual(len(snapshot.visible_groups), 1)
        self.assertEqual(snapshot.node_count, 5)

    def test_date_group_read_does_not_parse_article_cards(self) -> None:
        document = _document(
            _navigation(),
            _date_group(
                "8月7日",
                _article_card("不应在定位阶段解析", rect=(80, 100, 420, 190)),
            ),
        )

        with patch(
            "src.modules.window.uia_window_test_reader._article_card",
            side_effect=AssertionError("日期定位阶段不应解析文章卡片"),
        ):
            snapshot = UiaWindowTestReader().read_date_groups(_home_window(document))

        self.assertEqual(
            [(group.date_text, group.published_date) for group in snapshot.visible_groups],
            [("8月7日", "2026-08-07")],
        )

    def test_date_group_direct_card_does_not_require_read_metric(self) -> None:
        full_title = "主题党日| 医心向党筑根基 多元研学淬初心——完整标题结尾"
        article_list = _group(
            _date_group(
                "8月7日",
                _article_card(full_title, rect=(80, 100, 420, 190)),
                _article_card("第二篇文章", rect=(80, 190, 420, 280)),
            ),
            rect=(60, 65, 440, 500),
            forbid_get_children=True,
        )
        document = _document(
            _navigation(),
            article_list,
        )

        snapshot = UiaWindowTestReader().read(_home_window(document))

        self.assertEqual(article_list.get_children_calls, 0)
        self.assertEqual(snapshot.content_viewport, (0, 60, 500, 500))
        self.assertEqual(len(snapshot.groups), 1)
        self.assertEqual(snapshot.groups[0].date_text, "8月7日")
        self.assertEqual(
            [card.raw_title for card in snapshot.groups[0].cards],
            [full_title, "第二篇文章"],
        )
        self.assertEqual(
            [card.marker for card in snapshot.visible_cards],
            [("8月7日", full_title), ("8月7日", "第二篇文章")],
        )
        self.assertEqual(snapshot.visible_cards[0].card_rect, (80, 100, 420, 190))
        self.assertEqual(snapshot.visible_cards[0].click_point, (250, 145))

    def test_partial_card_uses_visible_intersection_and_ten_pixel_threshold(self) -> None:
        document = _document(
            _navigation(),
            _date_group(
                "昨天",
                _article_card("顶部露出十像素", rect=(80, 40, 420, 70)),
                _article_card("底部只露出九像素", rect=(80, 491, 420, 540)),
            ),
        )

        snapshot = UiaWindowTestReader(min_visible_height=10).read(
            _home_window(document)
        )

        self.assertEqual(
            [card.raw_title for card in snapshot.visible_cards],
            ["顶部露出十像素"],
        )
        visible = snapshot.visible_cards[0]
        self.assertEqual(visible.card_rect, (80, 40, 420, 70))
        self.assertEqual(visible.visible_rect, (80, 60, 420, 70))
        self.assertEqual(visible.visible_height, 10)
        self.assertEqual(visible.click_point, (250, 65))
        self.assertEqual(len(snapshot.all_cards), 2)


class _FakeControl:
    def __init__(
        self,
        control_type: str,
        *,
        name: str = "",
        rect: Rect = (0, 0, 0, 0),
        children: tuple["_FakeControl", ...] = (),
        forbid_get_children: bool = False,
        is_offscreen: bool = False,
    ) -> None:
        self.ControlTypeName = control_type
        self.Name = name
        self.BoundingRectangle = rect
        self.AutomationId = ""
        self.IsOffscreen = is_offscreen
        self._children = children
        self._parent: _FakeControl | None = None
        self._forbid_get_children = forbid_get_children
        self.get_children_calls = 0
        for child in children:
            child._parent = self

    def GetChildren(self) -> tuple["_FakeControl", ...]:
        self.get_children_calls += 1
        if self._forbid_get_children:
            raise AssertionError("article list must not be expanded with GetChildren")
        return self._children

    def GetFirstChildControl(self) -> "_FakeControl | None":
        return self._children[0] if self._children else None

    def GetLastChildControl(self) -> "_FakeControl | None":
        return self._children[-1] if self._children else None

    def GetNextSiblingControl(self) -> "_FakeControl | None":
        if self._parent is None:
            return None
        index = self._parent._children.index(self)
        return (
            self._parent._children[index + 1]
            if index + 1 < len(self._parent._children)
            else None
        )

    def GetPreviousSiblingControl(self) -> "_FakeControl | None":
        if self._parent is None:
            return None
        index = self._parent._children.index(self)
        return self._parent._children[index - 1] if index > 0 else None

    def GetRuntimeId(self) -> list[int]:
        return [id(self)]


def _home_window(document: _FakeControl) -> WindowInfo:
    return WindowInfo(
        1,
        "微信",
        "Chrome_WidgetWin_0",
        "WeChatAppEx.exe",
        (0, 0, 500, 500),
        control=document,
    )


def _document(*children: _FakeControl) -> _FakeControl:
    return _FakeControl(
        "DocumentControl",
        rect=(0, 0, 500, 500),
        children=children,
    )


def _navigation() -> _FakeControl:
    return _group(
        _text("全部", (80, 35, 120, 60)),
        _text("贴图", (130, 35, 170, 60)),
        _text("文章", (180, 35, 220, 60)),
        _text("视频号", (230, 35, 290, 60)),
        rect=(60, 30, 440, 60),
    )


def _date_group(
    date_text: str,
    *cards: _FakeControl,
    group_rect: Rect = (60, 65, 440, 540),
) -> _FakeControl:
    top = group_rect[1]
    date_row = _group(
        _text(date_text, (80, top + 5, 140, top + 25)),
        rect=(60, top, 440, top + 30),
    )
    return _group(date_row, *cards, rect=group_rect)


def _article_card(title: str, *, rect: Rect) -> _FakeControl:
    title_leaf = _text(title, (rect[0] + 20, rect[1] + 10, rect[2] - 20, rect[3] - 20))
    thumbnail = _group(rect=(rect[2] - 80, rect[1] + 10, rect[2] - 10, rect[3] - 10))
    return _group(title_leaf, thumbnail, rect=rect)


def _text(name: str, rect: Rect, *, is_offscreen: bool = False) -> _FakeControl:
    return _FakeControl(
        "TextControl",
        name=name,
        rect=rect,
        is_offscreen=is_offscreen,
    )


def _group(
    *children: _FakeControl,
    rect: Rect,
    forbid_get_children: bool = False,
) -> _FakeControl:
    return _FakeControl(
        "GroupControl",
        rect=rect,
        children=children,
        forbid_get_children=forbid_get_children,
    )


if __name__ == "__main__":
    unittest.main()

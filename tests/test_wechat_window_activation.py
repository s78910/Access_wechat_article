from __future__ import annotations

import unittest
from unittest.mock import patch

from src.core.config import AppFeatureConfig, AppRuntimeConfig
from src.core.task_manager import TaskManager
from src.workers import home_article_clicker
from src.workers import wechat_detail_windows
from src.workers import wechat_home
from src.workers.wechat_home import WeChatHomeSnapshot


class FakeWindow:
    Name = "公众号"
    ClassName = "Chrome_WidgetWin_0"
    NativeWindowHandle = 12345
    ProcessId = 100

    def GetChildren(self):
        return []


class FakeRect:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeControl:
    def __init__(
        self,
        name: str,
        *,
        children: list["FakeControl"] | None = None,
        hwnd: int = 0,
        rect: tuple[int, int, int, int] = (0, 0, 0, 0),
        control_type: str = "TextControl",
    ) -> None:
        self.Name = name
        self.Value = ""
        self.ControlTypeName = control_type
        self.ClassName = ""
        self.NativeWindowHandle = hwnd
        self.BoundingRectangle = FakeRect(*rect)
        self._children = children or []

    def GetChildren(self):
        return self._children


class FakeAutoModule:
    @staticmethod
    def GetRootControl():
        return FakeRootControl()

    @staticmethod
    def ControlFromHandle(_hwnd):
        return None


class FakeRootControl:
    def GetChildren(self):
        return [FakeWindow()]


class FakeAutoModuleWithWindows:
    def __init__(self, windows: list[FakeControl]) -> None:
        self._windows = windows

    def GetRootControl(self):
        return FakeRootControlWithWindows(self._windows)

    def ControlFromHandle(self, _hwnd):
        return None


class FakeRootControlWithWindows:
    def __init__(self, windows: list[FakeControl]) -> None:
        self._windows = windows

    def GetChildren(self):
        return self._windows


class WechatWindowActivationTest(unittest.TestCase):
    def test_home_parser_reads_header_account_when_sticker_cards_are_visible(self) -> None:
        snapshot = wechat_home.parse_wechat_home_text(
            "\n".join(
                [
                    "公众号",
                    "新华社",
                    "全部",
                    "贴图",
                    "文章",
                    "视频号",
                    "阅读 10万+ 赞 860",
                    "今天",
                    "早知天下事〔2026.06.21〕",
                    "阅读 5.7万 赞 1311",
                    "贴图",
                    "全部",
                    "夏至，喜至！",
                    "阅读 9.5万 赞 2922",
                    "端午安康！",
                    "阅读 10万+ 赞 3997",
                    "昨天",
                    "夜读 | 老爸，我想您了！",
                    "阅读 10万+ 赞 5145",
                ]
            )
        )

        self.assertTrue(snapshot.found)
        self.assertEqual(snapshot.account_name, "新华社")
        self.assertEqual(snapshot.status, "partial")
        self.assertEqual(snapshot.account_confidence, "high")
        self.assertEqual(snapshot.account_source, "profile_header")

    def test_home_parser_rejects_content_list_as_account_when_header_missing(self) -> None:
        snapshot = wechat_home.parse_wechat_home_text(
            "\n".join(
                [
                    "全部",
                    "贴图",
                    "文章",
                    "视频号",
                    "今天",
                    "早知天下事〔2026.06.21〕",
                    "阅读 5.7万 赞 1311",
                    "贴图",
                    "全部",
                    "夏至，喜至！",
                    "阅读 9.5万 赞 2922",
                    "端午安康！",
                    "阅读 10万+ 赞 3997",
                ]
            )
        )

        self.assertFalse(snapshot.found)
        self.assertNotEqual(snapshot.account_name, "夏至，喜至！")
        self.assertEqual(snapshot.status, "content_only")
        self.assertEqual(snapshot.account_confidence, "low")
        self.assertEqual(snapshot.account_source, "content_list")

    def test_home_parser_does_not_treat_wechat_shell_title_as_account(self) -> None:
        snapshot = wechat_home.parse_wechat_home_text("\n".join(["微信", "Weixin", "MMUIRenderSubWindowHW"]))

        self.assertFalse(snapshot.found)
        self.assertEqual(snapshot.status, "not_found")
        self.assertNotEqual(snapshot.account_name, "微信")

    def test_home_parser_keeps_top_account_when_sticker_content_is_visible_without_tabs(self) -> None:
        snapshot = wechat_home.parse_wechat_home_text(
            "\n".join(
                [
                    "公众号",
                    "新华社",
                    "夏至，喜至！",
                    "阅读 9.5万 赞 2922",
                    "端午安康！",
                    "阅读 10万+ 赞 3997",
                ]
            )
        )

        self.assertTrue(snapshot.found)
        self.assertEqual(snapshot.account_name, "新华社")
        self.assertEqual(snapshot.description, "未识别到主页简介")
        self.assertEqual(snapshot.status, "partial")
        self.assertEqual(snapshot.account_confidence, "medium")
        self.assertEqual(snapshot.account_source, "profile_text")

    def test_home_parser_reads_service_account_profile_after_tabs(self) -> None:
        snapshot = wechat_home.parse_wechat_home_text(
            "\n".join(
                [
                    "服务号",
                    "全部",
                    "贴图",
                    "文章",
                    "视频号",
                    "正在加载...",
                    "289篇原创内容",
                    "6个朋友关注",
                    "视频号 : 金领冠爱儿俱乐部",
                    "金领冠爱儿俱乐部",
                    "伊利集团中国奶粉销量第一！近70年匠心探索，中国母乳研究开拓者，铸就10大核心配方专利，懂营养，更懂中国宝宝成长所需。",
                    "展开",
                    "已关注",
                    "发消息",
                    "昨天",
                    "【有奖】积分清零月倒计时开始，7重福利齐发！速来薅~",
                    "阅读 4.37万 赞 390",
                ]
            )
        )

        self.assertTrue(snapshot.found)
        self.assertEqual(snapshot.status, "ready")
        self.assertEqual(snapshot.account_name, "金领冠爱儿俱乐部")
        self.assertEqual(
            snapshot.description,
            "伊利集团中国奶粉销量第一！近70年匠心探索，中国母乳研究开拓者，铸就10大核心配方专利，懂营养，更懂中国宝宝成长所需。",
        )
        self.assertEqual(snapshot.original_count, "289")
        self.assertEqual(snapshot.friend_follow_count, "6")
        self.assertEqual(snapshot.account_confidence, "high")

    def test_home_parser_does_not_treat_expand_control_as_service_account_name(self) -> None:
        snapshot = wechat_home.parse_wechat_home_text(
            "\n".join(
                [
                    "服务号",
                    "全部",
                    "贴图",
                    "文章",
                    "视频号",
                    "1362篇原创内容",
                    "11个朋友关注",
                    "视频号 : 星妈会",
                    "全部",
                    "「飞鹤星妈会」8500万中国妈妈都信赖的育儿品牌。因为更懂得，我们以科学知识和温暖陪伴，守护成长每一步。",
                    "展开",
                    "已关注",
                    "发消息",
                    "星期日",
                    "夏天娃手脚长泡别乱挤！汗疱疹3个护理误区，90%家长都中招（有奖）",
                    "阅读 3.5万 赞 120",
                ]
            )
        )

        self.assertTrue(snapshot.found)
        self.assertEqual(snapshot.account_name, "星妈会")
        self.assertNotEqual(snapshot.account_name, "展开")
        self.assertEqual(snapshot.original_count, "1362")
        self.assertEqual(snapshot.friend_follow_count, "11")

    def test_home_detector_accepts_service_account_window_without_process_name(self) -> None:
        service_window = FakeControl(
            "服务号",
            hwnd=100,
            rect=(100, 100, 900, 900),
            control_type="PaneControl",
        )
        service_window.ClassName = "Chrome_WidgetWin_0"
        service_window.ProcessId = 100
        auto_module = FakeAutoModuleWithWindows([service_window])

        with (
            patch.object(wechat_home.platform, "system", return_value="Windows"),
            patch.object(wechat_home, "_get_process_name", return_value=""),
            patch.object(
                wechat_home,
                "_collect_best_wechat_texts",
                return_value=[
                    "服务号",
                    "全部",
                    "贴图",
                    "文章",
                    "视频号",
                    "289篇原创内容",
                    "6个朋友关注",
                    "视频号 : 金领冠爱儿俱乐部",
                    "金领冠爱儿俱乐部",
                    "伊利集团中国奶粉销量第一！近70年匠心探索，中国母乳研究开拓者。",
                    "已关注",
                    "发消息",
                ],
            ),
        ):
            snapshot = wechat_home._detect_with_uiautomation(auto_module=auto_module)

        self.assertTrue(snapshot.found)
        self.assertEqual(snapshot.account_name, "金领冠爱儿俱乐部")

    def test_article_clicker_activates_home_window_before_collecting_targets(self) -> None:
        calls: list[str] = []
        window = FakeWindow()

        def activate(_window, **_kwargs):
            calls.append("activate")
            return {"ok": True, "reason": "activated"}

        def collect(_window, **_kwargs):
            calls.append("collect")
            return []

        with (
            patch.object(home_article_clicker, "activate_wechat_window_for_uia", side_effect=activate),
            patch.object(home_article_clicker, "collect_article_click_targets", side_effect=collect),
        ):
            result = home_article_clicker.trigger_home_article_open(
                {"wechat_home_activate_delay_seconds": 0},
                1,
                home_window=window,
            )

        self.assertEqual(result["reason"], "article_click_target_not_found")
        self.assertEqual(calls, ["activate", "collect"])

    def test_article_clicker_reads_win32_child_window_when_top_level_is_shell_only(self) -> None:
        shell_window = FakeControl(
            "公众号",
            hwnd=100,
            rect=(100, 100, 900, 900),
            control_type="PaneControl",
            children=[FakeControl("公众号", control_type="TextControl")],
        )
        article_title = FakeControl(
            "一篇真实文章标题",
            hwnd=200,
            rect=(220, 360, 780, 410),
            control_type="TextControl",
        )
        child_window = FakeControl(
            "公众号正文",
            hwnd=200,
            rect=(100, 100, 900, 900),
            control_type="DocumentControl",
            children=[article_title],
        )

        targets = home_article_clicker.collect_article_click_targets(
            shell_window,
            max_depth=4,
            max_nodes=100,
            child_hwnds_provider=lambda _hwnd: [200],
            control_from_handle=lambda _hwnd: child_window,
        )

        self.assertEqual([target.title for target in targets], ["一篇真实文章标题"])
        self.assertEqual(targets[0].hwnd, 200)

    def test_article_clicker_ignores_profile_description_before_article_titles(self) -> None:
        profile_description = FakeControl(
            "新华通讯社官方账号。硬新闻、暖故事、好朋友。",
            hwnd=200,
            rect=(353, 400, 969, 435),
            control_type="TextControl",
        )
        article_title = FakeControl(
            "归来方知山河重",
            hwnd=200,
            rect=(393, 755, 561, 785),
            control_type="TextControl",
        )
        home_window = FakeControl(
            "公众号正文",
            hwnd=200,
            rect=(100, 100, 900, 900),
            control_type="DocumentControl",
            children=[profile_description, article_title],
        )

        targets = home_article_clicker.collect_article_click_targets(
            home_window,
            max_depth=4,
            max_nodes=100,
        )

        self.assertEqual([target.title for target in targets], ["归来方知山河重"])

    def test_article_clicker_ignores_wechat_shell_render_window_text(self) -> None:
        shell_window = FakeControl(
            "微信",
            hwnd=200,
            rect=(100, 100, 900, 900),
            control_type="DocumentControl",
            children=[
                FakeControl("Weixin", hwnd=200, rect=(100, 100, 900, 900), control_type="TextControl"),
                FakeControl(
                    "MMUIRenderSubWindowHW",
                    hwnd=200,
                    rect=(100, 100, 900, 900),
                    control_type="TextControl",
                ),
            ],
        )

        targets = home_article_clicker.collect_article_click_targets(
            shell_window,
            max_depth=4,
            max_nodes=100,
        )

        self.assertEqual(targets, [])

    def test_article_clicker_prefers_regular_article_list_over_pinned_album_card(self) -> None:
        home_window = FakeControl(
            "公众号正文",
            hwnd=200,
            rect=(100, 100, 900, 900),
            control_type="DocumentControl",
            children=[
                FakeControl("全部", hwnd=200, rect=(353, 658, 409, 710), control_type="HyperlinkControl"),
                FakeControl("贴图", hwnd=200, rect=(457, 658, 513, 710), control_type="HyperlinkControl"),
                FakeControl("文章", hwnd=200, rect=(561, 658, 617, 710), control_type="HyperlinkControl"),
                FakeControl("归来方知山河重", hwnd=200, rect=(393, 755, 561, 785), control_type="TextControl"),
                FakeControl("转发给咱家人", hwnd=200, rect=(825, 755, 969, 785), control_type="TextControl"),
                FakeControl("置顶", hwnd=200, rect=(353, 829, 409, 864), control_type="TextControl"),
                FakeControl("2个内容", hwnd=200, rect=(377, 912, 478, 947), control_type="TextControl"),
                FakeControl("今天", hwnd=200, rect=(385, 1028, 433, 1058), control_type="TextControl"),
                FakeControl(
                    "收藏这张图，看球不迷糊！",
                    hwnd=200,
                    rect=(385, 1114, 901, 1154),
                    control_type="TextControl",
                ),
                FakeControl(
                    "阅读\u20067.7万\u2004\u2005赞\u2006796",
                    hwnd=200,
                    rect=(385, 1164, 594, 1194),
                    control_type="TextControl",
                ),
            ],
        )

        targets = home_article_clicker.collect_article_click_targets(
            home_window,
            max_depth=4,
            max_nodes=100,
        )

        self.assertEqual([target.title for target in targets], ["收藏这张图，看球不迷糊！"])

    def test_article_clicker_ignores_cards_inside_sticker_and_video_sections(self) -> None:
        home_window = FakeControl(
            "公众号正文",
            hwnd=200,
            rect=(100, 100, 900, 1400),
            control_type="DocumentControl",
            children=[
                FakeControl("全部", hwnd=200, rect=(155, 180, 215, 212), control_type="TextControl"),
                FakeControl("贴图", hwnd=200, rect=(235, 180, 295, 212), control_type="TextControl"),
                FakeControl("文章", hwnd=200, rect=(315, 180, 375, 212), control_type="TextControl"),
                FakeControl("视频号", hwnd=200, rect=(395, 180, 470, 212), control_type="TextControl"),
                FakeControl("叮叮！也能用心炖炄", hwnd=200, rect=(155, 250, 520, 292), control_type="TextControl"),
                FakeControl("阅读 3.7万 赞 208", hwnd=200, rect=(155, 300, 300, 322), control_type="TextControl"),
                FakeControl("封面不重要的话不听?", hwnd=200, rect=(155, 340, 520, 388), control_type="TextControl"),
                FakeControl("阅读 4.2万 赞 188", hwnd=200, rect=(155, 396, 300, 418), control_type="TextControl"),
                FakeControl("贴图", hwnd=200, rect=(155, 760, 220, 792), control_type="TextControl"),
                FakeControl("收藏这张图，看球不迷糊！", hwnd=200, rect=(155, 830, 520, 880), control_type="TextControl"),
                FakeControl("阅读 2830 赞 45", hwnd=200, rect=(155, 900, 300, 922), control_type="TextControl"),
                FakeControl("视频号", hwnd=200, rect=(155, 990, 235, 1020), control_type="TextControl"),
                FakeControl("营养辅食 | 宝宝能量补给站", hwnd=200, rect=(155, 1060, 520, 1110), control_type="TextControl"),
                FakeControl("阅读 3.2万 赞 1487", hwnd=200, rect=(155, 1130, 310, 1152), control_type="TextControl"),
            ],
        )

        targets = home_article_clicker.collect_article_click_targets(
            home_window,
            max_depth=4,
            max_nodes=200,
        )

        self.assertEqual([target.title for target in targets], ["叮叮！也能用心炖炄", "封面不重要的话不听?"])

    def test_article_clicker_collects_multiple_articles_inside_one_service_account_card(self) -> None:
        home_window = FakeControl(
            "服务号正文",
            hwnd=200,
            rect=(100, 100, 900, 1100),
            control_type="DocumentControl",
            children=[
                FakeControl("全部", hwnd=200, rect=(135, 350, 170, 380), control_type="HyperlinkControl"),
                FakeControl("贴图", hwnd=200, rect=(200, 350, 235, 380), control_type="HyperlinkControl"),
                FakeControl("文章", hwnd=200, rect=(265, 350, 300, 380), control_type="HyperlinkControl"),
                FakeControl("昨天", hwnd=200, rect=(155, 470, 200, 500), control_type="TextControl"),
                FakeControl(
                    "【有奖】积分清零月倒计时开始，7重福利齐发！速来薅~",
                    hwnd=200,
                    rect=(155, 515, 478, 560),
                    control_type="TextControl",
                ),
                FakeControl("阅读 4.37万 赞 390", hwnd=200, rect=(155, 570, 320, 590), control_type="TextControl"),
                FakeControl(
                    "冠妈聚光帖｜宝妈真实带娃日常，有崩溃更有温柔",
                    hwnd=200,
                    rect=(155, 635, 478, 685),
                    control_type="TextControl",
                ),
                FakeControl("阅读 3248 赞 60", hwnd=200, rect=(155, 695, 300, 715), control_type="TextControl"),
                FakeControl(
                    "娃摔伤划伤别乱消毒！容易留疤还恢复慢，正确方法速看",
                    hwnd=200,
                    rect=(155, 755, 478, 805),
                    control_type="TextControl",
                ),
                FakeControl("阅读 3657 赞 59", hwnd=200, rect=(155, 815, 300, 835), control_type="TextControl"),
                FakeControl(
                    "老人总偷偷给娃喂零食乱喂饭，别硬碰硬！聪明妈妈都这么做",
                    hwnd=200,
                    rect=(155, 875, 478, 930),
                    control_type="TextControl",
                ),
                FakeControl("阅读 2889 赞 34", hwnd=200, rect=(155, 940, 300, 960), control_type="TextControl"),
            ],
        )

        targets = home_article_clicker.collect_article_click_targets(
            home_window,
            max_depth=4,
            max_nodes=100,
        )

        self.assertEqual(
            [target.title for target in targets],
            [
                "【有奖】积分清零月倒计时开始，7重福利齐发！速来薅~",
                "冠妈聚光帖｜宝妈真实带娃日常，有崩溃更有温柔",
                "娃摔伤划伤别乱消毒！容易留疤还恢复慢，正确方法速看",
                "老人总偷偷给娃喂零食乱喂饭，别硬碰硬！聪明妈妈都这么做",
            ],
        )

    def test_article_clicker_fails_when_uia_titles_unreadable(self) -> None:
        window = FakeControl(
            "公众号",
            hwnd=100,
            rect=(200, 100, 1000, 900),
            control_type="PaneControl",
            children=[FakeControl("公众号", control_type="TextControl")],
        )
        clicked: list[tuple[int, int, int]] = []

        def clicker(hwnd, x, y, **_kwargs):
            clicked.append((hwnd, x, y))
            return {"method": "test_click", "target_hwnd": hwnd, "screen_point": [x, y]}

        with (
            patch.object(home_article_clicker, "activate_wechat_window_for_uia", return_value={"ok": True}),
            patch.object(home_article_clicker, "collect_article_click_targets", return_value=[]),
        ):
            result = home_article_clicker.trigger_home_article_open(
                {"wechat_home_activate_delay_seconds": 0},
                1,
                home_window=window,
                clicker=clicker,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "article_click_target_not_found")
        self.assertEqual(clicked, [])

    def test_find_home_window_prefers_explicit_home_with_article_targets_over_empty_home_shell(self) -> None:
        shell_window = FakeControl(
            "公众号",
            hwnd=100,
            rect=(100, 100, 700, 900),
            control_type="PaneControl",
            children=[FakeControl("公众号", control_type="TextControl")],
        )
        article_window = FakeControl(
            "服务号",
            hwnd=200,
            rect=(200, 100, 1000, 900),
            control_type="DocumentControl",
            children=[
                FakeControl("昨天", hwnd=200, rect=(220, 350, 280, 380), control_type="TextControl"),
                FakeControl(
                    "还没坐稳，球就进了！世界杯历史上的那些“闪电”进球",
                    hwnd=200,
                    rect=(220, 410, 780, 460),
                    control_type="TextControl",
                ),
                FakeControl("阅读 10万+ 赞 928", hwnd=200, rect=(220, 470, 480, 500), control_type="TextControl"),
            ],
        )
        auto_module = FakeAutoModuleWithWindows([shell_window, article_window])

        with (
            patch.object(home_article_clicker.platform, "system", return_value="Windows"),
            patch.object(home_article_clicker, "_process_name", side_effect=["WeChatAppEx.exe", "WeChatAppEx.exe"]),
        ):
            selected = home_article_clicker.find_wechat_home_window(auto_module=auto_module)

        self.assertIs(selected, article_window)

    def test_find_home_window_prefers_explicit_home_title_when_content_is_unreadable(self) -> None:
        for home_title in ("公众号", "服务号"):
            with self.subTest(home_title=home_title):
                shell_window = FakeControl(
                    "微信",
                    hwnd=100,
                    rect=(100, 100, 700, 900),
                    control_type="PaneControl",
                    children=[FakeControl("微信", control_type="TextControl")],
                )
                shell_window.ClassName = "Chrome_WidgetWin_0"
                shell_window.ProcessId = 100

                home_window = FakeControl(
                    home_title,
                    hwnd=200,
                    rect=(200, 100, 1000, 900),
                    control_type="PaneControl",
                    children=[FakeControl(home_title, control_type="TextControl")],
                )
                home_window.ClassName = "Chrome_WidgetWin_0"
                home_window.ProcessId = 200

                auto_module = FakeAutoModuleWithWindows([shell_window, home_window])

                with (
                    patch.object(home_article_clicker.platform, "system", return_value="Windows"),
                    patch.object(home_article_clicker, "_process_name", side_effect=["Weixin.exe", "WeChatAppEx.exe"]),
                ):
                    selected = home_article_clicker.find_wechat_home_window(auto_module=auto_module)

                self.assertIs(selected, home_window)

    def test_find_home_window_ignores_hidden_generic_shell_article_like_content(self) -> None:
        hidden_shell = FakeControl(
            "微信",
            hwnd=100,
            rect=(0, 0, 0, 0),
            control_type="WindowControl",
            children=[
                FakeControl(
                    "看一看文章标题",
                    hwnd=101,
                    rect=(-31576, -31554, -31044, -31475),
                    control_type="TextControl",
                ),
                FakeControl(
                    "阅读 10万+ 赞 928",
                    hwnd=101,
                    rect=(-31576, -31464, -31300, -31434),
                    control_type="TextControl",
                ),
            ],
        )
        hidden_shell.ClassName = "Qt51514QWindowIcon"
        hidden_shell.ProcessId = 100

        home_window = FakeControl(
            "服务号",
            hwnd=200,
            rect=(200, 100, 1000, 900),
            control_type="PaneControl",
            children=[FakeControl("服务号", control_type="TextControl")],
        )
        home_window.ClassName = "Chrome_WidgetWin_0"
        home_window.ProcessId = 200
        auto_module = FakeAutoModuleWithWindows([hidden_shell, home_window])

        with (
            patch.object(home_article_clicker.platform, "system", return_value="Windows"),
            patch.object(home_article_clicker, "_process_name", side_effect=["Weixin.exe", "WeChatAppEx.exe"]),
        ):
            selected = home_article_clicker.find_wechat_home_window(auto_module=auto_module)

        self.assertIs(selected, home_window)

    def test_find_home_window_prefers_explicit_home_over_visible_chat_window_with_article_like_text(self) -> None:
        chat_window = FakeControl(
            "微信",
            hwnd=100,
            rect=(1478, 378, 2464, 1201),
            control_type="WindowControl",
            children=[
                FakeControl("三秋叶磨一剑", hwnd=100, rect=(1600, 520, 1850, 560), control_type="TextControl"),
                FakeControl("阅读 10万+ 赞 928", hwnd=100, rect=(1600, 570, 1820, 600), control_type="TextControl"),
                FakeControl("轻舟使过万重山", hwnd=100, rect=(1600, 660, 1850, 700), control_type="TextControl"),
                FakeControl("阅读 8万 赞 520", hwnd=100, rect=(1600, 710, 1820, 740), control_type="TextControl"),
            ],
        )
        chat_window.ClassName = "Qt51514QWindowIcon"
        chat_window.ProcessId = 100

        home_window = FakeControl(
            "公众号",
            hwnd=200,
            rect=(353, 167, 1103, 1167),
            control_type="PaneControl",
            children=[FakeControl("公众号", control_type="TextControl")],
        )
        home_window.ClassName = "Chrome_WidgetWin_0"
        home_window.ProcessId = 200
        auto_module = FakeAutoModuleWithWindows([chat_window, home_window])

        with (
            patch.object(home_article_clicker.platform, "system", return_value="Windows"),
            patch.object(home_article_clicker, "_process_name", side_effect=["Weixin.exe", "WeChatAppEx.exe"]),
        ):
            selected = home_article_clicker.find_wechat_home_window(auto_module=auto_module)

        self.assertIs(selected, home_window)

    def test_home_detector_skips_visible_chat_window_before_activating_home_candidate(self) -> None:
        calls: list[str] = []
        chat_window = FakeControl(
            "微信",
            hwnd=100,
            rect=(1478, 378, 2464, 1201),
            control_type="WindowControl",
            children=[FakeControl("三秋叶磨一剑", hwnd=100, rect=(1600, 520, 1850, 560), control_type="TextControl")],
        )
        chat_window.ClassName = "Qt51514QWindowIcon"
        chat_window.ProcessId = 100
        home_window = FakeControl(
            "公众号",
            hwnd=200,
            rect=(353, 167, 1103, 1167),
            control_type="PaneControl",
            children=[FakeControl("公众号", control_type="TextControl")],
        )
        home_window.ClassName = "Chrome_WidgetWin_0"
        home_window.ProcessId = 200
        auto_module = FakeAutoModuleWithWindows([chat_window, home_window])

        def activate(window, **_kwargs):
            calls.append(f"activate:{getattr(window, 'NativeWindowHandle', 0)}")
            return {"ok": True}

        def collect(window, **_kwargs):
            calls.append(f"collect:{getattr(window, 'NativeWindowHandle', 0)}")
            if window is home_window:
                return ["公众号", "测试公众号", "1篇原创", "2个朋友关注"]
            return ["微信", "三秋叶磨一剑", "阅读 10万+ 赞 928"]

        with (
            patch.object(wechat_home.platform, "system", return_value="Windows"),
            patch.object(wechat_home, "_get_process_name", side_effect=["Weixin.exe", "WeChatAppEx.exe"]),
            patch.object(wechat_home, "activate_wechat_window_for_uia", side_effect=activate),
            patch.object(wechat_home, "_collect_best_wechat_texts", side_effect=collect),
        ):
            snapshot = wechat_home._detect_with_uiautomation(auto_module=auto_module, activate=True)

        self.assertTrue(snapshot.found)
        self.assertEqual(snapshot.account_name, "测试公众号")
        self.assertEqual(calls, ["activate:200", "collect:200"])

    def test_article_clicker_calls_before_click_with_target_before_sending_click(self) -> None:
        calls: list[str] = []
        window = FakeControl(
            "account",
            hwnd=100,
            rect=(200, 100, 1000, 900),
            control_type="PaneControl",
        )
        target = home_article_clicker.ArticleClickTarget(
            title="target article title",
            rect=(220, 360, 780, 410),
            hwnd=200,
        )

        def before_click(click_target):
            calls.append(f"before:{click_target.title}")

        def clicker(_hwnd, _x, _y, **_kwargs):
            calls.append("click")
            return {"method": "test_click"}

        with (
            patch.object(home_article_clicker, "activate_wechat_window_for_uia", return_value={"ok": True}),
            patch.object(home_article_clicker, "collect_article_click_targets", return_value=[target]),
        ):
            result = home_article_clicker.trigger_home_article_open(
                {"wechat_home_activate_delay_seconds": 0},
                1,
                home_window=window,
                clicker=clicker,
                before_click=before_click,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["before:target article title", "click"])

    def test_trigger_home_article_open_uses_passed_home_window_without_refinding(self) -> None:
        calls: list[str] = []
        home_window = FakeControl(
            "服务号",
            hwnd=100,
            rect=(200, 100, 1000, 900),
            control_type="PaneControl",
        )
        target = home_article_clicker.ArticleClickTarget(
            title="passed title",
            rect=(220, 360, 780, 410),
            hwnd=200,
        )

        def find_home_window(**_kwargs):
            calls.append("find")
            return None

        def activate(window, **_kwargs):
            calls.append(f"activate:{getattr(window, 'NativeWindowHandle', 0)}")
            return {"ok": True}

        def collect(window, **_kwargs):
            calls.append(f"collect:{getattr(window, 'NativeWindowHandle', 0)}")
            return [target] if window is home_window else []

        def clicker(_hwnd, _x, _y, **_kwargs):
            calls.append("click")
            return {"method": "test_click"}

        with (
            patch.object(home_article_clicker, "find_wechat_home_window", side_effect=find_home_window),
            patch.object(home_article_clicker, "activate_wechat_window_for_uia", side_effect=activate),
            patch.object(home_article_clicker, "collect_article_click_targets", side_effect=collect),
        ):
            result = home_article_clicker.trigger_home_article_open(
                {"wechat_home_activate_delay_seconds": 0},
                1,
                home_window=home_window,
                clicker=clicker,
            )

        self.assertTrue(result["ok"])
        self.assertNotIn("find", calls)
        self.assertIn("activate:100", calls)
        self.assertIn("collect:100", calls)
        self.assertIn("click", calls)

    def test_article_clicker_returns_visible_targets_for_runtime_diagnosis(self) -> None:
        window = FakeControl(
            "account",
            hwnd=100,
            rect=(200, 100, 1000, 900),
            control_type="PaneControl",
        )
        targets = [
            home_article_clicker.ArticleClickTarget(
                title="first runtime article",
                rect=(220, 360, 780, 410),
                hwnd=200,
            ),
            home_article_clicker.ArticleClickTarget(
                title="second runtime article",
                rect=(220, 450, 780, 500),
                hwnd=200,
            ),
        ]

        with (
            patch.object(home_article_clicker, "activate_wechat_window_for_uia", return_value={"ok": True}),
            patch.object(home_article_clicker, "collect_article_click_targets", return_value=targets),
        ):
            result = home_article_clicker.trigger_home_article_open(
                {"wechat_home_activate_delay_seconds": 0},
                1,
                home_window=window,
                clicker=lambda *_args, **_kwargs: {"method": "test_click"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["target_title"], "first runtime article")
        self.assertEqual(
            [item["title"] for item in result["visible_targets"]],
            ["first runtime article", "second runtime article"],
        )
        self.assertEqual(result["visible_targets"][0]["index"], 1)
        self.assertEqual(result["visible_targets"][0]["rect"], [220, 360, 780, 410])

    def test_trigger_home_article_open_clicks_passed_candidate_without_runtime_rescan_drift(self) -> None:
        calls: list[tuple[str, object]] = []
        window = FakeControl(
            "account",
            hwnd=100,
            rect=(200, 100, 1000, 900),
            control_type="PaneControl",
        )
        selected_candidate = home_article_clicker.ArticleClickTarget(
            title="你的手机性能正在决定你的生活",
            rect=(220, 260, 780, 310),
            hwnd=200,
        )
        stale_runtime_target = home_article_clicker.ArticleClickTarget(
            title="韩国队，被淘汰",
            rect=(220, 360, 780, 410),
            hwnd=200,
        )

        def collect_targets(_window, **_kwargs):
            calls.append(("collect", "runtime"))
            return [stale_runtime_target]

        def before_click(target):
            calls.append(("before", target.title))

        def clicker(hwnd, x, y, **_kwargs):
            calls.append(("click", (hwnd, x, y)))
            return {"method": "test_click"}

        with (
            patch.object(home_article_clicker, "activate_wechat_window_for_uia", return_value={"ok": True}),
            patch.object(home_article_clicker, "collect_article_click_targets", side_effect=collect_targets),
        ):
            result = home_article_clicker.trigger_home_article_open(
                {"wechat_home_activate_delay_seconds": 0},
                1,
                home_window=window,
                candidate=selected_candidate,
                clicker=clicker,
                before_click=before_click,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["target_title"], "你的手机性能正在决定你的生活")
        self.assertEqual(result["click_point"], [500, 285])
        self.assertEqual(calls, [("before", "你的手机性能正在决定你的生活"), ("click", (200, 500, 285))])
        self.assertEqual(result["visible_targets"][0]["title"], "你的手机性能正在决定你的生活")

    def test_post_message_click_uses_child_window_under_click_point(self) -> None:
        calls = []

        class FakeUser32:
            def ScreenToClient(self, hwnd, _point_ref):
                calls.append(("screen_to_client", int(hwnd)))
                return True

            def PostMessageW(self, hwnd, message, _wparam, _lparam):
                calls.append(("post_message", int(hwnd), int(message)))
                return True

        with (
            patch.object(home_article_clicker.platform, "system", return_value="Windows"),
            patch.object(home_article_clicker, "_find_child_hwnd_containing_point", return_value=456, create=True),
            patch.object(home_article_clicker.ctypes, "windll", create=True) as windll,
        ):
            windll.user32 = FakeUser32()
            result = home_article_clicker.post_message_click(123, 10, 20, pause_seconds=0)

        self.assertEqual(result["parent_hwnd"], 123)
        self.assertEqual(result["target_hwnd"], 456)
        self.assertEqual(calls[0], ("screen_to_client", 456))
        self.assertTrue(all(call[1] == 456 for call in calls if call[0] == "post_message"))

    def test_close_detail_windows_skips_public_account_and_service_account_home_windows(self) -> None:
        windows = {
            1: {"title": "公众号", "class_name": "Chrome_WidgetWin_0", "process_name": "WeChatAppEx.exe"},
            2: {"title": "服务号", "class_name": "Chrome_WidgetWin_0", "process_name": "WeChatAppEx.exe"},
            3: {
                "title": "2026-06-28 文章标题",
                "class_name": "Chrome_WidgetWin_0",
                "process_name": "WeChatAppEx.exe",
            },
        }
        post_calls: list[tuple[int, int]] = []

        class FakeUser32:
            def EnumWindows(self, callback, lparam):
                for hwnd in windows:
                    callback(hwnd, lparam)
                return True

            def IsWindowVisible(self, _hwnd):
                return True

            def PostMessageW(self, hwnd, message, _wparam, _lparam):
                post_calls.append((int(hwnd), int(message)))
                return True

        def get_value(hwnd: int, key: str):
            return windows[int(hwnd)][key]

        with (
            patch.object(wechat_detail_windows.platform, "system", return_value="Windows"),
            patch.object(wechat_detail_windows.ctypes, "windll", create=True) as windll,
            patch.object(wechat_detail_windows, "_get_window_text", side_effect=lambda hwnd: get_value(hwnd, "title")),
            patch.object(
                wechat_detail_windows,
                "_get_window_class",
                side_effect=lambda hwnd: get_value(hwnd, "class_name"),
            ),
            patch.object(
                wechat_detail_windows,
                "_get_window_process_name",
                side_effect=lambda hwnd: get_value(hwnd, "process_name"),
            ),
            patch.object(wechat_detail_windows, "_get_window_rect", return_value=(100, 100, 1200, 1600)),
        ):
            windll.user32 = FakeUser32()
            result = wechat_detail_windows.close_wechat_article_detail_windows(
                homepage_hwnd=999,
                pause_seconds=0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual([item["title"] for item in result["closed"]], ["2026-06-28 文章标题"])
        self.assertEqual(post_calls, [(3, wechat_detail_windows.WM_CLOSE)])

    def test_close_detail_windows_accepts_wechat_browser_chrome_widget_variants(self) -> None:
        windows = {
            1: {"title": "公众号", "class_name": "Chrome_WidgetWin_1", "process_name": "WeChatAppEx.exe"},
            2: {
                "title": "文章详情页",
                "class_name": "Chrome_WidgetWin_1",
                "process_name": "WeChatAppEx.exe",
            },
            3: {"title": "微信", "class_name": "Chrome_WidgetWin_1", "process_name": "WeChatAppEx.exe"},
        }
        post_calls: list[tuple[int, int]] = []

        class FakeUser32:
            def EnumWindows(self, callback, lparam):
                for hwnd in windows:
                    callback(hwnd, lparam)
                return True

            def IsWindowVisible(self, _hwnd):
                return True

            def PostMessageW(self, hwnd, message, _wparam, _lparam):
                post_calls.append((int(hwnd), int(message)))
                return True

        def get_value(hwnd: int, key: str):
            return windows[int(hwnd)][key]

        with (
            patch.object(wechat_detail_windows.platform, "system", return_value="Windows"),
            patch.object(wechat_detail_windows.ctypes, "windll", create=True) as windll,
            patch.object(wechat_detail_windows, "_get_window_text", side_effect=lambda hwnd: get_value(hwnd, "title")),
            patch.object(
                wechat_detail_windows,
                "_get_window_class",
                side_effect=lambda hwnd: get_value(hwnd, "class_name"),
            ),
            patch.object(
                wechat_detail_windows,
                "_get_window_process_name",
                side_effect=lambda hwnd: get_value(hwnd, "process_name"),
            ),
            patch.object(wechat_detail_windows, "_get_window_rect", return_value=(100, 100, 1200, 1600)),
        ):
            windll.user32 = FakeUser32()
            result = wechat_detail_windows.close_wechat_article_detail_windows(
                homepage_hwnd=1,
                pause_seconds=0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual([item["title"] for item in result["closed"]], ["文章详情页", "微信"])
        self.assertEqual(post_calls, [(2, wechat_detail_windows.WM_CLOSE), (3, wechat_detail_windows.WM_CLOSE)])

    def test_close_detail_windows_closes_wechat_titled_builtin_browser_when_not_homepage(self) -> None:
        windows = {
            1: {"title": "公众号", "class_name": "Chrome_WidgetWin_0", "process_name": "WeChatAppEx.exe"},
            2: {"title": "微信", "class_name": "Chrome_WidgetWin_0", "process_name": "WeChatAppEx.exe"},
        }
        post_calls: list[tuple[int, int]] = []

        class FakeUser32:
            def EnumWindows(self, callback, lparam):
                for hwnd in windows:
                    callback(hwnd, lparam)
                return True

            def IsWindowVisible(self, _hwnd):
                return True

            def PostMessageW(self, hwnd, message, _wparam, _lparam):
                post_calls.append((int(hwnd), int(message)))
                return True

        def get_value(hwnd: int, key: str):
            return windows[int(hwnd)][key]

        with (
            patch.object(wechat_detail_windows.platform, "system", return_value="Windows"),
            patch.object(wechat_detail_windows.ctypes, "windll", create=True) as windll,
            patch.object(wechat_detail_windows, "_get_window_text", side_effect=lambda hwnd: get_value(hwnd, "title")),
            patch.object(
                wechat_detail_windows,
                "_get_window_class",
                side_effect=lambda hwnd: get_value(hwnd, "class_name"),
            ),
            patch.object(
                wechat_detail_windows,
                "_get_window_process_name",
                side_effect=lambda hwnd: get_value(hwnd, "process_name"),
            ),
            patch.object(wechat_detail_windows, "_get_window_rect", return_value=(548, 60, 1476, 968)),
        ):
            windll.user32 = FakeUser32()
            result = wechat_detail_windows.close_wechat_article_detail_windows(
                homepage_hwnd=1,
                pause_seconds=0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual([item["title"] for item in result["closed"]], ["微信"])
        self.assertEqual(post_calls, [(2, wechat_detail_windows.WM_CLOSE)])

    def test_home_detector_does_not_activate_wechat_window_by_default(self) -> None:
        calls: list[str] = []

        def activate(_window, **_kwargs):
            calls.append("activate")
            return {"ok": True, "reason": "activated"}

        def collect(_window, **_kwargs):
            calls.append("collect")
            return ["测试公众号", "1篇原创", "朋友关注 2"]

        with (
            patch.object(wechat_home, "activate_wechat_window_for_uia", side_effect=activate),
            patch.object(wechat_home, "_collect_best_wechat_texts", side_effect=collect),
            patch.object(wechat_home, "_get_process_name", return_value="WeChat.exe"),
        ):
            snapshot = wechat_home._detect_with_uiautomation(auto_module=FakeAutoModule)

        self.assertTrue(snapshot.found)
        self.assertEqual(calls, ["collect"])

    def test_home_detector_can_activate_wechat_window_before_reading_text_tree(self) -> None:
        calls: list[str] = []

        def activate(_window, **_kwargs):
            calls.append("activate")
            return {"ok": True, "reason": "activated"}

        def collect(_window, **_kwargs):
            calls.append("collect")
            return ["测试公众号", "1篇原创", "朋友关注 2"]

        with (
            patch.object(wechat_home, "activate_wechat_window_for_uia", side_effect=activate),
            patch.object(wechat_home, "_collect_best_wechat_texts", side_effect=collect),
            patch.object(wechat_home, "_get_process_name", return_value="WeChat.exe"),
        ):
            snapshot = wechat_home._detect_with_uiautomation(auto_module=FakeAutoModule, activate=True)

        self.assertTrue(snapshot.found)
        self.assertEqual(calls, ["activate", "collect"])

    def test_task_manager_only_activates_home_detection_when_starting_task(self) -> None:
        calls: list[bool] = []

        def detector(*, activate: bool = False):
            calls.append(activate)
            return WeChatHomeSnapshot(
                status="not_found",
                status_label="未检测到主页窗口",
                account_name="未检测到微信 PC 公众号主页",
                description="测试用未找到状态",
                original_count="未识别到",
                friend_follow_count="未识别到",
                found=False,
                message="测试用未找到状态",
            )

        class NoopFileLogger:
            path = "test.log"

            def write(self, _event):
                return None

        manager = TaskManager(home_detector=detector, file_logger=NoopFileLogger())

        manager.get_status(refresh_home=True)
        manager.start_task({"recordLimit": 1})

        self.assertEqual(calls, [False, False, True])

    def test_task_manager_does_not_pass_content_unreadable_placeholder_as_account_name(self) -> None:
        started: dict = {}

        class NoopFileLogger:
            path = "test.log"

            def write(self, _event):
                return None

        class FakeProcessManager:
            def is_running(self, _name: str) -> bool:
                return False

            def start_worker(self, name: str, _target=None, args=(), **_kwargs):
                started["name"] = name
                started["config"] = args[1]

            def running_workers(self) -> list[str]:
                return []

        def detector(*, activate: bool = False):
            return WeChatHomeSnapshot(
                status="content_unreadable",
                status_label="已检测到主页窗口",
                account_name="已检测到公众号窗口，但无法读取主页内容",
                description="微信窗口当前未向 Windows UI Automation 暴露公众号主页正文",
                original_count="未识别到",
                friend_follow_count="未识别到",
                found=False,
                message="已检测到公众号窗口，但未读取到可解析的主页文本",
            )

        manager = TaskManager(
            process_manager=FakeProcessManager(),
            home_detector=detector,
            file_logger=NoopFileLogger(),
        )

        with patch.object(manager, "_ensure_mitm_ready_for_collection", return_value={"ok": True}):
            manager.start_task({"recordLimit": 1})

        self.assertEqual(started["name"], "article_capture")
        self.assertNotIn("account_name", started["config"])

    def test_task_manager_passes_capture_timing_options_to_article_worker(self) -> None:
        started: dict = {}

        class NoopFileLogger:
            path = "test.log"

            def write(self, _event):
                return None

        class FakeProcessManager:
            def is_running(self, _name: str) -> bool:
                return False

            def start_worker(self, name: str, _target=None, args=(), **_kwargs):
                started["name"] = name
                started["config"] = args[1]

            def running_workers(self) -> list[str]:
                return []

        def detector(*, activate: bool = False):
            return WeChatHomeSnapshot(
                status="ready",
                status_label="主页信息已获取",
                account_name="测试公众号",
                description="测试简介",
                original_count="1",
                friend_follow_count="2",
                found=True,
                account_confidence="high",
                account_source="profile_header",
            )

        manager = TaskManager(
            config=AppRuntimeConfig(app=AppFeatureConfig(request_interval_seconds=5, retry_count=2)),
            process_manager=FakeProcessManager(),
            home_detector=detector,
            file_logger=NoopFileLogger(),
        )

        with patch.object(manager, "_ensure_mitm_ready_for_collection", return_value={"ok": True}):
            manager.start_task({"recordLimit": 1})

        self.assertEqual(started["name"], "article_capture")
        self.assertEqual(started["config"]["request_interval_seconds"], 5)
        self.assertEqual(started["config"]["retry_count"], 2)

    def test_task_manager_keeps_last_trusted_home_display_when_content_unreadable(self) -> None:
        snapshots = [
            WeChatHomeSnapshot(
                status="ready",
                status_label="主页信息已获取",
                account_name="新华社",
                description="国家通讯社",
                original_count="123",
                friend_follow_count="456",
                found=True,
                account_confidence="high",
                account_source="profile_header",
                visible_tabs=("全部", "文章"),
            ),
            WeChatHomeSnapshot(
                status="content_unreadable",
                status_label="已检测到主页窗口",
                account_name="已检测到公众号窗口，但无法读取主页内容",
                description="微信窗口当前未向 Windows UI Automation 暴露公众号主页正文",
                original_count="未识别到",
                friend_follow_count="未识别到",
                found=False,
                message="已检测到公众号窗口，但未读取到可解析的主页文本",
            ),
        ]

        class NoopFileLogger:
            path = "test.log"

            def write(self, _event):
                return None

        def detector(*, activate: bool = False):
            if snapshots:
                return snapshots.pop(0)
            return WeChatHomeSnapshot(
                status="content_unreadable",
                status_label="已检测到主页窗口",
                account_name="已检测到公众号窗口，但无法读取主页内容",
                description="微信窗口当前未向 Windows UI Automation 暴露公众号主页正文",
                original_count="未识别到",
                friend_follow_count="未识别到",
                found=False,
                message="已检测到公众号窗口，但未读取到可解析的主页文本",
            )

        manager = TaskManager(home_detector=detector, file_logger=NoopFileLogger())
        status = manager.get_status(refresh_home=True)
        home = status["home"]

        self.assertEqual(home["accountName"], "新华社")
        self.assertEqual(home["description"], "国家通讯社")
        self.assertEqual(home["originalCount"], "123")
        self.assertEqual(home["friendFollowCount"], "456")
        self.assertEqual(home["status"], "display_cached")
        self.assertEqual(home["statusLabel"], "主页信息暂不可读，已沿用上次识别")
        self.assertEqual(home["message"], "展示信息仅供参考，不影响采集入库")

    def test_task_manager_shows_short_display_hint_without_trusted_home_cache(self) -> None:
        class NoopFileLogger:
            path = "test.log"

            def write(self, _event):
                return None

        def detector(*, activate: bool = False):
            return WeChatHomeSnapshot(
                status="content_unreadable",
                status_label="已检测到主页窗口",
                account_name="已检测到公众号窗口，但无法读取主页内容",
                description="微信窗口当前未向 Windows UI Automation 暴露公众号主页正文",
                original_count="未识别到",
                friend_follow_count="未识别到",
                found=False,
                message="已检测到公众号窗口，但未读取到可解析的主页文本",
            )

        manager = TaskManager(home_detector=detector, file_logger=NoopFileLogger())
        home = manager.get_status(refresh_home=False)["home"]

        self.assertEqual(home["status"], "display_unavailable")
        self.assertEqual(home["statusLabel"], "主页信息暂不可读，不影响采集")
        self.assertEqual(home["accountName"], "未读取到可信公众号名")
        self.assertEqual(home["description"], "展示信息仅供参考，不影响采集入库")
        self.assertEqual(home["originalCount"], "暂不可读")
        self.assertEqual(home["friendFollowCount"], "暂不可读")

    def test_task_manager_does_not_pass_low_confidence_account_name(self) -> None:
        started: dict = {}

        class NoopFileLogger:
            path = "test.log"

            def write(self, _event):
                return None

        class FakeProcessManager:
            def is_running(self, _name: str) -> bool:
                return False

            def start_worker(self, name: str, _target=None, args=(), **_kwargs):
                started["name"] = name
                started["config"] = args[1]

            def running_workers(self) -> list[str]:
                return []

        def detector(*, activate: bool = False):
            return WeChatHomeSnapshot(
                status="partial",
                status_label="主页局部信息已获取",
                account_name="夏至，喜至！",
                description="未识别到主页简介",
                original_count="无",
                friend_follow_count="无",
                found=True,
                account_confidence="low",
                account_source="content_list",
            )

        manager = TaskManager(
            process_manager=FakeProcessManager(),
            home_detector=detector,
            file_logger=NoopFileLogger(),
        )

        with patch.object(manager, "_ensure_mitm_ready_for_collection", return_value={"ok": True}):
            manager.start_task({"recordLimit": 1})

        self.assertEqual(started["name"], "article_capture")
        self.assertNotIn("account_name", started["config"])


if __name__ == "__main__":
    unittest.main()

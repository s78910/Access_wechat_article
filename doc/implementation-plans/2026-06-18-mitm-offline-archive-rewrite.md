# MITM 常驻与离线归档一致性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让文章采集 worker 与常驻 MITM worker 通过事件交互，并让 Playwright 保存的本地 `index.html` 与在线短链接页面显示尽量一致。

**Architecture:** MITM worker 保持独立常驻，只负责监听和发送关键事件；文章采集 worker 不再启动或关闭 MITM，只等待 MITM 捕获到的文章主 HTML 事件并整理本地归档。离线页面保存使用 URL 规范化映射和属性级重写，避免破坏 `//res.wx.qq.com/...`、`srcset`、CSS `url(...)` 等资源引用。

**Tech Stack:** Python 3.13、mitmproxy、Playwright、SQLite、unittest。

---

### Task 1: 修复离线页资源 URL 重写

**Files:**
- Modify: `src/workers/article_capture.py`
- Test: `tests/test_article_capture_worker.py`

- [ ] **Step 1: Write the failing test**

Add a test that proves protocol-relative URLs are rewritten to local assets without producing malformed URLs:

```python
def test_rewrites_protocol_relative_assets_without_breaking_host_path_boundary(self):
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_dir = Path(tmp_dir)
        local_js = archive_dir / "assets" / "js" / "wechat.js"
        local_css = archive_dir / "assets" / "css" / "wechat.css"
        local_js.parent.mkdir(parents=True)
        local_css.parent.mkdir(parents=True)
        local_js.write_text("console.log('ok')", encoding="utf-8")
        local_css.write_text("body{}", encoding="utf-8")
        html_text = (
            '<script src="//res.wx.qq.com/a/b/wechat.js"></script>'
            '<link href="/a/b/wechat.css" rel="stylesheet">'
        )

        rewritten = rewrite_html_resource_urls(
            html_text,
            "https://mp.weixin.qq.com/s/test",
            {
                "https://res.wx.qq.com/a/b/wechat.js": local_js,
                "https://res.wx.qq.com/a/b/wechat.css": local_css,
            },
            archive_dir,
        )

    self.assertIn('src="assets/js/wechat.js"', rewritten)
    self.assertIn('href="assets/css/wechat.css"', rewritten)
    self.assertNotIn("//res.wx.qq.comassets", rewritten)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_article_capture_worker.ArticleCaptureWorkerTest.test_rewrites_protocol_relative_assets_without_breaking_host_path_boundary`

Expected: FAIL because the old replacement can produce malformed protocol-relative paths.

- [ ] **Step 3: Write minimal implementation**

Implement URL variants for each captured resource:

```python
def build_resource_url_variants(source_url: str) -> set[str]:
    parsed = urlparse(source_url)
    variants = {source_url}
    if parsed.scheme and parsed.netloc:
        variants.add(urlunparse(("", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)))
        variants.add(urlunparse(("", "", parsed.path, parsed.params, parsed.query, parsed.fragment)))
    return {item for item in variants if item}
```

Replace only complete attribute/CSS URL values, not every substring globally.

- [ ] **Step 4: Run targeted tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_article_capture_worker`

Expected: PASS.

### Task 2: 增加 MITM 文章主 HTML 捕获事件

**Files:**
- Modify: `src/workers/mitm_worker.py`
- Test: `tests/test_mitm_worker_parser.py`

- [ ] **Step 1: Write the failing test**

Add tests for classifying article URLs and building a compact capture event:

```python
def test_builds_article_main_html_capture_event_with_key_request(self):
    url = "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=abc&key=secret&pass_ticket=ticket"
    event = mitm_worker.build_article_main_html_capture_event(
        url=url,
        method="GET",
        request_headers={"cookie": "appmsg_token=abc"},
        response_headers={"content-type": "text/html"},
        html_text='var msg_title = "标题"; var ct = "1781760000";',
        status_code=200,
    )

    self.assertEqual(event["type"], "article_main_html_captured")
    self.assertEqual(event["url"], url)
    self.assertEqual(event["title"], "标题")
    self.assertEqual(event["status_code"], 200)
    self.assertIn("key", event["query"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_mitm_worker_parser.MitmWorkerParserTest.test_builds_article_main_html_capture_event_with_key_request`

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Write minimal implementation**

Add helper functions to `mitm_worker.py`: `is_article_main_html_url()`, `extract_article_title_from_html()`, `extract_publish_time_from_html()`, `build_article_main_html_capture_event()`. In `WeChatCaptureAddon.response()`, when a `/s` article URL contains `key`, send the new event with compact request headers and response metadata.

- [ ] **Step 4: Run targeted tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_mitm_worker_parser`

Expected: PASS.

### Task 3: 采集 worker 不再启动旧 MITM 生命周期

**Files:**
- Modify: `src/core/task_manager.py`
- Modify: `src/workers/article_capture.py`
- Test: `tests/test_task_manager.py`
- Test: `tests/test_article_capture_worker.py`

- [ ] **Step 1: Write failing tests**

Update the TaskManager expectation:

```python
def test_start_task_keeps_prepared_mitm_running_while_article_capture_runs(self):
    process_manager = FakeProcessManager()
    manager = self.make_manager(process_manager=process_manager)
    manager.start_mitm_proxy()

    payload = manager.start_task({"recordLimit": 1})

    self.assertTrue(payload["ok"])
    self.assertEqual([name for name, *_ in process_manager.started], ["mitm", "article_capture"])
    self.assertEqual(process_manager.stopped, [])
```

Add a worker test proving a supplied MITM capture event can be saved without calling the legacy pipeline:

```python
with patch("src.workers.article_capture.collect_article_capture_report_from_mitm", return_value=report):
    run_article_capture_worker(event_queue, config)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_task_manager.TaskManagerTest.test_start_task_keeps_prepared_mitm_running_while_article_capture_runs`

Expected: FAIL because current code stops `mitm`.

- [ ] **Step 3: Write minimal implementation**

Remove the pre-capture `stop_worker("mitm")` path. Add `collect_article_capture_report_from_mitm(event_queue, config, article_index)` that waits for `article_main_html_captured`, converts it into the report shape already consumed by `build_local_article_archive()`, and only falls back to legacy UI click helpers when no MITM event arrives.

- [ ] **Step 4: Run targeted tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_task_manager tests.test_article_capture_worker`

Expected: PASS.

### Task 4: Playwright 截图对比验证

**Files:**
- Create: `src/utils/offline_page_compare.py`
- Test: manual Playwright verification

- [ ] **Step 1: Add a utility script**

Create a small internal utility that opens the online URL and local `index.html`, captures screenshots under `output/playwright/`, and records failed resource requests.

- [ ] **Step 2: Run comparison against the current sample**

Run with the sample `storages/人民日报/.../article_detail.json`.

Expected: two screenshots are produced and malformed `//res.wx.qq.comassets` references disappear after regeneration.

### Task 5: Final verification

**Files:**
- Verify all touched Python modules and tests.

- [ ] **Step 1: Run full unit tests**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`

Expected: PASS.

- [ ] **Step 2: Run compile check**

Run: `.\.venv\Scripts\python.exe -m compileall -q src app tests`

Expected: exit code 0.

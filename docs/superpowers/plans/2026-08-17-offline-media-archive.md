# Offline Media Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有单篇离线缓存子进程中发现并完整下载微信文章音视频资源，并提供只处理本地文件的 FFmpeg 合并能力。

**Architecture:** `CapturedResponseStore` 只登记媒体候选，图文资源仍复用 Playwright 响应；独立的 requests 下载模块负责 200/206 流式下载并返回本地映射。FFmpeg 模块通过 `imageio_ffmpeg.get_ffmpeg_exe()` 处理本地 concat 或 mux，不参与网络请求。

**Tech Stack:** Python 3.13、Playwright、requests、imageio-ffmpeg、unittest

---

### Task 1: requests 媒体下载器

**Files:**
- Create: `src/modules/archive/offline_media_downloader.py`
- Create: `tests/test_offline_media_downloader.py`

- [ ] **Step 1: 写普通 200 响应和强制 206 连续下载的失败测试**

```python
result = download_media_candidate(candidate, assets_dir, cookies=[], timeout_seconds=10)
self.assertTrue(result.ok)
self.assertEqual(result.local_path.read_bytes(), expected_body)
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `uv run python -m unittest tests.test_offline_media_downloader`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现候选模型、请求头过滤、Cookie 传递、200/206 流式写入和原子替换**

```python
@dataclass(frozen=True, slots=True)
class MediaCandidate:
    url: str
    content_type: str
    request_headers: Mapping[str, str]

def download_media_candidate(
    candidate: MediaCandidate,
    assets_dir: Path,
    *,
    cookies: Sequence[Mapping[str, object]],
    timeout_seconds: float,
    session_factory: Callable[[], requests.Session] = requests.Session,
) -> MediaDownloadResult:
    return RequestsMediaDownloader(
        assets_dir,
        timeout_seconds=timeout_seconds,
        session_factory=session_factory,
    ).download(candidate, cookies=cookies)
```

- [ ] **Step 4: 运行下载器测试并确认通过**

Run: `uv run python -m unittest tests.test_offline_media_downloader`
Expected: all tests pass

### Task 2: Playwright 媒体发现与归档接入

**Files:**
- Modify: `src/modules/archive/offline_archiver.py`
- Modify: `tests/test_offline_cache_archiver.py`

- [ ] **Step 1: 写媒体响应只登记候选、不读取部分 body 的失败测试**

```python
saved = store.capture(partial_video_response)
self.assertFalse(saved)
self.assertEqual(partial_video_response.body_calls, 0)
self.assertEqual(len(store.media_candidates), 1)
```

- [ ] **Step 2: 运行归档测试并确认缺少媒体候选行为**

Run: `uv run python -m unittest tests.test_offline_cache_archiver`
Expected: media candidate assertion fails

- [ ] **Step 3: 接入候选登记、Cookie 导出、requests 下载、resource_map 更新和 video/audio DOM 地址回写**

```python
cookies = context.cookies([candidate.url for candidate in resource_store.media_candidates])
for result in download_media_candidates(
    resource_store.media_candidates,
    assets_dir=assets_dir,
    cookies=cookies,
    timeout_seconds=request.resource_timeout_seconds,
):
    if result.ok:
        resource_store.resource_map[result.source_url] = result.relative_path
```

- [ ] **Step 4: 运行归档与子进程测试并确认通过**

Run: `uv run python -m unittest tests.test_offline_cache_archiver tests.test_offline_cache_process`
Expected: all tests pass

### Task 3: 本地 FFmpeg 合并接口

**Files:**
- Create: `src/modules/archive/offline_media_merger.py`
- Create: `tests/test_offline_media_merger.py`

- [ ] **Step 1: 写 concat 和独立音视频轨 mux 命令的失败测试**

```python
result = concat_local_media_segments(segment_paths, output_path, runner=fake_runner)
self.assertTrue(result.ok)
self.assertIn("-f", fake_runner.command)
self.assertIn("concat", fake_runner.command)
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `uv run python -m unittest tests.test_offline_media_merger`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 使用 imageio-ffmpeg 路径实现本地 concat、mux、临时输出和失败信息**

```python
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
command = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", temp_output]
```

- [ ] **Step 4: 运行 FFmpeg 接口测试并确认通过**

Run: `uv run python -m unittest tests.test_offline_media_merger`
Expected: all tests pass

### Task 4: 回归验证

**Files:**
- Verify: `src/modules/archive/offline_media_downloader.py`
- Verify: `src/modules/archive/offline_media_merger.py`
- Verify: `src/modules/archive/offline_archiver.py`

- [ ] **Step 1: 运行离线归档相关测试**

Run: `uv run python -m unittest tests.test_offline_media_downloader tests.test_offline_media_merger tests.test_offline_cache_archiver tests.test_offline_cache_process tests.test_article_detail_offline_cache_huey_service`
Expected: all tests pass

- [ ] **Step 2: 运行编译和差异检查**

Run: `uv run python -m compileall -q src/modules/archive tests/test_offline_media_downloader.py tests/test_offline_media_merger.py`
Expected: exit code 0

Run: `git diff --check -- src/modules/archive tests/test_offline_media_downloader.py tests/test_offline_media_merger.py`
Expected: no whitespace errors

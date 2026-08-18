# 离线音视频归档设计

## 目标

在现有单篇离线缓存子进程中完成音视频资源归档，同时保持图文资源继续复用 Playwright 已捕获的完整响应。媒体失败只产生 warning，不阻断 `index.html` 和图文资源保存。

## 职责边界

- Playwright：触发懒加载，记录浏览器实际请求的媒体 URL、内容类型和请求头，并在媒体下载完成前保持上下文存活。
- requests：携带 Playwright 会话中的 Cookie、Referer 和 User-Agent，流式下载普通 MP4、MP3、M4A 等资源；服务端强制返回 206 时按 `Content-Range` 连续补齐字节。
- imageio-ffmpeg：只提供 FFmpeg 可执行文件路径；FFmpeg 只处理已落地的本地媒体片段，不直接访问网络。
- 离线 HTML 重写：把成功下载的媒体 URL 映射到 `assets/video/` 或 `assets/audio/`，失败时保留原 DOM 并记录警告。

## 当前范围

- 支持普通 HTTP 200 媒体流式下载。
- 支持无 Range 请求仍返回 206 的服务端，按连续字节区间补齐完整文件。
- 支持捕获并去重浏览器实际使用的媒体 URL。
- 支持本地同类型媒体片段 concat 和独立音视频轨 mux 的 FFmpeg 调用接口。
- 当前归档样本没有 m3u8，因此本次不实现 HLS 清单解析；检测到 m3u8 时明确记录暂不支持，而不是误存为完整视频。

## 生命周期

```text
Playwright 打开并滚动文章
-> 保存完整图文响应
-> 汇总媒体候选
-> 暂停页面播放器
-> 导出当前 Playwright Cookie
-> requests 下载完整媒体
-> 成功资源写入 resource_map
-> 必要时 FFmpeg 合并本地片段
-> 重写并保存 index.html
-> 关闭 Playwright
```

## 错误处理

- 下载先写 `.part` 文件，成功校验后原子替换正式文件。
- 206 区间起点不连续、总长度变化或区间不前进时终止该媒体下载。
- 媒体 URL 和 Cookie 只在当前子进程内使用；日志不输出 Cookie，也不完整输出带鉴权查询参数的 URL。
- 单个媒体失败追加 warning，其他媒体与图文归档继续执行。


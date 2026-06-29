# 贡献指南

感谢你愿意改进 Access WeChat Article。这个项目涉及 Windows 桌面窗口、微信 PC 客户端、本地 MITM、系统代理、SQLite、本地归档和 Playwright 离线缓存。贡献时请尽量保持改动边界清楚、验证过程可复核、敏感数据不外泄。

## 1. 项目定位

本项目是面向学术研究、课程项目和个人学习场景的本地科研辅助工具。它不是在线采集服务，也不提供公网部署、多用户账号系统或商业化数据服务。

贡献方向应优先围绕：

- Windows 桌面端交互和本地服务稳定性。
- 微信主页窗口识别、文章候选过滤、点击和窗口保护。
- MITM 捕获、请求解析、评论采集和敏感字段脱敏。
- SQLite 索引、本地归档、Excel 导出和缓存清理。
- Playwright 离线缓存、资源过滤和页面完整性。
- 文档、测试、CI 和发布流程。

不建议提交会扩大合规风险的功能，例如绕过平台限制、批量滥用接口、规避验证码或规避账号风控。

## 2. 开发环境

当前 Python 环境统一使用 `uv` 管理。

```bash
uv sync
```

本项目不再维护 `requirements.txt`。依赖来源以这些文件为准：

- `pyproject.toml`
- `uv.lock`

Playwright 浏览器应安装到项目目录，避免写入用户全局缓存：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH=".playwright-browsers"
uv run playwright install chromium
```

不要使用系统 Python、全局 pip、`pip install --user` 或手工复制依赖的方式修改项目环境。

## 3. 分支和 Pull Request

- 建议从 `main` 拉出功能分支。
- 一个 Pull Request 尽量只解决一个明确问题。
- PR 标题应说明改动范围，例如 `fix: improve home window candidate filtering`。
- 如果改动影响配置、数据结构、目录结构或用户操作流程，请在 PR 中说明迁移方式。
- 不要把个人运行数据、数据库、证书、日志、缓存页面、截图或导出的 Excel 提交到仓库。

## 4. 代码边界

请尽量沿用现有模块边界：

- FastAPI 路由放在 `src/app/fastapi_app/`。
- pywebview 桌面能力放在 `src/app/pywebview_app/`。
- 任务状态、日志和调度放在 `src/core/`。
- 用户配置读取放在 `src/config/`。
- MITM、系统代理和证书放在 `src/modules/proxy/`。
- 微信主页识别、文章候选和窗口保护放在 `src/modules/window/`。
- 文章详情和评论解析放在 `src/modules/detail/`。
- SQLite、本地归档、删除和 Excel 导出放在 `src/modules/storage/`。
- Playwright 离线缓存放在 `src/modules/html_archive/`。
- 后台执行流程放在 `src/workers/`。

代码设计要求：

- 低耦合，避免把业务逻辑堆到路由、窗口 API 或单个 worker 中。
- 可测试，关键逻辑尽量可用 fake object 或 mock 环境验证。
- 可恢复，涉及系统代理、证书、进程和临时文件时要考虑异常退出。
- 可脱敏，日志和返回值中不要暴露 `key`、`pass_ticket`、`appmsg_token`、Cookie 等敏感内容。

## 5. 文档维护

修改用户可感知行为时，请同步更新文档：

- 安装和启动变化：更新 `doc/install_zh.md`。
- 页面功能、按钮能力和业务流程变化：更新 `doc/features_zh.md`。
- 模块边界、运行链路、目录结构变化：更新 `doc/architecture_zh.md`。
- 贡献流程、安全边界或敏感数据规则变化：更新本文件或 `doc/security_zh.md`。

README 保留原项目展示内容，不作为详细维护手册。新增详细说明优先放入 `doc/`。

## 6. 测试建议

优先运行与改动相关的测试。

基础服务和归档相关：

```bash
uv run python -m unittest tests.test_archive_cache_service tests.test_archive_delete_service tests.test_archive_excel_export_service tests.test_runtime_cleanup tests.test_sqlite_store
```

窗口识别相关：

```bash
uv run python -m unittest tests.test_home_article_cursor tests.test_wechat_window_activation
```

入口文件语法检查：

```bash
uv run python -m py_compile main.py dev_server.py
```

部分测试依赖 Windows、微信 PC 客户端、系统代理、证书、真实浏览器或真实网络环境。如果无法验证，请在 PR 中明确说明。

## 7. 提交前检查清单

提交前建议确认：

- [ ] 代码改动范围与目标一致，没有顺手重构无关模块。
- [ ] 已运行与改动相关的测试。
- [ ] 没有提交 `.mitmproxy/`、`.playwright-browsers/`、`data/awa_public.sqlite3`、`data/logs/`、`data/tmp/`、`storages/`。
- [ ] 没有提交真实 Cookie、证书、数据库、文章归档、日志全文或带临时参数的 URL。
- [ ] 文档已同步更新。
- [ ] PR 中说明了已验证和未验证内容。

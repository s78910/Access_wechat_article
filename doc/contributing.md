# 贡献、行为与安全指南

感谢你愿意改进 Access WeChat Article。这个项目涉及 Windows 桌面窗口、微信 PC 客户端、本地 MITM、系统代理、SQLite、本地归档和 Playwright 离线缓存。贡献时请尽量保持改动边界清楚、验证过程可复核、敏感数据不外泄。

本文件合并说明贡献流程、社区行为准则和安全边界，作为项目协作时的统一参考。

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

- 安装和启动变化：更新 `doc/install.md` 和 `doc/install_en.md`。
- 页面功能、按钮能力和业务流程变化：更新 `doc/features.md` 和 `doc/features_en.md`。
- 贡献流程、行为规则、安全边界或敏感数据规则变化：更新本文件和 `doc/contributing_en.md`。

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

## 7. 行为准则

Access WeChat Article 是一个面向学习、科研和本地材料整理的项目。我们希望项目讨论保持直接、友好、具体、尊重事实，并重视法律、平台规则和研究伦理。

我们鼓励：

- 清楚描述问题、复现步骤、运行环境和已尝试的方法。
- 对代码、文档、测试和设计提出具体建议。
- 尊重不同使用场景、技术水平和研究背景。
- 在涉及平台规则、法律、伦理和数据安全时保持谨慎。
- 对不确定的信息明确说明，不编造接口能力、实验结果或项目功能。

我们不接受：

- 人身攻击、侮辱、骚扰、歧视或恶意嘲讽。
- 发布他人的个人信息、Cookie、证书、数据库、聊天记录、文章归档或敏感日志。
- 鼓励绕过平台规则、侵犯版权、批量滥用接口、规避账号风控或进行不合规采集。
- 要求维护者协助处理不合规用途。
- 在没有证据的情况下声称项目具有不存在的能力或效果。

提交 Issue 或 Pull Request 时，请尽量使用清晰标题，描述目标和阻塞，提供脱敏后的最小复现信息，并把多个独立问题拆开讨论。

维护者可以根据情况编辑或删除包含敏感信息的内容，要求补充复现步骤或脱敏材料，关闭重复、无关或不符合项目目标的问题，拒绝会增加合规风险或安全风险的贡献，并限制持续破坏讨论秩序的参与者。

## 8. 安全边界

当前项目默认支持范围：

- Windows 10/11 本地桌面环境。
- 用户自己登录并操作的微信 PC 客户端。
- 本机 FastAPI 服务，默认监听 `127.0.0.1:8766`。
- 本机 MITM 代理，默认监听 `localhost:18000` 或配置文件中的本地地址。
- 本机 SQLite 数据库和本地文章归档目录。

当前项目不默认支持：

- 公网服务部署。
- 多用户共享服务。
- 云端采集服务。
- 账号托管或远程控制。
- 绕过平台规则、验证码、账号风控或访问限制。

如果你修改代码让服务监听公网地址、暴露远程 API 或引入账号托管能力，需要重新评估安全模型和合规风险。

## 9. 不要提交的文件

以下内容可能包含个人数据、证书、运行日志、文章材料或短时间有效的请求参数，不应提交到 Git：

- `.mitmproxy/`
- `.playwright-browsers/`
- `data/awa_public.sqlite3`
- `data/logs/`
- `data/tmp/`
- `storages/`
- `tests/artifacts/`
- `tests/output/`
- 导出的 `.xlsx`、`.csv`、`.db`、`.sqlite`、`.sqlite3` 文件

如果需要提交测试样例，请使用最小化、脱敏后的假数据，不要使用真实账号、真实文章归档或真实请求参数。

## 10. 敏感参数

运行过程中可能出现这些临时参数：

- `key`
- `pass_ticket`
- `appmsg_token`
- `uin`
- `wxtoken`
- Cookie
- Set-Cookie
- 带完整 query string 的微信文章 URL

这些内容可能短时间内有效。日志、测试、Issue、Pull Request、截图和文档中都应脱敏。

建议脱敏方式：

- URL 中移除 `key`、`pass_ticket`、`appmsg_token`。
- Cookie 只保留字段名，不保留真实值。
- 长 token 只保留前后少量字符，例如 `abc...xyz`。
- 日志只粘贴必要片段，不上传完整日志文件。

## 11. 本地代理和证书

项目使用 mitmproxy 进行本地 HTTPS 捕获。安装 CA 证书、开启系统代理或恢复系统代理时，请确认操作对象是当前项目需要的本地代理配置。

注意事项：

- 只信任当前项目生成或明确确认的 mitmproxy CA 证书。
- 程序退出或停止代理后，应恢复系统代理。
- 如果程序异常退出后网络不可用，请检查系统代理是否仍指向本地端口。
- 不要把 `.mitmproxy/` 目录分享给他人。
- 不要把证书文件、私钥或系统证书截图提交到 Issue 或 PR。

## 12. SQLite 和本地归档

默认数据库：

```text
data/awa_public.sqlite3
```

默认文章归档：

```text
storages/
```

这些文件可能包含账号名称、文章标题、发布时间、短链接、互动指标、评论信息、原始 HTML 和请求证据。对外分享前需要确认是否符合研究伦理、平台规则和法律要求。

## 13. 安全问题反馈

如果你发现安全问题，请提交一个不包含敏感细节的 Issue，说明需要处理的安全问题。

请不要在公开 Issue 中粘贴：

- 真实 Cookie。
- 证书或私钥。
- SQLite 数据库。
- 完整运行日志。
- 真实文章归档。
- 带 `key`、`pass_ticket`、`appmsg_token` 的 URL。

如果讨论中出现敏感信息，请立即编辑删除，并提醒维护者。涉及隐私、安全或敏感数据时，不要在公开讨论中贴出细节。

## 14. 提交前检查清单

提交前建议确认：

- [ ] 代码改动范围与目标一致，没有顺手重构无关模块。
- [ ] 已运行与改动相关的测试。
- [ ] 没有提交 `.mitmproxy/`、`.playwright-browsers/`、`data/awa_public.sqlite3`、`data/logs/`、`data/tmp/`、`storages/`。
- [ ] 没有提交真实 Cookie、证书、数据库、文章归档、日志全文或带临时参数的 URL。
- [ ] 文档已同步更新。
- [ ] PR 中说明了已验证和未验证内容。


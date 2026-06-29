## 变更内容

- 

## 影响范围

- 

## 已验证

- [ ] `uv run python -m unittest tests.test_archive_cache_service tests.test_archive_excel_export_service`
- [ ] `uv run python -m unittest tests.test_home_article_cursor tests.test_wechat_window_activation`
- [ ] 已手动验证 Windows/微信/代理相关流程，或已在下方说明未验证原因

## 未验证内容

- 

## 安全检查

- [ ] 未提交 `.mitmproxy/`、`data/awa_public.sqlite3`、`storages/`、日志、证书或真实文章归档
- [ ] 日志、截图和测试数据中没有 `key`、`pass_ticket`、`appmsg_token`、Cookie 等敏感内容
- [ ] 已阅读 `doc/contributing_zh.md` 和 `doc/security_zh.md`

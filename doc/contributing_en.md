# Contributing Guide

Thank you for improving Access WeChat Article. This project involves Windows desktop windows, WeChat PC, local MITM, system proxy, SQLite, local archives, and Playwright offline cache. Please keep changes scoped, verification reproducible, and sensitive data private.

## 1. Project Positioning

This project is a local research assistant for academic research, coursework, and personal learning. It is not an online collection service, public deployment service, multi-user account system, or commercial data service.

Preferred contribution areas:

- Windows desktop interaction and local service stability.
- WeChat home window recognition, article candidate filtering, clicking, and window protection.
- MITM capture, request parsing, comment collection, and sensitive field redaction.
- SQLite index, local archive, Excel export, and cache cleanup.
- Playwright offline cache, resource filtering, and page completeness.
- Documentation, tests, CI, and release workflow.

Avoid submitting features that increase compliance risk, such as bypassing platform restrictions, bulk endpoint abuse, captcha avoidance, or account risk-control circumvention.

## 2. Development Environment

Python dependencies are managed with `uv`.

```bash
uv sync
```

This project no longer maintains `requirements.txt`. Dependencies are defined by:

- `pyproject.toml`
- `uv.lock`

Playwright browsers should be installed into the project directory to avoid using the global user cache:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH=".playwright-browsers"
uv run playwright install chromium
```

Do not use system Python, global pip, `pip install --user`, or manual dependency copying to modify the project environment.

## 3. Branches And Pull Requests

- Create a feature branch from `main`.
- Keep each pull request focused on one clear problem.
- Use clear PR titles, such as `fix: improve home window candidate filtering`.
- If a change affects configuration, data schema, directory structure, or user workflow, describe the migration path in the PR.
- Do not commit personal runtime data, databases, certificates, logs, cached pages, screenshots, or exported Excel files.

## 4. Code Boundaries

Follow existing module boundaries where possible:

- FastAPI routes belong in `src/app/fastapi_app/`.
- pywebview desktop capabilities belong in `src/app/pywebview_app/`.
- Task status, logs, and scheduling belong in `src/core/`.
- User configuration loading belongs in `src/config/`.
- MITM, system proxy, and certificates belong in `src/modules/proxy/`.
- WeChat home recognition, article candidates, and window protection belong in `src/modules/window/`.
- Article detail and comment parsing belong in `src/modules/detail/`.
- SQLite, local archive, deletion, and Excel export belong in `src/modules/storage/`.
- Playwright offline cache belongs in `src/modules/html_archive/`.
- Background execution flows belong in `src/workers/`.

Design requirements:

- Keep coupling low; avoid placing business logic in routes, window APIs, or one large worker.
- Keep logic testable with fake objects or mocks where possible.
- Keep operations recoverable when touching system proxy, certificates, processes, or temporary files.
- Redact sensitive values such as `key`, `pass_ticket`, `appmsg_token`, and Cookie in logs and API responses.

## 5. Documentation Maintenance

When changing user-visible behavior, update the relevant docs:

- Installation and startup changes: update `doc/install_zh.md` and `doc/install_en.md`.
- Page features, buttons, and workflow changes: update `doc/features_zh.md` and `doc/features_en.md`.
- Contribution rules, security boundaries, or sensitive data rules: update this file or `doc/security_en.md`.

The root README keeps the project presentation. Detailed instructions should go under `doc/`.

## 6. Testing Suggestions

Run tests related to your changes first.

Base service and archive related:

```bash
uv run python -m unittest tests.test_archive_cache_service tests.test_archive_delete_service tests.test_archive_excel_export_service tests.test_runtime_cleanup tests.test_sqlite_store
```

Window recognition related:

```bash
uv run python -m unittest tests.test_home_article_cursor tests.test_wechat_window_activation
```

Entry point syntax check:

```bash
uv run python -m py_compile main.py dev_server.py
```

Some tests depend on Windows, WeChat PC, system proxy, certificates, a real browser, or real network conditions. If you cannot verify them, state the unverified items and reasons in the PR.

## 7. Pre-submit Checklist

Before submitting, check:

- [ ] The change scope matches the goal and does not include unrelated refactors.
- [ ] Related tests have been run.
- [ ] `.mitmproxy/`, `.playwright-browsers/`, `data/awa_public.sqlite3`, `data/logs/`, `data/tmp/`, and `storages/` are not committed.
- [ ] No real Cookie, certificate, database, article archive, full log, or URL with temporary parameters is committed.
- [ ] Documentation is updated.
- [ ] The PR explains verified and unverified items.

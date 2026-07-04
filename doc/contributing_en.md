# Contribution, Conduct, And Security Guide

Thank you for improving Access WeChat Article. This project involves Windows desktop windows, WeChat PC, local MITM, system proxy, SQLite, local archives, and Playwright offline cache. Please keep changes scoped, verification reproducible, and sensitive data private.

This file combines contribution workflow, community conduct, and security boundaries into one collaboration guide.

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

- Installation and startup changes: update `doc/install.md` and `doc/install_en.md`.
- Page features, buttons, and workflow changes: update `doc/features.md` and `doc/features_en.md`.
- Contribution rules, conduct rules, security boundaries, or sensitive data rules: update this file and `doc/contributing.md`.

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

## 7. Code Of Conduct

Access WeChat Article is a project for learning, research, and local material management. We want discussions to stay direct, friendly, specific, fact-based, and mindful of law, platform rules, and research ethics.

Encouraged behavior:

- Clearly describe problems, reproduction steps, runtime environment, and what you have tried.
- Provide concrete suggestions for code, documentation, tests, and design.
- Respect different use cases, technical backgrounds, and research contexts.
- Be cautious when discussing platform rules, laws, ethics, and data safety.
- Clearly state uncertainty instead of inventing interface capabilities, experiment results, or project features.

Unacceptable behavior:

- Personal attacks, insults, harassment, discrimination, or malicious ridicule.
- Publishing other people's personal information, Cookie values, certificates, databases, chat records, article archives, or sensitive logs.
- Encouraging platform rule bypassing, copyright infringement, endpoint abuse, account risk-control circumvention, or non-compliant collection.
- Asking maintainers to assist with non-compliant use cases.
- Claiming nonexistent project capabilities or effects without evidence.

When submitting issues or pull requests, use clear titles, describe your goal and current blocker, provide minimal redacted reproduction information, and split independent problems into separate discussions.

Maintainers may edit or delete content containing sensitive information, ask for reproduction steps or redacted material, close duplicate or out-of-scope issues, reject contributions that increase compliance or security risk, and restrict participants who repeatedly disrupt discussion.

## 8. Security Boundary

Default supported scope:

- Windows 10/11 local desktop environment.
- The user's own WeChat PC client session.
- Local FastAPI service, defaulting to `127.0.0.1:8766`.
- Local MITM proxy, defaulting to `localhost:18000` or the configured local address.
- Local SQLite database and local article archive directory.

Not supported by default:

- Public Internet deployment.
- Multi-user shared services.
- Cloud collection services.
- Account hosting or remote control.
- Bypassing platform rules, captchas, account risk control, or access restrictions.

If you modify the code to listen on public addresses, expose remote APIs, or introduce account hosting, you need to reassess the security model and compliance risk.

## 9. Files That Must Not Be Committed

The following may contain personal data, certificates, runtime logs, article materials, or short-lived request parameters and should not be committed to Git:

- `.mitmproxy/`
- `.playwright-browsers/`
- `data/awa_public.sqlite3`
- `data/logs/`
- `data/tmp/`
- `storages/`
- `tests/artifacts/`
- `tests/output/`
- Exported `.xlsx`, `.csv`, `.db`, `.sqlite`, or `.sqlite3` files

If test samples are needed, use minimal redacted fake data. Do not use real accounts, real article archives, or real request parameters.

## 10. Sensitive Parameters

Runtime data may contain these temporary parameters:

- `key`
- `pass_ticket`
- `appmsg_token`
- `uin`
- `wxtoken`
- Cookie
- Set-Cookie
- WeChat article URLs with complete query strings

These values may be valid for a short time. They should be redacted in logs, tests, issues, pull requests, screenshots, and documentation.

Recommended redaction:

- Remove `key`, `pass_ticket`, and `appmsg_token` from URLs.
- Keep Cookie field names only, not real values.
- For long tokens, keep only a small prefix and suffix, such as `abc...xyz`.
- Paste only necessary log snippets; do not upload full log files.

## 11. Local Proxy And Certificates

The project uses mitmproxy for local HTTPS capture. When installing CA certificates, enabling the system proxy, or restoring the system proxy, make sure the target is the local proxy configuration needed by this project.

Notes:

- Trust only the mitmproxy CA certificate generated or confirmed for this project.
- Restore the system proxy after the program exits or the proxy is stopped.
- If network access fails after an abnormal exit, check whether the system proxy still points to a local port.
- Do not share the `.mitmproxy/` directory.
- Do not submit certificate files, private keys, or system certificate screenshots to issues or PRs.

## 12. SQLite And Local Archive

Default database:

```text
data/awa_public.sqlite3
```

Default article archive:

```text
storages/
```

These files may contain account names, article titles, publication times, short links, engagement metrics, comment information, raw HTML, and request evidence. Before sharing, make sure it complies with research ethics, platform rules, and applicable laws.

## 13. Security Issue Reporting

If you find a security issue, submit an issue without sensitive details and explain that a security issue needs to be handled.

Do not paste the following in public issues:

- Real Cookie values.
- Certificates or private keys.
- SQLite databases.
- Full runtime logs.
- Real article archives.
- URLs containing `key`, `pass_ticket`, or `appmsg_token`.

If sensitive information appears in a discussion, edit and remove it immediately, then notify the maintainers. Do not post private, security-related, or sensitive details in public discussions.

## 14. Pre-submit Checklist

Before submitting, check:

- [ ] The change scope matches the goal and does not include unrelated refactors.
- [ ] Related tests have been run.
- [ ] `.mitmproxy/`, `.playwright-browsers/`, `data/awa_public.sqlite3`, `data/logs/`, `data/tmp/`, and `storages/` are not committed.
- [ ] No real Cookie, certificate, database, article archive, full log, or URL with temporary parameters is committed.
- [ ] Documentation is updated.
- [ ] The PR explains verified and unverified items.


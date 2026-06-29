# Security Guide

Access WeChat Article is a local research assistant that interacts with WeChat PC windows, local proxy, certificates, SQLite database, runtime logs, and article archive files. Please pay close attention to local data safety, system proxy recovery, and sensitive field redaction.

## 1. Security Boundary

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

## 2. Files That Must Not Be Committed

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

## 3. Sensitive Parameters

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

## 4. Local Proxy And Certificates

The project uses mitmproxy for local HTTPS capture. When installing CA certificates, enabling the system proxy, or restoring the system proxy, make sure the target is the local proxy configuration needed by this project.

Notes:

- Trust only the mitmproxy CA certificate generated or confirmed for this project.
- Restore the system proxy after the program exits or the proxy is stopped.
- If network access fails after an abnormal exit, check whether the system proxy still points to a local port.
- Do not share the `.mitmproxy/` directory.
- Do not submit certificate files, private keys, or system certificate screenshots to issues or PRs.

## 5. SQLite And Local Archive

Default database:

```text
data/awa_public.sqlite3
```

Default article archive:

```text
storages/
```

These files may contain account names, article titles, publication times, short links, engagement metrics, comment information, raw HTML, and request evidence. Before sharing, make sure it complies with research ethics, platform rules, and applicable laws.

## 6. Security Issue Reporting

If you find a security issue, submit an issue without sensitive details and explain that a security issue needs to be handled.

Do not paste the following in public issues:

- Real Cookie values
- Certificates or private keys
- SQLite databases
- Full runtime logs
- Real article archives
- URLs containing `key`, `pass_ticket`, or `appmsg_token`

## 7. Maintainer Handling Policy

Maintainers may delete issues, comments, PR attachments, or screenshots that contain sensitive information and ask the reporter to provide redacted material.

If a topic involves compliance risk, account safety, or platform rule risk, maintainers may pause public discussion, move to private communication, or close the request.

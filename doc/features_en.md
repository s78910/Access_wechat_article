# Feature Guide

This document describes the current main features. For installation, see [Installation Guide](./install_en.md). For the project overview, see [README_en.md](./README_en.md).

## 1. Main Collection Service

The main service identifies articles from a WeChat PC public account, service account, or subscription account home page, then opens articles according to the configured collection count.

Basic flow:

1. Log in to WeChat PC.
2. Open the target public account, service account, or subscription account home page in WeChat.
3. Set the collection count on the main service page.
4. Click "Start".
5. The program identifies article candidates on the home page, opens them one by one, and waits for MITM to capture article requests.
6. The program saves structured article information, request evidence, and comment information when available.

The main flow prioritizes real public account or service account home windows and avoids selecting chat windows, hidden shell windows, or article detail windows.

## 2. Proxy Tool

The proxy tool starts the local MITM proxy and works with the system proxy to capture article requests from the WeChat built-in browser.

Default listener:

```text
127.0.0.1:18000
```

Capabilities:

- Start MITM proxy
- Stop MITM proxy
- Enable system proxy
- Restore system proxy
- Test proxy connection
- View MITM runtime status

When the program exits or the proxy is manually stopped, the original system proxy should be restored to avoid affecting browsers or other software.

## 3. Certificate Installation

WeChat article pages are HTTPS pages, so MITM capture requires the mitmproxy CA certificate.

Certificate capabilities:

- Check whether the certificate is installed
- Install the CA certificate from the current project `.mitmproxy/` directory
- List mitmproxy-related certificates in the system
- Delete mitmproxy certificates confirmed by the user

Windows may show a confirmation dialog during certificate installation. Follow the system prompt to confirm.

## 4. Local Article Archive

After successful collection, article data is saved under:

```text
storages/account_name/article_publish_time article_title/
```

Main files:

- `article_detail.json`: structured article information, including title, account name, publication time, short link, read count, like count, share count, recommendation count, comment count, and related fields
- Comment-related JSON files, depending on current comment collection capability

Raw MITM capture data is runtime diagnostic data and is stored under `data/logs/article_capture/` by default. It may contain short-lived sensitive parameters such as `key`, `pass_ticket`, and `appmsg_token`; do not share it publicly.

## 5. Data Archive

The data archive page is used to view and manage collected account and article records.

Capabilities:

- View account list
- View article records under an account
- View archive status and local storage usage
- Delete selected article records and their local archives
- Delete an account and all its article archives
- Open the project `storages/` directory

The archive index is read from:

```text
data/awa_public.sqlite3
```

## 6. Article Cache

Article cache reads short links from SQLite, opens pages with Playwright, and saves offline pages.

Output location:

```text
storages/account_name/article_publish_time article_title/index.html
storages/account_name/article_publish_time article_title/assets/
```

Characteristics:

- Uses randomized browser request headers
- Does not include MITM `key` parameters
- Finishes short articles quickly
- Uses adaptive scrolling to preserve long articles as completely as possible
- Saves only resources actually referenced by the page
- Default batch concurrency limit is 3

If a "Read Original" link exists near the article bottom, the offline page attempts to preserve the link.

## 7. Excel Export

The data archive page supports batch Excel export by account.

Export rules:

- Each account generates a separate Excel file
- File name format: `account_name_article_records_N_items_YYYYMMDD_HHMMSS.xlsx`
- Articles are sorted by publication time in descending order
- If `article_detail.json` is missing, existing SQLite fields are still exported
- Missing metric fields are left blank, and the reason is written into the "record status" column

Excel headers:

```text
Index, Record Status, Publish Time, Article Title, Article Short Link, Audience Count, Read Count, Like Count, Share Count, Recommendation Count, Comment Count, Record Collection Time
```

Export files are first written to:

```text
data/tmp/archive_excel_export_*/
```

Then copied to the user-selected output directory.

## 8. System Settings

The system settings page is used to view and modify runtime configuration.

Common settings:

- Proxy listen host and port
- Proxy startup delay
- Whether to take over the system proxy automatically
- Whether to clean temporary files automatically
- Log level
- Request interval
- Retry count
- Proxy verification URL

Configuration file:

```text
data/custom.yaml
```

## 9. Runtime Logs

Runtime logs are saved under:

```text
data/logs/yyyy-mm-dd/*.log
```

The main service page also shows recent runtime logs. Logs help troubleshoot:

- Whether MITM is started
- Whether system proxy is enabled
- Whether the home window is recognized
- Whether article candidates are found
- Whether article requests are captured
- Whether local archive writing succeeds
- Whether cache or export tasks fail

## 10. Temporary File Cleanup

The program uses `data/tmp/` for runtime temporary files, such as cache tasks, export intermediates, and window probe results.

When automatic temporary cleanup is enabled, the program cleans safe-to-delete files under `data/tmp/` at startup while keeping files needed by the current run.

## 11. Common Feature Issues

### Proxy Started But Web Pages Cannot Be Opened

Check:

- Whether the MITM proxy is running
- Whether the system proxy points to `127.0.0.1:18000`
- Whether the mitmproxy CA certificate is installed and trusted
- Whether another proxy tool has taken over the system proxy
- Whether the system proxy was restored when the program exited

### Program Recognizes The WeChat Chat Window

Make sure the currently opened WeChat window is a public account, service account, or subscription account home page, not a chat page or article detail page. The current main flow prioritizes home windows, but if window focus or visible content is abnormal, reopen the home page and run again.

### Where To Check Failure Reasons

Check:

```text
data/logs/yyyy-mm-dd/*.log
```

You can also view recent errors in the main service runtime log area.

<h1 align="center">Access WeChat Article</h1>

<p align="center">
  <strong>A research assistant for academic work and public article material management</strong>
</p>

<p align="center">
  <a href="../README.md">简体中文</a> | <a href="./README_en.md">English</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.13">
  <img src="https://img.shields.io/badge/requests-http-009688?style=flat-square&logo=python&logoColor=white" alt="requests http">
  <img src="https://img.shields.io/badge/SQLite-storage-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite storage">
  <img src="https://img.shields.io/badge/License-CC_BY--NC--SA_4.0-6C5CE7?style=flat-square" alt="License CC BY-NC-SA 4.0">
  <a href="https://zread.ai/yeximm/Access_wechat_article"><img src="https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff" alt="zread"></a>
</p>

<p align="center">
  <img src="../README/6b365eb7-fdc7-4031-bbda-ffc26196033e.png" alt="Access WeChat Article research workbench hero" width="92%">
</p>

---

**Access_WeChat_Article** is a Python-based local research tool for helping researchers systematically organize public WeChat article materials and related metadata, including article titles, publication times, short links, collection status, and available engagement metrics.

The project is designed for controllable, traceable, and reusable research workflows. It is suitable for communication studies, journalism, social science, public issue research, content analysis, course papers, and personal research projects.

> 📌 **Notice**
>
> This project is intended for academic research, coursework, and personal learning scenarios.
>
> Users should comply with WeChat platform rules, applicable laws, and research ethics when processing public article materials, citations, and research outputs.
>
> Legal, platform, and ethical responsibilities arising from use of this project are borne by the user.

---

## 📦 Development And Contribution

The v2 release currently supports **Windows** only, mainly Windows 10/11 desktop usage and local development. Linux and macOS are not target environments for v2.

If you want to study, modify, or extend this project, please fork the repository first and work on your own branch. The Python environment is managed with `uv`; do not install dependencies into the system Python environment.

Contributions are welcome in these areas:

- Desktop interaction, MITM capture workflow, structured fields, task scheduling, research workflow, and performance improvements.
- Issues for bugs, feature requests, and technical discussion.
- Pull requests for code, documentation, tests, or workflow improvements.
- CI, testing, and type checking improvements.

For detailed contribution, conduct, and security guidance, see [Contribution Guide](./contributing_en.md).

---

## ✨ Highlights

- **Research-oriented workflow**: Designed for public article material management in communication studies, social science, public issue research, content analysis, course papers, and research projects.
- **Structured research fields**: Records account name, title, publication time, short link, engagement metrics, task status, and related metadata.
- **Traceable collection process**: Keeps sample selection, material organization, task progress, and failure states in one local workflow.
- **Analysis-ready records**: Prepares collected materials for manual coding, topic labeling, statistical summaries, text processing, and paper writing.
- **Windows desktop workbench**: Uses WebView2 to provide a visual interface for task configuration, status monitoring, history records, and system settings.

<table>
  <tr>
    <td width="50%">
      <strong>📚 Public Article Material Management</strong><br>
      Organize public WeChat article titles, account names, publication times, short links, and collection status into reusable research records.
    </td>
    <td width="50%">
      <strong>🧾 Structured Research Metadata</strong><br>
      Build consistent fields around article details, engagement metrics, collection time, task result, and duration.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <strong>📈 Engagement Metrics</strong><br>
      Record available reading, like, recommendation, comment, and other metrics for communication performance analysis.
    </td>
    <td width="50%">
      <strong>📊 Task Progress And Failure Records</strong><br>
      Use status fields and runtime logs to reduce repeated manual checks and missing records.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <strong>🧪 Analysis Preparation</strong><br>
      Prepare collected materials for content analysis, manual coding, topic labeling, text cleaning, and descriptive statistics.
    </td>
    <td width="50%">
      <strong>🖥️ Windows Desktop Workbench</strong><br>
      Manage task configuration, runtime status, history records, and system settings through a local desktop application.
    </td>
  </tr>
</table>

---

## 🚀 Quick Start

Access WeChat Article v2 currently supports **Windows 10/11**. Python dependencies are managed with `uv`.

```bash
git clone https://github.com/yeximm/Access_wechat_article.git
cd Access_wechat_article
uv sync
```

Install Playwright Chromium into the project directory:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH=".playwright-browsers"
uv run playwright install chromium
```

Start the desktop application:

```bash
uv run python main.py
```

After startup, the local web interface is also available at:

```text
http://127.0.0.1:8766/
```

For full setup instructions, see [Installation Guide](./install_en.md). For feature details, see [Feature Guide](./features_en.md).

---

## Visual Workflow

This section shows the overall runtime flow. The Mermaid diagram describes how the core modules work together.

```mermaid
flowchart LR
    A["Windows Desktop Workbench<br/>Vue 3 + WebView2"]
    A --> B["FastAPI Local Service"]
    B --> C["Task Scheduling And Runtime Status"]
    C --> D["MITM Proxy And Request Parsing"]
    C --> E["Background Worker<br/>Article Details / Comments"]
    D --> E
    E --> F["Structured Field Records"]
    C --> F["Runtime Logs And Progress Feedback"]
    F --> B
```

The architecture image provides a more visual view of the collaboration between the desktop client, backend service, proxy parser, background tasks, and UI.

<p align="center">
  <img src="../README/64a99030-d5ec-4ddc-8802-1ae9a4a05626.png" alt="Access WeChat Article visual workflow architecture" width="92%">
  <sub>Access WeChat Article overall workflow architecture</sub>
</p>

---

## Feature Overview

This section shows the main application pages.

### Main Service: Task Configuration And Runtime Monitoring

The main service page is used to set collection count, select collection content, start or stop tasks, and view account recognition results, task progress, proxy status, network speed, and runtime logs.

<p align="center">
  <img src="../README/image-20260628122809991.png" alt="Main service page" width="92%">
</p>

### Data Archive: Account List And Record Details

The data archive page is used to browse account-level material lists, article counts, update times, record details, archive status, and quick operations.

<p align="center">
  <img src="../README/image-20260628153743002.png" alt="Data archive page" width="92%">
</p>

### Collection History: Search And Summary

The history page is used to filter records by keyword, collection type, task status, and date, and to view record details, success rate, latest collection date, and recent trends.

<p align="center">
  <img src="../README/image-20260628123525585.png" alt="Collection history page" width="92%">
</p>

### System Settings: Runtime And Proxy Configuration

The settings page is used to manage base configuration, proxy switches, system proxy, CA certificates, environment checks, and cache cleanup.

<p align="center">
  <img src="../README/image-20260628123624595.png" alt="System settings page" width="92%">
</p>

---

## Support

If this project helps your research workflow, a GitHub Star is appreciated.

For questions, feature requests, or discussions, please use GitHub Issues.

<p align="center">
  <img src="../README/qrcode_1749894334903.jpg" alt="Project discussion QR code" width="300" />
</p>

[![Stargazers repo roster for @yeximm/Access_wechat_article](https://reporoster.com/stars/yeximm/Access_wechat_article)](https://github.com/yeximm/Access_wechat_article/stargazers)
[![Forkers repo roster for @yeximm/Access_wechat_article](https://reporoster.com/forks/yeximm/Access_wechat_article)](https://github.com/yeximm/Access_wechat_article/network/members)

---

## License

This project uses the [`CC BY-NC-SA 4.0`](https://creativecommons.org/licenses/by-nc-sa/4.0/) license. For the full terms, see the [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/) license.

Please read the license and project notice carefully before viewing, using, copying, modifying, or redistributing the repository content.

- Use, modification, and distribution of this project should comply with `CC BY-NC-SA 4.0` and applicable laws.
- Any modification, extension, deployment, distribution, or secondary development based on this repository is the responsibility of the user or third party.
- Third-party software, hardware, platforms, or tools mentioned in this repository are only used to describe the runtime environment or technical background.
- Risks and consequences arising from the use of third-party software, hardware, platforms, or tools are borne by the actual user.

## Star History

<picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=yeximm/Access_wechat_article&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=yeximm/Access_wechat_article&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=yeximm/Access_wechat_article&type=date&legend=top-left" />
</picture>

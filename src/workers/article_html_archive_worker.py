from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

from src.core.config import DEFAULT_DB_PATH, PROJECT_ROOT
from src.modules.html_archive.article_html_archiver import archive_article_html
from src.modules.html_archive.models import ArticleHtmlArchiveConfig, ArticleHtmlArchiveTask
from src.modules.html_archive.sqlite_task_reader import load_saved_article_html_archive_tasks


ArchiveFunc = Callable[[ArticleHtmlArchiveTask, ArticleHtmlArchiveConfig], object]


def run_html_archive_tasks(
    tasks: Iterable[ArticleHtmlArchiveTask],
    config: ArticleHtmlArchiveConfig | None = None,
    *,
    archive_func: ArchiveFunc = archive_article_html,
    executor_factory=ProcessPoolExecutor,
) -> list[object]:
    config = config or ArticleHtmlArchiveConfig()
    task_list = list(tasks)
    if not task_list:
        return []
    max_workers = max(1, min(int(config.concurrency or 1), len(task_list)))
    with executor_factory(max_workers=max_workers) as executor:
        futures = [executor.submit(archive_func, task, config) for task in task_list]
        return [future.result() for future in futures]


def run_article_html_archive_worker(event_queue=None, config: dict | None = None) -> None:
    payload = dict(config or {})
    db_path = Path(payload.get("db_path") or DEFAULT_DB_PATH)
    storage_root = Path(payload.get("storage_root") or (PROJECT_ROOT / "storages"))
    limit = int(payload.get("limit") or 1)
    archive_config = ArticleHtmlArchiveConfig(
        headless=bool(payload.get("headless", True)),
        concurrency=int(payload.get("concurrency") or 2),
    )
    tasks = load_saved_article_html_archive_tasks(db_path, storage_root=storage_root, limit=limit)
    _put_event(event_queue, "html_archive_started", {"task_count": len(tasks)})
    results = run_html_archive_tasks(tasks, archive_config)
    _put_event(event_queue, "html_archive_finished", {"results": [_result_to_dict(result) for result in results]})


def _result_to_dict(result: object) -> dict[str, object]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"ok": False, "message": str(result)}


def _put_event(event_queue, event_type: str, payload: dict[str, object]) -> None:
    if event_queue is None:
        return
    try:
        event_queue.put({"type": event_type, **payload})
    except Exception:
        return


__all__ = ["run_article_html_archive_worker", "run_html_archive_tasks"]

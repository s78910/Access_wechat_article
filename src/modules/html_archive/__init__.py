"""微信文章 HTML 离线归档模块。"""

from src.modules.html_archive.article_html_archiver import archive_article_html
from src.modules.html_archive.models import ArticleHtmlArchiveConfig, ArticleHtmlArchiveResult, ArticleHtmlArchiveTask
from src.modules.html_archive.sqlite_task_reader import load_saved_article_html_archive_tasks

__all__ = [
    "ArticleHtmlArchiveConfig",
    "ArticleHtmlArchiveResult",
    "ArticleHtmlArchiveTask",
    "archive_article_html",
    "load_saved_article_html_archive_tasks",
]

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.modules.system.safe_directory_cleaner import SafeDirectoryCleaner


BusyCheck = Callable[[], str | None]


@dataclass(frozen=True, slots=True)
class RuntimeCacheClearResult:
    ok: bool
    status: str
    message: str
    temp_dir: Path
    http_status: int = 200
    removed_file_count: int = 0
    removed_directory_count: int = 0
    freed_bytes: int = 0
    skipped: tuple[dict[str, str], ...] = field(default_factory=tuple)

    @property
    def removed_count(self) -> int:
        return self.removed_file_count + self.removed_directory_count

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "removedCount": self.removed_count,
            "removedFileCount": self.removed_file_count,
            "removedDirectoryCount": self.removed_directory_count,
            "freedBytes": self.freed_bytes,
            "skippedCount": len(self.skipped),
            "skipped": list(self.skipped),
            "tempDir": str(self.temp_dir),
            "message": self.message,
        }


class RuntimeCacheClearService:
    """校验运行状态和目录边界后，清理配置指定的临时目录。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        config: Any,
        busy_check: BusyCheck | None = None,
        cleaner: SafeDirectoryCleaner | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._config = config
        self._busy_check = busy_check or (lambda: None)
        self._cleaner = cleaner or SafeDirectoryCleaner()

    def clear(self) -> RuntimeCacheClearResult:
        temp_dir = Path(self._config.storage.temp_dir).resolve()
        busy_reason = self._busy_check()
        if busy_reason:
            return RuntimeCacheClearResult(
                ok=False,
                status="busy",
                message=f"{busy_reason}，请等待运行结束后再清理缓存。",
                temp_dir=temp_dir,
                http_status=409,
            )

        protected_reason = self._protected_path_reason(temp_dir)
        if protected_reason:
            return RuntimeCacheClearResult(
                ok=False,
                status="protected-path",
                message=f"拒绝清理临时目录：{protected_reason}",
                temp_dir=temp_dir,
                http_status=400,
            )

        try:
            clean_result = self._cleaner.clear_contents(temp_dir)
        except Exception as exc:
            return RuntimeCacheClearResult(
                ok=False,
                status="failed",
                message=f"清理临时缓存失败：{exc}",
                temp_dir=temp_dir,
                http_status=500,
            )

        message = (
            f"已清理 {clean_result.removed_count} 项临时缓存。"
            if clean_result.ok
            else (
                f"已清理 {clean_result.removed_count} 项临时缓存，"
                f"{clean_result.skipped_count} 项被占用或无权限。"
            )
        )
        return RuntimeCacheClearResult(
            ok=clean_result.ok,
            status=clean_result.status,
            message=message,
            temp_dir=temp_dir,
            removed_file_count=clean_result.removed_file_count,
            removed_directory_count=clean_result.removed_directory_count,
            freed_bytes=clean_result.freed_bytes,
            skipped=tuple(clean_result.skipped),
        )

    def _protected_path_reason(self, temp_dir: Path) -> str | None:
        if temp_dir == Path(temp_dir.anchor):
            return "不能清理磁盘根目录"
        if temp_dir == self._project_root:
            return "不能清理项目根目录"
        if not temp_dir.is_relative_to(self._project_root):
            return "临时目录必须位于项目目录内"

        for label, protected_path in self._protected_paths():
            if _paths_overlap(temp_dir, protected_path):
                return f"临时目录与受保护的{label}重叠（{protected_path}）"
        return None

    def _protected_paths(self) -> tuple[tuple[str, Path], ...]:
        storage = self._config.storage
        proxy = getattr(self._config, "proxy", None)
        configured_paths: list[tuple[str, Path]] = [
            ("文章归档目录", Path(storage.article_storage_root).resolve()),
            ("数据库目录", Path(storage.db_dir).resolve()),
            ("日志目录", Path(storage.log_dir).resolve()),
            ("数据库脚本目录", (self._project_root / "data" / "sql").resolve()),
            ("前端构建目录", (self._project_root / "src" / "webview").resolve()),
            ("配置文件", (self._project_root / "data" / "custom.yaml").resolve()),
        ]
        confdir = getattr(proxy, "confdir", None)
        if confdir is not None:
            configured_paths.append(("MITM 配置目录", Path(confdir).resolve()))
        return tuple(configured_paths)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


__all__ = ["RuntimeCacheClearResult", "RuntimeCacheClearService"]

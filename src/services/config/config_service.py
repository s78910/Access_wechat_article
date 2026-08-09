from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from src.config.app_config import AppConfig
from src.config.config_loader import load_app_config, load_system_app_config
from src.config.config_writer import restore_config_file


class AppConfigLoader(Protocol):
    def __call__(
        self,
        config_path: str | Path,
        *,
        project_root: str | Path,
        system_config_path: str | Path | None = None,
    ) -> AppConfig: ...


@dataclass(frozen=True, slots=True)
class ConfigRestoreResult:
    config: AppConfig
    config_path: Path
    backup_path: Path | None


class ConfigService:
    """在程序启动时加载配置，并向业务流程提供同一份内存对象。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        config_path: str | Path | None = None,
        system_config_path: str | Path | None = None,
        loader: AppConfigLoader = load_app_config,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        raw_path = Path(config_path) if config_path is not None else Path("data/custom.yaml")
        self._config_path = (
            raw_path.resolve()
            if raw_path.is_absolute()
            else (self._project_root / raw_path).resolve()
        )
        raw_system_path = (
            Path(system_config_path)
            if system_config_path is not None
            else Path("src/config/system.yaml")
        )
        self._system_config_path = (
            raw_system_path.resolve()
            if raw_system_path.is_absolute()
            else (self._project_root / raw_system_path).resolve()
        )
        self._loader = loader
        self._lock = RLock()
        self._current = self._load()

    @property
    def current(self) -> AppConfig:
        """返回当前内存配置；此操作不会重新读取 YAML。"""
        with self._lock:
            return self._current

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def system_config_path(self) -> Path:
        return self._system_config_path

    def reload(self) -> AppConfig:
        """显式重新读取并校验 YAML，成功后原子替换内存配置。"""
        loaded = self._load()
        with self._lock:
            self._current = loaded
            return self._current

    def restore_system_defaults(self) -> ConfigRestoreResult:
        """校验系统配置后覆盖 custom.yaml，并原子替换当前内存配置。"""
        loaded = load_system_app_config(
            self._system_config_path,
            project_root=self._project_root,
        )
        file_result = restore_config_file(
            system_config_path=self._system_config_path,
            custom_config_path=self._config_path,
        )
        with self._lock:
            self._current = loaded
        return ConfigRestoreResult(
            config=loaded,
            config_path=file_result.config_path,
            backup_path=file_result.backup_path,
        )

    def _load(self) -> AppConfig:
        return self._loader(
            self._config_path,
            project_root=self._project_root,
            system_config_path=self._system_config_path,
        )


__all__ = ["ConfigRestoreResult", "ConfigService"]

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConfigFileRestoreResult:
    config_path: Path
    backup_path: Path | None


def restore_config_file(
    *,
    system_config_path: str | Path,
    custom_config_path: str | Path,
) -> ConfigFileRestoreResult:
    """使用系统 YAML 原子替换用户 YAML，并保留一份最近备份。"""
    source = Path(system_config_path).resolve()
    target = Path(custom_config_path).resolve()
    system_content = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Path | None = None
    if target.is_file():
        backup_path = target.with_name(f"{target.name}.bak")
        shutil.copy2(target, backup_path)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as file:
            file.write(system_content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, target)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return ConfigFileRestoreResult(
        config_path=target,
        backup_path=backup_path,
    )


__all__ = ["ConfigFileRestoreResult", "restore_config_file"]

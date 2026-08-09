from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.domain.enums import ErrorCode
from src.domain.errors import DomainError


SCHEMA_VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)$")


class SchemaLoadError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.DB_INIT_FAILED, message)


@dataclass(frozen=True, slots=True)
class SchemaDefinition:
    version: str
    path: Path
    sql: str


def schema_file_name(version: str) -> str:
    """把版本精确映射为脚本名，不扫描目录寻找最新文件。"""
    match = SCHEMA_VERSION_PATTERN.fullmatch(version.strip())
    if not match:
        raise SchemaLoadError(f"无效的数据表版本：{version}")
    major, minor = match.groups()
    return f"create_awa_v{major}_{minor}.sql"


def load_schema(version: str, *, project_root: str | Path) -> SchemaDefinition:
    root = Path(project_root).resolve()
    path = root / "data/sql/create_script" / schema_file_name(version)
    if not path.is_file():
        raise SchemaLoadError(f"建表脚本不存在：{path}")
    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        raise SchemaLoadError(f"建表脚本为空：{path}")
    return SchemaDefinition(version=version, path=path, sql=sql)

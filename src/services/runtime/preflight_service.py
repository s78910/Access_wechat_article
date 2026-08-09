from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import socket
from typing import Callable, Iterable
from uuid import uuid4

from src.domain.enums import ErrorCode
from src.domain.models import TaskContext
from src.domain.results import ServiceResult
from src.storage.sqlite.database_initializer import validate_database


@dataclass(frozen=True, slots=True)
class CapturePreflightReport:
    database_path: Path
    storage_root: Path
    temp_dir: Path
    proxy_address: str


class CapturePreflightService:
    """任务级预检；不执行 HTTPS 请求，也不重复初始化数据库。"""

    def __init__(
        self,
        *,
        proxy_host: str,
        proxy_port: int,
        ca_cert_path: str | Path | None,
        port_in_use: Callable[[str, int], bool] | None = None,
        dependency_checker: Callable[[Iterable[str]], tuple[str, ...]] | None = None,
    ) -> None:
        self.proxy_host = proxy_host
        self.proxy_port = int(proxy_port)
        self.ca_cert_path = None if ca_cert_path is None else Path(ca_cert_path)
        self._port_in_use = port_in_use or _port_in_use
        self._dependency_checker = dependency_checker or _missing_dependencies

    def run(self, context: TaskContext) -> ServiceResult[CapturePreflightReport]:
        try:
            validate_database(context.db_path)
            _ensure_writable_directory(context.storage_root)
            _ensure_writable_directory(context.temp_dir)
            if self._port_in_use(self.proxy_host, self.proxy_port):
                raise RuntimeError(f"MITM 端口 {self.proxy_port} 已被其他进程占用")
            if self.ca_cert_path is not None and not self.ca_cert_path.is_file():
                raise RuntimeError(f"MITM CA 证书不存在：{self.ca_cert_path}")
            missing = self._dependency_checker(("mitmproxy", "uiautomation"))
            if missing:
                raise RuntimeError(f"缺少运行依赖：{', '.join(missing)}")
            return ServiceResult.success(
                CapturePreflightReport(
                    database_path=context.db_path,
                    storage_root=context.storage_root,
                    temp_dir=context.temp_dir,
                    proxy_address=f"{self.proxy_host}:{self.proxy_port}",
                )
            )
        except Exception as exc:
            return ServiceResult.failure(ErrorCode.PREFLIGHT_FAILED, str(exc))


def _ensure_writable_directory(path: Path) -> None:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / f".awa-write-probe-{uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex((host, int(port))) == 0


def _missing_dependencies(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(name for name in names if importlib.util.find_spec(name) is None)

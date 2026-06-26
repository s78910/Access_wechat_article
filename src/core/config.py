from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = DATA_DIR
DB_DIR = DATA_DIR
LOG_DIR = DATA_DIR / "logs"
TMP_DIR = DATA_DIR / "tmp"
MITMPROXY_CONF_DIR = PROJECT_ROOT / ".mitmproxy"
DEFAULT_DB_PATH = DB_DIR / "awa_public.sqlite3"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "custom.yaml"


@dataclass(frozen=True)
class ProxyConfig:
    host: str = "127.0.0.1"
    port: int = 18000
    startup_delay_seconds: float = 0
    enable_system_proxy: bool = True
    verification_url: str = "http://mitm.it/"
    confdir: Path = MITMPROXY_CONF_DIR
    ssl_insecure: bool = True

    def to_worker_payload(self) -> dict:
        data = asdict(self)
        data["confdir"] = str(self.confdir)
        return data


@dataclass(frozen=True)
class AppFeatureConfig:
    auto_save_content: bool = True
    auto_clean_temp_files: bool = True
    auto_start_proxy: bool = True
    log_level: str = "INFO"
    request_interval_seconds: float = 2
    retry_count: int = 3
    version: str = "2.0.0"


@dataclass(frozen=True)
class StorageConfig:
    db_path: Path = DEFAULT_DB_PATH


@dataclass(frozen=True)
class AppRuntimeConfig:
    app: AppFeatureConfig = AppFeatureConfig()
    proxy: ProxyConfig = ProxyConfig()
    storage: StorageConfig = StorageConfig()

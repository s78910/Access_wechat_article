from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.core.config import (
    AppFeatureConfig,
    AppRuntimeConfig,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    ProxyConfig,
    StorageConfig,
)
from src.core.log_levels import normalize_log_level


def load_runtime_config(config_path: str | Path | None = None) -> AppRuntimeConfig:
    """从 data/custom.yaml 读取用户运行配置。"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    data = _read_config_file(path)

    app_data = data.get("app", data)
    proxy_data = data.get("proxy", {})
    storage_data = data.get("storage", {})

    app = AppFeatureConfig(
        auto_save_content=_get_bool(app_data, "auto_save_content", True),
        auto_clean_temp_files=_get_bool(app_data, "auto_clean_temp_files", True),
        auto_start_proxy=_get_bool(app_data, "auto_start_proxy", True),
        log_level=normalize_log_level(_get_alias(app_data, ("log_level", "logLevel"), data.get("log_level", "INFO"))),
        request_interval_seconds=max(0.0, _get_float_alias(app_data, ("request_interval_seconds", "requestIntervalSeconds"), 2)),
        retry_count=max(0, _get_int_alias(app_data, ("retry_count", "retryCount"), 3)),
        version=str(app_data.get("version", "2.0.0")),
    )
    proxy = ProxyConfig(
        host=str(proxy_data.get("host", "127.0.0.1")),
        port=_get_int(proxy_data, "port", 18000),
        startup_delay_seconds=_get_float(proxy_data, "startup_delay_seconds", 0),
        enable_system_proxy=_get_bool(data, "enable_system_proxy", True),
        verification_url=str(proxy_data.get("verification_url", "http://mitm.it/")),
        confdir=_resolve_config_path(proxy_data.get("confdir", ProxyConfig.confdir), path.parent),
        ssl_insecure=_get_bool(proxy_data, "ssl_insecure", True),
    )
    storage = StorageConfig(
        db_path=_resolve_config_path(storage_data.get("db_path", DEFAULT_DB_PATH), path.parent),
    )

    return AppRuntimeConfig(app=app, proxy=proxy, storage=storage)


def update_runtime_config_from_payload(
    payload: dict[str, Any] | str,
    current: AppRuntimeConfig | None = None,
) -> AppRuntimeConfig:
    """把前端传入的配置字段转换成后端运行配置对象。"""
    data = _coerce_payload(payload)
    base = current or AppRuntimeConfig()
    app_data = data.get("app", data)
    proxy_data = data.get("proxy", {})
    storage_data = data.get("storage", {})

    app = AppFeatureConfig(
        auto_save_content=_get_bool_alias(
            app_data,
            ("auto_save_content", "autoSaveContent"),
            base.app.auto_save_content,
        ),
        auto_clean_temp_files=_get_bool_alias(
            app_data,
            ("auto_clean_temp_files", "autoCleanTempFiles"),
            base.app.auto_clean_temp_files,
        ),
        auto_start_proxy=_get_bool_alias(
            app_data,
            ("auto_start_proxy", "autoStartProxy"),
            base.app.auto_start_proxy,
        ),
        log_level=normalize_log_level(
            _get_alias(app_data, ("log_level", "logLevel"), base.app.log_level),
            base.app.log_level,
        ),
        request_interval_seconds=max(
            0.0,
            _get_float_alias(app_data, ("request_interval_seconds", "requestIntervalSeconds"), base.app.request_interval_seconds),
        ),
        retry_count=max(0, _get_int_alias(app_data, ("retry_count", "retryCount"), base.app.retry_count)),
        version=str(_get_alias(app_data, ("version", "appVersion"), base.app.version)),
    )
    proxy = ProxyConfig(
        host=str(_get_alias(proxy_data, ("host",), base.proxy.host)),
        port=_get_int_alias(proxy_data, ("port",), base.proxy.port),
        startup_delay_seconds=_get_float_alias(
            proxy_data,
            ("startup_delay_seconds", "startupDelaySeconds"),
            base.proxy.startup_delay_seconds,
        ),
        enable_system_proxy=_get_bool_alias(
            data,
            ("enable_system_proxy", "enableSystemProxy"),
            base.proxy.enable_system_proxy,
        ),
        verification_url=str(
            _get_alias(
                proxy_data,
                ("verification_url", "verificationUrl"),
                base.proxy.verification_url,
            )
        ),
        confdir=_resolve_config_path(_get_alias(proxy_data, ("confdir",), base.proxy.confdir), Path(DEFAULT_CONFIG_PATH).parent),
        ssl_insecure=_get_bool_alias(
            proxy_data,
            ("ssl_insecure", "sslInsecure"),
            base.proxy.ssl_insecure,
        ),
    )
    storage = StorageConfig(
        db_path=_resolve_config_path(
            _get_alias(storage_data, ("db_path", "dbPath"), base.storage.db_path),
            Path(DEFAULT_CONFIG_PATH).parent,
        ),
    )

    return AppRuntimeConfig(app=app, proxy=proxy, storage=storage)


def save_runtime_config(
    config: AppRuntimeConfig,
    config_path: str | Path | None = None,
) -> Path:
    """把运行配置写回 data/custom.yaml。"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_runtime_config(config, config_dir=path.parent), encoding="utf-8")
    return path


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}

    if path.suffix.lower() == ".json":
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {}

    try:
        from ruamel.yaml import YAML

        loaded = YAML(typ="safe").load(text)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return _read_simple_yaml(text)


def _coerce_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        loaded = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _format_runtime_config(config: AppRuntimeConfig, *, config_dir: Path | None = None) -> str:
    return "\n".join(
        [
            "# 用户可修改配置。修改后重启软件生效。",
            "",
            "# 内容自动保存：true 时，mitm 捕获到文章列表后写入 SQLite。",
            f"auto_save_content: {_format_bool(config.app.auto_save_content)}",
            "",
            "# 自动清理临时文件：当前先保留配置项，后续接入临时文件清理逻辑。",
            f"auto_clean_temp_files: {_format_bool(config.app.auto_clean_temp_files)}",
            "",
            "# 开启代理：true 时，打开软件后自动启动 mitm 监听。",
            f"auto_start_proxy: {_format_bool(config.app.auto_start_proxy)}",
            "",
            "# 当前开发版本号，供主服务页运行环境区域显示。",
            "# log_level: DEBUG 最详细；INFO 默认；WARN 仅警告和错误；ERROR 仅错误。",
            f"log_level: {normalize_log_level(config.app.log_level)}",
            "",
            "# 请求间隔时间：每篇文章处理完成后，进入下一篇前等待的秒数。",
            f"request_interval_seconds: {config.app.request_interval_seconds:g}",
            "",
            "# 重试次数：单篇文章失败后最多额外重试次数；0 表示不重试。",
            f"retry_count: {config.app.retry_count}",
            "",
            f"version: {_format_yaml_scalar(config.app.version)}",
            "",
            "# 系统代理：true 时，开启代理后自动接管系统代理；软件关闭时恢复原代理。",
            f"enable_system_proxy: {_format_bool(config.proxy.enable_system_proxy)}",
            "",
            "proxy:",
            f"  host: {_format_yaml_scalar(config.proxy.host)}",
            f"  port: {config.proxy.port}",
            f"  startup_delay_seconds: {config.proxy.startup_delay_seconds:g}",
            f"  verification_url: {_format_yaml_scalar(config.proxy.verification_url)}",
            f"  confdir: {_format_yaml_scalar(_format_config_path(config.proxy.confdir, config_dir))}",
            f"  ssl_insecure: {_format_bool(config.proxy.ssl_insecure)}",
            "",
            "storage:",
            f"  db_path: {_format_yaml_scalar(_format_config_path(config.storage.db_path, config_dir))}",
            "",
        ]
    )


def _resolve_config_path(value: Any, config_dir: Path) -> Path:
    """允许 custom.yaml 中的路径写绝对路径，也允许写相对 custom.yaml 的相对路径。"""
    path = Path(value)
    if path.is_absolute():
        return path
    return (config_dir / path).resolve()


def _format_config_path(path: Path, config_dir: Path | None) -> str:
    """项目配置写回时，尽量把配置目录附近的路径保存成可迁移的相对路径。"""
    if config_dir is None:
        return str(path)
    try:
        resolved_path = Path(path).resolve()
        resolved_config_dir = config_dir.resolve()
        config_scope = resolved_config_dir.parent
        if resolved_path.is_relative_to(config_scope):
            return os.path.relpath(resolved_path, resolved_config_dir).replace("\\", "/")
    except (OSError, ValueError):
        pass
    return str(path)


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _format_yaml_scalar(value: str) -> str:
    text = str(value)
    if not text:
        return "''"
    if any(char in text for char in (":", "\\", "#", " ", "\t")):
        return "'" + text.replace("'", "''") + "'"
    return text


def _read_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_section: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if not line.startswith(" ") and line.endswith(":"):
            section_name = line[:-1].strip()
            data[section_name] = {}
            current_section = data[section_name]
            continue

        key, sep, value = line.strip().partition(":")
        if not sep:
            continue

        target = current_section if raw_line.startswith(" ") and current_section is not None else data
        target[key.strip()] = _parse_scalar(value.strip())

    return data


def _parse_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value.strip("\"'")


def _get_alias(data: dict[str, Any], keys: tuple[str, ...], default: Any) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


def _get_bool_alias(data: dict[str, Any], keys: tuple[str, ...], default: bool) -> bool:
    return _coerce_bool(_get_alias(data, keys, default), default)


def _get_int_alias(data: dict[str, Any], keys: tuple[str, ...], default: int) -> int:
    try:
        return int(_get_alias(data, keys, default))
    except (TypeError, ValueError):
        return default


def _get_float_alias(data: dict[str, Any], keys: tuple[str, ...], default: float) -> float:
    try:
        return float(_get_alias(data, keys, default))
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _get_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    return _coerce_bool(data.get(key, default), default)


def _get_int(data: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_float(data: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default

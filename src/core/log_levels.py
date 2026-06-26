from __future__ import annotations


VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")

_LEVEL_WEIGHTS = {
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
}


def normalize_log_level(value: object, default: str = "INFO") -> str:
    """把配置里的日志等级统一成后端可识别的 DEBUG / INFO / WARN / ERROR。"""
    text = str(value or "").strip().upper()
    if text == "WARNING":
        text = "WARN"
    if text in VALID_LOG_LEVELS:
        return text
    return default if default in VALID_LOG_LEVELS else "INFO"


def should_emit_log(event_level: object, configured_level: object) -> bool:
    """判断一条运行日志是否达到当前配置的输出等级。"""
    normalized_config = normalize_log_level(configured_level)
    normalized_event = str(event_level or "INFO").strip().upper()
    event_weight = _LEVEL_WEIGHTS.get(normalized_event, _LEVEL_WEIGHTS["INFO"])
    config_weight = _LEVEL_WEIGHTS[normalized_config]
    return event_weight >= config_weight

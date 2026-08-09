"""文章采集业务编排。"""

from src.services.capture.capture_runtime_factory import CaptureRuntimeFactory
from src.services.capture.html_parse_save_service import (
    ArticleSaveData,
    HtmlParseSaveService,
)
from src.services.capture.window_runtime_factory import WindowRuntimeFactory

__all__ = [
    "ArticleSaveData",
    "CaptureRuntimeFactory",
    "HtmlParseSaveService",
    "WindowRuntimeFactory",
]

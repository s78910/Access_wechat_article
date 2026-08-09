from __future__ import annotations

from src.domain.enums import ErrorCode


class DomainError(Exception):
    """携带稳定错误码的业务异常。"""

    def __init__(self, error_code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code

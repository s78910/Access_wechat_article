from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Self, TypeVar

from src.domain.enums import ErrorCode, TaskStatus


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ToolResult(Generic[T]):
    status: TaskStatus
    data: T | None = None
    error_code: ErrorCode | None = None
    message: str = ""
    duration_seconds: float = 0

    @classmethod
    def success(cls, data: T | None = None, *, duration_seconds: float = 0) -> Self:
        return cls(status=TaskStatus.SUCCESS, data=data, duration_seconds=duration_seconds)

    @classmethod
    def failure(
        cls,
        error_code: ErrorCode,
        message: str,
        *,
        duration_seconds: float = 0,
    ) -> Self:
        return cls(
            status=TaskStatus.FAILED,
            error_code=error_code,
            message=message,
            duration_seconds=duration_seconds,
        )


@dataclass(frozen=True, slots=True)
class ServiceResult(ToolResult[T]):
    warnings: tuple[str, ...] = ()

    @classmethod
    def failure(
        cls,
        error_code: ErrorCode,
        message: str,
        *,
        warnings: tuple[str, ...] = (),
        duration_seconds: float = 0,
    ) -> Self:
        return cls(
            status=TaskStatus.FAILED,
            error_code=error_code,
            message=message,
            warnings=warnings,
            duration_seconds=duration_seconds,
        )


@dataclass(frozen=True, slots=True)
class TaskResult(ServiceResult[T]):
    """任务最终结果；完整过程事件由 TaskManager 单独保存。"""

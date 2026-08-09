from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class WindowInfo:
    handle: int
    title: str
    class_name: str
    process_name: str
    rect: tuple[int, int, int, int]
    visible: bool = True
    is_minimized: bool = False
    control: Any | None = field(default=None, repr=False, compare=False)

    @property
    def has_valid_rect(self) -> bool:
        left, top, right, bottom = self.rect
        return right > left and bottom > top


@dataclass(frozen=True, slots=True)
class BrowserTabInfo:
    tab_id: str
    owner_handle: int
    title: str
    rect: tuple[int, int, int, int]
    is_active: bool = False
    control: Any | None = field(default=None, repr=False, compare=False)

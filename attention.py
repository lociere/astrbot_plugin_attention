"""In-memory, bounded attention windows. No SDK, model, I/O or background tasks."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Scope:
    platform: str
    bot: str
    group: str
    user: str


@dataclass(frozen=True)
class Options:
    enabled: bool = True
    window_seconds: float = 90.0
    refresh_on_reply: bool = True
    allowed_groups: tuple[str, ...] = ()
    ignore_addressed_to_others: bool = True
    allow_media: bool = True
    max_sessions: int = 1000

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> Options:
        defaults = cls()
        values = {
            name: config.get(name, getattr(defaults, name)) for name in cls.__dataclass_fields__
        }
        for name in ("enabled", "refresh_on_reply", "ignore_addressed_to_others", "allow_media"):
            if not isinstance(values[name], bool):
                raise ValueError(f"{name} 必须是布尔值")
        seconds = values["window_seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("window_seconds 必须是 1—3600 秒之间的数值")
        if not math.isfinite(seconds) or not 1 <= seconds <= 3600:
            raise ValueError("window_seconds 必须是 1—3600 秒之间的数值")
        values["window_seconds"] = float(seconds)
        limit = values["max_sessions"]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError("max_sessions 必须是 1—10000 之间的整数")
        groups = values["allowed_groups"]
        if not isinstance(groups, (list, tuple)) or any(
            not isinstance(group, str) or not group.strip() for group in groups
        ):
            raise ValueError("allowed_groups 必须是非空字符串组成的列表，空列表表示不额外限制")
        values["allowed_groups"] = tuple(dict.fromkeys(group.strip() for group in groups))
        return cls(**values)


@dataclass(frozen=True)
class Window:
    lease: int
    expires_at: float


class AttentionWindow:
    def __init__(
        self,
        seconds: float,
        max_sessions: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.seconds = seconds
        self.max_sessions = max_sessions
        self.clock = clock
        self._windows: OrderedDict[Scope, Window] = OrderedDict()
        self._sequence = 0

    def _purge(self, now: float) -> None:
        # All entries have the same lifetime; opening / refreshing moves to end.
        while self._windows:
            oldest = next(iter(self._windows))
            if self._windows[oldest].expires_at > now:
                break
            self._windows.popitem(last=False)

    def open(self, scope: Scope) -> int:
        now = self.clock()
        self._purge(now)
        self._sequence += 1
        self._windows[scope] = Window(self._sequence, now + self.seconds)
        self._windows.move_to_end(scope)
        while len(self._windows) > self.max_sessions:
            self._windows.popitem(last=False)
        return self._sequence

    def get(self, scope: Scope) -> int | None:
        self._purge(self.clock())
        window = self._windows.get(scope)
        return window.lease if window else None

    def refresh(self, scope: Scope, lease: int) -> bool:
        now = self.clock()
        self._purge(now)
        window = self._windows.get(scope)
        if window is None or window.lease != lease:
            return False
        self._windows[scope] = Window(lease, now + self.seconds)
        self._windows.move_to_end(scope)
        return True

    def clear(self) -> None:
        self._windows.clear()

"""apa-sdk: 事件防抖（设计文档 §6.3）。

防止高频 UI 变化产生事件风暴淹没 Decision Engine。

异步版本（EventCoalescer）：asyncio 执行器使用。
同步版本（SyncCoalescer）：POC 的同步执行器使用（last-write-wins 时间窗）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Dict


class EventCoalescer:
    """同名事件在 debounce 窗口内只发一次（§6.3）。"""

    def __init__(self, debounce_ms: int = 500) -> None:
        self._pending: Dict[str, asyncio.TimerHandle] = {}
        self._debounce_ms = debounce_ms

    async def submit(self, event_name: str, event_fn: Callable) -> None:
        handle = self._pending.get(event_name)
        if handle is not None:
            handle.cancel()
        loop = asyncio.get_event_loop()
        handle = loop.call_later(
            self._debounce_ms / 1000,
            lambda: asyncio.create_task(event_fn()),
        )
        self._pending[event_name] = handle

    def flush(self) -> None:
        for handle in self._pending.values():
            handle.cancel()
        self._pending.clear()


class SyncCoalescer:
    """同步版本：窗口内同名事件只保留最后一次，轮询 flush 时统一发射。

    emit(name, data) 记录最新值；flush() 返回窗口期内需要发射的事件。
    """

    def __init__(self, debounce_ms: int = 500) -> None:
        self._debounce_ms = debounce_ms
        self._last_emit: Dict[str, float] = {}
        self._pending: Dict[str, dict] = {}
        self.suppressed = 0

    def emit(self, event_name: str, data: dict) -> None:
        now = time.monotonic() * 1000
        last = self._last_emit.get(event_name)
        if last is not None and now - last < self._debounce_ms:
            self._pending[event_name] = data  # 覆盖，稍后发射最新值
            self.suppressed += 1
            return
        self._last_emit[event_name] = now
        self._pending[event_name] = data

    def flush(self) -> list:
        out = []
        for name, data in self._pending.items():
            out.append((name, data))
            self._last_emit[name] = time.monotonic() * 1000
        self._pending.clear()
        return out
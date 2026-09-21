from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._subscribers[event_name].append(handler)

    def emit(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        for handler in self._subscribers.get(event_name, []):
            try:
                handler(payload)
            except Exception:
                continue

    async def emit_async(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        for handler in self._subscribers.get(event_name, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception:
                continue

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., Any]
    schema: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, description: str, fn: Callable[..., Any], schema: dict[str, Any] | None = None) -> None:
        self._tools[name] = ToolSpec(name=name, description=description, fn=fn, schema=schema or {})

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f'Tool {name} not found')
        return self._tools[name]

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def execute(self, name: str, **kwargs: Any) -> Any:
        tool = self.get(name)
        return tool.fn(**kwargs)

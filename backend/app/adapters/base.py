from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolAdapter:
    name: str
    description: str
    action: Callable[..., Any]

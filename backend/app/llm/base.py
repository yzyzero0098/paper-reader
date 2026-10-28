"""Provider-agnostic chat interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class Msg:
    role: str                       # "user" | "assistant"
    content: str
    images: list[tuple[bytes, str]] = field(default_factory=list)   # (bytes, mime)


class Provider:
    name: str = "base"
    supports_vision: bool = False

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.last_usage: dict | None = None     # {"input": n, "output": n} after a call

    async def stream(self, system: str, messages: list[Msg], max_tokens: int = 8000,
                     effort: str = "medium") -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover

    async def complete(self, system: str, messages: list[Msg], max_tokens: int = 8000,
                       effort: str = "medium") -> str:
        parts = []
        async for t in self.stream(system, messages, max_tokens=max_tokens, effort=effort):
            parts.append(t)
        return "".join(parts)

    async def list_models(self) -> list[str]:
        return []

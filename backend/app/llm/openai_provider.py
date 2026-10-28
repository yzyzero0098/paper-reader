"""OpenAI and OpenAI-compatible endpoints (DeepSeek, Ollama, OpenRouter, ...)."""
from __future__ import annotations

import base64
from typing import AsyncIterator

from openai import AsyncOpenAI

from .base import Msg, Provider


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str = "", vision: bool = True, name: str = "openai"):
        super().__init__(api_key, model, base_url)
        self.name = name
        self.supports_vision = vision
        self.client = AsyncOpenAI(api_key=api_key or "sk-no-key", base_url=base_url or None)

    def _convert(self, system: str, messages: list[Msg]) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.images and m.role == "user" and self.supports_vision:
                content = [{"type": "text", "text": m.content}]
                for data, mime in m.images:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{base64.standard_b64encode(data).decode()}"},
                    })
                out.append({"role": "user", "content": content})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    async def stream(self, system: str, messages: list[Msg], max_tokens: int = 8000,
                     effort: str = "medium") -> AsyncIterator[str]:
        self.last_usage = None
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=self._convert(system, messages),
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in resp:
            u = getattr(chunk, "usage", None)
            if u is not None:
                self.last_usage = {"input": getattr(u, "prompt_tokens", 0) or 0, "output": getattr(u, "completion_tokens", 0) or 0}
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def list_models(self) -> list[str]:
        ids = []
        async for m in self.client.models.list():
            ids.append(m.id)
        return sorted(ids)

"""Claude via the official anthropic SDK (streaming, vision, refusal fallbacks)."""
from __future__ import annotations

import base64
from typing import AsyncIterator

import anthropic

from .base import Msg, Provider


class AnthropicProvider(Provider):
    name = "anthropic"
    supports_vision = True

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        super().__init__(api_key, model, base_url)
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.AsyncAnthropic(**kwargs)

    @staticmethod
    def _convert(messages: list[Msg]) -> list[dict]:
        out = []
        for m in messages:
            if m.images and m.role == "user":
                content = []
                for data, mime in m.images:
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime,
                                   "data": base64.standard_b64encode(data).decode()},
                    })
                content.append({"type": "text", "text": m.content})
                out.append({"role": m.role, "content": content})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    async def stream(self, system: str, messages: list[Msg], max_tokens: int = 8000,
                     effort: str = "medium") -> AsyncIterator[str]:
        params = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=self._convert(messages),
            output_config={"effort": effort},
        )
        if system:
            params["system"] = system
        self.last_usage = None
        try:
            # Server-side refusal fallbacks (routes a safety refusal to another model).
            async with self.client.beta.messages.stream(
                **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            ) as s:
                async for text in s.text_stream:
                    yield text
                self._usage(await s.get_final_message())
            return
        except (TypeError, anthropic.BadRequestError):
            pass   # SDK/model without fallback support → plain request below
        async with self.client.messages.stream(**params) as s:
            async for text in s.text_stream:
                yield text
            self._usage(await s.get_final_message())

    def _usage(self, msg) -> None:
        u = getattr(msg, "usage", None)
        if u is not None:
            self.last_usage = {"input": getattr(u, "input_tokens", 0) or 0, "output": getattr(u, "output_tokens", 0) or 0}

    async def list_models(self) -> list[str]:
        ids = []
        async for m in self.client.models.list():
            ids.append(m.id)
        return ids

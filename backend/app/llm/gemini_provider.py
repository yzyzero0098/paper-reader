"""Google Gemini via the google-genai SDK."""
from __future__ import annotations

from typing import AsyncIterator

from google import genai
from google.genai import types

from .base import Msg, Provider


class GeminiProvider(Provider):
    name = "gemini"
    supports_vision = True

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        super().__init__(api_key, model, base_url)
        self.client = genai.Client(api_key=api_key)

    @staticmethod
    def _convert(messages: list[Msg]) -> list[types.Content]:
        out = []
        for m in messages:
            parts = [types.Part.from_text(text=m.content)]
            for data, mime in m.images:
                parts.insert(0, types.Part.from_bytes(data=data, mime_type=mime))
            out.append(types.Content(role="user" if m.role == "user" else "model", parts=parts))
        return out

    async def stream(self, system: str, messages: list[Msg], max_tokens: int = 8000,
                     effort: str = "medium") -> AsyncIterator[str]:
        config = types.GenerateContentConfig(system_instruction=system or None, max_output_tokens=max_tokens)
        resp = await self.client.aio.models.generate_content_stream(
            model=self.model, contents=self._convert(messages), config=config
        )
        self.last_usage = None
        async for chunk in resp:
            if chunk.text:
                yield chunk.text
            um = getattr(chunk, "usage_metadata", None)
            if um is not None:
                self.last_usage = {"input": getattr(um, "prompt_token_count", 0) or 0,
                                   "output": getattr(um, "candidates_token_count", 0) or 0}

    async def list_models(self) -> list[str]:
        ids = []
        async for m in await self.client.aio.models.list():
            name = (m.name or "").replace("models/", "")
            actions = getattr(m, "supported_actions", None) or []
            if name.startswith("gemini") and (not actions or "generateContent" in actions):
                ids.append(name)
        return sorted(ids)

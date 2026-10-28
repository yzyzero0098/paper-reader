"""ChatGPT plan usage: Responses API with the user's Sign-in-with-ChatGPT access token."""
from __future__ import annotations

import asyncio
import base64
from typing import AsyncIterator

import openai
from openai import AsyncOpenAI

from .. import chatgpt_auth
from .base import Msg, Provider

USAGE_URL = "https://chatgpt.com/settings/usage"


class ChatGPTPlanError(Exception):
    pass


def _friendly(code: str, message: str, status: int | None) -> str:
    if code == "subscription_sharing_usage_limit_exceeded" or status == 429:
        try:
            import time

            from .. import db
            db.cache_set("chatgpt:limit_hit", time.time())     # shown in the usage panel
        except Exception:
            pass
        return f"ChatGPT 플랜 사용 한도에 도달했습니다. 사용량 설정에서 확인하세요: {USAGE_URL}"
    if code == "subscription_sharing_user_not_eligible":
        return "이 ChatGPT 계정/워크스페이스는 외부 앱에서 플랜 사용이 허용되지 않습니다."
    if code in ("subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable") or status == 503:
        return "ChatGPT 사용량 확인이 일시적으로 불가합니다. 잠시 후 다시 시도하세요."
    if code == "subscription_sharing_invalid_user" or status == 401:
        return "ChatGPT 세션이 유효하지 않습니다. 설정에서 다시 로그인하세요."
    if code in ("chatpass_v2_scope_not_authorized", "chatpass_v2_invalid_authorization_context"):
        return "ChatGPT 플랜 사용 권한이 없습니다. 설정에서 다시 로그인하고 권한에 동의하세요."
    return f"ChatGPT 요청 실패: {code or status}: {message}"


class ChatGPTProvider(Provider):
    name = "chatgpt"
    supports_vision = True

    def __init__(self, model: str):
        super().__init__("", model, chatgpt_auth.RESOURCE)

    def _client(self, token: str) -> AsyncOpenAI:
        return AsyncOpenAI(api_key=token, base_url=chatgpt_auth.RESOURCE, max_retries=0)

    @staticmethod
    def _convert(messages: list[Msg]) -> list[dict]:
        items: list[dict] = []
        for m in messages:
            if m.role == "user":
                content: list[dict] = [{"type": "input_text", "text": m.content}]
                for data, mime in m.images:
                    content.append({"type": "input_image",
                                    "image_url": f"data:{mime};base64,{base64.standard_b64encode(data).decode()}"})
                items.append({"role": "user", "content": content})
            else:
                items.append({"role": "assistant", "content": [{"type": "output_text", "text": m.content}]})
        return items

    async def stream(self, system: str, messages: list[Msg], max_tokens: int = 8000,
                     effort: str = "medium") -> AsyncIterator[str]:
        token = await asyncio.to_thread(chatgpt_auth.get_access_token)
        self.last_usage = None
        for attempt in (0, 1):
            try:
                async for t in self._stream_once(token, system, messages, effort):
                    yield t
                return
            except openai.AuthenticationError as e:
                if attempt == 1:
                    raise ChatGPTPlanError(_friendly(_code(e), str(e), 401))
                token = await asyncio.to_thread(chatgpt_auth.get_access_token, True)
            except openai.APIStatusError as e:
                raise ChatGPTPlanError(_friendly(_code(e), _msg(e), e.status_code))
            except chatgpt_auth.AuthError as e:
                raise ChatGPTPlanError(str(e))

    async def _stream_once(self, token: str, system: str, messages: list[Msg], effort: str = "medium") -> AsyncIterator[str]:
        client = self._client(token)
        kwargs = dict(model=self.model, input=self._convert(messages), store=False, stream=True)
        if system:
            kwargs["instructions"] = system
        if effort in ("low", "medium", "high"):
            kwargs["reasoning"] = {"effort": effort}
        try:
            stream = await client.responses.create(**kwargs)
        except openai.BadRequestError as e:
            if "reasoning" not in str(e):
                raise
            kwargs.pop("reasoning", None)          # model without reasoning control
            stream = await client.responses.create(**kwargs)
        async for event in stream:
            et = getattr(event, "type", "")
            if et == "response.output_text.delta":
                yield event.delta
            elif et == "response.completed":
                u = getattr(getattr(event, "response", None), "usage", None)
                if u is not None:
                    self.last_usage = {"input": getattr(u, "input_tokens", 0) or 0, "output": getattr(u, "output_tokens", 0) or 0}
            elif et == "response.failed":
                err = getattr(getattr(event, "response", None), "error", None)
                code = getattr(err, "code", "") or ""
                msg = getattr(err, "message", "") or ""
                raise ChatGPTPlanError(_friendly(code, msg, None))
            elif et == "error":
                raise ChatGPTPlanError(_friendly(getattr(event, "code", "") or "", getattr(event, "message", "") or "", None))

    async def list_models(self) -> list[str]:
        token = await asyncio.to_thread(chatgpt_auth.get_access_token)
        models = await asyncio.to_thread(chatgpt_auth.list_models_sync, token)
        return [m["slug"] for m in models]


def _code(e: openai.APIStatusError) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return str(err.get("code") or err.get("type") or "")
    return ""


def _msg(e: openai.APIStatusError) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(e)

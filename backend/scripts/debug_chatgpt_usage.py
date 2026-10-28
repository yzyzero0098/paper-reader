"""Dev tool: show response headers and the response.metadata event of a tiny ChatGPT-plan request.

Prints header names (values only for usage/limit-looking headers) so we can see whether the server reports
plan usage. Usage: python -X utf8 backend/scripts/debug_chatgpt_usage.py
"""
import asyncio
import json
import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app import chatgpt_auth  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.llm.base import Msg  # noqa: E402
from app.llm.chatgpt_provider import ChatGPTProvider  # noqa: E402

INTERESTING = re.compile(r"limit|usage|quota|percent|reset|window|plan|codex|credit|remaining", re.I)


async def main():
    model = load_settings()["providers"]["chatgpt"]["model"]
    p = ChatGPTProvider(model)
    client = p._client(chatgpt_auth.get_access_token())
    stream = await client.responses.create(
        model=model, input=p._convert([Msg("user", "Reply with: OK")]), store=False, stream=True,
    )
    headers = stream.response.headers
    print("header names:", sorted(headers.keys()))
    for k, v in headers.items():
        if INTERESTING.search(k):
            print("  ", k, "=", v)
    async for ev in stream:
        if getattr(ev, "type", "") == "response.metadata":
            d = ev.model_dump() if hasattr(ev, "model_dump") else ev.__dict__
            print("response.metadata:", json.dumps(d, ensure_ascii=False, default=str)[:3000])
        if getattr(ev, "type", "") == "response.completed":
            u = getattr(ev.response, "usage", None)
            print("usage:", u)


asyncio.run(main())

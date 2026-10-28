"""Dev tool: print raw Responses API stream event types for the ChatGPT-plan provider.

Usage: python -X utf8 backend/scripts/debug_chatgpt_events.py [paper_id]
"""
import asyncio
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app import chatgpt_auth, pdf_engine, services  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.llm.chatgpt_provider import ChatGPTProvider  # noqa: E402
from app.llm.base import Msg  # noqa: E402


async def main():
    model = load_settings()["providers"]["chatgpt"]["model"]
    token = chatgpt_auth.get_access_token()
    p = ChatGPTProvider(model)
    client = p._client(token)
    system = "You are a helpful assistant. Reply in Korean."
    if len(sys.argv) > 1:
        text = pdf_engine.full_text(services.doc_for(sys.argv[1]), max_chars=150_000)
        system = services.CHAT_SYSTEM.format(lang="Korean", title="test", text=text)
    print("system chars:", len(system), "model:", model)
    stream = await client.responses.create(
        model=model,
        input=p._convert([Msg("user", "이 논문에서 FAIMS를 썼나요? 한 문장으로.")]),
        instructions=system,
        store=False,
        stream=True,
    )
    counts: dict[str, int] = {}
    text_out = ""
    async for ev in stream:
        t = getattr(ev, "type", "?")
        counts[t] = counts.get(t, 0) + 1
        if t == "response.output_text.delta":
            text_out += ev.delta
        if t in ("response.failed", "error", "response.incomplete"):
            print("EVENT", t, getattr(ev, "response", None) or ev)
    print("events:", counts)
    print("text:", text_out[:300])


asyncio.run(main())

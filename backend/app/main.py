"""FastAPI entry point: REST + SSE endpoints and static serving of the built frontend."""
from __future__ import annotations

import json
import traceback
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chatgpt_auth, db, services
from .config import FRONTEND_DIST, PROVIDERS, load_settings, public_settings, save_settings
from .llm import ProviderError, get_provider
from .llm.chatgpt_provider import ChatGPTPlanError

app = FastAPI(title="Paper Reader", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- helpers
def _404(pid: str) -> dict:
    p = db.get_paper(pid)
    if not p:
        raise HTTPException(404, "논문을 찾을 수 없습니다.")
    return p


def _lang(req: Request, override: str | None = None) -> str:
    return override or req.query_params.get("lang") or services.default_lang()


def sse(gen: AsyncIterator[str]) -> StreamingResponse:
    async def events():
        try:
            async for chunk in gen:
                yield f"data: {json.dumps({'t': chunk}, ensure_ascii=False)}\n\n"
            yield "data: {\"done\": true}\n\n"
        except (ProviderError, ChatGPTPlanError, chatgpt_auth.AuthError, services.NotFound, ValueError) as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:  # surface provider errors to the UI
            traceback.print_exc()
            yield f"data: {json.dumps({'error': f'{type(e).__name__}: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.exception_handler(ProviderError)
async def _provider_error(_: Request, exc: ProviderError):
    return Response(json.dumps({"detail": str(exc)}, ensure_ascii=False), status_code=400, media_type="application/json")


@app.exception_handler(ChatGPTPlanError)
@app.exception_handler(chatgpt_auth.AuthError)
async def _chatgpt_error(_: Request, exc: Exception):
    return Response(json.dumps({"detail": str(exc)}, ensure_ascii=False), status_code=400, media_type="application/json")


# ---------------------------------------------------------------- Sign in with ChatGPT
@app.post("/api/auth/chatgpt/start")
async def chatgpt_start():
    return chatgpt_auth.start_login()


@app.get("/api/auth/chatgpt/status")
async def chatgpt_status():
    return chatgpt_auth.status()


@app.post("/api/auth/chatgpt/logout")
async def chatgpt_logout():
    chatgpt_auth.logout()
    return {"ok": True}


@app.exception_handler(services.NotFound)
async def _not_found(_: Request, exc: services.NotFound):
    return Response(json.dumps({"detail": f"찾을 수 없음: {exc}"}, ensure_ascii=False), status_code=404, media_type="application/json")


# ---------------------------------------------------------------- settings
class ProviderPatch(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class SettingsPatch(BaseModel):
    target_lang: str | None = None
    default_provider: str | None = None
    vision_provider: str | None = None
    usage_budget_5h: int | None = None
    usage_budget_7d: int | None = None
    providers: dict[str, ProviderPatch] | None = None


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/settings")
async def get_settings():
    return public_settings()


@app.put("/api/settings")
async def put_settings(patch: SettingsPatch):
    s = load_settings()
    if patch.target_lang:
        s["target_lang"] = patch.target_lang
    if patch.default_provider in PROVIDERS:
        s["default_provider"] = patch.default_provider
    if patch.vision_provider is not None:
        s["vision_provider"] = patch.vision_provider if patch.vision_provider in PROVIDERS else ""
    for k in ("usage_budget_5h", "usage_budget_7d"):
        v = getattr(patch, k)
        if v is not None:
            s[k] = max(0, int(v))
    for name, p in (patch.providers or {}).items():
        if name not in PROVIDERS:
            continue
        cfg = s["providers"][name]
        if p.api_key is not None:
            cfg["api_key"] = p.api_key.strip()
        if p.model is not None:
            cfg["model"] = p.model.strip()
        if p.base_url is not None:
            cfg["base_url"] = p.base_url.strip()
    save_settings(s)
    return public_settings()


@app.get("/api/settings/models")
async def list_models(provider: str):
    try:
        return {"models": await get_provider(provider).list_models()}
    except ProviderError:
        raise
    except Exception as e:
        raise HTTPException(400, f"모델 목록을 가져오지 못했습니다: {type(e).__name__}: {e}")


@app.post("/api/settings/test")
async def test_provider(body: dict):
    name = body.get("provider", "")
    try:
        reply = await services.test_provider(name)
        return {"ok": True, "reply": reply}
    except ProviderError:
        raise
    except Exception as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- papers
@app.get("/api/papers")
async def list_papers():
    return db.list_papers()


@app.post("/api/papers")
async def upload_paper(file: UploadFile = File(...), folder_id: int | None = Form(None)):
    data = await file.read()
    try:
        return services.add_paper(data, file.filename or "paper.pdf", folder_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/papers/{pid}")
async def get_paper(pid: str):
    return _404(pid)


class PaperPatch(BaseModel):
    title: str | None = None
    folder_id: int | None = None        # send null to move a paper out of its folder


@app.patch("/api/papers/{pid}")
async def patch_paper(pid: str, body: PaperPatch):
    _404(pid)
    if body.title is not None:
        db.update_paper_title(pid, body.title.strip()[:400])
        services._context.pop(pid, None)
    if "folder_id" in body.model_fields_set:
        if body.folder_id is not None and not any(f["id"] == body.folder_id for f in db.list_folders()):
            raise HTTPException(404, "폴더를 찾을 수 없습니다.")
        db.set_paper_folder(pid, body.folder_id)
    return db.get_paper(pid)


# ---------------------------------------------------------------- folders
class FolderIn(BaseModel):
    name: str | None = None
    color: str | None = None


@app.get("/api/folders")
async def list_folders():
    return db.list_folders()


@app.post("/api/folders")
async def create_folder(body: FolderIn):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "폴더 이름을 입력하세요.")
    return {"id": db.add_folder(name[:80], body.color)}


@app.patch("/api/folders/{fid}")
async def patch_folder(fid: int, body: FolderIn):
    name = body.name.strip()[:80] if body.name is not None else None
    if name == "":
        raise HTTPException(400, "폴더 이름을 입력하세요.")
    db.update_folder(fid, name, body.color)
    return {"ok": True}


@app.delete("/api/folders/{fid}")
async def remove_folder(fid: int):
    db.delete_folder(fid)          # papers move back to "unfiled"; none are deleted
    return {"ok": True}


# ---------------------------------------------------------------- reading log
class HeartbeatIn(BaseModel):
    day: str                         # client-local date, YYYY-MM-DD
    seconds: int = 0
    page: int | None = None


@app.post("/api/papers/{pid}/reading")
async def reading_heartbeat(pid: str, body: HeartbeatIn):
    _404(pid)
    import re as _re
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.day):
        raise HTTPException(400, "day 형식은 YYYY-MM-DD 입니다.")
    db.log_reading(pid, body.day, min(max(body.seconds, 0), 300), body.page)
    return {"ok": True}


@app.get("/api/reading/calendar")
async def reading_calendar(month: str):
    import re as _re
    if not _re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, "month 형식은 YYYY-MM 입니다.")
    return db.reading_calendar(month)


@app.delete("/api/papers/{pid}")
async def delete_paper(pid: str):
    _404(pid)
    services.delete_paper(pid)
    return {"ok": True}


@app.get("/api/papers/{pid}/file")
async def paper_file(pid: str):
    _404(pid)
    return FileResponse(services.paper_path(pid), media_type="application/pdf")


@app.get("/api/papers/{pid}/pages/{pno}/layout")
async def page_layout(pid: str, pno: int):
    _404(pid)
    return services.layout(pid, pno)


@app.get("/api/usage")
async def usage(paper_id: str | None = None):
    return db.usage_summary(paper_id)


@app.get("/api/papers/{pid}/pages/{pno}/translate")
async def page_translate(pid: str, pno: int, request: Request, lang: str | None = None,
                         provider: str | None = None, force: bool = False, model: str | None = None):
    _404(pid)
    try:
        return await services.translate_page(pid, pno, _lang(request, lang), provider, force, model)
    except ProviderError:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(502, f"번역 실패: {type(e).__name__}: {e}")


class TextIn(BaseModel):
    text: str
    lang: str | None = None
    provider: str | None = None
    model: str | None = None


@app.post("/api/papers/{pid}/translate-text")
async def translate_text(pid: str, body: TextIn, request: Request):
    _404(pid)
    return {"t": await services.translate_text(pid, body.text, _lang(request, body.lang), body.provider, body.model)}


@app.get("/api/papers/{pid}/figures/{fid}/image")
async def figure_image(pid: str, fid: str, caption: int = 1, zoom: float = 2.0):
    _404(pid)
    png = services.figure_image(pid, fid, with_caption=bool(caption), zoom=min(max(zoom, 1.0), 4.0))
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/papers/{pid}/references")
async def references(pid: str):
    _404(pid)
    return services.get_references(pid)


@app.get("/api/papers/{pid}/references/{n}/lookup")
async def reference_lookup(pid: str, n: int, force: bool = False):
    _404(pid)
    return await services.lookup_reference(pid, n, force)


class CitationIn(BaseModel):
    text: str
    style: str = "numeric"
    refs: list[int] = []
    authors: str = ""


@app.post("/api/papers/{pid}/citations/resolve")
async def resolve_citation(pid: str, body: CitationIn):
    _404(pid)
    return services.resolve_citation(pid, body.text, body.style, body.refs, body.authors)


# ---------------------------------------------------------------- AI (SSE)
class ExplainIn(BaseModel):
    kind: str = "text"             # text | equation | term | figure | table | citation
    page: int = 0
    text: str = ""
    figure_id: str = ""
    refs: list[dict] = []
    question: str = ""
    lang: str | None = None
    provider: str | None = None
    model: str | None = None
    effort: str = "medium"


@app.post("/api/papers/{pid}/explain")
async def explain(pid: str, body: ExplainIn, request: Request):
    _404(pid)
    return sse(services.explain_stream(pid, body.kind, body.model_dump(), _lang(request, body.lang),
                                       body.provider, body.model, body.effort))


@app.get("/api/papers/{pid}/summary")
async def get_summary(pid: str, request: Request, lang: str | None = None):
    _404(pid)
    s = services.get_summary(pid, _lang(request, lang))
    return {"summary": s}


class GenIn(BaseModel):
    lang: str | None = None
    provider: str | None = None
    model: str | None = None
    effort: str = "medium"
    force: bool = False


@app.post("/api/papers/{pid}/summary")
async def gen_summary(pid: str, body: GenIn, request: Request):
    _404(pid)
    return sse(services.summary_stream(pid, _lang(request, body.lang), body.provider, body.model, body.effort))


class ChatIn(BaseModel):
    messages: list[dict]
    lang: str | None = None
    provider: str | None = None
    model: str | None = None
    effort: str = "medium"


@app.get("/api/papers/{pid}/chat")
async def get_chat(pid: str):
    _404(pid)
    return {"messages": db.get_chat(pid)}


@app.put("/api/papers/{pid}/chat")
async def put_chat(pid: str, body: ChatIn):
    _404(pid)
    db.save_chat(pid, body.messages[-200:])
    return {"ok": True}


@app.post("/api/papers/{pid}/chat")
async def chat(pid: str, body: ChatIn, request: Request):
    _404(pid)
    return sse(services.chat_stream(pid, body.messages, _lang(request, body.lang), body.provider, body.model, body.effort))


# ---------------------------------------------------------------- highlights
class HighlightIn(BaseModel):
    page: int
    rects: list[list[float]]
    color: str = "yellow"
    text: str = ""
    note: str = ""


class HighlightPatch(BaseModel):
    note: str | None = None
    color: str | None = None


@app.get("/api/papers/{pid}/highlights")
async def list_highlights(pid: str):
    _404(pid)
    return db.list_highlights(pid)


@app.post("/api/papers/{pid}/highlights")
async def add_highlight(pid: str, body: HighlightIn):
    _404(pid)
    hid = db.add_highlight(pid, body.page, body.rects, body.color, body.text, body.note)
    return {"id": hid}


@app.patch("/api/papers/{pid}/highlights/{hid}")
async def patch_highlight(pid: str, hid: int, body: HighlightPatch):
    _404(pid)
    db.update_highlight(hid, body.note, body.color)
    return {"ok": True}


@app.delete("/api/papers/{pid}/highlights/{hid}")
async def delete_highlight(pid: str, hid: int):
    _404(pid)
    db.delete_highlight(hid)
    return {"ok": True}


# ---------------------------------------------------------------- frontend
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        target = FRONTEND_DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")

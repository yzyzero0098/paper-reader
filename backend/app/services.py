"""AI services on top of the PDF engine: translation, explanation, summary, chat, citations."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import AsyncIterator

import fitz

from . import citations as cit
from . import db, paragraphs, pdf_engine
from .config import LANG_NAMES, PAPERS_DIR, load_settings
from .llm import Msg, resolve_provider

LAYOUT_VERSION = 11    # bump when layout extraction changes (invalidates cached layouts and translations)
_refs_start: dict[str, tuple[int, float] | None] = {}
_context: dict[str, dict] = {}


class NotFound(Exception):
    pass


# ---------------------------------------------------------------- papers
def paper_path(pid: str) -> Path:
    p = PAPERS_DIR / f"{pid}.pdf"
    if not p.exists():
        raise NotFound(pid)
    return p


def doc_for(pid: str) -> fitz.Document:
    return pdf_engine.open_doc(paper_path(pid))


def add_paper(data: bytes, filename: str, folder_id: int | None = None) -> dict:
    if not data.startswith(b"%PDF"):
        raise ValueError("PDF 파일이 아닙니다.")
    pid = uuid.uuid4().hex[:12]
    path = PAPERS_DIR / f"{pid}.pdf"
    path.write_bytes(data)
    doc = pdf_engine.open_doc(path)
    title = pdf_engine.extract_title(doc)
    meta = {k: v for k, v in (doc.metadata or {}).items() if v and k in ("author", "subject", "keywords", "creationDate")}
    db.add_paper(pid, title, filename, doc.page_count, meta)
    if folder_id is not None:
        db.set_paper_folder(pid, folder_id)
    return db.get_paper(pid)


def delete_paper(pid: str) -> None:
    path = PAPERS_DIR / f"{pid}.pdf"
    pdf_engine.close_doc(path)
    if path.exists():
        path.unlink()
    db.delete_paper(pid)
    _refs_start.pop(pid, None)
    _context.pop(pid, None)


def refs_start(pid: str):
    if pid not in _refs_start:
        _refs_start[pid] = pdf_engine.find_references_start(doc_for(pid))
    return _refs_start[pid]


def layout(pid: str, pno: int) -> dict:
    key = f"layout{LAYOUT_VERSION}:{pid}:{pno}"
    cached = db.cache_get(key)
    if cached:
        return cached
    doc = doc_for(pid)
    if pno < 0 or pno >= doc.page_count:
        raise NotFound(f"page {pno}")
    lay = pdf_engine.page_layout(doc, pno, refs_start(pid), ref_count=len(get_references(pid)))
    db.cache_set(key, lay)
    return lay


def paper_context(pid: str) -> dict:
    if pid not in _context:
        paper = db.get_paper(pid) or {}
        doc = doc_for(pid)
        head = ""
        for i in range(min(2, doc.page_count)):
            head += doc[i].get_text("text", sort=True)
        _context[pid] = {
            "title": paper.get("title") or "",
            "head": re.sub(r"[ \t]+", " ", head)[:3500],
        }
    return _context[pid]


def page_text(pid: str, pno: int, limit: int = 4000) -> str:
    doc = doc_for(pid)
    if 0 <= pno < doc.page_count:
        return doc[pno].get_text("text", sort=True)[:limit]
    return ""


# ---------------------------------------------------------------- references
def get_references(pid: str) -> list[dict]:
    key = f"refs{LAYOUT_VERSION}:{pid}"
    cached = db.cache_get(key)
    if cached is not None:
        return cached
    refs = cit.parse_references(pdf_engine.page_texts(doc_for(pid)))
    db.cache_set(key, refs)
    return refs


def find_reference(pid: str, n: int) -> dict | None:
    return next((r for r in get_references(pid) if r["n"] == n), None)


async def lookup_reference(pid: str, n: int, force: bool = False) -> dict:
    ref = find_reference(pid, n)
    if not ref:
        raise NotFound(f"reference {n}")
    key = f"reflookup:{pid}:{n}"
    cached = None if force else db.cache_get(key)
    if cached is not None:
        return {**ref, "meta": cached}
    meta = await cit.lookup_crossref(ref["raw"], ref.get("doi", ""))
    db.cache_set(key, meta or {})
    return {**ref, "meta": meta or {}}


def resolve_citation(pid: str, text: str, style: str, refs: list[int], authors: str = "") -> list[dict]:
    """Return the reference entries that an in-text citation points to."""
    all_refs = get_references(pid)
    if style == "author-year" and authors:
        nums = cit.match_author_year(all_refs, authors)
    else:
        nums = refs
    return [r for r in all_refs if r["n"] in nums]


# ---------------------------------------------------------------- helpers
def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


def _record(pid: str, provider, kind: str) -> None:
    """Persist the token usage of the call that just finished."""
    u = getattr(provider, "last_usage", None)
    if u and (u.get("input") or u.get("output")):
        db.add_usage(pid, provider.name, provider.model, kind, u.get("input", 0), u.get("output", 0))
        provider.last_usage = None


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1:
        raise ValueError("모델 응답에서 JSON을 찾지 못했습니다.")
    return json.loads(text[a:b + 1])


def _figure(pid: str, fid: str) -> tuple[int, dict]:
    m = re.match(r"^[ft](\d+)-\d+$", fid)
    if not m:
        raise NotFound(fid)
    pno = int(m.group(1))
    lay = layout(pid, pno)
    fig = next((f for f in lay["figures"] if f["id"] == fid), None)
    if not fig:
        raise NotFound(fid)
    return pno, fig


def figure_image(pid: str, fid: str, with_caption: bool = True, zoom: float = 2.0) -> bytes:
    pno, fig = _figure(pid, fid)
    bbox = fitz.Rect(fig["bbox"])
    if with_caption and fig.get("caption_bbox"):
        bbox = bbox | fitz.Rect(fig["caption_bbox"])
    return pdf_engine.figure_png(doc_for(pid), pno, list(bbox), zoom=zoom)


# ---------------------------------------------------------------- translation
TRANSLATE_SYSTEM = """You are a professional academic translator. Translate sentences of a research paper into {lang}.
The input is a list of items; each item is one sentence (or a heading/caption). Items whose ids share the same prefix before the last dot are consecutive sentences of the same paragraph, in order. Translate them so that they read naturally in sequence, but return exactly one translation per item (do not merge or split items).
Rules:
- Preserve meaning precisely; use the standard technical terminology of the field. Keep gene/protein names, abbreviations, units, numbers, variable names, equations, citation markers like [12] or (Smith et al., 2020), and figure/table references unchanged.
- Translate headings and captions too. Do not add commentary.
- Output ONLY a JSON object of the form {{"translations": [{{"id": "<item id>", "t": "<translation>"}}, ...]}} with one entry per input item, same ids."""


def _body_page(pid: str, pno: int, step: int) -> tuple[int | None, dict | None]:
    """Nearest page in direction `step` that has body text (skips figure-only pages)."""
    n = doc_for(pid).page_count
    q = pno + step
    for _ in range(paragraphs.LOOKAHEAD):
        if q < 0 or q >= n:
            break
        lay = layout(pid, q)
        if paragraphs.has_body(lay):
            return q, lay
        q += step
    return None, None


def _open_tail(units: list[dict]) -> dict | None:
    """The page's last body unit if it ends mid-sentence and no heading follows it."""
    for u in reversed(units):
        if u["kind"] == "heading":
            return None
        if u["kind"] == paragraphs.BODY:
            return None if paragraphs.ends_sentence(u["blocks"][-1]["text"]) else u
    return None


def page_stitching(pid: str, pno: int, units: list[dict]) -> tuple[dict | None, dict | None]:
    """(continuation into the next body page, reference back to the previous body page)."""
    cont = None
    tail = _open_tail(units)
    if tail:
        q, lay_q = _body_page(pid, pno, +1)
        head_unit = paragraphs.first_content_is_body(lay_q) if lay_q else None
        if head_unit:
            head = paragraphs.split_unit(head_unit)[0]
            rects = paragraphs.rects_for_range(doc_for(pid)[q], head_unit, head["start"], head["end"])
            cont = {"unit_id": tail["id"], "page": q, "text": head["text"], "rects": rects}
    ref = None
    head_unit = paragraphs.first_content_is_body(layout(pid, pno))
    if head_unit:
        p, lay_p = _body_page(pid, pno, -1)
        if lay_p:
            prev_tail = _open_tail(paragraphs.build_units(lay_p))
            if prev_tail:
                last_k = len(paragraphs.split_unit(prev_tail)) - 1
                ref = {"unit_id": head_unit["id"], "page": p, "sid": f"{prev_tail['id']}.{last_k}"}
    return cont, ref


async def translate_page(pid: str, pno: int, lang: str, provider_name: str | None = None,
                         force: bool = False, model: str | None = None) -> list[dict]:
    key = f"tr{LAYOUT_VERSION}u:{pid}:{pno}:{lang}"
    if not force:
        cached = db.cache_get(key)
        if cached is not None:
            return cached
    lay = layout(pid, pno)
    units = paragraphs.build_units(lay)
    if not units:
        db.cache_set(key, [])
        return []
    cont, ref = page_stitching(pid, pno, units)
    page = doc_for(pid)[pno]

    # sentences per unit; the sentence cut by a page break is translated whole on the earlier page
    unit_sents: dict[str, list[dict]] = {}
    items: list[dict] = []
    for u in units:
        ss = paragraphs.split_unit(u)
        for k, s in enumerate(ss):
            s["id"] = f"{u['id']}.{k}"
            s["rects"] = paragraphs.rects_for_range(page, u, s["start"], s["end"])
            if ref and u["id"] == ref["unit_id"] and k == 0:
                s["ref"] = {"page": ref["page"], "sid": ref["sid"]}
                continue
            if cont and u["id"] == cont["unit_id"] and k == len(ss) - 1:
                s["text"] = f"{s['text']} {cont['text']}"
                s["cont"] = {"page": cont["page"], "rects": cont["rects"]}
            items.append({"id": s["id"], "text": s["text"]})
        unit_sents[u["id"]] = ss
    chunks: list[list[dict]] = [[]]
    size = 0
    for it in items:
        if size > 5000 and chunks[-1]:
            chunks.append([])
            size = 0
        chunks[-1].append(it)
        size += len(it["text"])

    provider = resolve_provider(provider_name, model=model)
    ctx = paper_context(pid)
    system = TRANSLATE_SYSTEM.format(lang=lang_name(lang))
    result_map: dict[str, str] = {}
    for chunk in chunks:
        user = f"Paper title: {ctx['title']}\n\nItems:\n{json.dumps(chunk, ensure_ascii=False)}"
        text = await provider.complete(system, [Msg("user", user)], max_tokens=16000, effort="low")
        _record(pid, provider, "translate")
        parsed = _extract_json(text)
        for item in parsed.get("translations", []):
            if isinstance(item, dict) and "id" in item:
                result_map[str(item["id"])] = str(item.get("t", ""))

    result = []
    for u in units:
        sentences = []
        for s in unit_sents[u["id"]]:
            item = {"id": s["id"], "text": s["text"], "t": "" if s.get("ref") else result_map.get(s["id"], ""), "rects": s["rects"]}
            for k in ("ref", "cont"):
                if s.get(k):
                    item[k] = s[k]
            sentences.append(item)
        first = u["blocks"][0]
        result.append({
            "id": u["id"], "kind": u["kind"], "bbox": first["bbox"], "size": first["size"],
            "lines": sum(b["lines"] for b in u["blocks"]),
            "text": paragraphs.unit_text(u),
            "t": " ".join(x["t"] for x in sentences if x["t"]),
            "sentences": sentences,
            "boxes": paragraphs.overlay_boxes(u, lay["width"]),
        })
    db.cache_set(key, result)
    return result


async def translate_text(pid: str, text: str, lang: str, provider_name: str | None = None,
                         model: str | None = None) -> str:
    provider = resolve_provider(provider_name, model=model)
    ctx = paper_context(pid)
    system = (f"You translate excerpts of the research paper '{ctx['title']}' into {lang_name(lang)}. "
              "Return only the translation, no commentary.")
    out = await provider.complete(system, [Msg("user", text)], max_tokens=4000, effort="low")
    _record(pid, provider, "translate")
    return out


# ---------------------------------------------------------------- explanation
EXPLAIN_SYSTEM = """You are an expert research colleague helping a reader understand a specific paper.
Answer in {lang}. Be concrete and accurate; ground every statement in the paper's own content and standard domain knowledge.
If something is not determinable from the paper, say so rather than guessing.
Use short paragraphs or bullet points; use Markdown; keep LaTeX for equations ($...$).

Paper title: {title}
Beginning of the paper (abstract / introduction):
{head}"""


async def explain_stream(pid: str, kind: str, payload: dict, lang: str,
                         provider_name: str | None = None, model: str | None = None,
                         effort: str = "medium") -> AsyncIterator[str]:
    ctx = paper_context(pid)
    system = EXPLAIN_SYSTEM.format(lang=lang_name(lang), title=ctx["title"], head=ctx["head"])
    images: list[tuple[bytes, str]] = []
    pno = int(payload.get("page", 0) or 0)
    question = (payload.get("question") or "").strip()

    if kind in ("figure", "table"):
        fid = payload.get("figure_id", "")
        pno, fig = _figure(pid, fid)
        images.append((figure_image(pid, fid, with_caption=True), "image/png"))
        what = "table" if fig["kind"] == "table" else "figure"
        user = (f"Explain this {what} from the paper (page {pno + 1}).\n"
                f"Caption: {fig.get('caption') or '(none detected)'}\n\n"
                f"Text on the same page for context:\n{page_text(pid, pno, 3000)}\n\n"
                "Cover: (1) what is shown and how to read the axes/panels/columns, (2) the key finding the authors "
                "draw from it, (3) how it supports the paper's argument, (4) anything a careful reader should be "
                "cautious about.")
    elif kind == "citation":
        refs = payload.get("refs") or []
        ref_txt = "\n".join(f"- [{r.get('n')}] {r.get('raw')}" for r in refs) or "(reference entry not found)"
        user = (f"In the paper, this sentence/passage (page {pno + 1}) cites a reference:\n\"{payload.get('text', '')}\"\n\n"
                f"Cited reference(s):\n{ref_txt}\n\n"
                "Explain briefly: what is the cited work about, why the authors cite it here, and what claim it "
                "supports. If you know the cited work, summarize its main contribution in 2–3 sentences.")
    else:
        sel = payload.get("text", "")
        extra = ""
        if kind == "equation":
            extra = "This is an equation or mathematical expression: define every symbol, explain the intuition, and say where it is used in the paper.\n"
        elif kind == "term":
            extra = "Give a concise definition of the term as used in this paper and in the field.\n"
        user = (f"Selected passage (page {pno + 1}):\n\"\"\"{sel}\"\"\"\n\n{extra}"
                f"Surrounding page text for context:\n{page_text(pid, pno, 3000)}\n\n"
                "Explain the selected passage in context: what it means, why it matters for the paper, and any "
                "background knowledge needed to understand it.")
    if question:
        user += f"\n\nThe reader's specific question: {question}"

    provider = resolve_provider(provider_name, need_vision=bool(images), model=model)
    async for t in provider.stream(system, [Msg("user", user, images)], max_tokens=6000, effort=effort):
        yield t
    _record(pid, provider, f"explain:{kind}")


# ---------------------------------------------------------------- summary
SUMMARY_SYSTEM = """You are an expert at summarizing research papers for other researchers. Write in {lang}.
Use Markdown with exactly these sections (translate the headings into {lang}):
1. One-sentence summary
2. Research question / motivation
3. Methods (data, model/experimental design, key techniques)
4. Key results (with the important numbers)
5. Contributions / novelty
6. Limitations and open questions
7. Keywords (5–8)
Be faithful to the paper; do not invent results."""


def get_summary(pid: str, lang: str) -> str | None:
    return db.cache_get(f"sum:{pid}:{lang}")


async def summary_stream(pid: str, lang: str, provider_name: str | None = None,
                         model: str | None = None, effort: str = "medium") -> AsyncIterator[str]:
    text = pdf_engine.full_text(doc_for(pid), max_chars=150_000)
    ctx = paper_context(pid)
    provider = resolve_provider(provider_name, model=model)
    system = SUMMARY_SYSTEM.format(lang=lang_name(lang))
    user = f"Paper title: {ctx['title']}\n\nFull text:\n{text}"
    buf = []
    async for t in provider.stream(system, [Msg("user", user)], max_tokens=6000, effort=effort):
        buf.append(t)
        yield t
    _record(pid, provider, "summary")
    db.cache_set(f"sum:{pid}:{lang}", "".join(buf))


# ---------------------------------------------------------------- chat
CHAT_SYSTEM = """You are a knowledgeable research colleague discussing one specific paper with the reader.
Respond in {lang}. Ground your answers in the paper's text; cite page numbers like (p.3) when you refer to specific content.
When the paper does not contain the answer, say so clearly and then offer relevant general knowledge, labeled as such.
Use Markdown; keep LaTeX for equations.

Paper title: {title}

Full text of the paper (page markers [p.N]):
{text}"""


async def chat_stream(pid: str, messages: list[dict], lang: str,
                      provider_name: str | None = None, model: str | None = None,
                      effort: str = "medium") -> AsyncIterator[str]:
    text = pdf_engine.full_text(doc_for(pid), max_chars=150_000)
    ctx = paper_context(pid)
    provider = resolve_provider(provider_name, model=model)
    system = CHAT_SYSTEM.format(lang=lang_name(lang), title=ctx["title"], text=text)
    conv = [Msg(m["role"], m["content"]) for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
    if not conv or conv[-1].role != "user":
        raise ValueError("마지막 메시지는 사용자 메시지여야 합니다.")
    async for t in provider.stream(system, conv, max_tokens=6000, effort=effort):
        yield t
    _record(pid, provider, "chat")


async def test_provider(name: str) -> str:
    from .llm import get_provider
    p = get_provider(name)
    out = await p.complete("Reply with exactly: OK", [Msg("user", "ping")], max_tokens=64, effort="low")
    return out.strip()[:200]


def default_lang() -> str:
    return load_settings().get("target_lang", "ko")

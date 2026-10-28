"""Reference-list parsing and metadata lookup (CrossRef)."""
from __future__ import annotations

import re

import httpx

REF_HEADING_RE = re.compile(
    r"(?im)^[^\w\n]*(?:\d+\.?\s*)?(references?|bibliography|reference list|literature cited|works cited|참고\s*문헌)\b[^\w\n]*(?=$|[(\[]?\d)"
)
STOP_RE = re.compile(r"(?im)^\s*(appendix|appendices|supplementary (?:material|information)|supporting information)\b")
NUM_START_RE = re.compile(r"^\s*(?:\[(\d{1,4})\]|\((\d{1,4})\)|(\d{1,4})\.(?!\d)|(\d{1,4})\)|(\d{1,4})\s+(?=[A-Z]))\s*")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;]+)")
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})[a-z]?\b")


def looks_like_reference_list(lines: list[str]) -> bool:
    """True when the first lines after a heading look like bibliography entries."""
    head = lines[:40]
    numbered = sum(1 for ln in head if NUM_START_RE.match(ln))
    if numbered >= 3:
        return True
    author_year = sum(1 for ln in head if re.match(r"^[A-Z][A-Za-z'’\-]+,?\s", ln) and YEAR_RE.search(ln[:200]))
    return author_year >= 3


def find_reference_section(page_texts: list[str]) -> tuple[list[dict], int | None, str]:
    """Locate the bibliography. Returns (entries, page index of the heading, heading line text)."""
    text = "\n".join(page_texts)
    heads = list(REF_HEADING_RE.finditer(text))
    # try the last heading first; fall back to earlier ones (NIH manuscripts put tables after the refs)
    for h in reversed(heads):
        body = text[h.end():]
        stop = STOP_RE.search(body)
        if stop and stop.start() > 300:
            body = body[: stop.start()]
        lines = [ln.rstrip() for ln in body.splitlines() if ln.strip()]
        if len(lines) >= 3 and looks_like_reference_list(lines):
            entries = _split_entries(lines)
            if len(entries) >= 3:
                # map the char offset back to a page index
                pos, pno = 0, 0
                for i, t in enumerate(page_texts):
                    if pos + len(t) >= h.start():
                        pno = i
                        break
                    pos += len(t) + 1
                return _finish_entries(entries), pno, h.group(0).strip()
    return [], None, ""


def parse_references(page_texts: list[str]) -> list[dict]:
    return find_reference_section(page_texts)[0]


def _split_entries(lines: list[str]) -> list[str]:
    numbered_hits = sum(1 for ln in lines if NUM_START_RE.match(ln))
    entries: list[str] = []
    if numbered_hits >= 3:
        # numbered list: accept a new entry only when its number continues the sequence
        cur, expected, started = "", 1, False
        for ln in lines:
            m = NUM_START_RE.match(ln)
            n = int(next(g for g in m.groups() if g)) if m else None
            if n is not None and ((not started and n <= 2) or (started and expected <= n <= expected + 2)):
                if cur:
                    entries.append(cur)
                cur, expected, started = ln, n + 1, True
            elif started:
                cur += " " + ln.strip()
        if cur:
            entries.append(cur)
    else:
        # author-year style: a new entry starts with a capital letter after a line ending with . or )
        cur = ""
        for ln in lines:
            s = ln.strip()
            starts_new = bool(re.match(r"^[A-ZÀ-ɏ][A-Za-zÀ-ɏ'’\-]+", s)) and (
                not cur or re.search(r"[.)\d]\s*$", cur)
            ) and bool(YEAR_RE.search(s[:160]))
            if starts_new and cur:
                entries.append(cur)
                cur = s
            else:
                cur = (cur + " " + s).strip()
        if cur:
            entries.append(cur)
    return entries


def _finish_entries(entries: list[str]) -> list[dict]:
    out: list[dict] = []
    for i, raw in enumerate(entries):
        raw = re.sub(r"\s+", " ", raw).strip()
        m = NUM_START_RE.match(raw)
        n = int(next(g for g in m.groups() if g)) if m else i + 1
        body_txt = raw[m.end():] if m else raw
        doi = DOI_RE.search(body_txt)
        year = YEAR_RE.search(body_txt)
        first_author = re.split(r"[,;(]", body_txt, 1)[0].strip()[:60]
        out.append({
            "n": n,
            "raw": body_txt,
            "doi": doi.group(1).rstrip(".") if doi else "",
            "year": year.group(1) if year else "",
            "first_author": first_author,
        })
    return out


def match_author_year(refs: list[dict], authors: str) -> list[int]:
    """Map an author-year citation like 'Smith et al., 2020' onto entry numbers."""
    hits: list[int] = []
    for part in re.split(r"\s*;\s*", authors):
        surname = re.match(r"([A-Z][A-Za-z'’\-]+)", part.strip())
        year = YEAR_RE.search(part)
        if not surname or not year:
            continue
        for r in refs:
            if r["year"] == year.group(1) and re.search(r"\b" + re.escape(surname.group(1)) + r"\b", r["raw"][:200]):
                hits.append(r["n"])
                break
    return hits


async def lookup_crossref(raw: str, doi: str = "") -> dict | None:
    """Fetch bibliographic metadata from CrossRef; returns None if nothing found."""
    headers = {"User-Agent": "paper-reader/0.1 (mailto:paper-reader@example.com)"}
    try:
        async with httpx.AsyncClient(timeout=12, headers=headers) as client:
            item = None
            if doi:
                r = await client.get(f"https://api.crossref.org/works/{doi}")
                if r.status_code == 200:
                    item = r.json().get("message")
            if item is None:
                r = await client.get(
                    "https://api.crossref.org/works",
                    params={"query.bibliographic": raw[:300], "rows": 1},
                )
                if r.status_code != 200:
                    return None
                items = r.json().get("message", {}).get("items") or []
                item = items[0] if items else None
            if not item:
                return None
    except Exception:
        return None

    title = (item.get("title") or [""])[0]
    authors = []
    for a in item.get("author") or []:
        nm = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if nm:
            authors.append(nm)
    year = ""
    for k in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(k) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    abstract = re.sub(r"<[^>]+>", " ", item.get("abstract") or "")
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "journal": (item.get("container-title") or [""])[0],
        "doi": item.get("DOI", ""),
        "url": item.get("URL") or (f"https://doi.org/{item['DOI']}" if item.get("DOI") else ""),
        "abstract": abstract[:2000],
        "cited_by": item.get("is-referenced-by-count"),
        "score": item.get("score"),
    }

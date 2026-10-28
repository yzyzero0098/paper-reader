"""PDF layout extraction with PyMuPDF.

Everything the reader needs from a page: text blocks with bounding boxes
(for layout-preserving translation), figures/tables (for figure explanation),
and in-text citation markers (for smart citations).
Coordinates are PDF points with the origin at the top-left, which matches
pdf.js at scale 1.
"""
from __future__ import annotations

import re
import statistics
import threading
from collections import OrderedDict
from pathlib import Path

import fitz  # PyMuPDF

CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?s?\.?|table|scheme|algorithm|chart|box)\s*S?\d+", re.I)
TABLE_CAPTION_RE = re.compile(r"^\s*table\s*S?\d+", re.I)
REF_HEADING_RE = re.compile(
    r"^[\W\d]*(references?|bibliography|reference list|literature cited|works cited|참고\s*문헌)\b[^\w\n]*(?=$|[(\[]?\d)",
    re.I,
)
NUMERIC_CITE_RE = re.compile(r"\[(\d{1,4}(?:\s*[-–—−,]\s*\d{1,4})*)\]")
PAREN_CITE_RE = re.compile(r"\((\d{1,3}(?:\s*[-–—−,]\s*\d{1,3})*)\)")
SUP_TEXT_RE = re.compile(r"[\d\s,\-–—−]+")
SUP_CITE_RE = re.compile(r"\d{1,3}(?:\s*[-–—−,]\s*\d{1,3})*")
JUNK_TITLE_RE = re.compile(r"^\w{4,}\s+\d+\.\.\d+$|untitled|\.(pdf|docx?|tex|dvi|ps)$|^(doi|microsoft word)", re.I)
BOILERPLATE_RE = re.compile(
    r"public access|author manuscript|downloaded from|accepted manuscript|^(research|review|original) article|^www\.|^https?:|^©|all rights reserved",
    re.I,
)
AUTHOR_YEAR_RE = re.compile(
    r"\(((?:[A-Z][A-Za-z'’\-]+(?:\s+(?:et\s+al\.?|and|&)\s*[A-Z]?[A-Za-z'’\-]*)*,?\s+(?:19|20)\d{2}[a-z]?"
    r"(?:\s*[;,]\s*)?)+)\)"
)

_docs: "OrderedDict[str, fitz.Document]" = OrderedDict()
_docs_lock = threading.Lock()
_MAX_OPEN = 8


def open_doc(path: Path) -> fitz.Document:
    key = str(path)
    with _docs_lock:
        if key in _docs:
            _docs.move_to_end(key)
            return _docs[key]
        doc = fitz.open(key)
        _docs[key] = doc
        while len(_docs) > _MAX_OPEN:
            _, old = _docs.popitem(last=False)
            try:
                old.close()
            except Exception:
                pass
        return doc


def close_doc(path: Path) -> None:
    _line_x_cache.pop(str(path), None)
    with _docs_lock:
        doc = _docs.pop(str(path), None)
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


# ---------------------------------------------------------------- helpers
def _join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha() and ln[:1].islower():
            out = out[:-1] + ln          # de-hyphenate
        else:
            out += " " + ln
    return re.sub(r"\s+", " ", out).strip()


def _expand_numbers(s: str) -> list[int]:
    nums: list[int] = []
    for part in re.split(r"\s*,\s*", s):
        m = re.match(r"(\d+)\s*[-–—−]\s*(\d+)$", part.strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a < 50:
                nums.extend(range(a, b + 1))
        elif part.strip().isdigit():
            nums.append(int(part))
    return nums


def _rect(b) -> fitz.Rect:
    return fitz.Rect(b)


LINE_NO_RE = re.compile(r"^\s*\d{1,4}\s*$")


def line_number_spans(blocks: list[dict], page_width: float, known_x: float | None = None) -> set[tuple[int, int, int]]:
    """Find manuscript line numbers: short integer spans in a narrow margin column whose values increase
    top to bottom. `known_x` is the line-number column found elsewhere in the document; spans there are
    dropped even on pages with only a few lines. Returns (block, line, span) indices to drop."""
    cands = []
    page_h = 0.0
    for bi, b in enumerate(blocks):
        if b.get("type") != 0:
            continue
        page_h = max(page_h, b["bbox"][3])
        for li, ln in enumerate(b["lines"]):
            filled = [s for s in ln["spans"] if s["text"].strip()]
            if len(filled) != 1:          # a line number stands alone on its line (not a table cell)
                continue
            for si, s in enumerate(ln["spans"]):
                if s is not filled[0] or not LINE_NO_RE.match(s["text"]) or s["size"] < 7:
                    continue
                x0, y0, x1, _ = s["bbox"]
                if x1 - x0 < 30 and (x1 < 0.22 * page_width or x0 > 0.78 * page_width):
                    cands.append((x0, y0, int(s["text"]), (bi, li, si)))
    drop: set[tuple[int, int, int]] = set()
    cands.sort()
    i = 0
    while i < len(cands):
        j = i
        while j + 1 < len(cands) and cands[j + 1][0] - cands[i][0] <= 8:
            j += 1
        group = sorted(cands[i:j + 1], key=lambda c: c[1])
        if known_x is not None and all(abs(g[0] - known_x) <= 8 for g in group):
            drop.update(g[3] for g in group)
        elif len(group) >= 5:
            vals = [g[2] for g in group]
            inc = sum(1 for a, b2 in zip(vals, vals[1:]) if 0 < b2 - a <= 3)
            tall = group[-1][1] - group[0][1] >= 0.25 * max(page_h, 1)
            if tall and inc >= 0.8 * (len(vals) - 1):
                drop.update(g[3] for g in group)
        i = j + 1
    return drop


_line_x_cache: dict[str, float | None] = {}


def doc_line_number_x(doc: fitz.Document) -> float | None:
    """x position of the manuscript line-number column, detected on the first pages (None if absent)."""
    key = doc.name or str(id(doc))
    if key not in _line_x_cache:
        xs: list[float] = []
        for pno in range(min(doc.page_count, 8)):
            page = doc[pno]
            blocks = page.get_text("dict")["blocks"]
            for bi, li, si in line_number_spans(blocks, page.rect.width):
                xs.append(blocks[bi]["lines"][li]["spans"][si]["bbox"][0])
            if len(xs) >= 20:
                break
        _line_x_cache[key] = statistics.median(xs) if len(xs) >= 8 else None
    return _line_x_cache[key]


def strip_line_numbers(blocks: list[dict], page_width: float, known_x: float | None = None) -> list[dict]:
    """Copy of the raw text blocks with line-number spans removed and bboxes recomputed."""
    drop = line_number_spans(blocks, page_width, known_x)
    if not drop:
        return blocks
    out = []
    for bi, b in enumerate(blocks):
        if b.get("type") != 0:
            out.append(b)
            continue
        lines = []
        for li, ln in enumerate(b["lines"]):
            spans = [s for si, s in enumerate(ln["spans"]) if (bi, li, si) not in drop]
            if any(s["text"].strip() for s in spans):
                lines.append({**ln, "spans": spans})
        if not lines:
            continue
        r = None
        for ln in lines:
            for s in ln["spans"]:
                if s["text"].strip():
                    r = fitz.Rect(s["bbox"]) if r is None else r | fitz.Rect(s["bbox"])
        out.append({**b, "lines": lines, "bbox": tuple(r) if r else b["bbox"]})
    return out


def _merge_rects(rects: list[fitz.Rect], gap: float = 6) -> list[fitz.Rect]:
    rects = [fitz.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out: list[fitz.Rect] = []
        while rects:
            r = rects.pop()
            grown = fitz.Rect(r.x0 - gap, r.y0 - gap, r.x1 + gap, r.y1 + gap)
            merged = False
            for i, o in enumerate(out):
                if grown.intersects(o):
                    out[i] = o | r
                    merged = True
                    changed = True
                    break
            if not merged:
                out.append(r)
        rects = out
    return rects


# ---------------------------------------------------------------- metadata
def extract_title(doc: fitz.Document) -> str:
    meta_title = ((doc.metadata or {}).get("title") or "").strip()
    words = [w for w in re.findall(r"[A-Za-zÀ-ɏ가-힣]{4,}", meta_title)]
    if 10 < len(meta_title) < 300 and len(meta_title.split()) >= 3 and len(words) >= 2 \
            and not JUNK_TITLE_RE.search(meta_title) and not BOILERPLATE_RE.search(meta_title):
        return meta_title
    if doc.page_count == 0:
        return "제목 없음"
    page = doc[0]
    best, best_size = "", 0.0
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        sizes = [s["size"] for ln in b["lines"] for s in ln["spans"] if s["text"].strip()]
        if not sizes:
            continue
        size = max(sizes)
        text = _join_lines(["".join(s["text"] for s in ln["spans"]) for ln in b["lines"]])
        if 10 < len(text) < 300 and len(text.split()) >= 3 and size > best_size and not BOILERPLATE_RE.search(text):
            best, best_size = text, size
    return best or meta_title or "제목 없음"


def reading_text(page: fitz.Page) -> str:
    """Page text in reading order: full-width blocks first, then left column, then right column."""
    W, H = page.rect.width, page.rect.height
    items = []
    for b in strip_line_numbers(page.get_text("dict")["blocks"], W, doc_line_number_x(page.parent)):
        if b.get("type") != 0:
            continue
        x0, y0, x1, y1 = b["bbox"]
        lines = ["".join(s["text"] for s in ln["spans"]).strip() for ln in b["lines"]]
        lines = [ln for ln in lines if ln]
        if not lines:
            continue
        # running headers / footers (journal name, page numbers, DOI lines) pollute the text
        if len(lines) <= 3 and (y1 - y0) < 45 and (y0 < 0.07 * H or y1 > 0.93 * H):
            continue
        wide = (x1 - x0) > 0.6 * W
        col = 0 if wide or (x0 + x1) / 2 < W / 2 else 1
        items.append((col, y0, x0, "\n".join(lines)))
    items.sort(key=lambda t: (t[0], t[1], t[2]))
    return "\n".join(t[3] for t in items)


def page_texts(doc: fitz.Document) -> list[str]:
    return [reading_text(p) for p in doc]


def full_text(doc: fitz.Document, max_chars: int = 200_000) -> str:
    parts = []
    total = 0
    for i, t in enumerate(page_texts(doc)):
        chunk = f"\n\n[p.{i + 1}]\n{t.strip()}"
        if total + len(chunk) > max_chars:
            parts.append(chunk[: max(0, max_chars - total)])
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts)


def find_references_start(doc: fitz.Document) -> tuple[int, float] | None:
    """(page index, y) of the References heading, searched from the back."""
    from .citations import find_reference_section

    _, pno, heading = find_reference_section(page_texts(doc))
    if pno is None:
        return None
    page = doc[pno]
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if text and (text == heading or REF_HEADING_RE.match(text)):
                return pno, float(ln["bbox"][1])
    return pno, 0.0


# ---------------------------------------------------------------- layout
def _superscript_cites(lines: list[dict]) -> list[tuple[str, list[float]]]:
    """Find superscript numeric citation markers (e.g. '12', '3–5', '2,7') in a block's lines."""
    found: list[tuple[str, list[float]]] = []
    for ln in lines:
        group: list[dict] = []

        def flush():
            if not group:
                return
            txt = re.sub(r"\s+", "", "".join(s["text"] for s in group))
            if SUP_CITE_RE.fullmatch(txt):
                r = fitz.Rect(group[0]["bbox"])
                for s in group[1:]:
                    r |= fitz.Rect(s["bbox"])
                found.append((txt, [round(v, 2) for v in r]))
            group.clear()

        for s in ln["spans"]:
            if (s["flags"] & 1) and s["text"].strip() and SUP_TEXT_RE.fullmatch(s["text"]):
                group.append(s)
            elif group and not s["text"].strip():
                continue
            else:
                flush()
        flush()
    return found


def page_layout(doc: fitz.Document, pno: int, refs_start: tuple[int, float] | None, ref_count: int = 0) -> dict:
    page = doc[pno]
    W, H = page.rect.width, page.rect.height
    raw = page.get_text("dict")
    raw = {**raw, "blocks": strip_line_numbers(raw["blocks"], W, doc_line_number_x(doc))}

    # ---- text blocks
    blocks: list[dict] = []
    image_rects: list[fitz.Rect] = []
    all_sizes: list[float] = []
    for b in raw["blocks"]:
        if b.get("type") == 1:
            image_rects.append(_rect(b["bbox"]))
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                if s["text"].strip():
                    all_sizes.extend([s["size"]] * max(1, len(s["text"].strip())))
    body_size = statistics.median(all_sizes) if all_sizes else 10.0

    cites: dict[str, dict] = {}
    in_refs_page = refs_start is not None and pno > refs_start[0]
    for i, b in enumerate(raw["blocks"]):
        if b.get("type") != 0:
            continue
        line_texts, sizes, bold_chars, total_chars = [], [], 0, 0
        for ln in b["lines"]:
            t = "".join(s["text"] for s in ln["spans"])
            line_texts.append(t)
            for s in ln["spans"]:
                n = len(s["text"].strip())
                if n:
                    sizes.append(s["size"])
                    total_chars += n
                    if s["flags"] & 16:
                        bold_chars += n
        text = _join_lines(line_texts)
        if not text:
            continue
        size = statistics.median(sizes) if sizes else body_size
        bold = total_chars > 0 and bold_chars / total_chars > 0.6
        nlines = len([t for t in line_texts if t.strip()])
        bbox = [round(v, 2) for v in b["bbox"]]

        kind = "text"
        if CAPTION_RE.match(text):
            kind = "caption"
        elif REF_HEADING_RE.match(text):
            kind = "heading"
        elif len(text) < 4 or (nlines == 1 and size < body_size * 0.8 and (bbox[1] < H * 0.06 or bbox[3] > H * 0.94)):
            kind = "small"           # page numbers, running headers
        elif (nlines <= 2 or bbox[3] - bbox[1] < 2.6 * size) and len(text) < 160 and (bbox[3] < H * 0.065 or bbox[1] > H * 0.94):
            kind = "small"           # running headers/footers ("Journal of ... Article", "J. ... 2022, 21, 2085")
        elif re.fullmatch(r"[\d\s.,;:()\[\]|\-–—]+", text):
            kind = "small"
        elif (size >= body_size * 1.15 and nlines <= 3 and len(text) < 160) or (bold and nlines <= 2 and len(text) < 120):
            kind = "heading"
        if in_refs_page or (refs_start is not None and pno == refs_start[0] and bbox[1] >= refs_start[1] - 2 and kind != "heading"):
            if kind in ("text", "small"):
                kind = "reference"
        if kind not in ("reference", "small"):
            for txt, rect in _superscript_cites(b["lines"]):
                entry = cites.setdefault("^" + txt, {"text": txt, "style": "numeric", "refs": _expand_numbers(txt), "rects": []})
                entry["rects"].append(rect)
        blocks.append({
            "id": f"{pno}-{i}",
            "bbox": bbox,
            "text": text,
            "kind": kind,
            "size": round(size, 2),
            "lines": nlines,
            "bold": bold,
        })

    # ---- tables
    tables: list[fitz.Rect] = []
    try:
        for t in page.find_tables().tables:
            r = fitz.Rect(t.bbox)
            if r.width > 60 and r.height > 30:
                tables.append(r)
    except Exception:
        pass

    # ---- figures = embedded images + vector drawing clusters
    draw_rects: list[fitz.Rect] = []
    try:
        for r in page.cluster_drawings():
            r = fitz.Rect(r)
            if r.width < 40 or r.height < 40:
                continue
            if any((r & t).get_area() > 0.6 * r.get_area() for t in tables):
                continue
            draw_rects.append(r)
    except Exception:
        pass
    fig_rects = []
    for r in _merge_rects(image_rects + draw_rects, gap=8):
        if r.width < 40 or r.height < 40:
            continue
        if r.get_area() > 0.92 * W * H:          # full-page background
            continue
        r = r & page.rect
        if r.is_empty:
            continue
        fig_rects.append(r)
    # drop figure rects that are mostly a table
    fig_rects = [r for r in fig_rects if not any((r & t).get_area() > 0.7 * r.get_area() for t in tables)]

    captions = [b for b in blocks if b["kind"] == "caption"]

    def nearest_caption(r: fitz.Rect, table: bool) -> dict | None:
        best, best_d = None, 1e9
        for c in captions:
            is_tab = bool(TABLE_CAPTION_RE.match(c["text"]))
            if is_tab != table:
                continue
            cb = fitz.Rect(c["bbox"])
            if cb.x1 < r.x0 - 20 or cb.x0 > r.x1 + 20:
                continue
            d_below = cb.y0 - r.y1
            d_above = r.y0 - cb.y1
            d = min(d_below if d_below >= -5 else 1e9, d_above if d_above >= -5 else 1e9)
            if d < best_d and d < 90:
                best, best_d = c, d
        return best

    figures: list[dict] = []
    for i, r in enumerate(sorted(fig_rects, key=lambda q: (q.y0, q.x0))):
        cap = nearest_caption(r, table=False)
        figures.append({
            "id": f"f{pno}-{i}",
            "kind": "figure",
            "bbox": [round(v, 2) for v in r],
            "caption": cap["text"] if cap else "",
            "caption_bbox": cap["bbox"] if cap else None,
        })
    for i, r in enumerate(sorted(tables, key=lambda q: (q.y0, q.x0))):
        cap = nearest_caption(r, table=True)
        figures.append({
            "id": f"t{pno}-{i}",
            "kind": "table",
            "bbox": [round(v, 2) for v in r],
            "caption": cap["text"] if cap else "",
            "caption_bbox": cap["bbox"] if cap else None,
        })

    # ---- text drawn inside figures/tables (axis labels, legends, cells) is not body text
    fig_boxes = [fitz.Rect(f["bbox"]) for f in figures]
    for b in blocks:
        if b["kind"] not in ("text", "heading") or not fig_boxes:
            continue
        r = fitz.Rect(b["bbox"])
        area = max(r.get_area(), 1.0)
        if any((r & fr).get_area() > 0.6 * area for fr in fig_boxes):
            b["kind"] = "figtext"

    # ---- in-text citations (bracketed, parenthetical numeric, author-year; superscripts collected above)
    searchable: dict[str, dict] = {}
    for b in blocks:
        if b["kind"] in ("reference", "small"):
            continue
        for m in NUMERIC_CITE_RE.finditer(b["text"]):
            key = m.group(0)
            if key not in searchable:
                searchable[key] = {"text": key, "style": "numeric", "refs": _expand_numbers(m.group(1)), "rects": []}
        if ref_count > 0:
            for m in PAREN_CITE_RE.finditer(b["text"]):
                nums = _expand_numbers(m.group(1))
                key = m.group(0)
                if nums and max(nums) <= ref_count and key not in searchable:
                    searchable[key] = {"text": key, "style": "numeric", "refs": nums, "rects": []}
        for m in AUTHOR_YEAR_RE.finditer(b["text"]):
            key = m.group(0)
            if key not in searchable:
                searchable[key] = {"text": key, "style": "author-year", "refs": [], "authors": m.group(1), "rects": []}
    for key, c in searchable.items():
        try:
            rects = page.search_for(key)[:40]
        except Exception:
            rects = []
        c["rects"] = [[round(v, 2) for v in r] for r in rects]
        if c["rects"]:
            cites[key] = c

    return {
        "page": pno,
        "width": round(W, 2),
        "height": round(H, 2),
        "body_size": round(body_size, 2),
        "blocks": blocks,
        "figures": figures,
        "citations": list(cites.values()),
    }


ABBREV_RE = re.compile(
    r"(?:^|[\s(\[])(?:Fig|Figs|Tab|Tabs|Eq|Eqs|Ref|Refs|et al|al|i\.e|e\.g|vs|cf|viz|Dr|Mr|Mrs|Ms|Prof|No|Nos|approx|ca|St|Inc|Ltd|Co|Jr|Sr"
    r"|vol|pp|p|Suppl|Sect|Ch|Chem|Phys|Biol|Proc|Natl|Acad|Sci|J|Am|Soc|Nat|Rev|Res|Mol|Cell|Sci|Eng|Med|Univ|Dept|Lab|Ave|U\.S|U\.K|[A-Z])\.$"
)
# sentence end: ". " or, after a word, a period followed by a superscript citation (".14 ", ".2,3 ", ".5–7 ")
SENT_END_RE = re.compile(
    r"(?:(?<=[A-Za-z)\]%])[.!?]\d{1,3}(?:[,–\-−]\d{1,3})*|[.!?])(?=\s+[A-Z0-9(\[\"“‘])"
)


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, keeping common abbreviations and short fragments together."""
    parts, last = [], 0
    for m in SENT_END_RE.finditer(text):
        parts.append(text[last:m.end()].strip())
        last = m.end()
    parts.append(text[last:].strip())
    parts = [p for p in parts if p]
    out: list[str] = []
    for p in parts:
        if out and (ABBREV_RE.search(out[-1]) or len(out[-1]) < 12 or len(p) < 8):
            out[-1] += " " + p
        else:
            out.append(p)
    return out or [text.strip()]


def _r(rect) -> list[float]:
    return [round(v, 2) for v in rect]


def sentence_rects(page: fitz.Page, text: str, clip) -> list[list[float]]:
    """Locate a sentence on the page (within its block). Falls back to head/tail anchoring when the
    exact search fails (e.g. de-hyphenated words), returning line-spanning rects inside the block."""
    clip = fitz.Rect(clip)
    try:
        hits = page.search_for(text, clip=clip)
    except Exception:
        hits = []
    if hits:
        return [_r(r) for r in hits]
    head, tail = text[:40].strip(), text[-40:].strip()
    try:
        hs = page.search_for(head, clip=clip)
        ts = page.search_for(tail, clip=clip)
    except Exception:
        hs, ts = [], []
    s = fitz.Rect(hs[0]) if hs else None
    e = fitz.Rect(ts[-1]) if ts else None
    if s and e and e.y1 >= s.y0:
        if abs(e.y0 - s.y0) < 3:      # same line
            return [_r(fitz.Rect(s.x0, s.y0, e.x1, e.y1))]
        rects = [fitz.Rect(s.x0, s.y0, clip.x1, s.y1)]
        if e.y0 - s.y1 > 2:
            rects.append(fitz.Rect(clip.x0, s.y1, clip.x1, e.y0))
        rects.append(fitz.Rect(clip.x0, e.y0, e.x1, e.y1))
        return [_r(r) for r in rects]
    if s:
        return [_r(s)]
    if e:
        return [_r(e)]
    return []


def figure_png(doc: fitz.Document, pno: int, bbox: list[float], zoom: float = 2.0, pad: float = 4) -> bytes:
    page = doc[pno]
    r = fitz.Rect(bbox)
    r = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad) & page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=r, alpha=False)
    return pix.tobytes("png")


def page_png(doc: fitz.Document, pno: int, zoom: float = 1.5) -> bytes:
    pix = doc[pno].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png")

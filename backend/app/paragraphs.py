"""Group layout blocks into translation units (paragraphs) and stitch sentences across columns and pages.

Why: PDFs often split one sentence over several blocks - one block per line in line-numbered manuscripts,
a column break in two-column papers, or a page break (sometimes with a figure-only page in between).
Translating blocks independently cuts sentences in half. Here we:
  1. order the body blocks of a page in reading order,
  2. merge consecutive body blocks while the previous one does not end a sentence (and merge single-line
     blocks of the same paragraph in line-per-block manuscripts),
  3. if a page's last body paragraph is unfinished, borrow the opening fragment of the next body page
     (skipping up to 3 pages without body text) so that sentence is translated whole; the next page then
     marks that fragment as a reference back to the previous page's sentence.
"""
from __future__ import annotations

import re

import fitz

from . import pdf_engine

TRAIL_CITE_RE = re.compile(r"(?:\s*(?:\[\d[^\]]*\]|\(\d[\d,\s–\-]*\)|\d{1,3}(?:[,–\-]\d{1,3})*))+$")
TERMINAL = (".", "!", "?", "。", ".\"", ".”", ".’", ".)")
BODY = "text"
LOOKAHEAD = 3


def ends_sentence(text: str) -> bool:
    t = text.rstrip()
    if not t:
        return True
    if t.endswith(TERMINAL) or t.endswith(":"):
        return True
    stripped = TRAIL_CITE_RE.sub("", t).rstrip()      # "...resistance.12" / "...(2)."
    return stripped != t and stripped.endswith(TERMINAL)


def _col(b: dict, page_w: float) -> int:
    x0, _, x1, _ = b["bbox"]
    if x1 - x0 > 0.6 * page_w:
        return 0
    return 0 if (x0 + x1) / 2 < page_w / 2 else 1


def reading_order(blocks: list[dict], page_w: float) -> list[dict]:
    return sorted(blocks, key=lambda b: (_col(b, page_w), b["bbox"][1], b["bbox"][0]))


def build_units(lay: dict) -> list[dict]:
    """Translation units of one page, in reading order. Each unit: id, kind, blocks (list of block dicts)."""
    W = lay["width"]
    content = [b for b in reading_order(lay["blocks"], W) if b["kind"] in ("text", "heading", "caption")]
    units: list[dict] = []
    for b in content:
        prev = units[-1] if units else None
        if prev and prev["kind"] == BODY and b["kind"] == BODY:
            last = prev["blocks"][-1]
            gap = b["bbox"][1] - last["bbox"][3]
            same_col = _col(last, W) == _col(b, W)
            indented = b["bbox"][0] > min(x["bbox"][0] for x in prev["blocks"]) + 8
            line_per_block = last["lines"] == 1 and b["lines"] == 1 and same_col and 0 <= gap < 0.9 * b["size"] and not indented
            if not ends_sentence(last["text"]) or line_per_block:
                prev["blocks"].append(b)
                continue
        units.append({"id": b["id"], "kind": b["kind"], "blocks": [b]})
    return units


def first_content_is_body(lay: dict) -> dict | None:
    """The first body unit if the page opens with body text (captions may come first), else None."""
    for u in build_units(lay):
        if u["kind"] == "caption":
            continue
        return u if u["kind"] == BODY else None
    return None


def has_body(lay: dict) -> bool:
    return any(b["kind"] == BODY for b in lay["blocks"])


def unit_text(u: dict) -> str:
    return " ".join(b["text"] for b in u["blocks"])


def split_unit(u: dict) -> list[dict]:
    """Sentences of a unit with their [start, end) offsets in unit_text."""
    text = unit_text(u)
    sents = pdf_engine.split_sentences(text) if u["kind"] == BODY else [text]
    out, pos = [], 0
    for s in sents:
        i = text.find(s, pos)
        if i < 0:
            i = pos
        out.append({"text": s, "start": i, "end": i + len(s)})
        pos = i + len(s)
    return out


def rects_for_range(page: fitz.Page, u: dict, start: int, end: int) -> list[list[float]]:
    """Rects on the page for characters [start, end) of a unit's text, block by block."""
    rects: list[list[float]] = []
    off = 0
    for b in u["blocks"]:
        bt = b["text"]
        b0, b1 = off, off + len(bt)
        a, z = max(start, b0), min(end, b1)
        if a < z:
            portion = bt[a - b0:z - b0].strip()
            if a == b0 and z >= b1 - 1:
                rects.append(b["bbox"])            # whole block
            elif portion:
                rects.extend(pdf_engine.sentence_rects(page, portion, b["bbox"]) or [b["bbox"]])
        off = b1 + 1                                 # +1 for the joining space
    return rects


def overlay_boxes(u: dict, page_w: float) -> list[dict]:
    """Union boxes per column run; the first run carries the translation in overlay mode."""
    runs: list[list[dict]] = []
    for b in u["blocks"]:
        if runs and _col(runs[-1][-1], page_w) == _col(b, page_w):
            runs[-1].append(b)
        else:
            runs.append([b])
    out = []
    for k, run in enumerate(runs):
        r = fitz.Rect(run[0]["bbox"])
        for b in run[1:]:
            r |= fitz.Rect(b["bbox"])
        out.append({"bbox": [round(v, 2) for v in r], "main": k == 0})
    return out

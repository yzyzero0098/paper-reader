"""Dev tool: dump blocks/lines/spans of one page (to study line numbers, columns, page breaks).

Usage: python -X utf8 backend/scripts/debug_spans.py <pdf> <page_index> [max_blocks]
"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
import fitz  # noqa: E402

doc = fitz.open(sys.argv[1])
pno = int(sys.argv[2])
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 12
page = doc[pno]
print("page size", page.rect)
for bi, b in enumerate(page.get_text("dict")["blocks"][:limit]):
    if b.get("type") != 0:
        print(f"B{bi} IMAGE {[round(v) for v in b['bbox']]}")
        continue
    print(f"B{bi} {[round(v) for v in b['bbox']]} lines={len(b['lines'])}")
    for li, ln in enumerate(b["lines"][:4]):
        spans = [(round(s["bbox"][0]), round(s["size"], 1), s["text"][:40]) for s in ln["spans"]]
        print(f"   L{li} {spans}")

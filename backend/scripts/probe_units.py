"""Dev tool: show translation units and cross-page stitching for a library paper (no LLM calls).

Usage: python -X utf8 backend/scripts/probe_units.py <paper_id> [first_page] [last_page]
"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app import paragraphs, services  # noqa: E402

pid = sys.argv[1]
n = services.doc_for(pid).page_count
a = int(sys.argv[2]) if len(sys.argv) > 2 else 0
z = int(sys.argv[3]) if len(sys.argv) > 3 else min(n - 1, a + 3)
for pno in range(a, z + 1):
    lay = services.layout(pid, pno)
    units = paragraphs.build_units(lay)
    cont, ref = services.page_stitching(pid, pno, units)
    body = [u for u in units if u["kind"] == "text"]
    print(f"=== p{pno + 1}: blocks={len(lay['blocks'])} units={len(units)} body={len(body)} "
          f"max_blocks_per_unit={max((len(u['blocks']) for u in units), default=0)}")
    for u in units[:4]:
        t = paragraphs.unit_text(u)
        print(f"   [{u['kind']}] ({len(u['blocks'])} blk) {t[:110]}{'…' if len(t) > 110 else ''}")
    if ref:
        print(f"   << starts with the end of a sentence from p{ref['page'] + 1} ({ref['sid']})")
    if cont:
        print(f"   >> last sentence continues on p{cont['page'] + 1}: '{cont['text'][:90]}' ({len(cont['rects'])} rects)")

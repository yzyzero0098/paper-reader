"""Dev tool: print what the layout engine extracts from PDFs.

Usage: python -X utf8 backend/scripts/probe_layout.py <pdf-or-glob> [max_pages]
"""
import glob
import sys
import warnings
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import fitz  # noqa: E402

from app import citations, pdf_engine  # noqa: E402

pattern = sys.argv[1] if len(sys.argv) > 1 else "*.pdf"
max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 6
for f in sorted(glob.glob(pattern)):
    doc = fitz.open(f)
    print("=" * 80)
    print(Path(f).name[:70], "pages", doc.page_count)
    print("title:", pdf_engine.extract_title(doc)[:80])
    rs = pdf_engine.find_references_start(doc)
    print("refs start:", rs)
    refs = citations.parse_references(pdf_engine.page_texts(doc))
    print("refs parsed:", len(refs), [(r["n"], r["raw"][:60]) for r in refs[:3]])
    for pno in range(min(doc.page_count, max_pages)):
        lay = pdf_engine.page_layout(doc, pno, rs, ref_count=len(refs))
        kinds = Counter(b["kind"] for b in lay["blocks"])
        figs = [(x["id"], x["kind"], x["caption"][:30]) for x in lay["figures"]]
        cites = [(c["text"], c["refs"]) for c in lay["citations"]][:5]
        print(f" p{pno}: blocks={dict(kinds)} figs={figs} cites={cites}")

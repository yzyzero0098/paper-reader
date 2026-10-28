"""Dev tool: inspect reference headings, superscript spans and bracket citations in a PDF."""
import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
import fitz  # noqa: E402

doc = fitz.open(sys.argv[1])
# 1) lines containing 'references'
for pno in range(doc.page_count):
    for ln in doc[pno].get_text("text").splitlines():
        if re.search(r"references|bibliography", ln, re.I) and len(ln) < 60:
            print(f"p{pno} heading-like line: {ln!r}")
# 2) superscript spans and bracket/paren numeric patterns on first 4 pages
for pno in range(min(4, doc.page_count)):
    page = doc[pno]
    sup, br, par = [], [], []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                if s["flags"] & 1 and s["text"].strip():
                    sup.append((s["text"], round(s["size"], 1)))
        text = " ".join("".join(s["text"] for s in ln["spans"]) for ln in b["lines"])
        br += re.findall(r"\[\d{1,3}[^\]]{0,20}\]", text)
        par += re.findall(r"\(\d{1,3}(?:\s*[-–,]\s*\d{1,3})*\)", text)
    print(f"p{pno} superscripts={sup[:12]} brackets={br[:8]} parens={par[:8]}")
    if br:
        print("   search_for", br[0], "->", len(page.search_for(br[0])))

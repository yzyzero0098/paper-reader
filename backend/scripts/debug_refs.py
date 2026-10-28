"""Dev tool: show the raw text around the reference heading as parse_references sees it."""
import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
import fitz  # noqa: E402

from app import citations, pdf_engine  # noqa: E402

doc = fitz.open(sys.argv[1])
texts = pdf_engine.page_texts(doc)
joined = "\n".join(texts)
for m in re.finditer(r"(?i)references", joined):
    s = max(0, m.start() - 80)
    print("---- match at", m.start(), repr(joined[s:m.end() + 300]))
print("heads:", [(h.start(), h.group(0)) for h in citations.REF_HEADING_RE.finditer(joined)])
refs = citations.parse_references(texts)
print("parsed", len(refs))
for r in refs[:5]:
    print(r["n"], r["raw"][:100])

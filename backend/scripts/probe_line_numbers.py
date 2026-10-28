"""Dev tool: report detected manuscript line-number columns for PDFs (to catch false positives).

Usage: python -X utf8 backend/scripts/probe_line_numbers.py <pdf> [<pdf> ...]
"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
import fitz  # noqa: E402

from app import pdf_engine  # noqa: E402

for f in sys.argv[1:]:
    doc = fitz.open(f)
    x = pdf_engine.doc_line_number_x(doc)
    n = sum(len(pdf_engine.line_number_spans(doc[p].get_text("dict")["blocks"], doc[p].rect.width, x))
            for p in range(doc.page_count))
    print(f"{Path(f).name[:60]:60s} column_x={x} dropped_spans={n}")

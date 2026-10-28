"""Dev tool: translate pages through the running server and print paragraph/sentence linking diagnostics.

Usage: python -X utf8 backend/scripts/check_translation.py <paper_id> <page_index> [<page_index> ...]
(uses http://127.0.0.1:8000 and the configured AI; costs tokens)
"""
import json
import re
import sys
import urllib.request

pid = sys.argv[1]
for p in map(int, sys.argv[2:]):
    with urllib.request.urlopen(f"http://127.0.0.1:8000/api/papers/{pid}/pages/{p}/translate?lang=ko", timeout=600) as r:
        units = json.load(r)
    sents = [s for u in units for s in u["sentences"]]
    stray = [s["t"] for s in sents if re.search(r"\s\d{1,3}$", s["t"] or "")]
    print(f"=== p{p + 1}: units={len(units)} sentences={len(sents)} translated={sum(1 for s in sents if s['t'])} "
          f"refs={sum(1 for s in sents if s.get('ref'))} conts={sum(1 for s in sents if s.get('cont'))} "
          f"trailing-number-suspects={len(stray)}")
    for u in units[:3]:
        print(f"   [{u['kind']}] {u['t'][:120]}")
    for s in sents:
        if s.get("ref"):
            print(f"   << ref to p{s['ref']['page'] + 1} {s['ref']['sid']}: '{s['text'][:70]}'")
        if s.get("cont"):
            print(f"   >> continues on p{s['cont']['page'] + 1}: '{s['text'][-90:]}'")
            print(f"      번역: '{s['t'][-110:]}'")
    for t in stray[:3]:
        print("   ? ", t[-60:])

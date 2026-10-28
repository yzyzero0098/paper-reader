"""Self-test for folders and the reading calendar, run against a throw-away data directory.

Usage: python -X utf8 backend/scripts/selftest_folders.py <some.pdf>
"""
import os
import sys
import tempfile
import warnings
from pathlib import Path

os.environ["PAPER_READER_DATA"] = tempfile.mkdtemp(prefix="paper_reader_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)
pdf = Path(sys.argv[1]).read_bytes()


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        sys.exit(1)


p1 = c.post("/api/papers", files={"file": ("a.pdf", pdf, "application/pdf")}).json()
fid = c.post("/api/folders", json={"name": "Proteomics"}).json()["id"]
fid2 = c.post("/api/folders", json={"name": "Methods"}).json()["id"]
ok(c.post("/api/folders", json={"name": "  "}).status_code == 400, "empty folder name rejected")

p2 = c.post("/api/papers", files={"file": ("b.pdf", pdf, "application/pdf")}, data={"folder_id": str(fid)}).json()
ok(p2["folder_id"] == fid, "upload directly into a folder")
ok(p1["folder_id"] is None, "upload without folder stays unfiled")

moved = c.patch(f"/api/papers/{p1['id']}", json={"folder_id": fid2}).json()
ok(moved["folder_id"] == fid2, "move paper to a folder")
ok(c.patch(f"/api/papers/{p1['id']}", json={"folder_id": 9999}).status_code == 404, "unknown folder rejected")
renamed = c.patch(f"/api/papers/{p1['id']}", json={"title": "New title"}).json()
ok(renamed["title"] == "New title" and renamed["folder_id"] == fid2, "rename keeps folder")

counts = {f["name"]: f["count"] for f in c.get("/api/folders").json()}
ok(counts == {"Proteomics": 1, "Methods": 1}, f"folder counts {counts}")

c.post(f"/api/papers/{p1['id']}/reading", json={"day": "2026-10-28", "seconds": 0, "page": 0})
c.post(f"/api/papers/{p1['id']}/reading", json={"day": "2026-10-28", "seconds": 15, "page": 2})
c.post(f"/api/papers/{p1['id']}/reading", json={"day": "2026-10-28", "seconds": 15, "page": 3})
c.post(f"/api/papers/{p2['id']}/reading", json={"day": "2026-10-28", "seconds": 60, "page": 1})
c.post(f"/api/papers/{p2['id']}/reading", json={"day": "2026-10-30", "seconds": 45, "page": 1})
ok(c.post(f"/api/papers/{p1['id']}/reading", json={"day": "bad", "seconds": 1}).status_code == 400, "bad day rejected")

cal = c.get("/api/reading/calendar", params={"month": "2026-10"}).json()
ok(sorted(cal["days"]) == ["2026-10-28", "2026-10-30"], f"calendar days {sorted(cal['days'])}")
d28 = {e["paper_id"]: e for e in cal["days"]["2026-10-28"]}
ok(d28[p1["id"]]["seconds"] == 30 and d28[p1["id"]]["folder_name"] == "Methods", "seconds accumulate, folder joined")
ok(cal["total_seconds"] == 30 + 60 + 45 and cal["papers"] == 2, f"month totals {cal['total_seconds']}s / {cal['papers']} papers")
ok(c.get("/api/reading/calendar", params={"month": "2026-11"}).json()["days"] == {}, "other month empty")
ok(c.get("/api/reading/calendar", params={"month": "x"}).status_code == 400, "bad month rejected")

last = {p["id"]: p for p in c.get("/api/papers").json()}
ok(last[p1["id"]]["last_page"] == 3 and last[p1["id"]]["last_read"], "last page and last_read stored")

c.delete(f"/api/folders/{fid}")
ok(c.get(f"/api/papers/{p2['id']}").json()["folder_id"] is None, "deleting a folder unfiles its papers")
ok(len(c.get("/api/papers").json()) == 2, "no paper deleted with the folder")

c.delete(f"/api/papers/{p1['id']}")
cal = c.get("/api/reading/calendar", params={"month": "2026-10"}).json()
ok(all(e["paper_id"] != p1["id"] for es in cal["days"].values() for e in es), "deleting a paper removes its reading log")
print("ALL PASSED")

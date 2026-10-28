"""SQLite storage: papers, cache, chats, highlights."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from .config import DB_FILE

_conn = sqlite3.connect(DB_FILE, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_lock = threading.Lock()

_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS papers (
        id TEXT PRIMARY KEY,
        title TEXT,
        filename TEXT,
        pages INTEGER,
        added_at REAL,
        meta TEXT
    );
    CREATE TABLE IF NOT EXISTS cache (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at REAL
    );
    CREATE TABLE IF NOT EXISTS chats (
        paper_id TEXT PRIMARY KEY,
        messages TEXT,
        updated_at REAL
    );
    CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        color TEXT,
        created_at REAL
    );
    CREATE TABLE IF NOT EXISTS reading (
        paper_id TEXT,
        day TEXT,
        seconds INTEGER DEFAULT 0,
        last_ts REAL,
        PRIMARY KEY (paper_id, day)
    );
    CREATE TABLE IF NOT EXISTS usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL,
        paper_id TEXT,
        provider TEXT,
        model TEXT,
        kind TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER
    );
    CREATE TABLE IF NOT EXISTS highlights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id TEXT,
        page INTEGER,
        rects TEXT,
        color TEXT,
        text TEXT,
        note TEXT,
        created_at REAL
    );
    """
)
_conn.commit()

# lightweight migration: columns added after the first release
_paper_cols = {r["name"] for r in _conn.execute("PRAGMA table_info(papers)").fetchall()}
for _col, _ddl in (("folder_id", "INTEGER"), ("last_page", "INTEGER DEFAULT 0"), ("last_read", "REAL")):
    if _col not in _paper_cols:
        _conn.execute(f"ALTER TABLE papers ADD COLUMN {_col} {_ddl}")
_conn.commit()


def _rows(q: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(q, args).fetchall()]


def _exec(q: str, args: tuple = ()) -> int:
    with _lock:
        cur = _conn.execute(q, args)
        _conn.commit()
        return cur.lastrowid or 0


# ---- papers -------------------------------------------------------------
def add_paper(pid: str, title: str, filename: str, pages: int, meta: dict) -> None:
    _exec(
        "INSERT INTO papers (id,title,filename,pages,added_at,meta) VALUES (?,?,?,?,?,?)",
        (pid, title, filename, pages, time.time(), json.dumps(meta, ensure_ascii=False)),
    )


def list_papers() -> list[dict]:
    rows = _rows("SELECT * FROM papers ORDER BY added_at DESC")
    for r in rows:
        r["meta"] = json.loads(r.get("meta") or "{}")
    return rows


def get_paper(pid: str) -> dict | None:
    rows = _rows("SELECT * FROM papers WHERE id=?", (pid,))
    if not rows:
        return None
    r = rows[0]
    r["meta"] = json.loads(r.get("meta") or "{}")
    return r


def update_paper_title(pid: str, title: str) -> None:
    _exec("UPDATE papers SET title=? WHERE id=?", (title, pid))


def set_paper_folder(pid: str, folder_id: int | None) -> None:
    _exec("UPDATE papers SET folder_id=? WHERE id=?", (folder_id, pid))


# ---- folders ------------------------------------------------------------
FOLDER_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#84cc16", "#8b5cf6"]


def list_folders() -> list[dict]:
    return _rows(
        "SELECT f.id, f.name, f.color, f.created_at, COUNT(p.id) AS count "
        "FROM folders f LEFT JOIN papers p ON p.folder_id=f.id GROUP BY f.id ORDER BY f.name COLLATE NOCASE"
    )


def add_folder(name: str, color: str | None = None) -> int:
    if not color:
        color = FOLDER_COLORS[len(_rows("SELECT id FROM folders")) % len(FOLDER_COLORS)]
    return _exec("INSERT INTO folders (name,color,created_at) VALUES (?,?,?)", (name, color, time.time()))


def update_folder(fid: int, name: str | None, color: str | None) -> None:
    if name is not None:
        _exec("UPDATE folders SET name=? WHERE id=?", (name, fid))
    if color is not None:
        _exec("UPDATE folders SET color=? WHERE id=?", (color, fid))


def delete_folder(fid: int) -> None:
    _exec("UPDATE papers SET folder_id=NULL WHERE folder_id=?", (fid,))
    _exec("DELETE FROM folders WHERE id=?", (fid,))


# ---- reading log --------------------------------------------------------
def log_reading(pid: str, day: str, seconds: int, page: int | None) -> None:
    now = time.time()
    _exec(
        "INSERT INTO reading (paper_id,day,seconds,last_ts) VALUES (?,?,?,?) "
        "ON CONFLICT(paper_id,day) DO UPDATE SET seconds=seconds+excluded.seconds, last_ts=excluded.last_ts",
        (pid, day, max(0, int(seconds)), now),
    )
    if page is not None:
        _exec("UPDATE papers SET last_page=?, last_read=? WHERE id=?", (int(page), now, pid))
    else:
        _exec("UPDATE papers SET last_read=? WHERE id=?", (now, pid))


def reading_calendar(month: str) -> dict:
    """month = 'YYYY-MM'. Returns {day: [{paper_id,title,seconds,folder_id,folder_name,folder_color}]}."""
    rows = _rows(
        "SELECT r.day, r.paper_id, r.seconds, r.last_ts, p.title, p.folder_id, f.name AS folder_name, f.color AS folder_color "
        "FROM reading r JOIN papers p ON p.id=r.paper_id LEFT JOIN folders f ON f.id=p.folder_id "
        "WHERE r.day LIKE ? ORDER BY r.day, r.last_ts",
        (month + "-%",),
    )
    days: dict[str, list] = {}
    for r in rows:
        days.setdefault(r["day"], []).append({k: r[k] for k in ("paper_id", "title", "seconds", "folder_id", "folder_name", "folder_color")})
    total = sum(r["seconds"] for r in rows)
    return {"month": month, "days": days, "total_seconds": total, "papers": len({r["paper_id"] for r in rows})}


def delete_paper(pid: str) -> None:
    _exec("DELETE FROM papers WHERE id=?", (pid,))
    _exec("DELETE FROM reading WHERE paper_id=?", (pid,))
    _exec("DELETE FROM chats WHERE paper_id=?", (pid,))
    _exec("DELETE FROM highlights WHERE paper_id=?", (pid,))
    _exec("DELETE FROM cache WHERE key LIKE ?", (f"%:{pid}:%",))


# ---- cache --------------------------------------------------------------
def cache_get(key: str):
    rows = _rows("SELECT value FROM cache WHERE key=?", (key,))
    return json.loads(rows[0]["value"]) if rows else None


def cache_set(key: str, value) -> None:
    _exec(
        "INSERT OR REPLACE INTO cache (key,value,updated_at) VALUES (?,?,?)",
        (key, json.dumps(value, ensure_ascii=False), time.time()),
    )


def cache_delete(key: str) -> None:
    _exec("DELETE FROM cache WHERE key=?", (key,))


# ---- chats --------------------------------------------------------------
def get_chat(pid: str) -> list:
    rows = _rows("SELECT messages FROM chats WHERE paper_id=?", (pid,))
    return json.loads(rows[0]["messages"]) if rows else []


def save_chat(pid: str, messages: list) -> None:
    _exec(
        "INSERT OR REPLACE INTO chats (paper_id,messages,updated_at) VALUES (?,?,?)",
        (pid, json.dumps(messages, ensure_ascii=False), time.time()),
    )


# ---- usage --------------------------------------------------------------
def add_usage(paper_id: str, provider: str, model: str, kind: str, input_tokens: int, output_tokens: int) -> None:
    _exec(
        "INSERT INTO usage (ts,paper_id,provider,model,kind,input_tokens,output_tokens) VALUES (?,?,?,?,?,?,?)",
        (time.time(), paper_id, provider, model, kind, int(input_tokens or 0), int(output_tokens or 0)),
    )


def usage_summary(paper_id: str | None = None) -> dict:
    import datetime as _dt
    day_start = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def agg(where: str, args: tuple) -> dict:
        rows = _rows(f"SELECT COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o, COUNT(*) n FROM usage WHERE {where}", args)
        r = rows[0]
        return {"input": r["i"], "output": r["o"], "calls": r["n"]}

    out = {
        "today": agg("ts>=?", (day_start,)),
        "total": agg("1=1", ()),
        "by_provider_today": [dict(r) for r in _rows(
            "SELECT provider, model, SUM(input_tokens) input, SUM(output_tokens) output, COUNT(*) calls "
            "FROM usage WHERE ts>=? GROUP BY provider, model ORDER BY input+output DESC", (day_start,))],
        "by_kind_today": [dict(r) for r in _rows(
            "SELECT kind, SUM(input_tokens) input, SUM(output_tokens) output, COUNT(*) calls "
            "FROM usage WHERE ts>=? GROUP BY kind ORDER BY input+output DESC", (day_start,))],
    }
    if paper_id:
        out["paper"] = agg("paper_id=?", (paper_id,))
    return out


# ---- highlights ---------------------------------------------------------
def list_highlights(pid: str) -> list[dict]:
    rows = _rows("SELECT * FROM highlights WHERE paper_id=? ORDER BY page, id", (pid,))
    for r in rows:
        r["rects"] = json.loads(r["rects"])
    return rows


def add_highlight(pid: str, page: int, rects: list, color: str, text: str, note: str) -> int:
    return _exec(
        "INSERT INTO highlights (paper_id,page,rects,color,text,note,created_at) VALUES (?,?,?,?,?,?,?)",
        (pid, page, json.dumps(rects), color, text, note, time.time()),
    )


def update_highlight(hid: int, note: str | None, color: str | None) -> None:
    if note is not None:
        _exec("UPDATE highlights SET note=? WHERE id=?", (note, hid))
    if color is not None:
        _exec("UPDATE highlights SET color=? WHERE id=?", (color, hid))


def delete_highlight(hid: int) -> None:
    _exec("DELETE FROM highlights WHERE id=?", (hid,))

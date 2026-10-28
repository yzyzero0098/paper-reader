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


def delete_paper(pid: str) -> None:
    _exec("DELETE FROM papers WHERE id=?", (pid,))
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

"""
SQLite storage for the Vidora dashboard.

All pipeline results are stored here. The schema mirrors the JSON that
vidora_scout_final.analyse() returns, flattened for easy filtering.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path("C:/vidora/vidora.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    analysed_at TEXT,
    lead_grade TEXT,
    overall_score REAL,
    priority_flag INTEGER DEFAULT 0,
    screenshot_count INTEGER DEFAULT 0,
    upgrade_potential TEXT,
    estimated_audience_size TEXT,
    lighting INTEGER,
    composition INTEGER,
    editing_colour INTEGER,
    brand_consistency INTEGER,
    content_production INTEGER,
    overall INTEGER,
    weaknesses TEXT,            -- JSON array
    strengths TEXT,             -- JSON array
    personalised_pitch TEXT,
    sales_notes TEXT,
    business_intent_score INTEGER,
    business_type TEXT,
    location_match INTEGER DEFAULT 0,
    location_signals TEXT,      -- JSON array
    selling_signals TEXT,       -- JSON array
    status TEXT DEFAULT 'new',  -- new / contacted / qualified / closed / dead
    notes TEXT,
    audit_path TEXT,
    business_name TEXT,
    maps_address TEXT,
    maps_phone TEXT,
    maps_website TEXT,
    maps_rating TEXT,
    maps_review_count TEXT,
    maps_url TEXT,
    maps_place_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_leads_grade ON leads(lead_grade);
CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads(priority_flag);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT DEFAULT 'running',   -- running / success / failed / stopped
    leads_target INTEGER,
    leads_found INTEGER DEFAULT 0,
    location TEXT,
    log TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
        # Seed default settings
        defaults = {
            "anthropic_api_key": "",
            "instagram_username": "",
            "default_location": "manchester",
            "default_leads_per_run": "10",
            "company_name": "Vidora",
            "company_tagline": "AI lead generation for media production",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_settings() -> dict:
    with connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_setting(key: str, default: str = "") -> str:
    with connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def update_settings(updates: dict) -> None:
    with connection() as conn:
        for k, v in updates.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, v),
            )


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def _to_json(value) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def upsert_lead_from_pipeline(result: dict) -> int:
    """Insert a lead from the vidora_scout_final JSON result.

    Returns the row id. If the username already exists, updates the record.
    """
    scores = result.get("scores", {}) or {}
    row = {
        "username": result.get("username"),
        "analysed_at": result.get("analysed_at")
        or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "lead_grade": result.get("lead_grade"),
        "overall_score": result.get("overall_score"),
        "priority_flag": 1 if result.get("priority_flag") else 0,
        "screenshot_count": result.get("screenshot_count") or 0,
        "upgrade_potential": result.get("upgrade_potential"),
        "estimated_audience_size": result.get("estimated_audience_size"),
        "lighting": scores.get("lighting"),
        "composition": scores.get("composition"),
        "editing_colour": scores.get("editing_colour"),
        "brand_consistency": scores.get("brand_consistency"),
        "content_production": scores.get("content_production"),
        "overall": scores.get("overall"),
        "weaknesses": _to_json(result.get("top_weaknesses", [])),
        "strengths": _to_json(result.get("strengths", [])),
        "personalised_pitch": result.get("personalised_pitch"),
        "sales_notes": result.get("sales_notes"),
        "business_intent_score": result.get("business_intent_score"),
        "business_type": result.get("business_type"),
        "location_match": 1 if result.get("location_match") else 0,
        "location_signals": _to_json(result.get("location_signals", [])),
        "selling_signals": _to_json(result.get("selling_signals", [])),
        "business_name": result.get("business_name"),
        "maps_address": result.get("maps_address"),
        "maps_phone": result.get("maps_phone"),
        "maps_website": result.get("maps_website"),
        "maps_rating": str(result["maps_rating"]) if result.get("maps_rating") is not None else None,
        "maps_review_count": str(result["maps_review_count"]) if result.get("maps_review_count") is not None else None,
        "maps_url": result.get("maps_url"),
        "maps_place_id": result.get("maps_place_id"),
    }

    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    update_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "username")

    sql = (
        f"INSERT INTO leads ({','.join(cols)}, updated_at) "
        f"VALUES ({placeholders}, CURRENT_TIMESTAMP) "
        f"ON CONFLICT(username) DO UPDATE SET {update_clause}, "
        f"updated_at = CURRENT_TIMESTAMP"
    )
    with connection() as conn:
        conn.execute(sql, [row[c] for c in cols])
        lead_id = conn.execute(
            "SELECT id FROM leads WHERE username = ?", (row["username"],)
        ).fetchone()["id"]
    return lead_id


def list_leads(
    grade: str | None = None,
    priority_only: bool = False,
    status: str | None = None,
    business_type: str | None = None,
    search: str | None = None,
    order_by: str = "overall_score DESC",
    limit: int | None = None,
) -> list[dict]:
    where = []
    params: list = []
    if grade:
        where.append("lead_grade = ?")
        params.append(grade.upper())
    if priority_only:
        where.append("priority_flag = 1")
    if status:
        where.append("status = ?")
        params.append(status)
    if business_type:
        where.append("business_type = ?")
        params.append(business_type)
    if search:
        where.append("(username LIKE ? OR business_type LIKE ?)")
        q = f"%{search}%"
        params.extend([q, q])

    sql = "SELECT * FROM leads"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Whitelist order_by to avoid injection.
    allowed = {
        "overall_score DESC",
        "overall_score ASC",
        "analysed_at DESC",
        "lead_grade ASC",
        "business_intent_score DESC",
        "username ASC",
    }
    sql += f" ORDER BY {order_by if order_by in allowed else 'overall_score DESC'}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_lead(r) for r in rows]


def get_lead(lead_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(row) if row else None


def get_lead_by_username(username: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE username = ?", (username,)
        ).fetchone()
    return _row_to_lead(row) if row else None


def update_lead_fields(lead_id: int, updates: dict) -> None:
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    params = list(updates.values()) + [lead_id]
    with connection() as conn:
        conn.execute(
            f"UPDATE leads SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )


def delete_lead(lead_id: int) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))


def _row_to_lead(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("weaknesses", "strengths", "location_signals", "selling_signals"):
        raw = d.get(field) or "[]"
        try:
            d[field] = json.loads(raw)
        except (TypeError, ValueError):
            d[field] = []
    d["priority_flag"] = bool(d.get("priority_flag"))
    d["location_match"] = bool(d.get("location_match"))
    return d


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

def dashboard_stats() -> dict:
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
        grades = {
            r["lead_grade"] or "?": r["n"]
            for r in conn.execute(
                "SELECT lead_grade, COUNT(*) AS n FROM leads GROUP BY lead_grade"
            ).fetchall()
        }
        priority = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE priority_flag = 1"
        ).fetchone()["n"]
        avg_score_row = conn.execute(
            "SELECT AVG(overall_score) AS s FROM leads"
        ).fetchone()
        avg_score = avg_score_row["s"] or 0
        contacted = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE status != 'new'"
        ).fetchone()["n"]
        location_matches = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE location_match = 1"
        ).fetchone()["n"]
        latest_run = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "total": total,
        "grades": {g: grades.get(g, 0) for g in ("A", "B", "C", "D")},
        "priority": priority,
        "avg_score": round(avg_score or 0, 2),
        "contacted": contacted,
        "location_matches": location_matches,
        "latest_run": dict(latest_run) if latest_run else None,
    }


def business_types() -> list[str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT business_type FROM leads "
            "WHERE business_type IS NOT NULL AND business_type != '' "
            "ORDER BY business_type"
        ).fetchall()
    return [r["business_type"] for r in rows]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def create_run(leads_target: int, location: str | None) -> int:
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO runs (leads_target, location) VALUES (?, ?)",
            (leads_target, location),
        )
        return cur.lastrowid


def append_run_log(run_id: int, line: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE runs SET log = COALESCE(log,'') || ? WHERE id = ?",
            (line + "\n", run_id),
        )


def finish_run(run_id: int, status: str, leads_found: int) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE runs SET status = ?, leads_found = ?, "
            "finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, leads_found, run_id),
        )


def get_run(run_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(limit: int = 20) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def active_run() -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None

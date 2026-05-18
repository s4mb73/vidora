"""Vidora → Innovite CRM bridge.

After a lead finishes Vidora's pipeline (`upsert_lead_from_pipeline`),
we push it to the Innovite CRM at /api/vidora/lead so the unified
dashboard can show it alongside Innovite's other clients' leads.

Gated by env vars — install this code and the runner keeps behaving
exactly as today. The bridge only activates when both are set:

    VIDORA_BRIDGE_SECRET   shared secret matching Innovite-side
    INNOVITE_API_URL       e.g. https://crm.innovite.io/api/vidora/lead

If either is missing → push is a no-op. If the POST fails for any
reason (network down, 5xx, timeout) → the lead is enqueued in a local
SQLite table `pending_pushes` and retried by `drain_pending()` on the
next daily_run.

The local lead insert ALWAYS succeeds first. The bridge runs after,
wrapped in try/except — Vidora's existing flow never breaks because
the VPS is unreachable.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import requests

from dashboard import db

logger = logging.getLogger("vidora.bridge")

_TIMEOUT_SECONDS = float(os.environ.get("VIDORA_BRIDGE_TIMEOUT") or "20")
_MAX_RETRY_ATTEMPTS = int(os.environ.get("VIDORA_BRIDGE_MAX_RETRIES") or "10")

_PENDING_PUSHES_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_pushes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    enqueued_at TEXT DEFAULT CURRENT_TIMESTAMP,
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    last_attempt_at TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pending_pushes_lead ON pending_pushes(lead_id);
"""


def ensure_table() -> None:
    """Create the pending_pushes table if missing. Safe to call repeatedly."""
    with db.connection() as conn:
        conn.executescript(_PENDING_PUSHES_SCHEMA)


def _enabled() -> bool:
    """Both env vars must be set for the bridge to fire."""
    return bool(os.environ.get("VIDORA_BRIDGE_SECRET")
                and os.environ.get("INNOVITE_API_URL"))


def _build_payload(lead_row: dict) -> dict:
    """Construct the JSON body Innovite's /api/vidora/lead expects."""
    payload = dict(lead_row)
    for k in ("id", "created_at", "updated_at"):
        payload.pop(k, None)
    return payload


def _do_push(payload: dict, pdf_path: str | None) -> tuple[bool, str]:
    """Single attempt. Returns (ok, error_message)."""
    url = os.environ["INNOVITE_API_URL"]
    secret = os.environ["VIDORA_BRIDGE_SECRET"]

    files = {"lead": (None, json.dumps(payload), "application/json")}
    fh = None
    if pdf_path and os.path.exists(pdf_path):
        try:
            fh = open(pdf_path, "rb")
            files["pdf"] = (os.path.basename(pdf_path), fh, "application/pdf")
        except OSError as exc:
            return False, f"pdf open failed: {exc}"
    try:
        resp = requests.post(
            url,
            headers={"X-Vidora-Key": secret},
            files=files,
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return False, f"network: {type(exc).__name__}: {exc}"
    finally:
        if fh is not None:
            fh.close()

    if 200 <= resp.status_code < 300:
        return True, ""
    return False, f"http {resp.status_code}: {resp.text[:200]}"


def push_lead(lead_id: int) -> None:
    """Push the named local lead to Innovite. If anything fails, queue
    for retry. NEVER raises."""
    if not _enabled():
        return
    try:
        ensure_table()
        lead = db.get_lead(lead_id)
        if not lead:
            logger.warning("bridge.push_lead: lead %s not found", lead_id)
            return
        payload = _build_payload(lead)
        pdf_path = lead.get("audit_path") or None
        ok, err = _do_push(payload, pdf_path)
        if ok:
            _mark_sent(lead_id)
            logger.info("bridge → innovite OK lead=%s username=%s",
                        lead_id, lead.get("username"))
        else:
            _enqueue(lead_id, err)
            logger.warning("bridge → innovite FAIL lead=%s err=%s",
                           lead_id, err[:120])
    except Exception:
        logger.exception("bridge.push_lead crashed for lead=%s — swallowed", lead_id)


def _enqueue(lead_id: int, error: str) -> None:
    """Add or update the pending row for this lead."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, attempts FROM pending_pushes WHERE lead_id = ?",
            (lead_id,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE pending_pushes SET attempts = attempts + 1, "
                "last_error = ?, last_attempt_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (error[:500], row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO pending_pushes (lead_id, attempts, last_error, "
                "last_attempt_at) VALUES (?, 1, ?, CURRENT_TIMESTAMP)",
                (lead_id, error[:500]),
            )


def _mark_sent(lead_id: int) -> None:
    """Remove any pending entry for this lead — push succeeded."""
    with db.connection() as conn:
        conn.execute("DELETE FROM pending_pushes WHERE lead_id = ?", (lead_id,))


def drain_pending(max_per_run: int = 50) -> dict:
    """Re-attempt every pending push."""
    if not _enabled():
        return {"enabled": False, "attempted": 0, "ok": 0, "still_pending": 0, "gave_up": 0}

    ensure_table()
    counters = {"enabled": True, "attempted": 0, "ok": 0,
                "still_pending": 0, "gave_up": 0}

    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, lead_id, attempts FROM pending_pushes "
            "ORDER BY id LIMIT ?",
            (max_per_run,),
        ).fetchall()

    for pending in rows:
        counters["attempted"] += 1
        if pending["attempts"] >= _MAX_RETRY_ATTEMPTS:
            counters["gave_up"] += 1
        lead = db.get_lead(pending["lead_id"])
        if not lead:
            with db.connection() as conn:
                conn.execute("DELETE FROM pending_pushes WHERE id = ?", (pending["id"],))
            continue
        payload = _build_payload(lead)
        ok, err = _do_push(payload, lead.get("audit_path"))
        if ok:
            _mark_sent(pending["lead_id"])
            counters["ok"] += 1
        else:
            _enqueue(pending["lead_id"], err)
            counters["still_pending"] += 1
        time.sleep(0.2)

    logger.info("bridge drain: %s", counters)
    return counters


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not _enabled():
        print("Bridge disabled — set VIDORA_BRIDGE_SECRET + INNOVITE_API_URL.")
        raise SystemExit(0)
    result = drain_pending()
    print(json.dumps(result, indent=2))
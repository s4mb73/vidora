"""
Background runner that drives vidora_scout_final.py as a subprocess.

The scout script writes a leads CSV on completion. This module imports
that CSV into SQLite so the dashboard shows results immediately after
each run. Log lines are streamed from the subprocess stdout in real time.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from . import db
from .pdf_audit import generate_audit

ROOT = Path(__file__).resolve().parent.parent

_lock = threading.Lock()
_current_thread: threading.Thread | None = None

# Full path to the Python interpreter running this server.
_PYTHON = sys.executable


class RunLogger:
    """Captures stdout/stderr lines and appends them to the run log in DB."""

    def __init__(self, run_id: int):
        self.run_id = run_id
        self._buf = ""

    def write(self, chunk: str) -> int:
        if not chunk:
            return 0
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                db.append_run_log(self.run_id, line.rstrip())
        return len(chunk)

    def flush(self) -> None:
        if self._buf.strip():
            db.append_run_log(self.run_id, self._buf.rstrip())
            self._buf = ""


def is_running() -> bool:
    global _current_thread
    return _current_thread is not None and _current_thread.is_alive()


def start_run(
    leads_target: int,
    location: str | None,
    api_key: str,
    source: str = "maps",
    query: str | None = None,
) -> int | None:
    """Kick off the pipeline in a background thread. Returns the run id or None."""
    global _current_thread
    with _lock:
        if is_running():
            return None
        run_id = db.create_run(leads_target, location)
        _current_thread = threading.Thread(
            target=_run_pipeline,
            args=(run_id, leads_target, location, api_key, source, query),
            daemon=True,
            name=f"vidora-run-{run_id}",
        )
        _current_thread.start()
    return run_id


def _run_pipeline(
    run_id: int,
    leads_target: int,
    location: str | None,
    api_key: str,
    source: str,
    query: str | None,
):
    logger = RunLogger(run_id)
    found = 0
    status = "success"

    try:
        if not api_key:
            raise RuntimeError("Anthropic API key missing. Add it in Settings.")

        output_csv = ROOT / f"run_{run_id}_leads.csv"

        cmd = [
            _PYTHON,
            str(ROOT / "vidora_scout_final.py"),
            "--source", source,
            "--leads", str(leads_target),
            "--output", str(output_csv),
            "--audits-dir", "C:/vidora/audits",
        ]
        if location:
            cmd += ["--location", location]
        if source == "maps" and query:
            cmd += ["--query", query]

        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = api_key

        logger.write(f"[run {run_id}] $ {' '.join(cmd)}\n\n")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        for line in proc.stdout:
            logger.write(line)

        proc.wait()

        if proc.returncode != 0:
            status = "failed"
            logger.write(f"\nProcess exited with code {proc.returncode}.\n")
        else:
            if output_csv.exists():
                found = import_csv(output_csv)
                logger.write(f"\nImported {found} lead(s) into the database.\n")
                try:
                    output_csv.unlink()
                except Exception:
                    pass
            else:
                logger.write("\nNo output CSV was produced.\n")

    except Exception as exc:
        status = "failed"
        logger.write(f"ERROR: {exc}\n{traceback.format_exc()}")
    finally:
        logger.flush()
        db.finish_run(run_id, status, found)


# ---------------------------------------------------------------------------
# CSV import — handles both vidora_scout_final format and master_leads format
# ---------------------------------------------------------------------------

def import_csv(path: Path) -> int:
    """Import a leads CSV into SQLite. Returns the number of rows imported.

    Handles two formats:
    - vidora_scout_final output: username, lighting, composition, etc.
    - master_leads format: instagram_handle, fw_score_1..5, name, etc.
    """
    count = 0
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Username — new format uses 'username', old uses 'instagram_handle'
            username = (row.get("username") or row.get("instagram_handle") or "").strip()
            if not username:
                continue

            weaknesses = [row.get(k, "") for k in ("weakness_1", "weakness_2", "weakness_3")]
            weaknesses = [w for w in weaknesses if w]

            # Strengths — new format uses strength_1/2, old uses transformation_1/2/3
            strengths = [row.get(k, "") for k in ("strength_1", "strength_2",
                                                    "transformation_1", "transformation_2")]
            strengths = [s for s in strengths if s]

            # Scores — new format uses named columns, old uses fw_score_1..5
            def _score(new_col, fw_col):
                return _int(row.get(new_col) or row.get(fw_col))

            scores = {
                "lighting":          _score("lighting",          "fw_score_1"),
                "composition":       _score("composition",       "fw_score_2"),
                "editing_colour":    _score("editing_colour",    "fw_score_3"),
                "brand_consistency": _score("brand_consistency", "fw_score_4"),
                "content_production":_score("content_production","fw_score_5"),
                "overall":           _int(row.get("overall")),
            }

            # Selling signals — may be semicolon list or a single long string
            raw_selling = row.get("selling_signals") or row.get("selling_signals", "")
            selling_signals = _split(raw_selling) if raw_selling else []

            result = {
                "username":               username,
                "analysed_at":            row.get("analysed_at"),
                "lead_grade":             row.get("lead_grade"),
                "overall_score":          _float(row.get("overall_score")),
                "priority_flag":          (row.get("priority_flag") or "").lower()
                                          in ("true", "1", "yes"),
                "screenshot_count":       _int(row.get("screenshot_count")),
                "upgrade_potential":      row.get("upgrade_potential"),
                "estimated_audience_size":row.get("estimated_audience_size"),
                "scores":                 scores,
                "top_weaknesses":         weaknesses,
                "strengths":              strengths,
                "personalised_pitch":     row.get("personalised_pitch"),
                "sales_notes":            row.get("sales_notes"),
                "business_intent_score":  _int(row.get("business_intent_score")),
                "business_type":          row.get("business_type"),
                "location_match":         (row.get("location_match") or "").lower()
                                          in ("true", "1", "yes"),
                "location_signals":       _split(row.get("location_signals")),
                "selling_signals":        selling_signals,
                # Maps metadata — new format OR master_leads column names
                "business_name":     row.get("business_name") or row.get("name"),
                "maps_address":      row.get("maps_address") or row.get("address"),
                "maps_phone":        row.get("maps_phone") or row.get("phone"),
                "maps_website":      row.get("maps_website") or row.get("website"),
                "maps_rating":       row.get("maps_rating") or row.get("google_rating"),
                "maps_review_count": row.get("maps_review_count") or row.get("review_count"),
                "maps_url":          row.get("maps_url"),
                "maps_place_id":     row.get("maps_place_id") or row.get("place_id"),
            }

            lead_id = db.upsert_lead_from_pipeline(result)

            # Resolve audit PDF path
            audit_path = (
                row.get("pdf_report")
                or row.get("audit_path")
                or _find_audit_pdf(username)
            )
            if audit_path and Path(audit_path).exists():
                db.update_lead_fields(lead_id, {"audit_path": str(audit_path)})
            else:
                # Try to generate a PDF on the fly
                lead = db.get_lead(lead_id)
                if lead:
                    try:
                        out_dir = Path("C:/vidora/audits")
                        out_dir.mkdir(parents=True, exist_ok=True)
                        company = db.get_setting("company_name", "Vidora")
                        pdf_path = generate_audit(lead, out_dir, company_name=company)
                        db.update_lead_fields(lead_id, {"audit_path": str(pdf_path)})
                    except Exception:
                        pass

            count += 1
    return count


def _find_audit_pdf(username: str) -> str | None:
    """Look for an existing PDF in C:/vidora/audits for this username."""
    audits_dir = Path("C:/vidora/audits")
    if not audits_dir.exists():
        return None
    for pattern in [f"{username}.pdf", f"*{username}*.pdf", f"*{username.replace('_', ' ')}*.pdf"]:
        matches = list(audits_dir.glob(pattern))
        if matches:
            return str(matches[0])
    return None


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _split(v):
    if not v:
        return []
    return [s.strip() for s in v.split(";") if s.strip()]

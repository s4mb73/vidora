"""
Background runner that drives the existing vidora_scout_final pipeline.

The scout script is a CLI that prints progress and writes a CSV when it
finishes. We reuse its modules directly instead of shelling out, so we
can persist each lead to SQLite the moment it is analysed and stream log
lines back to the runs table.

If the pipeline cannot start (e.g. missing Multilogin on this machine),
the failure is captured in the run log rather than crashing the web UI.
"""

from __future__ import annotations

import io
import sys
import threading
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from . import db
from .pdf_audit import generate_audit

ROOT = Path(__file__).resolve().parent.parent

# Add the scout directory to the import path so we can reuse the pipeline
# functions directly instead of fragile subprocess parsing.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_lock = threading.Lock()
_current_thread: threading.Thread | None = None


class RunLogger:
    """Captures stdout/stderr and appends each line to the run log."""

    def __init__(self, run_id: int):
        self.run_id = run_id
        self._buf = ""

    def reconfigure(self, *args, **kwargs) -> None:
        """No-op: vidora_scout_final calls sys.stdout.reconfigure() at import time."""
        pass

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


def start_run(leads_target: int, location: str | None, api_key: str) -> int | None:
    """Kick off the pipeline in a background thread. Returns the run id
    or None if another run is already active."""
    global _current_thread
    with _lock:
        if is_running():
            return None
        run_id = db.create_run(leads_target, location)
        _current_thread = threading.Thread(
            target=_run_pipeline,
            args=(run_id, leads_target, location, api_key),
            daemon=True,
            name=f"vidora-run-{run_id}",
        )
        _current_thread.start()
    return run_id


def _run_pipeline(run_id: int, leads_target: int, location: str | None, api_key: str):
    logger = RunLogger(run_id)
    found = 0
    status = "success"
    try:
        if not api_key:
            raise RuntimeError(
                "Anthropic API key missing. Add it in Settings before running."
            )
        with redirect_stdout(logger), redirect_stderr(logger):
            print(f"[run {run_id}] target={leads_target} location={location or '-'}")

            try:
                import vidora_scout_final as scout  # noqa: WPS433 (runtime import by design)
            except Exception as exc:  # pragma: no cover
                raise RuntimeError(
                    f"Could not import vidora_scout_final: {exc}. "
                    "Make sure the scout scripts sit next to the dashboard folder."
                ) from exc

            import anthropic

            claude = anthropic.Anthropic(api_key=api_key)

            print("Authenticating Multilogin...")
            token = scout.signin()
            port = scout.start_profile(token)
            time.sleep(3)

            driver = None
            try:
                driver = scout.connect_driver(port)
                scout.ensure_logged_in(driver)
                usernames = scout.collect_usernames(
                    driver, limit=leads_target, location=location
                )
                print(f"Collected {len(usernames)} usernames.")
                screenshots_dir = Path("C:/vidora/screenshots")
                screenshots_dir.mkdir(parents=True, exist_ok=True)

                for i, username in enumerate(usernames, 1):
                    print(f"[{i}/{len(usernames)}] @{username}")
                    shots = scout.screenshot_creator(driver, username, screenshots_dir)
                    if not shots:
                        continue
                    try:
                        result = scout.analyse(
                            username, shots, claude, location=location
                        )
                    except Exception as analyse_err:  # noqa: BLE001
                        print(f"    analysis error: {analyse_err}")
                        continue
                    if result:
                        _persist_lead(result)
                        found += 1
                        print(
                            f"    saved @{username} "
                            f"grade={result.get('lead_grade')} "
                            f"score={result.get('overall_score')}"
                        )
                    time.sleep(2)
            finally:
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                try:
                    scout.stop_profile(token)
                except Exception:
                    pass

            print(f"Run finished. {found} leads persisted.")
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        logger.write(f"ERROR: {exc}\n")
        logger.write(traceback.format_exc())
    finally:
        logger.flush()
        db.finish_run(run_id, status, found)


def _persist_lead(result: dict) -> None:
    """Store a single analysed lead, then (try to) render its PDF audit."""
    lead_id = db.upsert_lead_from_pipeline(result)
    lead = db.get_lead(lead_id)
    if lead is None:
        return
    try:
        out_dir = Path(__file__).resolve().parent / "data" / "audits"
        company = db.get_setting("company_name", "Vidora")
        path = generate_audit(lead, out_dir, company_name=company)
        db.update_lead_fields(lead_id, {"audit_path": str(path)})
    except Exception as exc:  # noqa: BLE001
        # PDF generation should never fail the run.
        print(f"    PDF audit failed for @{lead['username']}: {exc}")


# ---------------------------------------------------------------------------
# CSV import (useful for loading existing leads.csv files into the DB)
# ---------------------------------------------------------------------------

def import_csv(path: Path) -> int:
    """Import a leads.csv file produced by vidora_scout_final and return
    the number of leads imported."""
    import csv

    count = 0
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            weaknesses = [
                row.get(k, "") for k in ("weakness_1", "weakness_2", "weakness_3")
            ]
            weaknesses = [w for w in weaknesses if w]
            strengths = [row.get(k, "") for k in ("strength_1", "strength_2")]
            strengths = [s for s in strengths if s]

            result = {
                "username": row.get("username"),
                "analysed_at": row.get("analysed_at"),
                "lead_grade": row.get("lead_grade"),
                "overall_score": _float(row.get("overall_score")),
                "priority_flag": (row.get("priority_flag") or "").lower()
                in ("true", "1", "yes"),
                "screenshot_count": _int(row.get("screenshot_count")),
                "upgrade_potential": row.get("upgrade_potential"),
                "estimated_audience_size": row.get("estimated_audience_size"),
                "scores": {
                    "lighting": _int(row.get("lighting")),
                    "composition": _int(row.get("composition")),
                    "editing_colour": _int(row.get("editing_colour")),
                    "brand_consistency": _int(row.get("brand_consistency")),
                    "content_production": _int(row.get("content_production")),
                    "overall": _int(row.get("overall")),
                },
                "top_weaknesses": weaknesses,
                "strengths": strengths,
                "personalised_pitch": row.get("personalised_pitch"),
                "sales_notes": row.get("sales_notes"),
                "business_intent_score": _int(row.get("business_intent_score")),
                "business_type": row.get("business_type"),
                "location_match": (row.get("location_match") or "").lower()
                in ("true", "1", "yes"),
                "location_signals": _split(row.get("location_signals")),
                "selling_signals": _split(row.get("selling_signals")),
            }
            if not result["username"]:
                continue
            lead_id = db.upsert_lead_from_pipeline(result)
            lead = db.get_lead(lead_id)
            if lead:
                try:
                    out_dir = Path(__file__).resolve().parent / "data" / "audits"
                    company = db.get_setting("company_name", "Vidora")
                    path_pdf = generate_audit(lead, out_dir, company_name=company)
                    db.update_lead_fields(lead_id, {"audit_path": str(path_pdf)})
                except Exception:  # noqa: BLE001
                    pass
            count += 1
    return count


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

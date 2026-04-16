"""
Vidora daily pipeline runner.

Scheduled by Windows Task Scheduler at 08:00 every day.
Reads all config from the database (no CLI prompts needed).

Usage:
    python C:/vidora/daily_run.py

Logs to: C:/vidora/logs/daily_YYYY-MM-DD.log
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VIDORA_DIR   = Path("C:/vidora")
LOGS_DIR     = VIDORA_DIR / "logs"
SCOUT_SCRIPT = VIDORA_DIR / "vidora_scout_final.py"
DB_PATH      = VIDORA_DIR / "vidora.db"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOGS_DIR / f"daily_{date.today().isoformat()}.log"


def _log(msg: str) -> None:
    line = f"[{date.today().isoformat()}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _get_setting(key: str) -> str:
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        return row[0] if row else ""
    except Exception as e:
        _log(f"DB read error for '{key}': {e}")
        return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _log("=== Vidora daily run starting ===")

    api_key = (
        _get_setting("anthropic_api_key")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    if not api_key:
        _log("ERROR: Anthropic API key not found in DB or environment. Aborting.")
        sys.exit(1)

    location    = _get_setting("default_location") or "manchester"
    leads_count = _get_setting("default_leads_per_run") or "10"
    output_csv  = str(VIDORA_DIR / f"leads_daily_{date.today().isoformat()}.csv")
    audits_dir  = str(VIDORA_DIR / "audits")

    _log(f"Target: {leads_count} leads | location: {location}")
    _log(f"Output: {output_csv}")

    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = api_key

    cmd = [
        sys.executable,
        str(SCOUT_SCRIPT),
        "--source", "maps",
        "--query", f"aesthetic clinic {location}",
        "--leads", str(leads_count),
        "--output", output_csv,
        "--audits-dir", audits_dir,
    ]

    _log("Launching pipeline: " + " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=7200,  # 2-hour hard limit
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                _log(f"  {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                _log(f"  STDERR: {line}")
        if result.returncode == 0:
            _log("Pipeline finished successfully.")
        else:
            _log(f"Pipeline exited with code {result.returncode}.")
    except subprocess.TimeoutExpired:
        _log("ERROR: Pipeline timed out after 2 hours.")
        sys.exit(1)
    except Exception as e:
        _log(f"ERROR running pipeline: {e}")
        sys.exit(1)

    _log("=== Daily run complete ===")


if __name__ == "__main__":
    main()

"""
Zoho IMAP reply monitor.

Checks the Zoho inbox every 30 minutes for replies from known lead emails.
When a reply is found:
  - Updates lead status to 'replied'
  - Cancels any pending follow-ups in the queue
  - Posts a Discord notification with the reply preview

Credentials:
    C:/vidora/zoho_email.txt   — IMAP login (same as SMTP)
    C:/vidora/zoho_pass.txt    — password (same file)

Zoho IMAP:  imap.zoho.eu:993 (SSL)
"""

from __future__ import annotations

import email
import email.header
import imaplib
import threading
import time as _time
from datetime import datetime, timedelta
from pathlib import Path

from . import db
from .discord import notify_reply

IMAP_HOST = "imap.zoho.eu"
IMAP_PORT = 993
CHECK_INTERVAL = 900   # 15 minutes

CRED_EMAIL = Path("C:/vidora/zoho_email.txt")
CRED_PASS  = Path("C:/vidora/zoho_pass.txt")

_monitor_started = False
_monitor_lock = threading.Lock()


def _load_creds() -> tuple[str, str] | None:
    if not CRED_EMAIL.exists() or not CRED_PASS.exists():
        return None
    return (
        CRED_EMAIL.read_text(encoding="utf-8").strip(),
        CRED_PASS.read_text(encoding="utf-8").strip(),
    )


def _decode_header(raw: str) -> str:
    parts = email.header.decode_header(raw or "")
    out = []
    for byt, enc in parts:
        if isinstance(byt, bytes):
            out.append(byt.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(byt)
    return " ".join(out)


def _get_text_body(msg: email.message.Message) -> str:
    """Extract plain-text body from a Message object."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")
    return ""


def check_inbox_for_replies() -> int:
    """
    Connect to Zoho IMAP, scan recent messages for replies from lead emails.
    Returns the number of new replies found.
    """
    creds = _load_creds()
    if not creds:
        print("[imap] credentials not found — skipping reply check")
        return 0

    zoho_email, password = creds

    # Build a set of {email: lead_id} for all contacted leads
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, email FROM leads WHERE email IS NOT NULL AND email != '' "
            "AND status NOT IN ('replied', 'dead')"
        ).fetchall()
    lead_by_email = {r["email"].lower().strip(): r["id"] for r in rows}

    if not lead_by_email:
        return 0

    found = 0
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(zoho_email, password)
            imap.select("INBOX")

            # Search messages received in the last 48 hours
            cutoff = (datetime.utcnow() - timedelta(hours=48)).strftime("%d-%b-%Y")
            _, msg_nums = imap.search(None, f'SINCE "{cutoff}"')
            ids = msg_nums[0].split()

            for num in ids:
                _, msg_data = imap.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_header = _decode_header(msg.get("From", ""))
                # Extract bare email address from "Name <email@domain.com>"
                from_email = from_header
                if "<" in from_header and ">" in from_header:
                    from_email = from_header.split("<")[1].split(">")[0].strip()
                from_email = from_email.lower().strip()

                if from_email not in lead_by_email:
                    continue

                lead_id = lead_by_email[from_email]

                # Check we haven't already logged this reply
                with db.connection() as conn:
                    already = conn.execute(
                        "SELECT 1 FROM outreach_log WHERE lead_id = ? AND status = 'replied'",
                        (lead_id,),
                    ).fetchone()
                if already:
                    continue

                # Extract preview
                body = _get_text_body(msg)
                preview = body.strip()[:300] if body else "(no body)"

                # Update DB
                db.update_lead_fields(lead_id, {"status": "replied"})
                _cancel_pending_followups(lead_id)

                # Log the reply
                subject = _decode_header(msg.get("Subject", ""))
                with db.connection() as conn:
                    conn.execute(
                        "INSERT INTO outreach_log (lead_id, to_email, subject, status, sent_at, sequence_day) "
                        "VALUES (?, ?, ?, 'replied', ?, 0)",
                        (lead_id, from_email, subject, datetime.utcnow().isoformat()),
                    )

                # Discord notification
                lead = db.get_lead(lead_id)
                if lead:
                    notify_reply(lead, from_email, preview)

                print(f"[imap] reply from {from_email} — lead #{lead_id} marked replied")
                found += 1

    except imaplib.IMAP4.error as e:
        print(f"[imap] IMAP error: {e}")
    except Exception as e:
        print(f"[imap] unexpected error: {e}")

    return found


def _cancel_pending_followups(lead_id: int) -> None:
    """Cancel any queued follow-ups for a lead that has replied."""
    with db.connection() as conn:
        conn.execute(
            "UPDATE followup_queue SET status = 'cancelled' "
            "WHERE lead_id = ? AND status = 'pending'",
            (lead_id,),
        )


def start_monitor() -> None:
    """Start background IMAP monitor thread. Safe to call multiple times."""
    global _monitor_started
    with _monitor_lock:
        if _monitor_started:
            return
        _monitor_started = True

    def _loop():
        # Initial delay so app starts up cleanly before first check
        _time.sleep(60)
        while True:
            try:
                n = check_inbox_for_replies()
                if n:
                    print(f"[imap] {n} new replies processed")
            except Exception as e:
                print(f"[imap] monitor error: {e}")
            _time.sleep(CHECK_INTERVAL)

    t = threading.Thread(target=_loop, name="imap-monitor", daemon=True)
    t.start()
    print("[imap] reply monitor started (checks every 30 min)")

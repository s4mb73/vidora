"""
Zoho IMAP reply monitor.

Checks the Zoho inbox every 15 minutes for replies from known lead emails.
When a reply is found:
  - Classifies it with Claude (interested / not_interested / unsubscribe /
    auto_reply / other)
  - Stores the full reply + classification in the `replies` table
  - Dispatches the correct follow-up action:
      interested       → cancel follow-ups, mark replied, Discord ping
      not_interested   → cancel follow-ups, mark replied
      unsubscribe      → cancel follow-ups, add to suppression list, mark replied
      auto_reply       → reschedule follow-ups for after return_date; status stays contacted
      other            → cancel follow-ups, mark replied, quiet Discord log

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
from . import reply_classifier
from .discord import notify_reply_interested, notify_reply_other

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


def _dispatch(lead: dict, reply: dict) -> None:
    """Apply the right follow-up action for a classified reply.

    `reply` is the dict returned by reply_classifier.classify().
    """
    lead_id = lead["id"]
    label = reply["label"]

    if label == "auto_reply":
        # Reschedule pending follow-ups past the return date. Lead stays
        # 'contacted' — they haven't actually engaged yet.
        resume_after = reply.get("return_date") or (
            datetime.utcnow().date() + timedelta(days=reply_classifier.AUTO_REPLY_FALLBACK_DAYS)
        ).isoformat()
        n = db.reschedule_pending_followups(lead_id, resume_after)
        db.update_lead_fields(lead_id, {"last_reply_label": label})
        print(f"[imap] lead #{lead_id}: auto_reply — rescheduled {n} follow-ups to {resume_after}")
        return

    # All other labels cancel remaining follow-ups.
    db.cancel_pending_followups(lead_id)
    db.update_lead_fields(lead_id, {"status": "replied", "last_reply_label": label})

    if label == "unsubscribe":
        email_addr = reply.get("from_email") or lead.get("email") or ""
        db.add_suppression(email_addr, reason="unsubscribe", lead_id=lead_id)
        if lead.get("email"):
            db.add_suppression(lead["email"], reason="unsubscribe", lead_id=lead_id)
        print(f"[imap] lead #{lead_id}: unsubscribe — added to suppression list")
        return

    if label == "interested":
        notify_reply_interested(lead, reply["from_email"], reply["body"][:300])
        print(f"[imap] lead #{lead_id}: INTERESTED — Discord pinged")
        return

    if label == "not_interested":
        print(f"[imap] lead #{lead_id}: not_interested — follow-ups cancelled")
        return

    # label == "other"
    notify_reply_other(lead, reply["from_email"], reply["body"][:300], reply.get("reasoning", ""))
    print(f"[imap] lead #{lead_id}: other — manual review flagged")


def check_inbox_for_replies() -> int:
    """
    Connect to Zoho IMAP, scan recent messages for replies from lead emails.
    Classifies each reply and dispatches the appropriate action.
    Returns the number of new replies processed.
    """
    creds = _load_creds()
    if not creds:
        print("[imap] credentials not found — skipping reply check")
        return 0

    zoho_email, password = creds

    # Build a set of {email: lead_id} for all contacted leads. We include
    # leads that already have last_reply_label=auto_reply so subsequent replies
    # (e.g. "back now, let's chat") still get classified.
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, email FROM leads WHERE email IS NOT NULL AND email != '' "
            "AND status != 'dead'"
        ).fetchall()
    lead_by_email = {r["email"].lower().strip(): r["id"] for r in rows}

    if not lead_by_email:
        return 0

    found = 0
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(zoho_email, password)
            imap.select("INBOX")

            # Search messages received in the last 48 hours.
            cutoff = (datetime.utcnow() - timedelta(hours=48)).strftime("%d-%b-%Y")
            _, msg_nums = imap.search(None, f'SINCE "{cutoff}"')
            ids = msg_nums[0].split()

            for num in ids:
                _, msg_data = imap.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_header = _decode_header(msg.get("From", ""))
                from_email = from_header
                if "<" in from_header and ">" in from_header:
                    from_email = from_header.split("<")[1].split(">")[0].strip()
                from_email = from_email.lower().strip()

                if from_email not in lead_by_email:
                    continue

                lead_id = lead_by_email[from_email]
                subject = _decode_header(msg.get("Subject", ""))

                # Dedup: skip if we've already stored this message.
                if db.reply_exists_for_message(lead_id, subject, from_email):
                    continue

                body = _get_text_body(msg) or ""

                # Classify (never raises; falls back to "other" with confidence 0).
                result = reply_classifier.classify(subject, body, from_email)
                label = result["label"]
                result["from_email"] = from_email
                result["body"] = body

                # Persist the reply row.
                db.insert_reply(
                    lead_id=lead_id,
                    from_email=from_email,
                    subject=subject,
                    body=body[:reply_classifier.MAX_BODY_CHARS],
                    label=label,
                    confidence=result["confidence"],
                    return_date=result.get("return_date"),
                    classification_model=result["model"],
                    reasoning=result["reasoning"],
                )

                # Keep backward-compat outreach_log 'replied' row so existing
                # stats queries (weekly_stats, leads_pipeline_stats) keep working.
                with db.connection() as conn:
                    conn.execute(
                        "INSERT INTO outreach_log "
                        "(lead_id, to_email, subject, status, sent_at, sequence_day) "
                        "VALUES (?, ?, ?, 'replied', ?, 0)",
                        (lead_id, from_email, subject, datetime.utcnow().isoformat()),
                    )

                # Dispatch action based on label.
                lead = db.get_lead(lead_id)
                if lead:
                    _dispatch(lead, result)

                found += 1

    except imaplib.IMAP4.error as e:
        print(f"[imap] IMAP error: {e}")
    except Exception as e:
        print(f"[imap] unexpected error: {e}")

    return found


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
    print("[imap] reply monitor started (checks every 15 min)")

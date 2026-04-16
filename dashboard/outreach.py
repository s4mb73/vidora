"""
Cold email outreach via Zoho SMTP — three-email sequence.

Day 1  Subject: "{business_name} — quick question"
Day 3  Subject: "{business_name} — what {competitor_name} are doing differently"
Day 7  Subject: "two Manchester {business_type}s — one spot left"

Credentials:  C:/vidora/zoho_email.txt
              C:/vidora/zoho_pass.txt

Volume cap:   50 emails per calendar day (all sequence steps combined).
"""

from __future__ import annotations

import re
import smtplib
import ssl
import threading
import time as _time
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from . import db

ZOHO_HOST = "smtp.zoho.eu"
ZOHO_PORT = 465
DAILY_CAP = 50

CRED_EMAIL = Path("C:/vidora/zoho_email.txt")
CRED_PASS  = Path("C:/vidora/zoho_pass.txt")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _load_creds() -> tuple[str, str]:
    if not CRED_EMAIL.exists():
        raise FileNotFoundError(f"Zoho email file missing: {CRED_EMAIL}")
    if not CRED_PASS.exists():
        raise FileNotFoundError(f"Zoho password file missing: {CRED_PASS}")
    return (CRED_EMAIL.read_text(encoding="utf-8").strip(),
            CRED_PASS.read_text(encoding="utf-8").strip())


# ---------------------------------------------------------------------------
# Daily cap
# ---------------------------------------------------------------------------

def _sent_today() -> int:
    today = date.today().isoformat()
    with db.connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM outreach_log "
            "WHERE status = 'sent' AND sent_at >= ?",
            (today + " 00:00:00",),
        ).fetchone()
    return row["n"] if row else 0


def _check_cap() -> None:
    sent = _sent_today()
    if sent >= DAILY_CAP:
        raise RuntimeError(
            f"Daily send cap reached ({DAILY_CAP}/day). "
            f"{sent} emails already sent today."
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _short_name(lead: dict) -> str:
    """Return a short readable business name for use inside email body copy.

    'City Centre Dental & Implant Clinic - Manchester' → 'City Centre Dental'
    Strips anything after ' - ', ' – ', ' & ', and drops trailing generic words.
    """
    full = (lead.get("business_name") or "").strip()
    if not full:
        return "@" + (lead.get("username") or "your business").lstrip("@")
    # Cut at dash/dash separator (location suffix)
    for sep in (" - ", " – ", " | "):
        if sep in full:
            full = full.split(sep)[0].strip()
    # Cut at ampersand if what follows is a generic word
    generic_after_amp = {"implant", "implants", "cosmetic", "associates", "partners"}
    if " & " in full:
        parts = full.split(" & ", 1)
        if parts[1].split()[0].lower() in generic_after_amp:
            full = parts[0].strip()
    # Drop trailing generic words (Clinic, Studio, Practice, Ltd, etc.)
    drop_tail = {"clinic", "clinics", "studio", "practice", "practices",
                 "centre", "center", "ltd", "limited", "llp"}
    words = full.split()
    while words and words[-1].lower().rstrip("s") in drop_tail:
        words.pop()
    return " ".join(words) if words else full


def _first_name(lead: dict) -> str:
    biz = (lead.get("business_name") or "").strip()
    if biz:
        return biz.split()[0].rstrip(".,")
    return (lead.get("username") or "there").lstrip("@")


def _competitor_name(lead: dict, settings: dict) -> str:
    """Best competitor name: competitor_benchmark top name, then competitors list, then fallback."""
    bench = lead.get("competitor_benchmark") or {}
    if bench.get("top_competitor_name"):
        return bench["top_competitor_name"]
    comps = lead.get("competitors") or []
    if comps and comps[0].get("business_name"):
        return comps[0]["business_name"]
    if comps and comps[0].get("username"):
        return "@" + comps[0]["username"]
    return settings.get("competitor_name_fallback", "a competitor nearby")


def _biz_type(lead: dict) -> str:
    raw = (lead.get("business_type") or "business").lower().strip()
    # strip plural if already there, then return base word
    return raw.rstrip("s")


def _fmt(value, suffix="", fallback="unknown") -> str:
    return f"{value}{suffix}" if value is not None else fallback


def _top_competitor_reviews(lead: dict) -> str:
    """Return a string like '312' or '' for the top competitor's review count."""
    bench = lead.get("competitor_benchmark") or {}
    rev = bench.get("top_competitor_maps_reviews")
    return str(rev) if rev else ""


def _fill(template: str, lead: dict, settings: dict) -> str:
    """Replace all {placeholders} in a template string."""
    biz = lead.get("business_name") or ("@" + (lead.get("username") or "your business"))
    weaknesses = lead.get("weaknesses") or []
    weakness_1 = weaknesses[0] if weaknesses else "production quality gaps limiting your reach"

    replacements = {
        "business_name":    biz,
        "first_name":       _first_name(lead),
        "maps_review_count": _fmt(lead.get("maps_review_count"), fallback="hundreds of"),
        "maps_rating":      _fmt(lead.get("maps_rating"), fallback=""),
        "avg_likes":        _fmt(lead.get("avg_likes"), fallback="very few"),
        "avg_comments":     _fmt(lead.get("avg_comments"), fallback=""),
        "engagement_rate":  _fmt(lead.get("engagement_rate"), "%", fallback="low"),
        "posting_frequency": lead.get("posting_frequency") or "regularly",
        "weakness_1":       weakness_1,
        "competitor_name":  _competitor_name(lead, settings),
        "business_type":    _biz_type(lead),
        "sender_name":      settings.get("sender_name", ""),
        "sender_title":     settings.get("sender_title", ""),
        "sender_website":   settings.get("sender_website", "innovite.io"),
        "sender_address":   settings.get("sender_address", ""),
        "client_company":   settings.get("client_company", "Vidora Media"),
        "social_proof":     settings.get("social_proof", ""),
        "top_competitor_reviews": _top_competitor_reviews(lead),
    }
    result = template
    for key, val in replacements.items():
        result = result.replace("{" + key + "}", str(val) if val is not None else "")
    return result


# ---------------------------------------------------------------------------
# Day 1 — initial email
# ---------------------------------------------------------------------------

def build_subject(lead: dict, settings: dict) -> str:
    # Use Claude-generated subject if available
    if lead.get("email_subject"):
        return lead["email_subject"]
    tmpl = settings.get(
        "email_subject_template",
        "{business_name} - quick question",
    )
    return _fill(tmpl, lead, settings)


def _posting_context(lead: dict) -> str:
    """Return a posting frequency string, falling back to mining the weakness text."""
    pf = lead.get("posting_frequency")
    if pf:
        return f"posting {pf}"
    # Try to extract from Claude's weakness text e.g. "posting 7 times per week"
    import re
    for w in (lead.get("weaknesses") or []):
        m = re.search(r'posting\s+(\d+\s+times?\s+(?:per|a)\s+week)', w, re.I)
        if m:
            return f"posting {m.group(1)}"
    return "posting regularly"


def _avg_likes_context(lead: dict) -> str:
    """Return avg likes string, falling back to mining the weakness text."""
    al = lead.get("avg_likes")
    if al is not None:
        return f"averaging just {al} likes per post"
    import re
    for w in (lead.get("weaknesses") or []):
        m = re.search(r'average(?:s)?\s+(?:of\s+)?(?:only\s+)?([\d.]+)\s+likes?\s+per\s+post', w, re.I)
        if m:
            return f"averaging just {m.group(1)} likes per post"
    return "getting very little engagement"


def build_body(lead: dict, settings: dict) -> str:
    biz          = _short_name(lead)
    review_count = _fmt(lead.get("maps_review_count"), fallback="hundreds of")
    rating       = _fmt(lead.get("maps_rating"), fallback="")
    posting_ctx  = _posting_context(lead)
    likes_ctx    = _avg_likes_context(lead)
    comp_name    = _competitor_name(lead, settings)

    greeting     = settings.get("email_greeting", "Hi {first_name},")
    greeting     = _fill(greeting, lead, settings)
    intro        = settings.get("email_intro",
                       "I run Innovite - a content evaluation platform used by media agencies across the UK.")
    social_proof = settings.get("social_proof",
                       "We handle content for Premier League footballers and a handful of Manchester clinics.")
    sender_name    = settings.get("sender_name", "Louis")
    sender_title   = settings.get("sender_title", "Innovite")
    sender_website = settings.get("sender_website", "innovite.io")
    sender_address = settings.get("sender_address", "")
    address_line   = f"\n{sender_address}" if sender_address else ""

    # Use Claude-generated email body if available (from pipeline)
    if lead.get("email_body"):
        return lead["email_body"]

    # Use template if provided, otherwise use hardcoded sequence body
    custom = settings.get("email_body_day1", "").strip()
    if custom:
        return _fill(custom, lead, settings)

    rating_str = f" at {rating} stars" if rating else ""

    reviews_line = ""
    bench = lead.get("competitor_benchmark") or {}
    top_rev = bench.get("top_competitor_maps_reviews")
    target_rev = lead.get("maps_review_count")
    if top_rev and target_rev and int(top_rev) > int(target_rev):
        reviews_line = f" - and they already overtook {biz} on Google reviews ({top_rev} vs {review_count})"
    elif top_rev:
        reviews_line = f" - with {top_rev} Google reviews already"

    body = (
        f"With {review_count} Google reviews{rating_str}, {biz} has built the kind of reputation "
        f"that should have new patients finding you every day - but {posting_ctx} and "
        f"{likes_ctx}, that reputation is completely invisible to anyone who hasn't already heard of you.\n\n"
        f"{comp_name} is already converting their social presence into consultations because their "
        f"content looks like it costs what their treatments do{reviews_line}.\n\n"
        f"{social_proof}\n\n"
        f"Worth seeing what that looks like for {biz} - yes or no?\n\n"
        f"{sender_name}"
    )
    return body


# ---------------------------------------------------------------------------
# Day 3 — competitor specific follow-up
# ---------------------------------------------------------------------------

def _original_subject(lead_id: int, settings: dict) -> str:
    """Return the Day 1 subject sent to this lead, for Re: threading."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT subject FROM outreach_log WHERE lead_id = ? AND sequence_day = 1 AND status = 'sent' "
            "ORDER BY sent_at DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
    if row and row["subject"]:
        return row["subject"]
    # Fallback: build it fresh
    lead = db.get_lead(lead_id) or {}
    return build_subject(lead, settings)


def build_followup_day3(lead: dict, settings: dict) -> tuple[str, str]:
    """Returns (subject, body)."""
    body_tmpl = settings.get("followup_day3_body", "")

    orig_subj = _original_subject(lead["id"], settings)
    subject = f"Re: {orig_subj}"

    if body_tmpl.strip():
        body = _fill(body_tmpl, lead, settings)
    else:
        biz          = _short_name(lead)
        comp_name    = _competitor_name(lead, settings)
        review_count = _fmt(lead.get("maps_review_count"), fallback="hundreds of")
        sender_name  = settings.get("sender_name", "Louis")

        body = (
            f"{biz} has {review_count} reviews sitting completely unused on Instagram "
            f"while {comp_name} one mile away is actively converting theirs into bookings.\n\n"
            f"{comp_name} uses their Story Highlights as a consultation funnel - their Reviews "
            f"highlight turns their Google reputation into social proof that a patient sees "
            f"before they ever send a DM.\n\n"
            f"One restructured bio and a Reviews highlight costs nothing to set up - what "
            f"determines whether patients act on it is the quality of the content behind it.\n\n"
            f"That the piece worth fixing - yes or no?\n\n"
            f"{sender_name}"
        )
    return subject, body


# ---------------------------------------------------------------------------
# Day 7 — scarcity close
# ---------------------------------------------------------------------------

def build_followup_day7(lead: dict, settings: dict) -> tuple[str, str]:
    """Returns (subject, body)."""
    body_tmpl = settings.get("followup_day7_body", "")

    orig_subj = _original_subject(lead["id"], settings)
    subject = f"Re: {orig_subj}"

    if body_tmpl.strip():
        body = _fill(body_tmpl, lead, settings)
    else:
        biz          = _short_name(lead)
        biz_type     = _biz_type(lead)
        review_count = _fmt(lead.get("maps_review_count"), fallback="hundreds of")
        rating       = _fmt(lead.get("maps_rating"), fallback="")
        rating_str   = f" and a {rating}-star average" if rating else ""
        sender_name  = settings.get("sender_name", "Louis")

        body = (
            f"Taking on two Manchester {biz_type}s for production content this month - "
            f"one is confirmed, one spot is still open.\n\n"
            f"{biz} fits exactly the profile that works: strong offline reputation, "
            f"consistent posting schedule, engagement that hasn't caught up yet.\n\n"
            f"A practice with {review_count} reviews{rating_str} has already done the hard part "
            f"- the content is what's missing.\n\n"
            f"Is that second spot for {biz} - yes or no?\n\n"
            f"{sender_name}"
        )
    return subject, body


# ---------------------------------------------------------------------------
# Core send
# ---------------------------------------------------------------------------

def _send_smtp(from_email: str, password: str, to_email: str, subject: str, body: str) -> None:
    from email.utils import formataddr
    display_name = "Louis | Innovite"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = formataddr((display_name, from_email))
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(ZOHO_HOST, ZOHO_PORT, context=ctx) as server:
        server.login(from_email, password)
        server.sendmail(from_email, [to_email], msg.as_string())


def _do_send(lead_id: int, to_email: str, subject: str, body: str,
             sequence_day: int) -> dict:
    """Internal send — logs result, returns {ok, message}."""
    log_id = db.log_outreach(lead_id, to_email, subject, sequence_day)
    try:
        from_email, password = _load_creds()
        _send_smtp(from_email, password, to_email, subject, body)
        db.update_outreach_log(log_id, "sent")
        return {"ok": True, "message": f"Day {sequence_day} email sent to {to_email}."}
    except Exception as exc:
        db.update_outreach_log(log_id, "failed", str(exc))
        return {"ok": False, "message": f"Send failed: {exc}"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_lead_email(lead_id: int, override_email: str = "") -> dict:
    """Send Day 1 email. Schedules Day 3 & 7 follow-ups on success."""
    lead = db.get_lead(lead_id)
    if not lead:
        return {"ok": False, "message": "Lead not found."}

    to_email = (override_email or lead.get("email") or "").strip()
    if not to_email:
        return {"ok": False, "message": "No email address saved for this lead."}

    try:
        _check_cap()
    except RuntimeError as e:
        return {"ok": False, "message": str(e)}

    # Don't resend Day 1 if already sent
    if 1 in db.sequence_days_sent(lead_id):
        return {"ok": False, "message": "Day 1 email already sent to this lead."}

    settings = db.get_settings()
    subject  = build_subject(lead, settings)
    body     = build_body(lead, settings)

    result = _do_send(lead_id, to_email, subject, body, sequence_day=1)

    if result["ok"]:
        if lead.get("status") == "new":
            db.update_lead_fields(lead_id, {"status": "contacted"})
        db.schedule_followups(lead_id)

    return result


def send_followup(lead_id: int, sequence_day: int, queue_id: int | None = None) -> dict:
    """Send a specific follow-up day (3 or 7) for a lead."""
    lead = db.get_lead(lead_id)
    if not lead:
        return {"ok": False, "message": "Lead not found."}

    to_email = (lead.get("email") or "").strip()
    if not to_email:
        if queue_id:
            db.mark_followup(queue_id, "cancelled")
        return {"ok": False, "message": "No email address for this lead."}

    try:
        _check_cap()
    except RuntimeError as e:
        return {"ok": False, "message": str(e)}

    # Don't resend same sequence day
    if sequence_day in db.sequence_days_sent(lead_id):
        if queue_id:
            db.mark_followup(queue_id, "cancelled")
        return {"ok": False, "message": f"Day {sequence_day} already sent."}

    settings = db.get_settings()

    if sequence_day == 3:
        subject, body = build_followup_day3(lead, settings)
    elif sequence_day == 7:
        subject, body = build_followup_day7(lead, settings)
    else:
        return {"ok": False, "message": f"Unknown sequence day: {sequence_day}"}

    result = _do_send(lead_id, to_email, subject, body, sequence_day=sequence_day)

    if queue_id:
        db.mark_followup(queue_id, "sent" if result["ok"] else "cancelled")

    return result


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------

_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_scheduler() -> None:
    """Start a background thread that checks for due follow-ups every hour.
    Safe to call multiple times — only starts one thread.
    """
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def _loop():
        while True:
            try:
                due = db.get_due_followups()
                for item in due:
                    if not item.get("email"):
                        db.mark_followup(item["id"], "cancelled")
                        continue
                    result = send_followup(
                        item["lead_id"],
                        item["sequence_day"],
                        queue_id=item["id"],
                    )
                    print(f"[scheduler] lead {item['lead_id']} day {item['sequence_day']}: {result['message']}")
            except Exception as e:
                print(f"[scheduler] error: {e}")
            _time.sleep(3600)  # check every hour

    t = threading.Thread(target=_loop, name="followup-scheduler", daemon=True)
    t.start()

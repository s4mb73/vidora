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

def humanise_frequency(raw) -> str:
    """Convert a raw posts/week value to natural language."""
    if not raw:
        return "rarely posting"
    try:
        n = float(re.search(r"[\d.]+", str(raw)).group())
    except (AttributeError, ValueError):
        return str(raw)
    if n < 0.2:
        return "roughly once a fortnight"
    if n < 0.4:
        return "once every few weeks"
    if n < 0.75:
        return "about once a fortnight"
    if n < 1.5:
        return "once a week"
    if n < 2.5:
        return "a couple of times a week"
    if n < 4.5:
        return f"{int(round(n))} times a week"
    if n < 6.5:
        return "almost daily"
    return "daily"


def humanise_engagement(avg_likes, followers=None) -> str:
    """Convert avg_likes to a natural engagement description.

    Uses engagement rate when followers is provided so 13 likes on 15k followers
    reads as 'barely any engagement' rather than 'modest'.
    """
    try:
        n = float(avg_likes)
    except (TypeError, ValueError):
        return "unknown engagement"
    if followers:
        try:
            er = n / float(followers) * 100
            if er < 0.5:
                return "barely any engagement"
            if er < 1.5:
                return "modest engagement"
            if er < 4:
                return "decent engagement"
            return "strong engagement"
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    # Absolute fallback (no follower count available)
    if n < 10:
        return "barely any engagement"
    if n < 50:
        return "modest engagement"
    if n < 200:
        return "decent engagement"
    return "strong engagement"


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
    return settings.get("competitor_name_fallback") or ""


def _biz_type(lead: dict) -> str:
    """Return singular form of the business type (e.g. 'clinic', 'salon', 'aesthetics')."""
    raw = (lead.get("business_type") or "clinic").lower().strip()
    raw = re.sub(r'\s*\(.*?\)', '', raw).strip()
    words = raw.split()
    core = words[-1] if words else "clinic"
    _already_singular = {"business", "aesthetics", "athletics", "gymnastics", "physics", "logistics"}
    if core in _already_singular:
        return core
    if core.endswith("s") and len(core) > 3:
        return core[:-1]
    return core


def _biz_type_plural(lead: dict) -> str:
    """Return the plural form for use in copy (e.g. 'clinics', 'salons', 'businesses')."""
    singular = _biz_type(lead)
    _irregular = {"business": "businesses", "aesthetics": "aesthetics"}
    if singular in _irregular:
        return _irregular[singular]
    return singular + "s"


def _fmt(value, suffix="", fallback="unknown") -> str:
    if value is None:
        return fallback
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return f"{value}{suffix}"


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
    # Use settings template if explicitly set
    tmpl = settings.get("email_subject_template", "")
    if tmpl:
        return _fill(tmpl, lead, settings)
    # Build a hook-aware subject line
    biz     = _short_name(lead)
    hook    = _select_hook(lead)
    reviews = lead.get("maps_review_count") or ""
    al_raw  = lead.get("avg_likes")
    al      = int(al_raw) if isinstance(al_raw, float) and al_raw == int(al_raw) else al_raw
    pf      = lead.get("posting_frequency") or ""
    freq    = humanise_frequency(pf) if pf else "barely posting"
    try:
        fol = int(lead.get("followers") or 0)
        fol_str = f"{fol:,}"
    except (TypeError, ValueError):
        fol_str = ""
    try:
        ws_raw = float(lead.get("website_score") or 0)
        ws_str = f"{int(ws_raw)}/10" if ws_raw == int(ws_raw) else f"{ws_raw}/10"
    except (TypeError, ValueError):
        ws_str = ""

    if hook == "A" and al:
        return f"{biz} \u2014 {al} likes and {freq}"
    if hook == "B" and al:
        return f"{biz} \u2014 {freq}, {al} likes"
    if hook == "D" and ws_str:
        return f"{biz} \u2014 {fol_str} followers, {ws_str} website"
    if hook == "E" and reviews and fol_str:
        return f"{biz} \u2014 {reviews} reviews, {fol_str} followers"
    # Hook C and fallback
    if al is not None and reviews:
        return f"{biz} \u2014 {reviews} reviews, {al} likes"
    if reviews:
        return f"{biz} \u2014 {reviews} reviews"
    return f"{biz} \u2014 your content"


def _posting_context(lead: dict) -> str:
    """Return a humanised posting frequency string."""
    pf = lead.get("posting_frequency")
    if pf:
        return humanise_frequency(pf)
    # Fall back to mining weakness text for a raw number
    for w in (lead.get("weaknesses") or []):
        m = re.search(r'posting\s+([\d.]+)\s+times?', w, re.I)
        if m:
            return humanise_frequency(m.group(1))
    return "rarely posting"


def _avg_likes_context(lead: dict) -> str:
    """Return a humanised engagement description, scaled against follower count."""
    followers = lead.get("followers")
    al = lead.get("avg_likes")
    if al is not None:
        return humanise_engagement(al, followers)
    for w in (lead.get("weaknesses") or []):
        m = re.search(r'average(?:s)?\s+(?:of\s+)?(?:only\s+)?([\d.]+)\s+likes?\s+per\s+post', w, re.I)
        if m:
            return humanise_engagement(m.group(1), followers)
    return "barely any engagement"


def _select_hook(lead: dict) -> str:
    """Return 'A', 'B', 'C', 'D', or 'E' based on the lead's weakness profile."""
    try:
        pf_raw = lead.get("posting_frequency") or "0"
        ppw = float(re.search(r"[\d.]+", str(pf_raw)).group())
    except (AttributeError, ValueError):
        ppw = 0.0
    try:
        avg_likes = float(lead.get("avg_likes") or 0)
    except (TypeError, ValueError):
        avg_likes = 0.0
    try:
        ws = float(lead.get("website_score") or
                   (lead.get("website_analysis") or {}).get("website_score") or 10)
    except (TypeError, ValueError):
        ws = 10.0
    try:
        followers = int(lead.get("followers") or 0)
    except (TypeError, ValueError):
        followers = 0
    try:
        reviews = int(lead.get("maps_review_count") or 0)
    except (TypeError, ValueError):
        reviews = 0

    # Hook D: decent social, weak website — most specific, check first
    if ws < 5 and followers > 1000:
        return "D"
    # Hook E: strong offline reputation but small online following
    if reviews > 200 and followers < 3000:
        return "E"
    # Hook A: rare posting but audience responds when they do
    if ppw < 1 and avg_likes > 50:
        return "A"
    # Hook B: posting often but content not landing
    if ppw >= 2 and avg_likes < 50:
        return "B"
    # Hook C: low everything (default)
    return "C"


def build_body(lead: dict, settings: dict) -> str:
    # Use Claude-generated email body if available (from pipeline)
    if lead.get("email_body"):
        return lead["email_body"]

    # Use settings template if provided
    custom = settings.get("email_body_day1", "").strip()
    if custom:
        return _fill(custom, lead, settings)

    biz          = _short_name(lead)
    review_count = _fmt(lead.get("maps_review_count"), fallback="hundreds of")
    rating       = _fmt(lead.get("maps_rating"), fallback="")
    rating_str   = f" at {rating} stars" if rating else ""
    posting_ctx  = _posting_context(lead)
    comp_name    = _competitor_name(lead, settings)
    social_proof = settings.get("social_proof",
                       "We produce content for KSI, Premier League footballers and some of the most followed personal brands in the UK. We work with a small number of Manchester businesses we think are ready for that level of production.")
    sender_name  = settings.get("sender_name", "Louis")

    try:
        avg_likes_n = float(lead.get("avg_likes") or 0)
        al_display  = int(avg_likes_n) if avg_likes_n == int(avg_likes_n) else avg_likes_n
    except (TypeError, ValueError):
        al_display = None

    try:
        followers_n = int(lead.get("followers") or 0)
    except (TypeError, ValueError):
        followers_n = 0

    try:
        ws = float(lead.get("website_score") or
                   (lead.get("website_analysis") or {}).get("website_score") or 0)
        ws_display = int(ws) if ws == int(ws) else ws
    except (TypeError, ValueError):
        ws_display = None

    bench    = lead.get("competitor_benchmark") or {}
    top_rev  = bench.get("top_competitor_maps_reviews")
    target_rev = lead.get("maps_review_count")
    if comp_name and top_rev and target_rev and int(top_rev) > int(target_rev):
        reviews_line = f" \u2014 and they already overtook {biz} on Google reviews ({top_rev} vs {review_count})"
    elif comp_name and top_rev:
        reviews_line = f" \u2014 {top_rev} Google reviews and counting"
    else:
        reviews_line = ""

    comp_para = (
        f"{comp_name} is already converting their social presence into consultations because their "
        f"content looks like it costs what their treatments do{reviews_line}.\n\n"
    ) if comp_name else ""

    hook = _select_hook(lead)

    if hook == "A":
        # Low frequency, decent engagement — audience is there, just underserved
        likes_str = f"{al_display} likes" if al_display else "real engagement"
        para1 = (
            f"Getting {likes_str} when you do post tells you the audience is there — "
            f"{biz} just isn't giving them enough to come back for. "
            f"With {review_count} Google reviews{rating_str} and that kind of response rate, "
            f"posting {posting_ctx} means most of those followers will never become patients."
        )
    elif hook == "B":
        # High frequency, low engagement — effort without results
        likes_str = f"{al_display} likes" if al_display else "very few likes"
        para1 = (
            f"{biz} is posting {posting_ctx} but averaging {likes_str} — "
            f"the content isn't landing the way the effort deserves. "
            f"With {review_count} Google reviews{rating_str}, the reputation is clearly there, "
            f"but the social presence isn't converting it."
        )
    elif hook == "D":
        # Decent social, weak website — traffic not converting
        fol_str = f"{followers_n:,}" if followers_n else "a solid following"
        ws_str  = f"{ws_display}/10" if ws_display is not None else "low"
        para1 = (
            f"{biz} is doing the right things on social — {fol_str} followers, "
            f"posting {posting_ctx} — but the website scores {ws_str} and has no clear "
            f"way to convert that traffic into bookings. "
            f"The audience is landing and leaving with nothing to act on."
        )
    elif hook == "E":
        # Strong offline reputation but small online following
        fol_str = f"{followers_n:,}" if followers_n else "a small following"
        para1 = (
            f"{biz} has {review_count} Google reviews{rating_str} — "
            f"the kind of credibility most practices spend years building. "
            f"But with only {fol_str} followers online, that reputation isn't reaching "
            f"the people who haven't already walked through the door."
        )
    else:
        # Hook C — low everything: default
        para1 = (
            f"With {review_count} Google reviews{rating_str}, {biz} has built the kind of "
            f"reputation that should have new patients finding you every day — but posting "
            f"{posting_ctx} with {_avg_likes_context(lead)}, that reputation is completely "
            f"invisible to anyone who hasn't already heard of you."
        )

    body = (
        f"{para1}\n\n"
        f"{comp_para}"
        f"{social_proof}\n\n"
        f"Worth seeing what that looks like for {biz} — yes or no?\n\n"
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

        if comp_name:
            comp_para_d3 = (
                f"{biz} has {review_count} reviews sitting on Google completely invisible on Instagram "
                f"while {comp_name} is actively converting theirs into bookings.\n\n"
                f"{comp_name} uses their Story Highlights as a consultation funnel \u2014 their Reviews "
                f"highlight turns their Google reputation into social proof that a patient sees "
                f"before they ever send a DM.\n\n"
            )
        else:
            comp_para_d3 = (
                f"{biz} has {review_count} Google reviews that almost nobody on Instagram "
                f"ever sees. A clinic with that kind of reputation should be using social proof "
                f"at every step of the patient journey.\n\n"
            )

        body = (
            f"{comp_para_d3}"
            f"One restructured bio and a Reviews highlight costs nothing to set up \u2014 what "
            f"determines whether patients act on it is the quality of the content behind it.\n\n"
            f"That's the piece worth fixing \u2014 yes or no?\n\n"
            f"{sender_name}"
        )
    return subject, body


# ---------------------------------------------------------------------------
# Day 7 — scarcity close
# ---------------------------------------------------------------------------

def build_followup_day7(lead: dict, settings: dict) -> tuple[str, str]:
    """Returns (subject, body)."""
    body_tmpl = settings.get("followup_day7_body", "")

    comp_name = _competitor_name(lead, settings)
    if comp_name:
        subject = f"Re: {comp_name} — last spot this month"
    else:
        orig_subj = _original_subject(lead["id"], settings)
        subject = f"Re: {orig_subj}"

    if body_tmpl.strip():
        body = _fill(body_tmpl, lead, settings)
    else:
        biz          = _short_name(lead)
        biz_type     = _biz_type_plural(lead)
        review_count = _fmt(lead.get("maps_review_count"), fallback="hundreds of")
        rating       = _fmt(lead.get("maps_rating"), fallback="")
        rating_str   = f" and a {rating}-star average" if rating else ""
        sender_name  = settings.get("sender_name", "Louis")
        hook         = _select_hook(lead)

        # Para 2 adapts so "consistent posting schedule" is never said about a dormant account
        if hook == "B":
            profile_line = (
                f"consistent content output, a strong reputation offline, "
                f"but engagement numbers that should be higher given the effort going in"
            )
        elif hook in ("A", "C"):
            profile_line = (
                f"strong offline reputation, an audience that's already there, "
                f"and a content gap that's straightforward to close"
            )
        elif hook == "E":
            profile_line = (
                f"reviews that most clinics spend years earning, "
                f"and an online presence that hasn't caught up with that credibility yet"
            )
        else:  # D and fallback
            profile_line = (
                f"strong offline reputation, social following that should be converting more, "
                f"and a clear gap between traffic and bookings"
            )

        body = (
            f"Taking on two Manchester {biz_type} for production content this month \u2014 "
            f"one is confirmed, one spot is still open.\n\n"
            f"{biz} fits exactly the profile that works: {profile_line}.\n\n"
            f"A practice with {review_count} reviews{rating_str} has already done the hard part "
            f"\u2014 the content is what's missing.\n\n"
            f"Is that second spot for {biz} \u2014 yes or no?\n\n"
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

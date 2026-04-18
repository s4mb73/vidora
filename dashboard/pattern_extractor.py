"""
Extract winning patterns from an email that triggered an `interested` reply.

Triggered by `imap_monitor` right after a reply is classified as `interested`.
Reads the original outbound email (subject + body) plus the inbound reply and
asks Claude to identify which specific components caused the positive outcome.

Patterns land in the `patterns` table with status='pending' and wait for
human approval before they can be used to shape future email generation.
This is intentional — Claude extracting from Claude is a self-reinforcing
loop, and the human-in-the-loop approval is the external signal that keeps
the knowledge base honest.

Model:  claude-haiku-4-5-20251001 (cheap, structured output is easy here).
Scope:  1-4 patterns per interested reply. Never raises — pattern extraction
        failures must not break the IMAP monitor.
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import db

MODEL = "claude-haiku-4-5-20251001"
MAX_BODY_CHARS = 4000
MAX_REPLY_CHARS = 2000

VALID_TYPES = {"opening", "proof", "competitor_drop", "close", "subject", "angle", "other"}

SYSTEM_PROMPT = """You extract reusable cold-email patterns from a message that got a positive reply.

You will see:
- The subject and body of a cold email that was sent
- The reply that came back (classified as 'interested' — positive signal)

Your job: identify 1 to 4 specific, reusable components of the sent email that plausibly contributed to the positive response. Not the obvious stuff (personalisation). The transferable stuff (opening move, angle, proof structure, closing line style).

Allowed pattern types:
- "opening": the first 1-2 lines that set the tone
- "proof": a credibility/social-proof line
- "competitor_drop": a mention of a competitor used as tension
- "close": the final ask / CTA style
- "subject": the subject line if it's a structure (not the specific text)
- "angle": the overall framing ("what's missing" vs "what's working")
- "other": something else worth reusing, labelled clearly

For each pattern:
- `text` is the actual line or short block from the email (≤200 chars). Quote it, don't paraphrase.
- `reasoning` is ≤20 words on why it worked (what the reply signal suggests).

Rules:
- Only extract patterns you believe contributed to the positive reply, not everything.
- 1-4 patterns total. Fewer is fine if only one component was strong.
- If nothing transferable stands out, return an empty array.
- Output strict JSON, no prose.

Schema:
{
  "patterns": [
    {"pattern_type": "opening|proof|competitor_drop|close|subject|angle|other",
     "text": "quoted excerpt from the sent email",
     "reasoning": "why this likely worked"}
  ]
}"""


def _api_key() -> str | None:
    key = db.get_setting("anthropic_api_key", "").strip()
    if key:
        return key
    return os.environ.get("ANTHROPIC_API_KEY") or None


def _build_user_prompt(subject: str, body: str, reply_body: str) -> str:
    body_t = (body or "").strip()[:MAX_BODY_CHARS]
    reply_t = (reply_body or "").strip()[:MAX_REPLY_CHARS]
    return (
        f"SENT EMAIL\n"
        f"Subject: {subject or '(no subject)'}\n"
        f"---\n{body_t or '(empty body)'}\n\n"
        f"REPLY (classified 'interested')\n"
        f"---\n{reply_t or '(empty reply)'}"
    )


def _coerce(raw: dict[str, Any]) -> list[dict]:
    """Normalise classifier output into a clean list of pattern dicts."""
    items = raw.get("patterns") or []
    if not isinstance(items, list):
        return []
    out = []
    for item in items[:4]:  # hard-cap
        if not isinstance(item, dict):
            continue
        ptype = str(item.get("pattern_type", "other")).strip().lower()
        if ptype not in VALID_TYPES:
            ptype = "other"
        text = str(item.get("text", "")).strip()[:400]
        reasoning = str(item.get("reasoning", "")).strip()[:200]
        if not text:
            continue
        out.append({"pattern_type": ptype, "text": text, "reasoning": reasoning})
    return out


def extract_patterns(subject: str, body: str, reply_body: str) -> list[dict]:
    """Return 0-4 pattern dicts. Never raises."""
    try:
        import anthropic
    except ImportError:
        return []
    key = _api_key()
    if not key:
        return []
    if not (body or "").strip():
        return []

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": _build_user_prompt(subject, body, reply_body)}],
        )
        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1].lstrip("json").strip()
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    except Exception as e:
        print(f"[patterns] extraction error: {e}")
        return []

    return _coerce(parsed)


def extract_and_store(lead_id: int, reply_id: int) -> int:
    """Pipeline entry point. Looks up the sent email + reply, extracts patterns,
    stores them as pending in the `patterns` table. Returns the number stored.
    """
    lead = db.get_lead(lead_id)
    if not lead:
        return 0
    subject = lead.get("email_subject") or ""
    body = lead.get("email_body") or ""
    if not body:
        return 0

    reply_body = ""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT body FROM replies WHERE id = ?", (reply_id,)
        ).fetchone()
    if row:
        reply_body = row["body"] or ""

    patterns = extract_patterns(subject, body, reply_body)
    if not patterns:
        return 0

    for p in patterns:
        db.insert_pattern(
            pattern_type=p["pattern_type"],
            text=p["text"],
            reasoning=p["reasoning"],
            source_lead_id=lead_id,
            source_reply_id=reply_id,
            source_email_subject=subject,
            source_email_body=body,
            extractor_model=MODEL,
        )
    print(f"[patterns] extracted {len(patterns)} pattern(s) from lead #{lead_id}")
    return len(patterns)

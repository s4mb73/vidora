"""
Classify an inbound email reply to cold outreach into one of five labels.

Labels:
    interested       positive signal; questions, tell-me-more, calendar ask
    not_interested   soft no; "not right now", "we're good"
    unsubscribe      explicit opt-out; STOP, remove, unsubscribe
    auto_reply       out-of-office / vacation responder; populate return_date
    other            ambiguous, referral, wrong-person, parseable-but-unclear

Uses claude-haiku-4-5-20251001 for speed and cost. Classification is cached
on the reply row — never re-runs for the same message.

If the Anthropic API key is missing or the call fails, we fall back to label
"other" with confidence 0 so the IMAP monitor still records the reply.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

from . import db

MODEL = "claude-haiku-4-5-20251001"
MAX_BODY_CHARS = 10_000
CONFIDENCE_FLOOR = 0.7   # below this, force label to "other"
AUTO_REPLY_FALLBACK_DAYS = 14

VALID_LABELS = {"interested", "not_interested", "unsubscribe", "auto_reply", "other"}


SYSTEM_PROMPT = """You classify email replies to cold outreach into exactly one label.

Labels (choose one):

- "interested": positive signal. Examples: asks questions about the offer, requests a call/meeting/time, replies "sounds good", "tell me more", "send info", "yes", "let's chat", forwards to a colleague saying they're interested. Any reply showing willingness to engage further.

- "not_interested": soft no, polite decline, "not right now", "we're good thanks", "already have a provider", "maybe later". The sender read it and said no.

- "unsubscribe": explicit opt-out. Examples: "STOP", "remove me", "unsubscribe", "do not email again", "take me off your list", GDPR-style opt-out, angry "don't contact us".

- "auto_reply": automated response. Out-of-office, vacation responder, "I'm away until X", "will return on X", "currently on leave", "I have limited email access". If a return date is stated, extract it as YYYY-MM-DD.

- "other": anything else. Referrals to a different contact ("email Jane instead"), wrong person ("you have the wrong address"), parseable but ambiguous replies, questions that aren't about the offer.

Output strict JSON only, no prose, matching this schema:

{
  "label": "interested" | "not_interested" | "unsubscribe" | "auto_reply" | "other",
  "confidence": number between 0 and 1,
  "return_date": "YYYY-MM-DD" or null,
  "reasoning": "one short sentence"
}

Rules:
- Confidence reflects how sure you are. If the reply is ambiguous, use lower confidence.
- return_date MUST be null unless label is "auto_reply" AND the sender stated a specific return date.
- reasoning is one short sentence, under 20 words. No markdown.
- Output ONLY the JSON object. No code fences, no explanation before or after."""


def _api_key() -> str | None:
    key = db.get_setting("anthropic_api_key", "").strip()
    if key:
        return key
    return os.environ.get("ANTHROPIC_API_KEY") or None


def _build_user_prompt(subject: str, body: str, from_email: str) -> str:
    sender_domain = from_email.split("@")[-1] if "@" in from_email else from_email
    body_trimmed = (body or "").strip()
    if len(body_trimmed) > MAX_BODY_CHARS:
        body_trimmed = body_trimmed[:MAX_BODY_CHARS] + "\n[...truncated]"
    return (
        f"Sender domain: {sender_domain}\n"
        f"Subject: {subject or '(no subject)'}\n"
        f"---\n"
        f"{body_trimmed or '(empty body)'}"
    )


def _fallback_return_date() -> str:
    return (date.today() + timedelta(days=AUTO_REPLY_FALLBACK_DAYS)).isoformat()


def _coerce(raw: dict[str, Any]) -> dict:
    """Normalise a classifier JSON blob into our canonical shape."""
    label = str(raw.get("label", "other")).strip().lower()
    if label not in VALID_LABELS:
        label = "other"
    try:
        confidence = float(raw.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    # Enforce confidence floor: low-confidence labels collapse to "other".
    if confidence < CONFIDENCE_FLOOR and label != "other":
        label = "other"

    return_date = raw.get("return_date")
    if label == "auto_reply":
        if not return_date:
            return_date = _fallback_return_date()
    else:
        return_date = None

    reasoning = str(raw.get("reasoning", "") or "")[:300]

    return {
        "label": label,
        "confidence": confidence,
        "return_date": return_date,
        "reasoning": reasoning,
    }


def classify(subject: str, body: str, from_email: str) -> dict:
    """Classify a reply. Returns {label, confidence, return_date, reasoning, model}.

    Never raises. On any failure, returns label='other' with confidence 0.
    """
    try:
        import anthropic
    except ImportError:
        return {
            "label": "other", "confidence": 0.0, "return_date": None,
            "reasoning": "anthropic SDK not installed", "model": MODEL,
        }

    key = _api_key()
    if not key:
        return {
            "label": "other", "confidence": 0.0, "return_date": None,
            "reasoning": "no API key configured", "model": MODEL,
        }

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(subject, body, from_email)}],
        )
        raw_text = response.content[0].text.strip()
        # Strip a fenced-code wrapper if the model added one.
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1].lstrip("json").strip()
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return {
            "label": "other", "confidence": 0.0, "return_date": None,
            "reasoning": f"unparseable JSON: {e}", "model": MODEL,
        }
    except Exception as e:
        return {
            "label": "other", "confidence": 0.0, "return_date": None,
            "reasoning": f"classifier error: {e}", "model": MODEL,
        }

    result = _coerce(parsed)
    result["model"] = MODEL
    return result

"""
Discord webhook notifications for Vidora.

Webhook URL stored in C:/vidora/discord_webhook.txt
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path

WEBHOOK_FILE = Path("C:/vidora/discord_webhook.txt")


def _webhook_url() -> str | None:
    if WEBHOOK_FILE.exists():
        return WEBHOOK_FILE.read_text(encoding="utf-8").strip()
    return None


def _post(payload: dict) -> bool:
    url = _webhook_url()
    if not url:
        return False
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (vidora, 1.0)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as http_err:
            # Discord returns 204 No Content on success — urllib raises this as an error
            if http_err.code == 204:
                return True
            print(f"[discord] webhook HTTP error: {http_err.code}")
            return False
    except Exception as e:
        print(f"[discord] webhook error: {e}")
        return False


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def notify_reply(lead: dict, from_email: str, preview: str) -> bool:
    """Fire when a lead replies to an outreach email."""
    username = lead.get("username") or "unknown"
    biz = lead.get("business_name") or f"@{username}"
    payload = {
        "embeds": [{
            "title": f"📬 Reply from {biz}",
            "description": (
                f"**Lead:** [@{username}](https://instagram.com/{username})\n"
                f"**From:** {from_email}\n\n"
                f"**Preview:**\n> {preview[:300]}"
            ),
            "color": 0xFFD700,  # gold
            "footer": {"text": "Vidora · Reply detected"},
        }]
    }
    return _post(payload)


def notify_run_complete(run_id: int, leads_found: int, location: str) -> bool:
    """Fire when a pipeline run finishes."""
    payload = {
        "embeds": [{
            "title": f"✅ Run #{run_id} complete",
            "description": (
                f"Found **{leads_found}** new leads in **{location}**.\n"
                f"Check the dashboard to review and send outreach."
            ),
            "color": 0x57F287,  # green
            "footer": {"text": "Vidora · Pipeline"},
        }]
    }
    return _post(payload)


def notify_send_failed(lead: dict, day: int, error: str) -> bool:
    """Fire when an email send fails."""
    username = lead.get("username") or "unknown"
    biz = lead.get("business_name") or f"@{username}"
    payload = {
        "embeds": [{
            "title": f"⚠️ Send failed — Day {day} to {biz}",
            "description": f"**Error:** {error[:400]}",
            "color": 0xED4245,  # red
            "footer": {"text": "Vidora · Outreach"},
        }]
    }
    return _post(payload)


def send_weekly_report(stats: dict) -> bool:
    """Post weekly stats summary."""
    payload = {
        "embeds": [{
            "title": "📊 Vidora — Weekly Report",
            "fields": [
                {"name": "Leads found", "value": str(stats.get("leads_this_week", 0)), "inline": True},
                {"name": "Emails sent", "value": str(stats.get("emails_this_week", 0)), "inline": True},
                {"name": "Replies received", "value": str(stats.get("replies_this_week", 0)), "inline": True},
                {"name": "Total leads", "value": str(stats.get("total_leads", 0)), "inline": True},
                {"name": "Contacted", "value": str(stats.get("contacted", 0)), "inline": True},
                {"name": "Qualified", "value": str(stats.get("qualified", 0)), "inline": True},
            ],
            "color": 0x5865F2,  # blurple
            "footer": {"text": "Vidora · Weekly digest"},
        }]
    }
    return _post(payload)


def test_webhook() -> bool:
    """Send a test message to confirm the webhook is working."""
    payload = {
        "embeds": [{
            "title": "🟢 Vidora connected",
            "description": "Discord notifications are active. You'll receive alerts for replies, run completions, and weekly reports here.",
            "color": 0x57F287,
        }]
    }
    return _post(payload)

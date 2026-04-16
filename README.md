# Vidora — AI Outbound Intelligence System

Automated lead generation, scoring, and cold email outreach for media production.  
Targets local businesses (aesthetic clinics, dental practices, etc.) on Google Maps, analyses their Instagram presence and website quality, scores them with Claude AI, and sends personalised cold emails with automated follow-ups.

---

## System Overview

```
Google Maps → Instagram (Multilogin) → Website Analyser → Claude Vision
       ↓                                                        ↓
  Lead Scoring ← Competitor Benchmark ← Claude Text ← Content Analysis
       ↓
  PDF Audit Report + Email Copy (Claude) → SQLite DB → Flask Dashboard
       ↓
  Zoho SMTP (Day 1 email) → IMAP Monitor → Follow-ups (Day 3, Day 7)
       ↓
  Discord Notifications
```

---

## Directory Structure

```
C:/vidora/
├── vidora_scout_final.py      # Main pipeline (Maps → Instagram → score → email → PDF)
├── daily_run.py               # Daily automation wrapper (called by Task Scheduler)
├── website_analyzer.py        # HTTP website scoring module (10 signals, 0-10)
├── dashboard/
│   ├── app.py                 # Flask web UI (port 8080)
│   ├── db.py                  # SQLite helpers
│   ├── outreach.py            # SMTP send + follow-up sequence builder
│   ├── imap_monitor.py        # Zoho IMAP reply monitor (every 15 min)
│   ├── pipeline.py            # Dashboard pipeline trigger + CSV import
│   ├── pdf_audit.py           # ReportLab premium PDF generator
│   ├── discord.py             # Discord webhook notifications
│   └── templates/             # Jinja2 HTML templates
│       ├── base.html
│       ├── home.html
│       ├── leads.html         # Leads list with bulk actions
│       ├── lead_detail.html   # Full lead profile + outreach controls
│       ├── run.html           # Pipeline trigger
│       ├── settings.html      # All config in one page
│       └── run_detail.html
├── audits/                    # Generated PDF audit reports
├── logs/                      # daily_YYYY-MM-DD.log, batch_*.log
├── leads_aesthetic.csv        # Aesthetic clinic batch output
├── leads_dental.csv           # Dental clinic batch output
├── vidora.db                  # SQLite database
├── zoho_email.txt             # SMTP/IMAP login email
├── zoho_pass.txt              # SMTP/IMAP password
├── google_api_key.txt         # Google Places API key
└── discord_webhook.txt        # Discord webhook URL
```

---

## Setup

### 1. Python dependencies

```bash
pip install flask anthropic requests selenium reportlab pillow
```

### 2. Credentials

| File | Contents |
|------|----------|
| `C:/vidora/zoho_email.txt` | `louisb@innoviteai.com` |
| `C:/vidora/zoho_pass.txt` | Zoho SMTP/IMAP password |
| `C:/vidora/google_api_key.txt` | Google Places API key |
| `C:/vidora/discord_webhook.txt` | Discord webhook URL |

Anthropic API key is stored in the database (`Settings` page in the dashboard).

### 3. Multilogin

Multilogin desktop app must be running for Instagram data collection.  
Profile ID: `440c4445-407b-48d9-bbd1-c8e203477c3d`  
ML account: `innoviteecom@gmail.com`

### 4. Start the dashboard

```bash
cd C:/vidora
python -m dashboard.app
```

Dashboard runs at `http://localhost:8080` (or `http://194.31.142.127:8080`).

---

## Running the Pipeline

### Manual run (from dashboard)
Navigate to **Run** → set query and lead count → click **New run**.

### CLI run

```bash
cd C:/vidora
python vidora_scout_final.py \
  --source maps \
  --query "aesthetic clinic manchester" \
  --leads 20 \
  --output C:/vidora/leads_aesthetic.csv \
  --audits-dir C:/vidora/audits
```

### Daily automated run
Windows Task Scheduler triggers `daily_run.py` at **08:00 every day**.  
Reads `default_leads_per_run` and `default_location` from DB settings.  
Logs to `C:/vidora/logs/daily_YYYY-MM-DD.log`.

---

## Lead Scoring

Each lead receives an **overall_score (0–10)** composed of:

| Component | Weight | Source |
|-----------|--------|--------|
| Content quality | 50% | Claude Vision (6 dimensions) |
| Website score | 25% | `website_analyzer.py` (10 signals) |
| Google Maps rating | 25% | Google Places API |

**Grades:**  A (8+) · B (6–8) · C (4–6) · D (<4)

**Priority flag** set when: `overall_score ≥ 7`, `followers ≥ 500`, `maps_review_count ≥ 50`, `business_intent_score ≥ 7`.

---

## Email Sequence

| Day | Subject | Trigger |
|-----|---------|---------|
| 1 | Claude-generated (specific hook) | Manual send from dashboard |
| 3 | `Re: [Day 1 subject]` | Auto — 3 days after Day 1 send |
| 7 | `Re: [Day 1 subject]` | Auto — 7 days after Day 1 send |

- **Day 1**: Claude Sonnet writes a personalised email using one of four patterns (Specific Observation, Quiet Competitor Drop, Effortless Credential, Yes/No Close). KSI social proof line included.
- **Day 3**: Competitor-specific follow-up referencing the same named competitor from the benchmark.
- **Day 7**: Scarcity close ("one spot left this month").
- All emails sent from `louisb@innoviteai.com` via Zoho SMTP (SSL, port 465).
- Daily send cap: 50 emails/day across all sequence steps.
- Follow-ups automatically cancelled when a reply is detected.

---

## IMAP Reply Monitor

Checks `imap.zoho.eu:993` every **15 minutes** for replies from lead email addresses.

On reply detected:
1. Lead status updated to `replied`
2. Pending follow-ups cancelled
3. Discord notification sent with reply preview

---

## PDF Audit Reports

Generated for every lead. Sections:

1. **Executive Summary** — 3 data-derived bullets
2. **Business Overview** — reviews, followers, ER, website score, rating, posting frequency
3. **Content Analysis** — score bars for 6 dimensions + weaknesses + pitch paragraph
4. **Website Analysis** — SSL/mobile/CTA/contact checks, load time, top weaknesses
5. **Competitor Intelligence** — target vs top 3 competitors table (target column in gold)
6. **Revenue Gap** — estimated £/month missed based on ER gap vs industry average
7. **Recommended Next Steps** — 3 data-driven actionable steps

Reports saved to `C:/vidora/audits/` and downloadable from the lead detail page.

---

## Dashboard Features

- **Leads list**: grade badges, score, intent, followers, ER, website score, status tabs, bulk delete, export CSV, copy email to clipboard
- **Lead detail**: full Instagram stats, website analysis panel, competitor benchmark panel, outreach log, follow-up queue, send Day 1 / Day 3 / Day 7 buttons, PDF download
- **Pipeline stats bar**: leads today, emails today, reply rate (this week), best grade in queue
- **Settings**: all email templates, sender identity, API key, Discord webhook test, CSV import

---

## Discord Notifications

| Event | Trigger |
|-------|---------|
| Run complete | End of each pipeline run |
| Send failed | SMTP failure on any email |
| Reply received | IMAP monitor detects a reply |
| Weekly report | Monday 08:00 via n8n webhook |

---

## n8n Webhooks

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/run-status` | GET | Current pipeline state |
| `/api/check-replies` | POST | Trigger immediate inbox check |
| `/api/weekly-report` | POST | Send Discord weekly stats |
| `/api/discord-test` | POST | Test Discord webhook |

All POST endpoints require header `X-Vidora-Key` matching `VIDORA_SECRET` env var.

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API (fallback if not in DB) |
| `VIDORA_SECRET` | Shared secret for n8n API endpoints |

---

## Tech Stack

- **Python 3.13** · Flask · SQLite · ReportLab · Anthropic SDK
- **Claude Sonnet 4.6** — Vision analysis, competitor enrichment, email copy
- **Multilogin + Selenium** — Instagram data collection
- **Zoho Mail** — SMTP send (port 465 SSL) + IMAP monitor (port 993 SSL)
- **Google Places API** — Maps search + business details
- **Discord webhooks** — Notifications
- **Windows Task Scheduler** — Daily 08:00 automation

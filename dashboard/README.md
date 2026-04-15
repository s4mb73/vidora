# Vidora Dashboard

Dark-themed Flask dashboard for the Vidora lead-generation pipeline.
Pairs with `vidora_scout_final.py` in the repo root.

## Install

```bash
pip install -r dashboard/requirements.txt
```

## Run

From the repo root (`C:\vidora\`):

```bash
python run_dashboard.py
```

Open http://localhost:8080.

## First-time setup

1. Go to **Settings** and paste your Anthropic API key.
2. Optionally seed demo data so you can click around immediately:
   ```bash
   python -m dashboard.seed
   ```
3. Head to **Run pipeline** and click *Start run*.

## Layout

```
dashboard/
  app.py          Flask app + routes
  db.py           SQLite schema & helpers
  pipeline.py     Background runner around vidora_scout_final
  pdf_audit.py    ReportLab audit PDF generator
  seed.py         Demo data
  templates/      Jinja2 templates
  static/         CSS
  data/
    vidora.db     SQLite database (gitignored)
    audits/       PDF audits per lead (gitignored)
```

## Data model

Each lead stores everything that `vidora_scout_final.analyse()` returns:
the six sub-scores, top weaknesses, strengths, personalised pitch,
business intent (type, selling signals, location signals, match flag),
plus sales pipeline fields (status, notes).

## Pipeline integration

The dashboard imports `vidora_scout_final` as a module and drives its
existing helpers directly (`signin`, `start_profile`, `collect_usernames`,
`screenshot_creator`, `analyse`). Each analysed lead is persisted to
SQLite and rendered to a PDF audit immediately, so you can review
results while a long run is still in progress.

If Multilogin is not installed on the machine running the dashboard
(e.g. a server without a GUI), the run will fail with a clear error in
the run log rather than taking down the web UI.

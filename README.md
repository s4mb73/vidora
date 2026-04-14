# IG Lead Engine

> AI-powered Instagram content quality analyser for media production agencies.
> Evaluate creator content, score production quality, and generate personalised outreach pitches — automatically.

---

## What it does

1. Takes screenshots and video frames from an Instagram creator's profile
2. Sends them to Claude Vision for deep production quality analysis
3. Scores across 11 dimensions (lighting, composition, editing, stability, setup, and more)
4. Generates a personalised outreach pitch based on the specific weaknesses found
5. Exports a scored lead sheet to CSV for your CRM

**Designed to work with an Android emulator (BlueStacks / Android Studio) + ADB for automated capture.**

---

## Quick start

### 1. Clone the repo
```bash
git clone https://github.com/yourusername/ig-lead-engine.git
cd ig-lead-engine
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set your Anthropic API key
```bash
export ANTHROPIC_API_KEY=your_key_here
```
Get your key at [console.anthropic.com](https://console.anthropic.com)

### 4. Run on a creator
```bash
# Photos only
python src/analyser.py --folder ./screenshots/@creator --username @creator

# Photos + video frames
python src/analyser.py \
  --folder ./screenshots/@creator \
  --username @creator \
  --video-frames ./video_frames/@creator \
  --output leads.csv
```

---

## Full workflow with emulator

### Step 1 — Capture video frames
With your Android emulator running and ADB connected:
```bash
# Check ADB connection
adb devices

# Play a video in the emulator, then immediately run:
python src/video_capture.py \
  --duration 30 \
  --output ./video_frames/@creator/video_01
```

### Step 2 — Analyse
```bash
python src/analyser.py \
  --folder ./screenshots/@creator \
  --username @creator \
  --video-frames ./video_frames/@creator \
  --output leads.csv
```

### Step 3 — Batch run multiple creators
```bash
# Structure your screenshots folder like:
# screenshots/
#   @creator1/  ← photos here
#   @creator2/
#   @creator3/

python src/batch.py \
  --root ./screenshots \
  --output leads.csv \
  --grade-filter B   # Only export A and B grade leads
```

---

## Scoring dimensions

| Category | Dimensions scored |
|----------|------------------|
| Photos | Lighting, Composition, Editing & colour, Brand consistency, Overall |
| Video | Stability, Lighting consistency, Production setup, Editing sophistication, Framing |

### Lead grades
| Grade | Meaning |
|-------|---------|
| **A** | High priority — clear production gaps, audience worth investing in |
| **B** | Good opportunity — noticeable issues, likely open to upgrading |
| **C** | Marginal — some issues but may not be ready to invest |
| **D** | Not a fit — content already strong or audience too small |

---

## CSV export fields

The output CSV includes everything your sales team needs:

- `username`, `lead_grade`, `overall_score`, `priority_flag`
- Individual scores for all 11 dimensions
- `photo_weakness_1/2/3` and `video_weakness_1/2/3` — specific, actionable
- `production_setup_observed` — what gear Claude could see
- `upgrade_potential` — high / medium / low
- `personalised_pitch` — ready-to-use outreach message
- `sales_notes` — internal notes for your team

---

## Project structure

```
ig-lead-engine/
├── src/
│   ├── analyser.py        # Core AI analysis engine
│   ├── video_capture.py   # ADB frame capture module
│   └── batch.py           # Batch runner for multiple creators
├── docs/
│   ├── setup.md           # Detailed setup guide
│   └── appium.md          # Appium automation guide
├── examples/
│   └── sample_output.csv  # Example lead report output
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Requirements

- Python 3.11+
- Anthropic API key
- ADB (Android Debug Bridge) — for video capture
- Android emulator (BlueStacks or Android Studio AVD)
- OpenCV — for smart frame extraction (optional, falls back to even sampling)

---

## Roadmap

- [ ] Appium integration for fully automated emulator browsing
- [ ] Airtable / HubSpot direct push
- [ ] Scheduling (run nightly, export fresh leads each morning)
- [ ] Web dashboard UI
- [ ] Multi-tenant SaaS wrapper

---

## License

MIT

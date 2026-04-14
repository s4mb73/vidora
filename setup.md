# Setup Guide

## Prerequisites

### Python 3.11+
```bash
python --version  # Must be 3.11 or higher
```

### ADB (Android Debug Bridge)
ADB comes bundled with Android Studio. After installing:
```bash
adb version  # Should print version info
```

Add ADB to your PATH if needed:
- **Mac**: `export PATH=$PATH:~/Library/Android/sdk/platform-tools`
- **Windows**: Add `C:\Users\YOU\AppData\Local\Android\Sdk\platform-tools` to System PATH
- **Linux**: `export PATH=$PATH:~/Android/Sdk/platform-tools`

---

## Installation

```bash
git clone https://github.com/yourusername/ig-lead-engine.git
cd ig-lead-engine
pip install -r requirements.txt
```

---

## API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Set it as an environment variable:

```bash
# Mac / Linux — add to ~/.zshrc or ~/.bashrc for persistence
export ANTHROPIC_API_KEY=sk-ant-...

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

Or create a `.env` file (never commit this):
```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Emulator Setup

### Option A — BlueStacks
1. Download and install [BlueStacks](https://www.bluestacks.com)
2. Enable ADB: Settings → Advanced → Enable Android Debug Bridge
3. Connect: `adb connect 127.0.0.1:5555`
4. Verify: `adb devices` — should show your emulator

### Option B — Android Studio AVD
1. Install [Android Studio](https://developer.android.com/studio)
2. Create a virtual device: AVD Manager → Create Virtual Device
3. Start the emulator — ADB connects automatically
4. Verify: `adb devices`

### Install Instagram on the emulator
- BlueStacks: search Instagram in the Play Store built in
- Android Studio AVD: `adb install instagram.apk` (download APK from APKPure)

---

## Screenshot tips

For best analysis results:
- Capture 6–9 recent posts per creator
- Include both portrait and landscape shots if available
- Screenshot the full post, not just the thumbnail
- Higher resolution = better analysis quality

Suggested folder structure:
```
screenshots/
  @creator1/
    01.png
    02.png
    03.png
  @creator2/
    01.jpg
    02.jpg
```

---

## Costs

Each creator analysis makes 3 API calls to Claude:
- Photo analysis: ~500-800 input tokens + images
- Video analysis: ~500-800 input tokens + frames
- Pitch generation: ~300 input tokens

Approximate cost per creator: **$0.05–$0.15** depending on image count.
At 100 creators/day: ~$5–$15/day in API costs.

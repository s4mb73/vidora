# -*- coding: utf-8 -*-
"""
Vidora Scout — Final Version
------------------------------
Connects to Multilogin, starts your IG browser profile,
browses Instagram explore, screenshots creators, analyses
with Claude Vision, exports scored leads to CSV.

Usage:
    python vidora_scout_final.py --leads 5 --output leads.csv
"""

import os, sys, time, base64, json, csv, argparse, requests, hashlib, urllib3
from pathlib import Path
from datetime import datetime

urllib3.disable_warnings()

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chromium.options import ChromiumOptions
    from selenium.common.exceptions import TimeoutException
except ImportError:
    print("ERROR: pip install selenium")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic")
    sys.exit(1)

# -- Your Multilogin config --------------------------------------------------
ML_EMAIL      = "innoviteecom@gmail.com"
ML_PASS_FILE  = "C:/vidora/pass.txt"
FOLDER_ID     = "3fcc8abd-1429-45ea-9383-1e71db538bc0"
PROFILE_ID    = "440c4445-407b-48d9-bbd1-c8e203477c3d"
MLX_API       = "https://api.multilogin.com"
MLX_LAUNCHER  = "https://127.0.0.1:45001/api/v2"
LOCALHOST     = "http://127.0.0.1"

# -- Timings -----------------------------------------------------------------
SHORT_WAIT, MEDIUM_WAIT, LONG_WAIT = 2, 4, 7


def signin() -> str:
    pw = open(ML_PASS_FILE).read().strip()
    h = hashlib.md5(pw.encode()).hexdigest()
    r = requests.post(f"{MLX_API}/user/signin",
        json={"email": ML_EMAIL, "password": h},
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    if r.status_code != 200:
        raise Exception(f"Login failed: {r.text}")
    token = r.json()["data"]["token"]
    print("  Multilogin: authenticated")
    return token


def start_profile(token: str) -> str:
    r = requests.get(
        f"{MLX_LAUNCHER}/profile/f/{FOLDER_ID}/p/{PROFILE_ID}/start?automation_type=selenium",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        verify=False
    )
    if r.status_code != 200:
        raise Exception(f"Failed to start profile: {r.text}")
    port = r.json()["data"]["port"]
    print(f"  Profile started on port {port}")
    return port


def stop_profile(token: str):
    try:
        requests.get(
            f"https://127.0.0.1:45001/api/v1/profile/stop/p/{PROFILE_ID}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            verify=False
        )
        print("  Profile stopped")
    except Exception:
        pass


def connect_driver(port: str) -> webdriver.Remote:
    options = ChromiumOptions()
    driver = webdriver.Remote(
        command_executor=f"{LOCALHOST}:{port}",
        options=options
    )
    print("  Selenium: connected")
    return driver


def check_logged_in(driver):
    driver.get("https://www.instagram.com/")
    time.sleep(LONG_WAIT)
    if "accounts/login" in driver.current_url:
        raise Exception(
            "Not logged into Instagram on this profile.\n"
            "Open Multilogin, start the IG 1 profile manually, log into instagram.com, then run again."
        )
    print("  Instagram: logged in")


def collect_usernames(driver, limit: int) -> list:
    print(f"  Browsing explore — collecting up to {limit} creators...")
    driver.get("https://www.instagram.com/explore/")
    time.sleep(LONG_WAIT)

    usernames = set()
    scroll_attempts = 0

    while len(usernames) < limit and scroll_attempts < 20:
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
            href = a.get_attribute("href") or ""
            if (
                "instagram.com/" in href and href.endswith("/")
                and "/explore" not in href and "/reel/" not in href
                and "/p/" not in href and "/stories/" not in href
                and "/direct/" not in href and "/accounts/" not in href
                and "?" not in href
            ):
                username = href.rstrip("/").split("/")[-1]
                if username and 2 <= len(username) <= 30 and "." not in username:
                    usernames.add(username)
        if len(usernames) >= limit:
            break
        driver.execute_script("window.scrollBy(0, 1500)")
        time.sleep(SHORT_WAIT)
        scroll_attempts += 1

    result = list(usernames)[:limit]
    print(f"  Collected {len(result)} usernames")
    return result


def screenshot_creator(driver, username: str, save_dir: Path) -> list:
    profile_dir = save_dir / username
    profile_dir.mkdir(parents=True, exist_ok=True)
    shots = []

    try:
        driver.get(f"https://www.instagram.com/{username}/")
        time.sleep(MEDIUM_WAIT)

        if (
            "Page Not Found" in driver.title
            or driver.current_url == "https://www.instagram.com/"
            or "/accounts/login" in driver.current_url
        ):
            print(f"    @{username}: not accessible")
            return []

        overview = profile_dir / "00_overview.png"
        driver.save_screenshot(str(overview))
        shots.append(overview)

        post_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")
        clicked = 0
        for link in post_links[:8]:
            if clicked >= 6:
                break
            try:
                href = link.get_attribute("href") or ""
                if "/p/" not in href:
                    continue
                driver.get(href)
                time.sleep(MEDIUM_WAIT)
                shot = profile_dir / f"{clicked+1:02d}_post.png"
                driver.save_screenshot(str(shot))
                shots.append(shot)
                clicked += 1
                driver.back()
                time.sleep(SHORT_WAIT)
            except Exception:
                try:
                    driver.get(f"https://www.instagram.com/{username}/")
                    time.sleep(MEDIUM_WAIT)
                except Exception:
                    pass

        reel_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/reel/']")
        if reel_links and clicked < 6:
            try:
                driver.get(reel_links[0].get_attribute("href"))
                time.sleep(MEDIUM_WAIT)
                shot = profile_dir / f"{clicked+1:02d}_reel.png"
                driver.save_screenshot(str(shot))
                shots.append(shot)
                driver.back()
                time.sleep(SHORT_WAIT)
            except Exception:
                pass

    except Exception as e:
        print(f"    Error on @{username}: {e}")

    print(f"    @{username}: {len(shots)} screenshots")
    return shots


PROMPT = """You are an expert media production consultant evaluating an Instagram creator's content quality for a professional media production company.

Analyse these {n} screenshots from @{username}'s Instagram profile.

Score each dimension 1-10 (10 = broadcast/editorial quality, 1 = very poor):
1. LIGHTING — consistency, exposure, flattering vs harsh shadows
2. COMPOSITION — framing, backgrounds, visual clutter
3. EDITING & COLOUR — grade consistency, intentionality
4. BRAND CONSISTENCY — coherent visual identity across the feed
5. CONTENT PRODUCTION VALUE — overall production effort visible
6. OVERALL — your holistic professional judgment

Identify TOP 3 SPECIFIC WEAKNESSES. Be precise: not "bad lighting" but e.g. "single overhead bulb creates harsh downward shadows in every indoor shot".

Write a 3-4 sentence PERSONALISED OUTREACH PITCH that references specific observations, frames weaknesses as opportunities, sounds human, and ends with a soft CTA. Never mention AI.

Respond ONLY in this exact JSON (no markdown fences):
{{
  "scores": {{
    "lighting": <1-10>,
    "composition": <1-10>,
    "editing_colour": <1-10>,
    "brand_consistency": <1-10>,
    "content_production": <1-10>,
    "overall": <1-10>
  }},
  "overall_score": <average 1 decimal>,
  "lead_grade": "<A=high opportunity / B=good / C=marginal / D=not a fit>",
  "priority_flag": <true if A or B>,
  "top_weaknesses": ["<specific 1>", "<specific 2>", "<specific 3>"],
  "strengths": ["<strength 1>", "<strength 2>"],
  "personalised_pitch": "<3-4 sentence pitch>",
  "upgrade_potential": "<high/medium/low>",
  "estimated_audience_size": "<small/mid/large>",
  "sales_notes": "<internal notes>"
}}"""


def analyse(username: str, shots: list, claude) -> dict:
    if not shots:
        return None
    images = []
    for p in shots[:10]:
        if not Path(p).exists():
            continue
        ext = Path(p).suffix.lower().lstrip(".")
        mtype = "image/jpeg" if ext in ("jpg","jpeg") else "image/png"
        with open(p, "rb") as f:
            enc = base64.standard_b64encode(f.read()).decode()
        images.append({"type": "image", "source": {"type": "base64", "media_type": mtype, "data": enc}})
    if not images:
        return None
    content = images + [{"type": "text", "text": PROMPT.format(n=len(images), username=username)}]
    response = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=1200,
        messages=[{"role": "user", "content": content}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    result = json.loads(raw)
    result["username"] = username
    result["analysed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    result["screenshot_count"] = len(images)
    return result


COLOURS = {"A": "\033[92m", "B": "\033[94m", "C": "\033[93m", "D": "\033[91m"}
RESET = "\033[0m"


def print_report(r: dict):
    grade = r.get("lead_grade", "?")
    c = COLOURS.get(grade, "")
    print(f"\n{'='*62}")
    print(f"  @{r['username']}")
    print(f"  Grade: {c}{grade}{RESET}  Score: {r.get('overall_score')}/10  Priority: {'YES' if r.get('priority_flag') else 'No'}")
    print(f"  Audience: {r.get('estimated_audience_size','?')}  Upgrade: {r.get('upgrade_potential','?')}")
    print(f"{'-'*62}")
    scores = r.get("scores", {})
    for key, label in [("lighting","Lighting"),("composition","Composition"),("editing_colour","Editing & colour"),("brand_consistency","Brand"),("content_production","Production"),("overall","Overall")]:
        s = scores.get(key, 0)
        print(f"  {label:<20} {'¦'*s}{'¦'*(10-s)}  {s}/10")
    print(f"\n  WEAKNESSES:")
    for i, w in enumerate(r.get("top_weaknesses", []), 1):
        print(f"    {i}. {w}")
    print(f"\n  PITCH:")
    words = r.get("personalised_pitch","").split()
    line = "    "
    for word in words:
        if len(line) + len(word) > 60:
            print(line)
            line = "    " + word + " "
        else:
            line += word + " "
    if line.strip():
        print(line)
    if r.get("sales_notes"):
        print(f"\n  SALES: {r['sales_notes']}")
    print()


def export_csv(results: list, path: str):
    if not results:
        return
    fields = ["username","analysed_at","lead_grade","overall_score","priority_flag",
              "screenshot_count","upgrade_potential","estimated_audience_size",
              "lighting","composition","editing_colour","brand_consistency","content_production","overall",
              "weakness_1","weakness_2","weakness_3","strength_1","strength_2",
              "personalised_pitch","sales_notes"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            sc = r.get("scores", {})
            wk = r.get("top_weaknesses", [])
            st = r.get("strengths", [])
            w.writerow({
                "username": r.get("username"), "analysed_at": r.get("analysed_at"),
                "lead_grade": r.get("lead_grade"), "overall_score": r.get("overall_score"),
                "priority_flag": r.get("priority_flag"), "screenshot_count": r.get("screenshot_count"),
                "upgrade_potential": r.get("upgrade_potential"),
                "estimated_audience_size": r.get("estimated_audience_size"),
                "lighting": sc.get("lighting"), "composition": sc.get("composition"),
                "editing_colour": sc.get("editing_colour"), "brand_consistency": sc.get("brand_consistency"),
                "content_production": sc.get("content_production"), "overall": sc.get("overall"),
                "weakness_1": wk[0] if len(wk) > 0 else "",
                "weakness_2": wk[1] if len(wk) > 1 else "",
                "weakness_3": wk[2] if len(wk) > 2 else "",
                "strength_1": st[0] if len(st) > 0 else "",
                "strength_2": st[1] if len(st) > 1 else "",
                "personalised_pitch": r.get("personalised_pitch"),
                "sales_notes": r.get("sales_notes","")
            })
    print(f"\n  Exported {len(results)} leads to {path}")


def main():
    parser = argparse.ArgumentParser(description="Vidora Scout")
    parser.add_argument("--leads",           type=int, default=10)
    parser.add_argument("--output",          default="leads.csv")
    parser.add_argument("--screenshots-dir", default="C:/vidora/screenshots")
    parser.add_argument("--grade-filter",    default=None)
    parser.add_argument("--api-key",         default=None)
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key = input("Anthropic API key: ").strip()

    save_dir = Path(args.screenshots_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    claude = anthropic.Anthropic(api_key=api_key)
    grade_order = {"A":0,"B":1,"C":2,"D":3}
    filter_grade = args.grade_filter.upper() if args.grade_filter else None

    print(f"\n{'='*50}")
    print(f"  Vidora Scout")
    print(f"  Target: {args.leads} creators")
    print(f"{'='*50}\n")

    print("Authenticating...")
    token = signin()

    print("Starting browser profile...")
    port = start_profile(token)
    time.sleep(3)

    driver = None
    results = []

    try:
        driver = connect_driver(port)
        check_logged_in(driver)
        usernames = collect_usernames(driver, limit=args.leads)

        print(f"\nAnalysing {len(usernames)} creators...\n")

        for i, username in enumerate(usernames, 1):
            print(f"[{i}/{len(usernames)}] @{username}")
            shots = screenshot_creator(driver, username, save_dir)
            if not shots:
                continue
            try:
                result = analyse(username, shots, claude)
                if result:
                    print_report(result)
                    if filter_grade is None or grade_order.get(result.get("lead_grade","D"),3) <= grade_order.get(filter_grade,3):
                        results.append(result)
            except Exception as e:
                print(f"    Analysis error: {e}")
            time.sleep(MEDIUM_WAIT)

    except KeyboardInterrupt:
        print("\nStopped — saving results...")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback; traceback.print_exc()
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass
        stop_profile(token)

    if results:
        export_csv(results, args.output)
        priority = [r for r in results if r.get("priority_flag")]
        print(f"\nDone! {len(results)} leads | {len(priority)} high priority | saved to {args.output}")
    else:
        print("\nNo results to export.")


if __name__ == "__main__":
    main()
"""
Vidora Scout - Final Version
------------------------------
Connects to Multilogin, starts your IG browser profile,
browses Instagram explore, screenshots creators, analyses
with Claude Vision, exports scored leads to CSV.

Usage:
    python vidora_scout_final.py --leads 5 --output leads.csv
"""

import os, sys, time, base64, json, csv, argparse, requests, hashlib, urllib3, re
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

urllib3.disable_warnings()

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chromium.options import ChromiumOptions
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
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
    pw = open(ML_PASS_FILE, encoding='utf-8').read().strip()
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


IG_USER_FILE = "C:/vidora/ig_user.txt"
IG_PASS_FILE = "C:/vidora/ig_pass.txt"


def ensure_logged_in(driver):
    """Visit instagram.com and log in automatically if not already logged in.
    The Multilogin profile persists the session, so subsequent runs skip the login form."""
    driver.get("https://www.instagram.com/")
    time.sleep(LONG_WAIT)

    if "accounts/login" not in driver.current_url:
        print("  Instagram: already logged in")
        return

    # --- need to log in ---
    username = open(IG_USER_FILE, encoding='utf-8').read().strip()
    password = open(IG_PASS_FILE, encoding='utf-8').read().strip()

    if not username or not password:
        raise Exception(
            "Instagram credentials missing.\n"
            f"Fill in {IG_USER_FILE} and {IG_PASS_FILE} then run again."
        )

    print("  Instagram: not logged in - signing in...")

    wait = WebDriverWait(driver, 20)

    # Type username
    user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
    user_field.clear()
    for ch in username:          # character-by-character avoids paste-detection blocks
        user_field.send_keys(ch)
        time.sleep(0.05)

    # Type password
    pass_field = driver.find_element(By.NAME, "password")
    pass_field.clear()
    for ch in password:
        pass_field.send_keys(ch)
        time.sleep(0.05)

    time.sleep(0.5)

    # Submit
    submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    submit.click()

    # Wait for redirect away from login page (up to 20 s)
    try:
        wait.until(lambda d: "accounts/login" not in d.current_url)
    except TimeoutException:
        raise Exception("Instagram login timed out - still on login page. Check credentials.")

    time.sleep(SHORT_WAIT)

    # Dismiss "Save your login info?" if it appears
    for xpath in [
        "//button[contains(text(),'Not Now')]",
        "//button[contains(text(),'Not now')]",
        "//button[contains(text(),'Skip')]",
    ]:
        try:
            driver.find_element(By.XPATH, xpath).click()
            time.sleep(SHORT_WAIT)
            break
        except Exception:
            pass

    # Dismiss push-notification prompt if it appears
    for xpath in [
        "//button[contains(text(),'Not Now')]",
        "//button[contains(text(),'Not now')]",
    ]:
        try:
            driver.find_element(By.XPATH, xpath).click()
            time.sleep(SHORT_WAIT)
            break
        except Exception:
            pass

    if "accounts/login" in driver.current_url:
        raise Exception("Instagram login failed - still on login page after submit.")

    print("  Instagram: login successful (session saved to Multilogin profile)")


_IG_SKIP = {
    "explore", "reels", "stories", "direct", "accounts", "p",
    "reel", "tv", "ar", "live", "locations", "tags", "about",
    "privacy", "help", "press", "api", "jobs", "legal",
    "www", "static", "rsrc", "cdninstagram", "fbcdn",
    "graphql", "query", "o1", "o2", "o3",
}

# Matches "username":"somehandle" in embedded JSON - grabs real usernames, not shortcodes
_JSON_USERNAME_RE = re.compile(r'"username"\s*:\s*"([A-Za-z0-9._]{2,30})"')

# Shortcode pattern: 11 chars, alphanumeric mixed-case, no dots/underscores
_SHORTCODE_RE = re.compile(r'^[A-Za-z0-9]{9,13}$')


def _is_valid_username(u: str) -> bool:
    if not u or not (2 <= len(u) <= 30):
        return False
    if u.lower() in _IG_SKIP:
        return False
    if not re.match(r'^[A-Za-z0-9._]+$', u):
        return False
    # Reject Instagram media shortcodes: alphanumeric only, mixed-case, 9-13 chars
    if _SHORTCODE_RE.match(u) and u != u.lower() and any(c.isdigit() for c in u):
        return False
    # Reject domain fragments
    if u.count('.') > 1:
        return False
    return True


def _extract_from_links(driver) -> set:
    """Approach 1 & 2: only count links that are direct profile paths
    (exactly one path segment after the domain, not a content/nav path)."""
    found = set()
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
        href = a.get_attribute("href") or ""
        if "instagram.com/" not in href:
            continue
        clean = href.split("?")[0].split("#")[0]
        try:
            path = clean.split("instagram.com", 1)[1]   # everything after domain
        except IndexError:
            continue
        parts = [p for p in path.strip("/").split("/") if p]
        # Only direct profile links have exactly one path segment
        if len(parts) == 1 and _is_valid_username(parts[0]):
            found.add(parts[0])
    return found


def _extract_from_source(driver) -> set:
    """Approach 3: pull usernames from embedded JSON blobs using the
    'username' key — avoids matching shortcodes from URL paths."""
    try:
        source = driver.page_source
        hits = _JSON_USERNAME_RE.findall(source)
        return {u for u in hits if _is_valid_username(u)}
    except Exception:
        return set()


def _username_from_post_page(driver) -> str:
    """On a post or reel page, extract the author's username."""
    # Method A: check the URL — navigating directly gives /username/p/code/
    url = driver.current_url
    try:
        path_parts = url.split("instagram.com/")[1].strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[1] in ("p", "reel", "tv"):
            candidate = path_parts[0]
            if _is_valid_username(candidate):
                return candidate
    except (IndexError, AttributeError):
        pass

    # Method B: look for the author profile link in the post header
    for sel in [
        "header a[href]",
        "article a[href]",
        "div[role='dialog'] a[href]",
        "a[href][role='link']",
    ]:
        try:
            for a in driver.find_elements(By.CSS_SELECTOR, sel):
                href = a.get_attribute("href") or ""
                try:
                    path = href.split("instagram.com/")[1].strip("/").split("/")
                    if len(path) == 1 and _is_valid_username(path[0]):
                        return path[0]
                except IndexError:
                    continue
        except Exception:
            pass

    # Method C: JSON source
    hits = _JSON_USERNAME_RE.findall(driver.page_source)
    for u in hits:
        if _is_valid_username(u):
            return u

    return None


def collect_usernames(driver, limit: int, location: str = None) -> list:
    if location:
        loc = location.lower().strip()
        explore_urls = [
            f"https://www.instagram.com/explore/tags/{loc}/",
            f"https://www.instagram.com/explore/tags/{loc}business/",
            f"https://www.instagram.com/explore/tags/{loc}uk/",
        ]
        print(f"  Browsing location hashtags for '{location}' - collecting up to {limit} creators...")
    else:
        explore_urls = ["https://www.instagram.com/explore/"]
        print(f"  Browsing explore - collecting up to {limit} creators...")

    usernames = set()
    visited_posts = set()

    url_index = 0
    scroll_rounds = 0

    # Load the first URL
    current_url = explore_urls[url_index]
    driver.get(current_url)
    print(f"  Waiting for page to load: {current_url}")
    time.sleep(LONG_WAIT + 3)

    # Gentle scroll to trigger lazy-loading of the grid
    for _ in range(4):
        driver.execute_script("window.scrollBy(0, 600)")
        time.sleep(SHORT_WAIT)
    driver.execute_script("window.scrollTo(0, 0)")
    time.sleep(SHORT_WAIT)

    while len(usernames) < limit and scroll_rounds < 10:
        # Gather all post/reel links currently visible on the page
        post_links = []
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/'], a[href*='/reel/']"):
            href = (a.get_attribute("href") or "").split("?")[0].rstrip("/")
            if href and href not in visited_posts:
                post_links.append(href)
                visited_posts.add(href)

        print(f"  [debug] scroll={scroll_rounds} | post-links found={len(post_links)} | usernames so far={len(usernames)}")

        for href in post_links:
            if len(usernames) >= limit:
                break
            try:
                driver.get(href)
                time.sleep(MEDIUM_WAIT)
                username = _username_from_post_page(driver)
                if username:
                    print(f"    Found @{username} from {href.split('instagram.com')[1]}")
                    usernames.add(username)
                else:
                    print(f"    Could not extract username from {href.split('instagram.com')[1]}")
                driver.back()
                time.sleep(SHORT_WAIT)
            except Exception as e:
                print(f"    Error visiting post: {e}")
                try:
                    driver.get(current_url)
                    time.sleep(LONG_WAIT)
                except Exception:
                    pass

        if len(usernames) >= limit:
            break

        # Rotate to next URL or scroll for more posts on current URL
        url_index = (url_index + 1) % len(explore_urls)
        current_url = explore_urls[url_index]
        driver.get(current_url)
        time.sleep(MEDIUM_WAIT)
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 1200)")
            time.sleep(SHORT_WAIT)
        scroll_rounds += 1

    result = list(usernames)[:limit]
    print(f"  Collected {len(result)} usernames: {result}")
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


def build_prompt(username: str, n: int, location: str = None) -> str:
    if location:
        loc_display = location.strip().title() + ", UK"
        location_line = loc_display
    else:
        loc_display = "the target area"
        location_line = "not specified — score based on general signals"

    base = f"""You are an expert media production consultant evaluating an Instagram creator's content quality for a professional media production company.

Analyse these {n} screenshots from @{username}'s Instagram profile.

Score each dimension 1-10 (10 = broadcast/editorial quality, 1 = very poor):
1. LIGHTING - consistency, exposure, flattering vs harsh shadows
2. COMPOSITION - framing, backgrounds, visual clutter
3. EDITING & COLOUR - grade consistency, intentionality
4. BRAND CONSISTENCY - coherent visual identity across the feed
5. CONTENT PRODUCTION VALUE - overall production effort visible
6. OVERALL - your holistic professional judgment

Identify TOP 3 SPECIFIC WEAKNESSES. Be precise: not "bad lighting" but e.g. "single overhead bulb creates harsh downward shadows in every indoor shot".

Write a 3-4 sentence PERSONALISED OUTREACH PITCH that references specific observations, frames weaknesses as opportunities, sounds human, and ends with a soft CTA. Never mention AI.

BUSINESS INTENT ANALYSIS
Location target: {location_line}

Examine the bio text, captions, and any visible contact info in the screenshots for:
- Selling signals: "DM to book", "link in bio", "enquiries", "services", phone numbers, email addresses, booking links, price lists
- Location signals: any mention of {loc_display} in bio, location tags, captions, or business name

Classify the business type (e.g. photographer, hair salon, restaurant, personal trainer, tattoo artist, clothing brand, beauty therapist, etc.). Write "unknown" if unclear.

The IDEAL LEAD is: a {loc_display} business + poor production quality + actively selling via Instagram.
Grade A = all three present. Grade B = two of three. Grade C = one. Grade D = none.

Add these fields to your JSON (keep all existing fields too):
  "business_intent_score": <1-10, 10=actively selling>,
  "business_type": "<category>",
  "location_match": <true/false>,
  "location_signals": ["<signal1>", ...],
  "selling_signals": ["<signal1>", ...]

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
  "sales_notes": "<internal notes>",
  "business_intent_score": <1-10>,
  "business_type": "<category>",
  "location_match": <true/false>,
  "location_signals": ["<signal1>", ...],
  "selling_signals": ["<signal1>", ...]
}}"""
    return base


def analyse(username: str, shots: list, claude, location: str = None) -> dict:
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
    prompt_text = build_prompt(username, len(images), location)
    content = images + [{"type": "text", "text": prompt_text}]
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
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
        print(f"  {label:<20} {'#'*s}{'-'*(10-s)}  {s}/10")
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
    btype = r.get("business_type", "unknown")
    bintent = r.get("business_intent_score", "?")
    bloc = r.get("location_match", False)
    selling_sigs = r.get("selling_signals", [])
    print(f"  Business type: {btype}   Intent: {bintent}/10   Location match: {bloc}")
    print(f"  Selling signals: {', '.join(selling_sigs) if selling_sigs else 'none'}")
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
              "business_intent_score","business_type","location_match","location_signals","selling_signals",
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
                "business_intent_score": r.get("business_intent_score", ""),
                "business_type": r.get("business_type", ""),
                "location_match": r.get("location_match", ""),
                "location_signals": "; ".join(r.get("location_signals", [])),
                "selling_signals": "; ".join(r.get("selling_signals", [])),
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
    parser.add_argument("--location",        default=None, help="Filter by location e.g. manchester")
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
    if args.location:
        print(f"  Location: {args.location.strip().title()}, UK")
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
        ensure_logged_in(driver)
        usernames = collect_usernames(driver, limit=args.leads, location=args.location)

        print(f"\nAnalysing {len(usernames)} creators...\n")

        for i, username in enumerate(usernames, 1):
            print(f"[{i}/{len(usernames)}] @{username}")
            shots = screenshot_creator(driver, username, save_dir)
            if not shots:
                continue
            try:
                result = analyse(username, shots, claude, location=args.location)
                if result:
                    print_report(result)
                    if filter_grade is None or grade_order.get(result.get("lead_grade","D"),3) <= grade_order.get(filter_grade,3):
                        results.append(result)
            except Exception as e:
                print(f"    Analysis error: {e}")
            time.sleep(MEDIUM_WAIT)

    except KeyboardInterrupt:
        print("\nStopped - saving results...")
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

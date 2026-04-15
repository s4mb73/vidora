"""
Vidora Scout - Final Version
------------------------------
Two source modes:
  explore (default) - Browse Instagram explore/hashtags to discover creators.
  maps              - Start from Google Maps business results, then match Instagram.

Flow (maps):    Google Maps -> Instagram match -> Screenshots -> Claude Vision -> PDF Audit -> CSV
Flow (explore): Instagram explore/hashtags -> Screenshots -> Claude Vision -> PDF Audit -> CSV

Usage:
    python vidora_scout_final.py --leads 5 --output leads.csv
    python vidora_scout_final.py --source maps --query "hair salon manchester" --leads 10 --output leads.csv
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

# -- Google Maps config ------------------------------------------------------
GOOGLE_API_KEY_FILE = "C:/vidora/google_api_key.txt"
PLACES_SEARCH_URL   = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAIL_URL   = "https://maps.googleapis.com/maps/api/place/details/json"

# -- Output dirs -------------------------------------------------------------
AUDITS_DIR = Path("C:/vidora/audits")

# -- Timings -----------------------------------------------------------------
SHORT_WAIT, MEDIUM_WAIT, LONG_WAIT = 2, 4, 7


# ===========================================================================
# Multilogin
# ===========================================================================

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
    for attempt in range(10):
        try:
            driver = webdriver.Remote(
                command_executor=f"{LOCALHOST}:{port}",
                options=options
            )
            print("  Selenium: connected")
            return driver
        except Exception:
            if attempt == 9:
                raise
            time.sleep(3)
    raise Exception("Could not connect to browser")


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

    username = open(IG_USER_FILE, encoding='utf-8').read().strip()
    password = open(IG_PASS_FILE, encoding='utf-8').read().strip()

    if not username or not password:
        raise Exception(
            "Instagram credentials missing.\n"
            f"Fill in {IG_USER_FILE} and {IG_PASS_FILE} then run again."
        )

    print("  Instagram: not logged in - signing in...")

    wait = WebDriverWait(driver, 20)

    user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
    user_field.clear()
    for ch in username:
        user_field.send_keys(ch)
        time.sleep(0.05)

    pass_field = driver.find_element(By.NAME, "password")
    pass_field.clear()
    for ch in password:
        pass_field.send_keys(ch)
        time.sleep(0.05)

    time.sleep(0.5)

    submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    submit.click()

    try:
        wait.until(lambda d: "accounts/login" not in d.current_url)
    except TimeoutException:
        raise Exception("Instagram login timed out - still on login page. Check credentials.")

    time.sleep(SHORT_WAIT)

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


# ===========================================================================
# Google Maps (Places API)
# ===========================================================================

def load_google_api_key() -> str:
    key = Path(GOOGLE_API_KEY_FILE).read_text(encoding='utf-8').strip()
    if not key:
        raise Exception(f"No Google API key found in {GOOGLE_API_KEY_FILE}.")
    return key


def search_places(query: str, api_key: str) -> list:
    """Run a Places Text Search and page through all results (max 60 via 3 pages)."""
    results = []
    params = {
        "query": query,
        "key":   api_key,
        "type":  "establishment",
    }

    page = 1
    while True:
        print(f"  Fetching page {page}...")
        r = requests.get(PLACES_SEARCH_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            raise Exception(f"Places API error: {status} — {data.get('error_message', '')}")

        batch = data.get("results", [])
        results.extend(batch)
        print(f"    Got {len(batch)} results (total so far: {len(results)})")

        next_token = data.get("next_page_token")
        if not next_token or page >= 3:
            break

        # Google requires ~3 s before next_page_token becomes valid; retry up to 5x
        ready = False
        for _ in range(5):
            time.sleep(3)
            test = requests.get(
                PLACES_SEARCH_URL,
                params={"pagetoken": next_token, "key": api_key},
                timeout=10
            )
            if test.json().get("status") != "INVALID_REQUEST":
                ready = True
                break
        if not ready:
            print("    (Pagination token not ready — using results so far)")
            break
        params = {"pagetoken": next_token, "key": api_key}
        page += 1

    return results


def get_place_details(place_id: str, api_key: str) -> dict:
    """Fetch website and phone for a place."""
    params = {
        "place_id": place_id,
        "key":      api_key,
        "fields":   "website,formatted_phone_number",
    }
    r = requests.get(PLACES_DETAIL_URL, params=params, timeout=10)
    r.raise_for_status()
    result = r.json().get("result", {})
    return {
        "website": result.get("website", ""),
        "phone":   result.get("formatted_phone_number", ""),
    }


def extract_places_leads(raw: list, api_key: str, min_reviews: int) -> list:
    """Filter raw Places results by review count, fetch details, return business list."""
    filtered = [p for p in raw if p.get("user_ratings_total", 0) >= min_reviews]
    print(f"  {len(filtered)} of {len(raw)} pass the {min_reviews}+ review filter\n")

    leads = []
    for i, place in enumerate(filtered, 1):
        name    = place.get("name", "?")
        rating  = place.get("rating", "?")
        reviews = place.get("user_ratings_total", 0)
        print(f"  [{i}/{len(filtered)}] {name}  ({rating}★  {reviews} reviews)")
        try:
            details = get_place_details(place["place_id"], api_key)
            leads.append({
                "name":         name,
                "address":      place.get("formatted_address", ""),
                "rating":       rating,
                "review_count": reviews,
                "website":      details.get("website", ""),
                "phone":        details.get("phone", ""),
                "place_id":     place.get("place_id", ""),
                "maps_url":     f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id', '')}",
            })
            print(f"    website: {details.get('website') or '—'}")
        except Exception as e:
            print(f"    detail fetch error: {e}")
        time.sleep(0.1)

    return leads


# ===========================================================================
# Instagram username extraction (explore mode)
# ===========================================================================

_IG_SKIP = {
    "explore", "reels", "stories", "direct", "accounts", "p",
    "reel", "tv", "ar", "live", "locations", "tags", "about",
    "privacy", "help", "press", "api", "jobs", "legal",
    "www", "static", "rsrc", "cdninstagram", "fbcdn",
    "graphql", "query", "o1", "o2", "o3",
}

# Matches "username":"somehandle" in embedded JSON
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
    if _SHORTCODE_RE.match(u) and u != u.lower() and any(c.isdigit() for c in u):
        return False
    if u.count('.') > 1:
        return False
    return True


def _extract_from_links(driver) -> set:
    found = set()
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
        href = a.get_attribute("href") or ""
        if "instagram.com/" not in href:
            continue
        clean = href.split("?")[0].split("#")[0]
        try:
            path = clean.split("instagram.com", 1)[1]
        except IndexError:
            continue
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) == 1 and _is_valid_username(parts[0]):
            found.add(parts[0])
    return found


def _extract_from_source(driver) -> set:
    try:
        source = driver.page_source
        hits = _JSON_USERNAME_RE.findall(source)
        return {u for u in hits if _is_valid_username(u)}
    except Exception:
        return set()


def _username_from_post_page(driver) -> str:
    url = driver.current_url
    try:
        path_parts = url.split("instagram.com/")[1].strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[1] in ("p", "reel", "tv"):
            candidate = path_parts[0]
            if _is_valid_username(candidate):
                return candidate
    except (IndexError, AttributeError):
        pass

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

    current_url = explore_urls[url_index]
    driver.get(current_url)
    print(f"  Waiting for page to load: {current_url}")
    time.sleep(LONG_WAIT + 3)

    for _ in range(4):
        driver.execute_script("window.scrollBy(0, 600)")
        time.sleep(SHORT_WAIT)
    driver.execute_script("window.scrollTo(0, 0)")
    time.sleep(SHORT_WAIT)

    while len(usernames) < limit and scroll_rounds < 10:
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


# ===========================================================================
# Instagram matching (maps mode)
# ===========================================================================

def extract_ig_from_website(website_url: str) -> str | None:
    """Try to find an Instagram handle from a business website URL.

    First checks if the website URL IS an Instagram profile, then scrapes
    the site's HTML for any instagram.com links.
    """
    if not website_url:
        return None

    # Website IS an Instagram profile
    if "instagram.com/" in website_url:
        try:
            parts = website_url.split("instagram.com/")[1].strip("/").split("/")
            if parts and _is_valid_username(parts[0]):
                return parts[0]
        except IndexError:
            pass

    # Scrape the business website for IG links
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(website_url, headers=headers, timeout=8, allow_redirects=True)
        hits = re.findall(r'instagram\.com/([A-Za-z0-9._]{2,30})/?', r.text)
        for hit in hits:
            if _is_valid_username(hit):
                return hit
    except Exception:
        pass

    return None


def search_instagram_for_business(driver, business_name: str) -> str | None:
    """Use the logged-in browser to search Instagram for a business name.

    Hits Instagram's internal topsearch endpoint (requires an active session)
    and returns the first valid username from the JSON response.
    """
    try:
        from urllib.parse import quote
        url = (
            f"https://www.instagram.com/web/search/topsearch/"
            f"?query={quote(business_name)}&context=blended"
        )
        driver.get(url)
        time.sleep(SHORT_WAIT)
        hits = _JSON_USERNAME_RE.findall(driver.page_source)
        for u in hits:
            if _is_valid_username(u):
                return u
    except Exception:
        pass
    return None


def find_instagram_for_business(business: dict, driver) -> str | None:
    """Find the Instagram handle for a Google Maps business.

    Strategy:
    1. Check the business website URL/HTML for an instagram.com link (no browser).
    2. Fall back to an Instagram search via the logged-in browser.
    """
    username = extract_ig_from_website(business.get("website", ""))
    if username:
        print(f"    IG via website : @{username}")
        return username

    username = search_instagram_for_business(driver, business.get("name", ""))
    if username:
        print(f"    IG via search  : @{username}")
        return username

    print(f"    No Instagram found for: {business.get('name')}")
    return None


# ===========================================================================
# Screenshots
# ===========================================================================

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


# ===========================================================================
# Claude Vision analysis
# ===========================================================================

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
        mtype = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
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


# ===========================================================================
# PDF audit
# ===========================================================================

def generate_pdf_audit(result: dict, audits_dir: Path = AUDITS_DIR) -> Path | None:
    """Generate a branded PDF audit for a lead. Returns the path or None on failure.

    Imports dashboard.pdf_audit at call time so the standalone script works even
    when the dashboard package is not installed (PDF step is simply skipped).
    """
    try:
        from dashboard.pdf_audit import generate_audit
    except ImportError:
        return None
    try:
        audits_dir = Path(audits_dir)
        audits_dir.mkdir(parents=True, exist_ok=True)
        path = generate_audit(result, audits_dir)
        print(f"    PDF audit saved : {path.name}")
        return path
    except Exception as e:
        print(f"    PDF audit failed: {e}")
        return None


# ===========================================================================
# Reporting & export
# ===========================================================================

COLOURS = {"A": "\033[92m", "B": "\033[94m", "C": "\033[93m", "D": "\033[91m"}
RESET = "\033[0m"


def print_report(r: dict):
    grade = r.get("lead_grade", "?")
    c = COLOURS.get(grade, "")
    print(f"\n{'='*62}")
    print(f"  @{r['username']}")
    if r.get("business_name"):
        print(f"  Business : {r['business_name']}")
    print(f"  Grade: {c}{grade}{RESET}  Score: {r.get('overall_score')}/10  Priority: {'YES' if r.get('priority_flag') else 'No'}")
    print(f"  Audience: {r.get('estimated_audience_size','?')}  Upgrade: {r.get('upgrade_potential','?')}")
    print(f"{'-'*62}")
    scores = r.get("scores", {})
    for key, label in [
        ("lighting",          "Lighting"),
        ("composition",       "Composition"),
        ("editing_colour",    "Editing & colour"),
        ("brand_consistency", "Brand"),
        ("content_production","Production"),
        ("overall",           "Overall"),
    ]:
        s = scores.get(key, 0)
        print(f"  {label:<20} {'#'*s}{'-'*(10-s)}  {s}/10")
    print(f"\n  WEAKNESSES:")
    for i, w in enumerate(r.get("top_weaknesses", []), 1):
        print(f"    {i}. {w}")
    print(f"\n  PITCH:")
    words = r.get("personalised_pitch", "").split()
    line = "    "
    for word in words:
        if len(line) + len(word) > 60:
            print(line)
            line = "    " + word + " "
        else:
            line += word + " "
    if line.strip():
        print(line)
    btype      = r.get("business_type", "unknown")
    bintent    = r.get("business_intent_score", "?")
    bloc       = r.get("location_match", False)
    sell_sigs  = r.get("selling_signals", [])
    print(f"  Business type: {btype}   Intent: {bintent}/10   Location match: {bloc}")
    print(f"  Selling signals: {', '.join(sell_sigs) if sell_sigs else 'none'}")
    if r.get("maps_address"):
        print(f"  Maps address : {r['maps_address']}")
    if r.get("maps_phone"):
        print(f"  Maps phone   : {r['maps_phone']}")
    if r.get("maps_website"):
        print(f"  Maps website : {r['maps_website']}")
    if r.get("sales_notes"):
        print(f"\n  SALES: {r['sales_notes']}")
    print()


def export_csv(results: list, path: str):
    if not results:
        return
    fields = [
        "username", "analysed_at", "lead_grade", "overall_score", "priority_flag",
        "screenshot_count", "upgrade_potential", "estimated_audience_size",
        "lighting", "composition", "editing_colour", "brand_consistency",
        "content_production", "overall",
        "weakness_1", "weakness_2", "weakness_3",
        "strength_1", "strength_2",
        "business_intent_score", "business_type", "location_match",
        "location_signals", "selling_signals",
        "personalised_pitch", "sales_notes",
        # Maps fields (populated in maps mode; empty in explore mode)
        "business_name", "maps_address", "maps_phone", "maps_website",
        "maps_rating", "maps_review_count", "maps_url", "maps_place_id",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            sc = r.get("scores", {})
            wk = r.get("top_weaknesses", [])
            st = r.get("strengths", [])
            w.writerow({
                "username":               r.get("username"),
                "analysed_at":            r.get("analysed_at"),
                "lead_grade":             r.get("lead_grade"),
                "overall_score":          r.get("overall_score"),
                "priority_flag":          r.get("priority_flag"),
                "screenshot_count":       r.get("screenshot_count"),
                "upgrade_potential":      r.get("upgrade_potential"),
                "estimated_audience_size":r.get("estimated_audience_size"),
                "lighting":               sc.get("lighting"),
                "composition":            sc.get("composition"),
                "editing_colour":         sc.get("editing_colour"),
                "brand_consistency":      sc.get("brand_consistency"),
                "content_production":     sc.get("content_production"),
                "overall":                sc.get("overall"),
                "weakness_1":             wk[0] if len(wk) > 0 else "",
                "weakness_2":             wk[1] if len(wk) > 1 else "",
                "weakness_3":             wk[2] if len(wk) > 2 else "",
                "strength_1":             st[0] if len(st) > 0 else "",
                "strength_2":             st[1] if len(st) > 1 else "",
                "business_intent_score":  r.get("business_intent_score", ""),
                "business_type":          r.get("business_type", ""),
                "location_match":         r.get("location_match", ""),
                "location_signals":       "; ".join(r.get("location_signals", [])),
                "selling_signals":        "; ".join(r.get("selling_signals", [])),
                "personalised_pitch":     r.get("personalised_pitch"),
                "sales_notes":            r.get("sales_notes", ""),
                "business_name":          r.get("business_name", ""),
                "maps_address":           r.get("maps_address", ""),
                "maps_phone":             r.get("maps_phone", ""),
                "maps_website":           r.get("maps_website", ""),
                "maps_rating":            r.get("maps_rating", ""),
                "maps_review_count":      r.get("maps_review_count", ""),
                "maps_url":               r.get("maps_url", ""),
                "maps_place_id":          r.get("maps_place_id", ""),
            })
    print(f"\n  Exported {len(results)} leads to {path}")


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Vidora Scout")
    parser.add_argument(
        "--source", default="explore", choices=["explore", "maps"],
        help="'explore' = Instagram explore/hashtags (default); 'maps' = Google Maps then Instagram match"
    )
    parser.add_argument(
        "--query", default=None,
        help="Google Places search query (maps mode only). E.g. 'hair salon manchester'"
    )
    parser.add_argument(
        "--min-reviews", type=int, default=10,
        help="Minimum Google review count to include a business (maps mode)"
    )
    parser.add_argument("--leads",           type=int, default=10)
    parser.add_argument("--output",          default="leads.csv")
    parser.add_argument("--screenshots-dir", default="C:/vidora/screenshots")
    parser.add_argument("--audits-dir",      default="C:/vidora/audits")
    parser.add_argument("--grade-filter",    default=None)
    parser.add_argument("--api-key",         default=None)
    parser.add_argument(
        "--location", default=None,
        help="Location bias for scoring/hashtags e.g. manchester"
    )
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key = input("Anthropic API key: ").strip()

    save_dir   = Path(args.screenshots_dir)
    audits_dir = Path(args.audits_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    audits_dir.mkdir(parents=True, exist_ok=True)

    claude       = anthropic.Anthropic(api_key=api_key)
    grade_order  = {"A": 0, "B": 1, "C": 2, "D": 3}
    filter_grade = args.grade_filter.upper() if args.grade_filter else None

    print(f"\n{'='*50}")
    print(f"  Vidora Scout")
    print(f"  Source : {args.source}")
    print(f"  Target : {args.leads} leads")
    if args.location:
        print(f"  Location: {args.location.strip().title()}, UK")
    print(f"{'='*50}\n")

    # -----------------------------------------------------------------------
    # Maps mode: Google Places -> Instagram match -> Screenshots -> Analyse
    # -----------------------------------------------------------------------
    if args.source == "maps":
        query = args.query or f"business {args.location or 'manchester'}"
        print(f"Google Maps search: '{query}'\n")

        google_key = load_google_api_key()
        raw        = search_places(query, google_key)
        businesses = extract_places_leads(raw, google_key, args.min_reviews)
        businesses = businesses[:args.leads]

        if not businesses:
            print("No businesses found. Try a different --query or lower --min-reviews.")
            return

        print(f"\nFound {len(businesses)} businesses — starting browser for IG matching...\n")

        print("Authenticating Multilogin...")
        token = signin()
        port  = start_profile(token)
        time.sleep(3)

        driver  = None
        results = []

        try:
            driver = connect_driver(port)
            ensure_logged_in(driver)

            for i, business in enumerate(businesses, 1):
                print(f"\n[{i}/{len(businesses)}] {business['name']}")
                username = find_instagram_for_business(business, driver)
                if not username:
                    continue

                print(f"  Instagram : @{username}")
                shots = screenshot_creator(driver, username, save_dir)
                if not shots:
                    continue

                try:
                    result = analyse(username, shots, claude, location=args.location)
                    if result:
                        # Attach Maps metadata to the result
                        result["business_name"]     = business["name"]
                        result["maps_address"]      = business["address"]
                        result["maps_phone"]        = business["phone"]
                        result["maps_website"]      = business["website"]
                        result["maps_rating"]       = business["rating"]
                        result["maps_review_count"] = business["review_count"]
                        result["maps_url"]          = business["maps_url"]
                        result["maps_place_id"]     = business["place_id"]

                        print_report(result)
                        generate_pdf_audit(result, audits_dir)

                        if filter_grade is None or \
                                grade_order.get(result.get("lead_grade", "D"), 3) <= grade_order.get(filter_grade, 3):
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

    # -----------------------------------------------------------------------
    # Explore mode: Instagram explore/hashtags -> Screenshots -> Analyse
    # -----------------------------------------------------------------------
    else:
        print("Authenticating Multilogin...")
        token = signin()
        port  = start_profile(token)
        time.sleep(3)

        driver  = None
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
                        generate_pdf_audit(result, audits_dir)
                        if filter_grade is None or \
                                grade_order.get(result.get("lead_grade", "D"), 3) <= grade_order.get(filter_grade, 3):
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

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

import os, sys, time, base64, json, csv, argparse, requests, hashlib, urllib3, re, urllib.parse
from pathlib import Path
from datetime import datetime

try:
    from website_analyzer import analyze_website
    _WEBSITE_ANALYZER = True
except ImportError:
    _WEBSITE_ANALYZER = False
    def analyze_website(url, **kw):
        return {}

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


def extract_places_leads(raw: list, api_key: str, min_reviews: int,
                         min_rating: float = 3.5) -> list:
    """Filter raw Places results and fetch details.

    Pre-filter criteria (logged when skipped):
      - rating >= min_rating (default 3.5)
      - review_count >= min_reviews (default 50 at call site)
      - website URL present in Place Details
    Businesses failing any check are skipped and logged.
    """
    # Step 1: rating + review count filter (no API call needed)
    passed, skipped = [], []
    for p in raw:
        rating  = p.get("rating") or 0
        reviews = p.get("user_ratings_total", 0)
        name    = p.get("name", "?")
        if reviews < min_reviews:
            skipped.append(f"  ✗ {name} — only {reviews} reviews (need {min_reviews}+)")
        elif rating < min_rating:
            skipped.append(f"  ✗ {name} — rating {rating}★ (need {min_rating}+)")
        else:
            passed.append(p)

    if skipped:
        print(f"  Pre-filter: {len(skipped)} skipped:")
        for s in skipped:
            print(s)
    print(f"  {len(passed)} of {len(raw)} pass rating/review filter\n")

    leads = []
    for i, place in enumerate(passed, 1):
        name    = place.get("name", "?")
        rating  = place.get("rating", "?")
        reviews = place.get("user_ratings_total", 0)
        print(f"  [{i}/{len(passed)}] {name}  ({rating}★  {reviews} reviews)")
        try:
            details = get_place_details(place["place_id"], api_key)
            website = details.get("website", "")
            if not website:
                print(f"    ✗ skipped — no website found")
                continue
            leads.append({
                "name":         name,
                "address":      place.get("formatted_address", ""),
                "rating":       rating,
                "review_count": reviews,
                "website":      website,
                "phone":        details.get("phone", ""),
                "place_id":     place.get("place_id", ""),
                "maps_url":     f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id', '')}",
            })
            print(f"    website: {website}")
        except Exception as e:
            print(f"    detail fetch error: {e}")
        time.sleep(0.1)

    print(f"  {len(leads)} leads after website filter\n")
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


def extract_email_from_website(website_url: str) -> str | None:
    """Scrape a business website for a contact email address.

    Tries the homepage, then /contact. Returns the first plausible email found.
    Ignores common false positives (noreply, example.com, wix, etc.).
    """
    if not website_url:
        return None

    IGNORE = {"noreply", "no-reply", "example", "wix", "wordpress", "mailchimp",
               "sentry", "support@sentry", "domain", "youremail", "info@example"}
    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    def _is_good(email: str) -> bool:
        lower = email.lower()
        if any(bad in lower for bad in IGNORE):
            return False
        # Skip image/asset filenames that happen to contain @
        if any(lower.endswith(ext) for ext in (".png", ".jpg", ".gif", ".svg")):
            return False
        return True

    def _fetch(url: str) -> list[str]:
        try:
            r = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
            return EMAIL_RE.findall(r.text)
        except Exception:
            return []

    base = website_url.rstrip("/")
    for url in [base, base + "/contact", base + "/contact-us", base + "/about"]:
        for email in _fetch(url):
            if _is_good(email):
                return email.lower()

    # Fallback: info@domain
    try:
        from urllib.parse import urlparse
        netloc = urlparse(website_url).netloc.lower().lstrip("www.")
        if netloc:
            return f"info@{netloc}"
    except Exception:
        pass

    return None


def _ig_handle_candidates(business_name: str) -> list[str]:
    """Generate plausible Instagram handle candidates from a business name.

    e.g. "City Centre Dental & Implant Clinic - Manchester"
    → ["citycentredental", "citycentredentalclinic", "centredental", ...]
    """
    import unicodedata
    # normalise and lower
    name = unicodedata.normalize("NFKD", business_name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-zA-Z0-9\s]", " ", name).lower()
    words = [w for w in name.split() if w not in {
        "the", "a", "an", "and", "or", "of", "in", "at", "for",
        "ltd", "limited", "llp", "plc", "co",
        "uk", "manchester", "london", "birmingham", "leeds",
        "salford", "stockport", "trafford",
        "&", "-", "and",
    } and len(w) >= 3]

    candidates = []
    # join all words
    candidates.append("".join(words))
    # join first 3 words
    if len(words) >= 3:
        candidates.append("".join(words[:3]))
    # join first 2 words
    if len(words) >= 2:
        candidates.append("".join(words[:2]))
    # first word only (if long enough)
    if words and len(words[0]) >= 4:
        candidates.append(words[0])
    # with underscores
    candidates.append("_".join(words))
    if len(words) >= 2:
        candidates.append("_".join(words[:2]))

    # deduplicate preserving order, filter valid length
    seen = set()
    result = []
    for c in candidates:
        c = c.strip("_")
        if c and 2 <= len(c) <= 30 and c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _verify_profile_matches(driver, username: str, business_name: str) -> bool:
    """Visit the IG profile and check whether the page content looks like this business.

    Returns True if there's a reasonable name/keyword match.
    """
    try:
        driver.get(f"https://www.instagram.com/{username}/")
        time.sleep(SHORT_WAIT)
        if (
            "Page Not Found" in driver.title
            or driver.current_url == "https://www.instagram.com/"
            or "/accounts/login" in driver.current_url
        ):
            return False
        source = driver.page_source.lower()
        # Check for any word from the business name (3+ chars) in page source
        words = [w.lower() for w in business_name.split() if len(w) >= 4]
        matches = sum(1 for w in words if w in source)
        return matches >= 1
    except Exception:
        return False


def search_instagram_for_business(driver, business_name: str) -> str | None:
    """Search Instagram's internal topsearch for a business name.

    Tries the full name, then a shortened version.
    Parses "username" keys from the JSON response.
    """
    from urllib.parse import quote

    def _try_query(q: str) -> str | None:
        try:
            url = (
                f"https://www.instagram.com/web/search/topsearch/"
                f"?query={quote(q)}&context=blended"
            )
            driver.get(url)
            time.sleep(SHORT_WAIT)
            source = driver.page_source
            # Strip any HTML wrapper (IG sometimes serves a plain JSON page)
            json_start = source.find("{")
            if json_start != -1:
                try:
                    data = json.loads(source[json_start:source.rfind("}") + 1])
                    for user in data.get("users", []):
                        u = user.get("user", {}).get("username", "")
                        if _is_valid_username(u):
                            return u
                except (json.JSONDecodeError, Exception):
                    pass
            # Regex fallback
            hits = _JSON_USERNAME_RE.findall(source)
            for u in hits:
                if _is_valid_username(u):
                    return u
        except Exception:
            pass
        return None

    # Try full name
    result = _try_query(business_name)
    if result:
        return result

    # Try first 2-3 meaningful words
    words = [w for w in business_name.split() if len(w) >= 3]
    if len(words) >= 2:
        result = _try_query(" ".join(words[:3]))
        if result:
            return result

    return None


def _google_search_instagram(driver, business_name: str) -> str | None:
    """Google search for the business Instagram page.

    Searches: site:instagram.com "{business_name}"
    Parses the first instagram.com/username result.
    """
    from urllib.parse import quote
    try:
        query = f'site:instagram.com "{business_name}"'
        url = f"https://www.google.com/search?q={quote(query)}&num=5"
        driver.get(url)
        time.sleep(MEDIUM_WAIT)
        source = driver.page_source
        # Find instagram.com/handle links in Google results
        hits = re.findall(r'instagram\.com/([A-Za-z0-9._]{2,30})/?(?:"|\s|<)', source)
        for u in hits:
            if _is_valid_username(u):
                return u
        # Also look in anchor hrefs
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='instagram.com']"):
            href = a.get_attribute("href") or ""
            m = re.search(r'instagram\.com/([A-Za-z0-9._]{2,30})/?', href)
            if m and _is_valid_username(m.group(1)):
                return m.group(1)
    except Exception:
        pass
    return None


def find_instagram_for_business(business: dict, driver) -> str | None:
    """Find the Instagram handle for a Google Maps business.

    Tries four strategies in order:
    1. Scrape the business website for an instagram.com link (no browser needed).
    2. Try plausible handle patterns derived from the business name.
    3. Instagram internal topsearch API (requires logged-in browser).
    4. Google search: site:instagram.com "{business name}".
    """
    name = business.get("name", "")

    # Strategy 1: website HTML
    username = extract_ig_from_website(business.get("website", ""))
    if username:
        print(f"    IG via website : @{username}")
        return username

    # Strategy 2: try generated handle patterns
    for candidate in _ig_handle_candidates(name):
        if _verify_profile_matches(driver, candidate, name):
            print(f"    IG via pattern : @{candidate}")
            return candidate

    # Strategy 3: Instagram internal search
    username = search_instagram_for_business(driver, name)
    if username:
        # Verify the result actually belongs to this business
        if _verify_profile_matches(driver, username, name):
            print(f"    IG via IG search: @{username}")
            return username
        else:
            print(f"    IG search returned @{username} but failed verification — skipping")

    # Strategy 4: Google search
    username = _google_search_instagram(driver, name)
    if username:
        if _verify_profile_matches(driver, username, name):
            print(f"    IG via Google  : @{username}")
            return username
        else:
            print(f"    Google returned @{username} but failed verification — skipping")

    print(f"    No Instagram found for: {name}")
    return None


# ===========================================================================
# Profile stats scraping
# ===========================================================================

def _parse_count(text: str):
    """Convert '1,234', '1.2K', '12.3M' etc. to int. Returns None on failure."""
    if not text:
        return None
    text = str(text).strip().replace(",", "").replace(" ", "")
    try:
        if text.upper().endswith("K"):
            return int(float(text[:-1]) * 1_000)
        if text.upper().endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        if text.upper().endswith("B"):
            return int(float(text[:-1]) * 1_000_000_000)
        return int(float(text))
    except (ValueError, IndexError):
        return None


def _extract_post_stats(driver) -> dict:
    """Extract likes, comments, and post date from an open post/reel page.

    Strategy:
      1. Page-source JSON patterns (old GraphQL + newer field names)
      2. aria-label DOM parsing  ("View all 1,234 likes", "1,234 likes")
      3. title-attribute / text DOM fallback
      4. <time datetime="..."> for date (still reliable)
    """
    result = {"likes": None, "comments": None, "date": None}
    source = driver.page_source

    # --- Date: <time datetime="YYYY-MM-DD..."> ---
    m = re.search(r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})', source)
    if m:
        result["date"] = m.group(1)

    # --- 1. Page-source JSON ---
    like_patterns = [
        r'"like_count"\s*:\s*(\d+)',
        r'"edge_media_preview_like"\s*:\s*\{"count"\s*:\s*(\d+)\}',
        r'"edge_liked_by"\s*:\s*\{"count"\s*:\s*(\d+)\}',
        r'"likeCount"\s*:\s*(\d+)',
    ]
    comment_patterns = [
        r'"comment_count"\s*:\s*(\d+)',
        r'"edge_media_to_parent_comment"\s*:\s*\{"count"\s*:\s*(\d+)\}',
        r'"edge_media_to_comment"\s*:\s*\{"count"\s*:\s*(\d+)\}',
        r'"commentCount"\s*:\s*(\d+)',
    ]
    for pat in like_patterns:
        m = re.search(pat, source)
        if m:
            result["likes"] = int(m.group(1))
            break
    for pat in comment_patterns:
        m = re.search(pat, source)
        if m:
            result["comments"] = int(m.group(1))
            break

    # --- 2. aria-label DOM parsing ---
    if result["likes"] is None:
        try:
            for el in driver.find_elements(By.XPATH, "//*[@aria-label]"):
                label = (el.get_attribute("aria-label") or "").lower()
                # "View all 1,234 likes" or "1,234 likes" or "Liked by 1,234 others"
                m = re.search(r"([\d,\.]+[km]?)\s*likes?", label)
                if not m:
                    m = re.search(r"liked by\s+([\d,\.]+[km]?)\s+others?", label)
                if m:
                    result["likes"] = _parse_count(m.group(1))
                    break
        except Exception:
            pass

    if result["comments"] is None:
        try:
            for el in driver.find_elements(By.XPATH, "//*[@aria-label]"):
                label = (el.get_attribute("aria-label") or "").lower()
                m = re.search(r"([\d,\.]+[km]?)\s*comments?", label)
                if m:
                    result["comments"] = _parse_count(m.group(1))
                    break
        except Exception:
            pass

    # --- 3. title / text DOM fallback for likes ---
    if result["likes"] is None:
        for sel in [
            "a[href$='/liked_by/'] span",
            "span[title]",
            "section span",
            "div[role='button'] span",
        ]:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    title = el.get_attribute("title") or ""
                    text = title or el.text or ""
                    v = _parse_count(text.replace(",", ""))
                    if v is not None and v >= 0:
                        result["likes"] = v
                        break
                if result["likes"] is not None:
                    break
            except Exception:
                pass

    return result


def _fetch_profile_api(driver, username: str) -> dict:
    """Navigate the browser to Instagram's profile info API endpoint and parse
    the JSON response.  Uses real browser navigation so all session cookies are
    sent automatically — no JS fetch, no script timeouts, no CORS issues.

    Returns the 'user' dict or {} on failure.
    Navigates back to the profile page before returning.
    """
    profile_url = f"https://www.instagram.com/{username}/"
    api_url = (
        f"https://www.instagram.com/api/v1/users/web_profile_info/"
        f"?username={username}"
    )
    try:
        driver.get(api_url)
        time.sleep(2)

        # The browser shows the raw JSON body — grab it from the <body> or <pre> tag
        try:
            body_text = driver.find_element(By.TAG_NAME, "pre").text
        except Exception:
            body_text = driver.find_element(By.TAG_NAME, "body").text

        data = json.loads(body_text)
        user = (data.get("data") or {}).get("user") or {}
        if user:
            print(f"    [api] profile data fetched for @{username}")
        return user

    except Exception as e:
        print(f"    [api] profile fetch failed: {e}")
        return {}
    finally:
        # Always return to the profile page
        driver.get(profile_url)
        time.sleep(2)


def scrape_profile_stats(driver, username: str) -> dict:
    """Extract profile stats from the currently loaded Instagram profile page.

    Primary:  _fetch_profile_api() navigates to the JSON API endpoint and parses
              the clean response — this works reliably for any logged-in session.
    Fallback: og:description meta tag — Instagram always embeds
              "328 Followers, 445 Following, 89 Posts" in the page meta.
    DOM:      bio text and website link from visible DOM elements.
    Debug:    saves page source to C:/vidora/debug_ig_source.html if all counts
              are still null after every method, so you can inspect what's there.
    """
    stats = {
        "followers": None,
        "following": None,
        "post_count": None,
        "bio_text": None,
        "bio_website": None,
        "has_link_in_bio": False,
        "last_post_date": None,
        "story_highlight_categories": [],
    }

    # ------------------------------------------------------------------ #
    # 1. JSON API via browser navigation (most reliable)                  #
    # ------------------------------------------------------------------ #
    api_user = _fetch_profile_api(driver, username)
    # After _fetch_profile_api we're back on the profile page
    source = driver.page_source

    if api_user:
        def _count(obj):
            """Handle both {"count": N} objects and bare integers."""
            if isinstance(obj, dict):
                return obj.get("count")
            if isinstance(obj, (int, float)):
                return int(obj)
            return None

        stats["followers"]  = _count(api_user.get("edge_followed_by") or api_user.get("follower_count"))
        stats["following"]  = _count(api_user.get("edge_follow")       or api_user.get("following_count"))
        stats["post_count"] = _count(api_user.get("edge_owner_to_timeline_media") or api_user.get("media_count"))
        stats["bio_text"]   = api_user.get("biography") or None

        # Website: try external_url, then bio_links list
        ext = api_user.get("external_url") or ""
        if not ext:
            for link in (api_user.get("bio_links") or []):
                if isinstance(link, dict) and link.get("url", "").startswith("http"):
                    ext = link["url"]
                    break
        if ext:
            stats["bio_website"] = ext

        # Pull post dates from API response for posting frequency
        edges = []
        timeline = api_user.get("edge_owner_to_timeline_media")
        if isinstance(timeline, dict):
            edges = timeline.get("edges") or []
        api_dates = []
        for edge in edges:
            node = edge.get("node") or {}
            ts = node.get("taken_at_timestamp") or node.get("taken_at")
            if ts:
                from datetime import datetime as _dt
                try:
                    api_dates.append(_dt.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d"))
                except Exception:
                    pass
        if api_dates:
            stats["last_post_date"] = sorted(api_dates, reverse=True)[0]

    # ------------------------------------------------------------------ #
    # 2. og:description meta tag fallback                                 #
    #    Format: "N Followers, N Following, N Posts - ..."               #
    # ------------------------------------------------------------------ #
    if stats["followers"] is None:
        m = re.search(
            r'content="([\d,\.]+[KkMmBb]?)\s*Followers?,\s*([\d,\.]+[KkMmBb]?)\s*Following,\s*([\d,\.]+[KkMmBb]?)\s*Posts?',
            source, re.I,
        )
        if m:
            stats["followers"]  = _parse_count(m.group(1))
            stats["following"]  = _parse_count(m.group(2))
            stats["post_count"] = _parse_count(m.group(3))
            print(f"    [og:desc] followers={stats['followers']}")

    # ------------------------------------------------------------------ #
    # 3. Page-source JSON patterns (both old GraphQL and newer names)     #
    # ------------------------------------------------------------------ #
    if stats["followers"] is None:
        for pat in [
            r'"edge_followed_by"\s*:\s*\{"count"\s*:\s*(\d+)\}',
            r'"follower_count"\s*:\s*(\d+)',
        ]:
            m = re.search(pat, source)
            if m:
                stats["followers"] = int(m.group(1))
                break

    if stats["following"] is None:
        for pat in [
            r'"edge_follow"\s*:\s*\{"count"\s*:\s*(\d+)\}',
            r'"following_count"\s*:\s*(\d+)',
        ]:
            m = re.search(pat, source)
            if m:
                stats["following"] = int(m.group(1))
                break

    if stats["post_count"] is None:
        for pat in [
            r'"edge_owner_to_timeline_media"\s*:\s*\{"count"\s*:\s*(\d+)',
            r'"media_count"\s*:\s*(\d+)',
        ]:
            m = re.search(pat, source)
            if m:
                stats["post_count"] = int(m.group(1))
                break

    if not stats["bio_text"]:
        m = re.search(r'"biography"\s*:\s*"([^"]{3,500})"', source)
        if m:
            stats["bio_text"] = m.group(1)

    if not stats["bio_website"]:
        m = re.search(r'"external_url"\s*:\s*"(https?://[^"]+)"', source)
        if m:
            url = m.group(1)
            if "instagram.com" not in url:
                stats["bio_website"] = url

    # ------------------------------------------------------------------ #
    # 4. DOM fallbacks (bio text and website from visible elements)       #
    # ------------------------------------------------------------------ #
    if not stats["bio_text"]:
        for sel in ["header section div span", "section div span", "header span"]:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    text = (el.text or "").strip()
                    if len(text) >= 10 and not text.replace(",", "").replace(".", "").isdigit():
                        stats["bio_text"] = text
                        break
                if stats["bio_text"]:
                    break
            except Exception:
                pass

    if not stats["bio_website"]:
        for sel in [
            "a[href*='l.instagram.com']",
            "header a[rel*='nofollow']",
            "header a[target='_blank']",
            "section a[rel*='nofollow']",
        ]:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    href = el.get_attribute("href") or ""
                    if "l.instagram.com" in href:
                        m = re.search(r"[?&]u=(https?://[^&]+)", href)
                        if m:
                            href = urllib.parse.unquote(m.group(1))
                    if href.startswith("http") and "instagram.com" not in href:
                        stats["bio_website"] = href
                        break
                if stats["bio_website"]:
                    break
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Derived fields                                                      #
    # ------------------------------------------------------------------ #
    stats["has_link_in_bio"] = bool(stats["bio_website"])

    # Story highlight categories from visible DOM buttons
    try:
        seen, cats = set(), []
        for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button'] span"):
            txt = (el.text or "").strip()
            if txt and 2 <= len(txt) <= 24 and txt not in seen:
                if not txt.replace(",", "").replace(".", "").isdigit():
                    seen.add(txt)
                    cats.append(txt)
            if len(cats) >= 8:
                break
        stats["story_highlight_categories"] = cats
    except Exception:
        pass

    # Last post date from <time datetime="..."> on the profile grid
    if not stats["last_post_date"]:
        try:
            dates = re.findall(r'datetime="(\d{4}-\d{2}-\d{2})', source)
            if dates:
                stats["last_post_date"] = sorted(dates, reverse=True)[0]
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Debug output                                                        #
    # ------------------------------------------------------------------ #
    print(
        f"    stats: followers={stats['followers']} "
        f"following={stats['following']} "
        f"posts={stats['post_count']} "
        f"bio={'yes' if stats['bio_text'] else 'NO'} "
        f"website={'yes' if stats['bio_website'] else 'no'} "
        f"last_post={stats['last_post_date'] or 'none'}"
    )

    # If counts are still null, dump source for inspection
    if stats["followers"] is None:
        debug_path = Path("C:/vidora/debug_ig_source.html")
        try:
            debug_path.write_text(source, encoding="utf-8")
            print(f"    [debug] followers still null — source saved to {debug_path}")
        except Exception:
            pass

    return stats


def _posting_frequency(dates: list) -> str | None:
    """Given a list of YYYY-MM-DD strings, return posts-per-week as a string."""
    if len(dates) < 2:
        return None
    try:
        from datetime import date as _date
        parsed = sorted(
            [_date.fromisoformat(d) for d in dates if d],
            reverse=True,
        )
        if len(parsed) < 2:
            return None
        span_days = (parsed[0] - parsed[-1]).days
        if span_days <= 0:
            return None
        posts_per_week = round(len(parsed) / (span_days / 7), 1)
        return f"{posts_per_week} posts/week"
    except Exception:
        return None


# ===========================================================================
# Screenshots
# ===========================================================================

def screenshot_creator(driver, username: str, save_dir: Path) -> tuple[list, dict]:
    """Visit the Instagram profile, take screenshots, and collect engagement stats.

    Returns (shots, profile_stats) where profile_stats contains:
        followers, following, post_count, bio_text, bio_website,
        avg_likes, avg_comments, engagement_rate, posting_frequency
    """
    profile_dir = save_dir / username
    profile_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    post_stats_list = []   # list of {"likes", "comments", "date"} per post

    profile_stats = {
        "followers": None,
        "following": None,
        "post_count": None,
        "bio_text": None,
        "bio_website": None,
        "has_link_in_bio": False,
        "last_post_date": None,
        "story_highlight_categories": [],
        "avg_likes": None,
        "avg_comments": None,
        "engagement_rate": None,
        "posting_frequency": None,
        "trend": None,
    }

    try:
        driver.get(f"https://www.instagram.com/{username}/")
        time.sleep(MEDIUM_WAIT)

        if (
            "Page Not Found" in driver.title
            or driver.current_url == "https://www.instagram.com/"
            or "/accounts/login" in driver.current_url
        ):
            print(f"    @{username}: not accessible")
            return [], profile_stats

        # --- Scrape profile header stats while on profile page ---
        header_stats = scrape_profile_stats(driver, username)
        profile_stats.update(header_stats)

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

                # Extract engagement stats from post page
                pstats = _extract_post_stats(driver)
                post_stats_list.append(pstats)

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
                pstats = _extract_post_stats(driver)
                post_stats_list.append(pstats)
                shot = profile_dir / f"{clicked+1:02d}_reel.png"
                driver.save_screenshot(str(shot))
                shots.append(shot)
                driver.back()
                time.sleep(SHORT_WAIT)
            except Exception:
                pass

    except Exception as e:
        print(f"    Error on @{username}: {e}")

    # --- Aggregate engagement stats ---
    likes_list    = [p["likes"]    for p in post_stats_list if p.get("likes")    is not None]
    comments_list = [p["comments"] for p in post_stats_list if p.get("comments") is not None]
    dates_list    = [p["date"]     for p in post_stats_list if p.get("date")]

    if likes_list:
        profile_stats["avg_likes"] = round(sum(likes_list) / len(likes_list), 1)
    if comments_list:
        profile_stats["avg_comments"] = round(sum(comments_list) / len(comments_list), 1)

    followers = profile_stats.get("followers")
    if followers and followers > 0 and likes_list:
        avg_l = profile_stats["avg_likes"] or 0
        avg_c = profile_stats["avg_comments"] or 0
        profile_stats["engagement_rate"] = round((avg_l + avg_c) / followers * 100, 2)

    # Posting frequency: prefer post-click dates; fall back to last_post_date from API
    if not dates_list and profile_stats.get("last_post_date"):
        # Can't compute frequency from a single date — leave as None
        pass
    profile_stats["posting_frequency"] = _posting_frequency(dates_list)

    # --- Trend detection: compare avg likes of first 3 vs last 3 posts ---
    if len(likes_list) >= 4:
        # post_stats_list is in visit order (newest first from profile grid)
        newest_likes = [p["likes"] for p in post_stats_list[:3] if p.get("likes") is not None]
        oldest_likes = [p["likes"] for p in post_stats_list[-3:] if p.get("likes") is not None]
        if newest_likes and oldest_likes:
            avg_new = sum(newest_likes) / len(newest_likes)
            avg_old = sum(oldest_likes) / len(oldest_likes)
            if avg_old > 0:
                change_pct = (avg_new - avg_old) / avg_old * 100
                if change_pct >= 15:
                    profile_stats["trend"] = "improving"
                elif change_pct <= -15:
                    profile_stats["trend"] = "declining"
                else:
                    profile_stats["trend"] = "stable"

    # --- Print summary ---
    f = profile_stats.get("followers")
    er = profile_stats.get("engagement_rate")
    pf = profile_stats.get("posting_frequency")
    trend = profile_stats.get("trend") or "unknown"
    print(f"    @{username}: {len(shots)} screenshots | "
          f"followers={f} | ER={er}% | {pf} | trend={trend}")

    return shots, profile_stats


# ===========================================================================
# Competitor comparison
# ===========================================================================

def screenshot_overview(driver, username: str, save_dir: Path) -> Path | None:
    """Visit a profile and take a single overview screenshot. No post clicks."""
    profile_dir = save_dir / f"_comp_{username}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        driver.get(f"https://www.instagram.com/{username}/")
        time.sleep(MEDIUM_WAIT)
        if (
            "Page Not Found" in driver.title
            or driver.current_url == "https://www.instagram.com/"
            or "/accounts/login" in driver.current_url
        ):
            return None
        path = profile_dir / "overview.png"
        driver.save_screenshot(str(path))
        return path
    except Exception as e:
        print(f"    Competitor screenshot error for @{username}: {e}")
        return None


def score_competitor(username: str, shot_path: Path, claude) -> dict | None:
    """Quick Claude Vision score for a competitor — just dimension scores, no full analysis."""
    if not shot_path or not shot_path.exists():
        return None
    try:
        with open(shot_path, "rb") as f:
            enc = base64.standard_b64encode(f.read()).decode()
        prompt = (
            f"You are scoring a competitor Instagram profile (@{username}) for a media production agency. "
            "Look at this single overview screenshot and score each dimension 1-10 "
            "(10 = broadcast/editorial quality, 1 = very poor). "
            "Respond ONLY in this JSON (no markdown):\n"
            '{"lighting":<1-10>,"composition":<1-10>,"editing_colour":<1-10>,'
            '"brand_consistency":<1-10>,"content_production":<1-10>,"overall":<1-10>,'
            '"overall_score":<average to 1 decimal>}'
        )
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": enc}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        scores = json.loads(raw)
        scores["username"] = username
        return scores
    except Exception as e:
        print(f"    Competitor scoring failed for @{username}: {e}")
        return None


def find_competitors(
    business_type: str,
    location: str,
    google_key: str,
    driver,
    save_dir: Path,
    exclude_username: str,
    claude,
    n: int = 3,
) -> list[dict]:
    """Find N competitor Instagram profiles for the same business type in the same location.

    Returns a list of dicts with enhanced keys:
    username, business_name, maps_rating, maps_review_count, website_score,
    ig_followers, ig_posting_frequency, overall_score,
    lighting, composition, editing_colour, brand_consistency, content_production, overall
    """
    loc = (location or "manchester").strip().lower()
    query = f"{business_type} {loc}"
    print(f"  Competitor search: '{query}'")

    competitors = []
    try:
        raw = search_places(query, google_key)
        candidates = extract_places_leads(raw, google_key, min_reviews=5)
    except Exception as e:
        print(f"  Competitor Places search failed: {e}")
        return []

    # Sort by user_ratings_total DESC — take most-reviewed businesses first
    candidates.sort(key=lambda b: b.get("review_count") or b.get("user_ratings_total") or 0, reverse=True)

    for biz in candidates:
        if len(competitors) >= n:
            break
        try:
            username = find_instagram_for_business(biz, driver)
            if not username or username.lower() == exclude_username.lower():
                continue
            print(f"  Competitor found: @{username} ({biz['name']})")
            shot = screenshot_overview(driver, username, save_dir)
            if not shot:
                continue
            scores = score_competitor(username, shot, claude)
            if not scores:
                continue

            # Website analysis for competitor
            comp_website_score = None
            if biz.get("website"):
                try:
                    comp_wa = analyze_website(biz["website"], business_name=biz["name"])
                    comp_website_score = comp_wa.get("website_score")
                    print(f"    Competitor website score: {comp_website_score}/10")
                except Exception as we:
                    print(f"    Competitor website analysis failed: {we}")

            # IG follower count + posting frequency via API
            ig_followers = None
            ig_posting_frequency = None
            try:
                api_user = _fetch_profile_api(driver, username)
                if api_user:
                    def _count(obj):
                        if isinstance(obj, dict):
                            return obj.get("count")
                        if isinstance(obj, (int, float)):
                            return int(obj)
                        return None
                    ig_followers = _count(api_user.get("edge_followed_by") or api_user.get("follower_count"))

                    # Derive posting frequency from timeline media timestamps
                    timeline = api_user.get("edge_owner_to_timeline_media") or {}
                    edges = timeline.get("edges") or [] if isinstance(timeline, dict) else []
                    if len(edges) >= 2:
                        timestamps = []
                        for edge in edges:
                            ts = (edge.get("node") or {}).get("taken_at_timestamp")
                            if ts:
                                timestamps.append(int(ts))
                        if len(timestamps) >= 2:
                            timestamps.sort(reverse=True)
                            span_days = (timestamps[0] - timestamps[-1]) / 86400
                            if span_days > 0:
                                posts_per_week = round((len(timestamps) - 1) / (span_days / 7), 1)
                                ig_posting_frequency = f"{posts_per_week}x/week"
                    print(f"    IG followers: {ig_followers}, freq: {ig_posting_frequency}")
            except Exception as fe:
                print(f"    Competitor API fetch failed: {fe}")

            competitors.append({
                "username": username,
                "business_name": biz["name"],
                "maps_rating": biz.get("rating"),
                "maps_review_count": biz.get("review_count") or biz.get("user_ratings_total"),
                "website_score": comp_website_score,
                "ig_followers": ig_followers,
                "ig_posting_frequency": ig_posting_frequency,
                "overall_score": scores.get("overall_score"),
                "lighting": scores.get("lighting"),
                "composition": scores.get("composition"),
                "editing_colour": scores.get("editing_colour"),
                "brand_consistency": scores.get("brand_consistency"),
                "content_production": scores.get("content_production"),
                "overall": scores.get("overall"),
            })
            print(f"    Score: {scores.get('overall_score')}/10")
            time.sleep(SHORT_WAIT)
        except Exception as e:
            print(f"  Competitor error: {e}")

    return competitors


def _compute_benchmark(target: dict, competitors: list) -> dict:
    """Compute a benchmark table comparing target against up to 3 competitors.

    composite_score = (content_score * 0.5) + (website_score * 0.25) + (maps_rating_normalized * 0.25)

    Returns a dict with keys:
    target_rank, top_competitor_name, top_competitor_username, top_competitor_maps_reviews,
    gap_to_top, biggest_advantage_dimension, biggest_advantage_gap, ranking_table
    """
    def _composite(content_score, website_score, maps_rating):
        cs = (content_score or 0) * 0.5
        ws = (website_score or 5) * 0.25
        mr_raw = (maps_rating / 5) * 10 if maps_rating else 5
        mr = mr_raw * 0.25
        return round(cs + ws + mr, 2)

    # Build target entry
    target_wa = target.get("website_analysis") or {}
    target_ws = target_wa.get("website_score") if target_wa and not target_wa.get("error") else None
    target_content = target.get("overall_score") or 0
    target_maps_rating = target.get("maps_rating")
    target_composite = _composite(target_content, target_ws, target_maps_rating)

    ranking_table = [{
        "label": target.get("business_name") or f"@{target.get('username', 'target')}",
        "is_target": True,
        "composite_score": target_composite,
        "content_score": target_content,
        "website_score": target_ws,
        "maps_rating": target_maps_rating,
        "maps_review_count": target.get("maps_review_count"),
        "ig_followers": target.get("followers"),
        "username": target.get("username"),
    }]

    for comp in competitors:
        comp_composite = _composite(
            comp.get("overall_score"),
            comp.get("website_score"),
            comp.get("maps_rating"),
        )
        ranking_table.append({
            "label": comp.get("business_name") or f"@{comp.get('username', '?')}",
            "is_target": False,
            "composite_score": comp_composite,
            "content_score": comp.get("overall_score") or 0,
            "website_score": comp.get("website_score"),
            "maps_rating": comp.get("maps_rating"),
            "maps_review_count": comp.get("maps_review_count"),
            "ig_followers": comp.get("ig_followers"),
            "username": comp.get("username"),
        })

    # Sort by composite_score DESC
    ranking_table.sort(key=lambda x: x["composite_score"], reverse=True)

    # Target rank (1-indexed)
    target_rank = next((i + 1 for i, row in enumerate(ranking_table) if row["is_target"]), None)

    # Top competitor (highest composite excluding target)
    top_comp = next((row for row in ranking_table if not row["is_target"]), None)

    gap_to_top = 0.0
    if top_comp:
        gap_to_top = round(top_comp["composite_score"] - target_composite, 2)

    # Biggest advantage dimension (where top competitor most outscores target)
    biggest_advantage_dimension = None
    biggest_advantage_gap = 0.0
    if top_comp:
        dims = {
            "lighting": (top_comp.get("content_score") or 0, target_content),
            "website_score": (top_comp.get("website_score") or 0, target_ws or 0),
        }
        # For full dimension comparison we need the raw scores from competitors list
        top_comp_raw = next((c for c in competitors if c.get("username") == top_comp.get("username")), None)
        if top_comp_raw:
            for dim in ("lighting", "composition", "editing_colour", "brand_consistency", "content_production"):
                tc_val = top_comp_raw.get(dim) or 0
                tg_val = target.get(dim) or target.get("scores", {}).get(dim, 0) if isinstance(target.get("scores"), dict) else target.get(dim) or 0
                dims[dim] = (tc_val, tg_val)
        # Website score dimension
        dims["website_score"] = (top_comp.get("website_score") or 0, target_ws or 0)

        for dim, (comp_val, tgt_val) in dims.items():
            gap = (comp_val or 0) - (tgt_val or 0)
            if gap > biggest_advantage_gap:
                biggest_advantage_gap = gap
                biggest_advantage_dimension = dim

    return {
        "target_rank": target_rank,
        "top_competitor_name": top_comp["label"] if top_comp else None,
        "top_competitor_username": top_comp["username"] if top_comp else None,
        "top_competitor_maps_reviews": top_comp["maps_review_count"] if top_comp else None,
        "gap_to_top": gap_to_top,
        "biggest_advantage_dimension": biggest_advantage_dimension,
        "biggest_advantage_gap": biggest_advantage_gap,
        "ranking_table": ranking_table,
    }


def _enrich_with_competitors(result: dict, competitors: list, benchmark: dict, claude) -> None:
    """Text-only Claude call to rewrite the pitch and sales notes referencing real competitor data.

    Called after find_competitors() + _compute_benchmark() so we have real names and scores.
    Updates result dict in place. Non-fatal — any error leaves original pitch intact.
    """
    if not competitors:
        return

    top_name = benchmark.get("top_competitor_name") or ""
    top_username = benchmark.get("top_competitor_username") or ""
    target_rank = benchmark.get("target_rank")
    gap = benchmark.get("gap_to_top") or 0
    adv_dim = benchmark.get("biggest_advantage_dimension") or ""

    comp_lines = []
    for c in competitors:
        parts = [f"  - {c.get('business_name') or '@' + c.get('username', '?')}"]
        if c.get("overall_score") is not None:
            parts.append(f"content score {c['overall_score']}/10")
        if c.get("website_score") is not None:
            parts.append(f"website {c['website_score']}/10")
        if c.get("maps_rating"):
            parts.append(f"Google {c['maps_rating']}★")
        if c.get("maps_review_count"):
            parts.append(f"{c['maps_review_count']} reviews")
        if c.get("ig_followers"):
            parts.append(f"{c['ig_followers']:,} IG followers")
        comp_lines.append(": ".join(parts[:1]) + " — " + ", ".join(parts[1:]))

    enrich_prompt = f"""You previously analysed @{result.get('username')} and wrote a pitch and sales notes.
Now I have real competitor data. Update ONLY the personalised_pitch and sales_notes fields to reference these specific competitors by name.

Target: {result.get('business_name') or '@' + result.get('username', '')}
Target overall rank: {target_rank}/4 in local market
Gap to top competitor: {gap} composite points
Top competitor: {top_name} (@{top_username}) — biggest advantage: {adv_dim}

Local competitors found:
{chr(10).join(comp_lines)}

Original pitch: {result.get('personalised_pitch', '')}
Original sales notes: {result.get('sales_notes', '')}

Rewrite the pitch (3-4 sentences) and sales notes to:
1. Name the top competitor ({top_name}) specifically — e.g. "while {top_name} nearby..."
2. Reference one concrete competitor stat (reviews, followers, or score)
3. Keep the same soft CTA tone — never mention AI
4. Sales notes should note the ranking position and biggest competitor advantage

Respond ONLY in this JSON (no markdown):
{{"personalised_pitch": "<updated pitch>", "sales_notes": "<updated sales notes>"}}"""

    try:
        print(f"  Enriching pitch with competitor context...")
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            messages=[{"role": "user", "content": enrich_prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        enriched = json.loads(raw)
        if enriched.get("personalised_pitch"):
            result["personalised_pitch"] = enriched["personalised_pitch"]
        if enriched.get("sales_notes"):
            result["sales_notes"] = enriched["sales_notes"]
        print(f"  Pitch enriched with competitor names")
    except Exception as e:
        print(f"  Pitch enrichment failed (keeping original): {e}")


def _get_kb_setting(key: str) -> str:
    """Read an optional knowledge-base setting from the dashboard DB.

    Returns "" if unset or the DB is missing. Never raises — email generation
    must still work if the dashboard isn't installed.
    """
    try:
        import sqlite3
        conn = sqlite3.connect("C:/vidora/vidora.db")
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        return (row[0] or "").strip() if row else ""
    except Exception:
        return ""


def _get_voice_guidance() -> str:
    return _get_kb_setting("email_voice_guidance")


def _get_business_context() -> str:
    return _get_kb_setting("business_context")


def _generate_email(result: dict, claude) -> None:
    """Text-only Claude call to write a personalised cold email (subject + body).

    Uses the premium copywriting system prompt with real data. Stores
    result['email_subject'] and result['email_body']. Non-fatal.
    """
    bench = result.get("competitor_benchmark") or {}
    wa = result.get("website_analysis") or {}

    # Extract posting frequency as a number (e.g. "0.1 posts/week" → "0.1")
    pf_raw = result.get("posting_frequency") or ""
    import re as _re
    pf_match = _re.search(r"([\d.]+)", pf_raw)
    posts_per_week = pf_match.group(1) if pf_match else pf_raw or "unknown"

    # Competitor data from benchmark
    ranking_table = bench.get("ranking_table") or []
    total = len(ranking_table) if ranking_table else "unknown"

    # Find top competitor's website score from ranking_table
    comp1_ws = ""
    top_comp_name = bench.get("top_competitor_name") or ""
    for row in ranking_table:
        if row.get("name") != (result.get("business_name") or result.get("username")):
            comp1_ws = row.get("website_score") or ""
            break

    data_block = f"""Business name: {result.get('business_name') or result.get('username')}
Google reviews: {result.get('maps_review_count') or 'unknown'} at {result.get('maps_rating') or 'unknown'} stars
Instagram followers: {result.get('followers') or 'unknown'}
Posts per week: {posts_per_week}
Average likes: {int(result['avg_likes']) if result.get('avg_likes') is not None else 'unknown'}
Engagement rate: {result.get('engagement_rate') or 'unknown'}%
Website score: {wa.get('website_score') or 'unknown'}/10
SSL present: {'yes' if wa.get('has_ssl') else 'no' if 'has_ssl' in wa else 'unknown'}
CTA present: {'yes' if wa.get('has_cta') else 'no' if 'has_cta' in wa else 'unknown'}
Top competitor: {top_comp_name or 'unknown'}
Competitor reviews: {bench.get('top_competitor_maps_reviews') or 'unknown'}
Competitor website score: {comp1_ws or 'unknown'}
Our rank: {bench.get('target_rank') or 'unknown'} out of {total} in this area"""

    voice = _get_voice_guidance()
    business = _get_business_context()
    business_section = (
        f"\n\nABOUT THE BUSINESS YOU'RE WRITING FOR (use these facts, never contradict them):\n{business}\n"
        if business else ""
    )
    voice_section = (
        f"\n\nVOICE GUIDANCE (honour this when writing):\n{voice}\n"
        if voice else ""
    )

    system_prompt = f"""You write cold emails for a premium outreach business.
Your emails get replies because they feel like they were written by a person who actually looked — not a tool that ran a report.
{business_section}{voice_section}
Study these high performing patterns before writing:

PATTERN 1 — THE SPECIFIC OBSERVATION:
"With [X] Google reviews at [rating] stars, [Business] has built something most clinics take years to earn. But posting [X] times a week, almost nobody outside your existing patients will ever find it."
Why it works: Makes them feel seen. Acknowledges what they have built before pointing at the gap.

PATTERN 2 — THE QUIET COMPETITOR DROP:
"[Competitor] nearby is already converting their online presence into bookings — [specific stat] vs yours."
Why it works: Specific. Real. Creates tension without alarm.

PATTERN 3 — THE EFFORTLESS CREDENTIAL:
"We produce content for KSI, Premier League footballers and some of the most followed personal brands in the UK. We work with a small number of Manchester businesses we think are ready for that level of production."
Why it works: Positions without boasting. Selective framing makes the prospect feel chosen not sold to.

PATTERN 4 — THE YES/NO CLOSE:
"Worth a look for [Business name] — yes or no?"
Why it works: Lowest friction ask possible. Removes all pressure. Easy to say yes to.

RULES — never break these:
- Maximum 4 paragraphs. Each one under 3 lines.
- Never start with "I" or "My name is"
- Never use: solutions, leverage, utilise, streamline, transform, innovative, exciting, cutting-edge, I wanted to reach out, hope this finds you well
- No exclamation marks
- Never mention AI, automation, software or technology
- Numbers are observed not computed: "67 likes" not "67.0 likes per post"
- One question only at the close. Yes or no answer.
- Sign off with "Louis" — nothing else. No title, no website, no phone.
- Sound like a trusted contact who noticed something useful — not a salesperson who ran a report

SUBJECT LINE:
Write like you noticed something, not like you want a click.
Never: "quick question", "following up", "touching base"
Format: "[Business name] — [honest observation]"
Good examples:
"MyAesthetics — Third Avenue just pulled ahead"
"Apex Dental — your reviews aren't reaching new patients"
"City Physio — something worth five minutes"

Output format — two things only, nothing else:
SUBJECT: [subject line]

[email body]"""

    # Select hook angle based on lead's weakness profile
    try:
        ppw_raw = result.get("posting_frequency") or "0"
        import re as _re2
        ppw = float(_re2.search(r"[\d.]+", str(ppw_raw)).group())
    except Exception:
        ppw = 0.0
    try:
        al = float(result.get("avg_likes") or 0)
    except Exception:
        al = 0.0
    try:
        ws_n = float(wa.get("website_score") or 10)
    except Exception:
        ws_n = 10.0
    try:
        fol = int(result.get("followers") or 0)
    except Exception:
        fol = 0

    try:
        reviews_n = int(result.get("maps_review_count") or 0)
    except Exception:
        reviews_n = 0

    if ws_n < 5 and fol > 1000:
        hook_label = "D"
        hook_hint = (
            "HOOK D — Decent social, weak website: "
            "The business has followers and is posting but the website can't convert. "
            "Open with their social strengths, then contrast with the website gap."
        )
    elif reviews_n > 200 and fol < 3000:
        hook_label = "E"
        hook_hint = (
            "HOOK E — Strong offline, small online: "
            "Impressive Google reviews but very few Instagram followers. "
            "The credibility is real but almost no one online can see it. "
            "Open with the review count as proof of quality, then contrast with the tiny online reach."
        )
    elif ppw < 1 and al > 50:
        hook_label = "A"
        hook_hint = (
            "HOOK A — Low frequency, decent engagement: "
            "When they post, people respond — the audience is clearly there. "
            "Open with the engagement signal as proof the audience exists, "
            "then point out they're barely feeding it."
        )
    elif ppw >= 2 and al < 50:
        hook_label = "B"
        hook_hint = (
            "HOOK B — High frequency, low engagement: "
            "They're putting in the effort but the content isn't landing. "
            "Open by acknowledging the posting effort, then surface the engagement gap."
        )
    else:
        hook_label = "C"
        hook_hint = (
            "HOOK C — Low everything: "
            "Strong offline reputation (reviews/rating) but almost invisible online. "
            "Open with the reputation they've built, then contrast with the silence on social."
        )

    user_msg = (
        f"HOOK TO USE: {hook_label}\n{hook_hint}\n\n"
        f"AVAILABLE DATA — use what is most striking, ignore the rest:\n{data_block}"
    )

    try:
        print(f"  Generating cold email copy...")
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()

        # Parse SUBJECT: line and body
        subject = ""
        body = ""
        if raw.startswith("SUBJECT:"):
            lines = raw.split("\n", 1)
            subject = lines[0].replace("SUBJECT:", "").strip()
            body = lines[1].strip() if len(lines) > 1 else ""
        else:
            body = raw

        if subject:
            result["email_subject"] = subject
        if body:
            result["email_body"] = body
        print(f"  Email generated: {subject}")
    except Exception as e:
        print(f"  Email generation failed: {e}")


# ===========================================================================
# Claude Vision analysis
# ===========================================================================

def build_prompt(username: str, n: int, location: str = None, profile_stats: dict = None,
                 website_analysis: dict = None, competitors: list = None,
                 competitor_benchmark: dict = None) -> str:
    if location:
        loc_display = location.strip().title() + ", UK"
        location_line = loc_display
    else:
        loc_display = "the target area"
        location_line = "not specified — score based on general signals"

    # --- Build structured data block from scraped stats ---
    ps = profile_stats or {}

    def _fmt(v, suffix=""):
        if v is None:
            return "unknown"
        if isinstance(v, float) and v == int(v):
            v = int(v)
        return f"{v}{suffix}"

    followers        = _fmt(ps.get("followers"))
    following        = _fmt(ps.get("following"))
    post_count       = _fmt(ps.get("post_count"))
    engagement_rate  = _fmt(ps.get("engagement_rate"), "%") if ps.get("engagement_rate") is not None else "unknown"
    posting_freq     = ps.get("posting_frequency") or "unknown"
    avg_likes        = _fmt(ps.get("avg_likes"))
    avg_comments     = _fmt(ps.get("avg_comments"))
    bio_text         = ps.get("bio_text") or "not extracted"
    bio_website      = ps.get("bio_website") or "none"
    has_link_in_bio  = "yes" if ps.get("has_link_in_bio") else "no"
    last_post_date   = ps.get("last_post_date") or "unknown"
    highlights       = ", ".join(ps.get("story_highlight_categories") or []) or "none detected"
    trend            = ps.get("trend") or "unknown"

    # Contextual commentary to help Claude interpret the numbers
    er_val = ps.get("engagement_rate")
    if er_val is not None:
        if er_val >= 6:
            er_context = "(high — strong audience connection)"
        elif er_val >= 3:
            er_context = "(average for this follower range)"
        elif er_val >= 1:
            er_context = "(below average — content not resonating)"
        else:
            er_context = "(very low — possible ghost followers or inactive audience)"
    else:
        er_context = ""

    # Trend context
    if trend == "improving":
        trend_context = "(engagement is growing — recent posts outperforming older ones)"
    elif trend == "declining":
        trend_context = "(engagement is falling — recent posts underperforming vs older ones)"
    elif trend == "stable":
        trend_context = "(engagement is consistent across posts)"
    else:
        trend_context = ""

    stats_block = f"""
STRUCTURED DATA (scraped before this analysis — treat as ground truth):
  Instagram handle      : @{username}
  Followers             : {followers}
  Following             : {following}
  Total posts           : {post_count}
  Last post date        : {last_post_date}
  Avg likes/post        : {avg_likes}
  Avg comments/post     : {avg_comments}
  Engagement rate       : {engagement_rate} {er_context}
  Posting frequency     : {posting_freq}
  Engagement trend      : {trend} {trend_context}
  Bio text              : {bio_text}
  Link in bio           : {has_link_in_bio}
  Website in bio        : {bio_website}
  Story highlight cats  : {highlights}

Use this data to inform your analysis:
- A high follower count with low engagement rate means the audience is not converting — flag this.
- Posting frequency under 2/week suggests inconsistent content strategy — relevant weakness.
- A declining trend means their content quality or consistency is worsening — strong sales signal.
- An improving trend means they are already investing in content — focus pitch on accelerating growth.
- Story highlights reveal what the business prioritises promoting — use in pitch if relevant.
- Bio text gives you exact business category, selling intent, and location signals.
- Link in bio and website are strong selling signals and lead quality indicators.
- Reference specific figures (e.g. "with {followers} followers and {engagement_rate} ER") in the pitch and sales notes.
"""

    # ---- Website analysis block (optional) ----
    wa = website_analysis or {}
    if wa and not wa.get("error"):
        def _yn(v):
            return "yes" if v else "no"
        wa_weaknesses = "; ".join(wa.get("top_weaknesses") or []) or "none detected"
        website_block = f"""
WEBSITE ANALYSIS (automated scan of their business homepage):
  Website score         : {wa.get('website_score', '?')}/10
  SSL certificate       : {_yn(wa.get('has_ssl'))}
  Mobile-friendly       : {_yn(wa.get('has_mobile_viewport'))}
  Load time             : {wa.get('load_time_ms')}ms
  Contact info visible  : {_yn(wa.get('has_contact_info'))}
  Clear CTA button      : {_yn(wa.get('has_cta'))}
  Title tag present     : {_yn(wa.get('has_title_tag'))}
  Meta description      : {_yn(wa.get('has_meta_description'))}
  Homepage word count   : {wa.get('word_count', 0)}
  Images on homepage    : {wa.get('image_count', 0)}
  Website weaknesses    : {wa_weaknesses}

Use this data in your analysis:
- A low website score compounds poor Instagram content — their entire digital presence needs work.
- Missing SSL or mobile-friendly meta tag signals a neglected website — strong sales angle.
- No CTA button or contact info means they are not converting website visitors.
- Reference specific website gaps in sales_notes and, where relevant, the personalised_pitch.
"""
    else:
        website_block = ""

    base = f"""You are an expert media production consultant evaluating an Instagram creator's content quality for a professional media production company.

{stats_block}{website_block}
Now analyse these {n} screenshots from @{username}'s Instagram profile.

Score each dimension 1-10 (10 = broadcast/editorial quality, 1 = very poor):
1. LIGHTING - consistency, exposure, flattering vs harsh shadows
2. COMPOSITION - framing, backgrounds, visual clutter
3. EDITING & COLOUR - grade consistency, intentionality
4. BRAND CONSISTENCY - coherent visual identity across the feed
5. CONTENT PRODUCTION VALUE - overall production effort visible
6. OVERALL - your holistic professional judgment

Identify TOP 3 SPECIFIC WEAKNESSES. Be precise: not "bad lighting" but e.g. "single overhead bulb creates harsh downward shadows in every indoor shot". Reference the engagement/follower data where relevant.

Write a 3-4 sentence PERSONALISED OUTREACH PITCH that references specific observations from both the screenshots AND the engagement data, frames weaknesses as opportunities, sounds human, and ends with a soft CTA. Never mention AI. Include the engagement rate or follower count naturally if it strengthens the case.

BUSINESS INTENT ANALYSIS
Location target: {location_line}

Cross-reference the bio text above with what is visible in screenshots. Look for:
- Selling signals: "DM to book", "link in bio", "enquiries", "services", phone numbers, email addresses, booking links, price lists
- Location signals: any mention of {loc_display} in bio, location tags, captions, or business name

The bio text "{bio_text}" already gives you intent clues — use it.

Classify the business type (e.g. photographer, hair salon, restaurant, personal trainer, tattoo artist, clothing brand, beauty therapist, etc.). Write "unknown" if unclear.

The IDEAL LEAD is: a {loc_display} business + poor production quality + actively selling via Instagram.
Grade A = all three present. Grade B = two of three. Grade C = one. Grade D = none.

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
  "overall_score": <average to 1 decimal>,
  "lead_grade": "<A/B/C/D>",
  "priority_flag": <true if A or B>,
  "top_weaknesses": ["<specific 1>", "<specific 2>", "<specific 3>"],
  "strengths": ["<strength 1>", "<strength 2>"],
  "personalised_pitch": "<3-4 sentence pitch referencing both visual and engagement data>",
  "upgrade_potential": "<high/medium/low>",
  "estimated_audience_size": "<small/mid/large>",
  "sales_notes": "<internal notes including engagement rate, posting frequency, and any bio signals>",
  "business_intent_score": <1-10, 10=actively selling>,
  "business_type": "<category>",
  "location_match": <true/false>,
  "location_signals": ["<signal1>", ...],
  "selling_signals": ["<signal1>", ...],
  "trend": "<improving|stable|declining|unknown>"
}}"""
    return base


def analyse(username: str, shots: list, claude, location: str = None, profile_stats: dict = None,
            website_analysis: dict = None, competitors: list = None,
            competitor_benchmark: dict = None) -> dict:
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
    prompt_text = build_prompt(username, len(images), location, profile_stats=profile_stats,
                               website_analysis=website_analysis, competitors=competitors,
                               competitor_benchmark=competitor_benchmark)
    content = images + [{"type": "text", "text": prompt_text}]
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
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
        # Profile stats
        "followers", "following", "post_count",
        "bio_text", "bio_website",
        "avg_likes", "avg_comments", "engagement_rate", "posting_frequency",
        "trend", "has_link_in_bio", "last_post_date", "story_highlights",
        # Website analysis
        "website_score", "website_ssl", "website_mobile", "website_cta",
        "website_load_ms", "website_word_count",
        # Maps fields (populated in maps mode; empty in explore mode)
        "business_name", "maps_address", "maps_phone", "maps_website",
        "maps_rating", "maps_review_count", "maps_url", "maps_place_id",
        # Competitor benchmark (JSON blob)
        "competitor_benchmark",
        # Claude-generated email
        "email_body",
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
                "followers":              r.get("followers", ""),
                "following":              r.get("following", ""),
                "post_count":             r.get("post_count", ""),
                "bio_text":               r.get("bio_text", ""),
                "bio_website":            r.get("bio_website", ""),
                "avg_likes":              r.get("avg_likes", ""),
                "avg_comments":           r.get("avg_comments", ""),
                "engagement_rate":        r.get("engagement_rate", ""),
                "posting_frequency":      r.get("posting_frequency", ""),
                "trend":                  r.get("trend", ""),
                "has_link_in_bio":        r.get("has_link_in_bio", ""),
                "last_post_date":         r.get("last_post_date", ""),
                "story_highlights":       "; ".join(r.get("story_highlight_categories") or []),
                "website_score":          (r.get("website_analysis") or {}).get("website_score", ""),
                "website_ssl":            (r.get("website_analysis") or {}).get("has_ssl", ""),
                "website_mobile":         (r.get("website_analysis") or {}).get("has_mobile_viewport", ""),
                "website_cta":            (r.get("website_analysis") or {}).get("has_cta", ""),
                "website_load_ms":        (r.get("website_analysis") or {}).get("load_time_ms", ""),
                "website_word_count":     (r.get("website_analysis") or {}).get("word_count", ""),
                "business_name":          r.get("business_name", ""),
                "maps_address":           r.get("maps_address", ""),
                "maps_phone":             r.get("maps_phone", ""),
                "maps_website":           r.get("maps_website", ""),
                "maps_rating":            r.get("maps_rating", ""),
                "maps_review_count":      r.get("maps_review_count", ""),
                "maps_url":               r.get("maps_url", ""),
                "maps_place_id":          r.get("maps_place_id", ""),
                "competitor_benchmark":   json.dumps(r.get("competitor_benchmark") or {}),
                "email_body":             r.get("email_body", ""),
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
        "--min-reviews", type=int, default=50,
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

                # ── Website analysis (before screenshots, no browser needed) ──
                web_analysis = {}
                if business.get("website"):
                    print(f"  Website   : {business['website']}")
                    web_analysis = analyze_website(
                        business["website"],
                        business_name=business["name"],
                    )
                    if web_analysis.get("error"):
                        print(f"    [web] error: {web_analysis['error']}")
                    else:
                        print(
                            f"    [web] score={web_analysis.get('website_score')}/10  "
                            f"ssl={'yes' if web_analysis.get('has_ssl') else 'NO'}  "
                            f"mobile={'yes' if web_analysis.get('has_mobile_viewport') else 'NO'}  "
                            f"cta={'yes' if web_analysis.get('has_cta') else 'no'}  "
                            f"load={web_analysis.get('load_time_ms')}ms  "
                            f"words={web_analysis.get('word_count')}"
                        )

                shots, pstats = screenshot_creator(driver, username, save_dir)
                if not shots:
                    continue

                try:
                    result = analyse(username, shots, claude, location=args.location,
                                     profile_stats=pstats, website_analysis=web_analysis)
                    if result:
                        # Attach profile stats
                        result.update(pstats)
                        # Attach Maps metadata to the result
                        result["business_name"]     = business["name"]
                        result["maps_address"]      = business["address"]
                        result["maps_phone"]        = business["phone"]
                        result["maps_website"]      = business["website"]
                        result["maps_rating"]       = business["rating"]
                        result["maps_review_count"] = business["review_count"]
                        result["maps_url"]          = business["maps_url"]
                        result["maps_place_id"]     = business["place_id"]
                        result["website_analysis"]  = web_analysis

                        # Extract email from business website
                        if business.get("website"):
                            print(f"  Email scrape : {business['website']}")
                            found_email = extract_email_from_website(business["website"])
                            result["email"] = found_email
                            if found_email:
                                print(f"  Email found : {found_email}")
                            else:
                                print("  Email found : none")

                        # Competitor comparison (maps mode only — we know business type)
                        biz_type = result.get("business_type") or ""
                        if biz_type and biz_type.lower() != "unknown":
                            print(f"  Finding competitors for: {biz_type}")
                            comps = find_competitors(
                                business_type=biz_type,
                                location=args.location or "manchester",
                                google_key=google_key,
                                driver=driver,
                                save_dir=save_dir,
                                exclude_username=username,
                                claude=claude,
                                n=3,
                            )
                            result["competitors"] = comps
                            if comps:
                                scores = [c["overall_score"] for c in comps if c.get("overall_score") is not None]
                                result["competitor_avg_score"] = round(sum(scores) / len(scores), 1) if scores else None
                                print(f"  Competitor avg score: {result['competitor_avg_score']}/10")
                            benchmark = _compute_benchmark(result, comps)
                            result["competitor_benchmark"] = benchmark
                            print(f"  Benchmark rank: {benchmark.get('target_rank')}/4, gap to top: {benchmark.get('gap_to_top')}")
                            # Enrich pitch + sales notes with real competitor names/scores
                            _enrich_with_competitors(result, comps, benchmark, claude)
                        else:
                            result["competitors"] = []
                            result["competitor_avg_score"] = None
                            result["competitor_benchmark"] = None

                        # Generate Claude-written cold email (subject + body)
                        _generate_email(result, claude)

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
                shots, pstats = screenshot_creator(driver, username, save_dir)
                if not shots:
                    continue
                try:
                    result = analyse(username, shots, claude, location=args.location, profile_stats=pstats)
                    if result:
                        result.update(pstats)
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

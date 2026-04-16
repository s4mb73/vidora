"""
Website analysis module for Vidora Scout.

Checks 10 quality dimensions of a business homepage using only requests + stdlib.
No Selenium required — runs before the browser session opens.

Usage (standalone test):
    python website_analyzer.py https://example.com

Usage (as module):
    from website_analyzer import analyze_website
    result = analyze_website("https://example.com")
"""

import re
import sys
import time
import html
from urllib.parse import urljoin, urlparse

import requests

# ── CTA keywords to look for in links and buttons ───────────────────────────
_CTA_PATTERNS = re.compile(
    r'\b(book\s*now|book\s*online|book\s*a|get\s+a\s+quote|get\s+quote|'
    r'contact\s*us|enquire|enquiry|get\s+in\s+touch|free\s+consultation|'
    r'request\s+a|start\s+today|claim\s+your|schedule\s+a|'
    r'call\s+now|message\s+us|dm\s+us|appointment|reserve|'
    r'sign\s+up|get\s+started|try\s+free|buy\s+now|shop\s+now)\b',
    re.I,
)

# ── Phone number patterns (UK + international) ───────────────────────────────
_PHONE_RE = re.compile(
    r'(\+44[\s\-]?[\d\s\-]{9,}|'        # +44 ...
    r'0[0-9]{2,4}[\s\-]?[0-9]{3,4}[\s\-]?[0-9]{3,5}|'   # 0161 xxx xxxx
    r'\b07\d{2}[\s\-]?\d{6}\b)',         # 07xxx xxxxxx mobile
    re.I,
)

# ── Email pattern (basic) ────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

# ── Strip HTML tags ──────────────────────────────────────────────────────────
_TAG_RE    = re.compile(r'<[^>]+>')
_SPACE_RE  = re.compile(r'\s+')

# ── Common words to exclude when hunting for competitor mentions ─────────────
_STOP_WORDS = {
    'the','a','an','and','or','but','in','on','at','to','for','of','with',
    'by','from','is','are','was','were','be','been','being','have','has',
    'had','do','does','did','will','would','could','should','may','might',
    'our','your','their','we','you','they','i','it','this','that','these',
    'those','all','any','some','more','most','about','into','through','over',
    'out','up','down','so','as','if','not','no','can','just','also','than',
    'then','when','where','which','who','how','what','why','there','here',
    'get','let','make','use','see','go','come','take','give','look','know',
}


# ─────────────────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def _strip_html(raw: str) -> str:
    """Remove tags and decode HTML entities, return plain text."""
    no_script = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', '', raw,
                       flags=re.S | re.I)
    no_tags = _TAG_RE.sub(' ', no_script)
    decoded = html.unescape(no_tags)
    return _SPACE_RE.sub(' ', decoded).strip()


def _find_competitor_mentions(text: str, business_name: str) -> list:
    """
    Look for other business-like proper nouns in the visible text that are NOT
    the site's own name.  Returns up to 5 suspects.

    Strategy: find Title Case phrases (2+ words) that appear more than once
    and are not the business's own name words.
    """
    own_words = {w.lower() for w in re.split(r'\W+', business_name or '') if len(w) >= 3}

    # Find 2-3 word Title Case phrases
    phrases = re.findall(r'\b([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,}){1,2})\b', text)

    counts: dict = {}
    for p in phrases:
        words_lower = p.lower().split()
        # Skip if it's mostly stop words or own-name words
        if all(w in _STOP_WORDS | own_words for w in words_lower):
            continue
        counts[p] = counts.get(p, 0) + 1

    # Return phrases that appear 2+ times (likely intentional brand references)
    suspects = [p for p, c in sorted(counts.items(), key=lambda x: -x[1]) if c >= 2]
    return suspects[:5]


def analyze_website(url: str, timeout: int = 10, business_name: str = "") -> dict:
    """
    Analyze a business website homepage for 10 quality signals.

    Returns a dict with all findings plus:
      website_score   (int  0-10)
      top_weaknesses  (list, up to 2 strings)
      error           (str or None)
    """
    result = {
        # 10 signals
        "load_time_ms":         None,
        "has_mobile_viewport":  False,
        "has_ssl":              False,
        "has_contact_info":     False,
        "has_cta":              False,
        "last_modified":        None,
        "word_count":           0,
        "has_title_tag":        False,
        "has_meta_description": False,
        "image_count":          0,
        "competitor_mentions":  [],
        # Computed
        "website_score":        0,
        "top_weaknesses":       [],
        "error":                None,
    }

    if not url:
        result["error"] = "no URL provided"
        return result

    # Ensure absolute URL
    if not url.startswith("http"):
        url = "https://" + url

    parsed = urlparse(url)

    # 3. SSL
    result["has_ssl"] = parsed.scheme == "https"

    try:
        t0 = time.perf_counter()
        resp = requests.get(
            url,
            headers=_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result["load_time_ms"] = elapsed_ms

        # 6. Last-Modified header
        lm = resp.headers.get("Last-Modified") or resp.headers.get("last-modified")
        if lm:
            result["last_modified"] = lm

        raw_html = resp.text

    except requests.exceptions.SSLError:
        # Try plain http fallback
        try:
            fallback = url.replace("https://", "http://")
            t0 = time.perf_counter()
            resp = requests.get(fallback, headers=_HEADERS, timeout=timeout, allow_redirects=True)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            result["load_time_ms"] = elapsed_ms
            result["has_ssl"] = False
            raw_html = resp.text
        except Exception as e:
            result["error"] = f"SSL error + http fallback failed: {e}"
            return result
    except requests.exceptions.Timeout:
        result["load_time_ms"] = timeout * 1000
        result["error"] = f"timed out after {timeout}s"
        return result
    except Exception as e:
        result["error"] = str(e)
        return result

    lower = raw_html.lower()

    # 2. Mobile viewport
    result["has_mobile_viewport"] = bool(
        re.search(r'<meta[^>]+name=["\']viewport["\']', raw_html, re.I)
    )

    # 8. Title tag
    m = re.search(r'<title[^>]*>([^<]{1,200})</title>', raw_html, re.I)
    result["has_title_tag"] = bool(m and m.group(1).strip())

    # 8. Meta description
    result["has_meta_description"] = bool(
        re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'][^"\']{10}', raw_html, re.I)
        or re.search(r'<meta[^>]+content=["\'][^"\']{10}[^>]+name=["\']description["\']', raw_html, re.I)
    )

    # 9. Image count (only <img> tags with a src)
    result["image_count"] = len(re.findall(r'<img\b[^>]+\bsrc=', raw_html, re.I))

    # 7. Word count from visible text
    plain = _strip_html(raw_html)
    words = [w for w in plain.split() if re.search(r'[a-zA-Z]', w)]
    result["word_count"] = len(words)

    # 4. Contact info — phone, email, or contact form
    has_phone = bool(_PHONE_RE.search(raw_html))
    has_email_on_page = bool(_EMAIL_RE.search(raw_html))
    has_contact_form = bool(
        re.search(r'<form\b', raw_html, re.I)
        and re.search(r'<input\b[^>]+type=["\'](?:text|email|tel)["\']', raw_html, re.I)
    )
    result["has_contact_info"] = has_phone or has_email_on_page or has_contact_form

    # 5. CTA — look in button text, anchor text, and input[value]
    # Extract text from <a>, <button>, <input type=submit>
    clickables = " ".join(
        re.findall(r'<(?:a|button)[^>]*>([^<]{1,80})</', raw_html, re.I)
        + re.findall(r'<input[^>]+value=["\']([^"\']{1,60})["\']', raw_html, re.I)
    )
    result["has_cta"] = bool(_CTA_PATTERNS.search(clickables))

    # 10. Competitor mentions in visible text
    result["competitor_mentions"] = _find_competitor_mentions(plain, business_name)

    # ── Score calculation (out of 10) ────────────────────────────────────────
    score = 0.0

    # SSL (1.5 pts — biggest trust signal)
    if result["has_ssl"]:
        score += 1.5

    # Mobile viewport (1.5 pts — half of UK traffic is mobile)
    if result["has_mobile_viewport"]:
        score += 1.5

    # Load time (1 pt — <3 s = full; 3-6 s = half; >6 s = none)
    lt = result["load_time_ms"]
    if lt is not None:
        if lt < 3000:
            score += 1.0
        elif lt < 6000:
            score += 0.5

    # Contact info (1.5 pts)
    if result["has_contact_info"]:
        score += 1.5

    # CTA present (1 pt)
    if result["has_cta"]:
        score += 1.0

    # Title tag (0.5 pt)
    if result["has_title_tag"]:
        score += 0.5

    # Meta description (0.5 pt)
    if result["has_meta_description"]:
        score += 0.5

    # Word count (0.5 pt >200 words, 1 pt >400)
    wc = result["word_count"]
    if wc >= 400:
        score += 1.0
    elif wc >= 200:
        score += 0.5

    # Image count (0.5 pt if ≥3 images)
    if result["image_count"] >= 3:
        score += 0.5

    result["website_score"] = min(10, round(score))

    # ── Top 2 weaknesses ────────────────────────────────────────────────────
    weaknesses = []

    if not result["has_ssl"]:
        weaknesses.append("No SSL certificate — site loads over HTTP, damaging trust and Google rankings")
    if not result["has_mobile_viewport"]:
        weaknesses.append("Missing mobile viewport meta tag — likely broken on smartphones")
    if lt is not None and lt >= 6000:
        weaknesses.append(f"Very slow load time ({lt}ms) — visitors are likely bouncing before the page renders")
    elif lt is not None and lt >= 3000:
        weaknesses.append(f"Slow page load ({lt}ms) — could impact bounce rate and Google ranking")
    if not result["has_contact_info"]:
        weaknesses.append("No visible phone number, email, or contact form — makes it hard for customers to reach them")
    if not result["has_cta"]:
        weaknesses.append("No clear call-to-action button — visitors have no obvious next step")
    if not result["has_title_tag"]:
        weaknesses.append("Missing title tag — basic SEO failure")
    if not result["has_meta_description"]:
        weaknesses.append("Missing meta description — Google has nothing to show in search results")
    if wc < 200:
        weaknesses.append(f"Very thin content ({wc} words) — not enough text for search engines or visitors")
    if result["image_count"] < 3:
        weaknesses.append(f"Only {result['image_count']} images detected — visually sparse homepage")

    result["top_weaknesses"] = weaknesses[:2]

    return result


def _fmt_bool(v: bool) -> str:
    return "yes" if v else "NO"


def print_analysis(url: str, r: dict):
    """Pretty-print a single website analysis result."""
    print(f"\n{'='*62}")
    print(f"  URL            : {url}")
    print(f"  Score          : {r['website_score']}/10")
    if r.get("error"):
        print(f"  ERROR          : {r['error']}")
    print(f"  Load time      : {r['load_time_ms']}ms")
    print(f"  SSL            : {_fmt_bool(r['has_ssl'])}")
    print(f"  Mobile viewport: {_fmt_bool(r['has_mobile_viewport'])}")
    print(f"  Contact info   : {_fmt_bool(r['has_contact_info'])}")
    print(f"  CTA button     : {_fmt_bool(r['has_cta'])}")
    print(f"  Title tag      : {_fmt_bool(r['has_title_tag'])}")
    print(f"  Meta desc      : {_fmt_bool(r['has_meta_description'])}")
    print(f"  Word count     : {r['word_count']}")
    print(f"  Images         : {r['image_count']}")
    print(f"  Last-Modified  : {r['last_modified'] or '-'}")
    if r["competitor_mentions"]:
        print(f"  Competitor refs: {', '.join(r['competitor_mentions'])}")
    if r["top_weaknesses"]:
        print(f"  Top weaknesses :")
        for w in r["top_weaknesses"]:
            print(f"    - {w}")
    print(f"{'='*62}")


# ── Standalone test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_urls = sys.argv[1:] if len(sys.argv) > 1 else [
        "https://www.smilestudio.co.uk",
        "https://www.toniandguy.com",
        "https://www.davidlloyd.co.uk",
    ]

    print(f"\nWebsite Analyzer — testing {len(test_urls)} URL(s)\n")
    for url in test_urls:
        print(f"Checking: {url} ...")
        r = analyze_website(url)
        print_analysis(url, r)

    print("\nDone.")

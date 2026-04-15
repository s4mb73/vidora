"""
Vidora Phase 1 - Google Places B2B Lead Engine
------------------------------------------------
Searches Google Places API for businesses in a location,
extracts contact details, filters by review count,
and exports to CSV.

Usage:
    python phase1_places.py --query "private dental clinic manchester" --min-reviews 10
"""

import sys, os, requests, csv, json, time, argparse
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_KEY_FILE = "C:/vidora/google_api_key.txt"
PLACES_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAIL_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def load_api_key() -> str:
    key = Path(API_KEY_FILE).read_text(encoding='utf-8').strip()
    if not key:
        raise Exception(f"No API key found in {API_KEY_FILE}. Add your Google API key to that file.")
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
            raise Exception(f"Places API error: {status} — {data.get('error_message','')}")

        batch = data.get("results", [])
        results.extend(batch)
        print(f"    Got {len(batch)} results (total so far: {len(results)})")

        next_token = data.get("next_page_token")
        if not next_token or page >= 3:
            break

        # Google requires ~3s before next_page_token becomes valid; retry up to 5x
        ready = False
        for attempt in range(5):
            time.sleep(3)
            test = requests.get(PLACES_SEARCH_URL, params={"pagetoken": next_token, "key": api_key}, timeout=10)
            if test.json().get("status") != "INVALID_REQUEST":
                ready = True
                break
        if not ready:
            print("    (Pagination token not ready — working with results so far)")
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
    data = r.json()
    result = data.get("result", {})
    return {
        "website": result.get("website", ""),
        "phone":   result.get("formatted_phone_number", ""),
    }


def extract_lead(place: dict, api_key: str) -> dict:
    """Build a lead record from a Places search result + detail lookup."""
    details = get_place_details(place["place_id"], api_key)
    return {
        "name":         place.get("name", ""),
        "address":      place.get("formatted_address", ""),
        "rating":       place.get("rating", ""),
        "review_count": place.get("user_ratings_total", 0),
        "website":      details.get("website", ""),
        "phone":        details.get("phone", ""),
        "place_id":     place.get("place_id", ""),
        "maps_url":     f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id','')}",
    }


def export_csv(leads: list, path: str):
    fields = ["name", "address", "phone", "website", "rating", "review_count", "maps_url", "place_id"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for lead in leads:
            w.writerow({k: lead.get(k, "") for k in fields})
    print(f"\n  Exported {len(leads)} leads to {path}")


def main():
    parser = argparse.ArgumentParser(description="Vidora Phase 1 - Google Places Lead Search")
    parser.add_argument("--query",       default="private dental clinic manchester")
    parser.add_argument("--min-reviews", type=int, default=10)
    parser.add_argument("--output",      default="C:/vidora/phase1_results.csv")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  Vidora Phase 1 — Google Places Search")
    print(f"  Query      : {args.query}")
    print(f"  Min reviews: {args.min_reviews}")
    print(f"{'='*55}\n")

    api_key = load_api_key()
    print(f"  API key loaded ({api_key[:8]}...)\n")

    print("Searching Google Places...")
    raw = search_places(args.query, api_key)
    print(f"\n  {len(raw)} total results found")

    # Filter by minimum review count
    filtered = [p for p in raw if p.get("user_ratings_total", 0) >= args.min_reviews]
    print(f"  {len(filtered)} pass the {args.min_reviews}+ review filter\n")

    if not filtered:
        print("No results after filtering. Try lowering --min-reviews.")
        return

    # Fetch details for each
    print("Fetching contact details (website + phone) for each business...\n")
    leads = []
    for i, place in enumerate(filtered, 1):
        name = place.get("name", "?")
        rating = place.get("rating", "?")
        reviews = place.get("user_ratings_total", 0)
        print(f"  [{i}/{len(filtered)}] {name}  ({rating}★  {reviews} reviews)")
        try:
            lead = extract_lead(place, api_key)
            leads.append(lead)
            print(f"    Phone  : {lead['phone'] or '—'}")
            print(f"    Website: {lead['website'] or '—'}")
            print(f"    Address: {lead['address']}")
        except Exception as e:
            print(f"    ERROR getting details: {e}")
        time.sleep(0.1)   # stay well within rate limits

    print(f"\n{'='*55}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*55}")
    print(f"  Total found    : {len(raw)}")
    print(f"  After filter   : {len(leads)}")
    has_website = sum(1 for l in leads if l.get("website"))
    has_phone   = sum(1 for l in leads if l.get("phone"))
    print(f"  Have website   : {has_website}")
    print(f"  Have phone     : {has_phone}")

    export_csv(leads, args.output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
fetch_rental_comps.py
Scrapes rental listings from Redfin using Playwright browser automation.

The Redfin gis-csv API ignores isRentals=true, so we use Playwright to
establish a browser session and call /stingray/api/v1/search/rentals
from within the browser context (with proper cookies/session).

Each property type (house, condo, townhome) is queried separately to
avoid apartments drowning out relevant comps.

Output: rental_comps.csv (or sd_rental_comps.csv) — same format as
Redfin CSV exports for compatibility with existing pipeline.

Usage:
  python3 fetch_rental_comps.py              # Full LA County
  python3 fetch_rental_comps.py --test       # Single tile test
  python3 fetch_rental_comps.py --market sd  # San Diego
"""

import csv, json, os, sys, time, random, math

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, REDFIN_NUM_HOMES, REDFIN_DELAY_MIN, REDFIN_DELAY_MAX

# ── Config ──
MAX_SUBDIVIDE_DEPTH = 3
SEARCH_API = "/stingray/api/v1/search/rentals"

# Property types to query (each separately to avoid apartment dominance)
# uipt=1 → houses (PT 6), uipt=2 → condos (PT 3), uipt=3 → townhomes (PT 13)
PROPERTY_TYPES = [
    ("1", "Houses"),
    ("2", "Condos"),
    ("3", "Townhomes"),
]

# Redfin rental propertyType → our CSV PROPERTY TYPE label
PT_TO_LABEL = {
    6: "Single Family Residential",
    3: "Condo/Co-op",
    13: "Townhouse",
    5: "Multi-Family (5+ Unit)",
    4: "Multi-Family (2-4 Unit)",
}

# ── Counters ──
all_listings = []
seen_keys = set()
tiles_fetched = 0
tiles_with_data = 0
tiles_empty = 0
tiles_subdivided = 0
dupes_skipped = 0


def build_grid(market):
    """Build initial coarse grid of tiles covering the market area."""
    lat_min, lat_max = market["lat_min"], market["lat_max"]
    lng_min, lng_max = market["lng_min"], market["lng_max"]
    tile_lat, tile_lng = market["tile_lat"], market["tile_lng"]
    tiles = []
    lat = lat_min
    while lat < lat_max:
        lng = lng_min
        while lng < lng_max:
            lat2 = round(min(lat + tile_lat, lat_max), 4)
            lng2 = round(min(lng + tile_lng, lng_max), 4)
            tiles.append({
                "lat_min": round(lat, 4),
                "lat_max": lat2,
                "lng_min": round(lng, 4),
                "lng_max": lng2,
                "depth": 0,
            })
            lng += tile_lng
        lat += tile_lat
    return tiles


def subdivide_tile(t):
    """Split a tile into 4 quadrants."""
    mid_lat = round((t["lat_min"] + t["lat_max"]) / 2, 6)
    mid_lng = round((t["lng_min"] + t["lng_max"]) / 2, 6)
    d = t.get("depth", 0) + 1
    return [
        {"lat_min": t["lat_min"], "lat_max": mid_lat, "lng_min": t["lng_min"], "lng_max": mid_lng, "depth": d},
        {"lat_min": t["lat_min"], "lat_max": mid_lat, "lng_min": mid_lng, "lng_max": t["lng_max"], "depth": d},
        {"lat_min": mid_lat, "lat_max": t["lat_max"], "lng_min": t["lng_min"], "lng_max": mid_lng, "depth": d},
        {"lat_min": mid_lat, "lat_max": t["lat_max"], "lng_min": mid_lng, "lng_max": t["lng_max"], "depth": d},
    ]


def tile_to_poly(t):
    """Convert tile to Redfin user_poly format: lng+lat pairs for rectangle."""
    return (
        f"{t['lng_min']}+{t['lat_min']},"
        f"{t['lng_max']}+{t['lat_min']},"
        f"{t['lng_max']}+{t['lat_max']},"
        f"{t['lng_min']}+{t['lat_max']},"
        f"{t['lng_min']}+{t['lat_min']}"
    )


def tile_label(t):
    mid_lat = (t["lat_min"] + t["lat_max"]) / 2
    mid_lng = (t["lng_min"] + t["lng_max"]) / 2
    depth = t.get("depth", 0)
    return f"({mid_lat:.3f}, {mid_lng:.3f}) d{depth}"


def parse_homes(homes):
    """Parse Redfin rental API homes array into flat listing dicts."""
    results = []
    for h in homes:
        hd = h.get("homeData", {})
        rx = h.get("rentalExtension", {})
        addr_info = hd.get("addressInfo", {})
        centroid = addr_info.get("centroid", {}).get("centroid", {})

        lat = centroid.get("latitude")
        lng = centroid.get("longitude")
        if not lat or not lng:
            continue

        address = addr_info.get("formattedStreetLine", "")
        city = addr_info.get("city", "")
        state = addr_info.get("state", "CA")
        zipcode = addr_info.get("zip", "")
        prop_type_code = hd.get("propertyType", 0)
        prop_type = PT_TO_LABEL.get(prop_type_code, "Other")

        # Date fields — freshnessTimestamp is when listing was posted/refreshed
        freshness = rx.get("freshnessTimestamp", "")  # ISO 8601 e.g. "2026-01-20T00:26:48.215Z"
        last_updated = rx.get("lastUpdated", "")      # ISO 8601 e.g. "2026-02-10T12:55:20.696947Z"

        # Rental data — use ranges (for buildings) or exact values (for single units)
        rent_range = rx.get("rentPriceRange", {})
        bed_range = rx.get("bedRange", {})
        bath_range = rx.get("bathRange", {})
        sqft_range = rx.get("sqftRange", {})

        # For buildings with ranges, create entries for each bed count if possible
        # For single units (min==max), create one entry
        rent_min = rent_range.get("min", 0)
        rent_max = rent_range.get("max", 0)
        beds_min = bed_range.get("min", 0)
        beds_max = bed_range.get("max", 0)
        baths_max = bath_range.get("max")
        sqft_min = sqft_range.get("min", 0) if sqft_range else 0
        sqft_max = sqft_range.get("max", 0) if sqft_range else 0

        if rent_max <= 0:
            continue

        # Common fields for all entries from this home
        common = {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "prop_type": prop_type,
            "address": address,
            "city": city,
            "state": state,
            "zip": zipcode,
            "freshness": freshness,
            "last_updated": last_updated,
        }

        # Single unit (min == max for beds) → one entry
        if beds_min == beds_max:
            results.append({
                **common,
                "price": rent_max,  # Use max rent (best case)
                "beds": beds_max,
                "baths": baths_max,
                "sqft": sqft_max,
            })
        else:
            # Building with range — create entry using max (largest unit)
            results.append({
                **common,
                "price": rent_max,
                "beds": beds_max,
                "baths": baths_max,
                "sqft": sqft_max,
            })
            # Also create entry for min bed count if different enough
            if beds_min >= 1 and rent_min > 0:
                results.append({
                    **common,
                    "price": rent_min,
                    "beds": beds_min,
                    "baths": bath_range.get("min"),
                    "sqft": sqft_min,
                })

    return results


def fetch_tile_browser(page, tile, market, uipt, retries=0):
    """Fetch rental listings for a tile via browser-context API call."""
    poly = tile_to_poly(tile)
    api_url = (
        f"https://www.redfin.com{SEARCH_API}?"
        f"al=1&isRentals=true&market={market['redfin_market']}&num_homes={REDFIN_NUM_HOMES}"
        f"&ord=redfin-recommended-asc&page_number=1"
        f"&sf=1,2,3,5,6,7&start=0&status=9&uipt={uipt}"
        f"&v=8&user_poly={poly}"
    )

    try:
        result = page.evaluate("""async (url) => {
            try {
                const resp = await fetch(url);
                if (resp.status === 429 || resp.status === 403) {
                    return {blocked: true, status: resp.status};
                }
                const text = await resp.text();
                const json = text.startsWith('{}&&') ? JSON.parse(text.slice(4)) : JSON.parse(text);
                const homes = json?.payload?.homes || json?.homes || [];
                return {homes: homes, count: homes.length};
            } catch(e) {
                return {error: e.message};
            }
        }""", api_url)

        if result.get("blocked"):
            if retries < 2:
                wait = 15 + random.uniform(0, 10)
                print(f"\n      {result['status']} on {tile_label(tile)} — waiting {wait:.0f}s...")
                time.sleep(wait)
                return fetch_tile_browser(page, tile, market, uipt, retries + 1)
            print(f"\n      Blocked on {tile_label(tile)}, skipping")
            return []

        if result.get("error"):
            if retries < 2:
                time.sleep(5)
                return fetch_tile_browser(page, tile, market, uipt, retries + 1)
            return []

        homes = result.get("homes", [])
        return homes

    except Exception as e:
        print(f"\n      Error: {e}")
        if retries < 2:
            time.sleep(5)
            return fetch_tile_browser(page, tile, market, uipt, retries + 1)
        return []


def process_tile(page, tile, market, uipt, uipt_label):
    """Fetch a tile. If it hits the cap, subdivide and recurse."""
    global tiles_fetched, tiles_with_data, tiles_empty, tiles_subdivided, dupes_skipped

    tiles_fetched += 1
    depth = tile.get("depth", 0)

    sys.stdout.write(
        f"\r  [req {tiles_fetched:>3}] "
        f"{uipt_label:>10s} {tile_label(tile)}  "
        f"| {len(all_listings):,} rentals  "
        f"| {dupes_skipped:,} dupes  "
        f"| {tiles_subdivided} splits   "
    )
    sys.stdout.flush()

    homes = fetch_tile_browser(page, tile, market, uipt)

    if not homes:
        tiles_empty += 1
        time.sleep(random.uniform(REDFIN_DELAY_MIN, REDFIN_DELAY_MAX))
        return

    hit_cap = len(homes) >= REDFIN_NUM_HOMES - 5

    if hit_cap and depth < MAX_SUBDIVIDE_DEPTH:
        tiles_subdivided += 1
        sub_tiles = subdivide_tile(tile)
        print(f"\n      Cap hit ({len(homes)}) on {tile_label(tile)} — splitting into 4 sub-tiles")
        time.sleep(random.uniform(REDFIN_DELAY_MIN, REDFIN_DELAY_MAX))
        for st in sub_tiles:
            process_tile(page, st, market, uipt, uipt_label)
        return

    # Parse homes and dedup
    parsed = parse_homes(homes)
    new_count = 0
    for listing in parsed:
        key = (listing["address"].lower(), str(listing["price"]), str(listing["beds"]))
        if key in seen_keys:
            dupes_skipped += 1
            continue
        seen_keys.add(key)
        all_listings.append(listing)
        new_count += 1

    if new_count > 0:
        tiles_with_data += 1
    else:
        tiles_empty += 1

    if hit_cap and depth >= MAX_SUBDIVIDE_DEPTH:
        print(f"\n      Warning: {tile_label(tile)} still at cap after max depth")

    time.sleep(random.uniform(REDFIN_DELAY_MIN, REDFIN_DELAY_MAX))


def main():
    from playwright.sync_api import sync_playwright

    test_mode = "--test" in sys.argv
    market = get_market()
    tiles = build_grid(market)
    output_file = market_file("rental_comps.csv", market)

    if test_mode:
        center_lat = (market["lat_min"] + market["lat_max"]) / 2
        center_lng = (market["lng_min"] + market["lng_max"]) / 2
        test_tile = None
        for t in tiles:
            if t["lat_min"] <= center_lat <= t["lat_max"] and t["lng_min"] <= center_lng <= t["lng_max"]:
                test_tile = t
                break
        if not test_tile:
            test_tile = tiles[len(tiles) // 2]
        tiles = [test_tile]

    print("\n" + "=" * 60)
    print(f"  Redfin {market['name']} — Rental Comps Scraper (Playwright)")
    if test_mode:
        print("  ** TEST MODE — single tile **")
    print("=" * 60)
    print(f"\n  Grid: {market['tile_lat']}° x {market['tile_lng']}° ({len(tiles)} tiles)")
    print(f"  Property types: {', '.join(label for _, label in PROPERTY_TYPES)}")
    print(f"  Requests per full scan: ~{len(tiles) * len(PROPERTY_TYPES)} (before subdivisions)")
    print(f"  Cap per tile: {REDFIN_NUM_HOMES} (auto-subdivides if hit)")
    print(f"  Rate limit: {REDFIN_DELAY_MIN}-{REDFIN_DELAY_MAX}s between requests")
    print(f"  Output: {output_file}\n")

    start_time = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Establish Redfin session
        print("  Establishing Redfin session...")
        page.goto("https://www.redfin.com/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        print("  Session established.\n")

        # Query each property type across all tiles
        for uipt, label in PROPERTY_TYPES:
            type_start = len(all_listings)
            print(f"\n  ── {label} (uipt={uipt}) ──")
            for tile in tiles:
                process_tile(page, tile, market, uipt, label)

            type_count = len(all_listings) - type_start
            print(f"\n  {label}: {type_count:,} listings added")

        browser.close()

    elapsed_total = time.time() - start_time

    print(f"\n\n  {'=' * 50}")
    print(f"  Done in {elapsed_total / 60:.1f} minutes ({tiles_fetched} requests)")
    print(f"\n  Results:")
    print(f"     Tiles with rentals:  {tiles_with_data}")
    print(f"     Tiles empty:         {tiles_empty}")
    print(f"     Tiles subdivided:    {tiles_subdivided}")
    print(f"     Duplicates removed:  {dupes_skipped:,}")
    print(f"     Unique rentals:      {len(all_listings):,}")

    # Type breakdown
    type_counts = {}
    for l in all_listings:
        pt = l["prop_type"]
        type_counts[pt] = type_counts.get(pt, 0) + 1
    print(f"\n  Type breakdown:")
    for pt, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"     {pt}: {count:,}")

    # Bed breakdown
    bed_counts = {}
    for l in all_listings:
        b = l.get("beds", 0)
        bed_counts[b] = bed_counts.get(b, 0) + 1
    print(f"\n  Bed breakdown:")
    for b in sorted(bed_counts.keys()):
        print(f"     {b}BR: {bed_counts[b]:,}")

    if not all_listings:
        print("\n  No rentals fetched.")
        sys.exit(1)

    # Rent stats
    rents = sorted(l["price"] for l in all_listings)
    med = rents[len(rents) // 2]
    print(f"\n  Rent: median ${med:,} | min ${rents[0]:,} | max ${rents[-1]:,}")

    # Freshness stats
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    age_days = []
    missing_freshness = 0
    for l in all_listings:
        ts = l.get("freshness", "")
        if not ts:
            missing_freshness += 1
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_days.append((now - dt).days)
        except Exception:
            missing_freshness += 1

    if age_days:
        age_days.sort()
        buckets = {"<7d": 0, "7-30d": 0, "30-90d": 0, "90-150d": 0, ">150d": 0}
        for d in age_days:
            if d < 7: buckets["<7d"] += 1
            elif d < 30: buckets["7-30d"] += 1
            elif d < 90: buckets["30-90d"] += 1
            elif d < 150: buckets["90-150d"] += 1
            else: buckets[">150d"] += 1
        med_age = age_days[len(age_days) // 2]
        print(f"\n  Freshness (days since posted):")
        print(f"     Median age: {med_age} days")
        for label, count in buckets.items():
            pct = count / len(age_days) * 100
            print(f"     {label:>6s}: {count:>5,} ({pct:.0f}%)")
        if missing_freshness:
            print(f"     (no timestamp): {missing_freshness:,}")

    # ── Write CSV ──
    header = [
        "PROPERTY TYPE", "ADDRESS", "CITY", "STATE OR PROVINCE",
        "ZIP OR POSTAL CODE", "PRICE", "BEDS", "BATHS",
        "SQUARE FEET", "LATITUDE", "LONGITUDE",
        "FRESHNESS TIMESTAMP", "LAST UPDATED",
    ]
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for l in all_listings:
            writer.writerow([
                l["prop_type"],
                l["address"],
                l["city"],
                l.get("state", "CA"),
                l["zip"],
                l["price"],
                l.get("beds", ""),
                l.get("baths", ""),
                l.get("sqft", ""),
                l["lat"],
                l["lng"],
                l.get("freshness", ""),
                l.get("last_updated", ""),
            ])

    size_kb = os.path.getsize(output_file) / 1024
    print(f"\n  Written: {output_file}")
    print(f"     Size: {size_kb:.0f} KB ({size_kb/1024:.1f} MB)")
    print(f"     Rows: {len(all_listings):,}")
    print(f"\n  Next: python3 build_rental_data.py && python3 listings_build.py")
    print(f"     Then refresh http://localhost:8080\n")


if __name__ == "__main__":
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n  Playwright not found. Install:")
        print("    pip3 install playwright")
        print("    python3 -m playwright install chromium\n")
        sys.exit(1)

    main()

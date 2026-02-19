#!/usr/bin/env python3
"""
fetch_listings.py
Pulls ALL active residential listings in LA County via Redfin's gis-csv endpoint.

Uses adaptive geographic tiling: starts with a coarse grid, then automatically
subdivides any tile that hits Redfin's per-request cap (350 listings) into
4 smaller tiles. Recurses until every tile is under the cap → 100% coverage.

Key fix: Creates a fresh HTTP session per tile to avoid Redfin's
cookie-based geographic restrictions on reused sessions.

Usage:
  python3 fetch_listings.py          # Full LA County
  python3 fetch_listings.py --test   # Single tile test
  python3 listings_build.py          # Process into listings.js
  (refresh browser)
"""

import requests
import csv
import io
import os
import time
import sys
import random

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Config ──
DELAY_MIN = 1.5
DELAY_MAX = 2.5
NUM_HOMES = 350
OUTPUT_FILE = "redfin_merged.csv"
MAX_RETRIES = 2
MAX_SUBDIVIDE_DEPTH = 6  # Max times a tile can be quartered (0.12° → ~0.002°)

# ── LA County bounding box ──
LA_LAT_MIN = 33.70
LA_LAT_MAX = 34.85
LA_LNG_MIN = -118.95
LA_LNG_MAX = -117.55

# Starting tile size in degrees (~8mi × ~8mi)
TILE_LAT = 0.12
TILE_LNG = 0.15

# Redfin endpoint
GIS_CSV_URL = "https://www.redfin.com/stingray/api/gis-csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.redfin.com/",
}

# ── Counters (global for easy access in recursive flow) ──
header_row = None
all_data_rows = []
seen_keys = set()
tiles_fetched = 0
tiles_with_data = 0
tiles_empty = 0
tiles_subdivided = 0
dupes_skipped = 0


def build_grid():
    """Build initial coarse grid of tiles covering LA County."""
    tiles = []
    lat = LA_LAT_MIN
    while lat < LA_LAT_MAX:
        lng = LA_LNG_MIN
        while lng < LA_LNG_MAX:
            lat2 = round(min(lat + TILE_LAT, LA_LAT_MAX), 4)
            lng2 = round(min(lng + TILE_LNG, LA_LNG_MAX), 4)
            tiles.append({
                "lat_min": round(lat, 4),
                "lat_max": lat2,
                "lng_min": round(lng, 4),
                "lng_max": lng2,
                "depth": 0,
            })
            lng += TILE_LNG
        lat += TILE_LAT
    return tiles


def subdivide_tile(t):
    """Split a tile into 4 quadrants."""
    mid_lat = round((t['lat_min'] + t['lat_max']) / 2, 6)
    mid_lng = round((t['lng_min'] + t['lng_max']) / 2, 6)
    d = t.get('depth', 0) + 1
    return [
        {"lat_min": t['lat_min'], "lat_max": mid_lat, "lng_min": t['lng_min'], "lng_max": mid_lng, "depth": d},
        {"lat_min": t['lat_min'], "lat_max": mid_lat, "lng_min": mid_lng, "lng_max": t['lng_max'], "depth": d},
        {"lat_min": mid_lat, "lat_max": t['lat_max'], "lng_min": t['lng_min'], "lng_max": mid_lng, "depth": d},
        {"lat_min": mid_lat, "lat_max": t['lat_max'], "lng_min": mid_lng, "lng_max": t['lng_max'], "depth": d},
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
    mid_lat = (t['lat_min'] + t['lat_max']) / 2
    mid_lng = (t['lng_min'] + t['lng_max']) / 2
    depth = t.get('depth', 0)
    return f"({mid_lat:.3f}, {mid_lng:.3f}) d{depth}"


def fetch_tile(tile, retries=0):
    """Fetch active listings for a geographic tile.
    Uses a fresh session each call to avoid Redfin's cookie-based
    geographic restrictions that break reused sessions.
    """
    poly = tile_to_poly(tile)
    url = (
        f"{GIS_CSV_URL}?al=1&market=socal&num_homes={NUM_HOMES}"
        f"&page_number=1&status=9&uipt=1,2,3,4,5"
        f"&v=8&user_poly={poly}"
    )

    try:
        session = requests.Session()
        resp = session.get(url, headers=HEADERS, timeout=30)
        session.close()

        if resp.status_code == 200:
            text = resp.text.strip()
            if not text or text.startswith("<!") or text.startswith("{"):
                return []

            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
            return rows if len(rows) > 1 else []

        elif resp.status_code in (429, 403):
            if retries < MAX_RETRIES:
                wait = 15 + random.uniform(0, 10)
                print(f"\n      {resp.status_code} on tile {tile_label(tile)} — waiting {wait:.0f}s...")
                time.sleep(wait)
                return fetch_tile(tile, retries + 1)
            else:
                print(f"\n      Blocked on tile {tile_label(tile)}, skipping")
                return []
        else:
            return []

    except requests.exceptions.Timeout:
        if retries < MAX_RETRIES:
            time.sleep(5)
            return fetch_tile(tile, retries + 1)
        return []
    except Exception as e:
        print(f"\n      Error: {e}")
        return []


def ingest_rows(rows):
    """Dedup and add data rows to the global collection. Returns new count."""
    global header_row, dupes_skipped
    if not rows:
        return 0

    if header_row is None:
        header_row = rows[0]

    new_count = 0
    for row in rows[1:]:
        if len(row) < 10:
            continue
        if row[0].startswith("In accordance") or row[0].startswith('"In accordance'):
            continue

        try:
            addr_idx = header_row.index("ADDRESS") if "ADDRESS" in header_row else 3
            price_idx = header_row.index("PRICE") if "PRICE" in header_row else 7
            key = (row[addr_idx].strip().lower(), row[price_idx].strip())
        except (IndexError, ValueError):
            key = tuple(row[:5])

        if key in seen_keys:
            dupes_skipped += 1
            continue
        seen_keys.add(key)
        all_data_rows.append(row)
        new_count += 1

    return new_count


def process_tile(tile):
    """Fetch a tile. If it hits the cap, subdivide and recurse."""
    global tiles_fetched, tiles_with_data, tiles_empty, tiles_subdivided

    tiles_fetched += 1
    depth = tile.get('depth', 0)

    sys.stdout.write(
        f"\r  [req {tiles_fetched:>3}] "
        f"{tile_label(tile)}  "
        f"| {len(all_data_rows):,} listings  "
        f"| {dupes_skipped:,} dupes  "
        f"| {tiles_subdivided} splits   "
    )
    sys.stdout.flush()

    rows = fetch_tile(tile)

    if not rows:
        tiles_empty += 1
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        return

    data_count = len(rows) - 1  # minus header
    hit_cap = data_count >= NUM_HOMES - 5

    if hit_cap and depth < MAX_SUBDIVIDE_DEPTH:
        # This tile is too dense — subdivide into 4 and recurse
        tiles_subdivided += 1
        sub_tiles = subdivide_tile(tile)
        print(f"\n      Cap hit ({data_count}) on {tile_label(tile)} — splitting into 4 sub-tiles")
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        for st in sub_tiles:
            process_tile(st)
        return

    # Under cap or max depth — ingest the data
    new = ingest_rows(rows)
    if new > 0:
        tiles_with_data += 1
    else:
        tiles_empty += 1

    if hit_cap and depth >= MAX_SUBDIVIDE_DEPTH:
        print(f"\n      Warning: {tile_label(tile)} still at cap after max depth — some listings missed")

    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def main():
    test_mode = "--test" in sys.argv
    tiles = build_grid()

    if test_mode:
        test_tile = None
        for t in tiles:
            if t['lat_min'] <= 34.05 <= t['lat_max'] and t['lng_min'] <= -118.35 <= t['lng_max']:
                test_tile = t
                break
        if not test_tile:
            test_tile = tiles[len(tiles) // 2]
        tiles = [test_tile]

    print("\n" + "=" * 60)
    print("  Redfin LA County — Adaptive Full-Coverage Fetcher")
    if test_mode:
        print("  ** TEST MODE — single tile **")
    print("=" * 60)
    print(f"\n  Starting grid: {TILE_LAT}° x {TILE_LNG}° ({len(tiles)} tiles)")
    print(f"  Cap per tile: {NUM_HOMES} (auto-subdivides if hit)")
    print(f"  Max subdivision depth: {MAX_SUBDIVIDE_DEPTH}")
    print(f"  Rate limit: {DELAY_MIN}-{DELAY_MAX}s between requests")
    print(f"  Output: {OUTPUT_FILE}\n")

    start_time = time.time()

    for tile in tiles:
        process_tile(tile)

    elapsed_total = time.time() - start_time

    print(f"\n\n  Done in {elapsed_total / 60:.1f} minutes ({tiles_fetched} requests)")
    print(f"\n  Results:")
    print(f"     Tiles with listings: {tiles_with_data}")
    print(f"     Tiles empty:         {tiles_empty}")
    print(f"     Tiles subdivided:    {tiles_subdivided}")
    print(f"     Duplicates removed:  {dupes_skipped:,}")
    print(f"     Unique listings:     {len(all_data_rows):,}")

    if not all_data_rows:
        print("\n  No listings fetched. Redfin may be blocking requests.")
        sys.exit(1)

    # ── Write CSV ──
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header_row)
        writer.writerows(all_data_rows)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"\n  Written: {OUTPUT_FILE}")
    print(f"     Size: {size_kb:.0f} KB ({size_kb/1024:.1f} MB)")
    print(f"     Rows: {len(all_data_rows):,}")
    print(f"\n  Next: python3 listings_build.py")
    print(f"     Then refresh http://localhost:8080\n")


if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("\n  'requests' not found. Install: pip3 install requests\n")
        sys.exit(1)

    main()

#!/usr/bin/env python3
"""
fetch_sold_comps.py
Pulls recent residential sold comps via Redfin's gis-csv endpoint.
Uses the same adaptive tiling as fetch_listings.py for full coverage.

Output: redfin_sold.csv → then run build_comps.py to update data.js

Usage:
  python3 fetch_sold_comps.py                    # Full LA County, last 2 years
  python3 fetch_sold_comps.py --market sd         # Full SD County
  python3 fetch_sold_comps.py --market sd --test  # Single tile test
"""

import requests
import csv
import io
import os
import time
import sys
import random

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, REDFIN_GIS_CSV_URL, REDFIN_HEADERS, REDFIN_NUM_HOMES, REDFIN_DELAY_MIN, REDFIN_DELAY_MAX
from tile_utils import build_grid, subdivide_tile, tile_to_poly, tile_label

# ── Config ──
MAX_RETRIES = 5
BACKOFF_BASE = 15  # seconds — doubles each retry: 15, 30, 60, 120, 240
MAX_SUBDIVIDE_DEPTH = 4
SOLD_WITHIN_DAYS = 730  # 2 years

# ── Counters ──
header_row = None
all_data_rows = []
seen_keys = set()
tiles_fetched = 0
tiles_with_data = 0
tiles_empty = 0
tiles_subdivided = 0
dupes_skipped = 0


def fetch_tile(tile, market, retries=0):
    poly = tile_to_poly(tile)
    url = (
        f"{REDFIN_GIS_CSV_URL}?al=1&market={market['redfin_market']}&num_homes={REDFIN_NUM_HOMES}"
        f"&page_number=1&status=130&uipt=1,2,3,4"
        f"&v=8&sold_within_days={SOLD_WITHIN_DAYS}"
        f"&user_poly={poly}"
    )

    try:
        session = requests.Session()
        resp = session.get(url, headers=REDFIN_HEADERS, timeout=30)
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
                wait = BACKOFF_BASE * (2 ** retries) + random.uniform(0, 10)
                print(f"\n      {resp.status_code} — waiting {wait:.0f}s (retry {retries+1}/{MAX_RETRIES})...")
                time.sleep(wait)
                return fetch_tile(tile, market, retries + 1)
            else:
                print(f"\n      Blocked on {tile_label(tile)}, skipping")
                return []
        else:
            return []

    except requests.exceptions.Timeout:
        if retries < MAX_RETRIES:
            wait = BACKOFF_BASE * (2 ** retries)
            time.sleep(wait)
            return fetch_tile(tile, market, retries + 1)
        return []
    except Exception as e:
        print(f"\n      Error: {e}")
        return []


def ingest_rows(rows):
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


def process_tile(tile, market):
    global tiles_fetched, tiles_with_data, tiles_empty, tiles_subdivided

    tiles_fetched += 1

    sys.stdout.write(
        f"\r  [req {tiles_fetched:>3}] "
        f"{tile_label(tile)}  "
        f"| {len(all_data_rows):,} sold  "
        f"| {dupes_skipped:,} dupes  "
        f"| {tiles_subdivided} splits   "
    )
    sys.stdout.flush()

    rows = fetch_tile(tile, market)

    if not rows:
        tiles_empty += 1
        time.sleep(random.uniform(REDFIN_DELAY_MIN, REDFIN_DELAY_MAX))
        return

    data_count = len(rows) - 1
    hit_cap = data_count >= REDFIN_NUM_HOMES - 5

    if hit_cap and tile.get('depth', 0) < MAX_SUBDIVIDE_DEPTH:
        tiles_subdivided += 1
        print(f"\n      Cap hit ({data_count}) on {tile_label(tile)} — splitting")
        time.sleep(random.uniform(REDFIN_DELAY_MIN, REDFIN_DELAY_MAX))
        for st in subdivide_tile(tile):
            process_tile(st, market)
        return

    new = ingest_rows(rows)
    if new > 0:
        tiles_with_data += 1
    else:
        tiles_empty += 1

    if hit_cap and tile.get('depth', 0) >= MAX_SUBDIVIDE_DEPTH:
        print(f"\n      Warning: {tile_label(tile)} at cap after max depth")

    time.sleep(random.uniform(REDFIN_DELAY_MIN, REDFIN_DELAY_MAX))


def main():
    test_mode = "--test" in sys.argv
    market = get_market()
    tiles = build_grid(market)
    output_file = market_file("redfin_sold.csv", market)

    if test_mode:
        center_lat = (market["lat_min"] + market["lat_max"]) / 2
        center_lng = (market["lng_min"] + market["lng_max"]) / 2
        test_tile = None
        for t in tiles:
            if t['lat_min'] <= center_lat <= t['lat_max'] and t['lng_min'] <= center_lng <= t['lng_max']:
                test_tile = t
                break
        if not test_tile:
            test_tile = tiles[len(tiles) // 2]
        tiles = [test_tile]

    print("\n" + "=" * 60)
    print(f"  Redfin {market['name']} — Sold Comps Fetcher (Last 2 Years)")
    if test_mode:
        print("  ** TEST MODE — single tile **")
    print("=" * 60)
    print(f"\n  Grid: {len(tiles)} tiles, adaptive subdivision")
    print(f"  Sold within: {SOLD_WITHIN_DAYS} days ({SOLD_WITHIN_DAYS // 365} years)")
    print(f"  Cap per tile: {REDFIN_NUM_HOMES} (auto-subdivides if hit)")
    print(f"  Retries: {MAX_RETRIES} with exponential backoff ({BACKOFF_BASE}s base)")
    print(f"  Output: {output_file}\n")

    start_time = time.time()
    for tile in tiles:
        process_tile(tile, market)

    elapsed = time.time() - start_time

    print(f"\n\n  Done in {elapsed / 60:.1f} minutes ({tiles_fetched} requests)")
    print(f"\n  Results:")
    print(f"     Tiles with data:   {tiles_with_data}")
    print(f"     Tiles empty:       {tiles_empty}")
    print(f"     Tiles subdivided:  {tiles_subdivided}")
    print(f"     Duplicates:        {dupes_skipped:,}")
    print(f"     Unique sold comps: {len(all_data_rows):,}")

    if not all_data_rows:
        print("\n  No sold comps fetched.")
        sys.exit(1)

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header_row)
        writer.writerows(all_data_rows)

    size_kb = os.path.getsize(output_file) / 1024
    print(f"\n  Written: {output_file}")
    print(f"     Size: {size_kb:.0f} KB ({size_kb / 1024:.1f} MB)")
    print(f"     Rows: {len(all_data_rows):,}")
    print(f"\n  Next: python3 build_comps.py")
    print(f"     Then: python3 listings_build.py")
    print(f"     Then refresh http://localhost:8080\n")


if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("\n  'requests' not found. Install: pip3 install requests\n")
        sys.exit(1)
    main()

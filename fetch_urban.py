#!/usr/bin/env python3
"""
fetch_urban.py
Checks whether each listing falls within a Census-designated Urban Area
using the TIGERweb REST API.

SB 1123 applies only to parcels in urbanized areas. This script queries
the Census Bureau's TIGERweb service for each listing location.

Reads:  redfin_merged.csv (lat/lng of active listings)
Writes: urban.json — keyed by "lat,lng" → true/false

Supports incremental runs (skips already-checked listings).
Checkpoints every 500 lookups.

Usage:
  python3 fetch_urban.py          # All listings
  python3 fetch_urban.py --test   # First 20 only
"""

import csv, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Config ──
TIGERWEB_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Urban/MapServer/0/query"
OUTPUT_FILE = "urban.json"
CHECKPOINT_EVERY = 500
MAX_WORKERS = 10
RATE_LIMIT_DELAY = 0.5  # Conservative — Census API is slow

# LA County bounding box
LA_LAT_MIN, LA_LAT_MAX = 33.70, 34.85
LA_LNG_MIN, LA_LNG_MAX = -118.95, -117.55


def query_urban(lat, lng, retries=2):
    """Query TIGERweb Urban Area layer for a point. Returns True/False/None."""
    params = {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "NAME,UATYP10",
        "returnGeometry": "false",
        "f": "json",
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.get(TIGERWEB_URL, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    return True  # Inside an urban area
                return False  # Not in an urban area
            elif resp.status_code in (429, 503):
                wait = 5 + attempt * 10
                print(f"    Rate limited ({resp.status_code}), waiting {wait}s...")
                time.sleep(wait)
                continue
        except requests.exceptions.Timeout:
            if attempt < retries:
                print(f"    Timeout, retry {attempt+1}...")
                time.sleep(3)
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
    return None  # All retries failed


def load_listings_from_csv():
    """Load lat/lng from redfin_merged.csv."""
    csv_file = "redfin_merged.csv"
    if not os.path.exists(csv_file):
        print(f"  No {csv_file} found.")
        sys.exit(1)

    listings = []
    with open(csv_file, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row.get("LATITUDE") or 0)
                lng = float(row.get("LONGITUDE") or 0)
                if LA_LAT_MIN <= lat <= LA_LAT_MAX and LA_LNG_MIN <= lng <= LA_LNG_MAX:
                    listings.append({"lat": round(lat, 6), "lng": round(lng, 6)})
            except (ValueError, TypeError):
                continue
    return listings


def save_cache(cache):
    """Write cache to disk."""
    with open(OUTPUT_FILE, "w") as f:
        json.dump(cache, f, separators=(",", ":"))


def main():
    test_mode = "--test" in sys.argv

    print("Loading listings from redfin_merged.csv...")
    listings = load_listings_from_csv()
    print(f"  {len(listings):,} listings loaded")

    # Load existing cache
    cache = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            cache = json.load(f)
        print(f"  {len(cache):,} cached urban lookups")

    # Build work list
    work = []
    for item in listings:
        key = f"{item['lat']},{item['lng']}"
        if key not in cache:
            work.append(item)

    limit = 20 if test_mode else len(work)
    work = work[:limit]

    total = len(work)
    if total == 0:
        print("  All listings already cached!")
    else:
        print(f"  Checking urban area status for {total:,} listings...")
        fetched = 0
        urban_count = 0
        non_urban_count = 0
        failed = 0

        for i, item in enumerate(work):
            key = f"{item['lat']},{item['lng']}"
            result = query_urban(item["lat"], item["lng"])

            if result is True:
                cache[key] = True
                urban_count += 1
            elif result is False:
                cache[key] = False
                non_urban_count += 1
            else:
                failed += 1

            fetched += 1

            if (i + 1) % 50 == 0 or i == total - 1:
                print(f"  [{i+1}/{total}] urban={urban_count} non-urban={non_urban_count} failed={failed}")

            # Checkpoint
            if fetched % CHECKPOINT_EVERY == 0:
                save_cache(cache)
                print(f"  Checkpoint: {len(cache):,} entries saved")

            time.sleep(RATE_LIMIT_DELAY)

        save_cache(cache)
        print(f"\nDone! urban={urban_count} non-urban={non_urban_count} failed={failed}")
        print(f"Total cached: {len(cache):,} entries -> {OUTPUT_FILE}")

    # Stats
    total_cached = len(cache)
    urban_total = sum(1 for v in cache.values() if v is True)
    non_urban_total = sum(1 for v in cache.values() if v is False)
    print(f"\nOverall: {urban_total:,} urban, {non_urban_total:,} non-urban out of {total_cached:,}")


if __name__ == "__main__":
    main()

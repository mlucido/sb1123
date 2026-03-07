#!/usr/bin/env python3
"""
fetch_slopes.py
Computes lot slope for each listing using USGS 1m LiDAR elevation data.

For each listing, queries elevation at 5 points (center + 30m N/S/E/W),
then computes max slope grade across the 4 cardinal directions.

Uses USGS Elevation Point Query Service (1m resolution, free, no API key).

Saves to slopes.json — keyed by "lat,lng" → slope percent.
Supports incremental runs (skips already-computed listings).

Usage:
  python3 fetch_slopes.py          # All listings (~35 min)
  python3 fetch_slopes.py --test   # First 50 only
  python3 listings_build.py        # Rebuild listings.js with slope data
"""

import json, os, sys, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Config ──
EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
LAT_OFFSET = 0.00027   # ~30m north/south
LNG_OFFSET = 0.00033   # ~30m east/west at 34°N latitude
HORIZ_DIST = 30.0      # meters between center and offset points
MAX_WORKERS = 25
OUTPUT_FILE = "slopes.json"


def fetch_elevation(lat, lng, retries=2):
    """Fetch elevation in meters from USGS EPQS (1m LiDAR)."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(EPQS_URL, params={
                "x": lng, "y": lat,
                "wkid": 4326, "units": "Meters",
                "includeDate": "false"
            }, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                val = data.get("value")
                if val is not None:
                    return float(val)
            elif resp.status_code in (429, 503):
                time.sleep(5 + attempt * 5)
                continue
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None


def compute_slope(lat, lng):
    """Query 5 elevation points and compute max slope grade (percent)."""
    points = [
        ("center", lat, lng),
        ("north", lat + LAT_OFFSET, lng),
        ("south", lat - LAT_OFFSET, lng),
        ("east", lat, lng + LNG_OFFSET),
        ("west", lat, lng - LNG_OFFSET),
    ]

    elevations = {}
    for label, plat, plng in points:
        elev = fetch_elevation(plat, plng)
        if elev is None:
            return None
        elevations[label] = elev

    center = elevations["center"]
    max_grade = 0
    for direction in ["north", "south", "east", "west"]:
        diff = abs(elevations[direction] - center)
        grade = (diff / HORIZ_DIST) * 100
        max_grade = max(max_grade, grade)

    return round(max_grade, 1)


def main():
    test_mode = "--test" in sys.argv

    # Load listings
    if not os.path.exists("listings.js"):
        print("  No listings.js found. Run listings_build.py first.")
        sys.exit(1)

    with open("listings.js") as f:
        raw = f.read()
    match = re.search(r"=\s*(\[.*\])\s*;?\s*$", raw, re.DOTALL)
    if not match:
        print("  Could not parse listings.js")
        sys.exit(1)

    listings = json.loads(match.group(1))

    # Load existing slopes (incremental — skip already computed)
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        print(f"  Loaded {len(existing):,} cached slopes")

    # Build work list
    work = []
    for l in listings:
        key = f"{l['lat']},{l['lng']}"
        if key not in existing:
            work.append((l["lat"], l["lng"], key))

    if test_mode:
        work = work[:50]

    total = len(work)
    print(f"\n{'='*60}")
    print(f"  USGS 1m LiDAR — Lot Slope Calculator")
    if test_mode:
        print(f"  ** TEST MODE — 50 listings **")
    print(f"{'='*60}")
    print(f"\n  Listings to process: {total:,}")
    print(f"  Already cached: {len(existing):,}")
    print(f"  API calls needed: {total * 5:,}")
    print(f"  Workers: {MAX_WORKERS}")
    est_min = total * 5 / MAX_WORKERS * 0.4 / 60
    print(f"  Est. time: {est_min:.0f} minutes\n")

    if total == 0:
        print("  All listings already have slopes. Done!\n")
        return

    results = dict(existing)
    completed = 0
    errors = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for lat, lng, key in work:
            fut = pool.submit(compute_slope, lat, lng)
            futures[fut] = key

        for fut in as_completed(futures):
            key = futures[fut]
            completed += 1
            try:
                slope = fut.result()
                if slope is not None:
                    results[key] = slope
                else:
                    errors += 1
            except Exception:
                errors += 1

            if completed % 200 == 0 or completed == total:
                elapsed = time.time() - start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate / 60 if rate > 0 else 0
                sys.stdout.write(
                    f"\r  [{completed:>5,}/{total:,}] "
                    f"{rate:.1f}/s | "
                    f"{errors} err | "
                    f"ETA {eta:.1f}m   "
                )
                sys.stdout.flush()

                # Checkpoint every 1000
                if completed % 1000 == 0:
                    with open(OUTPUT_FILE, "w") as f:
                        json.dump(results, f)

    elapsed = time.time() - start

    # Final save
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f)

    print(f"\n\n  Done in {elapsed / 60:.1f} minutes")
    print(f"  Total slopes: {len(results):,}")
    print(f"  Errors: {errors}")

    # Distribution
    slopes = [v for v in results.values() if isinstance(v, (int, float))]
    if slopes:
        slopes.sort()
        flat = sum(1 for s in slopes if s < 5)
        mild = sum(1 for s in slopes if 5 <= s < 15)
        moderate = sum(1 for s in slopes if 15 <= s < 25)
        steep = sum(1 for s in slopes if s >= 25)
        print(f"\n  Slope distribution:")
        print(f"    Flat (<5%):        {flat:,} ({flat / len(slopes) * 100:.1f}%)")
        print(f"    Mild (5-15%):      {mild:,} ({mild / len(slopes) * 100:.1f}%)")
        print(f"    Moderate (15-25%): {moderate:,} ({moderate / len(slopes) * 100:.1f}%)")
        print(f"    Steep (25%+):      {steep:,} ({steep / len(slopes) * 100:.1f}%)")

    print(f"\n  Written: {OUTPUT_FILE}")
    print(f"  Next: python3 listings_build.py")
    print(f"  Then refresh http://localhost:8080\n")


if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("\n  'requests' not found. Install: pip3 install requests\n")
        sys.exit(1)
    main()

#!/usr/bin/env python3
"""
fetch_elevation.py
Per-parcel topographic feasibility via USGS EPQS 3×3 elevation grid.

For each listing, samples 9 elevation points (3×3 grid) scaled to parcel size,
then computes slope variation metrics:
  - elevRange: max - min elevation in feet
  - maxSlope: steepest slope % between any adjacent grid points
  - flatPct: % of adjacent pairs below 10% slope
  - slopeScore: composite 0-100 (higher = worse for development)

Uses USGS Elevation Point Query Service (1m LiDAR, free, no API key).

Saves to elevation_cache.json — keyed by "lat,lng" → metrics dict.
Supports incremental runs (skips already-computed listings).

Usage:
  python3 fetch_elevation.py                 # All listings (~25 min)
  python3 fetch_elevation.py --test          # First 50 only
  python3 fetch_elevation.py --limit 100     # First 100 only
  python3 fetch_elevation.py --force         # Recompute all (ignore cache)
  python3 fetch_elevation.py --market sd     # San Diego market
"""

import csv, json, math, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, USGS_EPQS_URL

# ── Config ──
MAX_WORKERS = 8
REQUEST_DELAY = 0.3  # seconds between EPQS requests within each worker
GRID_N = 3           # 3×3 grid = 9 sample points
GRID_SCALE = 0.90    # sample at 90% of half-width (stay inside parcel edges)

# Conversion constants
FEET_PER_METER = 3.28084
DEG_LAT_PER_FOOT = 1.0 / (364000)   # ~1 degree lat ≈ 364,000 ft
DEG_LNG_PER_FOOT = 1.0 / (288000)   # ~1 degree lng ≈ 288,000 ft at 34°N


def generate_sample_grid(lat, lng, lot_sf, n=3):
    """Generate n×n grid of sample points scaled to parcel size.

    Estimates parcel side length from sqrt(lotSf), converts to lat/lng offsets,
    and generates grid at GRID_SCALE of half-width from center.
    """
    side_ft = math.sqrt(lot_sf) if lot_sf and lot_sf > 0 else 100
    half_ft = side_ft / 2.0 * GRID_SCALE

    lat_offset = half_ft * DEG_LAT_PER_FOOT
    lng_offset = half_ft * DEG_LNG_PER_FOOT

    points = []
    for row in range(n):
        for col in range(n):
            # Map 0..n-1 to -1..+1
            frac_r = (2 * row / (n - 1) - 1) if n > 1 else 0
            frac_c = (2 * col / (n - 1) - 1) if n > 1 else 0
            plat = lat + frac_r * lat_offset
            plng = lng + frac_c * lng_offset
            points.append((plat, plng, row, col))
    return points


def fetch_elevation(lat, lng, retries=2):
    """Fetch elevation in feet from USGS EPQS (1m LiDAR)."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(USGS_EPQS_URL, params={
                "x": lng, "y": lat,
                "wkid": 4326, "units": "Feet",
                "includeDate": "false"
            }, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                val = data.get("value")
                if val is not None:
                    fval = float(val)
                    if fval > -100:  # Sanity check — not ocean/error
                        return fval
            elif resp.status_code in (429, 503):
                time.sleep(5 + attempt * 5)
                continue
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None


def compute_slope_metrics(points_with_elev):
    """Compute slope variation metrics from grid of (lat, lng, row, col, elev).

    Returns dict with: elevRange, maxSlope, flatPct, slopeScore
    """
    if not points_with_elev or len(points_with_elev) < 4:
        return None

    elevations = [p[4] for p in points_with_elev]
    elev_range = max(elevations) - min(elevations)

    # Build grid lookup: (row, col) → elevation
    grid = {}
    for _, _, row, col, elev in points_with_elev:
        grid[(row, col)] = elev

    # Compute pairwise lat/lng distances for slope calculation
    point_lookup = {}
    for lat, lng, row, col, elev in points_with_elev:
        point_lookup[(row, col)] = (lat, lng, elev)

    # Adjacent pairs: horizontal, vertical, diagonal
    adjacent_pairs = []
    n = GRID_N
    for r in range(n):
        for c in range(n):
            if (r, c) not in point_lookup:
                continue
            # Right
            if (r, c + 1) in point_lookup:
                adjacent_pairs.append(((r, c), (r, c + 1)))
            # Down
            if (r + 1, c) in point_lookup:
                adjacent_pairs.append(((r, c), (r + 1, c)))
            # Diagonal down-right
            if (r + 1, c + 1) in point_lookup:
                adjacent_pairs.append(((r, c), (r + 1, c + 1)))
            # Diagonal down-left
            if (r + 1, c - 1) in point_lookup:
                adjacent_pairs.append(((r, c), (r + 1, c - 1)))

    if not adjacent_pairs:
        return None

    slopes = []
    for (r1, c1), (r2, c2) in adjacent_pairs:
        lat1, lng1, e1 = point_lookup[(r1, c1)]
        lat2, lng2, e2 = point_lookup[(r2, c2)]
        # Horizontal distance in feet
        dlat_ft = (lat2 - lat1) / DEG_LAT_PER_FOOT
        dlng_ft = (lng2 - lng1) / DEG_LNG_PER_FOOT
        horiz_ft = math.sqrt(dlat_ft ** 2 + dlng_ft ** 2)
        if horiz_ft < 1:
            continue
        elev_diff = abs(e2 - e1)
        slope_pct = (elev_diff / horiz_ft) * 100
        slopes.append(slope_pct)

    if not slopes:
        return None

    max_slope = max(slopes)
    flat_count = sum(1 for s in slopes if s < 10)
    flat_pct = round(flat_count / len(slopes) * 100)

    # Composite score: 0-100 (higher = worse for development)
    # Weight: elevation range (30%), max slope (30%), non-flat area (40%)
    score_elev = min((elev_range / 50.0) * 30, 30)
    score_slope = min((max_slope / 30.0) * 30, 30)
    score_flat = ((100 - flat_pct) / 100.0) * 40
    slope_score = round(min(score_elev + score_slope + score_flat, 100))

    return {
        "elevRange": round(elev_range, 1),
        "maxSlope": round(max_slope, 1),
        "flatPct": flat_pct,
        "slopeScore": slope_score,
    }


def process_listing(lat, lng, lot_sf):
    """Generate grid, fetch all 9 elevations, compute metrics."""
    points = generate_sample_grid(lat, lng, lot_sf, GRID_N)
    points_with_elev = []
    consecutive_failures = 0

    for plat, plng, row, col in points:
        elev = fetch_elevation(plat, plng)
        if elev is not None:
            points_with_elev.append((plat, plng, row, col, elev))
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                return None  # USGS likely down
        time.sleep(REQUEST_DELAY)

    if len(points_with_elev) < 4:
        return None  # Not enough points for meaningful analysis

    return compute_slope_metrics(points_with_elev)


def main():
    market = get_market()
    test_mode = "--test" in sys.argv
    force_mode = "--force" in sys.argv

    # Parse --limit N
    limit = None
    if test_mode:
        limit = 50
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    output_file = market_file("elevation_cache.json", market)
    csv_file = market_file("redfin_merged.csv", market)

    # Load listings from CSV (not listings.js — avoids CLUSTERS parse issue)
    if not os.path.exists(csv_file):
        print(f"  No {csv_file} found. Run fetch_listings.py first.")
        sys.exit(1)

    print(f"\n  Loading listings from {csv_file}...")
    csv_listings = []
    with open(csv_file, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row.get("LATITUDE") or 0)
                lng = float(row.get("LONGITUDE") or 0)
                if lat == 0 or lng == 0:
                    continue
                status = row.get("STATUS", "").strip()
                if status != "Active":
                    continue
                lot_str = re.sub(r"[^0-9.]", "", row.get("LOT SIZE") or "0") or "0"
                lot_sf = float(lot_str)
                # Only process listings with lot size (SB1123 needs lot for unit calc)
                if lot_sf < 5000:
                    continue
                csv_listings.append({
                    "lat": round(lat, 6),
                    "lng": round(lng, 6),
                    "lotSf": int(lot_sf),
                })
            except (ValueError, TypeError):
                continue

    print(f"  Found {len(csv_listings):,} active listings with lot >= 5,000 SF")

    # Load existing cache (incremental — skip already computed)
    existing = {}
    if os.path.exists(output_file) and not force_mode:
        with open(output_file) as f:
            existing = json.load(f)
        print(f"  Loaded {len(existing):,} cached elevation records")

    # Build work list
    work = []
    for l in csv_listings:
        key = f"{l['lat']},{l['lng']}"
        if key not in existing:
            work.append((l["lat"], l["lng"], l["lotSf"], key))

    if limit:
        work = work[:limit]

    total = len(work)
    print(f"\n{'='*60}")
    print(f"  USGS EPQS — Per-Parcel Elevation Grid (3×3)")
    if limit:
        print(f"  ** LIMITED TO {limit} LISTINGS **")
    print(f"{'='*60}")
    print(f"\n  Listings to process: {total:,}")
    print(f"  Already cached: {len(existing):,}")
    print(f"  API calls needed: {total * 9:,}")
    print(f"  Workers: {MAX_WORKERS}")
    est_min = total * 9 * REQUEST_DELAY / MAX_WORKERS / 60
    print(f"  Est. time: {est_min:.0f} minutes\n")

    if total == 0:
        print("  All listings already have elevation data. Done!\n")
        return

    results = dict(existing)
    completed = 0
    errors = 0
    consecutive_errors = 0
    pause_cycles = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for lat, lng, lot_sf, key in work:
            fut = pool.submit(process_listing, lat, lng, lot_sf)
            futures[fut] = key

        for fut in as_completed(futures):
            key = futures[fut]
            completed += 1
            try:
                metrics = fut.result()
                if metrics is not None:
                    results[key] = metrics
                    consecutive_errors = 0
                else:
                    errors += 1
                    consecutive_errors += 1
            except Exception:
                errors += 1
                consecutive_errors += 1

            # USGS downtime handling
            if consecutive_errors >= 10:
                pause_cycles += 1
                if pause_cycles >= 3:
                    print(f"\n\n  USGS appears down — aborting after {completed} listings")
                    break
                print(f"\n  {consecutive_errors} consecutive failures — pausing 60s...")
                time.sleep(60)
                consecutive_errors = 0

            if completed % 50 == 0 or completed == total:
                elapsed = time.time() - start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate / 60 if rate > 0 else 0
                cached = len(results) - len(existing)
                sys.stdout.write(
                    f"\r  [{completed:>5,}/{total:,}] "
                    f"{rate:.1f}/s | "
                    f"{cached} new | "
                    f"{errors} err | "
                    f"ETA {eta:.1f}m   "
                )
                sys.stdout.flush()

                # Checkpoint every 200
                if completed % 200 == 0:
                    with open(output_file, "w") as f:
                        json.dump(results, f)

    elapsed = time.time() - start

    # Final save
    with open(output_file, "w") as f:
        json.dump(results, f)

    print(f"\n\n  Done in {elapsed / 60:.1f} minutes")
    print(f"  Total cached: {len(results):,}")
    print(f"  New this run: {len(results) - len(existing):,}")
    print(f"  Errors: {errors}")

    # Distribution
    scores = [v["slopeScore"] for v in results.values() if isinstance(v, dict) and "slopeScore" in v]
    if scores:
        scores.sort()
        flat = sum(1 for s in scores if s <= 20)
        moderate = sum(1 for s in scores if 21 <= s <= 50)
        steep = sum(1 for s in scores if 51 <= s <= 75)
        severe = sum(1 for s in scores if s >= 76)
        print(f"\n  Slope score distribution:")
        print(f"    Flat (0-20):       {flat:,} ({flat / len(scores) * 100:.1f}%)")
        print(f"    Moderate (21-50):  {moderate:,} ({moderate / len(scores) * 100:.1f}%)")
        print(f"    Steep (51-75):     {steep:,} ({steep / len(scores) * 100:.1f}%)")
        print(f"    Severe (76-100):   {severe:,} ({severe / len(scores) * 100:.1f}%)")

    print(f"\n  Written: {output_file}")
    print(f"  Next: python3 listings_build.py")
    print(f"  Then refresh http://localhost:8080\n")


if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("\n  'requests' not found. Install: pip3 install requests\n")
        sys.exit(1)
    main()

#!/usr/bin/env python3
"""
fetch_parcels.py
Fetches parcel lot area + fire zone status from ArcGIS for each listing.

For each listing, queries two ArcGIS services:
  1. Parcel service — lot area, APN, assessed values (market-specific endpoint)
  2. Fire zone service — VHFHSZ status (statewide CAL FIRE or market-specific)

Reads:  redfin_merged.csv (directly, to avoid chicken-and-egg with listings.js)
Writes: parcels.json — keyed by "lat,lng"

Supports incremental runs (skips already-computed listings).

Usage:
  python3 fetch_parcels.py                     # All LA listings (~1-3 min)
  python3 fetch_parcels.py --market sd          # All SD listings
  python3 fetch_parcels.py --market sd --test   # First 10 only
"""

import csv, json, math, os, sys, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, CALFIRE_LRA_URL

# ── Config ──
MAX_WORKERS = 25
ENVELOPE_OFFSET = 0.00002  # ~2m envelope around point for parcel query

# Coordinate-to-feet conversion
DEG_LAT_FT = 364320  # ft per degree latitude (~111 km)


def _deg_lng_ft(lat_deg):
    """Feet per degree longitude at given latitude."""
    return DEG_LAT_FT * math.cos(math.radians(lat_deg))


def _edge_len(p1, p2, lng_ft):
    """Distance between two [lng, lat] points in feet."""
    dx = (p2[0] - p1[0]) * lng_ft
    dy = (p2[1] - p1[1]) * DEG_LAT_FT
    return math.sqrt(dx * dx + dy * dy)


def _perp_dist(p, a, b, lng_ft):
    """Perpendicular distance from point p to line a->b, in feet."""
    bx = (b[0] - a[0]) * lng_ft
    by = (b[1] - a[1]) * DEG_LAT_FT
    px = (p[0] - a[0]) * lng_ft
    py = (p[1] - a[1]) * DEG_LAT_FT
    edge_len = math.sqrt(bx * bx + by * by)
    if edge_len < 0.01:
        return 0
    return abs(bx * py - by * px) / edge_len


def _point_in_ring(lng, lat, ring):
    """Ray-casting point-in-polygon test for a single ring of [lng, lat] pairs."""
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def compute_lot_dimensions(geometry, lot_sf=None):
    """Compute lot width from polygon edges, depth from area / width.

    Width is measured from actual polygon geometry:
      4-vertex: average of shorter opposite edge pair. Shape = "rect".
      5+ vertex: minimum caliper width. Shape = "irreg".

    Depth is always derived as lotSf / width for consistency with actual
    lot area (polygon-measured depth overstates for irregular/rotated lots).

    Returns (lot_w, lot_d, lot_shape) or (None, None, None).
    """
    rings = geometry.get("rings")
    if not rings or not rings[0]:
        return None, None, None
    pts = rings[0]
    # Remove closing vertex if duplicate of first
    if len(pts) > 1 and pts[0][0] == pts[-1][0] and pts[0][1] == pts[-1][1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return None, None, None

    # Longitude-to-ft at polygon centroid
    avg_lat = sum(p[1] for p in pts) / n
    lng_ft = _deg_lng_ft(avg_lat)

    if n == 4:
        # Measure actual edge lengths, pair opposite edges
        edges = [_edge_len(pts[i], pts[(i + 1) % 4], lng_ft) for i in range(4)]
        pair_a = (edges[0] + edges[2]) / 2  # opposite edges 0,2
        pair_b = (edges[1] + edges[3]) / 2  # opposite edges 1,3
        lot_w = round(min(pair_a, pair_b))
        shape = "rect"
    else:
        # Minimum caliper width for irregular polygons
        calipers = []
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            max_d = 0
            for j in range(n):
                if j == i or j == (i + 1) % n:
                    continue
                d = _perp_dist(pts[j], a, b, lng_ft)
                if d > max_d:
                    max_d = d
            if max_d > 0:
                calipers.append(max_d)
        if not calipers:
            return None, None, None
        lot_w = round(min(calipers))
        shape = "irreg"

    if lot_w < 5:
        return None, None, None

    # Depth = area / width (effective rectangular depth)
    lot_d = round(lot_sf / lot_w) if lot_sf and lot_w > 0 else None

    if lot_d is not None and lot_d < 5:
        return None, None, None

    return (lot_w, lot_d, shape)


def query_parcel(lat, lng, market, retries=2):
    """Query parcel service with market-appropriate geometry (envelope or point)."""
    parcel_url = market["parcel_url"]
    field_map = market["parcel_field_map"]

    if market.get("parcel_query_type") == "envelope":
        # LA-style: small envelope around point
        offset = market.get("parcel_envelope_offset", ENVELOPE_OFFSET)
        env = {
            "xmin": lng - offset, "ymin": lat - offset,
            "xmax": lng + offset, "ymax": lat + offset,
            "spatialReference": {"wkid": 4326}
        }
        params = {
            "geometry": json.dumps(env),
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": market.get("parcel_out_fields", "*"),
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "json",
        }
    else:
        # SD-style: point query with coordinate system projection
        params = {
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": market.get("parcel_in_sr", 4326),
            "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": market.get("parcel_out_fields", "*"),
            "returnGeometry": "true",
            "f": "json",
        }

    for attempt in range(retries + 1):
        try:
            resp = requests.get(parcel_url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    if len(features) > 1:
                        # Pick smallest lot (most specific parcel) — avoids HOA/assessment overlays
                        best_feat = None
                        best_lot = None
                        for feat in features:
                            a = feat.get("attributes", {})
                            lot_raw = a.get(field_map["lot_sf"])
                            if lot_raw and lot_raw > 0:
                                if best_feat is None or lot_raw < best_lot:
                                    best_feat = feat
                                    best_lot = lot_raw
                        # Fallback: point-in-polygon test when lot sizes are null
                        if best_feat is None:
                            for feat in features:
                                geom = feat.get("geometry", {})
                                rings = geom.get("rings", [])
                                if rings and _point_in_ring(lng, lat, rings[0]):
                                    best_feat = feat
                                    break
                        chosen = best_feat if best_feat else features[0]
                    else:
                        chosen = features[0]
                    attrs = chosen.get("attributes", {})

                    # Map response fields using market config
                    lot_raw = attrs.get(field_map["lot_sf"])
                    multiplier = field_map.get("lot_sf_multiplier", 1)
                    lot_sf = round(lot_raw * multiplier) if lot_raw else None

                    situs_field = field_map.get("situs_address")
                    situs = attrs.get(situs_field, "") if situs_field else ""

                    # Extract lot dimensions from polygon geometry
                    geom = chosen.get("geometry")
                    lot_w, lot_d, lot_shape = compute_lot_dimensions(geom, lot_sf) if geom else (None, None, None)

                    return {
                        "lotSf": lot_sf,
                        "ain": attrs.get(field_map["ain"], ""),
                        "landValue": attrs.get(field_map["land_value"]),
                        "impValue": attrs.get(field_map["imp_value"]),
                        "situsAddress": situs,
                        "lotWidth": lot_w,
                        "lotDepth": lot_d,
                        "lotShape": lot_shape,
                    }
                return None  # No parcel found at this location
            elif resp.status_code in (429, 503):
                time.sleep(3 + attempt * 3)
                continue
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None


def query_fire_zone(lat, lng, market, retries=2):
    """Query fire zone service for VHFHSZ status.
    
    Uses market-specific endpoint if available, otherwise statewide CAL FIRE.
    """
    fire_url = market.get("fire_url") or CALFIRE_LRA_URL
    fire_field = market.get("fire_field", "HAZ_CLASS")
    fire_value = market.get("fire_vhfhsz_value", "Very High")

    params = {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": fire_field,
        "returnGeometry": "false",
        "f": "json",
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.get(fire_url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    haz = features[0].get("attributes", {}).get(fire_field, "")
                    return haz == fire_value
                return False  # No fire zone feature at this point
            elif resp.status_code in (429, 503):
                time.sleep(3 + attempt * 3)
                continue
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None  # Query failed


def fetch_parcel_data(lat, lng, market):
    """Fetch both parcel info and fire zone status for a single listing."""
    parcel = query_parcel(lat, lng, market)
    fire = query_fire_zone(lat, lng, market)

    if parcel is None and fire is None:
        return None

    result = {}
    if parcel:
        result["lotSf"] = parcel["lotSf"]
        result["ain"] = parcel["ain"]
        result["landValue"] = parcel["landValue"]
        result["impValue"] = parcel["impValue"]
        if parcel.get("situsAddress"):
            result["situsAddress"] = parcel["situsAddress"]
        if parcel.get("lotWidth"):
            result["lotWidth"] = parcel["lotWidth"]
        if parcel.get("lotDepth"):
            result["lotDepth"] = parcel["lotDepth"]
        if parcel.get("lotShape"):
            result["lotShape"] = parcel["lotShape"]
    if fire is not None:
        result["fireZone"] = fire

    return result if result else None


def load_listings_from_csv(market):
    """Load listing lat/lng from redfin_merged.csv."""
    csv_file = market_file("redfin_merged.csv", market)
    if not os.path.exists(csv_file):
        print(f"  No {csv_file} found.")
        sys.exit(1)

    lat_min, lat_max = market["lat_min"], market["lat_max"]
    lng_min, lng_max = market["lng_min"], market["lng_max"]

    listings = []
    with open(csv_file, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row.get("LATITUDE") or 0)
                lng = float(row.get("LONGITUDE") or 0)
                if not (lat_min <= lat <= lat_max and lng_min <= lng <= lng_max):
                    continue
                status = row.get("STATUS", "").strip()
                if status != "Active":
                    continue
                price = float(re.sub(r"[^0-9.]", "", row.get("PRICE") or "0") or 0)
                if price <= 0:
                    continue
                listings.append((round(lat, 6), round(lng, 6)))
            except Exception:
                continue
    return listings


def main():
    test_mode = "--test" in sys.argv
    market = get_market()
    output_file = market_file("parcels.json", market)

    listings = load_listings_from_csv(market)

    # Load existing (incremental — skip already computed)
    existing = {}
    if os.path.exists(output_file):
        with open(output_file) as f:
            existing = json.load(f)
        print(f"  Loaded {len(existing):,} cached parcels")

    # Build work list
    work = []
    for lat, lng in listings:
        key = f"{lat},{lng}"
        if key not in existing or "lotWidth" not in existing[key] or "lotShape" not in existing[key]:
            work.append((lat, lng, key))

    if test_mode:
        work = work[:10]

    total = len(work)
    fire_source = "CAL FIRE statewide" if not market.get("fire_url") else "local"
    print(f"\n{'='*60}")
    print(f"  {market['name']} ArcGIS — Parcel + Fire Zone Fetcher")
    if test_mode:
        print(f"  ** TEST MODE — 10 listings **")
    print(f"{'='*60}")
    print(f"\n  Listings from CSV: {len(listings):,}")
    print(f"  Already cached: {len(existing):,}")
    print(f"  To process: {total:,}")
    print(f"  Workers: {MAX_WORKERS}")
    print(f"  Fire zone source: {fire_source}")
    est_min = total * 2 / MAX_WORKERS * 0.5 / 60
    print(f"  Est. time: {est_min:.1f} minutes\n")

    if total == 0:
        print("  All listings already have parcel data. Done!\n")
        return

    results = dict(existing)
    completed = 0
    errors = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for lat, lng, key in work:
            fut = pool.submit(fetch_parcel_data, lat, lng, market)
            futures[fut] = key

        for fut in as_completed(futures):
            key = futures[fut]
            completed += 1
            try:
                data = fut.result()
                if data is not None:
                    results[key] = data
                else:
                    errors += 1
            except Exception:
                errors += 1

            if completed % 50 == 0 or completed == total:
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

                # Checkpoint every 500
                if completed % 500 == 0:
                    with open(output_file, "w") as f:
                        json.dump(results, f)

    elapsed = time.time() - start

    # Final save
    with open(output_file, "w") as f:
        json.dump(results, f)

    print(f"\n\n  Done in {elapsed / 60:.1f} minutes")
    print(f"  Total parcels: {len(results):,}")
    print(f"  Errors: {errors}")

    # Stats
    with_lot = sum(1 for v in results.values() if v.get("lotSf"))
    with_fire = sum(1 for v in results.values() if v.get("fireZone"))
    lots = [v["lotSf"] for v in results.values() if v.get("lotSf")]
    print(f"\n  With lot size: {with_lot:,}/{len(results):,}")
    print(f"  In VHFHSZ: {with_fire:,}")
    if lots:
        lots.sort()
        print(f"  Lot SF: median {lots[len(lots)//2]:,}, min {lots[0]:,}, max {lots[-1]:,}")

    # Lot width distribution
    widths = [v["lotWidth"] for v in results.values() if v.get("lotWidth")]
    with_dims = len(widths)
    print(f"\n  With lot dimensions: {with_dims:,}/{len(results):,}")
    if widths:
        widths.sort()
        narrow = sum(1 for w in widths if w < 40)
        medium = sum(1 for w in widths if 40 <= w < 60)
        wide = sum(1 for w in widths if 60 <= w < 100)
        very_wide = sum(1 for w in widths if w >= 100)
        print(f"  Lot width: median {widths[len(widths)//2]:,}', min {widths[0]:,}', max {widths[-1]:,}'")
        print(f"  <40': {narrow:,} | 40-60': {medium:,} | 60-100': {wide:,} | 100'+: {very_wide:,}")

    print(f"\n  Written: {output_file}")
    print(f"  Next: python3 listings_build.py\n")


if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("\n  'requests' not found. Install: pip3 install requests\n")
        sys.exit(1)
    main()

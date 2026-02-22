#!/usr/bin/env python3
"""
fetch_zoning.py
Fetches real zoning codes from ArcGIS endpoints for each listing.

Replaces the Redfin-guessed zoning (e.g. "Single Family Residential" → R1)
with actual zoning from city/county GIS (e.g. R2-1-O, RS-1-7).

For each listing, tries zoning endpoints in order (city first, county fallback).
First endpoint that returns data wins. Classification functions are market-specific.

Reads:  listings.js (parses the JSON array from the JS file)
Writes: zoning.json — keyed by "lat,lng"

Supports incremental runs (skips already-fetched listings).

Usage:
  python3 fetch_zoning.py                        # All LA listings
  python3 fetch_zoning.py --market sd             # All SD listings
  python3 fetch_zoning.py --market sd --test      # First 50 only
  python3 fetch_zoning.py --analyze               # Run on 50 listings + compare
"""

import json, os, re, sys, time
import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, CLASSIFY_FNS

# ── Config ──
CHECKPOINT_EVERY = 100
RATE_LIMIT_DELAY = 0.5  # ~2 req/sec


def query_zoning_endpoint(lat, lng, endpoint, retries=2):
    """Query a single ArcGIS zoning endpoint at a lat/lng point."""
    params = {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": endpoint.get("out_fields", "*"),
        "returnGeometry": "false",
        "f": "json",
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.get(endpoint["url"], params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    attrs = features[0].get("attributes", {})
                    zone_field = endpoint["zone_field"]
                    category_field = endpoint.get("category_field")

                    zone = attrs.get(zone_field, "")
                    # Try common field name variants if primary returns empty
                    if not zone:
                        for alt in ("ZONE_CMPLT", "ZONING", "Zone", "ZONE", "ZONE_CLASS"):
                            zone = attrs.get(alt, "")
                            if zone:
                                break

                    category = attrs.get(category_field, "") if category_field else ""
                    if not category:
                        for alt in ("CATEGORY", "GEN_PLAN"):
                            category = attrs.get(alt, "")
                            if category:
                                break

                    return {
                        "zoning": zone,
                        "category": category,
                        "source": endpoint["name"],
                    }
                return None  # No feature found at this location
            elif resp.status_code in (429, 503):
                wait = 3 + attempt * 5
                print(f"    Rate limited ({resp.status_code}), waiting {wait}s...")
                time.sleep(wait)
                continue
        except requests.exceptions.Timeout:
            if attempt < retries:
                print(f"    Timeout on {endpoint['name']}, retry {attempt+1}...")
                time.sleep(2)
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
    return None  # All retries failed


def fetch_zoning_cascade(lat, lng, market):
    """Try each zoning endpoint in order. First hit with data wins.

    Returns dict with zoning, category, sb1123, source — or None.
    """
    for endpoint in market["zoning_endpoints"]:
        result = query_zoning_endpoint(lat, lng, endpoint)
        if result and result.get("zoning"):
            # Classify using market-specific function
            classify_fn = CLASSIFY_FNS[endpoint["classify_fn"]]
            sb_zone = classify_fn(result["zoning"])
            result["sb1123"] = sb_zone
            return result
    return None


def load_listings_from_js(market):
    """Parse listings from listings.js (extracts the JSON array)."""
    js_file = market_file("listings.js", market)
    if not os.path.exists(js_file):
        print(f"  No {js_file} found.")
        sys.exit(1)

    with open(js_file, encoding="utf-8") as f:
        content = f.read()

    match = re.search(r'const LOADED_LISTINGS\s*=\s*(\[.*\])', content, re.DOTALL)
    if not match:
        print(f"  Could not parse {js_file}")
        sys.exit(1)

    listings_raw = json.loads(match.group(1))
    listings = []
    for item in listings_raw:
        lat = item.get("lat")
        lng = item.get("lng")
        if lat and lng:
            listings.append({
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "zone": item.get("zone", ""),
                "type": item.get("type", ""),
                "city": item.get("city", ""),
                "address": item.get("address", ""),
            })
    return listings


def save_cache(cache, output_file):
    """Write cache to disk."""
    with open(output_file, "w") as f:
        json.dump(cache, f, indent=1)


def main():
    test_mode = "--test" in sys.argv
    analyze_mode = "--analyze" in sys.argv
    market = get_market()
    output_file = market_file("zoning.json", market)

    print(f"Loading listings from {market_file('listings.js', market)}...")
    listings = load_listings_from_js(market)
    print(f"  {len(listings):,} listings loaded")

    # Show configured endpoints
    print(f"  Zoning endpoints ({market['name']}):")
    for ep in market["zoning_endpoints"]:
        print(f"    - {ep['name']} → {ep['zone_field']} → {ep['classify_fn']}")

    # Load existing cache
    cache = {}
    if os.path.exists(output_file):
        with open(output_file) as f:
            cache = json.load(f)
        print(f"  {len(cache):,} cached zoning lookups")

    # Build work list
    work = [item for item in listings
            if f"{item['lat']},{item['lng']}" not in cache]

    limit = 50 if (test_mode or analyze_mode) else len(work)
    work = work[:limit]

    total = len(work)
    if total == 0:
        print("  All listings already cached!")
    else:
        print(f"  Fetching zoning for {total:,} listings (cascade through {len(market['zoning_endpoints'])} endpoints)...")
        fetched = 0
        found = 0
        source_counts = {}
        for i, item in enumerate(work):
            key = f"{item['lat']},{item['lng']}"
            result = fetch_zoning_cascade(item["lat"], item["lng"], market)

            if result:
                cache[key] = result
                found += 1
                src = result.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
            else:
                cache[key] = {"zoning": None, "category": None, "sb1123": None, "source": None}

            fetched += 1

            if (i + 1) % 10 == 0 or i == total - 1:
                print(f"  [{i+1}/{total}] found={found} | last: {item.get('address','')[:40]} → {result.get('zoning','?') if result else '—'}")

            # Checkpoint
            if fetched % CHECKPOINT_EVERY == 0:
                save_cache(cache, output_file)
                print(f"  💾 Checkpoint: {len(cache):,} entries saved")

            time.sleep(RATE_LIMIT_DELAY)

        save_cache(cache, output_file)
        print(f"\nDone! {found}/{total} lookups returned zoning data.")
        print(f"Total cached: {len(cache):,} entries → {output_file}")
        if source_counts:
            print(f"  Sources: {source_counts}")

    # Analysis mode: compare real zoning vs Redfin-guessed zoning
    if analyze_mode:
        run_analysis(listings, cache)


def run_analysis(listings, cache):
    """Compare real zoning vs Redfin-guessed zoning for cached listings."""
    print("\n── Analysis: Real Zoning vs Redfin Zoning ──")

    results = []
    for item in listings:
        key = f"{item['lat']},{item['lng']}"
        if key not in cache:
            continue
        cached = cache[key]
        if not cached.get("zoning"):
            continue

        real_sb1123 = cached.get("sb1123", "")
        redfin_zone = item.get("zone", "")
        results.append({
            "address": item["address"],
            "city": item["city"],
            "redfin_type": item["type"],
            "redfin_zone": redfin_zone,
            "real_code": cached["zoning"],
            "real_category": cached.get("category", ""),
            "real_sb1123": real_sb1123,
            "source": cached.get("source", ""),
            "match": redfin_zone == real_sb1123,
        })

    if not results:
        print("  No data to analyze.")
        return

    total = len(results)
    matches = sum(1 for r in results if r["match"])
    mismatches = total - matches

    print(f"  Total compared: {total}")
    print(f"  Matches: {matches} ({matches/total*100:.0f}%)")
    print(f"  Mismatches: {mismatches} ({mismatches/total*100:.0f}%)")

    # Mismatch breakdown
    mismatch_types = {}
    for r in results:
        if not r["match"]:
            key = f"{r['redfin_zone']} → {r['real_sb1123']}"
            mismatch_types[key] = mismatch_types.get(key, 0) + 1

    if mismatch_types:
        print("\n  Mismatch patterns:")
        for k, v in sorted(mismatch_types.items(), key=lambda x: -x[1]):
            print(f"    {k}: {v}")

    # Source breakdown
    source_counts = {}
    for r in results:
        src = r.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    if source_counts:
        print(f"\n  By source: {source_counts}")


if __name__ == "__main__":
    main()

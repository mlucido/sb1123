#!/usr/bin/env python3
"""
fetch_zoning.py
Fetches real zoning codes from LA City's ZIMAS/ArcGIS endpoint for each listing.

Replaces the Redfin-guessed zoning (e.g. "Single Family Residential" → R1)
with actual zoning from the city (e.g. R2-1-O).

Reads:  listings.js (parses the JSON array from the JS file)
Writes: zoning.json — keyed by "lat,lng"

Supports incremental runs (skips already-fetched listings).
Rate-limited to ~2 req/sec. Checkpoints every 100 lookups.

Usage:
  python3 fetch_zoning.py              # All listings
  python3 fetch_zoning.py --test       # First 50 only
  python3 fetch_zoning.py --analyze    # Run on 50 listings + compare with Redfin guess
"""

import json, os, re, sys, time
import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Config ──
ZIMAS_URL = "https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/Zoning/FeatureServer/15/query"
COUNTY_ZONING_URL = "https://arcgis.lacounty.gov/arcgis/rest/services/DRP/Zoning/MapServer/0/query"
OUTPUT_FILE = "zoning.json"
CHECKPOINT_EVERY = 100
RATE_LIMIT_DELAY = 0.5  # ~2 req/sec


# ── SB 1123 Zoning Classification ──

def classify_zoning(zoning_code):
    """Convert a ZIMAS zoning code (e.g. 'R2-1-O') to an SB 1123 category.
    
    Per LA City Planning SHRA eligibility:
    - Single-family track: A, RA, RE, RS, R1, RU, RZ, RW1
    - Multifamily track: R2, RD, RW2, R3, RAS3, R4, RAS4, R5, all C zones
    """
    if not zoning_code:
        return None
    # Strip qualified conditions like [Q], [T], [D] prefixes
    code = re.sub(r'^\[.*?\]', '', zoning_code).strip()
    prefix = code.split("-")[0].upper().strip()

    # Single-family track (floor(lot/1200) units)
    # A, RA, RE*, RS*, R1*, RU*, RZ*, RW1*
    if prefix.startswith(("A", "RA", "RE", "RS", "R1", "RU", "RZ", "RW1")):
        # Exception: RW2 is multifamily
        if prefix.startswith("RW2"):
            return "R2"
        return "R1"
    
    # Multifamily track
    # R2: R2*, RD*
    if prefix.startswith(("R2", "RD")):
        return "R2"
    # R3: R3*, RAS3*, RW2* (but not RW1)
    if prefix.startswith(("R3", "RAS3", "RW2")):
        return "R3"
    # R4: R4*, RAS4*, R5*
    if prefix.startswith(("R4", "RAS4", "R5")):
        return "R4"
    # All C zones qualify for multifamily track
    if prefix.startswith("C"):
        return "R4"  # Treat as R4 for unit density (floor(lot/600))
    
    # Non-residential
    if prefix.startswith(("M", "P")):
        return "COMMERCIAL"
    if prefix.startswith("OS"):
        return "OPEN_SPACE"
    
    return None  # Unknown zone


def query_zoning(lat, lng, retries=2):
    """Query ZIMAS ArcGIS for zoning at a lat/lng point."""
    params = {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "Zoning,CATEGORY",
        "returnGeometry": "false",
        "f": "json",
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.get(ZIMAS_URL, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    attrs = features[0].get("attributes", {})
                    return {
                        "zoning": attrs.get("Zoning", ""),
                        "category": attrs.get("CATEGORY", ""),
                    }
                return None  # No zoning found (outside LA City)
            elif resp.status_code in (429, 503):
                wait = 3 + attempt * 5
                print(f"    Rate limited ({resp.status_code}), waiting {wait}s...")
                time.sleep(wait)
                continue
        except requests.exceptions.Timeout:
            if attempt < retries:
                print(f"    Timeout, retry {attempt+1}...")
                time.sleep(2)
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
    return None  # All retries failed


def classify_county_zoning(zone_code):
    """Convert an LA County zoning code to an SB 1123 category.

    County codes differ from LA City ZIMAS codes.
    Maps: R-1/R-A/RE → R1, R-2 → R2, R-3 → R3, R-4/R-5 → R4
    """
    if not zone_code:
        return None
    prefix = zone_code.strip().upper().split("-")[0]
    # Handle common county prefixes
    if prefix in ("R", "RA", "RE", "RS"):
        # Check full code for R-1, R-A, RE-9, etc.
        upper = zone_code.strip().upper()
        if upper.startswith(("R-1", "R1", "RA", "RE", "RS")):
            return "R1"
        if upper.startswith(("R-2", "R2")):
            return "R2"
        if upper.startswith(("R-3", "R3")):
            return "R3"
        if upper.startswith(("R-4", "R4", "R-5", "R5")):
            return "R4"
        return "R1"  # Default single-family for R- prefix
    if prefix in ("A", "A1", "A2"):
        return None  # Agricultural — not SB 1123 eligible
    if prefix in ("OS", "O"):
        return None  # Open space
    if prefix.startswith("C"):
        return "R4"  # Commercial zones allow multifamily under SB 1123
    return None


def query_county_zoning(lat, lng, retries=2):
    """Query LA County DRP Zoning service for zoning at a lat/lng point."""
    params = {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.get(COUNTY_ZONING_URL, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    attrs = features[0].get("attributes", {})
                    # Try common field names — county services vary
                    zone = (attrs.get("ZONE_CMPLT") or attrs.get("ZONING") or
                            attrs.get("Zone") or attrs.get("ZONE") or
                            attrs.get("ZONE_CLASS") or "")
                    category = attrs.get("CATEGORY", "") or attrs.get("GEN_PLAN", "") or ""
                    return {
                        "zoning": zone,
                        "category": category,
                        "source": "county",
                    }
                return None  # No zoning found
            elif resp.status_code in (429, 503):
                wait = 3 + attempt * 5
                print(f"    Rate limited ({resp.status_code}), waiting {wait}s...")
                time.sleep(wait)
                continue
        except requests.exceptions.Timeout:
            if attempt < retries:
                print(f"    Timeout, retry {attempt+1}...")
                time.sleep(2)
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
    return None


def load_listings_from_js():
    """Parse listings from listings.js (extracts the JSON array)."""
    js_file = "listings.js"
    if not os.path.exists(js_file):
        print(f"  No {js_file} found.")
        sys.exit(1)

    with open(js_file, encoding="utf-8") as f:
        content = f.read()

    # Extract the JSON array after "const LOADED_LISTINGS = "
    match = re.search(r'const LOADED_LISTINGS\s*=\s*(\[.*\])', content, re.DOTALL)
    if not match:
        print("  Could not parse listings.js")
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


def save_cache(cache):
    """Write cache to disk."""
    with open(OUTPUT_FILE, "w") as f:
        json.dump(cache, f, indent=1)


def main():
    test_mode = "--test" in sys.argv
    analyze_mode = "--analyze" in sys.argv

    print("Loading listings from listings.js...")
    listings = load_listings_from_js()
    print(f"  {len(listings):,} listings loaded")

    # Load existing cache
    cache = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            cache = json.load(f)
        print(f"  {len(cache):,} cached zoning lookups")

    # Build work list — prioritize LA City for better ZIMAS coverage
    work_la = []
    work_other = []
    for item in listings:
        key = f"{item['lat']},{item['lng']}"
        if key not in cache:
            if item.get("city", "") == "Los Angeles":
                work_la.append(item)
            else:
                work_other.append(item)

    work = work_la + work_other
    limit = 50 if (test_mode or analyze_mode) else len(work)
    work = work[:limit]

    total = len(work)
    if total == 0:
        print("  All listings already cached!")
    else:
        print(f"  Fetching zoning for {total:,} listings...")
        fetched = 0
        found = 0
        for i, item in enumerate(work):
            key = f"{item['lat']},{item['lng']}"
            result = query_zoning(item["lat"], item["lng"])

            if result:
                result["sb1123"] = classify_zoning(result["zoning"])
                cache[key] = result
                found += 1
            else:
                cache[key] = {"zoning": None, "category": None, "sb1123": None}

            fetched += 1

            if (i + 1) % 10 == 0 or i == total - 1:
                print(f"  [{i+1}/{total}] found={found} | last: {item.get('address','')[:40]} → {result.get('zoning','?') if result else '—'}")

            # Checkpoint
            if fetched % CHECKPOINT_EVERY == 0:
                save_cache(cache)
                print(f"  💾 Checkpoint: {len(cache):,} entries saved")

            time.sleep(RATE_LIMIT_DELAY)

        save_cache(cache)
        print(f"\nDone! {found}/{total} lookups returned zoning data.")
        print(f"Total cached: {len(cache):,} entries → {OUTPUT_FILE}")

    # ── Pass 2: LA County GIS for listings where ZIMAS returned null ──
    if not (test_mode or analyze_mode):
        null_zoning = []
        for item in listings:
            key = f"{item['lat']},{item['lng']}"
            if key in cache:
                cached = cache[key]
                if cached.get("zoning") is None and cached.get("source") != "county":
                    null_zoning.append(item)

        if null_zoning:
            print(f"\n── Pass 2: LA County GIS for {len(null_zoning):,} listings outside LA City ──")
            county_found = 0
            county_fetched = 0
            for i, item in enumerate(null_zoning):
                key = f"{item['lat']},{item['lng']}"
                result = query_county_zoning(item["lat"], item["lng"])

                if result:
                    zone_code = result.get("zoning", "")
                    sb_zone = classify_county_zoning(zone_code)
                    result["sb1123"] = sb_zone
                    cache[key] = result
                    if sb_zone:
                        county_found += 1
                else:
                    cache[key] = {"zoning": None, "category": None, "sb1123": None, "source": "county"}

                county_fetched += 1

                if (i + 1) % 10 == 0 or i == len(null_zoning) - 1:
                    zone_str = result.get("zoning", "?") if result else "—"
                    print(f"  [{i+1}/{len(null_zoning)}] county_found={county_found} | {item.get('address','')[:40]} → {zone_str}")

                if county_fetched % CHECKPOINT_EVERY == 0:
                    save_cache(cache)
                    print(f"  Checkpoint: {len(cache):,} entries saved")

                time.sleep(RATE_LIMIT_DELAY)

            save_cache(cache)
            print(f"\nCounty pass done! {county_found}/{len(null_zoning)} returned zoning data.")
        else:
            print("\n  No null-zoning listings to check with county GIS.")

    # Analysis mode: compare ZIMAS vs Redfin-guessed zoning
    if analyze_mode:
        run_analysis(listings, cache)


def run_analysis(listings, cache):
    """Compare ZIMAS zoning vs Redfin-guessed zoning for cached listings."""
    print("\n── Analysis: ZIMAS vs Redfin Zoning ──")

    results = []
    for item in listings:
        key = f"{item['lat']},{item['lng']}"
        if key not in cache:
            continue
        cached = cache[key]
        if not cached.get("zoning"):
            continue

        zimas_sb1123 = cached.get("sb1123", "")
        redfin_zone = item.get("zone", "")
        results.append({
            "address": item["address"],
            "city": item["city"],
            "redfin_type": item["type"],
            "redfin_zone": redfin_zone,
            "zimas_code": cached["zoning"],
            "zimas_category": cached["category"],
            "zimas_sb1123": zimas_sb1123,
            "match": redfin_zone == zimas_sb1123,
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

    # Write analysis markdown
    md = f"""# Zoning Analysis: ZIMAS vs Redfin Guesses

**Date:** {time.strftime('%Y-%m-%d')}
**Sample size:** {total} listings with ZIMAS data

## Summary

| Metric | Count | Pct |
|--------|-------|-----|
| Matches | {matches} | {matches/total*100:.0f}% |
| Mismatches | {mismatches} | {mismatches/total*100:.0f}% |

## Mismatch Details

| Address | Redfin Type | Redfin Zone | ZIMAS Code | ZIMAS SB1123 |
|---------|-------------|-------------|------------|---------------|
"""
    for r in results:
        if not r["match"]:
            md += f"| {r['address'][:45]} | {r['redfin_type']} | {r['redfin_zone']} | {r['zimas_code']} | {r['zimas_sb1123']} |\n"

    # Breakdown by mismatch type
    mismatch_types = {}
    for r in results:
        if not r["match"]:
            key = f"{r['redfin_zone']} → {r['zimas_sb1123']}"
            mismatch_types[key] = mismatch_types.get(key, 0) + 1

    if mismatch_types:
        md += "\n## Mismatch Patterns\n\n"
        md += "| Redfin → ZIMAS | Count |\n|----------------|-------|\n"
        for k, v in sorted(mismatch_types.items(), key=lambda x: -x[1]):
            md += f"| {k} | {v} |\n"

    md += """
## Key Takeaways

- Redfin property types are unreliable for zoning classification
- Many properties listed as "Single Family Residential" sit on R2+ zoned lots
- ZIMAS provides the authoritative zoning for LA City properties
- Properties outside LA City limits return no ZIMAS data (keep Redfin guess)
"""

    with open("analysis_zoning.md", "w") as f:
        f.write(md)
    print(f"\n  Analysis written to analysis_zoning.md")


if __name__ == "__main__":
    main()

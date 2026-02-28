#!/usr/bin/env python3
"""
build_rental_data.py
Converts rental_comps.csv into rental_data.js for the frontend rental comps table.

Usage:
  python3 build_rental_data.py              # LA (default)
  python3 build_rental_data.py --market sd  # San Diego
"""
import csv, json, re, os, sys
from datetime import datetime, timezone

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file

# Property type → compact code (matches build_comps.py PT_MAP)
PT_MAP = {
    "Single Family Residential": 1,
    "Townhouse": 3,
    "Condo/Co-op": 2,
    "Multi-Family (2-4 Unit)": 4,
    "Multi-Family (5+ Unit)": 5,
    "Mobile/Manufactured Home": 1,
    "Ranch": 1,
}

market = get_market()
LAT_MIN, LAT_MAX = market["lat_min"], market["lat_max"]
LNG_MIN, LNG_MAX = market["lng_min"], market["lng_max"]

# ── Data quality thresholds ──
MIN_RENT = 500
MAX_RENT = 20000
MIN_SQFT = 100
MAX_AGE_DAYS = 150  # Drop rental listings older than 5 months

src = market_file("rental_comps.csv", market)
if not os.path.exists(src):
    print(f"  No {src} found. Run fetch_rental_comps.py first.")
    sys.exit(1)

print(f"\n  Reading {src}...")

comps = []
skipped = 0
stale_skipped = 0
total = 0
now = datetime.now(timezone.utc)

with open(src, encoding="utf-8", errors="replace") as f:
    reader = csv.DictReader(f)
    for row in reader:
        total += 1
        try:
            lat = float(row.get("LATITUDE") or 0)
            lng = float(row.get("LONGITUDE") or 0)

            if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                skipped += 1
                continue

            # Freshness filter — drop listings older than MAX_AGE_DAYS
            freshness_ts = row.get("FRESHNESS TIMESTAMP", "").strip()
            if freshness_ts:
                try:
                    dt = datetime.fromisoformat(freshness_ts.replace("Z", "+00:00"))
                    age_days = (now - dt).days
                    if age_days > MAX_AGE_DAYS:
                        stale_skipped += 1
                        continue
                except Exception:
                    pass  # Keep listings with unparseable dates

            price_str = re.sub(r"[^0-9.]", "", row.get("PRICE") or "0") or "0"
            rent = float(price_str)

            if rent < MIN_RENT or rent > MAX_RENT:
                skipped += 1
                continue

            sqft_str = re.sub(r"[^0-9.]", "", row.get("SQUARE FEET") or "0") or "0"
            sqft = int(float(sqft_str)) if sqft_str != "0" else 0

            if sqft > 0 and sqft < MIN_SQFT:
                skipped += 1
                continue

            beds_str = re.sub(r"[^0-9.]", "", row.get("BEDS", "") or "")
            beds = int(float(beds_str)) if beds_str else None
            baths_str = re.sub(r"[^0-9.]", "", row.get("BATHS", "") or "")
            baths = float(baths_str) if baths_str else None

            prop_type = row.get("PROPERTY TYPE", "").strip()
            pt = PT_MAP.get(prop_type, 0)

            zipcode = str(row.get("ZIP OR POSTAL CODE", "")).strip()

            address_parts = [
                row.get("ADDRESS", "").strip(),
                row.get("CITY", "").strip(),
                "CA",
                zipcode,
            ]
            address = " ".join(p for p in address_parts if p)

            rec = {
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "rent": int(rent),
            }
            if beds is not None:
                rec["bd"] = beds
            if baths is not None:
                rec["ba"] = baths
            if sqft > 0:
                rec["sqft"] = sqft
            if pt:
                rec["pt"] = pt
            if address:
                rec["addr"] = address
            if zipcode:
                rec["zip"] = zipcode

            comps.append(rec)
        except Exception:
            skipped += 1
            continue

print(f"  Total rows: {total}")
print(f"  Valid rental comps: {len(comps)}")
print(f"  Skipped (quality/bounds): {skipped}")
if stale_skipped:
    print(f"  Skipped (stale >{MAX_AGE_DAYS}d): {stale_skipped}")

if not comps:
    print("  No rental comps to write.")
    sys.exit(1)

# Stats
with_sqft = sum(1 for c in comps if "sqft" in c)
with_beds = sum(1 for c in comps if "bd" in c)
rents = sorted(c["rent"] for c in comps)
median_rent = rents[len(rents) // 2]
print(f"  Median rent: ${median_rent:,}")
print(f"  With sqft: {with_sqft:,} ({with_sqft/len(comps)*100:.0f}%)")
print(f"  With beds: {with_beds:,} ({with_beds/len(comps)*100:.0f}%)")

# Type breakdown
pt_counts = {}
for c in comps:
    pt_counts[c.get("pt", 0)] = pt_counts.get(c.get("pt", 0), 0) + 1
PT_NAMES = {0: "Unknown", 1: "SFR", 2: "Condo", 3: "Townhome", 4: "MF 2-4", 5: "MF 5+"}
print(f"\n  Type breakdown:")
for pt_code in sorted(pt_counts.keys()):
    print(f"    {PT_NAMES.get(pt_code, '?')}: {pt_counts[pt_code]:,}")

# ── Write rental_data.js ──
output_file = market_file("rental_data.js", market)
js = "const LOADED_RENTAL_COMPS = " + json.dumps(comps, separators=(",", ":")) + ";"
with open(output_file, "w") as f:
    f.write(js)

size_kb = len(js) / 1024
print(f"\n  Written: {output_file} ({size_kb:.0f} KB, {len(comps):,} rental comps)")
print(f"  Then refresh http://localhost:8080\n")

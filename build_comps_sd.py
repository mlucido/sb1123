#!/usr/bin/env python3
"""
build_comps_sd.py
Converts redfin_sold_sd.csv into data_sd.js (San Diego comp data for analytics).

Usage:
  python3 build_comps_sd.py
"""
import csv, json, re, os
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── San Diego County bounding box ──
SD_LAT_MIN, SD_LAT_MAX = 32.53, 33.51
SD_LNG_MIN, SD_LNG_MAX = -117.60, -116.08

# ── Data quality thresholds ──
MIN_SQFT = 100
MAX_PRICE = 50_000_000
MAX_PPSF = 5_000
MIN_YEAR_BUILT = 1800
CURRENT_YEAR = datetime.now().year

TYPE_TO_ZONE = {
    "Single Family Residential": "R1",
    "Townhouse": "R2",
    "Condo/Co-op": "R2",
    "Multi-Family (2-4 Unit)": "R3",
    "Multi-Family (5+ Unit)": "R4",
    "Mobile/Manufactured Home": "R1",
    "Ranch": "R1",
}

src = "redfin_sold_sd.csv"
if not os.path.exists(src):
    print(f"  No {src} found. Run fetch_sold_comps_sd.py first.")
    exit(1)

print(f"\n  Reading {src}...")

comps = []
skipped = 0
skip_no_date = 0
skip_outlier = 0
total = 0

with open(src, encoding="utf-8", errors="replace") as f:
    reader = csv.DictReader(f)
    for row in reader:
        total += 1
        try:
            lat = float(row.get("LATITUDE") or 0)
            lng = float(row.get("LONGITUDE") or 0)

            if not (SD_LAT_MIN <= lat <= SD_LAT_MAX and SD_LNG_MIN <= lng <= SD_LNG_MAX):
                skipped += 1
                continue

            price_str = re.sub(r"[^0-9.]", "", row.get("PRICE") or "0") or "0"
            price = float(price_str)
            sqft_str = re.sub(r"[^0-9.]", "", row.get("SQUARE FEET") or "0") or "0"
            sqft = float(sqft_str)

            if price <= 0 or sqft <= 0:
                skipped += 1
                continue

            sold_date = row.get("SOLD DATE", "").strip()
            if not sold_date:
                skip_no_date += 1
                continue

            ppsf = round(price / sqft)

            if sqft < MIN_SQFT or price > MAX_PRICE or ppsf > MAX_PPSF:
                skip_outlier += 1
                continue

            year_built_str = row.get("YEAR BUILT", "").strip()
            year_built = int(year_built_str) if year_built_str.isdigit() else None
            if year_built and (year_built < MIN_YEAR_BUILT or year_built > CURRENT_YEAR):
                year_built = None

            zipcode = str(row.get("ZIP OR POSTAL CODE", "")).strip()
            prop_type = row.get("PROPERTY TYPE", "").strip()
            zone = TYPE_TO_ZONE.get(prop_type, "")

            beds_str = re.sub(r"[^0-9.]", "", row.get("BEDS", "") or "")
            beds = int(float(beds_str)) if beds_str else None
            baths_str = re.sub(r"[^0-9.]", "", row.get("BATHS", "") or "")
            baths = float(baths_str) if baths_str else None

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
                "price": int(price),
                "sqft": int(sqft),
                "zone": zone,
                "address": address,
                "date": sold_date,
                "zip": zipcode,
                "ppsf": ppsf,
                "yb": year_built,
            }
            if beds is not None:
                rec["bd"] = beds
            if baths is not None:
                rec["ba"] = baths

            comps.append(rec)
        except Exception:
            skipped += 1
            continue

print(f"  Total rows: {total}")
print(f"  Valid comps: {len(comps)}")
print(f"  Skipped (location/price/sqft): {skipped}")
print(f"  Skipped (no date): {skip_no_date}")
print(f"  Skipped (outliers): {skip_outlier}")

if not comps:
    print("  No comps to write.")
    exit(1)

# Zone breakdown
zone_counts = {}
for c in comps:
    z = c["zone"] or "Unknown"
    zone_counts[z] = zone_counts.get(z, 0) + 1
print(f"\n  Zone breakdown:")
for z in ["R1", "R2", "R3", "R4", "Unknown"]:
    if z in zone_counts:
        print(f"    {z}: {zone_counts[z]:,}")

with_beds = sum(1 for c in comps if "bd" in c)
with_baths = sum(1 for c in comps if "ba" in c)
print(f"  With beds: {with_beds:,} ({with_beds/len(comps)*100:.0f}%)")
print(f"  With baths: {with_baths:,} ({with_baths/len(comps)*100:.0f}%)")

zips = set(c["zip"] for c in comps if c["zip"])
print(f"  Unique zip codes: {len(zips)}")

# Write data_sd.js
js = "const LOADED_COMPS_SD = " + json.dumps(comps, separators=(",", ":")) + ";"
with open("data_sd.js", "w") as f:
    f.write(js)

size_kb = len(js) / 1024
print(f"\n  Written: data_sd.js ({size_kb:.0f} KB, {len(comps):,} comps)")
print(f"  Then refresh analytics.html\n")

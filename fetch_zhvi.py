#!/usr/bin/env python3
"""
fetch_zhvi.py
Downloads Zillow Home Value Index (ZHVI) CSV for single-family homes,
computes 12mo/24mo appreciation by zip code, outputs zhvi.json.

Usage:
    python3 fetch_zhvi.py
    python3 fetch_zhvi.py --market sd

Output:
    zhvi.json — { "90210": {"val_now": 2100000, "val_12mo": 1950000, "appr_12mo": 7.7, "appr_24mo": 15.2}, ... }
"""
import csv, json, os, io, sys
import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file

market = get_market()
listings_file = market_file("listings.js", market)
output_file = market_file("zhvi.json", market)

# Zillow Research ZHVI CSV — Single-Family, smoothed, seasonally adjusted, by zip
ZHVI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)
CACHE_FILE = "zhvi_cache.csv"

# ── Step 1: Extract unique zip codes from listings.js ──
print(f"\n📋 Step 1: Loading zip codes from {listings_file}...")
if not os.path.exists(listings_file):
    print(f"   ❌ {listings_file} not found — run: python3 listings_build.py")
    sys.exit(1)

with open(listings_file, "r") as f:
    raw = f.read()
start = raw.index("[")
end = raw.rindex("]") + 1
listings = json.loads(raw[start:end])

our_zips = set()
for l in listings:
    z = str(l.get("zip", "")).strip()
    if z and len(z) == 5 and z.isdigit():
        our_zips.add(z)

print(f"   Found {len(our_zips)} unique zip codes from {len(listings):,} listings")

# ── Step 2: Download ZHVI CSV ──
print(f"\n📥 Step 2: Downloading Zillow ZHVI data...")

csv_path = None
if os.path.exists(CACHE_FILE):
    import time as _time
    age_hours = (_time.time() - os.path.getmtime(CACHE_FILE)) / 3600
    if age_hours < 168:  # 7 days
        print(f"   Using cached {CACHE_FILE} ({age_hours:.0f}h old)")
        csv_path = CACHE_FILE

if not csv_path:
    try:
        print(f"   Downloading from Zillow Research...")
        resp = requests.get(ZHVI_URL, timeout=120, headers={
            "User-Agent": "Mozilla/5.0 (Python/fetch_zhvi.py)"
        })
        if resp.status_code == 200 and len(resp.content) > 10000:
            with open(CACHE_FILE, "wb") as f:
                f.write(resp.content)
            print(f"   ✅ Downloaded {len(resp.content):,} bytes")
            csv_path = CACHE_FILE
        else:
            print(f"   ⚠️  HTTP {resp.status_code} (size: {len(resp.content)})")
    except Exception as e:
        print(f"   ⚠️  Failed: {e}")

if not csv_path:
    print("   ❌ Could not download ZHVI data.")
    print("   Please manually download from: https://www.zillow.com/research/data/")
    print("   Save as zhvi_cache.csv in this directory and re-run.")
    sys.exit(1)

# ── Step 3: Parse CSV and compute appreciation ──
print(f"\n📊 Step 3: Parsing ZHVI data and computing appreciation...")

zhvi = {}
total_rows = 0
ca_rows = 0

with open(csv_path, encoding="utf-8", errors="replace") as f:
    reader = csv.DictReader(f)
    cols = reader.fieldnames or []

    # Find date columns (format: YYYY-MM-DD)
    import re
    date_cols = sorted([c for c in cols if re.match(r"\d{4}-\d{2}-\d{2}", c)])

    if not date_cols:
        print(f"   ❌ No date columns found in CSV. Columns: {cols[:20]}")
        sys.exit(1)

    print(f"   Date range: {date_cols[0]} → {date_cols[-1]} ({len(date_cols)} months)")

    for row in reader:
        total_rows += 1
        state = row.get("State", "").strip()
        if state != "CA":
            continue
        ca_rows += 1

        zipcode = str(row.get("RegionName", "")).strip()
        if not zipcode or len(zipcode) != 5:
            continue

        # Extract values: most recent, 12mo ago, 24mo ago
        # Work backwards from the end of date_cols to find non-empty values
        vals = []
        for col in reversed(date_cols):
            v = row.get(col, "").strip()
            if v:
                try:
                    vals.append((col, float(v)))
                except ValueError:
                    continue
            if len(vals) >= 3:  # We need current + enough history
                break

        if not vals:
            continue

        val_now = vals[0][1]
        date_now = vals[0][0]

        # Find value ~12 months ago
        val_12mo = None
        val_24mo = None
        target_12mo_idx = len(date_cols) - 1 - 12  # ~12 months back
        target_24mo_idx = len(date_cols) - 1 - 24  # ~24 months back

        if target_12mo_idx >= 0 and target_12mo_idx < len(date_cols):
            v = row.get(date_cols[target_12mo_idx], "").strip()
            if v:
                try:
                    val_12mo = float(v)
                except ValueError:
                    pass

        if target_24mo_idx >= 0 and target_24mo_idx < len(date_cols):
            v = row.get(date_cols[target_24mo_idx], "").strip()
            if v:
                try:
                    val_24mo = float(v)
                except ValueError:
                    pass

        entry = {"val_now": round(val_now)}
        if val_12mo and val_12mo > 0:
            entry["val_12mo"] = round(val_12mo)
            entry["appr_12mo"] = round((val_now / val_12mo - 1) * 100, 1)
        if val_24mo and val_24mo > 0:
            entry["val_24mo"] = round(val_24mo)
            entry["appr_24mo"] = round((val_now / val_24mo - 1) * 100, 1)

        zhvi[zipcode] = entry

print(f"   Total rows: {total_rows:,}")
print(f"   CA rows: {ca_rows:,}")
print(f"   CA zips with ZHVI: {len(zhvi):,}")

# ── Step 4: Filter to our zip codes ──
print(f"\n🎯 Step 4: Filtering to market zip codes...")
result = {}
for z in our_zips:
    if z in zhvi:
        result[z] = zhvi[z]

matched = len(result)
unmatched = our_zips - set(result.keys())
print(f"   Matched: {matched}/{len(our_zips)} zip codes")
if unmatched:
    print(f"   Unmatched: {len(unmatched)} zips: {sorted(list(unmatched))[:20]}...")

# ── Step 5: Write zhvi.json ──
print(f"\n📦 Step 5: Writing {output_file}...")
with open(output_file, "w") as f:
    json.dump(result, f, separators=(",", ":"))

size_kb = os.path.getsize(output_file) / 1024
print(f"   Created {output_file} ({size_kb:.1f} KB, {len(result)} zip codes)")

# ── Summary ──
if result:
    appr_12 = [v["appr_12mo"] for v in result.values() if "appr_12mo" in v]
    appr_24 = [v["appr_24mo"] for v in result.values() if "appr_24mo" in v]
    if appr_12:
        appr_12.sort()
        med = appr_12[len(appr_12) // 2]
        print(f"\n📊 Summary:")
        print(f"   12mo appreciation — Median: {med:+.1f}% | Min: {min(appr_12):+.1f}% | Max: {max(appr_12):+.1f}%")
    if appr_24:
        appr_24.sort()
        med = appr_24[len(appr_24) // 2]
        print(f"   24mo appreciation — Median: {med:+.1f}% | Min: {min(appr_24):+.1f}% | Max: {max(appr_24):+.1f}%")
    print(f"   Done! ✅\n")
else:
    print("\n   ⚠️  No matching ZHVI data found.\n")

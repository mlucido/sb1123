#!/usr/bin/env python3
"""
build_subdiv_comps.py
Detects small lot subdivision sales from redfin_sold.csv, clusters them by
proximity and time, applies appreciation adjustment from zhvi.json, and
outputs subdiv_comps.json for use as Tier 0 exit $/SF in listings_build.py.

Usage:
    python3 build_subdiv_comps.py
    python3 build_subdiv_comps.py --market sd

Output:
    subdiv_comps.json — [...] array of appreciation-adjusted subdivision comps
"""
import csv, json, re, os, math, sys
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, TYPE_TO_ZONE

market = get_market()
LAT_MIN, LAT_MAX = market["lat_min"], market["lat_max"]
LNG_MIN, LNG_MAX = market["lng_min"], market["lng_max"]

# ── Subdivision detection thresholds ──
MIN_YEAR_BUILT = 2019     # Modern construction = likely subdivision
MAX_LOT_SF = 4000         # Small lots = subdivided from larger parcel
MIN_LOT_SF = 1000         # Filter data errors
MIN_SQFT = 1200           # Townhome-scale product
MAX_SQFT = 2500
MIN_PRICE = 400000
SUBDIV_PROP_TYPES = {"Single Family Residential", "Townhouse", "Condo/Co-op"}

# ── Cluster detection ──
CLUSTER_PROXIMITY_DEG = 0.003   # ~200ft = same subdivision project
CLUSTER_MAX_MONTHS = 18         # Sold within 18 months of each other

# ── Appreciation adjustment ──
MAX_ADJUSTMENT_PCT = 30  # Cap at ±30%

now = datetime.now()

# ── Step 1: Read redfin_sold.csv and filter subdivision candidates ──
src = market_file("redfin_sold.csv", market)
if not os.path.exists(src):
    print(f"  ❌ {src} not found. Run fetch_sold_comps.py first.")
    sys.exit(1)

print(f"\n📄 Step 1: Reading {src} and filtering subdivision candidates...")

candidates = []
total = 0
skipped = {"location": 0, "year_built": 0, "lot": 0, "sqft": 0, "price": 0, "type": 0, "date": 0, "other": 0}

with open(src, encoding="utf-8", errors="replace") as f:
    reader = csv.DictReader(f)
    for row in reader:
        total += 1
        try:
            lat = float(row.get("LATITUDE") or 0)
            lng = float(row.get("LONGITUDE") or 0)
            if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                skipped["location"] += 1
                continue

            # Year built filter
            yb_str = row.get("YEAR BUILT", "").strip()
            if not yb_str.isdigit():
                skipped["year_built"] += 1
                continue
            yb = int(yb_str)
            if yb < MIN_YEAR_BUILT:
                skipped["year_built"] += 1
                continue

            # Lot size filter
            lot_str = re.sub(r"[^0-9.]", "", row.get("LOT SIZE") or "0") or "0"
            lot = float(lot_str)
            if lot < MIN_LOT_SF or lot > MAX_LOT_SF:
                skipped["lot"] += 1
                continue

            # Sqft filter
            sqft_str = re.sub(r"[^0-9.]", "", row.get("SQUARE FEET") or "0") or "0"
            sqft = float(sqft_str)
            if sqft < MIN_SQFT or sqft > MAX_SQFT:
                skipped["sqft"] += 1
                continue

            # Price filter
            price_str = re.sub(r"[^0-9.]", "", row.get("PRICE") or "0") or "0"
            price = float(price_str)
            if price < MIN_PRICE:
                skipped["price"] += 1
                continue

            # Property type filter
            prop_type = row.get("PROPERTY TYPE", "").strip()
            if prop_type not in SUBDIV_PROP_TYPES:
                skipped["type"] += 1
                continue

            # Sold date required
            sold_date_str = row.get("SOLD DATE", "").strip()
            if not sold_date_str:
                skipped["date"] += 1
                continue

            # Parse sold date
            sold_date = None
            for fmt in ("%B-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
                try:
                    sold_date = datetime.strptime(sold_date_str, fmt)
                    break
                except ValueError:
                    continue
            if not sold_date:
                skipped["date"] += 1
                continue

            ppsf = round(price / sqft)
            zipcode = str(row.get("ZIP OR POSTAL CODE", "")).strip()
            zone = TYPE_TO_ZONE.get(prop_type, "")

            candidates.append({
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "ppsf": ppsf,
                "price": int(price),
                "sqft": int(sqft),
                "lot": int(lot),
                "yb": yb,
                "sold": sold_date_str,
                "sold_date": sold_date,
                "zip": zipcode,
                "zone": zone,
            })
        except Exception:
            skipped["other"] += 1
            continue

print(f"   Total rows: {total:,}")
print(f"   Subdivision candidates: {len(candidates):,}")
for reason, count in sorted(skipped.items()):
    if count > 0:
        print(f"   Skipped ({reason}): {count:,}")

if not candidates:
    print("\n   ⚠️  No subdivision candidates found. Writing empty file.")
    output_file = market_file("subdiv_comps.json", market)
    with open(output_file, "w") as f:
        json.dump([], f)
    print(f"   Created {output_file} (empty)")
    sys.exit(0)

# ── Step 2: Cluster detection ──
print(f"\n🔗 Step 2: Detecting subdivision clusters...")

# Sort by location for efficient clustering
candidates.sort(key=lambda c: (c["lat"], c["lng"]))

# Assign cluster IDs using proximity + time window
cluster_id = 0
for c in candidates:
    c["cluster_id"] = None

for i, c in enumerate(candidates):
    if c["cluster_id"] is not None:
        continue

    # Start new cluster
    cluster_id += 1
    c["cluster_id"] = cluster_id
    cluster_members = [i]

    # Find all neighbors within proximity AND time window
    for j in range(i + 1, len(candidates)):
        d = candidates[j]
        if d["cluster_id"] is not None:
            continue

        # Check proximity
        if (abs(c["lat"] - d["lat"]) <= CLUSTER_PROXIMITY_DEG and
            abs(c["lng"] - d["lng"]) <= CLUSTER_PROXIMITY_DEG):
            # Check time window — within 18 months of ANY cluster member
            in_window = False
            for m_idx in cluster_members:
                m = candidates[m_idx]
                days_apart = abs((c["sold_date"] - d["sold_date"]).days)
                if days_apart <= CLUSTER_MAX_MONTHS * 30:
                    in_window = True
                    break
            if in_window:
                d["cluster_id"] = cluster_id
                cluster_members.append(j)

# Count cluster sizes
cluster_sizes = {}
for c in candidates:
    cid = c["cluster_id"]
    cluster_sizes[cid] = cluster_sizes.get(cid, 0) + 1

# Filter: keep only comps in clusters of 2+ (confirms subdivision)
clustered = [c for c in candidates if cluster_sizes.get(c["cluster_id"], 0) >= 2]
# Also tag cluster_size on each
for c in clustered:
    c["cluster_size"] = cluster_sizes[c["cluster_id"]]

# Stats
n_clusters = len(set(c["cluster_id"] for c in clustered))
singleton = sum(1 for c in candidates if cluster_sizes.get(c["cluster_id"], 0) < 2)
print(f"   Clusters found (2+ comps): {n_clusters}")
print(f"   Clustered comps: {len(clustered):,}")
print(f"   Singletons removed: {singleton:,}")

if not clustered:
    print("\n   ⚠️  No clusters found. Writing all candidates as comps (no cluster filter).")
    # Fall back to using all candidates
    clustered = candidates
    for c in clustered:
        c["cluster_size"] = 1

# ── Step 3: Appreciation adjustment using zhvi.json ──
zhvi_file = market_file("zhvi.json", market)
zhvi = {}
if os.path.exists(zhvi_file):
    print(f"\n📈 Step 3: Loading appreciation data from {zhvi_file}...")
    with open(zhvi_file) as f:
        zhvi = json.load(f)
    print(f"   Loaded {len(zhvi):,} zip-level appreciation records")
else:
    print(f"\n⚠️  {zhvi_file} not found — skipping appreciation adjustment")
    print(f"   Run: python3 fetch_zhvi.py")

adj_count = 0
adj_pcts = []
for c in clustered:
    months_ago = (now - c["sold_date"]).days / 30.0
    zipcode = c["zip"]
    appr_12mo = 0

    if zipcode in zhvi and "appr_12mo" in zhvi[zipcode]:
        appr_12mo = zhvi[zipcode]["appr_12mo"]

    if appr_12mo != 0 and months_ago > 0:
        # Compound appreciation: adj = sold_ppsf * (1 + annual_rate) ^ (months/12)
        annual_rate = appr_12mo / 100.0
        raw_factor = (1 + annual_rate) ** (months_ago / 12.0)
        # Cap adjustment at ±30%
        factor = max(1 - MAX_ADJUSTMENT_PCT / 100, min(1 + MAX_ADJUSTMENT_PCT / 100, raw_factor))
        adj_ppsf = round(c["ppsf"] * factor)
        adj_pct = round((factor - 1) * 100, 1)
    else:
        adj_ppsf = c["ppsf"]
        adj_pct = 0.0

    c["adj_ppsf"] = adj_ppsf
    c["appr_pct"] = adj_pct
    if adj_pct != 0:
        adj_count += 1
        adj_pcts.append(adj_pct)

print(f"   Appreciation-adjusted: {adj_count:,}/{len(clustered):,} comps")
if adj_pcts:
    adj_pcts.sort()
    print(f"   Adjustment range: {min(adj_pcts):+.1f}% to {max(adj_pcts):+.1f}% (median {adj_pcts[len(adj_pcts)//2]:+.1f}%)")

# ── Step 4: Write subdiv_comps.json ──
output_file = market_file("subdiv_comps.json", market)
print(f"\n📦 Step 4: Writing {output_file}...")

output = []
for c in clustered:
    output.append({
        "lat": c["lat"],
        "lng": c["lng"],
        "ppsf": c["ppsf"],
        "adj_ppsf": c["adj_ppsf"],
        "price": c["price"],
        "sqft": c["sqft"],
        "lot": c["lot"],
        "yb": c["yb"],
        "sold": c["sold"],
        "zip": c["zip"],
        "cluster_id": c["cluster_id"],
        "cluster_size": c["cluster_size"],
        "appr_pct": c["appr_pct"],
        "zone": c["zone"],
    })

with open(output_file, "w") as f:
    json.dump(output, f, separators=(",", ":"))

size_kb = os.path.getsize(output_file) / 1024
print(f"   Created {output_file} ({size_kb:.1f} KB, {len(output):,} comps)")

# ── Summary ──
print(f"\n📊 Summary:")
print(f"   Total subdivision comps: {len(output):,}")
print(f"   Clusters: {len(set(c['cluster_id'] for c in output)):,}")
ppsf_vals = sorted([c["ppsf"] for c in output])
adj_vals = sorted([c["adj_ppsf"] for c in output])
if ppsf_vals:
    print(f"   Raw $/SF — Median: ${ppsf_vals[len(ppsf_vals)//2]:,} | Min: ${min(ppsf_vals):,} | Max: ${max(ppsf_vals):,}")
    print(f"   Adj $/SF — Median: ${adj_vals[len(adj_vals)//2]:,} | Min: ${min(adj_vals):,} | Max: ${max(adj_vals):,}")

# Zone breakdown
zone_counts = {}
for c in output:
    z = c["zone"] or "Unknown"
    zone_counts[z] = zone_counts.get(z, 0) + 1
print(f"   Zone breakdown: {zone_counts}")

# Cluster size distribution
size_dist = {}
for c in output:
    s = c["cluster_size"]
    size_dist[s] = size_dist.get(s, 0) + 1
print(f"   Cluster sizes: {dict(sorted(size_dist.items()))}")
print(f"   Done! ✅\n")

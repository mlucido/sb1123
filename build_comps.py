#!/usr/bin/env python3
"""
build_comps.py
Converts redfin_sold.csv into data.js (comp data for the GUI).
Replaces the old assessor-based comps with fresh Redfin sold data.

Usage:
  python3 build_comps.py
  python3 listings_build.py   # Rebuild listings with updated neighborhood $/SF
"""
import csv, json, re, os, sys
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, TYPE_TO_ZONE

# Property type → numeric code (preserved alongside zone for comp weighting)
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
MIN_SQFT = 100        # Filter impossible sqft (data entry errors)
MAX_PRICE = 50_000_000  # Filter commercial outliers
MAX_PPSF = 5_000      # Filter impossible $/SF
MIN_YEAR_BUILT = 1800  # Filter bogus year built
CURRENT_YEAR = datetime.now().year

# ── ARV Model config ──
ARV_CONFIG = {
    "cell_size": 0.005,       # Grid cell size in degrees (~0.35 miles)
    "target_sf": 1750,        # SB 1123 product size for normalization
    "min_comps_per_cell": 3,  # Min comps to form a cluster
    "default_premium": 120,   # Default T1-T2 premium when insufficient data
    "min_slope": 200,         # Min regression slope ($/SF) for sanity
    "max_slope": 1500,        # Max regression slope ($/SF) for sanity
    "sqft_min": 1000,         # Min sqft for size curve fitting
    "sqft_max": 3500,         # Max sqft for size curve fitting
}


# ── ARV Model functions ──

def recency_weight(sale_date_str):
    """Compute time-decay weight for a comp based on sale date."""
    if not sale_date_str:
        return 0.5
    try:
        sale = datetime.strptime(sale_date_str, "%B-%d-%Y")  # Redfin: "January-15-2025"
    except Exception:
        try:
            sale = datetime.strptime(sale_date_str, "%Y-%m-%d")
        except Exception:
            return 0.5
    months_ago = (datetime.now() - sale).days / 30.44
    if months_ago <= 6: return 1.0
    elif months_ago <= 12: return 0.85
    elif months_ago <= 18: return 0.65
    elif months_ago <= 24: return 0.50
    elif months_ago <= 36: return 0.35
    else: return 0.20


def build_grid(comps):
    """Build spatial grid index for fast neighbor lookups."""
    CELL = ARV_CONFIG["cell_size"]
    grid = {}
    for i, c in enumerate(comps):
        key = (int(c['lat'] / CELL), int(c['lng'] / CELL))
        if key not in grid:
            grid[key] = []
        grid[key].append(i)
    return grid


def get_neighbors(grid, lat, lng, radius_cells=1):
    """Get comp indices from adjacent grid cells."""
    CELL = ARV_CONFIG["cell_size"]
    center_r = int(lat / CELL)
    center_c = int(lng / CELL)
    indices = []
    for dr in range(-radius_cells, radius_cells + 1):
        for dc in range(-radius_cells, radius_cells + 1):
            key = (center_r + dr, center_c + dc)
            if key in grid:
                indices.extend(grid[key])
    return indices


def compute_neighborhood_medians(comps):
    """Compute neighborhood median $/SF for each comp using spatial grid."""
    grid = build_grid(comps)
    for i, c in enumerate(comps):
        neighbor_idx = get_neighbors(grid, c['lat'], c['lng'], radius_cells=1)
        neighbor_ppsfs = [comps[j]['ppsf'] for j in neighbor_idx if j != i and comps[j]['ppsf'] > 0]

        # Expand to radius 2 if too few
        if len(neighbor_ppsfs) < 5:
            neighbor_idx = get_neighbors(grid, c['lat'], c['lng'], radius_cells=2)
            neighbor_ppsfs = [comps[j]['ppsf'] for j in neighbor_idx if j != i and comps[j]['ppsf'] > 0]

        if neighbor_ppsfs:
            neighbor_ppsfs.sort()
            c['_nbhd_median'] = neighbor_ppsfs[len(neighbor_ppsfs) // 2]
        else:
            c['_nbhd_median'] = c['ppsf']


def classify_tier(yb, ppsf, nbhd_median):
    """Classify comp as T1 (New/Remodel) or T2 (Existing)."""
    residual = ppsf - nbhd_median

    # Strong T1: new construction
    if yb and yb >= 2015:
        return 1

    # Strong T1: high residual
    if residual > 100:
        return 1

    # Strong T2: low residual on old home
    if residual < -30 and (not yb or yb < 2000):
        return 2

    # Moderate T1: somewhat elevated on older home
    if residual > 30 and (not yb or yb < 2000):
        return 1

    # Recent-ish homes (2000-2015)
    if yb and yb >= 2000:
        return 1

    return 2


def fit_size_curve(comps_list, target_sf):
    """Weighted linear regression: price = intercept + slope * sqft.
    Pure Python, no numpy/scipy.
    Returns predicted $/SF at target_sf, or None if insufficient data."""
    cfg = ARV_CONFIG
    valid = [c for c in comps_list if cfg["sqft_min"] <= c['sqft'] <= cfg["sqft_max"] and c['ppsf'] > 0]
    if len(valid) < 3:
        return None

    xs = [c['sqft'] for c in valid]
    ys = [c['price'] for c in valid]
    ws = [c.get('rw', 0.5) for c in valid]

    sw = sum(ws)
    sx = sum(w * x for w, x in zip(ws, xs))
    sy = sum(w * y for w, y in zip(ws, ys))
    sxx = sum(w * x * x for w, x in zip(ws, xs))
    sxy = sum(w * x * y for w, x, y in zip(ws, xs, ys))

    denom = sw * sxx - sx * sx
    if abs(denom) < 1e-10:
        return None

    slope = (sw * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / sw

    if slope < cfg["min_slope"] or slope > cfg["max_slope"]:
        return None

    predicted_price = intercept + slope * target_sf
    if predicted_price <= 0:
        return None

    ppsf_at_target = round(predicted_price / target_sf)

    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    mean_resid = sum(residuals) / len(residuals)
    var_resid = sum((r - mean_resid) ** 2 for r in residuals) / max(1, len(residuals) - 2)
    stdev_ppsf = round((var_resid ** 0.5) / target_sf)

    return {
        'ppsf_at_target': ppsf_at_target,
        'price_at_target': round(predicted_price),
        'stdev': stdev_ppsf,
    }


def compute_clusters(comps):
    """Group comps into grid cells, fit size curves per tier, output cluster summaries."""
    CELL = ARV_CONFIG["cell_size"]
    TARGET_SF = ARV_CONFIG["target_sf"]
    MIN_COMPS = ARV_CONFIG["min_comps_per_cell"]
    DEFAULT_PREM = ARV_CONFIG["default_premium"]

    # Group by cell
    cells = {}
    for c in comps:
        cr = int(c['lat'] / CELL)
        cc = int(c['lng'] / CELL)
        key = f"{cr * CELL:.3f}_{cc * CELL:.3f}"
        if key not in cells:
            cells[key] = {'comps': [], 'lat': cr * CELL + CELL / 2, 'lng': cc * CELL + CELL / 2}
        cells[key]['comps'].append(c)

    clusters = []
    for cell_id, cell in cells.items():
        all_c = cell['comps']
        t1 = [c for c in all_c if c.get('t') == 1]
        t2 = [c for c in all_c if c.get('t') == 2]

        if len(all_c) < MIN_COMPS:
            continue

        cluster = {
            'id': cell_id,
            'lat': round(cell['lat'], 4),
            'lng': round(cell['lng'], 4),
            'n': len(all_c),
            't1n': len(t1),
            't2n': len(t2),
        }

        # Fit T1 curve
        t1_result = fit_size_curve(t1, TARGET_SF)
        if t1_result:
            cluster['t1psf'] = t1_result['ppsf_at_target']
            cluster['t1price'] = t1_result['price_at_target']
            cluster['t1std'] = t1_result['stdev']
            cluster['t1fb'] = 0  # fallback level 0 = per-cell per-tier

        # Fit T2 curve
        t2_result = fit_size_curve(t2, TARGET_SF)
        if t2_result:
            cluster['t2psf'] = t2_result['ppsf_at_target']
            cluster['t2price'] = t2_result['price_at_target']
            cluster['t2std'] = t2_result['stdev']

        # Fallback 1: if T1 has too few, use all comps + estimated premium
        if 't1psf' not in cluster and len(all_c) >= 5:
            all_result = fit_size_curve(all_c, TARGET_SF)
            if all_result:
                t1_ppsfs = [c['ppsf'] for c in t1] if t1 else []
                t2_ppsfs = [c['ppsf'] for c in t2] if t2 else []
                if len(t1_ppsfs) >= 2 and len(t2_ppsfs) >= 2:
                    premium = sorted(t1_ppsfs)[len(t1_ppsfs) // 2] - sorted(t2_ppsfs)[len(t2_ppsfs) // 2]
                else:
                    premium = DEFAULT_PREM
                cluster['t1psf'] = all_result['ppsf_at_target'] + round(premium / 2)
                cluster['t2psf'] = all_result['ppsf_at_target'] - round(premium / 2)
                cluster['t1price'] = round(cluster['t1psf'] * TARGET_SF)
                cluster['t2price'] = round(cluster['t2psf'] * TARGET_SF)
                cluster['t1fb'] = 1

        # Fallback 3: tier medians
        if 't1psf' not in cluster:
            all_ppsfs = [c['ppsf'] for c in all_c]
            if all_ppsfs:
                median_all = sorted(all_ppsfs)[len(all_ppsfs) // 2]
                cluster['t1psf'] = round(median_all * 1.1)
                cluster['t2psf'] = round(median_all * 0.9)
                cluster['t1price'] = round(cluster['t1psf'] * TARGET_SF)
                cluster['t2price'] = round(cluster['t2psf'] * TARGET_SF)
                cluster['t1fb'] = 3
            else:
                continue

        # Derived: remodel premium
        if 't1psf' in cluster and 't2psf' in cluster:
            cluster['prem'] = cluster['t1psf'] - cluster['t2psf']

        # Confidence: average recency weight
        avg_rw = sum(c.get('rw', 0.5) for c in all_c) / len(all_c) if all_c else 0
        cluster['rw'] = round(avg_rw, 2)

        clusters.append(cluster)

    return clusters

src = market_file("redfin_sold.csv", market)
if not os.path.exists(src):
    print(f"  No {src} found. Run fetch_sold_comps.py first.")
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

            if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                skipped += 1
                continue

            price_str = re.sub(r"[^0-9.]", "", row.get("PRICE") or "0") or "0"
            price = float(price_str)
            sqft_str = re.sub(r"[^0-9.]", "", row.get("SQUARE FEET") or "0") or "0"
            sqft = float(sqft_str)

            if price <= 0 or sqft <= 0:
                skipped += 1
                continue

            # Require sold date — comps without dates can't be time-filtered
            sold_date = row.get("SOLD DATE", "").strip()
            if not sold_date:
                skip_no_date += 1
                continue

            ppsf = round(price / sqft)

            # Outlier filters
            if sqft < MIN_SQFT or price > MAX_PRICE or ppsf > MAX_PPSF:
                skip_outlier += 1
                continue

            year_built_str = row.get("YEAR BUILT", "").strip()
            year_built = int(year_built_str) if year_built_str.isdigit() else None
            if year_built and (year_built < MIN_YEAR_BUILT or year_built > CURRENT_YEAR):
                year_built = None  # Null out bogus years, keep the comp

            zipcode = str(row.get("ZIP OR POSTAL CODE", "")).strip()
            prop_type = row.get("PROPERTY TYPE", "").strip()
            zone = TYPE_TO_ZONE.get(prop_type, "")

            # Beds/baths
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

            pt = PT_MAP.get(prop_type, 0)

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
            if pt:
                rec["pt"] = pt
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

# Beds/baths coverage
with_beds = sum(1 for c in comps if "bd" in c)
with_baths = sum(1 for c in comps if "ba" in c)
print(f"  With beds: {with_beds:,} ({with_beds/len(comps)*100:.0f}%)")
print(f"  With baths: {with_baths:,} ({with_baths/len(comps)*100:.0f}%)")

# Zip coverage
zips = set(c["zip"] for c in comps if c["zip"])
print(f"  Unique zip codes: {len(zips)}")

# ── ARV Model: Tier Classification + Clustering ──
print(f"\n  ARV Model: Computing neighborhood medians...")
compute_neighborhood_medians(comps)

print(f"  ARV Model: Classifying condition tiers...")
for c in comps:
    c['t'] = classify_tier(c.get('yb'), c['ppsf'], c.get('_nbhd_median', c['ppsf']))
    c['rw'] = round(recency_weight(c.get('date', '')), 2)
    # Clean up internal field
    if '_nbhd_median' in c:
        del c['_nbhd_median']

t1_count = sum(1 for c in comps if c['t'] == 1)
t2_count = sum(1 for c in comps if c['t'] == 2)
print(f"  Tier 1 (New/Remodel): {t1_count:,} ({t1_count/len(comps)*100:.0f}%)")
print(f"  Tier 2 (Existing): {t2_count:,} ({t2_count/len(comps)*100:.0f}%)")

print(f"  ARV Model: Computing clusters + size curves...")
clusters = compute_clusters(comps)
t1_clusters = sum(1 for cl in clusters if 't1psf' in cl)
fb_counts = {}
for cl in clusters:
    fb = cl.get('t1fb', -1)
    fb_counts[fb] = fb_counts.get(fb, 0) + 1
print(f"  Clusters: {len(clusters)} total, {t1_clusters} with T1 pricing")
print(f"  Fallback levels: {fb_counts}")

# Sample validation: spot-check known ZIPs
CELL = ARV_CONFIG["cell_size"]
sample_zips = ['91367', '91316', '91356'] if market["slug"] == "la" else ['92129', '92127', '92130']
for z in sample_zips:
    z_comps = [c for c in comps if c['zip'] == z and c.get('t') == 1]
    if z_comps:
        ppsfs = sorted([c['ppsf'] for c in z_comps])
        median_ppsf = ppsfs[len(ppsfs) // 2]
        print(f"  ZIP {z}: T1 median raw $/SF = ${median_ppsf} (n={len(z_comps)})")

# Top/bottom T1 clusters for sanity check
sorted_clusters = sorted([cl for cl in clusters if 't1psf' in cl], key=lambda x: x['t1psf'], reverse=True)
if sorted_clusters:
    print(f"\n  Top 5 T1 clusters (highest $/SF at 1,750):")
    for cl in sorted_clusters[:5]:
        print(f"    {cl['id']}: ${cl['t1psf']}/SF (n={cl['n']}, t1={cl['t1n']}, fb={cl.get('t1fb','?')})")
    print(f"  Bottom 5 T1 clusters (lowest $/SF at 1,750):")
    for cl in sorted_clusters[-5:]:
        print(f"    {cl['id']}: ${cl['t1psf']}/SF (n={cl['n']}, t1={cl['t1n']}, fb={cl.get('t1fb','?')})")

# ── Write data.js ──
output_file = market_file("data.js", market)
js = "const LOADED_COMPS = " + json.dumps(comps, separators=(",", ":")) + ";\n"
js += "const CLUSTERS = " + json.dumps(clusters, separators=(",", ":")) + ";"
with open(output_file, "w") as f:
    f.write(js)

size_kb = len(js) / 1024
print(f"\n  Written: {output_file} ({size_kb:.0f} KB, {len(comps):,} comps, {len(clusters)} clusters)")
print(f"  Next: python3 listings_build.py")
print(f"  Then refresh http://localhost:8080\n")

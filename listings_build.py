#!/usr/bin/env python3
"""
listings_build.py
Processes a Redfin active-listings CSV export into listings.js for the GUI.

What it does:
  1. Reads the Redfin CSV
  2. Filters to LA County only (lat/lng bounding box)
  3. Pulls lot size from the CSV
  4. Computes hyperlocal PT-filtered exit $/SF (P75) from sold comps
     - P75 = 75th percentile (new townhomes compete with top quartile)
     - Spatial grid index for fast radius-based lookup
     - PT-filtered: SFR/Condo/Townhome only (exclude multi-family)
     - T1 (new/remodel) comps get 1.5x weight over T2 (existing)
     - Expanding radius search: 0.25mi → 0.5mi → 1mi
     - Falls back to zip-level if needed
  5. Assigns an approximate zone from Redfin property type
  6. Outputs a clean listings.js
"""
import csv, json, re, os, glob, statistics, time, math, sys
from datetime import datetime, timezone

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, TYPE_TO_ZONE, CLASSIFY_FNS


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

market = get_market()
LAT_MIN, LAT_MAX = market["lat_min"], market["lat_max"]
LNG_MIN, LNG_MAX = market["lng_min"], market["lng_max"]

# ── Weighted comp scoring model config ──
GRID_SIZE = 0.01          # ~0.7 miles per cell (for spatial index)
MIN_COMPS = 5             # Minimum scored comps for reliable output
DEG_PER_MILE = 1 / 69.0  # Approximate degrees latitude per mile
CURRENT_YEAR = datetime.now().year

# ── Product type weights (Tier 1–6) ──
TIER_1_WEIGHT = 1.00   # Townhouse, new (≤5yr)
TIER_2_WEIGHT = 0.85   # Townhouse, renovated (T1, >5yr)
TIER_3_WEIGHT = 0.75   # Condo/Co-op, new (≤5yr)
TIER_4_WEIGHT = 0.70   # Townhouse, older high-end (5–10yr, T1)
TIER_5_WEIGHT = 0.60   # Condo/Co-op, renovated (T1, >5yr)
TIER_6_WEIGHT = 0.50   # SFR, new (≤5yr), 1500–2200 SF ONLY
SFR_SQFT_MIN = 1500    # Hard gate: min SFR sqft to include
SFR_SQFT_MAX = 2200    # Hard gate: max SFR sqft to include

# ── Proximity weights (miles) ──
PROX_0_05  = 1.00   # 0–0.5 miles
PROX_05_10 = 0.80   # 0.5–1.0 miles
PROX_10_15 = 0.60   # 1.0–1.5 miles
PROX_15_20 = 0.40   # 1.5–2.0 miles
MAX_RADIUS_MI = 2.0  # Hard exclude beyond this
CASCADE_MAX_MI = 3.0 # Cascade can expand up to this

# ── Recency weights (months) ──
RECENCY_0_6   = 1.00
RECENCY_6_12  = 0.85
RECENCY_12_18 = 0.70
RECENCY_18_24 = 0.50
MAX_RECENCY_MONTHS = 24  # Hard exclude older

# ── New construction premium ──
# Comp pool is dominated by pre-2015 renovated stock (~87% T1-Reno in LA).
# New ground-up product trades ~20% above blended T1; we apply 10% conservatively.
NEW_CONSTRUCTION_PREMIUM = 1.10


# ── Step 1: Load comps and build spatial index ──
print("\n🏘️  Step 1: Loading comps + building spatial index...")
comps = []

comps_file = market_file("data.js", market)
if os.path.exists(comps_file):
    with open(comps_file, "r") as f:
        raw = f.read()
    match = re.search(r"LOADED_COMPS\s*=\s*(\[.*?\]);\s", raw, re.DOTALL)
    if match:
        comps = json.loads(match.group(1))
        print(f"   Loaded {len(comps):,} sold comps")
    else:
        print(f"   ⚠️  Could not parse {comps_file} — exit $/SF will be unavailable")
else:
    print(f"   ⚠️  {comps_file} not found — exit $/SF will be unavailable")

# ── Haversine distance (miles) ──
def haversine_mi(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles between two lat/lng points."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def proximity_weight(dist_mi):
    """Return proximity weight for a given distance in miles."""
    if dist_mi <= 0.5: return PROX_0_05
    if dist_mi <= 1.0: return PROX_05_10
    if dist_mi <= 1.5: return PROX_10_15
    if dist_mi <= 2.0: return PROX_15_20
    return 0  # excluded


def scored_recency_weight(sale_date_str):
    """Recency weight with hard 24-month exclude for the scoring model."""
    if not sale_date_str:
        return 0  # no date = exclude
    try:
        sale = datetime.strptime(sale_date_str, "%B-%d-%Y")
    except Exception:
        try:
            sale = datetime.strptime(sale_date_str, "%Y-%m-%d")
        except Exception:
            return 0  # unparseable = exclude
    months_ago = (datetime.now() - sale).days / 30.44
    if months_ago > MAX_RECENCY_MONTHS:
        return 0  # hard exclude
    if months_ago <= 6: return RECENCY_0_6
    if months_ago <= 12: return RECENCY_6_12
    if months_ago <= 18: return RECENCY_12_18
    return RECENCY_18_24


# PT code mapping: 1=SFR, 2=Condo, 3=Townhouse (from build_comps.py PT_MAP)
PT_SFR = 1
PT_CONDO = 2
PT_TOWNHOUSE = 3


def product_weight(pt, tier, yb, sqft):
    """Return (product_weight, tier_rank) or (0, -1) if excluded.
    pt: property type code (1=SFR, 2=Condo, 3=TH)
    tier: condition tier (1=T1 new/remodel, 2=T2 existing)
    yb: year built (int or None)
    sqft: building square footage
    """
    is_new = yb is not None and yb >= (CURRENT_YEAR - 5)
    is_t1 = tier == 1
    age = (CURRENT_YEAR - yb) if yb else 999

    if pt == PT_TOWNHOUSE:
        if is_new:
            return TIER_1_WEIGHT, 1
        if is_t1 and 5 < age <= 10:
            return TIER_4_WEIGHT, 4  # older high-end (5-10yr, T1)
        if is_t1:
            return TIER_2_WEIGHT, 2  # renovated (>10yr, T1)
        return 0, -1
    elif pt == PT_CONDO:
        if is_new:
            return TIER_3_WEIGHT, 3
        if is_t1:
            return TIER_5_WEIGHT, 5
        return 0, -1
    elif pt == PT_SFR:
        if is_new and SFR_SQFT_MIN <= sqft <= SFR_SQFT_MAX:
            return TIER_6_WEIGHT, 6
        return 0, -1
    return 0, -1  # unknown type


# Build spatial grid index for fast radius lookups
# Each comp entry: dict with all needed fields for scoring
comp_grid = {}  # (grid_row, grid_col) → [comp_dict, ...]
eligible_count = 0
pt_counts = {PT_SFR: 0, PT_CONDO: 0, PT_TOWNHOUSE: 0}
skipped_mf = 0
skipped_no_date = 0

for c in comps:
    clat = c.get("lat", 0)
    clng = c.get("lng", 0)
    cppsf = c.get("ppsf") or (round(c["price"] / c["sqft"]) if c.get("sqft", 0) > 0 else 0)
    csqft = c.get("sqft", 0)
    czip = c.get("zip", "")
    cpt = c.get("pt", 0)
    ctier = c.get("t", 2)
    cyb = c.get("yb")
    cdate = c.get("date", "")

    if cppsf <= 0 or clat == 0 or clng == 0:
        continue

    # Only SFR/Condo/TH
    if cpt not in (PT_SFR, PT_CONDO, PT_TOWNHOUSE):
        skipped_mf += 1
        continue

    # Pre-check: must have a parseable date within 24 months
    rw = scored_recency_weight(cdate)
    if rw == 0:
        skipped_no_date += 1
        continue

    # Pre-check: must have a product weight in at least the most permissive tier
    pw, tier_rank = product_weight(cpt, ctier, cyb, csqft)
    # We store ALL eligible comps (even those with pw=0 at strict tier)
    # because cascade may include lower tiers later.
    # But we do a soft check — if even Tier 6 wouldn't match, skip.
    # Actually, store all SFR/Condo/TH within 24 months — product_weight
    # will be re-evaluated per-listing during cascade.

    pt_counts[cpt] = pt_counts.get(cpt, 0) + 1

    grow = math.floor(clat / GRID_SIZE)
    gcol = math.floor(clng / GRID_SIZE)

    comp_entry = {
        "lat": clat, "lng": clng, "ppsf": cppsf, "sqft": csqft,
        "zip": czip, "pt": cpt, "t": ctier, "yb": cyb, "date": cdate,
        "rw": rw,
    }
    comp_grid.setdefault((grow, gcol), []).append(comp_entry)
    eligible_count += 1

print(f"   Spatial index: {len(comp_grid):,} grid cells")
print(f"     SFR (pt=1): {pt_counts.get(PT_SFR, 0):,}")
print(f"     Condo (pt=2): {pt_counts.get(PT_CONDO, 0):,}")
print(f"     Townhome (pt=3): {pt_counts.get(PT_TOWNHOUSE, 0):,}")
print(f"     Excluded MF (pt=4,5): {skipped_mf:,}")
print(f"     Excluded (no/stale date): {skipped_no_date:,}")
print(f"   Eligible comps indexed: {eligible_count:,}")


def iqr_trim(vals):
    """Remove outliers using IQR method (1.0x multiplier for tighter trim).
    vals: list of dicts with 'ppsf' key.
    Needs ≥5 comps to trim; otherwise returns original list."""
    if len(vals) < 5:
        return vals
    ppsfs = sorted(v["ppsf"] for v in vals)
    n = len(ppsfs)
    q1 = ppsfs[n // 4]
    q3 = ppsfs[(3 * n) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return vals
    lo = q1 - 1.0 * iqr
    hi = q3 + 1.0 * iqr
    trimmed = [v for v in vals if lo <= v["ppsf"] <= hi]
    if len(trimmed) < len(vals) * 0.6:
        return vals
    return trimmed if trimmed else vals


def rental_iqr_trim(vals):
    """Remove outliers from rental comps using IQR method (1.5x multiplier).
    vals: list of (rpsf, beds, sqft) tuples.
    Needs ≥4 comps to trim (lower threshold than sale comps — rental pools are thinner).
    1.5x multiplier (vs 1.0x for sale comps) — rental variance is naturally higher."""
    if len(vals) < 4:
        return vals
    ppsfs = sorted(v[0] for v in vals)
    n = len(ppsfs)
    q1 = ppsfs[n // 4]
    q3 = ppsfs[(3 * n) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return vals
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    trimmed = [v for v in vals if lo <= v[0] <= hi]
    # Don't trim too aggressively — keep at least 60% of comps
    if len(trimmed) < len(vals) * 0.6:
        return vals
    return trimmed if trimmed else vals


def collect_comps_in_radius(lat, lng, radius_mi):
    """Collect all comp entries from grid within radius_mi of (lat, lng)."""
    radius_deg = radius_mi * DEG_PER_MILE
    grow = math.floor(lat / GRID_SIZE)
    gcol = math.floor(lng / GRID_SIZE)
    cells = int(radius_deg / GRID_SIZE) + 1
    result = []
    for dr in range(-cells, cells + 1):
        for dc in range(-cells, cells + 1):
            for comp in comp_grid.get((grow + dr, gcol + dc), []):
                dist = haversine_mi(lat, lng, comp["lat"], comp["lng"])
                if dist <= radius_mi:
                    result.append((comp, dist))
    return result


def score_comps(lat, lng, zipcode, radius_mi, max_tier_rank=6):
    """Score comps within radius using the weighted model.
    Returns list of scored comp dicts (with composite_score, adjusted_psf, etc.)
    Only includes comps with product tier_rank <= max_tier_rank.
    """
    nearby = collect_comps_in_radius(lat, lng, radius_mi)
    scored = []
    for comp, dist in nearby:
        pw, tier_rank = product_weight(comp["pt"], comp["t"], comp["yb"], comp["sqft"])
        if pw == 0 or tier_rank > max_tier_rank:
            continue  # excluded by product filter

        prox_w = proximity_weight(dist)
        if prox_w == 0:
            continue  # beyond max radius

        rec_w = comp["rw"]  # pre-computed recency weight
        if rec_w == 0:
            continue  # too old

        composite = pw * prox_w * rec_w

        raw_ppsf = comp["ppsf"]
        adj_ppsf = raw_ppsf

        scored.append({
            **comp,
            "dist_mi": round(dist, 3),
            "product_wt": pw,
            "proximity_wt": prox_w,
            "recency_wt": rec_w,
            "composite_score": round(composite, 4),
            "adj_ppsf": adj_ppsf,
            "tier_rank": tier_rank,
        })
    return scored


def find_weighted_exit_ppsf(lat, lng, zipcode, debug=False):
    """Compute weighted exit $/SF using the composite scoring model.

    Cascade logic:
      1. Score comps at default max radius (2.0 mi), top tiers only
      2. If < 5 scored, expand radius by 0.5mi up to 3.0mi
      3. If still < 5, include next lower product tier
      4. If still < 5, flag low_comp_confidence
      5. If 0 comps, return null

    Returns: dict with exit_psf, comp_count, low_comp_confidence, sfr_comp_share, debug_info
    """
    result = {
        "exit_psf": None,
        "comp_count": 0,
        "low_comp_confidence": False,
        "sfr_comp_share": 0.0,
        "cascade_triggered": False,
        "cascade_step": None,
        "scored_comps": [],
    }

    # Start with default radius and all 6 tiers
    radius = MAX_RADIUS_MI
    max_tier = 6

    scored = score_comps(lat, lng, zipcode, radius, max_tier)

    if len(scored) >= MIN_COMPS:
        # Good pool at default radius
        pass
    else:
        result["cascade_triggered"] = True

        # Step 1: Expand radius in 0.5mi increments
        for r in [2.5, 3.0]:
            scored = score_comps(lat, lng, zipcode, r, max_tier)
            if len(scored) >= MIN_COMPS:
                result["cascade_step"] = f"radius_expand_{r}mi"
                break

        # Step 2: If still < 5, already including all tiers (max_tier=6)
        # Product tiers are already all included. Nothing more to add.

        if len(scored) < MIN_COMPS and len(scored) > 0:
            result["low_comp_confidence"] = True
            result["cascade_step"] = result["cascade_step"] or "low_comps"

    if not scored:
        return result

    # IQR trim outliers
    scored = iqr_trim(scored)

    # Compute weighted average
    total_weight = sum(c["composite_score"] for c in scored)
    if total_weight == 0:
        return result

    weighted_psf = sum(c["adj_ppsf"] * c["composite_score"] for c in scored) / total_weight

    # SFR comp share (by weight)
    sfr_weight = sum(c["composite_score"] for c in scored if c["pt"] == PT_SFR)
    sfr_share = sfr_weight / total_weight if total_weight > 0 else 0

    if len(scored) < MIN_COMPS:
        result["low_comp_confidence"] = True

    result["exit_psf"] = round(weighted_psf * NEW_CONSTRUCTION_PREMIUM)
    result["comp_count"] = len(scored)
    result["sfr_comp_share"] = round(sfr_share, 3)
    result["scored_comps"] = scored if debug else []

    return result


# ── Step 2: Find and read Redfin CSV ──
print("\n📄 Step 2: Reading Redfin listings CSV...")
merged_name = market_file("redfin_merged.csv", market)
redfin_csvs = glob.glob(merged_name) or glob.glob("redfin_*.csv")
if not redfin_csvs:
    print("   ❌ No redfin_*.csv found in this folder.")
    exit(1)

src = redfin_csvs[0]
print(f"   Found: {src}")

listings = []
skipped_location = 0
skipped_data = 0
total = 0

with open(src, encoding="utf-8", errors="replace") as f:
    reader = csv.DictReader(f)
    for row in reader:
        total += 1
        try:
            lat = float(row.get("LATITUDE") or 0)
            lng = float(row.get("LONGITUDE") or 0)

            # Filter to market bounding box
            if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                skipped_location += 1
                continue

            status = row.get("STATUS", "").strip()
            if status != "Active":
                continue

            price = float(re.sub(r"[^0-9.]", "", row.get("PRICE") or "0") or 0)
            sqft = float(re.sub(r"[^0-9.]", "", row.get("SQUARE FEET") or "0") or 0)
            lot_size = float(re.sub(r"[^0-9.]", "", row.get("LOT SIZE") or "0") or 0)
            prop_type = row.get("PROPERTY TYPE", "").strip()
            zone = TYPE_TO_ZONE.get(prop_type, "")

            if price <= 0:
                skipped_data += 1
                continue

            # sqft=0 is OK — MLS sometimes omits building SF for multi-family
            ppsf = round(price / sqft) if sqft > 0 else 0
            zipcode = str(row.get("ZIP OR POSTAL CODE", "")).strip()
            neighborhood = row.get("LOCATION", "").strip()

            address_parts = [
                row.get("ADDRESS", "").strip(),
                row.get("CITY", "").strip(),
                zipcode,
            ]
            address = ", ".join(p for p in address_parts if p)

            beds = row.get("BEDS", "").strip()
            baths = row.get("BATHS", "").strip()
            year_built = row.get("YEAR BUILT", "").strip()
            dom = row.get("DAYS ON MARKET", "").strip()
            hoa_str = re.sub(r"[^0-9.]", "", row.get("HOA/MONTH") or "0") or "0"
            hoa = float(hoa_str)
            url = row.get("URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis FOR INFO ON PRICING)", "").strip()

            city = row.get("CITY", "").strip()

            listings.append({
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "price": int(price),
                "sqft": int(sqft),
                "lotSf": int(lot_size) if lot_size > 0 else None,
                "ppsf": ppsf,
                "zone": zone,
                "track": "SF" if zone in ("R1", "LAND") else "MF",  # SF=single-family, MF=multifamily
                "neighborhood": neighborhood,
                "zip": zipcode,
                "city": city,
                "address": address,
                "type": prop_type,
                "beds": beds,
                "baths": baths,
                "yearBuilt": year_built,
                "dom": int(dom) if dom.isdigit() else None,
                "hoa": int(hoa) if hoa > 0 else None,
                "url": url,
                "hasStructure": True if (sqft > 0 and prop_type != "Vacant Land") else False,
            })
        except Exception as e:
            skipped_data += 1
            continue

print(f"   Total rows: {total}")
print(f"   ✅ {market['name']} listings: {len(listings)}")
print(f"   ⚠️  Outside {market['name']}: {skipped_location}")
print(f"   ⚠️  Bad/missing data: {skipped_data}")

if len(listings) == 0:
    print("\n❌ No listings matched. Check the CSV.")
    exit(1)

# ── Step 2.5: Stamp parcel data from parcels.json ──
PARCEL_FILE = market_file("parcels.json", market)
parcel_stamped = 0
parcel_fire_count = 0
if os.path.exists(PARCEL_FILE):
    print(f"\n📦 Step 2.5: Stamping parcel data from {PARCEL_FILE}...")
    with open(PARCEL_FILE) as f:
        parcel_data = json.load(f)
    print(f"   Loaded {len(parcel_data):,} parcel records")

    lot_source_counts = {"mls": 0, "parcel": 0, "none": 0}
    lot_mismatches = []  # (address, redfin_lot, parcel_lot, ratio)

    for l in listings:
        key = f"{l['lat']},{l['lng']}"
        if key in parcel_data:
            p = parcel_data[key]
            # Lot size priority: MLS (Redfin) is PRIMARY, parcel is FALLBACK
            # Redfin lot size comes from listing agent / MLS — most reliable
            # Parcel data from ArcGIS spatial lookup can match wrong parcel
            # (geocoding offset on cul-de-sacs, irregular lots, etc.)
            redfin_lot = l.get("lotSf") or 0
            parcel_lot = p.get("lotSf") or 0

            if redfin_lot > 0:
                l["lotSf"] = redfin_lot
                l["lotSource"] = "mls"
                lot_source_counts["mls"] += 1
                # Log mismatch if parcel differs by >50%
                if parcel_lot > 0 and abs(parcel_lot - redfin_lot) / redfin_lot > 0.5:
                    ratio = parcel_lot / redfin_lot
                    l["lotSource"] = "mls"
                    l["lotSfParcel"] = parcel_lot
                    lot_mismatches.append((l.get("address", "?"), redfin_lot, parcel_lot, ratio))
            elif parcel_lot > 0:
                l["lotSf"] = parcel_lot
                l["lotSource"] = "parcel"
                lot_source_counts["parcel"] += 1
            else:
                l["lotSource"] = "none"
                lot_source_counts["none"] += 1
            parcel_stamped += 1
            # Use ArcGIS situs address as FALLBACK only when Redfin address is missing
            # Redfin MLS address is primary (listing agent sourced, matches the listing URL)
            # ArcGIS situs can differ on corner lots (e.g. commercial vs residential frontage)
            redfin_addr = l.get("address", "").split(",")[0].strip()
            if not redfin_addr and p.get("situsAddress"):
                situs = p["situsAddress"].strip()
                if situs:
                    addr_parts = [situs, l.get("city", ""), l.get("zip", "")]
                    l["address"] = ", ".join(p for p in addr_parts if p)
            # Fire zone from ArcGIS
            if "fireZone" in p:
                l["fireZone"] = p["fireZone"]
                if p["fireZone"]:
                    parcel_fire_count += 1
            # Lot dimensions from parcel polygon geometry
            if p.get("lotWidth"):
                l["lw"] = p["lotWidth"]
                # Depth = lotSf / width (effective rectangular depth)
                final_lot = l.get("lotSf") or p.get("lotSf")
                if final_lot and final_lot > 0:
                    l["ld"] = round(final_lot / p["lotWidth"])
                elif p.get("lotDepth"):
                    l["ld"] = p["lotDepth"]
            if p.get("lotShape"):
                l["lotShape"] = p["lotShape"]
            # Assessor data for popup display
            if p.get("existingUnits"):
                l["existingUnits"] = p["existingUnits"]
            if p.get("ain"):
                l["ain"] = p["ain"]
            if p.get("landValue") is not None:
                l["assessedLandValue"] = p["landValue"]
            if p.get("impValue") is not None:
                l["assessedImpValue"] = p["impValue"]
        else:
            # No parcel data — keep Redfin MLS lot size
            if l.get("lotSf"):
                l["lotSource"] = "mls"
                lot_source_counts["mls"] += 1
            else:
                l["lotSource"] = "none"
                lot_source_counts["none"] += 1

    print(f"   Parcel records matched: {parcel_stamped:,}/{len(listings):,}")
    print(f"   Fire zone (VHFHSZ): {parcel_fire_count:,}")
    print(f"\n   Lot Size Sources:")
    total_l = len(listings)
    for src, cnt in lot_source_counts.items():
        pct = cnt / total_l * 100 if total_l else 0
        label = {"mls": "MLS (Redfin)", "parcel": "Parcel (fallback)", "none": "None"}.get(src, src)
        print(f"     {label}: {cnt:,} ({pct:.1f}%)")
    # Listings without parcel data keep MLS lot or None
    no_parcel = total_l - parcel_stamped
    mls_only = sum(1 for l in listings if l.get("lotSource") != "mls" and l.get("lotSource") != "parcel" and l.get("lotSource") != "none" and l.get("lotSf"))
    no_parcel_with_lot = sum(1 for l in listings if f"{l['lat']},{l['lng']}" not in parcel_data and l.get("lotSf"))
    if no_parcel > 0:
        print(f"     No parcel match (MLS kept): {no_parcel_with_lot:,}")
    print(f"     Mismatches (>50%): {len(lot_mismatches):,}")
    if lot_mismatches:
        # Print top 10 biggest mismatches by ratio
        lot_mismatches.sort(key=lambda x: x[3], reverse=True)
        print(f"\n   Top {min(10, len(lot_mismatches))} lot size mismatches (MLS vs Parcel):")
        for addr, mls, parcel, ratio in lot_mismatches[:10]:
            print(f"     {addr}: MLS={mls:,} vs Parcel={parcel:,} ({ratio:.1f}x)")
    with_dims = sum(1 for l in listings if l.get("lw"))
    print(f"\n   With lot dimensions: {with_dims:,}/{len(listings):,}")
else:
    print(f"\n⚠️  {PARCEL_FILE} not found — run: python3 fetch_parcels.py")
    # Tag all listings with lotSource even without parcel data
    for l in listings:
        if l.get("lotSf"):
            l["lotSource"] = "mls"
        else:
            l["lotSource"] = "none"

# ── Step 2.6: Stamp ZIMAS real zoning from zoning.json ──
ZONING_FILE = market_file("zoning.json", market)
zimas_stamped = 0
zimas_upgraded = 0
zimas_downgraded = 0
if os.path.exists(ZONING_FILE):
    print(f"\n🏛️  Step 2.6: Stamping ZIMAS real zoning from {ZONING_FILE}...")
    with open(ZONING_FILE) as f:
        zoning_data = json.load(f)
    print(f"   Loaded {len(zoning_data):,} zoning records")

    # Build classify function list for this market (for reclassification)
    _classify_fns = [CLASSIFY_FNS[ep["classify_fn"]]
                     for ep in market.get("zoning_endpoints", [])
                     if ep.get("classify_fn") in CLASSIFY_FNS]

    mu_reclassified = 0
    for l in listings:
        key = f"{l['lat']},{l['lng']}"
        if key in zoning_data:
            z = zoning_data[key]
            sb_zone = z.get("sb1123")
            raw_code = z.get("zoning")

            # Re-run classify functions to pick up MU reclassification
            # (cached sb1123 values may have stale R4 for commercial/MU zones)
            # Try all functions — if ANY returns MU for this raw code, use MU
            if sb_zone and raw_code and sb_zone != "MU":
                for fn in _classify_fns:
                    new_zone = fn(raw_code)
                    if new_zone == "MU":
                        mu_reclassified += 1
                        sb_zone = "MU"
                        break

            if sb_zone:
                l["zimasZone"] = raw_code       # Raw ZIMAS code (e.g. "R2-1")
                l["zimasCategory"] = z.get("category")  # Descriptive category
                old_zone = l["zone"]
                if old_zone != sb_zone:
                    if sb_zone in ("R2", "R3", "R4", "MU") and old_zone in ("R1", "LAND"):
                        zimas_upgraded += 1
                    elif old_zone in ("R2", "R3", "R4", "MU") and sb_zone in ("R1", "LAND"):
                        zimas_downgraded += 1
                l["zone"] = sb_zone  # Override Redfin guess with ZIMAS truth
                # Add track indicator (SF = single-family, MF = multifamily)
                l["track"] = "SF" if sb_zone in ("R1", "LAND") else "MF"
                zimas_stamped += 1

    print(f"   ZIMAS zoning stamped: {zimas_stamped:,}/{len(listings):,}")
    print(f"   MU reclassified (was R4): {mu_reclassified:,}")
    print(f"   Zone upgrades (R1/LAND→R2+): {zimas_upgraded:,} (more units allowed!)")
    print(f"   Zone downgrades (R2+→R1/LAND): {zimas_downgraded:,}")
else:
    print(f"\n⚠️  {ZONING_FILE} not found — run: python3 fetch_zoning.py")

# ── Step 2.7: Stamp urban area status from urban.json ──
URBAN_FILE = market_file("urban.json", market)
if os.path.exists(URBAN_FILE):
    print(f"\n🏙️  Step 2.7: Stamping urban area status from {URBAN_FILE}...")
    with open(URBAN_FILE) as f:
        urban_data = json.load(f)
    print(f"   Loaded {len(urban_data):,} urban area records")

    urban_stamped = 0
    urban_true = 0
    urban_false = 0
    for l in listings:
        key = f"{l['lat']},{l['lng']}"
        if key in urban_data:
            l["urbanArea"] = urban_data[key]
            urban_stamped += 1
            if urban_data[key]:
                urban_true += 1
            else:
                urban_false += 1

    print(f"   Stamped: {urban_stamped:,}/{len(listings):,}")
    print(f"   In urban area: {urban_true:,} | Not urban: {urban_false:,}")
else:
    print(f"\n⚠️  {URBAN_FILE} not found — run: python3 fetch_urban.py")

# ── Step 2.8: Tenant risk + RSO + Remainder parcel assessment ──
print("\n🏠 Step 2.8: Assessing tenant risk, RSO, and remainder parcels...")
tenant_risk_counts = {0: 0, 1: 0, 2: 0, 3: 0}
rso_count = 0
remainder_count = 0

for l in listings:
    risk_score = 0
    risk_factors = []

    beds_str = l.get("beds", "")
    beds_int = int(beds_str) if beds_str and str(beds_str).isdigit() else 0
    yb_str = l.get("yearBuilt", "")
    yb_int = int(yb_str) if yb_str and str(yb_str).isdigit() else 0
    is_sf = l.get("track") == "SF"  # R1/LAND = single-family (likely owner-occupied)
    has_structure = l.get("hasStructure", False)
    existing_units = l.get("existingUnits", 0) or 0
    imp_val_check = l.get("assessedImpValue", 0) or 0
    prop_type_mf = "multi-family" in (l.get("type") or "").lower()

    # A MF property is "likely tenant-occupied" if any signal of existing occupancy is present,
    # even if Redfin labels it "Vacant Land" (e.g., listed as land but has assessed improvements).
    if not is_sf:
        likely_tenant_occupied = (
            existing_units >= 2
            or imp_val_check > 200000
            or prop_type_mf
            or (has_structure and l.get("track") == "MF")
        )
    else:
        likely_tenant_occupied = False
    l["likelyTenantOccupied"] = likely_tenant_occupied

    if not likely_tenant_occupied and not has_structure and is_sf:
        # Vacant land / R1 with no signals = no tenant risk
        l["tenantRisk"] = 0
        l["tenantRiskFactors"] = []
        l["rsoRisk"] = False
        tenant_risk_counts[0] += 1
        continue

    if is_sf:
        # R1/LAND SFR: owner-occupied is the norm, tenant risk is low
        # Only flag if 5+ beds (likely converted to rental units)
        if not has_structure:
            l["tenantRisk"] = 0
            l["tenantRiskFactors"] = []
            l["rsoRisk"] = False
            tenant_risk_counts[0] += 1
            continue
        if beds_int >= 5:
            risk_score += 2
            risk_factors.append("5+beds")
    else:
        # MF (R2-R4): likely tenanted if likelyTenantOccupied
        # Factor 1: Multi-family zone with occupancy signal
        if likely_tenant_occupied:
            risk_score += 1
            risk_factors.append("MF+struct")

        # Factor 2: Improvement value confirms occupied
        if imp_val_check > 50000:
            risk_score += 1
            risk_factors.append("improved")

        # Factor 3: Bedroom count signals more units
        if beds_int >= 5:
            risk_score += 1
            risk_factors.append("5+beds")
        elif beds_int >= 3:
            risk_score += 1
            risk_factors.append("3+beds")

        # Factor 4: Pre-2000 = long-term tenants more likely
        if yb_int > 0 and yb_int < 2000:
            risk_score += 1
            risk_factors.append("pre-2000")

    # RSO/Ellis Act assessment (market-specific)
    if market.get("has_rso") and (has_structure or likely_tenant_occupied):
        is_pre_1978 = yb_int > 0 and yb_int < 1979
        is_la_city = (l.get("city") or "").lower() in market.get("rso_eligible_cities", [])
        is_multi = l.get("track") == "MF" or beds_int >= 3
        if is_pre_1978 and is_la_city and is_multi:
            l["rsoRisk"] = True
            l["rsoFactors"] = []
            if is_pre_1978:
                l["rsoFactors"].append(f"built {yb_int}")
            if is_multi:
                l["rsoFactors"].append("multi-unit")
            risk_score += 1
            risk_factors.append("RSO")
            rso_count += 1
        else:
            l["rsoRisk"] = False
    else:
        l["rsoRisk"] = False

    # Cap at 3 (high)
    risk_level = min(risk_score, 3)
    l["tenantRisk"] = risk_level
    l["tenantRiskFactors"] = risk_factors
    tenant_risk_counts[risk_level] += 1


    # Remainder parcel analysis (R2-R4 with structure)
    # Strategy: keep existing building as remainder parcel, develop rest
    # SB 1123 explicitly allows this — existing uses retained, new units on remainder
    if l.get("track") == "MF" and (has_structure or likely_tenant_occupied) and l.get("lotSf"):
        sqft = l.get("sqft", 0) or 0
        lot_sf = l["lotSf"]
        est_stories = 1 if sqft < 1500 else 2
        est_footprint = sqft / est_stories if sqft > 0 else 0
        # Driveway: 20' wide x ~100' depth for access to rear buildable area
        driveway_sf = 2000
        available_sf = max(0, lot_sf - est_footprint - driveway_sf)
        # Need ~1,200 SF per townhome unit (footprint + setbacks)
        remainder_units = min(10, int(available_sf / 1200)) if available_sf >= 1200 else 0
        # Viable = at least 4 units feasible (enough to justify development)
        remainder_viable = available_sf >= 6000 and remainder_units >= 4
        l["remainderSf"] = round(available_sf)
        l["remainderUnits"] = remainder_units
        l["remainderViable"] = remainder_viable
        l["estFootprint"] = round(est_footprint)
        l["drivewayDeduction"] = driveway_sf
        if remainder_units > 0:
            remainder_count += 1

print(f"   Tenant risk — None: {tenant_risk_counts[0]:,} | Low: {tenant_risk_counts[1]:,} | Med: {tenant_risk_counts[2]:,} | High: {tenant_risk_counts[3]:,}")
print(f"   RSO risk (LA only): {rso_count:,}")
print(f"   Remainder parcels (R2-R4 viable): {remainder_count:,}")

# ── Fuzzy key lookup for cache files (openspace, slopes, elevation) ──
# Coordinates can drift slightly between CSV refreshes (rounding).
# Build a grid index for O(1) fuzzy matching within 0.0005° (~55m).
FUZZY_CELL = 0.001  # Grid cell size for fuzzy lookup
FUZZY_TOL = 0.0005  # Max distance for fuzzy match (~55m)

def build_fuzzy_index(cache_dict):
    """Index cache keys by coarse grid cell for fast fuzzy lookup."""
    idx = {}
    for key in cache_dict:
        parts = key.split(",")
        lat, lng = float(parts[0]), float(parts[1])
        cell = (round(lat / FUZZY_CELL), round(lng / FUZZY_CELL))
        idx.setdefault(cell, []).append((lat, lng, key))
    return idx

def fuzzy_lookup(lat, lng, cache_dict, idx):
    """Exact match first, then fuzzy match within tolerance."""
    exact = f"{lat},{lng}"
    if exact in cache_dict:
        return exact
    cell = (round(lat / FUZZY_CELL), round(lng / FUZZY_CELL))
    best_key, best_dist = None, FUZZY_TOL + 1
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            for clat, clng, ckey in idx.get((cell[0] + dr, cell[1] + dc), []):
                d = abs(clat - lat) + abs(clng - lng)
                if d < best_dist:
                    best_dist = d
                    best_key = ckey
    return best_key if best_dist <= FUZZY_TOL else None

# ── Step 2.9: Stamp protected area status from openspace.json ──
OPENSPACE_FILE = market_file("openspace.json", market)
if os.path.exists(OPENSPACE_FILE):
    print(f"\n🌲 Step 2.9: Stamping protected area status from {OPENSPACE_FILE}...")
    with open(OPENSPACE_FILE) as f:
        openspace_data = json.load(f)
    print(f"   Loaded {len(openspace_data):,} openspace records")

    openspace_idx = build_fuzzy_index(openspace_data)
    os_stamped = 0
    os_protected = 0
    for l in listings:
        matched_key = fuzzy_lookup(l["lat"], l["lng"], openspace_data, openspace_idx)
        if matched_key is not None:
            os_stamped += 1
            val = openspace_data[matched_key]
            if val:  # dict = inside protected area
                l["openSpace"] = val["name"]
                l["openSpaceAgency"] = val.get("agency", "")
                os_protected += 1

    print(f"   Stamped: {os_stamped:,}/{len(listings):,}")
    print(f"   In protected area: {os_protected:,}")
    if os_protected:
        # List which protected areas
        names = {}
        for l in listings:
            if l.get("openSpace"):
                names[l["openSpace"]] = names.get(l["openSpace"], 0) + 1
        for name, cnt in sorted(names.items(), key=lambda x: -x[1]):
            print(f"     {name}: {cnt} listing(s)")
else:
    print(f"\n⚠️  {OPENSPACE_FILE} not found — run: python3 fetch_openspace.py")

# ── Step 3: Fire zone check (fallback for listings not stamped from parcels.json) ──
FIRE_ZONE_FILE = market_file("fire_zones_vhfhsz.geojson", market)
already_stamped_fire = sum(1 for l in listings if "fireZone" in l)
need_fire_check = [l for l in listings if "fireZone" not in l]

if need_fire_check and os.path.exists(FIRE_ZONE_FILE):
    print(f"\n🔥 Step 3: Checking VHFHSZ fire zones (fallback for {len(need_fire_check):,} unstamped)...")
    t0 = time.time()

    with open(FIRE_ZONE_FILE) as f:
        fz_data = json.load(f)

    # Ray-casting point-in-polygon
    def point_in_ring(px, py, ring):
        n = len(ring)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def point_in_polygon(px, py, coords):
        # Outer ring must contain point
        if not point_in_ring(px, py, coords[0]):
            return False
        # Holes must not contain point
        for hole in coords[1:]:
            if point_in_ring(px, py, hole):
                return False
        return True

    # Build list of all polygon coordinate arrays
    all_polys = []
    for feat in fz_data["features"]:
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            all_polys.append(geom["coordinates"])
        elif geom["type"] == "MultiPolygon":
            all_polys.extend(geom["coordinates"])

    print(f"   Loaded {len(all_polys)} VHFHSZ polygons")

    # Pre-compute bounding boxes for each polygon for fast rejection
    poly_bounds = []
    for coords in all_polys:
        ring = coords[0]
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        poly_bounds.append((min(xs), max(xs), min(ys), max(ys)))

    fire_count = 0
    for l in need_fire_check:
        lng, lat = l["lng"], l["lat"]
        in_fire = False
        for i, coords in enumerate(all_polys):
            bx0, bx1, by0, by1 = poly_bounds[i]
            if lng < bx0 or lng > bx1 or lat < by0 or lat > by1:
                continue
            if point_in_polygon(lng, lat, coords):
                in_fire = True
                break
        if in_fire:
            l["fireZone"] = True
            fire_count += 1

    elapsed = time.time() - t0
    print(f"   In VHFHSZ (fallback): {fire_count:,} / {len(need_fire_check):,} ({elapsed:.1f}s)")
elif need_fire_check:
    print(f"\n⚠️  {FIRE_ZONE_FILE} not found and {len(need_fire_check):,} listings lack fire zone data")
else:
    print(f"\n✅ Step 3: All {len(listings):,} listings already have fire zone data from parcels.json")

# ── Step 3b: Market-specific burn zone flagging ──
def point_in_polygon_simple(px, py, polygon):
    """Ray-casting point-in-polygon test. polygon = list of (x, y) tuples."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

burn_zones = market.get("burn_zones", [])
if burn_zones:
    print(f"\n🔥 Step 3b: Flagging burn zones ({len(burn_zones)} zones)...")
    burn_counts = {}
    for l in listings:
        lng, lat = l["lng"], l["lat"]
        for bz in burn_zones:
            if point_in_polygon_simple(lng, lat, bz["polygon"]):
                l["burnZone"] = bz["name"]
                burn_counts[bz["name"]] = burn_counts.get(bz["name"], 0) + 1
                break
    for name, count in burn_counts.items():
        print(f"   {name} burn zone: {count} listings")
    if not burn_counts:
        print("   No listings in burn zones")
else:
    print(f"\n✅ Step 3b: No burn zones configured for {market['name']}")

# ── Step 4: Weighted exit $/SF scoring model ──
if comps:
    print(f"\n📍 Step 4: Computing weighted exit $/SF (composite scoring model)...")
    t0 = time.time()
    count_with_exit = 0
    count_low_conf = 0
    count_null = 0
    count_cascade = 0
    comp_count_sum = 0

    for i, l in enumerate(listings):
        result = find_weighted_exit_ppsf(l["lat"], l["lng"], l["zip"])
        l["exitPsf"] = result["exit_psf"]
        l["compCount"] = result["comp_count"]
        l["lowCompConfidence"] = result["low_comp_confidence"]
        l["sfrCompShare"] = result["sfr_comp_share"]

        # Keep legacy fields for backward compat (newconPpsf shown as reference)
        l["hoodPpsf"] = result["exit_psf"]  # alias for any legacy readers
        l["newconPpsf"] = None  # no longer computed separately
        l["newconCount"] = 0
        l["newconTier"] = None
        l["newconFlag"] = None
        l["compMethod"] = "scored"
        l["compRadius"] = 0  # not used in new model

        if result["exit_psf"]:
            count_with_exit += 1
            comp_count_sum += result["comp_count"]
        else:
            count_null += 1
        if result["low_comp_confidence"]:
            count_low_conf += 1
        if result["cascade_triggered"]:
            count_cascade += 1

        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            print(f"   {i+1:,}/{len(listings):,} ({elapsed:.1f}s)")

    elapsed = time.time() - t0
    avg_comps = (comp_count_sum / count_with_exit) if count_with_exit else 0
    sfr_heavy = sum(1 for l in listings if (l.get("sfrCompShare") or 0) > 0.30)

    print(f"   Done in {elapsed:.1f}s")
    print(f"   With exit $/SF: {count_with_exit:,}/{len(listings):,}")
    print(f"   Null exit (no comps): {count_null:,}")
    print(f"   Low confidence: {count_low_conf:,}")
    print(f"   Cascade triggered: {count_cascade:,}")
    print(f"   SFR-heavy (>30%): {sfr_heavy:,}")
    if count_with_exit:
        print(f"   Avg comps per listing: {avg_comps:.1f}")
else:
    print(f"\n⚠️  No comps loaded — skipping exit $/SF computation")
    for l in listings:
        l["exitPsf"] = None
        l["compCount"] = 0
        l["lowCompConfidence"] = False
        l["sfrCompShare"] = 0
        l["hoodPpsf"] = None
        l["newconPpsf"] = None
        l["newconCount"] = 0
        l["newconTier"] = None
        l["newconFlag"] = None
        l["compMethod"] = "none"
        l["compRadius"] = 0

# ── Step 4b2: Subdivision comp exit $/SF (Tier 0 — highest priority) ──
SUBDIV_FILE = market_file("subdiv_comps.json", market)
SUBDIV_GRID_SIZE = 0.01  # Same grid size as sale comp index
SUBDIV_RADII = [0.007, 0.015, 0.029]  # 0.5mi, 1mi, 2mi
SUBDIV_MIN_COMPS = 3

subdiv_grid = {}   # { (row, col): [comp, ...] }
subdiv_count = 0

if os.path.exists(SUBDIV_FILE):
    print(f"\n🏘️  Step 4b2: Loading subdivision comps from {SUBDIV_FILE}...")
    with open(SUBDIV_FILE) as f:
        subdiv_comps_raw = json.load(f)
    print(f"   Loaded {len(subdiv_comps_raw):,} subdivision comps")

    for sc in subdiv_comps_raw:
        slat = sc.get("lat", 0)
        slng = sc.get("lng", 0)
        adj_ppsf = sc.get("adj_ppsf", 0)
        if adj_ppsf <= 0 or slat == 0 or slng == 0:
            continue

        grow = math.floor(slat / SUBDIV_GRID_SIZE)
        gcol = math.floor(slng / SUBDIV_GRID_SIZE)

        subdiv_grid.setdefault((grow, gcol), []).append(sc)
        subdiv_count += 1

    print(f"   Indexed: {subdiv_count:,} comps in {len(subdiv_grid):,} grid cells")

    def find_subdiv_exit_ppsf(lat, lng):
        """Find P75 of appreciation-adjusted subdivision comp $/SF."""
        grow = math.floor(lat / SUBDIV_GRID_SIZE)
        gcol = math.floor(lng / SUBDIV_GRID_SIZE)

        def p75(vals):
            vals.sort()
            return round(vals[int(len(vals) * 0.75)])

        def collect(grid, radius):
            cells = int(radius / SUBDIV_GRID_SIZE) + 1
            result = []
            for dr in range(-cells, cells + 1):
                for dc in range(-cells, cells + 1):
                    for sc in grid.get((grow + dr, gcol + dc), []):
                        if abs(sc["lat"] - lat) <= radius and abs(sc["lng"] - lng) <= radius:
                            result.append(sc)
            return result

        for radius in SUBDIV_RADII:
            comps = collect(subdiv_grid, radius)
            if len(comps) >= SUBDIV_MIN_COMPS:
                adj_vals = [c["adj_ppsf"] for c in comps]
                avg_appr = round(sum(c.get("appr_pct", 0) for c in comps) / len(comps), 1)
                avg_cluster = round(sum(c.get("cluster_size", 1) for c in comps) / len(comps), 1)
                miles = round(radius * 69, 2)
                return p75(adj_vals), len(comps), miles, avg_appr, avg_cluster

        return None, 0, 0, 0, 0

    # Compute subdiv stats for diagnostics (no longer stamped onto listings)
    subdiv_found = 0
    subdiv_vals = []
    for l in listings:
        val, count, radius_mi, avg_appr, avg_cluster = find_subdiv_exit_ppsf(
            l["lat"], l["lng"]
        )
        if val:
            subdiv_vals.append(val)
            subdiv_found += 1

    print(f"   Subdiv pricing (diagnostic only): {subdiv_found:,}/{len(listings):,} listings ({subdiv_found/len(listings)*100:.1f}%)")
    if subdiv_found:
        subdiv_vals.sort()
        print(f"   Subdiv $/SF: median ${subdiv_vals[len(subdiv_vals)//2]:,}")
else:
    print(f"\n⚠️  {SUBDIV_FILE} not found — run: python3 build_subdiv_comps.py")

# ── Step 4c: Stamp HUD Fair Market Rents from rents.json ──
RENTS_FILE = market_file("rents.json", market)
if os.path.exists(RENTS_FILE):
    print(f"\n🏠 Step 4c: Stamping HUD Fair Market Rents from {RENTS_FILE}...")
    with open(RENTS_FILE) as f:
        rent_data = json.load(f)
    print(f"   Loaded {len(rent_data):,} zip-level rent records")

    rent_stamped = 0
    est_rents = []
    for l in listings:
        zipcode = str(l.get("zip", "")).strip()
        if zipcode in rent_data:
            r = rent_data[zipcode]
            l["fmr3br"] = r.get("fmr3br")
            l["fmr4br"] = r.get("fmr4br")
            # New-construction premium: 1.25x HUD FMR for modern townhomes
            if l["fmr3br"]:
                l["estRentMonth"] = round(l["fmr3br"] * 1.25)
                est_rents.append(l["estRentMonth"])
                rent_stamped += 1
        else:
            l["fmr3br"] = None
            l["fmr4br"] = None
            l["estRentMonth"] = None

    print(f"   Rent data stamped: {rent_stamped:,}/{len(listings):,}")
    if est_rents:
        est_rents.sort()
        med = est_rents[len(est_rents)//2]
        print(f"   Est. Rent/Month (FMR×1.25): Median ${med:,} | Min ${min(est_rents):,} | Max ${max(est_rents):,}")
else:
    print(f"\n⚠️  {RENTS_FILE} not found — run: python3 fetch_rents.py")
    for l in listings:
        l["fmr3br"] = None
        l["fmr4br"] = None
        l["estRentMonth"] = None

# ── Step 4d: Spatial rental comp pipeline ──
# 4d-a: Load rental comps CSV into spatial grid
RENTAL_COMPS_FILE = market_file("rental_comps.csv", market)
rental_grid = {}  # { (row, col): [(lat, lng, rent, beds, sqft, prop_type), ...] }
RENTAL_GRID_SIZE = 0.01  # ~0.7 mi cells, matches sale comp grid

RENTAL_MAX_AGE_DAYS = 150  # Drop rental listings older than 5 months
rental_comp_count = 0
rental_stale_skipped = 0
if os.path.exists(RENTAL_COMPS_FILE):
    print(f"\n🏠 Step 4d: Loading rental comps from {RENTAL_COMPS_FILE}...")
    from datetime import datetime, timezone
    _now = datetime.now(timezone.utc)
    with open(RENTAL_COMPS_FILE, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Freshness filter — drop stale listings
                freshness_ts = row.get("FRESHNESS TIMESTAMP", "").strip()
                if freshness_ts:
                    try:
                        dt = datetime.fromisoformat(freshness_ts.replace("Z", "+00:00"))
                        if (_now - dt).days > RENTAL_MAX_AGE_DAYS:
                            rental_stale_skipped += 1
                            continue
                    except Exception:
                        pass

                rent = float(re.sub(r"[^0-9.]", "", row.get("PRICE") or "0") or 0)
                clat = float(row.get("LATITUDE") or 0)
                clng = float(row.get("LONGITUDE") or 0)
                if rent < 500 or rent > 20000 or clat == 0 or clng == 0:
                    continue
                beds_str = row.get("BEDS", "").strip()
                beds = int(float(beds_str)) if beds_str else 0
                sqft_str = re.sub(r"[^0-9.]", "", row.get("SQUARE FEET") or "0") or "0"
                sqft = float(sqft_str)
                prop_type = row.get("PROPERTY TYPE", "").strip()

                grow = math.floor(clat / RENTAL_GRID_SIZE)
                gcol = math.floor(clng / RENTAL_GRID_SIZE)
                rental_grid.setdefault((grow, gcol), []).append(
                    (clat, clng, rent, beds, sqft, prop_type)
                )
                rental_comp_count += 1
            except (ValueError, TypeError):
                continue
    print(f"   Loaded {rental_comp_count:,} rental comps in {len(rental_grid):,} grid cells")
    if rental_stale_skipped:
        print(f"   Skipped {rental_stale_skipped:,} stale listings (>{RENTAL_MAX_AGE_DAYS} days old)")
else:
    print(f"\n⚠️  {RENTAL_COMPS_FILE} not found — run: python3 fetch_rental_comps.py")

# 4d-b: Load ZORI zip-level rents from zori_data.csv
zori_by_zip = {}  # zip → most recent monthly rent value
ZORI_FILE = "zori_data.csv"
if os.path.exists(ZORI_FILE):
    print(f"   Loading ZORI data from {ZORI_FILE}...")
    with open(ZORI_FILE, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        # Monthly columns are date-formatted: 2015-01-31, ..., 2026-01-31
        date_cols = [c for c in cols if re.match(r"\d{4}-\d{2}-\d{2}", c)]
        date_cols.sort()  # chronological order
        for row in reader:
            state = row.get("State", "").strip()
            if state != "CA":
                continue
            zipcode = str(row.get("RegionName", "")).strip()
            if not zipcode:
                continue
            # Find most recent non-empty value
            for col in reversed(date_cols):
                val = row.get(col, "").strip()
                if val:
                    try:
                        zori_by_zip[zipcode] = round(float(val))
                        break
                    except ValueError:
                        continue
    print(f"   ZORI: {len(zori_by_zip):,} CA zips with rent data")
else:
    print(f"   ⚠️  {ZORI_FILE} not found — ZORI tier unavailable")

# 4d-b2: Load Census tract-level rents from census_rents.json
CENSUS_RENTS_FILE = market_file("census_rents.json", market)
census_rent_grid = {}  # { (row, col): [(lat, lng, rent, rent3br, rent4br), ...] }
census_rent_count = 0
if os.path.exists(CENSUS_RENTS_FILE):
    print(f"   Loading Census tract rents from {CENSUS_RENTS_FILE}...")
    with open(CENSUS_RENTS_FILE) as f:
        census_tracts = json.load(f)
    for ct in census_tracts:
        clat = ct.get("lat", 0)
        clng = ct.get("lng", 0)
        rent = ct.get("rent")
        rent3br = ct.get("rent3br")
        if clat == 0 or clng == 0:
            continue
        if rent is None and rent3br is None:
            continue
        grow = math.floor(clat / RENTAL_GRID_SIZE)
        gcol = math.floor(clng / RENTAL_GRID_SIZE)
        census_rent_grid.setdefault((grow, gcol), []).append(
            (clat, clng, rent, rent3br, ct.get("rent4br"))
        )
        census_rent_count += 1
    print(f"   Census tracts: {census_rent_count:,} in {len(census_rent_grid):,} grid cells")
else:
    print(f"   ⚠️  {CENSUS_RENTS_FILE} not found — run: python3 fetch_census_rents.py")

# 4d-c: 6-tier rental estimate function
SFR_TH_TYPES = {"Single Family Residential", "Townhouse", "Condo/Co-op", "Multi-Family (2-4 Unit)"}

def find_rental_psf(lat, lng, zipcode, safmr_3br):
    """Find best rental $/SF estimate using 6-tier priority.

    Returns: (rent_psf, method, comp_count, radius_mi, median_beds, median_sqft)
    """
    grow = math.floor(lat / RENTAL_GRID_SIZE)
    gcol = math.floor(lng / RENTAL_GRID_SIZE)

    SIZE_ELASTICITY = 0.35  # Power-law decay: $/SF drops as unit size grows
    MIN_COMPS_FOR_P75 = 8  # Below this, use median instead of P75

    def p75(vals):
        vals.sort()
        return vals[int(len(vals) * 0.75)]

    def median_val(vals):
        vals.sort()
        return vals[len(vals) // 2]

    def pick_psf(vals):
        """Use P75 when we have enough comps, median when few."""
        if len(vals) >= MIN_COMPS_FOR_P75:
            return p75(vals)
        return median_val(vals)

    def size_adjust(raw_psf, median_sqft):
        """Adjust $/SF for size mismatch vs 1,750 SF target unit.
        Smaller comps have higher $/SF — scale down when extrapolating to larger units.
        Larger comps have lower $/SF — scale up when extrapolating to smaller units.
        """
        if median_sqft <= 0:
            return raw_psf
        ratio = (median_sqft / 1750) ** SIZE_ELASTICITY
        return raw_psf * ratio

    def collect_comps(radius, exact_beds, min_beds, min_sqft, max_sqft, types_filter):
        """Collect rental comps within radius matching criteria.
        exact_beds: if set, filter beds == exact_beds; otherwise use min_beds.
        Returns list of (rent_psf, beds, sqft) tuples.
        """
        cells = int(radius / RENTAL_GRID_SIZE) + 1
        matches = []
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                for clat, clng, rent, beds, sqft, ptype in rental_grid.get((grow + dr, gcol + dc), []):
                    if abs(clat - lat) > radius or abs(clng - lng) > radius:
                        continue
                    if exact_beds is not None and beds != exact_beds:
                        continue
                    if exact_beds is None and beds < min_beds:
                        continue
                    if sqft < min_sqft or sqft <= 0:
                        continue
                    if max_sqft > 0 and sqft > max_sqft:
                        continue
                    if types_filter and ptype not in types_filter:
                        continue
                    rpsf = rent / sqft
                    # Sanity filter: reject outlier $/SF
                    # $8/SF ceiling: 3BR at $8+/SF = $14K+/mo for 1,750 SF — ultra-luxury, not SB 1123 product
                    if rpsf < 0.50 or rpsf > 8.00:
                        continue
                    matches.append((rpsf, beds, sqft))
        return matches

    # Tier 1: rental-comp — 0.5mi→1mi, 3BR exact, 1000-2300 SF, SFR/TH/Condo/MF2-4
    # Per-comp size normalization: normalize each comp's $/SF to 1,750 SF target
    # BEFORE aggregating. Prevents small-unit $/SF inflation from dominating median.
    for radius in [0.007, 0.015]:
        comps = collect_comps(radius, 3, 0, 1000, 2300, SFR_TH_TYPES)
        comps = rental_iqr_trim(comps)
        if len(comps) >= 3:
            norm_psf_vals = [rpsf * (sqft / 1750) ** SIZE_ELASTICITY for rpsf, _, sqft in comps]
            beds_list = [b for _, b, _ in comps]
            sqft_list = [s for _, _, s in comps]
            miles = round(radius * 69, 2)
            med_sqft = round(median_val(list(sqft_list)))
            adj_psf = pick_psf(norm_psf_vals)
            return round(adj_psf, 2), "rental-comp", len(comps), miles, median_val(beds_list), med_sqft

    # Tier 2: rental-comp-wide — 2mi, 3BR exact, 1000-2300 SF, SFR/TH/Condo/MF2-4
    comps = collect_comps(0.029, 3, 0, 1000, 2300, SFR_TH_TYPES)
    comps = rental_iqr_trim(comps)
    if len(comps) >= 3:
        norm_psf_vals = [rpsf * (sqft / 1750) ** SIZE_ELASTICITY for rpsf, _, sqft in comps]
        beds_list = [b for _, b, _ in comps]
        sqft_list = [s for _, _, s in comps]
        med_sqft = round(median_val(list(sqft_list)))
        adj_psf = pick_psf(norm_psf_vals)
        return round(adj_psf, 2), "rental-comp-wide", len(comps), round(0.029 * 69, 2), median_val(beds_list), med_sqft

    # Tier 3: rental-adj — 1mi, 2+ BR, 800+ SF, ALL types, +15% if median beds < 3
    comps = collect_comps(0.015, None, 2, 800, 0, None)
    comps = rental_iqr_trim(comps)
    if len(comps) >= 3:
        norm_psf_vals = [rpsf * (sqft / 1750) ** SIZE_ELASTICITY for rpsf, _, sqft in comps]
        beds_list = [b for _, b, _ in comps]
        sqft_list = [s for _, _, s in comps]
        med_beds = median_val(list(beds_list))
        med_sqft = round(median_val(list(sqft_list)))
        rent_psf = pick_psf(norm_psf_vals)
        if med_beds < 3:
            rent_psf = rent_psf * 1.15
        return round(rent_psf, 2), "rental-adj", len(comps), round(0.015 * 69, 2), med_beds, med_sqft

    # Tier 4: Census tract-level rent — nearest centroid within 0.02° (~1.4 mi)
    # Convert 3BR rent to $/SF: (rent3br × 1.20) / 1200
    if census_rent_grid:
        search_radius = 0.02
        cells = int(search_radius / RENTAL_GRID_SIZE) + 1
        best_dist = float("inf")
        best_rent = None
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                for clat, clng, rent, rent3br, rent4br in census_rent_grid.get((grow + dr, gcol + dc), []):
                    dist = abs(clat - lat) + abs(clng - lng)  # Manhattan distance
                    if dist < best_dist and dist <= search_radius * 2:
                        best_dist = dist
                        best_rent = rent3br if rent3br else rent
        if best_rent and best_rent > 0:
            rent_psf = round((best_rent * 1.20) / 1200, 2)
            # Floor at ZORI-derived $/SF
            if zipcode in zori_by_zip:
                zori_psf = round((zori_by_zip[zipcode] * 1.20) / 1200, 2)
                rent_psf = max(rent_psf, zori_psf)
            return rent_psf, "census-tract", 0, round(best_dist * 69, 2), 0, 0

    # Tier 5: ZORI zip-level — (zori × 1.20) / 1200
    if zipcode in zori_by_zip:
        rent_psf = round((zori_by_zip[zipcode] * 1.20) / 1200, 2)
        return rent_psf, "zori", 0, 0, 0, 0

    # Tier 6: SAFMR fallback — (fmr3br × 1.15) / 1200
    if safmr_3br and safmr_3br > 0:
        rent_psf = round((safmr_3br * 1.15) / 1200, 2)
        return rent_psf, "safmr", 0, 0, 0, 0

    return 0, "none", 0, 0, 0, 0

# 4d-d: Stamp rental estimates per listing
if rental_comp_count > 0 or zori_by_zip or census_rent_count > 0:
    print(f"\n   Computing 6-tier rental estimates...")
    t0 = time.time()
    tier_counts = {"rental-comp": 0, "rental-comp-wide": 0, "rental-adj": 0, "census-tract": 0, "zori": 0, "safmr": 0, "none": 0}
    tier_rents = {"rental-comp": [], "rental-comp-wide": [], "rental-adj": [], "census-tract": [], "zori": [], "safmr": []}

    for i, l in enumerate(listings):
        safmr = l.get("fmr3br") or 0
        rent_psf, method, comp_count, radius_mi, med_beds, med_sqft = find_rental_psf(
            l["lat"], l["lng"], l.get("zip", ""), safmr
        )
        l["rentPsf"] = rent_psf
        if rent_psf > 0:
            l["estRentMonth"] = round(rent_psf * 1750)  # Backward compat at default unit size
        l["rentMethod"] = method
        l["rentCompCount"] = comp_count
        l["rentCompRadius"] = radius_mi
        l["rentCompMedianBeds"] = med_beds
        l["rentCompMedianSqft"] = med_sqft
        tier_counts[method] += 1
        if method in tier_rents and rent_psf > 0:
            tier_rents[method].append(rent_psf)

        if (i + 1) % 5000 == 0:
            elapsed = time.time() - t0
            print(f"   {i+1:,}/{len(listings):,} ({elapsed:.1f}s)")

    elapsed = time.time() - t0

    # 4d-e: Summary
    print(f"\n   Rental estimate tiers (done in {elapsed:.1f}s):")
    total = len(listings)
    spatial_count = tier_counts["rental-comp"] + tier_counts["rental-comp-wide"] + tier_counts["rental-adj"]
    for method in ["rental-comp", "rental-comp-wide", "rental-adj", "census-tract", "zori", "safmr", "none"]:
        cnt = tier_counts[method]
        pct = cnt / total * 100 if total else 0
        med_str = ""
        if tier_rents.get(method):
            vals = sorted(tier_rents[method])
            med_psf = vals[len(vals)//2]
            med_str = f" (median ${med_psf:.2f}/SF → ${round(med_psf * 1750):,}/mo)"
        print(f"     {method:20s}: {cnt:>6,} ({pct:5.1f}%){med_str}")

    with_rent = sum(1 for l in listings if l.get("estRentMonth") and l["estRentMonth"] > 0)
    safmr_only = tier_counts["safmr"]
    print(f"\n   Coverage: {with_rent:,}/{total:,} listings have rent estimates")
    print(f"   Spatial rental comps: {spatial_count:,} ({spatial_count/total*100:.1f}%)")
    if safmr_only > 0:
        print(f"   Improvement vs SAFMR-only: {total - safmr_only - tier_counts['none']:,} listings upgraded")
else:
    print(f"\n   No rental comp data or ZORI — keeping Step 4c SAFMR estimates")
    for l in listings:
        l["rentMethod"] = "safmr" if l.get("estRentMonth") else "none"
        l["rentPsf"] = round(l["estRentMonth"] / 1750, 2) if l.get("estRentMonth") else 0
        l["rentCompCount"] = 0
        l["rentCompRadius"] = 0
        l["rentCompMedianBeds"] = 0
        l["rentCompMedianSqft"] = 0

# ── Step 5: Stamp lot slope from slopes.json ──
SLOPE_FILE = market_file("slopes.json", market)
if os.path.exists(SLOPE_FILE):
    print(f"\n⛰️  Step 5: Stamping lot slopes...")
    with open(SLOPE_FILE) as f:
        slope_data = json.load(f)
    print(f"   Loaded {len(slope_data):,} slope records")

    slope_idx = build_fuzzy_index(slope_data)
    stamped = 0
    fuzzy_hits = 0
    for l in listings:
        matched_key = fuzzy_lookup(l["lat"], l["lng"], slope_data, slope_idx)
        if matched_key:
            l["slope"] = slope_data[matched_key]
            stamped += 1
            if matched_key != f"{l['lat']},{l['lng']}":
                fuzzy_hits += 1

    slopes_list = [l["slope"] for l in listings if "slope" in l]
    if slopes_list:
        flat = sum(1 for s in slopes_list if s < 5)
        mild = sum(1 for s in slopes_list if 5 <= s < 15)
        moderate = sum(1 for s in slopes_list if 15 <= s < 25)
        steep = sum(1 for s in slopes_list if s >= 25)
        print(f"   Stamped: {stamped:,}/{len(listings):,} (fuzzy: {fuzzy_hits:,})")
        print(f"   Flat (<5%): {flat:,} | Mild (5-15%): {mild:,} | Moderate (15-25%): {moderate:,} | Steep (25%+): {steep:,}")
else:
    print(f"\n⚠️  {SLOPE_FILE} not found — run: python3 fetch_slopes.py")

# ── Step 5b: Stamp per-parcel elevation metrics from elevation_cache.json ──
ELEV_FILE = market_file("elevation_cache.json", market)
if os.path.exists(ELEV_FILE):
    print(f"\n⛰️  Step 5b: Stamping per-parcel elevation metrics from {ELEV_FILE}...")
    with open(ELEV_FILE) as f:
        elev_data = json.load(f)
    print(f"   Loaded {len(elev_data):,} elevation records")

    elev_idx = build_fuzzy_index(elev_data)
    elev_stamped = 0
    elev_fuzzy = 0
    for l in listings:
        matched_key = fuzzy_lookup(l["lat"], l["lng"], elev_data, elev_idx)
        if matched_key:
            e = elev_data[matched_key]
            if isinstance(e, dict) and "slopeScore" in e:
                l["elevRange"] = e.get("elevRange")
                l["maxSlope"] = e.get("maxSlope")
                l["flatPct"] = e.get("flatPct")
                l["slopeScore"] = e.get("slopeScore")
                elev_stamped += 1
                if matched_key != f"{l['lat']},{l['lng']}":
                    elev_fuzzy += 1

    scores = [l["slopeScore"] for l in listings if l.get("slopeScore") is not None]
    if scores:
        flat_ct = sum(1 for s in scores if s <= 20)
        mod_ct = sum(1 for s in scores if 21 <= s <= 50)
        steep_ct = sum(1 for s in scores if 51 <= s <= 75)
        severe_ct = sum(1 for s in scores if s >= 76)
        print(f"   Stamped: {elev_stamped:,}/{len(listings):,} (fuzzy: {elev_fuzzy:,})")
        print(f"   Flat (0-20): {flat_ct:,} | Moderate (21-50): {mod_ct:,} | Steep (51-75): {steep_ct:,} | Severe (76+): {severe_ct:,}")
else:
    print(f"\n⚠️  {ELEV_FILE} not found — run: python3 fetch_elevation.py")

print("\n📊 Summary:")
zone_counts = {}
for l in listings:
    z = l["zone"] or "Unknown"
    zone_counts[z] = zone_counts.get(z, 0) + 1
for z in ["R1", "R2", "R3", "R4", "MU", "LAND", "Unknown"]:
    if z in zone_counts:
        print(f"   {z}: {zone_counts[z]} listings")

with_exit = sum(1 for l in listings if l.get("exitPsf"))
with_lot = sum(1 for l in listings if l["lotSf"])
print(f"   With exit $/SF: {with_exit}/{len(listings)}")
print(f"   With lot size: {with_lot}/{len(listings)}")

# Show zone-specific exit $/SF samples
if with_exit:
    print(f"\n   Zone-specific exit $/SF:")
    for z in ["R1", "R2", "R3", "R4", "MU"]:
        zone_exits = [l["exitPsf"] for l in listings if l["zone"] == z and l.get("exitPsf")]
        if zone_exits:
            zone_exits.sort()
            med = zone_exits[len(zone_exits)//2]
            p10 = zone_exits[len(zone_exits)//10] if len(zone_exits) >= 10 else zone_exits[0]
            p90 = zone_exits[int(len(zone_exits)*0.9)] if len(zone_exits) >= 10 else zone_exits[-1]
            print(f"     {z}: ${med}/sf (P10=${p10}, P90=${p90}, n={len(zone_exits)})")

# ── Phase 5 Spot-Check: Debug two specific deals ──
if "--spot-check" in sys.argv or "--debug" in sys.argv:
    SPOT_CHECKS = [
        {"name": "Deal A: Santa Monica 90405", "lat": 34.015815, "lng": -118.460505},
        {"name": "Deal B: Woodland Hills 91367 (Oxnard St)", "lat": 34.185, "lng": -118.605},
    ]
    print(f"\n🔍 SPOT-CHECK: Comp scoring breakdown")
    for spot in SPOT_CHECKS:
        slat, slng = spot["lat"], spot["lng"]
        # Find nearest listing
        nearest = min(listings, key=lambda l: abs(l["lat"]-slat)+abs(l["lng"]-slng))
        print(f"\n   === {spot['name']} ===")
        print(f"   Nearest listing: {nearest.get('address','?')} ({nearest['lat']},{nearest['lng']})")
        print(f"   ZIP: {nearest.get('zip','?')}")

        # Run debug scoring
        result = find_weighted_exit_ppsf(nearest["lat"], nearest["lng"], nearest.get("zip",""), debug=True)

        # Also get raw pool count
        all_nearby = collect_comps_in_radius(nearest["lat"], nearest["lng"], CASCADE_MAX_MI)
        print(f"   Comp pool before filters (3mi radius): {len(all_nearby)}")

        scored = result["scored_comps"]
        print(f"   After scoring: {len(scored)} comps")
        print(f"   Weighted exit $/SF: {'$'+str(result['exit_psf']) if result['exit_psf'] else 'NULL'}")
        print(f"   Previous exit $/SF (from listing): {'$'+str(nearest.get('exitPsf','?')) if nearest.get('exitPsf') else 'NULL'}")
        print(f"   SFR comp share: {result['sfr_comp_share']*100:.0f}%{'  ⚠️ SFR-HEAVY' if result['sfr_comp_share']>0.30 else ''}")
        print(f"   Low comp confidence: {result['low_comp_confidence']}")
        print(f"   Cascade triggered: {result['cascade_triggered']} ({result['cascade_step'] or 'none'})")

        if scored:
            print(f"\n   {'Address':<35} {'PropType':<8} {'YrBlt':<6} {'SqFt':<6} {'Date':<12} {'Raw$/SF':<8} {'ProdWt':<7} {'ProxWt':<7} {'RecWt':<6} {'Score':<7} {'Adj$/SF':<8}")
            print(f"   {'─'*35} {'─'*8} {'─'*6} {'─'*6} {'─'*12} {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*7} {'─'*8}")
            for c in sorted(scored, key=lambda x: -x["composite_score"])[:20]:
                addr = (c.get("address","") or "")[:35]
                pt_name = {1:"SFR",2:"Condo",3:"TH"}.get(c["pt"],"?")
                print(f"   {addr:<35} {pt_name:<8} {c.get('yb','?')!s:<6} {c.get('sqft',0):<6} {(c.get('date','')or'')[:12]:<12} ${c['ppsf']:<7} {c['product_wt']:<7.2f} {c['proximity_wt']:<7.2f} {c['recency_wt']:<6.2f} {c['composite_score']:<7.4f} ${c['adj_ppsf']:<7}")
        print()

# ── Write listings.js ──
output_file = market_file("listings.js", market)
build_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Source file ages (days since last modified)
def file_age_days(path):
    try:
        return round((time.time() - os.path.getmtime(path)) / 86400, 1)
    except OSError:
        return -1

source_ages = {
    "compsAge": file_age_days(market_file("data.js", market)),
    "parcelsAge": file_age_days(market_file("parcels.json", market)),
    "slopesAge": file_age_days(market_file("slopes.json", market)),
    "listingsAge": file_age_days(market_file("redfin_merged.csv", market)),
}
ages_js = ",".join(f'{k}:{v}' for k, v in source_ages.items())

# Strip debug-only fields not used by the frontend (saves ~1-2% payload)
PRUNE_FIELDS = {"rentCompMedianBeds", "rentCompMedianSqft"}
if "--debug" not in sys.argv:
    pruned = 0
    for l in listings:
        for f in PRUNE_FIELDS:
            if f in l:
                del l[f]
                pruned += 1
    if pruned:
        print(f"   Pruned {pruned} debug fields ({len(PRUNE_FIELDS)} types)")

js = f"var LISTINGS_META = {{builtAt:\"{build_ts}\",count:{len(listings)},{ages_js}}};\n"
js += "var LOADED_LISTINGS = " + json.dumps(listings, separators=(",", ":")) + ";"
with open(output_file, "w") as f:
    f.write(js)
size_kb = len(js) / 1024
print(f"\n📦 Created {output_file} ({size_kb:.1f} KB, {len(listings)} listings)")
print("   Done! ✅\n")

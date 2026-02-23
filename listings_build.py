#!/usr/bin/env python3
"""
listings_build.py
Processes a Redfin active-listings CSV export into listings.js for the GUI.

What it does:
  1. Reads the Redfin CSV
  2. Filters to LA County only (lat/lng bounding box)
  3. Pulls lot size from the CSV
  4. Computes hyperlocal zone-matched exit $/SF (P75) from sold comps
     - P75 = 75th percentile (new townhomes compete with top quartile)
     - Spatial grid index for fast radius-based lookup
     - Same-zone comps only (R2 listing → R2 comps only)
     - Expanding radius search: 0.25mi → 0.5mi → 1mi → 2mi → 4mi
     - Falls back to all-zone comps, then zip-level if needed
  5. Assigns an approximate zone from Redfin property type
  6. Outputs a clean listings.js
"""
import csv, json, re, os, glob, statistics, time, math, sys
from datetime import datetime, timezone

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file, TYPE_TO_ZONE

market = get_market()
LAT_MIN, LAT_MAX = market["lat_min"], market["lat_max"]
LNG_MIN, LNG_MAX = market["lng_min"], market["lng_max"]

# ── Spatial comp index config ──
GRID_SIZE = 0.01          # ~0.7 miles per cell
MIN_COMPS = 5             # Minimum comps needed for a reliable median
DEG_PER_MILE = 1 / 69.0  # Approximate degrees latitude per mile
COMP_SQFT_MIN = 1300      # Min comp SF — 75% of 1,750 SF product size
COMP_SQFT_MAX = 3500      # Max comp SF — exclude mega-homes that drag down $/SF
# Search radii in degrees: 0.5mi and 1.0mi only — wider radii cross LA neighborhoods
SEARCH_RADII_DEG = [0.007, 0.015]

# ── Step 1: Load comps and build spatial index ──
print("\n🏘️  Step 1: Loading comps + building spatial index...")
comps = []

comps_file = market_file("data.js", market)
if os.path.exists(comps_file):
    with open(comps_file, "r") as f:
        raw = f.read()
    match = re.search(r"=\s*(\[.*\])\s*;?\s*$", raw, re.DOTALL)
    if match:
        comps = json.loads(match.group(1))
        print(f"   Loaded {len(comps):,} sold comps")
    else:
        print(f"   ⚠️  Could not parse {comps_file} — neighborhood $/SF will be unavailable")
else:
    print(f"   ⚠️  {comps_file} not found — neighborhood $/SF will be unavailable")

# Build spatial grid: zone-specific and all-zone indexes
# Key: (grid_row, grid_col) → list of (lat, lng, ppsf)
zone_grid = {}   # { zone: { (row,col): [(lat,lng,ppsf), ...] } }
all_grid = {}    # { (row,col): [(lat,lng,ppsf), ...] }
# New-con grids: tiered by vintage (2024-25 / 2023+ / 2021+)
# Entries include year_built for tiered filtering: (lat, lng, ppsf, sqft, yb)
newcon_zone_grid = {}  # { zone: { (row,col): [(lat,lng,ppsf,sqft,yb), ...] } }
newcon_all_grid = {}   # { (row,col): [(lat,lng,ppsf,sqft,yb,zone), ...] } — for cross-zone fallback
# Zip-level fallback: { (zip, zone): [ppsf], zip: [ppsf] }
zip_zone_ppsfs = {}
zip_all_ppsfs = {}
newcon_count = 0

for c in comps:
    clat = c.get("lat", 0)
    clng = c.get("lng", 0)
    czone = c.get("zone", "")
    cppsf = c.get("ppsf") or (round(c["price"] / c["sqft"]) if c.get("sqft", 0) > 0 else 0)
    csqft = c.get("sqft", 0)
    czip = c.get("zip", "")
    if cppsf <= 0 or clat == 0 or clng == 0:
        continue

    # Grid cell
    grow = math.floor(clat / GRID_SIZE)
    gcol = math.floor(clng / GRID_SIZE)
    entry = (clat, clng, cppsf, csqft)

    # Zone-specific grid
    if czone:
        if czone not in zone_grid:
            zone_grid[czone] = {}
        zone_grid[czone].setdefault((grow, gcol), []).append(entry)

    # All-zone grid
    all_grid.setdefault((grow, gcol), []).append(entry)

    # New-con grid (year_built >= 2021) — zone-specific + all-zone for cross-zone fallback
    yb = c.get("yb")
    if yb and yb >= 2021 and czone:
        nc_entry = (clat, clng, cppsf, csqft, yb)
        if czone not in newcon_zone_grid:
            newcon_zone_grid[czone] = {}
        newcon_zone_grid[czone].setdefault((grow, gcol), []).append(nc_entry)
        newcon_all_grid.setdefault((grow, gcol), []).append((clat, clng, cppsf, csqft, yb, czone))
        newcon_count += 1

    # Zip-level fallbacks
    if czip:
        if czone:
            zip_zone_ppsfs.setdefault((czip, czone), []).append(cppsf)
        zip_all_ppsfs.setdefault(czip, []).append(cppsf)

zone_comp_counts = {z: sum(len(v) for v in g.values()) for z, g in zone_grid.items()}
print(f"   Spatial index: {len(all_grid):,} grid cells")
for z in ["R1", "R2", "R3", "R4"]:
    print(f"     {z}: {zone_comp_counts.get(z, 0):,} comps")
newcon_zone_counts = {z: sum(len(v) for v in g.values()) for z, g in newcon_zone_grid.items()}
newcon_cells = sum(len(g) for g in newcon_zone_grid.values())
print(f"   New-con (2021+): {newcon_count:,} comps in {newcon_cells:,} cells")
for z in ["R1", "R2", "R3", "R4"]:
    if z in newcon_zone_counts:
        print(f"     {z}: {newcon_zone_counts[z]:,} new-con comps")
print(f"   Zip+zone fallbacks: {len(zip_zone_ppsfs)} combos")


def find_exit_ppsf(lat, lng, zone, zipcode):
    """Find zone-matched exit $/SF (P75) using radius-based search.

    Two radii only (0.5mi, 1mi) — wider searches cross LA neighborhoods.
    Size-band 1300-3500 SF preferred; thin-comp fallback if 1-4 comps found.

    Priority:
      1. Same-zone, size-band comps (≥5) → "zone"
      2. Same-zone, all-size comps (≥5 at widest) → "zone"
      3. Same-zone, any comps at widest (1-4) → "zone-thin"
      4. All-zone, size-band comps (≥5) → "all"
      5. All-zone, all-size comps (≥5 at widest) → "all"
      6. All-zone, any comps at widest (1-4) → "all-thin"
      7. Zip+zone / zip fallback
    """
    grow = math.floor(lat / GRID_SIZE)
    gcol = math.floor(lng / GRID_SIZE)

    def p75(vals):
        vals.sort()
        return round(vals[int(len(vals) * 0.75)])

    def in_band(sqft):
        return COMP_SQFT_MIN <= sqft <= COMP_SQFT_MAX

    # Try same-zone spatial search
    zg = zone_grid.get(zone, {})
    last_zone_band = []
    last_zone_all = []
    last_zone_miles = 0
    if zg:
        for radius in SEARCH_RADII_DEG:
            cells = int(radius / GRID_SIZE) + 1
            nearby_band = []
            nearby_all = []
            for dr in range(-cells, cells + 1):
                for dc in range(-cells, cells + 1):
                    for clat, clng, cppsf, csqft in zg.get((grow + dr, gcol + dc), []):
                        if abs(clat - lat) <= radius and abs(clng - lng) <= radius:
                            nearby_all.append(cppsf)
                            if in_band(csqft):
                                nearby_band.append(cppsf)
            if len(nearby_band) >= MIN_COMPS:
                miles = round(radius * 69, 2)
                return p75(nearby_band), len(nearby_band), miles, "zone"
            last_zone_band = nearby_band
            last_zone_all = nearby_all
            last_zone_miles = round(radius * 69, 2)
        # At widest radius: try all-size fallback, then thin-comp
        if len(last_zone_all) >= MIN_COMPS:
            return p75(last_zone_all), len(last_zone_all), last_zone_miles, "zone"
        if len(last_zone_band) > 0:
            return p75(last_zone_band), len(last_zone_band), last_zone_miles, "zone-thin"
        if len(last_zone_all) > 0:
            return p75(last_zone_all), len(last_zone_all), last_zone_miles, "zone-thin"

    # Fallback: all-zone spatial search
    last_all_band = []
    last_all_all = []
    last_all_miles = 0
    for radius in SEARCH_RADII_DEG:
        cells = int(radius / GRID_SIZE) + 1
        nearby_band = []
        nearby_all = []
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                for clat, clng, cppsf, csqft in all_grid.get((grow + dr, gcol + dc), []):
                    if abs(clat - lat) <= radius and abs(clng - lng) <= radius:
                        nearby_all.append(cppsf)
                        if in_band(csqft):
                            nearby_band.append(cppsf)
        if len(nearby_band) >= MIN_COMPS:
            miles = round(radius * 69, 2)
            return p75(nearby_band), len(nearby_band), miles, "all"
        last_all_band = nearby_band
        last_all_all = nearby_all
        last_all_miles = round(radius * 69, 2)
    # At widest radius: try all-size fallback, then thin-comp
    if len(last_all_all) >= MIN_COMPS:
        return p75(last_all_all), len(last_all_all), last_all_miles, "all"
    if len(last_all_band) > 0:
        return p75(last_all_band), len(last_all_band), last_all_miles, "all-thin"
    if len(last_all_all) > 0:
        return p75(last_all_all), len(last_all_all), last_all_miles, "all-thin"

    # Fallback: zip + same zone (only if zero spatial comps)
    zz_key = (zipcode, zone)
    if zz_key in zip_zone_ppsfs and len(zip_zone_ppsfs[zz_key]) >= 3:
        vals = list(zip_zone_ppsfs[zz_key])
        return p75(vals), len(vals), 0, "zip+zone"

    # Last resort: zip all-zone
    if zipcode in zip_all_ppsfs:
        vals = list(zip_all_ppsfs[zipcode])
        return p75(vals), len(vals), 0, "zip"

    return 0, 0, 0, "none"


ADJACENT_ZONES = {
    "R1": ["R2"],
    "R2": ["R1", "R3"],
    "R3": ["R2", "R4"],
    "R4": ["R3"],
    "LAND": ["R1"],
}
NEWCON_RADII = [0.007, 0.015, 0.022, 0.029]  # 0.5mi/1mi/1.5mi/2mi
NEWCON_MIN = 3  # Absolute minimum comps to use new-con pricing

def find_newcon_ppsf(lat, lng, zone, exit_psf):
    """Find new-construction P75 $/SF with tiered vintage and zone-matching.

    Tiers (searched in order, each tier accumulates):
      1. Built 2024-2025 — same rate environment
      2. Built 2023+ — post-rate-shock
      3. Built 2021-2022 — apply -10% haircut per comp

    Zone priority: same-zone first, then cross-zone (adjacent zones).
    Minimum 3 comps required. Sanity check vs general P75.

    Returns: (ppsf, count, tier_label, zone_matched, flag) or (None, 0, None, None, flag)
    """
    grow = math.floor(lat / GRID_SIZE)
    gcol = math.floor(lng / GRID_SIZE)

    def in_band(sqft):
        return COMP_SQFT_MIN <= sqft <= COMP_SQFT_MAX

    def p75(vals):
        vals.sort()
        return round(vals[int(len(vals) * 0.75)])

    def collect_from_grid(grid, radius):
        """Collect comps from a zone-specific grid within radius."""
        cells = int(radius / GRID_SIZE) + 1
        result = []
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                for entry in grid.get((grow + dr, gcol + dc), []):
                    clat, clng = entry[0], entry[1]
                    if abs(clat - lat) <= radius and abs(clng - lng) <= radius:
                        result.append(entry)
        return result

    def try_tiers(raw_comps):
        """Apply tiered vintage filtering. Returns (adjusted_ppsf_list, tier_label, has_stale)."""
        # Tier 1: 2024-2025 only
        t1 = [(cppsf, csqft) for _, _, cppsf, csqft, yb in raw_comps
               if yb >= 2024 and in_band(csqft)]
        if len(t1) >= MIN_COMPS:
            return [p for p, _ in t1], "2024-25", False

        # Tier 2: 2023+ (includes tier 1)
        t2 = [(cppsf, csqft) for _, _, cppsf, csqft, yb in raw_comps
               if yb >= 2023 and in_band(csqft)]
        if len(t2) >= MIN_COMPS:
            return [p for p, _ in t2], "2023+", False

        # Tier 3: 2021-2022 with -10% haircut, added to tier 2 comps
        t3_adj = [round(cppsf * 0.90) for _, _, cppsf, csqft, yb in raw_comps
                  if 2021 <= yb <= 2022 and in_band(csqft)]
        combined = [p for p, _ in t2] + t3_adj
        if len(combined) >= NEWCON_MIN:
            tier = "2021-22 adj" if t3_adj else "2023+"
            return combined, tier, bool(t3_adj)

        return combined, None, bool(t3_adj)

    # --- Phase 1: Same-zone search ---
    zg = newcon_zone_grid.get(zone, {})
    best_same = []
    for radius in NEWCON_RADII:
        raw = collect_from_grid(zg, radius) if zg else []
        if not raw:
            continue
        ppsf_list, tier, has_stale = try_tiers(raw)
        if tier and len(ppsf_list) >= MIN_COMPS:
            val = p75(ppsf_list)
            flag = "thin" if len(ppsf_list) < MIN_COMPS + 2 else ("stale" if has_stale else None)
            # Sanity check vs general P75
            if exit_psf and exit_psf > 0:
                if val < exit_psf * 0.75:
                    return None, len(ppsf_list), tier, True, "sanity-low"
                if val > exit_psf * 1.50:
                    flag = "sanity-high"
            return val, len(ppsf_list), tier, True, flag
        best_same = ppsf_list  # Keep widest radius result for fallback

    # --- Phase 2: Cross-zone search (adjacent zones) ---
    adj_zones = ADJACENT_ZONES.get(zone, [])
    for radius in NEWCON_RADII:
        raw_cross = []
        for az in adj_zones:
            azg = newcon_zone_grid.get(az, {})
            if azg:
                for entry in collect_from_grid(azg, radius):
                    raw_cross.append(entry)
        # Also include same-zone comps we already found
        raw_same = collect_from_grid(zg, radius) if zg else []
        raw_all = raw_same + raw_cross
        if not raw_all:
            continue
        ppsf_list, tier, has_stale = try_tiers(raw_all)
        if tier and len(ppsf_list) >= NEWCON_MIN:
            val = p75(ppsf_list)
            flag = "cross-zone"
            if has_stale:
                flag = "cross-zone"  # cross-zone takes priority as flag
            if len(ppsf_list) < MIN_COMPS + 2:
                flag = "cross-zone"
            # Sanity check
            if exit_psf and exit_psf > 0:
                if val < exit_psf * 0.75:
                    return None, len(ppsf_list), tier, False, "sanity-low"
                if val > exit_psf * 1.50:
                    flag = "sanity-high"
            return val, len(ppsf_list), tier, False, flag

    # Not enough comps even with cross-zone
    return None, 0, None, None, None


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

            # Land listings may have sqft=0 — that's OK
            if sqft <= 0 and zone != "LAND":
                skipped_data += 1
                continue

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

    for l in listings:
        key = f"{l['lat']},{l['lng']}"
        if key in parcel_data:
            p = parcel_data[key]
            # Parcel lot size is PRIMARY (Redfin CSV is fallback)
            # Exception: if parcel lot is >3x Redfin lot for vacant land,
            # prefer Redfin — listing agent knows what's actually for sale
            # (common with flag lots, sliver parcels sold from larger estates)
            redfin_lot = l.get("lotSf") or 0
            parcel_lot = p.get("lotSf") or 0
            if parcel_lot > 0:
                is_suspicious = (redfin_lot > 0 and parcel_lot > redfin_lot * 3
                                 and l.get("zone") == "LAND")
                if not is_suspicious:
                    l["lotSf"] = parcel_lot
                    parcel_stamped += 1
                else:
                    # Also flag assessed value vs price mismatch
                    l["lotSfParcel"] = parcel_lot  # Keep for reference
                    # Keep Redfin lot size
            # Override address with ArcGIS situs address when available
            # Redfin sometimes returns truncated/mangled addresses
            if p.get("situsAddress"):
                situs = p["situsAddress"].strip()
                if situs:
                    # Rebuild address with parcel situs + city + zip
                    addr_parts = [situs, l.get("city", ""), l.get("zip", "")]
                    l["address"] = ", ".join(p for p in addr_parts if p)
            # Fire zone from ArcGIS
            if "fireZone" in p:
                l["fireZone"] = p["fireZone"]
                if p["fireZone"]:
                    parcel_fire_count += 1
            # Assessor data for popup display
            if p.get("ain"):
                l["ain"] = p["ain"]
            if p.get("landValue") is not None:
                l["assessedLandValue"] = p["landValue"]
            if p.get("impValue") is not None:
                l["assessedImpValue"] = p["impValue"]

    print(f"   Lot size stamped: {parcel_stamped:,}/{len(listings):,}")
    print(f"   Fire zone (VHFHSZ): {parcel_fire_count:,}")
else:
    print(f"\n⚠️  {PARCEL_FILE} not found — run: python3 fetch_parcels.py")

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

    for l in listings:
        key = f"{l['lat']},{l['lng']}"
        if key in zoning_data:
            z = zoning_data[key]
            sb_zone = z.get("sb1123")
            if sb_zone:
                l["zimasZone"] = z.get("zoning")       # Raw ZIMAS code (e.g. "R2-1")
                l["zimasCategory"] = z.get("category")  # Descriptive category
                old_zone = l["zone"]
                if old_zone != sb_zone:
                    if sb_zone in ("R2", "R3", "R4") and old_zone in ("R1", "LAND"):
                        zimas_upgraded += 1
                    elif old_zone in ("R2", "R3", "R4") and sb_zone in ("R1", "LAND"):
                        zimas_downgraded += 1
                l["zone"] = sb_zone  # Override Redfin guess with ZIMAS truth
                # Add track indicator (SF = single-family, MF = multifamily)
                l["track"] = "SF" if sb_zone in ("R1", "LAND") else "MF"
                zimas_stamped += 1

    print(f"   ZIMAS zoning stamped: {zimas_stamped:,}/{len(listings):,}")
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

    if not l.get("hasStructure"):
        # Vacant land = no tenant risk
        l["tenantRisk"] = 0
        l["tenantRiskFactors"] = []
        l["rsoRisk"] = False
        tenant_risk_counts[0] += 1
        continue

    # Factor 1: Occupied structure (has improvement value from assessor)
    imp_val = l.get("assessedImpValue", 0) or 0
    if imp_val > 50000:
        risk_score += 1
        risk_factors.append("improved")

    # Factor 2: Bedroom count (more beds = more likely occupied)
    beds_str = l.get("beds", "")
    beds_int = int(beds_str) if beds_str and str(beds_str).isdigit() else 0
    if beds_int >= 5:
        risk_score += 2
        risk_factors.append("5+beds")
    elif beds_int >= 3:
        risk_score += 1
        risk_factors.append("3+beds")

    # Factor 3: Multi-family zone with structure (likely tenanted units)
    if l.get("track") == "MF" and l.get("hasStructure"):
        risk_score += 1
        risk_factors.append("MF+struct")

    # Factor 4: Year built suggests long-term occupancy
    yb_str = l.get("yearBuilt", "")
    yb_int = int(yb_str) if yb_str and str(yb_str).isdigit() else 0
    if yb_int > 0 and yb_int < 2000:
        risk_score += 1
        risk_factors.append("pre-2000")

    # RSO/Ellis Act assessment (LA market only)
    if market["slug"] == "la" and l.get("hasStructure"):
        is_pre_1978 = yb_int > 0 and yb_int < 1979
        is_la_city = (l.get("city") or "").lower() in ("los angeles", "la", "")
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
    if l.get("track") == "MF" and l.get("hasStructure") and l.get("lotSf"):
        sqft = l.get("sqft", 0) or 0
        lot_sf = l["lotSf"]
        est_stories = 1 if sqft < 1500 else 2
        est_footprint = sqft / est_stories if sqft > 0 else 0
        remainder_sf = max(0, lot_sf - est_footprint)
        remainder_units = min(10, int(remainder_sf / 600)) if remainder_sf >= 1200 else 0
        l["remainderSf"] = round(remainder_sf)
        l["remainderUnits"] = remainder_units
        l["estFootprint"] = round(est_footprint)
        if remainder_units > 0:
            remainder_count += 1

print(f"   Tenant risk — None: {tenant_risk_counts[0]:,} | Low: {tenant_risk_counts[1]:,} | Med: {tenant_risk_counts[2]:,} | High: {tenant_risk_counts[3]:,}")
print(f"   RSO risk (LA only): {rso_count:,}")
print(f"   Remainder parcels (R2-R4 viable): {remainder_count:,}")

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
                l["fireZone"] = True
                burn_counts[bz["name"]] = burn_counts.get(bz["name"], 0) + 1
                break
    for name, count in burn_counts.items():
        print(f"   {name} burn zone: {count} listings")
    if not burn_counts:
        print("   No listings in burn zones")
else:
    print(f"\n✅ Step 3b: No burn zones configured for {market['name']}")

# ── Step 4: Zone-matched spatial exit $/SF (P75) ──
if comps:
    print(f"\n📍 Step 4: Computing zone-matched exit $/SF (P75)...")
    t0 = time.time()
    method_counts = {"zone": 0, "zone-thin": 0, "all": 0, "all-thin": 0, "zip+zone": 0, "zip": 0, "none": 0}
    radius_sum = 0
    comp_count_sum = 0

    for i, l in enumerate(listings):
        exit_ppsf, n_comps, radius_mi, method = find_exit_ppsf(
            l["lat"], l["lng"], l["zone"], l["zip"]
        )
        l["exitPsf"] = exit_ppsf if exit_ppsf > 0 else None
        l["compMethod"] = method
        l["compCount"] = n_comps
        l["compRadius"] = radius_mi
        method_counts[method] += 1
        if method in ("zone", "all", "zone-thin", "all-thin"):
            radius_sum += radius_mi
            comp_count_sum += n_comps

        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            print(f"   {i+1:,}/{len(listings):,} ({elapsed:.1f}s)")

    elapsed = time.time() - t0
    spatial_hits = sum(method_counts[m] for m in ("zone", "all", "zone-thin", "all-thin"))
    avg_radius = (radius_sum / spatial_hits) if spatial_hits else 0
    avg_comps = (comp_count_sum / spatial_hits) if spatial_hits else 0

    print(f"   Done in {elapsed:.1f}s")
    print(f"   Method breakdown:")
    print(f"     Zone-matched spatial: {method_counts['zone']:,} ({method_counts['zone']/len(listings)*100:.1f}%)")
    print(f"     Zone-thin (1-4 comps): {method_counts['zone-thin']:,}")
    print(f"     All-zone spatial:     {method_counts['all']:,} ({method_counts['all']/len(listings)*100:.1f}%)")
    print(f"     All-thin (1-4 comps): {method_counts['all-thin']:,}")
    print(f"     Zip+zone fallback:    {method_counts['zip+zone']:,}")
    print(f"     Zip all-zone:         {method_counts['zip']:,}")
    print(f"     No data:              {method_counts['none']:,}")
    if spatial_hits:
        print(f"   Avg search radius: {avg_radius:.2f} mi")
        print(f"   Avg comps per listing: {avg_comps:.0f}")
else:
    print(f"\n⚠️  No comps loaded — skipping exit $/SF computation")
    for l in listings:
        l["exitPsf"] = None

# ── Step 4b: New-construction sell-side $/SF ──
if newcon_count > 0:
    print(f"\n🏗️  Step 4b: Computing tiered new-con exit $/SF (2021+ built)...")
    nc_found = 0
    tier_counts = {"2024-25": 0, "2023+": 0, "2021-22 adj": 0}
    zone_match_count = 0
    cross_zone_count = 0
    flag_counts = {"thin": 0, "stale": 0, "cross-zone": 0, "sanity-low": 0, "sanity-high": 0}
    for l in listings:
        exit_psf = l.get("exitPsf") or 0
        nc_val, nc_count, nc_tier, nc_zm, nc_flag = find_newcon_ppsf(
            l["lat"], l["lng"], l["zone"], exit_psf
        )
        l["newconPpsf"] = nc_val
        l["newconCount"] = nc_count
        l["newconTier"] = nc_tier
        l["newconZoneMatch"] = nc_zm
        l["newconFlag"] = nc_flag
        if nc_val:
            nc_found += 1
            if nc_tier in tier_counts:
                tier_counts[nc_tier] += 1
            if nc_zm:
                zone_match_count += 1
            else:
                cross_zone_count += 1
        if nc_flag and nc_flag in flag_counts:
            flag_counts[nc_flag] += 1

    print(f"   New-con pricing used: {nc_found:,}/{len(listings):,} listings")
    print(f"   Discarded (fell back to general P75): {len(listings) - nc_found:,}")
    print(f"   Tiers: 2024-25={tier_counts['2024-25']:,} | 2023+={tier_counts['2023+']:,} | 2021-22 adj={tier_counts['2021-22 adj']:,}")
    print(f"   Zone-matched: {zone_match_count:,} | Cross-zone: {cross_zone_count:,}")
    print(f"   Flags: thin={flag_counts['thin']:,} stale={flag_counts['stale']:,} cross-zone={flag_counts['cross-zone']:,} sanity-low={flag_counts['sanity-low']:,} sanity-high={flag_counts['sanity-high']:,}")
    nc_vals = [l["newconPpsf"] for l in listings if l.get("newconPpsf")]
    if nc_vals:
        nc_vals.sort()
        print(f"   New-con $/SF: median ${nc_vals[len(nc_vals)//2]}, P10=${nc_vals[len(nc_vals)//10]}, P90=${nc_vals[int(len(nc_vals)*0.9)]}")
else:
    print(f"\n⚠️  No new-construction comps — add 'yb' field to data.js (run build_comps.py)")
    for l in listings:
        l["newconPpsf"] = None
        l["newconCount"] = 0
        l["newconTier"] = None
        l["newconZoneMatch"] = None
        l["newconFlag"] = None

# ── Step 4b2: Subdivision comp exit $/SF (Tier 0 — highest priority) ──
SUBDIV_FILE = market_file("subdiv_comps.json", market)
SUBDIV_GRID_SIZE = 0.01  # Same grid size as sale comp index
SUBDIV_RADII = [0.007, 0.015, 0.029]  # 0.5mi, 1mi, 2mi
SUBDIV_MIN_COMPS = 3

subdiv_grid = {}   # { (row, col): [comp, ...] }
subdiv_zone_grid = {}  # { zone: { (row, col): [comp, ...] } }
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
        szone = sc.get("zone", "")
        if adj_ppsf <= 0 or slat == 0 or slng == 0:
            continue

        grow = math.floor(slat / SUBDIV_GRID_SIZE)
        gcol = math.floor(slng / SUBDIV_GRID_SIZE)

        subdiv_grid.setdefault((grow, gcol), []).append(sc)

        if szone:
            if szone not in subdiv_zone_grid:
                subdiv_zone_grid[szone] = {}
            subdiv_zone_grid[szone].setdefault((grow, gcol), []).append(sc)

        subdiv_count += 1

    print(f"   Indexed: {subdiv_count:,} comps in {len(subdiv_grid):,} grid cells")

    def find_subdiv_exit_ppsf(lat, lng, zone):
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

        # Try zone-matched first
        zg = subdiv_zone_grid.get(zone, {})
        for radius in SUBDIV_RADII:
            comps = collect(zg, radius) if zg else []
            if len(comps) >= SUBDIV_MIN_COMPS:
                adj_vals = [c["adj_ppsf"] for c in comps]
                avg_appr = round(sum(c.get("appr_pct", 0) for c in comps) / len(comps), 1)
                avg_cluster = round(sum(c.get("cluster_size", 1) for c in comps) / len(comps), 1)
                miles = round(radius * 69, 2)
                return p75(adj_vals), len(comps), miles, avg_appr, avg_cluster

        # Fall back to all-zone
        for radius in SUBDIV_RADII:
            comps = collect(subdiv_grid, radius)
            if len(comps) >= SUBDIV_MIN_COMPS:
                adj_vals = [c["adj_ppsf"] for c in comps]
                avg_appr = round(sum(c.get("appr_pct", 0) for c in comps) / len(comps), 1)
                avg_cluster = round(sum(c.get("cluster_size", 1) for c in comps) / len(comps), 1)
                miles = round(radius * 69, 2)
                return p75(adj_vals), len(comps), miles, avg_appr, avg_cluster

        return None, 0, 0, 0, 0

    # Stamp each listing
    subdiv_found = 0
    for l in listings:
        val, count, radius_mi, avg_appr, avg_cluster = find_subdiv_exit_ppsf(
            l["lat"], l["lng"], l["zone"]
        )
        if val:
            l["subdivExitPsf"] = val
            l["subdivCompCount"] = count
            l["subdivCompRadius"] = radius_mi
            l["subdivAvgAppr"] = avg_appr
            l["subdivAvgCluster"] = avg_cluster
            subdiv_found += 1

    print(f"   Subdiv pricing used: {subdiv_found:,}/{len(listings):,} listings ({subdiv_found/len(listings)*100:.1f}%)")
    if subdiv_found:
        sv = sorted([l["subdivExitPsf"] for l in listings if l.get("subdivExitPsf")])
        nc_comparable = [l.get("newconPpsf") for l in listings if l.get("subdivExitPsf") and l.get("newconPpsf")]
        print(f"   Subdiv $/SF: median ${sv[len(sv)//2]:,}")
        if nc_comparable:
            nc_comparable.sort()
            print(f"   vs New-con $/SF (where both exist): median ${nc_comparable[len(nc_comparable)//2]:,}")
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

rental_comp_count = 0
if os.path.exists(RENTAL_COMPS_FILE):
    print(f"\n🏠 Step 4d: Loading rental comps from {RENTAL_COMPS_FILE}...")
    with open(RENTAL_COMPS_FILE, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
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

# 4d-c: 5-tier rental estimate function
SFR_TH_TYPES = {"Single Family Residential", "Townhouse", "Condo/Co-op", "Multi-Family (2-4 Unit)"}

def find_rental_estimate(lat, lng, zipcode, safmr_3br):
    """Find best rental estimate using 5-tier priority.

    Returns: (est_rent, method, comp_count, radius_mi, median_beds)
    """
    grow = math.floor(lat / RENTAL_GRID_SIZE)
    gcol = math.floor(lng / RENTAL_GRID_SIZE)

    def p75(vals):
        vals.sort()
        return round(vals[int(len(vals) * 0.75)])

    def median_val(vals):
        vals.sort()
        return vals[len(vals) // 2]

    def collect_comps(radius, min_beds, min_sqft, types_filter):
        """Collect rental comps within radius matching criteria."""
        cells = int(radius / RENTAL_GRID_SIZE) + 1
        matches = []
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                for clat, clng, rent, beds, sqft, ptype in rental_grid.get((grow + dr, gcol + dc), []):
                    if abs(clat - lat) > radius or abs(clng - lng) > radius:
                        continue
                    if beds < min_beds:
                        continue
                    if min_sqft > 0 and sqft > 0 and sqft < min_sqft:
                        continue
                    if types_filter and ptype not in types_filter:
                        continue
                    matches.append((rent, beds))
        return matches

    # Tier 1: rental-comp — 0.5mi→1mi, 3+ BR, 1200+ SF, SFR/TH/Condo/MF2-4
    for radius in [0.007, 0.015]:
        comps = collect_comps(radius, 3, 1200, SFR_TH_TYPES)
        if len(comps) >= 3:
            rents = [r for r, _ in comps]
            beds_list = [b for _, b in comps]
            miles = round(radius * 69, 2)
            return p75(rents), "rental-comp", len(comps), miles, median_val(beds_list)

    # Tier 2: rental-comp-wide — 2mi, 3+ BR, 1200+ SF, SFR/TH/Condo/MF2-4
    comps = collect_comps(0.029, 3, 1200, SFR_TH_TYPES)
    if len(comps) >= 3:
        rents = [r for r, _ in comps]
        beds_list = [b for _, b in comps]
        return p75(rents), "rental-comp-wide", len(comps), round(0.029 * 69, 2), median_val(beds_list)

    # Tier 3: rental-adj — 1mi, 2+ BR, 900+ SF, ALL types, adj for 2BR
    comps = collect_comps(0.015, 2, 900, None)
    if len(comps) >= 3:
        rents = [r for r, _ in comps]
        beds_list = [b for _, b in comps]
        med_beds = median_val(list(beds_list))
        rent_p75 = p75(rents)
        # If median beds is 2, adjust up 20% to approximate 3BR
        if med_beds < 3:
            rent_p75 = round(rent_p75 * 1.20)
        return rent_p75, "rental-adj", len(comps), round(0.015 * 69, 2), med_beds

    # Tier 4: ZORI zip-level × 1.40 premium (new-con townhomes = ~40% above median rent)
    if zipcode in zori_by_zip:
        zori_rent = round(zori_by_zip[zipcode] * 1.40)
        return zori_rent, "zori", 0, 0, 0

    # Tier 5: SAFMR fallback — fmr3br × 1.25
    if safmr_3br and safmr_3br > 0:
        safmr_rent = round(safmr_3br * 1.25)
        return safmr_rent, "safmr", 0, 0, 0

    return 0, "none", 0, 0, 0

# 4d-d: Stamp rental estimates per listing
if rental_comp_count > 0 or zori_by_zip:
    print(f"\n   Computing 5-tier rental estimates...")
    t0 = time.time()
    tier_counts = {"rental-comp": 0, "rental-comp-wide": 0, "rental-adj": 0, "zori": 0, "safmr": 0, "none": 0}
    tier_rents = {"rental-comp": [], "rental-comp-wide": [], "rental-adj": [], "zori": [], "safmr": []}

    for i, l in enumerate(listings):
        safmr = l.get("fmr3br") or 0
        est_rent, method, comp_count, radius_mi, med_beds = find_rental_estimate(
            l["lat"], l["lng"], l.get("zip", ""), safmr
        )
        if est_rent > 0:
            l["estRentMonth"] = est_rent  # Override Step 4c SAFMR-based value
        l["rentMethod"] = method
        l["rentCompCount"] = comp_count
        l["rentCompRadius"] = radius_mi
        l["rentCompMedianBeds"] = med_beds
        tier_counts[method] += 1
        if method in tier_rents and est_rent > 0:
            tier_rents[method].append(est_rent)

        if (i + 1) % 5000 == 0:
            elapsed = time.time() - t0
            print(f"   {i+1:,}/{len(listings):,} ({elapsed:.1f}s)")

    elapsed = time.time() - t0

    # 4d-e: Summary
    print(f"\n   Rental estimate tiers (done in {elapsed:.1f}s):")
    total = len(listings)
    spatial_count = tier_counts["rental-comp"] + tier_counts["rental-comp-wide"] + tier_counts["rental-adj"]
    for method in ["rental-comp", "rental-comp-wide", "rental-adj", "zori", "safmr", "none"]:
        cnt = tier_counts[method]
        pct = cnt / total * 100 if total else 0
        med_str = ""
        if tier_rents.get(method):
            vals = sorted(tier_rents[method])
            med_str = f" (median ${vals[len(vals)//2]:,}/mo)"
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
        l["rentCompCount"] = 0
        l["rentCompRadius"] = 0
        l["rentCompMedianBeds"] = 0

# ── Step 5: Stamp lot slope from slopes.json ──
SLOPE_FILE = market_file("slopes.json", market)
if os.path.exists(SLOPE_FILE):
    print(f"\n⛰️  Step 5: Stamping lot slopes...")
    with open(SLOPE_FILE) as f:
        slope_data = json.load(f)
    print(f"   Loaded {len(slope_data):,} slope records")

    stamped = 0
    for l in listings:
        key = f"{l['lat']},{l['lng']}"
        if key in slope_data:
            l["slope"] = slope_data[key]
            stamped += 1

    slopes_list = [l["slope"] for l in listings if "slope" in l]
    if slopes_list:
        flat = sum(1 for s in slopes_list if s < 5)
        mild = sum(1 for s in slopes_list if 5 <= s < 15)
        moderate = sum(1 for s in slopes_list if 15 <= s < 25)
        steep = sum(1 for s in slopes_list if s >= 25)
        print(f"   Stamped: {stamped:,}/{len(listings):,}")
        print(f"   Flat (<5%): {flat:,} | Mild (5-15%): {mild:,} | Moderate (15-25%): {moderate:,} | Steep (25%+): {steep:,}")
else:
    print(f"\n⚠️  {SLOPE_FILE} not found — run: python3 fetch_slopes.py")

print("\n📊 Summary:")
zone_counts = {}
for l in listings:
    z = l["zone"] or "Unknown"
    zone_counts[z] = zone_counts.get(z, 0) + 1
for z in ["R1", "R2", "R3", "R4", "LAND", "Unknown"]:
    if z in zone_counts:
        print(f"   {z}: {zone_counts[z]} listings")

with_exit = sum(1 for l in listings if l.get("exitPsf"))
with_lot = sum(1 for l in listings if l["lotSf"])
print(f"   With exit $/SF (P75): {with_exit}/{len(listings)}")
print(f"   With lot size: {with_lot}/{len(listings)}")

# Show zone-specific exit $/SF samples
if with_exit:
    print(f"\n   Zone-specific exit $/SF (P75):")
    for z in ["R1", "R2", "R3", "R4"]:
        zone_exits = [l["exitPsf"] for l in listings if l["zone"] == z and l.get("exitPsf")]
        if zone_exits:
            zone_exits.sort()
            med = zone_exits[len(zone_exits)//2]
            p10 = zone_exits[len(zone_exits)//10] if len(zone_exits) >= 10 else zone_exits[0]
            p90 = zone_exits[int(len(zone_exits)*0.9)] if len(zone_exits) >= 10 else zone_exits[-1]
            print(f"     {z}: P75=${med}/sf (P10=${p10}, P90=${p90}, n={len(zone_exits)})")

# ── Write listings.js ──
output_file = market_file("listings.js", market)
build_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
js = f"const LISTINGS_META = {{builtAt:\"{build_ts}\",count:{len(listings)}}};\n"
js += "const LOADED_LISTINGS = " + json.dumps(listings, separators=(",", ":")) + ";"
with open(output_file, "w") as f:
    f.write(js)
size_kb = len(js) / 1024
print(f"\n📦 Created {output_file} ({size_kb:.1f} KB, {len(listings)} listings)")
print("   Done! ✅\n")

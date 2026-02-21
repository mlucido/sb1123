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
import csv, json, re, os, glob, statistics, time, math
from datetime import datetime, timezone

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── LA County bounding box ──
LA_LAT_MIN, LA_LAT_MAX = 33.70, 34.85
LA_LNG_MIN, LA_LNG_MAX = -118.95, -117.55

# ── Property-type → approximate zone mapping ──
TYPE_TO_ZONE = {
    "Single Family Residential": "R1",
    "Townhouse":                 "R2",
    "Condo/Co-op":               "R2",
    "Multi-Family (2-4 Unit)":   "R3",
    "Multi-Family (5+ Unit)":    "R4",
    "Mobile/Manufactured Home":  "R1",
    "Ranch":                     "R1",
    "Vacant Land":               "LAND",
    "Other":                     "LAND",
}

# ── Spatial comp index config ──
GRID_SIZE = 0.01          # ~0.7 miles per cell
MIN_COMPS = 5             # Minimum comps needed for a reliable median
DEG_PER_MILE = 1 / 69.0  # Approximate degrees latitude per mile
# Expanding search radii in degrees (~miles): 0.25mi, 0.5mi, 1mi, 2mi, 4mi
SEARCH_RADII_DEG = [0.004, 0.007, 0.015, 0.029, 0.058]

# ── Step 1: Load comps and build spatial index ──
print("\n🏘️  Step 1: Loading comps + building spatial index...")
comps = []

if os.path.exists("data.js"):
    with open("data.js", "r") as f:
        raw = f.read()
    match = re.search(r"=\s*(\[.*\])\s*;?\s*$", raw, re.DOTALL)
    if match:
        comps = json.loads(match.group(1))
        print(f"   Loaded {len(comps):,} sold comps")
    else:
        print("   ⚠️  Could not parse data.js — neighborhood $/SF will be unavailable")
else:
    print("   ⚠️  data.js not found — neighborhood $/SF will be unavailable")

# Build spatial grid: zone-specific and all-zone indexes
# Key: (grid_row, grid_col) → list of (lat, lng, ppsf)
zone_grid = {}   # { zone: { (row,col): [(lat,lng,ppsf), ...] } }
all_grid = {}    # { (row,col): [(lat,lng,ppsf), ...] }
newcon_zone_grid = {} # New/remodeled construction (year_built >= 2015) — zone-specific
# Zip-level fallback: { (zip, zone): [ppsf], zip: [ppsf] }
zip_zone_ppsfs = {}
zip_all_ppsfs = {}
newcon_count = 0

for c in comps:
    clat = c.get("lat", 0)
    clng = c.get("lng", 0)
    czone = c.get("zone", "")
    cppsf = c.get("ppsf") or (round(c["price"] / c["sqft"]) if c.get("sqft", 0) > 0 else 0)
    czip = c.get("zip", "")
    if cppsf <= 0 or clat == 0 or clng == 0:
        continue

    # Grid cell
    grow = math.floor(clat / GRID_SIZE)
    gcol = math.floor(clng / GRID_SIZE)
    entry = (clat, clng, cppsf)

    # Zone-specific grid
    if czone:
        if czone not in zone_grid:
            zone_grid[czone] = {}
        zone_grid[czone].setdefault((grow, gcol), []).append(entry)

    # All-zone grid
    all_grid.setdefault((grow, gcol), []).append(entry)

    # New/remodeled construction grid (year_built >= 2015) — zone-specific
    yb = c.get("yb")
    if yb and yb >= 2015 and czone:
        if czone not in newcon_zone_grid:
            newcon_zone_grid[czone] = {}
        newcon_zone_grid[czone].setdefault((grow, gcol), []).append(entry)
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
print(f"   New/remodeled (2015+): {newcon_count:,} comps in {newcon_cells:,} cells")
for z in ["R1", "R2", "R3", "R4"]:
    if z in newcon_zone_counts:
        print(f"     {z}: {newcon_zone_counts[z]:,} new-con comps")
print(f"   Zip+zone fallbacks: {len(zip_zone_ppsfs)} combos")


def find_exit_ppsf(lat, lng, zone, zipcode):
    """Find zone-matched exit $/SF (P75) using radius-based search.

    Uses 75th percentile — new-construction townhomes with roof decks
    compete with the top quartile of neighborhood sales.

    Priority:
      1. Same-zone comps within expanding radius (hyperlocal)
      2. All-zone comps within expanding radius (if <MIN_COMPS same-zone)
      3. Same zip + same zone P75 (fallback)
      4. Same zip all-zone P75 (last resort)
    """
    grow = math.floor(lat / GRID_SIZE)
    gcol = math.floor(lng / GRID_SIZE)

    def p75(vals):
        vals.sort()
        return round(vals[int(len(vals) * 0.75)])

    # Try same-zone spatial search at expanding radii
    zg = zone_grid.get(zone, {})
    if zg:
        for radius in SEARCH_RADII_DEG:
            cells = int(radius / GRID_SIZE) + 1
            nearby = []
            for dr in range(-cells, cells + 1):
                for dc in range(-cells, cells + 1):
                    for clat, clng, cppsf in zg.get((grow + dr, gcol + dc), []):
                        if abs(clat - lat) <= radius and abs(clng - lng) <= radius:
                            nearby.append(cppsf)
            if len(nearby) >= MIN_COMPS:
                miles = round(radius * 69, 2)
                return p75(nearby), len(nearby), miles, "zone"

    # Fallback: all-zone spatial search at expanding radii
    for radius in SEARCH_RADII_DEG:
        cells = int(radius / GRID_SIZE) + 1
        nearby = []
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                for clat, clng, cppsf in all_grid.get((grow + dr, gcol + dc), []):
                    if abs(clat - lat) <= radius and abs(clng - lng) <= radius:
                        nearby.append(cppsf)
        if len(nearby) >= MIN_COMPS:
            miles = round(radius * 69, 2)
            return p75(nearby), len(nearby), miles, "all"

    # Fallback: zip + same zone
    zz_key = (zipcode, zone)
    if zz_key in zip_zone_ppsfs and len(zip_zone_ppsfs[zz_key]) >= 3:
        vals = list(zip_zone_ppsfs[zz_key])
        return p75(vals), len(vals), 0, "zip+zone"

    # Last resort: zip all-zone
    if zipcode in zip_all_ppsfs:
        vals = list(zip_all_ppsfs[zipcode])
        return p75(vals), len(vals), 0, "zip"

    return 0, 0, 0, "none"


def find_newcon_ppsf(lat, lng, zone):
    """Find zone-matched new/remodeled (2015+) median $/SF.
    Returns median or None if fewer than MIN_COMPS comps found."""
    zg = newcon_zone_grid.get(zone, {})
    if not zg:
        return None
    grow = math.floor(lat / GRID_SIZE)
    gcol = math.floor(lng / GRID_SIZE)
    # Use wider radii since new construction is sparser
    for radius in [0.007, 0.015, 0.029, 0.058, 0.087]:
        cells = int(radius / GRID_SIZE) + 1
        nearby = []
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                for clat, clng, cppsf in zg.get((grow + dr, gcol + dc), []):
                    if abs(clat - lat) <= radius and abs(clng - lng) <= radius:
                        nearby.append(cppsf)
        if len(nearby) >= MIN_COMPS:
            return round(statistics.median(nearby))
    return None


# ── Step 2: Find and read Redfin CSV ──
print("\n📄 Step 2: Reading Redfin listings CSV...")
redfin_csvs = glob.glob("redfin_merged.csv") or glob.glob("redfin_*.csv")
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

            # Filter to LA County
            if not (LA_LAT_MIN <= lat <= LA_LAT_MAX and LA_LNG_MIN <= lng <= LA_LNG_MAX):
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
            })
        except Exception as e:
            skipped_data += 1
            continue

print(f"   Total rows: {total}")
print(f"   ✅ LA County listings: {len(listings)}")
print(f"   ⚠️  Outside LA County: {skipped_location}")
print(f"   ⚠️  Bad/missing data: {skipped_data}")

if len(listings) == 0:
    print("\n❌ No listings matched. Check the CSV.")
    exit(1)

# ── Step 2.5: Stamp parcel data from parcels.json ──
PARCEL_FILE = "parcels.json"
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
ZONING_FILE = "zoning.json"
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

# ── Step 3: Fire zone check (fallback for listings not stamped from parcels.json) ──
FIRE_ZONE_FILE = "fire_zones_vhfhsz.geojson"
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

# ── Step 4: Zone-matched spatial exit $/SF (P75) ──
if comps:
    print(f"\n📍 Step 4: Computing zone-matched exit $/SF (P75)...")
    t0 = time.time()
    method_counts = {"zone": 0, "all": 0, "zip+zone": 0, "zip": 0, "none": 0}
    radius_sum = 0
    comp_count_sum = 0

    for i, l in enumerate(listings):
        exit_ppsf, n_comps, radius_mi, method = find_exit_ppsf(
            l["lat"], l["lng"], l["zone"], l["zip"]
        )
        l["exitPsf"] = exit_ppsf if exit_ppsf > 0 else None
        method_counts[method] += 1
        if method in ("zone", "all"):
            radius_sum += radius_mi
            comp_count_sum += n_comps

        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            print(f"   {i+1:,}/{len(listings):,} ({elapsed:.1f}s)")

    elapsed = time.time() - t0
    spatial_hits = method_counts["zone"] + method_counts["all"]
    avg_radius = (radius_sum / spatial_hits) if spatial_hits else 0
    avg_comps = (comp_count_sum / spatial_hits) if spatial_hits else 0

    print(f"   Done in {elapsed:.1f}s")
    print(f"   Method breakdown:")
    print(f"     Zone-matched spatial: {method_counts['zone']:,} ({method_counts['zone']/len(listings)*100:.1f}%)")
    print(f"     All-zone spatial:     {method_counts['all']:,} ({method_counts['all']/len(listings)*100:.1f}%)")
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
    print(f"\n🏗️  Step 4b: Computing zone-matched new/remodeled $/SF (2015+ built)...")
    nc_found = 0
    for l in listings:
        nc = find_newcon_ppsf(l["lat"], l["lng"], l["zone"])
        if nc:
            l["newconPpsf"] = nc
            nc_found += 1
        else:
            l["newconPpsf"] = None
    print(f"   Found new-con comps for {nc_found:,}/{len(listings):,} listings")
    nc_vals = [l["newconPpsf"] for l in listings if l.get("newconPpsf")]
    if nc_vals:
        nc_vals.sort()
        print(f"   New-con $/SF: median ${nc_vals[len(nc_vals)//2]}, P10=${nc_vals[len(nc_vals)//10]}, P90=${nc_vals[int(len(nc_vals)*0.9)]}")
else:
    print(f"\n⚠️  No new-construction comps — add 'yb' field to data.js (run build_comps.py)")
    for l in listings:
        l["newconPpsf"] = None

# ── Step 5: Stamp lot slope from slopes.json ──
SLOPE_FILE = "slopes.json"
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
build_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
js = f"const LISTINGS_META = {{builtAt:\"{build_ts}\",count:{len(listings)}}};\n"
js += "const LOADED_LISTINGS = " + json.dumps(listings, separators=(",", ":")) + ";"
with open("listings.js", "w") as f:
    f.write(js)
size_kb = len(js) / 1024
print(f"\n📦 Created listings.js ({size_kb:.1f} KB, {len(listings)} listings)")
print("   Done! ✅\n")

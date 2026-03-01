#!/usr/bin/env python3
"""
add_btr_layer.py (v3)
Adds BTR (Build-to-Rent) opportunity fields to listings.js

Uses three-scenario rent estimation:
  - Conservative: ZORI raw (all-types median, no adjustment)
  - Base:         ZORI × new-construction premium factor
  - Aggressive:   ZORI × premium factor × 1.10

Flags parcels where: hood $/SF < $650 (for-sale doesn't work)
                 AND base YoC >= 4% (rental hold does work)
"""
import csv, json, re, os
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market

# ── BTR Configuration ──
BTR_CONFIG = {
    "MIN_SALE_PPSF": 650,        # Below this → not a for-sale candidate
    "TARGET_YOC": 0.04,          # 4% minimum base-case yield on cost
    "TARGET_UNIT_SQFT": 1750,    # Townhome unit size
    "UNITS_PER_PROJECT": 10,     # SB 1123 max density
    "CONSTRUCTION_PPSF": 350,    # Hard cost $/SF
    "SOFT_COST_MULT": 0.15,      # Soft costs as % of hard costs
    "VACANCY_RATE": 0.05,        # 5% vacancy
    "OPEX_RATIO": 0.30,          # 30% of EGI (NOI = 70% of EGI)
    "CAP_RATE": 0.05,            # For stabilized value calc
    # Geographic focus: Lower San Fernando Valley + adjacent areas
    "LAT_MIN": 33.95,
    "LAT_MAX": 34.25,
    "LNG_MIN": -118.65,
    "LNG_MAX": -118.05,
}

# ── New Construction Premium Factors ──
# Loaded from market_config.py; fallback to hardcoded defaults
_market = get_market()
NEWCON_PREMIUM = _market.get("btr_premium_factors", {"_default": {"factor": 1.25, "confidence": "default"}})

def get_premium(zip_code):
    """Return (factor, confidence) for a ZIP code."""
    entry = NEWCON_PREMIUM.get(str(zip_code), NEWCON_PREMIUM['_default'])
    return entry['factor'], entry['confidence']


def calc_scenario_noi(rent, units, vacancy_rate, opex_ratio):
    """Calculate NOI for a given rent level."""
    gross = rent * units * 12
    vacancy = gross * vacancy_rate
    egi = gross - vacancy
    opex = egi * opex_ratio
    noi = egi - opex
    return noi


def calc_btr_scenarios(zori_rent, zip_code, total_project_cost, units=10):
    """Calculate three-scenario BTR metrics."""
    premium_factor, confidence = get_premium(zip_code)
    vac = BTR_CONFIG['VACANCY_RATE']
    opex = BTR_CONFIG['OPEX_RATIO']

    scenarios = {}
    for label, rent in [
        ('conservative', zori_rent * 1.0),
        ('base', zori_rent * premium_factor),
        ('aggressive', zori_rent * premium_factor * 1.10),
    ]:
        noi = calc_scenario_noi(rent, units, vac, opex)
        yoc = noi / total_project_cost if total_project_cost > 0 else 0
        scenarios[label] = {
            'rent': round(rent),
            'noi': round(noi),
            'yoc': round(yoc, 4),
        }

    return scenarios, premium_factor, confidence


def calc_neighborhood_scenarios(base_rent, median_rent, total_project_cost, units=10):
    """Calculate three scenarios from manual neighborhood rent data.

    neighborhood_rents.json has:
      base_rent   = existing stock median (no premium)
      median_rent = base_rent × 1.15 (15% new-con premium)
    """
    vac = BTR_CONFIG['VACANCY_RATE']
    opex = BTR_CONFIG['OPEX_RATIO']

    scenarios = {}
    for label, rent in [
        ('conservative', base_rent),
        ('base', median_rent),
        ('aggressive', median_rent * 1.10),
    ]:
        noi = calc_scenario_noi(rent, units, vac, opex)
        yoc = noi / total_project_cost if total_project_cost > 0 else 0
        scenarios[label] = {
            'rent': round(rent),
            'noi': round(noi),
            'yoc': round(yoc, 4),
        }

    return scenarios


print("\n\U0001f3d7\ufe0f  BTR Layer Calculator v3 — Three-Scenario Premium Factor System")
print(f"   Config: ${BTR_CONFIG['MIN_SALE_PPSF']}/SF for-sale threshold, {BTR_CONFIG['TARGET_YOC']*100}% min base YoC")

# ── Step 1: Load rent data sources ──
print("\n\U0001f4ca Step 1: Loading rent data sources...")

# 1a: Neighborhood-level manual rent data
with open('neighborhood_rents.json') as f:
    rent_data = json.load(f)
neighborhoods = rent_data['neighborhoods']
print(f"   Neighborhood manual rents: {len(neighborhoods)} neighborhoods")

# 1b: ZORI ZIP-level data
zori_by_zip = {}
if os.path.exists('zori_data.csv'):
    with open('zori_data.csv') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        date_columns = [col for col in headers if re.match(r'\d{4}-\d{2}-\d{2}', col)]
        most_recent_month = sorted(date_columns)[-1]

        for row in reader:
            if row['State'] != 'CA':
                continue
            zip_code = row['RegionName']
            rent = row.get(most_recent_month, '')
            if rent and rent.strip():
                try:
                    zori_by_zip[zip_code] = float(rent)
                except ValueError:
                    pass
    print(f"   ZORI data: {len(zori_by_zip)} CA ZIPs (latest: {most_recent_month})")

# 1c: SAFMR (HUD Small Area Fair Market Rents) from rents.json
safmr_by_zip = {}
if os.path.exists('rents.json'):
    with open('rents.json') as f:
        safmr_data = json.load(f)
    for z, v in safmr_data.items():
        if 'fmr3br' in v:
            safmr_by_zip[z] = v['fmr3br']
    print(f"   SAFMR data: {len(safmr_by_zip)} ZIPs with 3BR FMR")

# ── Step 2: Load current listings.js ──
print("\n\U0001f4c2 Step 2: Loading listings.js...")
with open('listings.js') as f:
    raw = f.read()

m = re.search(r'LOADED_LISTINGS\s*=\s*(\[.*\])', raw, re.DOTALL)
if not m:
    print("\u274c Could not parse listings.js")
    exit(1)

listings = json.loads(m.group(1))
print(f"   Loaded {len(listings):,} listings")

# ── Step 3: Calculate BTR metrics with three-scenario system ──
print("\n\U0001f9ee Step 3: Calculating three-scenario BTR metrics...")
btr_eligible_count = 0
btr_manual_count = 0
btr_zori_count = 0
for_sale_count = 0
no_rent_data_count = 0
confidence_counts = {'validated': 0, 'estimated': 0, 'default': 0, 'manual': 0}

for l in listings:
    city = l.get('city', '').strip()
    lat = l.get('lat', 0)
    lng = l.get('lng', 0)
    hood_ppsf = l.get('hoodPpsf') or l.get('ppsf') or 0
    lot_sf = l.get('lotSf') or 0
    price = l.get('price') or 0
    zip_code = l.get('zip', '').strip()

    # Default: not BTR eligible
    l['btr'] = False

    # Geographic filter
    if not (BTR_CONFIG['LAT_MIN'] <= lat <= BTR_CONFIG['LAT_MAX'] and
            BTR_CONFIG['LNG_MIN'] <= lng <= BTR_CONFIG['LNG_MAX']):
        continue

    # Buildability filters
    if lot_sf < 12000:
        continue

    slope = l.get('slope')
    if slope is not None and slope > 10:
        continue

    fire_zone = l.get('fireZone', False)
    if fire_zone:
        continue

    # Check 1: If for-sale pencils, skip BTR
    if hood_ppsf >= BTR_CONFIG['MIN_SALE_PPSF']:
        for_sale_count += 1
        continue

    # Calculate total project cost
    land_cost = price if price > 0 else (hood_ppsf * lot_sf) if lot_sf > 0 else 0
    construction_cost = BTR_CONFIG['TARGET_UNIT_SQFT'] * BTR_CONFIG['UNITS_PER_PROJECT'] * BTR_CONFIG['CONSTRUCTION_PPSF']
    soft_costs = construction_cost * BTR_CONFIG['SOFT_COST_MULT']
    total_project_cost = land_cost + construction_cost + soft_costs

    # Check 2: Get rent estimates (prefer manual data, fallback to ZORI)
    scenarios = None
    rent_source = None
    premium_factor = None
    confidence = None
    zori_base = None

    if city in neighborhoods:
        # Manual neighborhood data — already has new-con premium baked in
        nh = neighborhoods[city]
        median_rent = nh['median_rent']
        base_rent = nh.get('base_rent', round(median_rent / 1.15))
        scenarios = calc_neighborhood_scenarios(base_rent, median_rent, total_project_cost)
        rent_source = 'manual'
        confidence = 'manual'
        # Try to get ZORI for this ZIP for display
        zori_base = round(zori_by_zip[zip_code]) if zip_code in zori_by_zip else None
    elif zip_code in zori_by_zip:
        # ZORI-based with premium factor system
        zori_rent = zori_by_zip[zip_code]
        zori_base = round(zori_rent)
        scenarios, premium_factor, confidence = calc_btr_scenarios(
            zori_rent, zip_code, total_project_cost
        )
        rent_source = 'zori'

    if not scenarios:
        no_rent_data_count += 1
        continue

    # Get SAFMR for this ZIP (display only)
    safmr_3br = safmr_by_zip.get(zip_code)

    # BTR eligibility: base-case YoC >= threshold
    yoc_base = scenarios['base']['yoc']
    if yoc_base >= BTR_CONFIG['TARGET_YOC']:
        l['btr'] = True

        # Three-scenario fields
        l['rentConservative'] = scenarios['conservative']['rent']
        l['rentBase'] = scenarios['base']['rent']
        l['rentAggressive'] = scenarios['aggressive']['rent']

        l['noiConservative'] = scenarios['conservative']['noi']
        l['noiBase'] = scenarios['base']['noi']
        l['noiAggressive'] = scenarios['aggressive']['noi']

        l['yocConservative'] = scenarios['conservative']['yoc']
        l['yocBase'] = scenarios['base']['yoc']
        l['yocAggressive'] = scenarios['aggressive']['yoc']

        # Transparency / data quality
        l['zoriBase'] = zori_base
        l['premiumFactor'] = premium_factor
        l['confidence'] = confidence
        l['safmr3br'] = safmr_3br

        # Legacy backward-compat fields (mapped to base case)
        l['estRent'] = scenarios['base']['rent']
        l['yoc'] = scenarios['base']['yoc']
        l['noi'] = scenarios['base']['noi']
        l['stabilizedValue'] = round(scenarios['base']['noi'] / BTR_CONFIG['CAP_RATE'])
        l['salePpsfGap'] = round(hood_ppsf - BTR_CONFIG['MIN_SALE_PPSF'])
        l['rentSource'] = rent_source

        btr_eligible_count += 1
        confidence_counts[confidence] += 1
        if rent_source == 'manual':
            btr_manual_count += 1
        else:
            btr_zori_count += 1

print(f"\n\u2705 Results:")
print(f"   For-sale eligible (\u2265${BTR_CONFIG['MIN_SALE_PPSF']}/SF): {for_sale_count:,}")
print(f"   BTR eligible (<${BTR_CONFIG['MIN_SALE_PPSF']}/SF, \u2265{BTR_CONFIG['TARGET_YOC']*100}% base YoC): {btr_eligible_count:,}")
print(f"   \u251c\u2500 Manual neighborhood rent data: {btr_manual_count:,}")
print(f"   \u2514\u2500 ZORI + premium factor: {btr_zori_count:,}")
print(f"   Confidence breakdown:")
for conf, cnt in sorted(confidence_counts.items()):
    if cnt > 0:
        print(f"     {conf:12s}: {cnt:,}")
print(f"   No rent data available: {no_rent_data_count:,}")

# Show sample BTR deals
btr_deals = [l for l in listings if l.get('btr')]
if btr_deals:
    print(f"\n   Sample BTR deals:")
    for l in sorted(btr_deals, key=lambda x: x.get('yocBase', 0), reverse=True)[:5]:
        addr = l.get('address', 'N/A')[:35]
        yb = l.get('yocBase', 0)
        rb = l.get('rentBase', 0)
        rc = l.get('rentConservative', 0)
        conf = l.get('confidence', '?')
        print(f"     {addr:35s}  YoC={yb*100:.1f}%  Rent=${rb:,}/mo (cons=${rc:,})  [{conf}]")

# ── Step 4: Write updated listings.js ──
print("\n\U0001f4dd Step 4: Writing updated listings.js...")
build_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
meta_line = f'const LISTINGS_META = {{builtAt:"{build_ts}",count:{len(listings)},btrCount:{btr_eligible_count}}};\n'
data_line = "const LOADED_LISTINGS = " + json.dumps(listings, separators=(",", ":")) + ";"
js_output = meta_line + data_line

with open("listings.js", "w") as f:
    f.write(js_output)

size_kb = len(js_output) / 1024
print(f"   Wrote listings.js ({size_kb:.1f} KB, {len(listings):,} listings, {btr_eligible_count:,} BTR)")
print(f"\n\u2705 Done! BTR layer v3 — three-scenario premium factor system.\n")

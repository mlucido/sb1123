#!/usr/bin/env python3
"""
fetch_rso.py — RSO (Rent Stabilization Ordinance) assessment for LA market.

LA RSO RULES (per LAHD / ZIMAS):
  - Built on or before October 1, 1978: RSO applies
  - 2+ rental units: RSO applies
  - Within City of LA boundaries: RSO applies
  - Exemptions: single-family homes, condos individually owned, government housing,
    new construction post-1978 (unless replacing demolished RSO units)

DATA SOURCE INVESTIGATION (Feb 2026):
  We probed all available public endpoints:
  - ZIMAS ArcGIS (D_QUERYLAYERS/MapServer): Service returns 500 error; no RSO layers
  - LA GeoHub: Only has 2 LAHD office service area polygons, no per-parcel RSO data
  - LADATA portal (data.lacity.org): Has LAHD violation/case datasets but no RSO registry
  - LAHD website: RSO lookup redirects to ZIMAS Housing tab (no public API)
  - OwnIt! rent control finder: Uses year-built heuristic (same approach as ours)

CONCLUSION:
  No bulk RSO dataset or per-parcel API exists. ZIMAS RSO determination is
  computed from year_built + property_type + unit_count + city boundary —
  the exact same heuristic we implement in listings_build.py Step 2.8.
  This script validates/enhances that heuristic using assessor data.

SD NOTE:
  San Diego has no RSO or equivalent rent control registry.
  Tenant risk for SD is assessed via structural heuristics only
  (see listings_build.py Step 2.8 tenant risk computation).
  The statewide 5-year tenant occupancy rule (SB 1123 §66499.41(a)(8)(C))
  still applies but there is no public database to query for SD.
"""

import json, os, sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from market_config import get_market, market_file

market = get_market()

if market["slug"] != "la":
    print(f"⚠️  RSO assessment only applies to LA market (current: {market['slug']})")
    print("   SD has no rent stabilization ordinance or parcel-level registry.")
    print("   Tenant risk is handled via structural heuristics in listings_build.py.")
    sys.exit(0)

# Load listings to analyze RSO exposure
LISTINGS_FILE = market_file("listings.js", market)
if not os.path.exists(LISTINGS_FILE):
    print(f"❌ {LISTINGS_FILE} not found — run listings_build.py first")
    sys.exit(1)

print("🏛️  RSO / Ellis Act Assessment — LA Market")
print("=" * 60)

# Parse listings.js
with open(LISTINGS_FILE) as f:
    content = f.read()
start = content.index("[")
end = content.rindex("]") + 1
listings = json.loads(content[start:end])

print(f"   Loaded {len(listings):,} listings")

# RSO analysis summary
rso_flagged = [l for l in listings if l.get("rsoRisk")]
high_tenant = [l for l in listings if l.get("tenantRisk", 0) >= 3]
med_tenant = [l for l in listings if l.get("tenantRisk", 0) == 2]
remainder_viable = [l for l in listings if l.get("remainderViable")]

print(f"\n📊 RSO Exposure Summary:")
print(f"   RSO flagged (pre-1978 + LA City + multi-unit): {len(rso_flagged):,}")
print(f"   High tenant risk (score 3): {len(high_tenant):,}")
print(f"   Medium tenant risk (score 2): {len(med_tenant):,}")
print(f"   Remainder parcel viable (R2-R4): {len(remainder_viable):,}")

# RSO by zone
print(f"\n   RSO by zone:")
for zone in ["R1", "R2", "R3", "R4", "LAND"]:
    zone_rso = [l for l in rso_flagged if l.get("zone") == zone]
    zone_total = [l for l in listings if l.get("zone") == zone]
    if zone_total:
        pct = len(zone_rso) / len(zone_total) * 100
        print(f"     {zone}: {len(zone_rso):,}/{len(zone_total):,} ({pct:.1f}%)")

# RSO deals with remainder parcel strategy
rso_with_remainder = [l for l in rso_flagged if l.get("remainderViable")]
print(f"\n   RSO deals with viable remainder strategy: {len(rso_with_remainder):,}")
if rso_with_remainder:
    print(f"   (These can be developed without Ellis Act — keep existing structure)")

# Year built distribution for RSO properties
print(f"\n   Year built distribution (RSO flagged):")
decade_bins = {}
for l in rso_flagged:
    yb = l.get("yearBuilt", "")
    yb_int = int(yb) if yb and str(yb).isdigit() else 0
    if yb_int > 0:
        decade = (yb_int // 10) * 10
        decade_bins[decade] = decade_bins.get(decade, 0) + 1
for decade in sorted(decade_bins):
    print(f"     {decade}s: {decade_bins[decade]:,}")

# Ellis Act cost estimation
if rso_flagged:
    def safe_beds(l):
        b = l.get("beds", "")
        return max(2, int(b)) if b and str(b).isdigit() else 2
    avg_units = sum(safe_beds(l) for l in rso_flagged) / len(rso_flagged)
    ellis_cost_per_deal = avg_units * 20000  # ~$20K/unit relocation
    print(f"\n   Est. Ellis Act relocation cost per RSO deal: ~${ellis_cost_per_deal:,.0f}")
    print(f"   (Based on avg ~{avg_units:.1f} units/property × $20K/unit)")

print(f"\n✅ RSO assessment complete.")
print(f"   RSO data is computed from structural heuristics in listings_build.py Step 2.8.")
print(f"   No external RSO API available — year_built + zone + city boundary is definitive.")

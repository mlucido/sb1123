#!/usr/bin/env python3
"""
market_config.py
Central configuration for all SB 1123 Deal Finder markets.

Every fetcher script imports from here. Add new markets by adding a new
entry to MARKETS dict + a classify_zoning_*() function.

Usage in scripts:
    from market_config import get_market, CALFIRE_LRA_URL
    market = get_market()  # reads --market CLI arg, defaults to "la"
    print(market["name"], market["bounds"])
"""

import sys, re

# ──────────────────────────────────────────────────────────────────────
# Statewide services (shared across all CA markets)
# ──────────────────────────────────────────────────────────────────────

CALFIRE_LRA_URL = (
    "https://services.gis.ca.gov/arcgis/rest/services/"
    "Environment/Fire_Severity_Zones/MapServer/1/query"
)
USGS_EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
HUD_SAFMR_BASE = "https://www.huduser.gov/hudapi/public/fmr/data/"

# Redfin (same endpoint for all markets, just change bounding box)
REDFIN_GIS_CSV_URL = "https://www.redfin.com/stingray/api/gis-csv"
REDFIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.redfin.com/",
}
REDFIN_NUM_HOMES = 350
REDFIN_DELAY_MIN = 1.5
REDFIN_DELAY_MAX = 2.5

# Property-type → approximate zone mapping (Redfin → SB 1123)
# Used as fallback when real zoning is unavailable
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


# ──────────────────────────────────────────────────────────────────────
# Zoning classification functions (one per jurisdiction)
# ──────────────────────────────────────────────────────────────────────

def classify_zoning_la_city(zoning_code):
    """LA City ZIMAS zoning code → SB 1123 category.
    
    Single-family track: A, RA, RE, RS, R1, RU, RZ, RW1 (≤ 1.5 acres)
    Multi-family track: R2, RD, RW2, R3, RAS3, R4, RAS4, R5, all C zones (≤ 5 acres)
    """
    if not zoning_code:
        return None
    code = re.sub(r'^\[.*?\]', '', zoning_code).strip()
    prefix = code.split("-")[0].upper().strip()

    # SF track
    if prefix.startswith(("A", "RA", "RE", "RS", "R1", "RU", "RZ", "RW1")):
        if prefix.startswith("RW2"):
            return "R2"
        return "R1"

    # MF track
    if prefix.startswith(("R2", "RD")):
        return "R2"
    if prefix.startswith(("R3", "RAS3", "RW2")):
        return "R3"
    if prefix.startswith(("R4", "RAS4", "R5")):
        return "R4"
    if prefix.startswith("C"):
        return "R4"  # Commercial → MF eligible

    if prefix.startswith(("M", "P")):
        return "COMMERCIAL"
    if prefix.startswith("OS"):
        return "OPEN_SPACE"

    return None


def classify_zoning_la_county(zone_code):
    """LA County DRP zoning code → SB 1123 category."""
    if not zone_code:
        return None
    upper = zone_code.strip().upper()
    if upper.startswith(("R-1", "R1", "RA", "RE", "RS")):
        return "R1"
    if upper.startswith(("R-2", "R2")):
        return "R2"
    if upper.startswith(("R-3", "R3")):
        return "R3"
    if upper.startswith(("R-4", "R4", "R-5", "R5")):
        return "R4"
    if upper.startswith(("A", "A1", "A2")):
        return None  # Agricultural
    if upper.startswith(("OS", "O")):
        return None  # Open space
    if upper.startswith("C"):
        return "R4"  # Commercial → MF eligible
    return None


def classify_zoning_sd_city(zone_name):
    """City of San Diego zone code → SB 1123 category.

    SD uses RE (Estate), RS (Single), RX (Small Lot), RM (Multiple), RT (Townhouse).
    Zone format: PREFIX-TIER-NUMBER, e.g. RS-1-7, RM-2-5, CC-3-4
    """
    if not zone_name:
        return None
    prefix = zone_name.split('-')[0].upper() if '-' in zone_name else zone_name.upper()

    # SF Track
    if prefix in ('RE', 'RS', 'RX'):
        return 'R1'

    # MF Track — density tier determines R2/R3/R4
    if prefix == 'RM':
        parts = zone_name.split('-')
        if len(parts) >= 2:
            tier = parts[1]
            if tier == '1':
                return 'R2'  # RM-1-* (1 DU / 2,000-3,000 SF)
            if tier == '2':
                return 'R3'  # RM-2-* (1 DU / 1,000-1,500 SF)
            if tier == '3':
                return 'R4'  # RM-3-* (1 DU / 400-800 SF)
        return 'R2'  # fallback

    if prefix == 'RT':
        return 'R2'  # Residential Townhouse

    # Employment Mixed-Use — MF eligible
    if prefix == 'EMX':
        return 'R4'

    # Commercial zones — MF eligible under SB 1123
    if prefix in ('CN', 'CO', 'CC', 'CR', 'CV'):
        return 'R4'

    # Planned districts (LJPD, OPD, *PD-* patterns)
    if prefix in ('LJPD', 'OPD') or 'PD' in prefix:
        # Try to extract density from suffix: *PD-SF → R1, *PD-MF → R3
        upper_name = zone_name.upper()
        if '-MF' in upper_name or '-RM' in upper_name:
            return 'R3'
        if '-MU' in upper_name or '-MX' in upper_name:
            return 'R4'
        return 'R2'  # Default planned district → R2

    # Ineligible
    if prefix in ('IL', 'IH', 'IS', 'IBT'):  # Industrial
        return None
    if prefix in ('OP', 'OC', 'OF', 'OR'):  # Open Space
        return None
    if prefix == 'AG':  # Agricultural
        return None

    return None


def classify_zoning_sd_county(use_reg):
    """Unincorporated SD County use regulation → SB 1123 category.

    County uses different codes: RS, RR, RV, RE, RC, A70, S80, C30, V-series, etc.
    """
    if not use_reg:
        return None
    upper = use_reg.strip().upper()

    # SF Track
    if upper in ('RS', 'RR', 'RV', 'RE', 'RU'):
        return 'R1'

    # Village residential/mixed — check before general R
    if upper.startswith('RMV'):
        return 'R2'

    # MF Track
    if upper in ('RC', 'RMH'):
        return 'R2'

    # Commercial — MF eligible
    if upper.startswith('C'):
        return 'R4'

    # Village zones — MF eligible
    if upper.startswith('V'):
        return 'R4'

    # Agricultural, open space, industrial — ineligible
    if upper.startswith(('A', 'S', 'M')):
        return None

    return None


# ──────────────────────────────────────────────────────────────────────
# Zoning classification function registry
# ──────────────────────────────────────────────────────────────────────

CLASSIFY_FNS = {
    "classify_zoning_la_city": classify_zoning_la_city,
    "classify_zoning_la_county": classify_zoning_la_county,
    "classify_zoning_sd_city": classify_zoning_sd_city,
    "classify_zoning_sd_county": classify_zoning_sd_county,
}


# ──────────────────────────────────────────────────────────────────────
# Market definitions
# ──────────────────────────────────────────────────────────────────────

MARKETS = {
    "la": {
        "name": "Los Angeles",
        "slug": "la",
        "redfin_market": "socal",
        "county_fips": "037",

        # Bounding box
        "lat_min": 33.70,
        "lat_max": 34.85,
        "lng_min": -118.95,
        "lng_max": -117.55,

        # Tile size for Redfin adaptive tiling
        "tile_lat": 0.12,
        "tile_lng": 0.15,

        # Parcel service
        "parcel_url": (
            "https://public.gis.lacounty.gov/public/rest/services/"
            "LACounty_Cache/LACounty_Parcel/MapServer/0/query"
        ),
        "parcel_query_type": "envelope",  # LA uses small envelope, not point
        "parcel_envelope_offset": 0.00002,
        "parcel_out_fields": "AIN,Roll_LandValue,Roll_ImpValue,SitusAddress,Shape.STArea()",
        "parcel_field_map": {
            "lot_sf": "Shape.STArea()",      # Already in sq ft
            "lot_sf_multiplier": 1,           # No conversion needed
            "ain": "AIN",
            "land_value": "Roll_LandValue",
            "imp_value": "Roll_ImpValue",
            "situs_address": "SitusAddress",
        },

        # Fire zone (legacy LA County endpoint — will migrate to statewide)
        "fire_url": (
            "https://public.gis.lacounty.gov/public/rest/services/"
            "LACounty_Dynamic/Hazards/MapServer/2/query"
        ),
        "fire_field": "HAZ_CLASS",
        "fire_vhfhsz_value": "Very High",

        # Zoning endpoints (tried in order — first hit wins)
        "zoning_endpoints": [
            {
                "name": "City of LA (ZIMAS)",
                "url": (
                    "https://services5.arcgis.com/7nsPwEMP38bSkCjy/"
                    "arcgis/rest/services/Zoning/FeatureServer/15/query"
                ),
                "out_fields": "Zoning,CATEGORY",
                "zone_field": "Zoning",
                "category_field": "CATEGORY",
                "classify_fn": "classify_zoning_la_city",
            },
            {
                "name": "LA County (DRP)",
                "url": (
                    "https://arcgis.lacounty.gov/arcgis/rest/services/"
                    "DRP/Zoning/MapServer/0/query"
                ),
                "out_fields": "*",
                "zone_field": "ZONE_CMPLT",
                "category_field": "CATEGORY",
                "classify_fn": "classify_zoning_la_county",
            },
        ],

        # Market-specific overlays
        "burn_zones": [
            {
                "name": "Palisades",
                "polygon": [
                    (-118.62, 34.05), (-118.62, 34.10),
                    (-118.52, 34.10), (-118.52, 34.05),
                    (-118.62, 34.05),
                ],
            },
            {
                "name": "Eaton",
                "polygon": [
                    (-118.18, 34.16), (-118.18, 34.22),
                    (-118.08, 34.22), (-118.08, 34.16),
                    (-118.18, 34.16),
                ],
            },
        ],

        # Pro forma defaults
        "construction_cost_psf": 350,
        "soft_cost_pct": 0.25,
        "avg_unit_sf": 1200,
        "sale_discount_pct": 0.05,
        "demo_cost": 25000,
    },

    "sd": {
        "name": "San Diego",
        "slug": "sd",
        "redfin_market": "socal",
        "county_fips": "073",

        # Bounding box — full SD County
        "lat_min": 32.53,
        "lat_max": 33.12,
        "lng_min": -117.60,
        "lng_max": -116.08,

        # Tile size
        "tile_lat": 0.12,
        "tile_lng": 0.15,

        # Parcel service — SanGIS county-wide
        "parcel_url": (
            "https://gis-public.sandiegocounty.gov/arcgis/rest/services/"
            "sdep_warehouse/PARCELS_ALL/FeatureServer/0/query"
        ),
        "parcel_query_type": "envelope",
        "parcel_envelope_offset": 0.0003,  # Wider than LA — SD parcels are larger
        "parcel_out_fields": "APN,ACREAGE,ASR_LAND,ASR_IMPR,ASR_TOTAL,TOTAL_LVG_AREA,BEDROOMS,BATHS",
        "parcel_field_map": {
            "lot_sf": "ACREAGE",
            "lot_sf_multiplier": 43560,   # Acres → sq ft
            "ain": "APN",
            "land_value": "ASR_LAND",
            "imp_value": "ASR_IMPR",
            "situs_address": None,         # Not available in this layer
        },

        # Fire zone — use statewide CAL FIRE (same as all new markets)
        "fire_url": None,  # Signals: use CALFIRE_LRA_URL instead
        "fire_field": "HAZ_CLASS",
        "fire_vhfhsz_value": "Very High",

        # Zoning endpoints
        "zoning_endpoints": [
            {
                "name": "City of San Diego (DSD)",
                "url": (
                    "https://webmaps.sandiego.gov/arcgis/rest/services/"
                    "DSD/Zoning_Base/MapServer/0/query"
                ),
                "out_fields": "ZONE_NAME",
                "zone_field": "ZONE_NAME",
                "category_field": None,
                "classify_fn": "classify_zoning_sd_city",
            },
            {
                "name": "SD County (DPW/BASE_LAYERS)",
                "url": (
                    "https://gis-public.sandiegocounty.gov/arcgis/rest/services/"
                    "DPW/BASE_LAYERS/MapServer/24/query"
                ),
                "out_fields": "USEREG",
                "zone_field": "USEREG",
                "category_field": None,
                "classify_fn": "classify_zoning_sd_county",
            },
        ],

        # No market-specific burn zones
        "burn_zones": [],

        # Pro forma defaults (same as LA for now)
        "construction_cost_psf": 350,
        "soft_cost_pct": 0.25,
        "avg_unit_sf": 1200,
        "sale_discount_pct": 0.05,
        "demo_cost": 25000,
    },
}


# ──────────────────────────────────────────────────────────────────────
# Helper: get active market from CLI args
# ──────────────────────────────────────────────────────────────────────

def get_market(default="la"):
    """Parse --market <slug> from sys.argv. Returns market config dict.

    Usage:
        python3 fetch_listings.py --market sd
        python3 fetch_listings.py                # defaults to "la"
    """
    slug = default
    for i, arg in enumerate(sys.argv):
        if arg == "--market" and i + 1 < len(sys.argv):
            slug = sys.argv[i + 1].lower()
            break

    if slug not in MARKETS:
        valid = ", ".join(MARKETS.keys())
        print(f"\n  ❌ Unknown market '{slug}'. Valid markets: {valid}\n")
        sys.exit(1)

    return MARKETS[slug]


def get_market_slug():
    """Return just the market slug string from CLI args."""
    for i, arg in enumerate(sys.argv):
        if arg == "--market" and i + 1 < len(sys.argv):
            return sys.argv[i + 1].lower()
    return "la"


# ──────────────────────────────────────────────────────────────────────
# Helper: market-specific file paths
# ──────────────────────────────────────────────────────────────────────

def market_file(base_name, market=None):
    """Return market-prefixed filename. Single-market = no prefix for backward compat.

    Examples:
        market_file("listings.js", la_market) → "listings.js"         (LA = default, no prefix)
        market_file("listings.js", sd_market) → "sd_listings.js"
        market_file("parcels.json", sd_market) → "sd_parcels.json"
    """
    if market is None:
        market = get_market()
    slug = market["slug"]
    if slug == "la":
        return base_name  # Backward compatible — no prefix for LA
    return f"{slug}_{base_name}"

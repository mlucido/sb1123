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

    # Mixed-use track — must check BEFORE SF track (RAS3/RAS4 startswith "RA")
    if prefix.startswith(("RAS3", "RAS4")):
        return "MU"
    if prefix.startswith("C"):
        return "MU"  # Commercial → MF eligible (mixed-use)

    # SF track
    if prefix.startswith(("A", "RA", "RE", "RS", "R1", "RU", "RZ", "RW1")):
        if prefix.startswith("RW2"):
            return "R2"
        return "R1"

    # MF track
    if prefix.startswith(("R2", "RD")):
        return "R2"
    if prefix.startswith(("R3", "RW2")):
        return "R3"
    if prefix.startswith(("R4", "R5")):
        return "R4"

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
        return "MU"  # Commercial → MF eligible (mixed-use)
    return None


def classify_zoning_santa_monica(zone_code):
    """Santa Monica zoning code → SB 1123 category.

    SM uses R1-R4 plus Ocean Park variants (OP1-OP4, OPD).
    Mixed-use/commercial zones are MF-eligible under SB 1123.
    """
    if not zone_code:
        return None
    upper = zone_code.strip().upper()
    # Direct residential
    if upper == "R1" or upper == "OP1":
        return "R1"
    if upper in ("R2", "OP2", "OPD"):
        return "R2"
    if upper in ("R3", "OP3"):
        return "R3"
    if upper in ("R4", "OP4"):
        return "R4"
    # Mixed-use / commercial → MF eligible
    if upper in ("MUC", "MUB", "MUBL", "HMU", "TA", "BTV", "NV", "GC",
                 "NC", "LT", "WT", "OT", "OC", "OF"):
        return "MU"
    # Non-residential — not SB 1123 eligible
    if upper in ("OS", "PL", "CC", "IC", "RMH", "BC", "CCS", "CAC"):
        return None
    return None


def classify_zoning_lancaster(zone_code):
    """City of Lancaster zoning code → SB 1123 category.

    Lancaster uses R-{lot_size} for SF, MDR/HDR for multifamily.
    """
    if not zone_code:
        return None
    z = zone_code.strip().upper()
    # Single-family residential (all R- variants + rural)
    if z.startswith("R-") or z in ("RR-1", "RR-2.5", "SRR", "MHP", "MHP-S"):
        return "R1"
    if z == "MDR":
        return "R3"
    if z == "HDR":
        return "R4"
    # Commercial / mixed-use → MF eligible
    if z in ("C", "CPD", "MU-C", "MU-E", "MU-N", "OP", "TOD"):
        return "MU"
    return None


def classify_zoning_palmdale(zone_code):
    """City of Palmdale zoning code → SB 1123 category.

    Palmdale uses R-1-{lot_size}, R-2, R-3, R-4 (30/50).
    PZ suffix = prezone, treat same as base zone.
    """
    if not zone_code:
        return None
    z = zone_code.strip().upper()
    if z.endswith(" PZ"):
        z = z[:-3].strip()
    if z.startswith("R-1"):
        return "R1"
    if z == "R-2":
        return "R2"
    if z == "R-3":
        return "R3"
    if z.startswith("R-4"):
        return "R4"
    if z.startswith("A-"):
        return "R1"  # Light agriculture = large-lot SFR
    if z.startswith("C-") or z == "C-D MX":
        return "MU"
    return None


def classify_zoning_malibu(zone_code):
    """City of Malibu zoning code → SB 1123 category.

    Malibu uses RR{acreage} for rural residential, SFL/SFM for single-family,
    MF/MFBF for multi-family.
    """
    if not zone_code:
        return None
    z = zone_code.strip().upper()
    if z.startswith("RR") or z in ("SFL", "SFM", "MH"):
        return "R1"
    if z in ("MF", "MFBF"):
        return "R3"
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
        return 'MU'

    # Commercial zones — MF eligible under SB 1123
    if prefix in ('CN', 'CO', 'CC', 'CR', 'CV'):
        return 'MU'

    # Planned districts (LJPD, OPD, *PD-* patterns)
    if prefix in ('LJPD', 'OPD') or 'PD' in prefix:
        # Try to extract density from suffix: *PD-SF → R1, *PD-MF → R3
        upper_name = zone_name.upper()
        if '-MF' in upper_name or '-RM' in upper_name:
            return 'R3'
        if '-MU' in upper_name or '-MX' in upper_name:
            return 'MU'
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
        return 'MU'

    # Village zones — MF eligible
    if upper.startswith('V'):
        return 'MU'

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
    "classify_zoning_santa_monica": classify_zoning_santa_monica,
    "classify_zoning_lancaster": classify_zoning_lancaster,
    "classify_zoning_palmdale": classify_zoning_palmdale,
    "classify_zoning_malibu": classify_zoning_malibu,
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
        "parcel_out_fields": "AIN,Roll_LandValue,Roll_ImpValue,SitusAddress,Shape.STArea(),Units1,Units2,Units3,Units4,Units5",
        "parcel_field_map": {
            "lot_sf": "Shape.STArea()",      # Already in sq ft
            "lot_sf_multiplier": 1,           # No conversion needed
            "ain": "AIN",
            "land_value": "Roll_LandValue",
            "imp_value": "Roll_ImpValue",
            "situs_address": "SitusAddress",
            "units_fields": ["Units1", "Units2", "Units3", "Units4", "Units5"],
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
                "name": "Santa Monica",
                "url": (
                    "https://gis.santamonica.gov/server/rest/services/"
                    "Zoning/FeatureServer/2/query"
                ),
                "out_fields": "zoning,zonedesc",
                "zone_field": "zoning",
                "category_field": "zonedesc",
                "classify_fn": "classify_zoning_santa_monica",
            },
            {
                "name": "Lancaster",
                "url": (
                    "https://maps.cityoflancasterca.org/server/rest/services/"
                    "Parcel_PopupReference/FeatureServer/8/query"
                ),
                "out_fields": "Zoning,ZoneDesc",
                "zone_field": "Zoning",
                "category_field": "ZoneDesc",
                "classify_fn": "classify_zoning_lancaster",
            },
            {
                "name": "Palmdale",
                "url": (
                    "https://mapserver.cityofpalmdale.org/arcgis/rest/services/"
                    "Planning_Zoning/PlanningZoning/FeatureServer/4/query"
                ),
                "out_fields": "CITY_ZONE,ZONE_NAME",
                "zone_field": "CITY_ZONE",
                "category_field": "ZONE_NAME",
                "classify_fn": "classify_zoning_palmdale",
            },
            {
                "name": "Malibu",
                "url": (
                    "https://services3.arcgis.com/w2LtkSgyOOlg6OKZ/"
                    "arcgis/rest/services/Zoning_Malibu/FeatureServer/0/query"
                ),
                "out_fields": "MALIBUZONE",
                "zone_field": "MALIBUZONE",
                "classify_fn": "classify_zoning_malibu",
            },
            {
                "name": "LA County (DRP)",
                "url": (
                    "https://arcgis.gis.lacounty.gov/arcgis/rest/services/"
                    "DRP/ZNET_Public/MapServer/4/query"
                ),
                "out_fields": "ZONE,Z_CATEGORY,Z_DESC",
                "zone_field": "ZONE",
                "category_field": "Z_CATEGORY",
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
        "construction_cost_psf": 400,
        "soft_cost_pct": 0.25,
        "avg_unit_sf": 1200,
        "sale_discount_pct": 0.05,
        "demo_cost": 25000,

        # RSO (Rent Stabilization Ordinance) — LA specific
        "has_rso": True,
        "rso_eligible_cities": ["los angeles", "la", ""],

        # Sample zips for validation (build_comps.py spot-check)
        "sample_zips": ["91367", "91316", "91356"],

        # BTR new-construction premium factors by ZIP
        "btr_premium_factors": {
            "91367": {"factor": 1.40, "confidence": "validated"},
            "91364": {"factor": 1.35, "confidence": "estimated"},
            "91303": {"factor": 1.30, "confidence": "estimated"},
            "91304": {"factor": 1.30, "confidence": "estimated"},
            "91306": {"factor": 1.25, "confidence": "estimated"},
            "91307": {"factor": 1.35, "confidence": "estimated"},
            "91316": {"factor": 1.45, "confidence": "estimated"},
            "91335": {"factor": 1.25, "confidence": "estimated"},
            "91356": {"factor": 1.35, "confidence": "estimated"},
            "91403": {"factor": 1.40, "confidence": "estimated"},
            "91423": {"factor": 1.40, "confidence": "estimated"},
            "91436": {"factor": 1.50, "confidence": "estimated"},
            "_default": {"factor": 1.25, "confidence": "default"},
        },
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
        "parcel_out_fields": "APN,ACREAGE,ASR_LAND,ASR_IMPR,ASR_TOTAL,TOTAL_LVG_AREA,BEDROOMS,BATHS,UNITQTY",
        "parcel_field_map": {
            "lot_sf": "ACREAGE",
            "lot_sf_multiplier": 43560,   # Acres → sq ft
            "ain": "APN",
            "land_value": "ASR_LAND",
            "imp_value": "ASR_IMPR",
            "situs_address": None,         # Not available in this layer
            "units_fields": ["UNITQTY"],
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
        "construction_cost_psf": 400,
        "soft_cost_pct": 0.25,
        "avg_unit_sf": 1200,
        "sale_discount_pct": 0.05,
        "demo_cost": 25000,

        # RSO — San Diego has no rent stabilization
        "has_rso": False,
        "rso_eligible_cities": [],

        # Sample zips for validation
        "sample_zips": ["92129", "92127", "92130"],

        # BTR premium factors — SD has no local data yet, use defaults
        "btr_premium_factors": {
            "_default": {"factor": 1.25, "confidence": "default"},
        },
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

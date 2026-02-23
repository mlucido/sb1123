# SB 1123 Deal Finder — Market Expansion Rubric + San Diego Implementation Plan

**Author:** Yardsworth Engineering  
**Date:** February 22, 2026  
**Status:** Build Plan — Ready for Execution

---

## Part 1: Reusable Market Expansion Rubric

This rubric defines the 9 data layers required to launch the Deal Finder in any new California market. Each layer is classified as **Portable** (same source, just change bounding box), **State-level** (California-wide source, filter to market), or **Local** (requires market-specific GIS endpoint discovery).

### Data Layer Inventory

| # | Layer | LA Source | Portability | New Market Work |
|---|-------|-----------|-------------|-----------------|
| 1 | **Active Listings** | Redfin gis-csv API | Portable | Change bounding box coordinates |
| 2 | **Sold Comps** | Redfin gis-csv API | Portable | Change bounding box coordinates |
| 3 | **Parcel Data** (lot SF, APN, assessed values) | LA County ArcGIS | Local | Find county assessor/parcel ArcGIS endpoint |
| 4 | **Fire Zones** (VHFHSZ) | LA County ArcGIS Hazards layer | State-level | Use CAL FIRE statewide service |
| 5 | **Zoning Codes** | ZIMAS (City of LA) + LA County DRP | Local | Find city + county zoning ArcGIS endpoints |
| 6 | **Slopes** | USGS EPQS (1m LiDAR) | Portable | No changes needed |
| 7 | **Urban Areas** | Census TIGER/Line 2020 shapefile | Portable | No changes needed |
| 8 | **Rents (SAFMR)** | HUD API by zip code | Portable | No changes needed |
| 9 | **Rents (ZORI)** | Zillow CSV download | Portable | Filter to new metro |

### Checklist: Adding a New Market

#### Step 1: Define Geography
- [ ] Set bounding box (lat_min, lat_max, lng_min, lng_max)
- [ ] Identify jurisdictions within the box (city + unincorporated county)
- [ ] Decide: full county pull vs. targeted sub-areas

#### Step 2: Portable Layers (< 1 hour)
- [ ] Update fetch_listings.py bounding box constants
- [ ] Update fetch_sold_comps.py bounding box constants
- [ ] Verify USGS EPQS coverage in the area
- [ ] Verify TIGER/Line urban area coverage
- [ ] Filter ZORI data to new metro zip codes

#### Step 3: Local Layers — The Real Work (4-8 hours per market)

**3a. Parcel Data Endpoint**
- [ ] Search for [County Name] ArcGIS parcel service REST API
- [ ] Identify endpoint URL and layer ID
- [ ] Test a point query — confirm lot area, APN, assessed values
- [ ] Document field names (they vary by county)
- [ ] Write adapter function or config mapping local fields to standard schema
- [ ] Test rate limits and pagination (MaxRecordCount varies)

**3b. Fire Zone Endpoint**
- [ ] Use CAL FIRE statewide: services.gis.ca.gov/arcgis/rest/services/Environment/Fire_Severity_Zones/MapServer
  - Layer 0: SRA FHSZ (State Responsibility Areas)
  - Layer 1: LRA VHFHSZ (Local Responsibility Areas — SB 1123 exclusion)
  - Layer 3: FRA FHSZ (Federal Responsibility Areas)
- [ ] Test point query — confirm HAZ_CLASS field
- [ ] Fallback: local county fire hazard layer if statewide is slow

**3c. Zoning Code Endpoint**
- [ ] Identify all zoning jurisdictions in the bounding box
- [ ] For each jurisdiction, find the ArcGIS zoning service
- [ ] Document the zone code field name
- [ ] Build classify_zoning() mapping local codes to SB 1123 categories
- [ ] Test with known addresses

**3d. SB 1123 Business Logic Calibration**
- [ ] Unit count formula: Same statewide
- [ ] FAR: Same statewide
- [ ] Construction cost: Configurable per market (default $350/SF)
- [ ] Exit $/SF: Derived from local sold comps
- [ ] Rent assumptions: Derived from ZORI/SAFMR

#### Step 4: Build & Test Pipeline
- [ ] Create market-specific config file
- [ ] Run full pipeline with new config
- [ ] Verify map renders correctly

#### Step 5: Validate
- [ ] Spot-check 10 listings: parcel sizes match public records?
- [ ] Spot-check 10 zoning codes: match official source?
- [ ] Spot-check fire zone boundaries
- [ ] Verify pro forma on 3-5 known deals
- [ ] Test all filters with new data ranges

---

## Part 2: San Diego Implementation Plan

### 2.1 Geographic Scope

Full SD County pull — no pre-filtering by neighborhood.

```
SD_LAT_MIN = 32.53
SD_LAT_MAX = 33.12
SD_LNG_MIN = -117.60
SD_LNG_MAX = -116.08
```

Phase 1 scope: City of San Diego + Unincorporated SD County only. Smaller incorporated cities (La Mesa, El Cajon, Poway, etc.) can be added later.

### 2.2 Portable Layers — Config Changes Only

All portable layers (Redfin listings, Redfin sold comps, USGS slopes, TIGER urban areas, HUD SAFMR, ZORI rents) require only bounding box or zip code filter changes. No code changes.

### 2.3 Local Layers — New Endpoints

#### 2.3a Parcel Data

SD County Parcels (covers all jurisdictions):
```
PARCEL_URL = "https://gis-public.sandiegocounty.gov/arcgis/rest/services/sdep_warehouse/PARCELS_ALL/MapServer/0/query"
```

Key fields: APN, ACREAGE, ASR_LAND, ASR_IMPR, ASR_TOTAL, TOTAL_LVG_AREA, BEDROOMS, BATHS, YEAR_EFFECTIVE, TAXSTAT, OWNEROCC, NUCLEUS_ZONE_CD, NUCLEUS_USE_CD

NOTE: Native CRS is EPSG:2230 (State Plane CA Zone 6, feet). Use inSR=4326&outSR=4326 for queries.

Backup: https://webmaps.sandiego.gov/arcgis/rest/services/Hosted/Civic_SD_Parcels/FeatureServer/0

#### 2.3b Fire Zones — Upgrade to Statewide Service

Switch ALL markets to CAL FIRE statewide:
```
CALFIRE_LRA_URL = "https://services.gis.ca.gov/arcgis/rest/services/Environment/Fire_Severity_Zones/MapServer/1/query"
```
Query Layer 1 (LRA VHFHSZ), check HAZ_CLASS field. This replaces LA County's local hazards layer and works for all CA markets.

#### 2.3c Zoning Codes

City of San Diego:
```
SD_CITY_ZONING_URL = "https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Base/MapServer/0/query"
Field: ZONE_NAME (e.g., RS-1-7, RM-2-5, CC-3-4)
```

Unincorporated SD County:
```
SD_COUNTY_ZONING_URL = "https://gis-public.sandiegocounty.gov/arcgis/rest/services/PPM_PublicAGO/MapServer/[LAYER_ID]/query"
Field: USEREG (e.g., RS, RR, A72)
```

### 2.4 SB 1123 Zoning Classification — San Diego

#### City of San Diego — SF Track (single-family, ≤ 1.5 acres)

| Zone Prefix | Zones | SB 1123 |
|---|---|---|
| RE | RE-1-1, RE-1-2 | R1 equivalent |
| RS | RS-1-1 through RS-1-8 | R1 equivalent |
| RX | RX-1-1, RX-1-2 | R1 equivalent |

#### City of San Diego — MF Track (multi-family, ≤ 5 acres)

| Zone Prefix | Zones | SB 1123 |
|---|---|---|
| RM-1 | RM-1-1, RM-1-2, RM-1-3 | R2 equivalent |
| RM-2 | RM-2-4, RM-2-5, RM-2-6 | R3 equivalent |
| RM-3 | RM-3-7, RM-3-8, RM-3-9 | R4 equivalent |
| RT | RT-1-1 through RT-1-4 | R2 equivalent |
| Commercial | CN, CO, CC, CR, CV prefixes | MF eligible |

#### City of San Diego — Ineligible
IL, IH, IS, IBT (Industrial), OP, OC, OF, OR (Open Space), AG (Agricultural)

#### Unincorporated SD County

| Use Reg | SB 1123 |
|---|---|
| RS, RR, RV, RE | SF Track (R1) |
| RC, RMH | MF Track (R2) |
| C-series, V-series | MF eligible |
| A-series, S-series | Ineligible |

#### classify_zoning() Implementation

```python
def classify_zoning_sd_city(zone_name):
    if not zone_name:
        return (None, None)
    prefix = zone_name.split('-')[0] if '-' in zone_name else zone_name
    
    # SF Track
    if prefix in ('RE', 'RS', 'RX'):
        return ('R1', 'SF')
    
    # MF Track
    if prefix == 'RM':
        parts = zone_name.split('-')
        if len(parts) >= 2:
            tier = parts[1]
            if tier == '1': return ('R2', 'MF')
            if tier == '2': return ('R3', 'MF')
            if tier == '3': return ('R4', 'MF')
        return ('R2', 'MF')
    
    if prefix == 'RT':
        return ('R2', 'MF')
    
    if prefix in ('CN', 'CO', 'CC', 'CR', 'CV'):
        return ('COMMERCIAL', 'MF')
    
    return (None, None)

def classify_zoning_sd_county(use_reg):
    if not use_reg:
        return (None, None)
    if use_reg in ('RS', 'RR', 'RV', 'RE'):
        return ('R1', 'SF')
    if use_reg in ('RC', 'RMH'):
        return ('R2', 'MF')
    if use_reg.startswith('C') or use_reg.startswith('V'):
        return ('COMMERCIAL', 'MF')
    return (None, None)
```

### 2.5 Architecture: Multi-Market Config

Refactor from hardcoded constants to config-driven:

```python
MARKETS = {
    "la": {
        "name": "Los Angeles",
        "bounds": (33.70, 34.85, -118.95, -117.55),
        "parcel_url": "https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query",
        "parcel_fields": {"lot": "Shape.STArea()", "ain": "AIN", "land": "LandValue", "impr": "ImpValue"},
        "zoning": [
            {"name": "LA City", "url": "...ZIMAS...", "field": "ZONE_CMPLT", "fn": "classify_zoning_la_city"},
            {"name": "LA County", "url": "...DRP...", "field": "ZONE_CMPLT", "fn": "classify_zoning_la_county"},
        ]
    },
    "sd": {
        "name": "San Diego",
        "bounds": (32.53, 33.12, -117.60, -116.08),
        "parcel_url": "https://gis-public.sandiegocounty.gov/arcgis/rest/services/sdep_warehouse/PARCELS_ALL/MapServer/0/query",
        "parcel_fields": {"lot": "ACREAGE", "lot_multiplier": 43560, "ain": "APN", "land": "ASR_LAND", "impr": "ASR_IMPR"},
        "zoning": [
            {"name": "SD City", "url": "...DSD/Zoning_Base...", "field": "ZONE_NAME", "fn": "classify_zoning_sd_city"},
            {"name": "SD County", "url": "...PPM_PublicAGO...", "field": "USEREG", "fn": "classify_zoning_sd_county"},
        ]
    }
}
```

### 2.6 Frontend: Separate data files per market, lazy-loaded on market switch.

### 2.7 Implementation Sequence

| Phase | Work | Sessions |
|---|---|---|
| 1. Infrastructure refactor | Extract market config, refactor fire zones to CAL FIRE statewide, test LA still works | 2-3 |
| 2. SD data pipeline | Verify endpoints, implement classify functions, run full pipeline | 2-3 |
| 3. Frontend multi-market | Market selector, lazy loading, per-market defaults | 1-2 |
| 4. Validation | Spot-checks, heatmap calibration | 1 |
| **Total** | | **6-9 sessions** |

### 2.8 Open Questions / Risks

1. SD County parcel endpoint uses EPSG:2230 — verify inSR=4326 projection works
2. SD County zoning layer ID in PPM_PublicAGO needs discovery
3. SanGIS stacked parcels may return multiple results per point query — need dedup logic
4. Small incorporated cities (La Mesa, El Cajon, Poway) not covered in Phase 1
5. Heatmap color scale may need re-calibration for SD price ranges
6. Verify Redfin API covers SD County with same behavior as LA

### 2.9 Claude Code Execution Prompts

Test SD Parcel Endpoint:
```
Test point query against SD County parcel service at 32.77, -117.15 (Clairemont):
https://gis-public.sandiegocounty.gov/arcgis/rest/services/sdep_warehouse/PARCELS_ALL/MapServer/0/query
Use geometry point, inSR=4326, outSR=4326, returnGeometry=false. Print all fields.
```

Test SD City Zoning:
```
Test point query against SD City zoning at 32.77, -117.15:
https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Base/MapServer/0/query
Use geometry point, inSR=4326, returnGeometry=false. Print ZONE_NAME and all fields.
```

Test CAL FIRE Statewide:
```
Test point query against CAL FIRE LRA VHFHSZ at 32.90, -117.10 (Scripps Ranch):
https://services.gis.ca.gov/arcgis/rest/services/Environment/Fire_Severity_Zones/MapServer/1/query
Use geometry point, inSR=4326, returnGeometry=false. Print HAZ_CLASS and all fields.
```

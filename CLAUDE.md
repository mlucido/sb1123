# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SB 1123 Deal Finder** — a static single-page map app that identifies townhome subdivision opportunities under California SB 1123. Python scripts fetch and enrich Redfin listings, then the browser app renders a filterable interactive map with real-time pro forma analysis.

**Multi-market architecture**: All scripts accept `--market <slug>` (default: `la`). Market configs live in `market_config.py`. Current markets: `la` (Los Angeles), `sd` (San Diego).

Deployed via GitHub Pages: `https://mlucido.github.io/la-comps-map/`

## Run Commands

```bash
# Serve locally
python3 -m http.server 8080    # → http://localhost:8080

# Full data refresh (fetches listings + sold comps, rebuilds, pushes)
./refresh.sh                       # LA (default)
./refresh.sh --market sd           # San Diego
./refresh.sh --quick               # LA, listings only
./refresh.sh --market sd --quick   # SD, listings only

# Individual pipeline steps (all accept --market sd)
python3 fetch_listings.py           # → redfin_merged.csv (or sd_redfin_merged.csv)
python3 fetch_listings.py --test    # single tile test
python3 fetch_parcels.py            # → parcels.json (incremental)
python3 fetch_sold_comps.py         # → redfin_sold.csv (slow, full county)
python3 build_comps.py              # redfin_sold.csv → data.js
python3 listings_build.py           # all enrichment → listings.js
python3 fetch_slopes.py             # → slopes.json (~35 min, incremental)
python3 fetch_zoning.py             # → zoning.json (cascade through endpoints)
python3 fetch_rents.py              # → rents.json (HUD SAFMR by zip)
python3 fetch_urban.py              # → urban.json (Census urban areas)
```

No build step, no bundler, no test suite. Only Python dependency: `requests`.

## Multi-Market File Naming

LA (default market) uses unprefixed filenames for backward compatibility:
- `data.js`, `listings.js`, `parcels.json`, `redfin_merged.csv`, etc.

All other markets use `{slug}_` prefix:
- `sd_data.js`, `sd_listings.js`, `sd_parcels.json`, `sd_redfin_merged.csv`, etc.

Controlled by `market_file()` in `market_config.py`.

## Data Pipeline

```
fetch_listings.py → redfin_merged.csv
fetch_parcels.py  → parcels.json (ArcGIS: lot size, AIN, fire zone)
fetch_slopes.py   → slopes.json  (USGS LiDAR elevation → slope %)
fetch_sold_comps.py → redfin_sold.csv → build_comps.py → data.js

All of the above feed into:
listings_build.py → listings.js (enriched active listings with zone $/SF, new-con $/SF, slopes, parcels)
```

## Key Files

| File | Role |
|------|------|
| `index.html` | Entire frontend (~1700 lines): HTML + CSS + JS. Leaflet map, filters, pro forma, favorites. |
| `data.js` | `const LOADED_COMPS = [...]` — ~50K sold comp records for neighborhood $/SF and heatmap (~25MB) |
| `listings.js` | `const LOADED_LISTINGS = [...]` + `LISTINGS_META` — enriched active listings (~11MB) |
| `parcels.json` | Parcel cache keyed by `"lat,lng"` → `{lotSf, ain, landValue, impValue, fireZone}` |
| `slopes.json` | Slope cache keyed by `"lat,lng"` → slope percent |
| `market_config.py` | Central config: market bounds, ArcGIS endpoints, zoning classify functions, pro forma defaults |
| `listings_build.py` | Main enrichment: stamps parcels, fire zones, zone-matched $/SF (expanding radius search), new-con $/SF, slopes |
| `fetch_listings.py` | Adaptive geographic tiling of Redfin API (auto-subdivides tiles hitting 350-listing cap) |
| `refresh.sh` | Full pipeline orchestration + git push (accepts --market flag) |

## Architecture Notes

**Frontend**: No framework — vanilla JS + Leaflet 1.9.4 with esri-leaflet, leaflet.heat. All libraries loaded via CDN. All code lives in `index.html`.

**Python scripts**: Use only stdlib + `requests`. Each fetcher uses adaptive geographic tiling with auto-subdivision when hitting API caps. Fetchers that hit external APIs (`fetch_parcels.py`, `fetch_slopes.py`) are incremental (skip already-cached entries) and checkpoint periodically.

**Output format**: Python scripts write JS files with `const LOADED_COMPS = [...]` / `const LOADED_LISTINGS = [...]` using compact JSON (`separators=(",",":")`) — these are loaded as `<script>` tags, not fetched.

**Spatial indexing**: `listings_build.py` uses a grid index (`GRID_SIZE = 0.01` ≈ 0.7mi cells) for zone-matched comp lookups with expanding radius (0.25mi → 0.5mi → 1mi → 2mi → 4mi, min 5 comps). The JS frontend uses `0.005` degree cells for viewport comp queries.

## Redfin API Constraints

- Endpoint: `www.redfin.com/stingray/api/gis-csv`
- `num_homes=350` max (500 rejected as of Feb 2026)
- **Must create fresh `requests.Session()` per tile** — Redfin cookies restrict subsequent queries to same area
- `user_poly` format: `lng+lat` pairs (literal `+`, not URL-encoded)
- Rate limit: 1.5–2.5s between requests; retry on 429/403 with 15-25s backoff

## SB 1123 Business Logic (in index.html)

- **Eligibility**: R1-R4/LAND zones, no condo/townhouse (shared land), no R1+HOA, no VHFHSZ fire zone, lot ≥ 10K SF
- **Unit count**: R1/LAND = `floor(lot/1200)` cap 10; R2-R4 = `floor(lot/600)` cap 10
- **FAR**: 1.25 (8-10 units), 1.0 (3-7 units), 0.5 (<3 units)
- **Pro forma defaults**: $350/SF hard + 25% soft, 1,200 SF avg unit, 5% sale discount, $25K demo
- **Exit $/SF**: prefers new-con comps (`newconPpsf`), falls back to zone $/SF (`hoodPpsf`)

## Property Type → Zone Mapping

```
Single Family Residential → R1    Multi-Family (2-4 Unit) → R3
Townhouse / Condo/Co-op   → R2    Multi-Family (5+ Unit)  → R4
Mobile/Ranch               → R1    Vacant Land / Other     → LAND
```

## Cross-Market Mandate

All code changes MUST apply to every market unless explicitly market-specific (e.g., RSO is LA-only).
- Python scripts: Always use `get_market()` + `market_file()` from `market_config.py`
- Frontend (index.html): Market-agnostic — serves all markets from one codebase
- Test both `./refresh.sh` and `./refresh.sh --market sd` after pipeline changes
- New data files: Add to `refresh.sh` git add for both prefixed and unprefixed variants

## Listing Fields (stamped by listings_build.py)

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| tenantRisk | int 0-3 | Step 2.8 | Tenant risk level: 0=none, 1=low, 2=medium, 3=high |
| tenantRiskFactors | string[] | Step 2.8 | Risk factor codes: improved, 3+beds, 5+beds, MF+struct, pre-2000, RSO |
| rsoRisk | bool | Step 2.8 | LA RSO rent stabilization applies (LA only) |
| rsoFactors | string[] | Step 2.8 | RSO factor codes |
| remainderSf | int | Step 2.8 | R2-R4 remainder lot SF after existing footprint |
| remainderUnits | int | Step 2.8 | SB 1123 units on remainder parcel |
| estFootprint | int | Step 2.8 | Estimated existing building footprint SF |

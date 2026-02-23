# Refactor Spec: Config-Driven Multi-Market

**Goal:** Refactor all Python scripts to use `market_config.py` instead of hardcoded LA constants. Every script should accept `--market la` (default) or `--market sd`. LA behavior must be 100% backward compatible — no regressions.

**Config file:** `market_config.py` is already created. Import with:
```python
from market_config import get_market, CALFIRE_LRA_URL, TYPE_TO_ZONE, CLASSIFY_FNS, market_file
```

---

## Script-by-Script Changes

### 1. fetch_listings.py

**Current:** Hardcoded `LA_LAT_MIN/MAX`, `LA_LNG_MIN/MAX`, `TILE_LAT`, `TILE_LNG`

**Changes:**
- Add `from market_config import get_market, market_file`
- At top of `main()`: `market = get_market()`
- Replace all `LA_*` constants with `market["lat_min"]`, `market["lat_max"]`, etc.
- Replace `TILE_LAT`/`TILE_LNG` with `market["tile_lat"]`/`market["tile_lng"]`
- Replace `OUTPUT_FILE = "redfin_merged.csv"` with `OUTPUT_FILE = market_file("redfin_merged.csv", market)`
- Replace `"market=socal"` in the Redfin URL with `f"market={market['redfin_market']}"`
- Update print banner to show market name
- **Keep** the `--test` flag working

**Test:** `python3 fetch_listings.py --test` should produce identical output to current version.

### 2. fetch_sold_comps.py

**Current:** Same hardcoded LA constants as fetch_listings.

**Changes:** Identical pattern to fetch_listings.py:
- Import market config
- Replace bounding box constants
- Replace `OUTPUT_FILE = "redfin_sold.csv"` with `market_file("redfin_sold.csv", market)`
- Replace `market=socal` with market config value
- Note: `SOLD_WITHIN_DAYS = 730` stays hardcoded (same for all markets)

### 3. fetch_parcels.py — MOST COMPLEX

**Current:** Hardcoded LA County parcel URL, LA fire zone URL, LA bounding box.

**Changes:**
- Import market config + `CALFIRE_LRA_URL`
- Replace `PARCEL_URL` with `market["parcel_url"]`
- Replace `FIRE_URL` with statewide logic:
  ```python
  fire_url = market.get("fire_url") or CALFIRE_LRA_URL
  ```
- Replace bounding box constants with market config
- Refactor `query_parcel()` to be config-driven:
  - If `market["parcel_query_type"] == "envelope"`: use current LA envelope approach
  - If `market["parcel_query_type"] == "point"`: use point geometry with `inSR`/`outSR`
  - Map response fields using `market["parcel_field_map"]`:
    ```python
    field_map = market["parcel_field_map"]
    lot_raw = attrs.get(field_map["lot_sf"])
    lot_sf = round(lot_raw * field_map["lot_sf_multiplier"]) if lot_raw else None
    ain = attrs.get(field_map["ain"], "")
    land_value = attrs.get(field_map["land_value"])
    imp_value = attrs.get(field_map["imp_value"])
    situs_field = field_map.get("situs_address")
    situs = attrs.get(situs_field, "") if situs_field else ""
    ```
- Replace `OUTPUT_FILE` with `market_file("parcels.json", market)`
- Replace `load_listings_from_csv()` to read from `market_file("redfin_merged.csv", market)`

**Critical:** The response format must remain identical:
```json
{"lotSf": 12345, "ain": "1234567890", "landValue": 500000, "impValue": 200000, "fireZone": false}
```

### 4. fetch_zoning.py

**Current:** Hardcoded ZIMAS_URL, COUNTY_ZONING_URL, LA-specific classify functions.

**Changes:**
- Import `get_market, CLASSIFY_FNS, market_file`
- Replace hardcoded endpoints with `market["zoning_endpoints"]` list
- Refactor main query loop to iterate through endpoints:
  ```python
  for endpoint in market["zoning_endpoints"]:
      result = query_zoning_endpoint(lat, lng, endpoint)
      if result:
          classify_fn = CLASSIFY_FNS[endpoint["classify_fn"]]
          sb_zone = classify_fn(result["zoning"])
          result["sb1123"] = sb_zone
          result["source"] = endpoint["name"]
          break
  ```
- Replace `OUTPUT_FILE` with `market_file("zoning.json", market)`
- Remove the hardcoded `classify_zoning()` and `classify_county_zoning()` functions (moved to market_config.py)
- Keep the `--analyze` mode working

### 5. fetch_slopes.py

**Current:** Reads from `listings.js` (implicitly LA).

**Changes:** Minimal:
- Import `get_market, market_file`
- Replace `"listings.js"` reads with `market_file("listings.js", market)`
- Replace `"slopes.json"` writes with `market_file("slopes.json", market)`
- No endpoint changes (USGS is nationwide)

### 6. fetch_rents.py

**Current:** Reads from `listings.js` (implicitly LA).

**Changes:** Minimal:
- Import `get_market, market_file`
- Replace `"listings.js"` reads with `market_file("listings.js", market)`
- Replace `"rents.json"` writes with `market_file("rents.json", market)`
- No endpoint changes (HUD is nationwide)

### 7. fetch_urban.py

**Current:** Reads from `redfin_merged.csv` (implicitly LA).

**Changes:** Minimal:
- Import `get_market, market_file`
- Replace CSV read path with `market_file("redfin_merged.csv", market)`
- Replace output path with `market_file("urban.json", market)`

### 8. build_comps.py

**Current:** Hardcoded LA bounding box, reads `redfin_sold.csv`, writes `data.js`.

**Changes:**
- Import `get_market, market_file, TYPE_TO_ZONE`
- Replace bounding box with market config
- Replace file paths with `market_file()` calls
- Remove duplicated `TYPE_TO_ZONE` (import from market_config)

### 9. listings_build.py

**Current:** Hardcoded LA bounding box, reads multiple cache files, writes `listings.js`. Has LA-specific burn zone polygons.

**Changes:**
- Import `get_market, market_file, TYPE_TO_ZONE`
- Replace `LA_*` bounding box with market config
- Replace ALL file reads/writes with `market_file()`:
  - `data.js` → `market_file("data.js", market)`
  - `redfin_merged.csv` → `market_file("redfin_merged.csv", market)`
  - `parcels.json` → `market_file("parcels.json", market)`
  - `zoning.json` → `market_file("zoning.json", market)`
  - `urban.json` → `market_file("urban.json", market)`
  - `rents.json` → `market_file("rents.json", market)`
  - `slopes.json` → `market_file("slopes.json", market)`
  - `listings.js` → `market_file("listings.js", market)`
- Remove duplicated `TYPE_TO_ZONE` (import from market_config)
- Replace hardcoded burn zone polygons with:
  ```python
  burn_zones = market.get("burn_zones", [])
  for bz in burn_zones:
      # ... point_in_polygon check using bz["polygon"]
  ```
- Update print banners to show market name

### 10. refresh.sh

**Current:** No market parameter.

**Changes:**
```bash
#!/bin/bash
MARKET=${1:-la}
echo "  Market: $MARKET"

python3 fetch_listings.py --market $MARKET
python3 fetch_parcels.py --market $MARKET
# ... etc
```

Usage: `./refresh.sh sd` or `./refresh.sh` (defaults to la)

---

## File Naming Convention

The `market_file()` helper in market_config.py handles this:
- LA (default): no prefix → `listings.js`, `parcels.json`, etc. (backward compatible)
- SD: prefix → `sd_listings.js`, `sd_parcels.json`, etc.

This means LA files keep their current names and git history is preserved.

---

## Testing Checklist

After refactoring, verify:
1. `python3 fetch_listings.py --test` → same output as before (LA default)
2. `python3 fetch_listings.py --market la --test` → same output
3. `python3 fetch_parcels.py --test` → same output
4. `python3 fetch_zoning.py --test` → same output
5. `python3 listings_build.py` → produces identical `listings.js`
6. `python3 build_comps.py` → produces identical `data.js`
7. Full refresh: `./refresh.sh` → site works unchanged
8. `python3 fetch_listings.py --market sd --test` → fetches a SD tile

---

## Execution Order

1. **Do NOT modify any existing files yet.** First, verify `market_config.py` imports work:
   ```python
   python3 -c "from market_config import get_market; m = get_market(); print(m['name'])"
   ```

2. Refactor scripts one at a time in this order (each builds on the last):
   1. `fetch_listings.py` (simplest — just bounding box)
   2. `fetch_sold_comps.py` (same pattern)
   3. `build_comps.py` (reads sold CSV, writes data.js)
   4. `fetch_parcels.py` (complex — parcel + fire zone)
   5. `fetch_zoning.py` (complex — multi-endpoint cascade)
   6. `fetch_slopes.py` (trivial — just file paths)
   7. `fetch_rents.py` (trivial)
   8. `fetch_urban.py` (trivial)
   9. `listings_build.py` (most changes — reads all cache files)
   10. `refresh.sh` (add market param)

3. After each script, run `--test` to verify no regression.

4. After all scripts done, run full `./refresh.sh` and verify the site is unchanged.

---

## Important: What NOT to Change

- `index.html` — no changes yet (multi-market frontend is Phase 3)
- Spatial index logic in `listings_build.py` — the comp search algorithms stay the same
- `GRID_SIZE`, `MIN_COMPS`, `SEARCH_RADII_DEG` — same for all markets
- `data.js` format — same schema regardless of market
- `listings.js` format — same schema regardless of market

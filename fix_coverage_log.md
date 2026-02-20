# Coverage Fix Log — 2026-02-18

## Fix 1: MAX_SUBDIVIDE_DEPTH (4 → 6)
**File:** `fetch_listings.py`
**Commit:** `256cf3c`

Increased from 4 to 6. At depth 4, the smallest tile is ~0.0075° (~0.5mi) — still too large for dense urban areas like Hollywood/DTLA where 350+ active listings exist in that area. At depth 6, tiles go down to ~0.002° (~450ft), which should capture everything.

## Fix 2: Address parsing — ArcGIS situs address override
**Files:** `fetch_parcels.py`, `listings_build.py`
**Commit:** `aa990eb`

**Root cause:** Redfin's gis-csv endpoint returns mangled addresses for some listings (e.g., "3 ambar Dr" instead of "21825 Ambar Dr"). This is a Redfin data quality issue, not a parsing bug.

**Fix:** `fetch_parcels.py` already queries `SitusAddress` from ArcGIS parcels but was discarding it. Now it's saved to `parcels.json` and used as the primary address in `listings_build.py` when available. Existing parcels.json needs to be regenerated (`python3 fetch_parcels.py`) to populate the new `situsAddress` field.

## Fix 3: Lot size cross-reference — Already correct ✅
**Files:** `fetch_parcels.py`, `listings_build.py`

Verified that ArcGIS parcel lot size (`Shape.STArea()`) already overrides Redfin's lot size in Step 2.5 of `listings_build.py`. Currently 16,639 / 20,521 parcels have ArcGIS lot sizes that override Redfin values. No code changes needed.

## Next steps
1. Re-run `python3 fetch_parcels.py` to populate `situsAddress` in parcels.json
2. Re-run `python3 fetch_listings.py` for improved coverage with depth 6
3. Re-run `python3 listings_build.py` to rebuild listings.js with fixes

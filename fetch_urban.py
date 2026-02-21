#!/usr/bin/env python3
"""
fetch_urban.py
Checks whether each listing falls within a Census-designated Urban Area
using a local TIGER/Line shapefile + geopandas spatial join.

Downloads the 2020 Urban Areas shapefile once, then runs a bulk spatial
join against all listing lat/lngs in a single operation (~30s).

SB 1123 applies only to parcels in urbanized areas.

Reads:  redfin_merged.csv (lat/lng of active listings)
Writes: urban.json — keyed by "lat,lng" → true/false

Usage:
  python3 fetch_urban.py          # All listings (full rebuild)
  python3 fetch_urban.py --test   # First 100 only

Requires: geopandas, shapely, fiona
  pip3 install geopandas shapely fiona
"""

import csv, json, os, sys, time, zipfile, urllib.request

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Config ──
SHAPEFILE_URL = "https://www2.census.gov/geo/tiger/TIGER2020/UAC/tl_2020_us_uac20.zip"
SHAPEFILE_DIR = "tiger_urban"
SHAPEFILE_ZIP = os.path.join(SHAPEFILE_DIR, "tl_2020_us_uac20.zip")
SHAPEFILE_PATH = os.path.join(SHAPEFILE_DIR, "tl_2020_us_uac20.shp")
OUTPUT_FILE = "urban.json"

# LA County bounding box
LA_LAT_MIN, LA_LAT_MAX = 33.70, 34.85
LA_LNG_MIN, LA_LNG_MAX = -118.95, -117.55


def download_shapefile():
    """Download and extract the TIGER Urban Areas shapefile if not present."""
    if os.path.exists(SHAPEFILE_PATH):
        print(f"  Shapefile already exists: {SHAPEFILE_PATH}")
        return

    os.makedirs(SHAPEFILE_DIR, exist_ok=True)

    if not os.path.exists(SHAPEFILE_ZIP):
        print(f"  Downloading Urban Areas shapefile (~120 MB)...")
        t0 = time.time()
        urllib.request.urlretrieve(SHAPEFILE_URL, SHAPEFILE_ZIP)
        print(f"  Downloaded in {time.time()-t0:.1f}s")
    else:
        print(f"  Zip already downloaded: {SHAPEFILE_ZIP}")

    print(f"  Extracting...")
    with zipfile.ZipFile(SHAPEFILE_ZIP, "r") as zf:
        zf.extractall(SHAPEFILE_DIR)
    print(f"  Extracted to {SHAPEFILE_DIR}/")


def load_listings_from_csv():
    """Load lat/lng from redfin_merged.csv."""
    csv_file = "redfin_merged.csv"
    if not os.path.exists(csv_file):
        print(f"  No {csv_file} found.")
        sys.exit(1)

    listings = []
    with open(csv_file, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row.get("LATITUDE") or 0)
                lng = float(row.get("LONGITUDE") or 0)
                if LA_LAT_MIN <= lat <= LA_LAT_MAX and LA_LNG_MIN <= lng <= LA_LNG_MAX:
                    listings.append({"lat": round(lat, 6), "lng": round(lng, 6)})
            except (ValueError, TypeError):
                continue
    return listings


def main():
    import geopandas as gpd
    from shapely.geometry import Point

    test_mode = "--test" in sys.argv
    t_start = time.time()

    # Step 1: Download shapefile
    print("Step 1: Ensuring Urban Areas shapefile is available...")
    download_shapefile()

    # Step 2: Load listings
    print("\nStep 2: Loading listings from redfin_merged.csv...")
    listings = load_listings_from_csv()
    if test_mode:
        listings = listings[:100]
    print(f"  {len(listings):,} listings loaded")

    # Step 3: Load shapefile and clip to LA County bbox
    print("\nStep 3: Loading Urban Areas shapefile...")
    t0 = time.time()
    urban_areas = gpd.read_file(SHAPEFILE_PATH, bbox=(LA_LNG_MIN, LA_LAT_MIN, LA_LNG_MAX, LA_LAT_MAX))
    print(f"  Loaded {len(urban_areas)} urban area polygons in LA County bbox ({time.time()-t0:.1f}s)")

    # Step 4: Build listing GeoDataFrame
    print("\nStep 4: Building listing points...")
    keys = [f"{l['lat']},{l['lng']}" for l in listings]
    points = [Point(l["lng"], l["lat"]) for l in listings]
    listings_gdf = gpd.GeoDataFrame({"key": keys}, geometry=points, crs=urban_areas.crs)
    print(f"  {len(listings_gdf):,} points created")

    # Step 5: Spatial join
    print("\nStep 5: Running spatial join...")
    t0 = time.time()
    joined = gpd.sjoin(listings_gdf, urban_areas, how="left", predicate="within")
    elapsed = time.time() - t0
    print(f"  Spatial join completed in {elapsed:.1f}s")

    # Step 6: Build output — deduplicate (sjoin can produce multiple matches)
    print("\nStep 6: Building urban.json...")
    cache = {}
    in_urban = set(joined.dropna(subset=["index_right"])["key"].unique())

    for key in keys:
        cache[key] = key in in_urban

    urban_count = sum(1 for v in cache.values() if v)
    non_urban_count = sum(1 for v in cache.values() if not v)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(cache, f, separators=(",", ":"))

    total_time = time.time() - t_start
    print(f"\n  Done in {total_time:.1f}s total")
    print(f"  Urban: {urban_count:,} | Non-urban: {non_urban_count:,} | Total: {len(cache):,}")
    print(f"  Written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

"""
tile_utils.py — Shared geographic tiling utilities for Redfin fetchers.

Used by: fetch_listings.py, fetch_sold_comps.py, fetch_rental_comps.py
"""


def build_grid(market):
    """Build initial coarse grid of tiles covering the market area."""
    lat_min, lat_max = market["lat_min"], market["lat_max"]
    lng_min, lng_max = market["lng_min"], market["lng_max"]
    tile_lat, tile_lng = market["tile_lat"], market["tile_lng"]
    tiles = []
    lat = lat_min
    while lat < lat_max:
        lng = lng_min
        while lng < lng_max:
            lat2 = round(min(lat + tile_lat, lat_max), 4)
            lng2 = round(min(lng + tile_lng, lng_max), 4)
            tiles.append({
                "lat_min": round(lat, 4),
                "lat_max": lat2,
                "lng_min": round(lng, 4),
                "lng_max": lng2,
                "depth": 0,
            })
            lng += tile_lng
        lat += tile_lat
    return tiles


def subdivide_tile(t):
    """Split a tile into 4 quadrants."""
    mid_lat = round((t['lat_min'] + t['lat_max']) / 2, 6)
    mid_lng = round((t['lng_min'] + t['lng_max']) / 2, 6)
    d = t.get('depth', 0) + 1
    return [
        {"lat_min": t['lat_min'], "lat_max": mid_lat, "lng_min": t['lng_min'], "lng_max": mid_lng, "depth": d},
        {"lat_min": t['lat_min'], "lat_max": mid_lat, "lng_min": mid_lng, "lng_max": t['lng_max'], "depth": d},
        {"lat_min": mid_lat, "lat_max": t['lat_max'], "lng_min": t['lng_min'], "lng_max": mid_lng, "depth": d},
        {"lat_min": mid_lat, "lat_max": t['lat_max'], "lng_min": mid_lng, "lng_max": t['lng_max'], "depth": d},
    ]


def tile_to_poly(t):
    """Convert tile to Redfin user_poly format: lng+lat pairs for rectangle."""
    return (
        f"{t['lng_min']}+{t['lat_min']},"
        f"{t['lng_max']}+{t['lat_min']},"
        f"{t['lng_max']}+{t['lat_max']},"
        f"{t['lng_min']}+{t['lat_max']},"
        f"{t['lng_min']}+{t['lat_min']}"
    )


def tile_label(t):
    """Human-readable tile identifier for logging."""
    mid_lat = (t['lat_min'] + t['lat_max']) / 2
    mid_lng = (t['lng_min'] + t['lng_max']) / 2
    depth = t.get('depth', 0)
    return f"({mid_lat:.3f}, {mid_lng:.3f}) d{depth}"


def tile_key(t):
    """Stable string key for checkpoint tracking."""
    return f"{t['lat_min']},{t['lat_max']},{t['lng_min']},{t['lng_max']}"

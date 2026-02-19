# Zillow Scraper Notes

## Usage

```bash
# Full LA County fetch
python3 fetch_zillow.py

# Test mode (single tile near central LA)
python3 fetch_zillow.py --test

# Skip cache, fresh fetch
python3 fetch_zillow.py --no-cache
```

## Output

- **`zillow_listings.json`** — Array of listing objects with: address, city, zip, price, beds, baths, sqft, lot_sqft, property_type, lat, lng, listing_url, days_on_market, source
- **`zillow_cache.json`** — Incremental cache keyed by zpid (auto-saved every 20 tiles)

## Filters Applied

- Property types: houses + land only (no condos, townhouses, apartments, multi-family)
- Lot size: 12,000+ SF minimum
- Status: active for-sale listings

## Rate Limiting

- 1.5-2.5s delay between requests
- Backs off 20-35s on 403/429 responses
- Max 2 retries per request

## Known Limitations

- Zillow actively blocks scraping — may get 403s, especially from cloud IPs
- If blocked, try from a residential IP or add proxy support
- Results cap at ~500 per search region; the tiling grid handles this
- The `GetSearchPageState` API response format may change without notice

## Integration

The output `zillow_listings.json` can be merged with Redfin data in `listings_build.py` to create a combined dataset. Each listing has `"source": "zillow"` for identification.

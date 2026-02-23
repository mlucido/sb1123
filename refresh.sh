#!/bin/bash
# refresh.sh — One-click data refresh for SB 1123 Deal Finder
# Pulls fresh Redfin listings, rebuilds all enrichment, and pushes to GitHub Pages.
#
# Usage:
#   ./refresh.sh                    # Full refresh, LA (default)
#   ./refresh.sh --quick            # Listings only, LA
#   ./refresh.sh --market sd        # Full refresh, San Diego
#   ./refresh.sh --market sd --quick  # Listings only, San Diego

set -e
cd "$(dirname "$0")"

echo ""
echo "============================================================"
echo "  SB 1123 Deal Finder — Data Refresh"
echo "============================================================"
echo ""

# Parse args
QUICK=false
MARKET_ARG=""
MARKET_SLUG="la"

while [[ $# -gt 0 ]]; do
  case $1 in
    --quick)
      QUICK=true
      shift
      ;;
    --market)
      MARKET_SLUG="$2"
      MARKET_ARG="--market $2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

echo "  Market: $MARKET_SLUG"
if [ "$QUICK" = true ]; then
  echo "  Mode: Quick (listings only, skip sold comps)"
else
  echo "  Mode: Full (listings + sold comps)"
fi
echo ""

# Determine file prefix for non-LA markets
PREFIX=""
if [ "$MARKET_SLUG" != "la" ]; then
  PREFIX="${MARKET_SLUG}_"
fi

# Step 1: Fetch fresh active listings from Redfin
echo "📥 Step 1: Fetching active listings from Redfin..."
python3 fetch_listings.py $MARKET_ARG
echo ""

# Step 1b: Fetch parcel data + fire zones from ArcGIS
echo "📦 Step 1b: Fetching parcel data from ArcGIS..."
python3 fetch_parcels.py $MARKET_ARG
echo ""

# Step 2: Optionally refresh sold comps
if [ "$QUICK" = false ]; then
  echo "📥 Step 2: Fetching sold comps from Redfin..."
  python3 fetch_sold_comps.py $MARKET_ARG
  echo ""

  echo "🔨 Step 3: Building ${PREFIX}data.js (sold comps)..."
  python3 build_comps.py $MARKET_ARG
  echo ""
fi

# Step 2b: Fetch ZHVI appreciation data
echo "📈 Fetching ZHVI appreciation data..."
python3 fetch_zhvi.py $MARKET_ARG
echo ""

# Step 2c: Build subdivision comps
echo "🏘️ Building subdivision comps..."
python3 build_subdiv_comps.py $MARKET_ARG
echo ""

# Step 3: Rebuild listings.js with all enrichment
echo "🔨 Building ${PREFIX}listings.js (zone $/SF, new-con, subdiv, slope, city)..."
python3 listings_build.py $MARKET_ARG
echo ""

# Step 4: Push to GitHub Pages
echo "🚀 Pushing to GitHub Pages..."
git add ${PREFIX}data.js ${PREFIX}listings.js ${PREFIX}slopes.json ${PREFIX}parcels.json ${PREFIX}zhvi.json ${PREFIX}subdiv_comps.json
git commit -m "Refresh ${MARKET_SLUG} listing data $(date +%Y-%m-%d)" --allow-empty
git push
echo ""

echo "============================================================"
echo "  ✅ Done! Site will update in ~60s:"
echo "  https://mlucido.github.io/la-comps-map/"
echo "============================================================"
echo ""

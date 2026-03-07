#!/usr/bin/env python3
"""
LA County $/SF Comps — Build & Serve
Filters the big Assessor CSV, creates data.js, and launches the map.
"""
import csv, json, glob, os, http.server, webbrowser

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Step 1: Find the big CSV ──
big_csvs = glob.glob("Parcel_Data_2021*.csv")
if not big_csvs:
    print("\n❌ Could not find the Assessor CSV file.")
    print("   Make sure the file starting with 'Parcel_Data_2021' is in this folder.")
    exit(1)

src = big_csvs[0]
print(f"\n🗂️  Found: {src}")
print(f"   Size: {os.path.getsize(src) / 1024 / 1024:.0f} MB")

# ── Step 2: Filter to R1-R4 residential ──
print("\n⏳ Filtering to residential R1-R4 comps... (this takes a few minutes)\n")

zone_map = {
    "Single Family Residence": "R1",
    "Double, Duplex, or Two Units": "R2",
    "Three Units (Any Combination)": "R3",
    "Four Units  (Any Combination)": "R3",
    "Five or More Units or Apartments (Any Combination)": "R4",
}

comps = []
skipped = 0

with open(src, encoding="utf-8", errors="replace") as f:
    reader = csv.reader(f)
    header = next(reader)

    for i, row in enumerate(reader):
        if i % 2_000_000 == 0:
            print(f"   ...processed {i:>12,} rows  |  found {len(comps):,} comps")
        try:
            d2 = row[10].strip()
            zone = zone_map.get(d2)
            if not zone:
                continue

            sqft = float(row[16] or 0)
            val = float(row[25] or 0)
            lat = float(row[48] or 0)
            lng = float(row[49] or 0)

            if sqft <= 0 or val <= 0 or lat == 0 or lng == 0:
                skipped += 1
                continue

            comps.append({
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "price": val,
                "sqft": sqft,
                "zone": zone,
                "address": row[6].strip(),
                "date": row[20].strip(),
            })
        except:
            skipped += 1
            continue

print(f"\n   ✅ Total rows processed: {i:,}")
print(f"   ✅ Comps found: {len(comps):,}")
print(f"   ⚠️  Rows skipped: {skipped:,}")

if len(comps) == 0:
    print("\n❌ No comps found. Something is wrong with the CSV format.")
    exit(1)

# ── Step 3: Write data.js ──
data_js = f"const LOADED_COMPS = {json.dumps(comps)};"
with open("data.js", "w") as f:
    f.write(data_js)

size_mb = len(data_js) / 1024 / 1024
print(f"\n📦 Created data.js ({size_mb:.1f} MB)")

# ── Step 4: Summary ──
zone_counts = {}
for c in comps:
    zone_counts[c["zone"]] = zone_counts.get(c["zone"], 0) + 1

print("\n📊 Breakdown:")
for z in ["R1", "R2", "R3", "R4"]:
    cnt = zone_counts.get(z, 0)
    print(f"   {z}: {cnt:>10,} comps")

# ── Step 5: Launch server ──
PORT = 8080
print(f"\n🗺️  Launching map at http://localhost:{PORT}")
print(f"   Press Ctrl+C to stop\n")

webbrowser.open(f"http://localhost:{PORT}")
http.server.HTTPServer(("", PORT), http.server.SimpleHTTPRequestHandler).serve_forever()

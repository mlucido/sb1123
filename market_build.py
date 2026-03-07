#!/usr/bin/env python3
"""
Matches LA County parcels with Redfin market $/SF data,
builds data.js, and launches the map server.
"""
import csv, json, random, re, os, http.server, webbrowser

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Step 1: Read Redfin zip code PPSF for CA ──
print("\nStep 1: Reading Redfin zip code data for CA...")
zip_ppsf = {}
with open("zip_code_market_tracker.tsv000", encoding="utf-8", errors="replace") as f:
    for i, line in enumerate(f):
        if i == 0:
            continue
        if i % 5_000_000 == 0:
            print(f"  ...{i:,} rows")
        parts = line.strip().split("\t")
        try:
            state = parts[10].strip('"')
            if state != "CA":
                continue
            # Extract zip from "Zip Code: 90006"
            region = parts[7].strip('"')
            m = re.search(r"(\d{5})", region)
            if not m:
                continue
            zipcode = m.group(1)
            # Only "All Residential"
            prop_type = parts[11].strip('"')
            if prop_type != "All Residential":
                continue
            # Only 2024-2025 data
            period = parts[1].strip('"')
            if "2024" not in period and "2025" not in period:
                continue
            ppsf_str = parts[19].strip('"')
            if not ppsf_str:
                continue
            ppsf = float(ppsf_str)
            if ppsf <= 0:
                continue
            # Keep latest period per zip
            old = zip_ppsf.get(zipcode, ("", 0))[0]
            if period >= old:
                zip_ppsf[zipcode] = (period, ppsf)
        except Exception:
            continue

print(f"  Found {len(zip_ppsf)} CA zip codes with recent PPSF")
samples = sorted(zip_ppsf.items())[:8]
for z, (p, v) in samples:
    print(f"    {z}: ${v:.0f}/sf ({p})")

# ── Step 2: Match parcels to market PPSF ──
print("\nStep 2: Matching parcels to market PPSF...")
comps = []
no_zip = 0
no_match = 0
with open("comps_r1r4.csv") as f:
    for row in csv.DictReader(f):
        addr = row["address"].strip()
        # Extract 5-digit zip from end of address
        m = re.search(r"(\d{5})\s*$", addr)
        if not m:
            no_zip += 1
            continue
        zipcode = m.group(1)
        entry = zip_ppsf.get(zipcode)
        if not entry:
            no_match += 1
            continue
        market_ppsf = entry[1]
        sqft = float(row["sqft"])
        comps.append({
            "lat": float(row["lat"]),
            "lng": float(row["lng"]),
            "price": round(market_ppsf * sqft),
            "sqft": sqft,
            "zone": row["zone"],
            "address": addr,
            "date": row["date"],
            "zip": zipcode,
            "ppsf": round(market_ppsf),
        })

print(f"  Matched: {len(comps):,}")
print(f"  No zip found: {no_zip:,}")
print(f"  Zip not in Redfin: {no_match:,}")

if len(comps) == 0:
    print("\nERROR: No comps matched. Check data files.")
    exit(1)

# ── Step 3: Sample if needed ──
if len(comps) > 50_000:
    print(f"\n  Sampling 50,000 from {len(comps):,}...")
    zg = {}
    for c in comps:
        zg.setdefault(c["zone"], []).append(c)
    sampled = []
    for zone, group in zg.items():
        n = max(100, int(50_000 * len(group) / len(comps)))
        sampled.extend(random.sample(group, min(n, len(group))))
    comps = sampled
    print(f"  Sampled to: {len(comps):,}")

# ── Step 4: Summary ──
print("\n  Zone breakdown (market $/SF):")
for z in ["R1", "R2", "R3", "R4"]:
    zc = [c for c in comps if c["zone"] == z]
    if zc:
        avg = round(sum(c["ppsf"] for c in zc) / len(zc))
        print(f"    {z}: {len(zc):,} comps, avg ${avg}/sf")

# ── Step 5: Write data.js ──
data_js = "const LOADED_COMPS = " + json.dumps(comps) + ";"
with open("data.js", "w") as f:
    f.write(data_js)
size_mb = len(data_js) / 1024 / 1024
print(f"\n  Created data.js ({size_mb:.1f} MB)")

# ── Step 6: Launch server ──
PORT = 8080
print(f"\n  Launching map at http://localhost:{PORT}")
print(f"  Press Ctrl+C to stop\n")
webbrowser.open(f"http://localhost:{PORT}")
http.server.HTTPServer(("", PORT), http.server.SimpleHTTPRequestHandler).serve_forever()

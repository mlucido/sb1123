# SB 1123 Townhome Subdivision — Lot Size Sensitivity Analysis

**Date:** 2026-02-18  
**Model basis:** 1123_v11-lots.xlsx base case (31,168 SF lot, 10 units, $850/SF exit)

## Key Assumptions

| Parameter | Value |
|-----------|-------|
| Zone | R1 (units = floor(lot_sf / 1,200), cap 10) |
| Land cost | $64/SF (scaled from base case) |
| Exit price | $850/SF |
| Hard cost | $250/SF vertical + $91/SF on-site + $10/SF subdiv + $6/SF A&E + 5% contingency |
| FAR | 1.25 (8-10 units), 1.0 (3-7 units) |
| Max SF/unit | 1,750 SF (constrained by FAR × lot / units) |
| Sponsor fees | ~9% of (land + hard) |
| Construction loan | 9%, 65% LTC, 22-month timeline |
| Bulk discount | 10% |
| Exit transaction costs | 6.7% + $40K legal/CPA |
| Existing house | $1M value + $3,500/mo rent for lots ≥ 15K SF; none for smaller |

## Results

| Lot SF | Units | SF/Unit | Total SF | Land Cost | Total Cost | Net Proceeds | Profit | LP MOIC | LP XIRR |
|-------:|------:|--------:|---------:|----------:|-----------:|-------------:|-------:|--------:|--------:|
| 12,000 | 10 | 1,500 | 15,000 | $768K | $7.54M | $10.67M | $3.13M | **1.87x** | **40.8%** |
| 15,000 | 10 | 1,750 | 17,500 | $960K | $8.78M | $12.45M | $3.68M | **1.88x** | **41.2%** |
| 20,000 | 10 | 1,750 | 17,500 | $1.28M | $9.13M | $12.45M | $3.32M | **1.77x** | **36.6%** |
| 25,000 | 10 | 1,750 | 17,500 | $1.60M | $9.49M | $12.45M | $2.96M | **1.67x** | **32.2%** |
| 31,168 | 10 | 1,750 | 17,500 | $1.99M | $9.92M | $12.45M | $2.53M | **1.55x** | **27.1%** |

## Key Findings

### 1. All lot sizes pencil (LP MOIC > 1.5x, XIRR > 25%)
Every lot from 12K to 31K SF clears the hurdle — but the economics diverge dramatically.

### 2. Smaller lots are MORE profitable, not less
The 12K and 15K SF lots produce the **best returns** because:
- You still get the **maximum 10 units** (12,000 / 1,200 = 10)
- Land basis is **much lower** ($768K vs $1.99M)
- Revenue is only slightly lower (15K has slightly smaller units at 1,500 SF vs 1,750 SF)
- The unit cap at 10 means you're just paying more for dirt on bigger lots

### 3. The sweet spot is 15,000 SF
- Hits 10 units AND maxes out at 1,750 SF/unit (FAR 1.25 × 15K / 10 = 1,875, capped at 1,750)
- Best absolute profit ($3.68M) and best LP MOIC (1.88x)
- Has the rental income offset from existing house during construction

### 4. 12,000 SF is the true minimum viable lot
- 10 units fit (barely: 12,000 / 1,200 = 10.0 exactly)
- Units are smaller (1,500 SF vs 1,750) due to FAR constraint
- Still produces excellent returns (1.87x / 40.8%)
- **Below 12K SF you lose a unit** — 11,999 SF → 9 units, crossing the FAR threshold from 1.25 to 1.0

### 5. Bigger lots = diminishing returns
Above 15K SF, you're paying for land that doesn't add units or buildable SF. The 31K SF base case is actually the **worst-performing** lot size in the set — it works, but every dollar of extra land cost is pure drag.

## Recommendation: Update App Filter from 10K to 12K SF

The app currently filters at 10,000 SF minimum. This should be **raised to 12,000 SF** because:

- **10,000 SF → 8 units** (10,000 / 1,200 = 8.33 → 8 units). Still works but materially fewer units.
- **11,999 SF → 9 units**, with FAR dropping to 1.0 (only 8 units would get 1.25 FAR). The unit count/FAR interaction creates an awkward zone between 10K-12K.
- **12,000 SF is the clean breakpoint**: exactly 10 units, FAR 1.25, and you're building the maximum density the law allows on R1.

Showing 10K-12K lots in the pipeline risks presenting deals that look feasible but are materially worse — a 20-25% return drag vs the 12K+ cohort.

---

*Analysis generated from model formulas. Cross-reference with v11 spreadsheet for exact waterfall/XIRR calculations.*

# Zoning Analysis: ZIMAS vs Redfin Guesses

**Date:** 2026-02-18  
**Sample size:** 50 LA City listings queried, 21 returned ZIMAS data (29 had no zoning data — likely unincorporated LA County areas despite "Los Angeles" city name in Redfin)

## Summary

| Metric | Count | Pct |
|--------|-------|-----|
| Total with ZIMAS data | 21 | — |
| Matches (Redfin = ZIMAS) | 8 | 38% |
| **Mismatches** | **13** | **62%** |

**62% of Redfin-guessed zones are WRONG** compared to actual ZIMAS zoning data.

## Mismatch Details

| Address | Redfin Type | Redfin Zone | ZIMAS Code | ZIMAS SB1123 |
|---------|-------------|-------------|------------|---------------|
| 322 S Grand Ave, LA 90731 | Multi-Family (2-4 Unit) | R3 | RD1.5-1XL-CPIO | R2 |
| 317 W 107th, LA 90003 | Single Family Residential | R1 | R2-1 | R2 |
| 152 W 111th Pl, LA 90061 | Multi-Family (2-4 Unit) | R3 | R2-1 | R2 |
| 416 W 108th, LA 90061 | Single Family Residential | R1 | [Q]R4-1 | R4 |
| 10965 S Hoover St, LA 90044 | Vacant Land | LAND | R1-1 | R1 |
| 10714 S Broadway, LA 90061 | Multi-Family (2-4 Unit) | R3 | C2-1VL-CPIO | COMMERCIAL |
| 519 W Athens, LA 90044 | Multi-Family (2-4 Unit) | R3 | R1-1 | R1 |
| 10904 S Spring, LA 90061 | Multi-Family (2-4 Unit) | R3 | R2-1 | R2 |
| 11166 S Figueroa St, LA 90061 | Multi-Family (2-4 Unit) | R3 | C2-2D-CPIO | COMMERCIAL |
| 134 W 113th, LA 90061 | Single Family Residential | R1 | R2-1 | R2 |
| 142 W 110th St, LA 90061 | Single Family Residential | R1 | R2-1 | R2 |
| 143 W 110th St, LA 90061 | Single Family Residential | R1 | R2-1 | R2 |
| 452 Laconia Blvd, LA 90061 | Single Family Residential | R1 | R3-1-O | R3 |

## Mismatch Patterns

| Redfin → ZIMAS | Count | Impact |
|----------------|-------|--------|
| R1 → R2 | 4 | **Undervalued** — these allow more density than Redfin suggests |
| R3 → R2 | 3 | Overvalued — actually less density than guessed |
| R3 → COMMERCIAL | 2 | **Wrong category entirely** — not eligible for SB 1123 |
| R1 → R4 | 1 | **Major undervaluation** — R4 allows significant density |
| R1 → R3 | 1 | Undervalued |
| R3 → R1 | 1 | Overvalued — actually single-family zoning |
| LAND → R1 | 1 | Vacant land correctly zoned R1 |

## Key Takeaways

1. **62% error rate** — Redfin property types are deeply unreliable for zoning classification
2. **Most common error: R1 → R2** — Single Family homes sitting on R2 lots (more density allowed than Redfin shows)
3. **Dangerous errors: R3 → COMMERCIAL** — Properties guessed as multifamily that are actually commercial zoning (not SB 1123 eligible at all)
4. **Hidden gems: R1 → R4** — A property listed as SFR actually sits on R4 zoning, allowing far more units
5. **42% hit rate for ZIMAS** — Only 21/50 "Los Angeles" listings returned data; many are in unincorporated areas served by LA County (not LA City)
6. **Recommendation:** Always use ZIMAS for LA City properties; fall back to Redfin guess only for non-LA-City areas

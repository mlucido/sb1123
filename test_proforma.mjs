#!/usr/bin/env node
/**
 * test_proforma.mjs — Unit tests for SB 1123 pro forma math
 *
 * Run:  node test_proforma.mjs
 *
 * Tests the core financial calculations that drive the entire app:
 * unit count, slope adjustment, full pro forma, layout constraints,
 * RSO/Ellis, BTR model, and edge cases.
 *
 * No dependencies — uses Node's built-in assert.
 */

import assert from 'node:assert/strict';

// Mock document.getElementById for BTR (returns null → falls back to defaults)
globalThis.document = { getElementById: () => null };

import {
  proforma,
  clearProformaCaches,
  getMinLotPerUnit,
  getMaxUnits,
  getSlopeAdjBuildCost,
  calculateProForma,
  calculateBTRProForma,
} from './js/proforma.js';

let passed = 0;
let failed = 0;

function test(name, fn) {
  clearProformaCaches();
  try {
    fn();
    passed++;
    console.log(`  \x1b[32m✓\x1b[0m ${name}`);
  } catch (e) {
    failed++;
    console.log(`  \x1b[31m✗\x1b[0m ${name}`);
    console.log(`    ${e.message}`);
  }
}

function approx(actual, expected, tolerance = 1) {
  if (Math.abs(actual - expected) > tolerance) {
    throw new Error(`Expected ~${expected}, got ${actual} (tolerance: ${tolerance})`);
  }
}

// ─── Unit Count Tests ───

console.log('\nUnit Count (getMaxUnits / getMinLotPerUnit)');

test('R1 min lot per unit = 1200', () => {
  assert.equal(getMinLotPerUnit('R1'), 1200);
});

test('LAND min lot per unit = 1200', () => {
  assert.equal(getMinLotPerUnit('LAND'), 1200);
});

test('R2 min lot per unit = 600', () => {
  assert.equal(getMinLotPerUnit('R2'), 600);
});

test('R3 min lot per unit = 600', () => {
  assert.equal(getMinLotPerUnit('R3'), 600);
});

test('R4 min lot per unit = 600', () => {
  assert.equal(getMinLotPerUnit('R4'), 600);
});

test('R1 10K lot = 8 units', () => {
  assert.equal(getMaxUnits({ lotSf: 10000, zone: 'R1' }), 8);
});

test('R2 10K lot = 10 units (capped)', () => {
  assert.equal(getMaxUnits({ lotSf: 10000, zone: 'R2' }), 10);
});

test('R1 2400 lot = 2 units', () => {
  assert.equal(getMaxUnits({ lotSf: 2400, zone: 'R1' }), 2);
});

test('R1 1199 lot = 1 unit (min floor)', () => {
  assert.equal(getMaxUnits({ lotSf: 1199, zone: 'R1' }), 1);
});

test('R2 6000 lot = 10 units (capped at 10)', () => {
  assert.equal(getMaxUnits({ lotSf: 6000, zone: 'R2' }), 10);
});

test('R2 599 lot = 1 unit (min floor)', () => {
  assert.equal(getMaxUnits({ lotSf: 599, zone: 'R2' }), 1);
});

test('Missing lotSf = 1 unit', () => {
  assert.equal(getMaxUnits({ lotSf: 0, zone: 'R1' }), 1);
  assert.equal(getMaxUnits({ zone: 'R1' }), 1);
});

test('LAND 12K lot = 10 units (capped)', () => {
  assert.equal(getMaxUnits({ lotSf: 12000, zone: 'LAND' }), 10);
});

// ─── Slope Adjustment Tests ───

console.log('\nSlope Adjustment (getSlopeAdjBuildCost)');

test('Flat lot (0%) = base cost', () => {
  assert.equal(getSlopeAdjBuildCost(0, 400), 400);
});

test('5% slope = base cost (threshold)', () => {
  assert.equal(getSlopeAdjBuildCost(5, 400), 400);
});

test('6% slope = base + $15', () => {
  assert.equal(getSlopeAdjBuildCost(6, 400), 415);
});

test('10% slope = base + $15', () => {
  assert.equal(getSlopeAdjBuildCost(10, 400), 415);
});

test('11% slope = base + $30', () => {
  assert.equal(getSlopeAdjBuildCost(11, 400), 430);
});

test('12% slope = base + $30', () => {
  assert.equal(getSlopeAdjBuildCost(12, 400), 430);
});

test('20% slope = base + $45', () => {
  assert.equal(getSlopeAdjBuildCost(20, 400), 445);
});

test('Null slope = base cost', () => {
  assert.equal(getSlopeAdjBuildCost(null, 400), 400);
  assert.equal(getSlopeAdjBuildCost(undefined, 400), 400);
});

// ─── Full Pro Forma: Golden Path ───

console.log('\nFull Pro Forma — Golden Path (R1, 10K, $1.5M, $600 exit, flat)');

const goldenListing = {
  lat: 34.05, lng: -118.35, lotSf: 10000, zone: 'R1',
  price: 1500000, exitPsf: 600, slope: 0,
};

test('Golden path: units, revenue, costs, margin', () => {
  const r = calculateProForma(goldenListing);

  assert.equal(r.maxUnits, 8);
  assert.equal(r.densityUnits, 8);
  assert.equal(r.effective_buildable_sf, 14000);
  assert.equal(r.adjBuildCostPerSf, 400);

  // Revenue
  assert.equal(r.grossRevenue, 8400000);
  assert.equal(r.netRevenue, 7965200);

  // Construction
  assert.equal(r.constructionCost, 5600000);
  assert.equal(r.totalBuildCost, 5600000);
  assert.equal(r.hardCosts, 4312000);
  assert.equal(r.softCosts, 1288000);

  // Verify hard + soft = construction
  assert.equal(r.hardCosts + r.softCosts, r.constructionCost);

  // Carry
  approx(r.carryInterest, 541800);
  approx(r.carryPropTax, 33000);
  assert.equal(r.insurance, 40000);
  approx(r.originationFee, 49700);
  approx(r.totalCarry, 664500);

  // Ellis: none for R1
  assert.equal(r.ellisRelocation, 0);
  assert.equal(r.ellisHoldMonths, 0);

  // Totals
  approx(r.totalCost, 7764500);
  approx(r.profit, 200700);
  approx(r.margin, 2.52, 0.1);
  approx(r.return_on_cost, 2.58, 0.1);

  // Land basis
  assert.equal(r.land_basis_psf, 107);

  // Max offer (negative for this tight deal)
  approx(r.max_offer, -395117, 5);
});

// ─── R2 + RSO + Slope ───

console.log('\nPro Forma — R2, RSO, 12% slope, 12K lot, $800K, $700 exit');

const rsoListing = {
  lat: 34.1, lng: -118.3, lotSf: 12000, zone: 'R2',
  price: 800000, exitPsf: 700, slope: 12, rsoRisk: true,
};

test('R2+RSO+slope: units, ellis, adjusted build cost', () => {
  const r = calculateProForma(rsoListing);

  assert.equal(r.maxUnits, 10);
  assert.equal(r.adjBuildCostPerSf, 430); // 400 + ceil((12-5)/5)*15 = 430

  // Ellis relocation for RSO + R2
  assert.equal(r.ellisRelocation, 200000);
  assert.equal(r.ellisHoldMonths, 4);

  // Revenue
  assert.equal(r.grossRevenue, 12250000);
  approx(r.netRevenue, 11634250);

  // Construction: 10 * 1750 * 430 = 7,525,000
  assert.equal(r.constructionCost, 7525000);
  assert.equal(r.totalBuildCost, 7725000); // + 200K ellis

  // Total
  approx(r.totalCost, 9330596, 5);
  approx(r.profit, 2303654, 5);
  approx(r.margin, 19.80, 0.1);
});

test('RSO on R1 = no Ellis relocation', () => {
  const r = calculateProForma({
    lat: 34.2, lng: -118.4, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600, rsoRisk: true,
  });
  assert.equal(r.ellisRelocation, 0);
  assert.equal(r.ellisHoldMonths, 0);
});

test('RSO on LAND = no Ellis relocation', () => {
  const r = calculateProForma({
    lat: 34.3, lng: -118.5, lotSf: 10000, zone: 'LAND',
    price: 500000, exitPsf: 500, rsoRisk: true,
  });
  assert.equal(r.ellisRelocation, 0);
});

// ─── Layout Constraints ───

console.log('\nLayout Constraints (lot width × depth)');

test('50×200 R1 lot: density=8 but layout caps at 7', () => {
  const r = calculateProForma({
    lat: 34.4, lng: -118.6, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600, lw: 50, ld: 200,
  });
  // parcelDepth=1200/50=24, availDepth=200-20-4=176, floor(176/24)=7
  assert.equal(r.layoutMax, 7);
  assert.equal(r.maxUnits, 7); // capped by layout
  assert.equal(r.densityUnits, 8); // density would allow 8
  assert.ok(r.layoutNote.includes('7 parcels'));
});

test('R2 50×200 lot: layout uses 15ft front setback', () => {
  const r = calculateProForma({
    lat: 34.5, lng: -118.7, lotSf: 10000, zone: 'R2',
    price: 800000, exitPsf: 600, lw: 50, ld: 200,
  });
  // R2 frontSet=15, availDepth=200-15-4=181, parcelDepth=24, floor(181/24)=7
  // density=floor(10000/600)=16 → capped 10, layout=7 < 10 → max(2,7)=7
  assert.equal(r.layoutMax, 7);
  assert.equal(r.maxUnits, 7);
});

test('Narrow lot (30ft wide): layoutMax=0, too narrow note', () => {
  const r = calculateProForma({
    lat: 34.6, lng: -118.8, lotSf: 6000, zone: 'R1',
    price: 500000, exitPsf: 500, lw: 30, ld: 200,
  });
  // unitBuildW = 30 - 20 - 4 = 6 < 20 → too narrow
  assert.equal(r.layoutMax, 0);
  assert.ok(r.layoutNote.includes('too narrow'));
  // But maxUnits still uses density (layout=0 is not < maxUnits in a way that triggers the cap)
  assert.equal(r.maxUnits, 5); // density: floor(6000/1200)=5
});

test('Wide lot with no layout constraint', () => {
  const r = calculateProForma({
    lat: 34.7, lng: -118.9, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600, lw: 100, ld: 100,
  });
  // unitBuildW=100-20-4=76>=20 ✓
  // parcelDepth=1200/100=12, availDepth=100-20-4=76, floor(76/12)=6
  // 6 < 8 → maxUnits=max(2,6)=6
  assert.equal(r.layoutMax, 6);
  assert.equal(r.maxUnits, 6);
});

test('No lot dimensions: layout fields null, density used', () => {
  const r = calculateProForma({
    lat: 34.8, lng: -119.0, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600,
  });
  assert.equal(r.layoutMax, null);
  assert.equal(r.layoutNote, null);
  assert.equal(r.maxUnits, 8);
});

// ─── Edge Cases ───

console.log('\nEdge Cases');

test('Zero exit $/SF = zero revenue, negative margin', () => {
  const r = calculateProForma({
    lat: 35.0, lng: -119.1, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 0,
  });
  assert.equal(r.grossRevenue, 0);
  assert.equal(r.netRevenue, -40000); // just the fixed disposition costs
  assert.ok(r.profit < 0);
});

test('Missing exit $/SF treated as zero', () => {
  const r = calculateProForma({
    lat: 35.1, lng: -119.2, lotSf: 10000, zone: 'R1',
    price: 1000000,
  });
  assert.equal(r.grossRevenue, 0);
});

test('Caching: same lat/lng returns cached result', () => {
  const l = { lat: 99, lng: -99, lotSf: 10000, zone: 'R1', price: 1000000, exitPsf: 600 };
  const r1 = calculateProForma(l);
  const r2 = calculateProForma(l);
  assert.equal(r1, r2); // same object reference (cached)
});

test('clearProformaCaches resets cache', () => {
  const l = { lat: 98, lng: -98, lotSf: 10000, zone: 'R1', price: 1000000, exitPsf: 600 };
  const r1 = calculateProForma(l);
  clearProformaCaches();
  const r2 = calculateProForma(l);
  assert.notEqual(r1, r2); // different object (cache was cleared)
  assert.equal(r1.profit, r2.profit); // same values though
});

// ─── Accounting Identity ───

console.log('\nAccounting Identity Checks');

test('hard + soft = construction cost (no rounding error)', () => {
  // Test across several scenarios
  for (const zone of ['R1', 'R2', 'R3', 'R4', 'LAND']) {
    const r = calculateProForma({
      lat: 40 + Math.random(), lng: -118 - Math.random(),
      lotSf: 10000, zone, price: 1000000, exitPsf: 600,
    });
    assert.equal(r.hardCosts + r.softCosts, r.constructionCost,
      `hard+soft != construction for ${zone}`);
  }
});

test('totalCost = acquisition + totalBuildCost + totalCarry', () => {
  const r = calculateProForma({
    lat: 50, lng: -120, lotSf: 10000, zone: 'R1',
    price: 1500000, exitPsf: 600,
  });
  approx(r.totalCost, r.acquisition + r.totalBuildCost + r.totalCarry);
});

test('profit = netRevenue - totalCost', () => {
  const r = calculateProForma({
    lat: 51, lng: -121, lotSf: 10000, zone: 'R2',
    price: 800000, exitPsf: 700, slope: 10,
  });
  approx(r.profit, r.netRevenue - r.totalCost);
});

test('totalCarry = interest + propTax + insurance + origination', () => {
  const r = calculateProForma({
    lat: 52, lng: -122, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600,
  });
  approx(r.totalCarry,
    r.carryInterest + r.carryPropTax + r.insurance + r.originationFee);
});

// ─── BTR Pro Forma ───

console.log('\nBTR Pro Forma');

test('BTR with rent data: NOI, yield, DSCR', () => {
  const l = {
    lat: 60, lng: -130, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600, rentPsf: 2.0,
  };
  const r = calculateBTRProForma(l);

  // rentPerUnit = round(2.0 * 1750) = 3500
  assert.equal(r.rentPerUnit, 3500);
  assert.equal(r.units, 8);
  assert.equal(r.hasEstRent, true);

  // grossAnnualRent = 3500 * 12 * 8 = 336,000
  assert.equal(r.grossAnnualRent, 336000);

  // NOI = 336000 * 0.70 = 235,200 (default 30% opex)
  approx(r.annualNOI, 235200);

  // yield on cost
  assert.ok(r.yieldOnCost > 0);
  approx(r.yieldOnCost, r.annualNOI / r.totalCost, 0.001);

  // stabilized value = NOI / 0.055
  approx(r.stabilizedValue, 235200 / 0.055, 1);

  // DSCR
  const loanAmt = r.totalProjectCost * 0.70;
  const annualDS = loanAmt * 0.065;
  approx(r.dscr, r.annualNOI / annualDS, 0.01);

  // GRM = grossRevenue / grossAnnualRent
  approx(r.grm, r.grossRevenue / r.grossAnnualRent, 0.01);
});

test('BTR with estRentMonth fallback', () => {
  const l = {
    lat: 61, lng: -131, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600, estRentMonth: 3500,
  };
  const r = calculateBTRProForma(l);
  // rentPsf = 3500 / 1750 = 2.0
  assert.equal(r.rentPsf, 2);
  assert.equal(r.hasEstRent, true);
});

test('BTR with no rent data: zero NOI', () => {
  const l = {
    lat: 62, lng: -132, lotSf: 10000, zone: 'R1',
    price: 1000000, exitPsf: 600,
  };
  const r = calculateBTRProForma(l);
  assert.equal(r.rentPsf, 0);
  assert.equal(r.hasEstRent, false);
  assert.equal(r.grossAnnualRent, 0);
  assert.equal(r.annualNOI, 0);
  assert.equal(r.btrPencils, false);
});

test('BTR btrPencils requires DSCR >= 1.25 AND rent > 0', () => {
  // High rent scenario that should pencil
  const l = {
    lat: 63, lng: -133, lotSf: 10000, zone: 'R1',
    price: 500000, exitPsf: 600, rentPsf: 5.0,
  };
  const r = calculateBTRProForma(l);
  if (r.dscr >= 1.25) {
    assert.equal(r.btrPencils, true);
  } else {
    assert.equal(r.btrPencils, false);
  }
});

// ─── Summary ───

console.log(`\n${'─'.repeat(50)}`);
console.log(`\x1b[${failed ? '31' : '32'}m${passed} passed, ${failed} failed\x1b[0m\n`);
process.exit(failed ? 1 : 0);

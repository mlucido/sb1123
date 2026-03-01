// Pro forma calculations — SB 1123 townhome development
// Exported config object is mutated by main module when assumptions change.

export const proforma = {
  allInBuildPsf: 450,          // truly all-in: hard + soft + demo + subdiv + A&E
  avgUnitSf: 1750,
  txnCostPct: 4.7,
  fixedDispositionCosts: 40000,
  demoCost: 55000,             // flat demo cost (included in allInBuildPsf)
  subdivisionPsf: 10,
  aePsf: 5,
  softCostPct: 25,             // soft % of hard construction
  holdMonths: 24,
  carryRatePct: 9,
  insurance: 40000,
  originationPct: 1,
  ellisPerUnit: 20000,
};

// Memo caches — cleared when assumptions change
let _proformaCache = {};
let _btrCache = {};
export function clearProformaCaches(){ _proformaCache = {}; _btrCache = {}; }

export function getMinLotPerUnit(zone){
  if(zone === 'R1') return 1200;
  if(zone === 'LAND') return 1200;
  return 600;
}

export function getMaxUnits(l){
  if(!l.lotSf) return 1;
  const minPer = getMinLotPerUnit(l.zone);
  const byLot = Math.floor(l.lotSf / minPer);
  return Math.min(10, Math.max(1, byLot));
}

export function getSlopeAdjBuildCost(slope, base){
  if(!slope || slope <= 5) return base;
  return base + Math.ceil((slope - 5) / 5) * 15;
}

export function calculateProForma(l){
  var cacheKey = l.lat + ',' + l.lng;
  if(_proformaCache[cacheKey]) return _proformaCache[cacheKey];
  const densityUnits = getMaxUnits(l);
  let maxUnits = densityUnits;
  let layoutMax = null, layoutNote = null;
  if (l.lw && l.ld) {
    const driveW = 20;
    const sideSet = 4;
    const frontSet = (l.zone === 'R2' || l.zone === 'R3' || l.zone === 'R4') ? 15 : 20;
    const rearSet = 4;
    const unitBuildW = l.lw - driveW - sideSet;
    if (unitBuildW >= 20) {
      const parcelDepth = 1200 / l.lw;
      const availDepth = l.ld - frontSet - rearSet;
      layoutMax = Math.min(10, Math.floor(availDepth / parcelDepth));
      if (layoutMax > 0 && layoutMax < maxUnits) {
        maxUnits = Math.max(2, layoutMax);
        layoutNote = l.lw + "'\u00d7" + l.ld + "' \u2014 " + layoutMax + " parcels at " + parcelDepth.toFixed(1) + "' depth";
      }
    } else {
      layoutMax = 0;
      layoutNote = "Lot " + l.lw + "' too narrow \u2014 need 44'+ (20' drive + 4' setback + 20' unit)";
    }
  }
  const pf = proforma;
  const valuePerSf = l.clusterT1psf || l.subdivExitPsf || l.newconPpsf || l.exitPsf || 0;
  const adjBuildCostPerSf = getSlopeAdjBuildCost(l.slope, pf.allInBuildPsf);

  const effective_buildable_sf = maxUnits * pf.avgUnitSf;

  const grossPerUnit = valuePerSf * pf.avgUnitSf;
  const grossRevenue = maxUnits * grossPerUnit;
  const netRevenue = grossRevenue * (1 - pf.txnCostPct / 100) - pf.fixedDispositionCosts;

  const acquisition = l.price;
  const ellisRelocation = (l.rsoRisk && l.zone !== 'R1' && l.zone !== 'LAND')
    ? maxUnits * (pf.ellisPerUnit || 20000) : 0;
  const ellisHoldMonths = ellisRelocation > 0 ? 4 : 0;

  // All-in build: $450/SF includes hard, soft, demo, subdivision, A&E
  const constructionCost = maxUnits * pf.avgUnitSf * adjBuildCostPerSf;
  const totalBuildCost = constructionCost + ellisRelocation;

  // Component breakdown (for display — sums back to constructionCost)
  const demo = l.sqft > 0 ? pf.demoCost : 0;
  const subdivision = (pf.subdivisionPsf || 10) * effective_buildable_sf;
  const ae = (pf.aePsf || 5) * effective_buildable_sf;
  const constructionRemaining = constructionCost - demo - subdivision - ae;
  const hardCosts = constructionRemaining / (1 + (pf.softCostPct || 25) / 100);
  const softConstruction = constructionRemaining - hardCosts;
  const softCosts = softConstruction + demo + subdivision + ae;

  const holdMonths = pf.holdMonths + ellisHoldMonths;
  const avgLoanOutstanding = totalBuildCost * 0.5;
  const carryInterest = avgLoanOutstanding * (pf.carryRatePct / 100) * (holdMonths / 12);
  const carryPropTax = acquisition * 0.011 * (holdMonths / 12);
  const insurance = pf.insurance || 40000;
  const originationFee = totalBuildCost * ((pf.originationPct || 1) / 100);
  const totalCarry = carryInterest + carryPropTax + insurance + originationFee;

  const totalCost = acquisition + totalBuildCost + totalCarry;
  const profit = netRevenue - totalCost;
  const margin_on_revenue = netRevenue > 0 ? ((profit / netRevenue) * 100) : 0;

  const land_basis_psf = effective_buildable_sf > 0 ? (l.price / effective_buildable_sf) : 0;

  const target_margin = 0.30;
  const nr = netRevenue;
  const target_total_cost = nr * (1 - target_margin);
  const build_carry = avgLoanOutstanding * (pf.carryRatePct / 100) * (holdMonths / 12);
  const build_plus_soft = totalBuildCost + build_carry + insurance + originationFee;
  const propTaxFactor = 0.011 * (holdMonths / 12);
  const max_offer = (target_total_cost - build_plus_soft) / (1 + propTaxFactor);

  const lot_efficiency = l.lotSf > 0 ? (effective_buildable_sf / l.lotSf) : 0;
  const return_on_cost = totalCost > 0 ? ((profit / totalCost) * 100) : 0;

  const totalProjectCost = acquisition + totalBuildCost;

  var result = {
    maxUnits,
    densityUnits,
    layoutMax,
    layoutNote,
    grossRevenue,
    netRevenue,
    acquisition,
    demo,
    constructionCost,
    hardCosts: Math.round(hardCosts),
    softCosts: Math.round(softCosts),
    totalBuildCost,
    totalProjectCost,
    totalCost,
    profit,
    margin: margin_on_revenue,
    margin_on_revenue,
    return_on_cost,
    pricePerUnit: Math.round(acquisition / maxUnits),
    effective_buildable_sf: Math.round(effective_buildable_sf),
    land_basis_psf: Math.round(land_basis_psf),
    max_offer: Math.round(max_offer),
    lot_efficiency,
    adjBuildCostPerSf,
    totalCarry: Math.round(totalCarry),
    carryInterest: Math.round(carryInterest),
    carryPropTax: Math.round(carryPropTax),
    insurance: Math.round(insurance),
    originationFee: Math.round(originationFee),
    ellisRelocation: Math.round(ellisRelocation),
    ellisHoldMonths,
  };
  _proformaCache[cacheKey] = result;
  return result;
}

export function calculateBTRProForma(l){
  var cacheKey = l.lat + ',' + l.lng;
  if(_btrCache[cacheKey]) return _btrCache[cacheKey];
  const pf = calculateProForma(l);

  const opexRatio = parseFloat((document.getElementById('btrOpex')||{}).value) || 0.30;
  const capRate = parseFloat((document.getElementById('btrCapRate')||{}).value) || 0.055;
  const refiLTV = parseFloat((document.getElementById('btrLTV')||{}).value) || 0.70;
  const refiRate = parseFloat((document.getElementById('btrRate')||{}).value) || 0.065;

  const rentPsf = l.rentPsf || (l.estRentMonth > 0 ? l.estRentMonth / 1750 : 0);
  const hasEstRent = rentPsf > 0;
  const rentPerUnit = Math.round(rentPsf * proforma.avgUnitSf);
  const units = pf.maxUnits;
  const totalCost = pf.totalCost;

  const grossAnnualRent = rentPerUnit * 12 * units;
  const annualNOI = grossAnnualRent * (1 - opexRatio);

  const yieldOnCost = totalCost > 0 ? annualNOI / totalCost : 0;
  const stabilizedValue = capRate > 0 ? annualNOI / capRate : 0;

  const loanAmount = pf.totalProjectCost * 0.70;
  const annualDebtService = loanAmount * 0.065;
  const dscr = annualDebtService > 0 ? annualNOI / annualDebtService : 0;

  const refiLoanAmount = stabilizedValue * refiLTV;
  const refiAnnualDS = refiLoanAmount * refiRate;
  const cashOutRefi = refiLoanAmount - totalCost;
  const equityAfterRefi = totalCost - refiLoanAmount;
  const cashFlow = annualNOI - annualDebtService;
  const cashOnCash = equityAfterRefi > 0 ? cashFlow / equityAfterRefi : 0;

  const grm = grossAnnualRent > 0 ? pf.grossRevenue / grossAnnualRent : 0;

  const btrPencils = dscr >= 1.25 && rentPsf > 0;

  var btrResult = {
    ...pf,
    rentPerUnit,
    rentPsf,
    hasEstRent,
    grm,
    grossAnnualRent,
    annualNOI,
    yieldOnCost,
    stabilizedValue,
    loanAmount,
    annualDebtService,
    dscr,
    refiLoanAmount,
    cashOutRefi,
    cashFlow,
    cashOnCash,
    btrPencils,
    opexRatio,
    capRate,
    refiLTV,
    units,
  };
  _btrCache[cacheKey] = btrResult;
  return btrResult;
}

// Export module — Excel model, OM export, CSV export
import { proforma, calculateProForma, calculateBTRProForma } from './proforma.js';

var _deps = {};
export function initExport(deps) {
  _deps = deps;
}

function sizeEquityAndDebt(askingPrice, units, avgUnitSF, buildCostPSF, exitPSF, monthlyRent) {
  const SOFT_PCT = 0.25;
  const DEMO = 55000;
  const SUBDIV = 100000;
  const AE = 150000;
  const TAX_RATE = 0.011;
  const INS_ANNUAL = 20000;
  const AM_MONTHLY = 3000;
  const DM_MONTHLY = 5000;
  const ACQ_FEE_PCT = 0.02;
  const ORIG_FEE_PCT = 0.02;
  const EQUITY_PCT = 0.26;
  const PRE_DEV_MO = 6;
  const CONSTR_MO = 12;
  const SALE_MO = 6;

  const buildableSF = units * avgUnitSF;
  const hardCosts = buildableSF * buildCostPSF;
  const softCosts = hardCosts * SOFT_PCT;
  const totalDev = hardCosts + softCosts + DEMO + SUBDIV + AE;

  const monthlyTax = askingPrice * TAX_RATE / 12;
  const monthlyIns = INS_ANNUAL / 12;
  const preDev = (monthlyTax + monthlyIns + AM_MONTHLY) * PRE_DEV_MO;
  const constr = (monthlyTax + monthlyIns + AM_MONTHLY + DM_MONTHLY) * CONSTR_MO;
  const sale = (monthlyTax + monthlyIns + AM_MONTHLY) * SALE_MO;
  const totalCarry = preDev + constr + sale;

  const acqFee = askingPrice * ACQ_FEE_PCT;

  const baseCosts = askingPrice + totalDev + totalCarry + acqFee;
  const totalCost = baseCosts / (1 - (1 - EQUITY_PCT) * ORIG_FEE_PCT);

  const equity = Math.ceil(totalCost * EQUITY_PCT / 10000) * 10000;
  const debt = Math.round(totalCost - equity);

  return { equity, debt, totalCost: equity + debt };
}

function exportCSV(){
  const filtered = _deps.getFilteredListings();
  if(!filtered.length) return;
  const headers = ['Fav','Address','Zone','Price','Lot SF','Lot Width','Units','Exit $/SF','Sale/Unit','Buy/Unit','Build/Unit','Profit','Margin %','Slope %','DOM','City','AIN','Notes','URL'];
  const favs = _deps.loadFavorites();
  const rows = filtered.map(l=>[
    favs[_deps.listingKey(l)]?'*':'', l.address, l.zone, l.price,
    l.lotSf||'', l.lw||'', l.maxUnits, l.clusterT1psf||l.newconPpsf||l.exitPsf||0,
    l.salePerUnit||'', l.pricePerUnit||'', l.buildPerUnit||'',
    Math.round(l.estProfit||0), (l.estMargin||0).toFixed(1),
    l.slope!=null?l.slope:'', l.dom!==null?l.dom:'', l.city||'',
    l.ain||'', (favs[_deps.listingKey(l)]||{}).notes||'', l.url||''
  ]);
  const csv = [headers,...rows].map(r=>r.map(v=>`"${v}"`).join(',')).join('\n');
  const blob = new Blob([csv], {type:'text/csv'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href=url; a.download='sb1123_deals_export.csv'; a.click();
  URL.revokeObjectURL(url);
}

// ── Excel Export Helpers ──
function colLetter(n) {
  var s = '';
  while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
  return s;
}
function setVal(ws, addr, value, numFmt) {
  var cell = ws.getCell(addr);
  cell.value = value;
  if (numFmt) cell.numFmt = numFmt;
}
function setFormula(ws, addr, formula, result, numFmt) {
  var cell = ws.getCell(addr);
  cell.value = { formula: formula, result: result != null ? result : 0 };
  if (numFmt) cell.numFmt = numFmt;
}
function sectionHeader(ws, row, col, text) {
  var cell = ws.getCell(colLetter(col) + row);
  cell.value = text;
  cell.font = { bold: true, size: 11 };
}
function labelCell(ws, row, col, text) {
  var cell = ws.getCell(colLetter(col) + row);
  cell.value = text;
  cell.font = { color: { argb: 'FF666666' } };
}
var _hdrFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1B2A4A' } };
var _hdrFont = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11 };
var _inputFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFDE7' } };
var _borderThin = { style: 'thin', color: { argb: 'FFCCCCCC' } };
var _borders = { top: _borderThin, bottom: _borderThin, left: _borderThin, right: _borderThin };
function inputCell(ws, addr, value, numFmt) {
  var cell = ws.getCell(addr);
  cell.value = value;
  cell.fill = _inputFill;
  cell.border = _borders;
  cell.font = { color: { argb: 'FF003078' } };
  if (numFmt) cell.numFmt = numFmt;
}
function buildAssumptionsTab(wb, l, pf, ed, exitPSF, monthlyRent) {
  var ws = wb.addWorksheet('Assumptions');
  ws.getColumn(1).width = 2;
  ws.getColumn(2).width = 28;
  ws.getColumn(3).width = 20;
  ws.getColumn(4).width = 3;
  ws.getColumn(5).width = 2;
  ws.getColumn(6).width = 24;
  ws.getColumn(7).width = 20;

  var units = pf.maxUnits;
  var avgUnitSF = proforma.avgUnitSf;
  var lotWidth = l.lw || Math.round(Math.sqrt((l.lotSf || 10000) * 0.33));
  var lotDepth = l.ld || Math.round((l.lotSf || 10000) / lotWidth);
  var slopeDecimal = (l.slope || 0) / 100;
  var bedsBaths = (l.beds || '') + ' / ' + (l.baths || '');
  var buildableSF = units * avgUnitSF;
  var buildCostPSF = buildableSF > 0 ? Math.round(pf.hardCosts / buildableSF) : 0;
  var hardCosts = buildableSF * buildCostPSF;
  var grossRevenue = units * avgUnitSF * exitPSF;
  var txCostPct = proforma.txnCostPct / 100;
  var start = new Date();
  start.setDate(start.getDate() + 60);
  start.setDate(1);

  // Title
  ws.mergeCells('B2:C2');
  var titleCell = ws.getCell('B2');
  titleCell.value = 'SB 1123 Pro Forma';
  titleCell.font = { bold: true, size: 14 };

  // ── Left: Property & Development ──
  ws.getCell('B4').value = 'PROPERTY';
  ws.getCell('B4').font = _hdrFont; ws.getCell('B4').fill = _hdrFill;
  ws.getCell('C4').fill = _hdrFill;

  labelCell(ws, 5, 2, 'Address');       inputCell(ws, 'C5', l.address || '');
  labelCell(ws, 6, 2, 'City, Zip');     inputCell(ws, 'C6', (l.city || '') + (l.zip ? ', ' + l.zip : ''));
  labelCell(ws, 7, 2, 'Zoning');        inputCell(ws, 'C7', (l.zone || 'R1').toUpperCase());
  labelCell(ws, 8, 2, 'Lot SF');        inputCell(ws, 'C8', l.lotSf || 0, '#,##0');
  labelCell(ws, 9, 2, 'Lot Width');     inputCell(ws, 'C9', lotWidth, '#,##0');
  labelCell(ws, 10, 2, 'Lot Depth');    inputCell(ws, 'C10', lotDepth, '#,##0');
  labelCell(ws, 11, 2, 'Slope');        inputCell(ws, 'C11', slopeDecimal, '0.0%');
  labelCell(ws, 12, 2, 'Beds / Baths'); inputCell(ws, 'C12', bedsBaths);
  labelCell(ws, 13, 2, 'DOM');          inputCell(ws, 'C13', l.dom || 0, '#,##0');

  ws.getCell('B15').value = 'ACQUISITION';
  ws.getCell('B15').font = _hdrFont; ws.getCell('B15').fill = _hdrFill;
  ws.getCell('C15').fill = _hdrFill;

  labelCell(ws, 16, 2, 'Purchase Price'); inputCell(ws, 'C16', l.price || 0, '$#,##0');
  labelCell(ws, 17, 2, 'Txn Cost %');     inputCell(ws, 'C17', 0.01, '0.0%');
  labelCell(ws, 18, 2, 'Txn Cost $');     setFormula(ws, 'C18', 'C16*C17', (l.price || 0) * 0.01, '$#,##0');

  ws.getCell('B19').value = 'DEVELOPMENT';
  ws.getCell('B19').font = _hdrFont; ws.getCell('B19').fill = _hdrFill;
  ws.getCell('C19').fill = _hdrFill;

  labelCell(ws, 20, 2, 'Units');           inputCell(ws, 'C20', units, '#,##0');
  labelCell(ws, 21, 2, 'Avg Unit SF');     inputCell(ws, 'C21', avgUnitSF, '#,##0');
  labelCell(ws, 22, 2, 'Buildable SF');    setFormula(ws, 'C22', 'C20*C21', buildableSF, '#,##0');
  labelCell(ws, 23, 2, 'Hard Cost $/SF');  inputCell(ws, 'C23', buildCostPSF, '$#,##0');
  labelCell(ws, 24, 2, 'Hard Costs');      setFormula(ws, 'C24', 'C22*C23', hardCosts, '$#,##0');
  labelCell(ws, 25, 2, 'Soft Cost %');     inputCell(ws, 'C25', 0.25, '0.0%');
  labelCell(ws, 26, 2, 'Soft Costs');      setFormula(ws, 'C26', 'C24*C25', hardCosts * 0.25, '$#,##0');
  labelCell(ws, 27, 2, 'Demo');            inputCell(ws, 'C27', 55000, '$#,##0');
  labelCell(ws, 28, 2, 'Subdivision');     setFormula(ws, 'C28', '10*C22', 10 * buildableSF, '$#,##0');
  labelCell(ws, 29, 2, 'A&E');             inputCell(ws, 'C29', 150000, '$#,##0');
  labelCell(ws, 30, 2, 'Total Dev Costs'); setFormula(ws, 'C30', 'C24+C26+C27+C28+C29', hardCosts + hardCosts * 0.25 + 55000 + 10 * buildableSF + 150000, '$#,##0');
  ws.getCell('C30').font = { bold: true };

  ws.getCell('B34').value = 'EXIT';
  ws.getCell('B34').font = _hdrFont; ws.getCell('B34').fill = _hdrFill;
  ws.getCell('C34').fill = _hdrFill;

  labelCell(ws, 35, 2, 'Exit $/SF');       inputCell(ws, 'C35', exitPSF, '$#,##0');
  labelCell(ws, 36, 2, 'Gross Revenue');   setFormula(ws, 'C36', 'C20*C21*C35', grossRevenue, '$#,##0');
  labelCell(ws, 37, 2, 'Txn Cost %');      inputCell(ws, 'C37', txCostPct, '0.0%');
  labelCell(ws, 38, 2, 'Net Proceeds');    setFormula(ws, 'C38', 'C36*(1-C37)', grossRevenue * (1 - txCostPct), '$#,##0');
  ws.getCell('C38').font = { bold: true };

  ws.getCell('B41').value = 'FUND STRUCTURE';
  ws.getCell('B41').font = _hdrFont; ws.getCell('B41').fill = _hdrFill;
  ws.getCell('C41').fill = _hdrFill;

  labelCell(ws, 42, 2, 'LP Pref Rate');      inputCell(ws, 'C42', 0.08, '0.0%');
  labelCell(ws, 43, 2, 'GP Promote %');       inputCell(ws, 'C43', 0.20, '0.0%');
  labelCell(ws, 44, 2, 'GP Co-Invest %');     inputCell(ws, 'C44', 0.05, '0.0%');

  ws.getCell('B47').value = 'BTR HOLD';
  ws.getCell('B47').font = _hdrFont; ws.getCell('B47').fill = _hdrFill;
  ws.getCell('C47').fill = _hdrFill;

  labelCell(ws, 48, 2, 'BTR Rent/Mo');     inputCell(ws, 'C48', monthlyRent, '$#,##0');
  labelCell(ws, 50, 2, 'BTR OpEx Ratio');  inputCell(ws, 'C50', 0.30, '0.0%');
  labelCell(ws, 51, 2, 'BTR Cap Rate');    inputCell(ws, 'C51', 0.055, '0.0%');
  labelCell(ws, 52, 2, 'BTR Refi LTV');    inputCell(ws, 'C52', 0.70, '0.0%');
  labelCell(ws, 53, 2, 'BTR Perm Rate');   inputCell(ws, 'C53', 0.065, '0.0%');
  labelCell(ws, 54, 2, 'BTR Rent Growth'); inputCell(ws, 'C54', 0.03, '0.0%');

  // ── Right: Timeline & Capital ──
  ws.getCell('F4').value = 'TIMELINE';
  ws.getCell('F4').font = _hdrFont; ws.getCell('F4').fill = _hdrFill;
  ws.getCell('G4').fill = _hdrFill;

  labelCell(ws, 5, 6, 'Pre-Dev Months');      inputCell(ws, 'G5', 6, '#,##0');
  labelCell(ws, 6, 6, 'Construction Months');  inputCell(ws, 'G6', 12, '#,##0');
  labelCell(ws, 7, 6, 'Sale Months');          inputCell(ws, 'G7', 6, '#,##0');
  labelCell(ws, 8, 6, 'Hold Months');          setFormula(ws, 'G8', 'G5+G6+G7', 24, '#,##0');
  ws.getCell('G8').font = { bold: true };
  labelCell(ws, 9, 6, 'Start Date');           inputCell(ws, 'G9', start, 'MMM YYYY');

  ws.getCell('F13').value = 'CAPITAL STRUCTURE';
  ws.getCell('F13').font = _hdrFont; ws.getCell('F13').fill = _hdrFill;
  ws.getCell('G13').fill = _hdrFill;

  labelCell(ws, 14, 6, 'Equity');              setFormula(ws, 'G14', 'CEILING((C16+C18+C30+G30+G34)/(1-(1-G17)*G19)*G17,10000)', ed.equity, '$#,##0');
  ws.getCell('G14').font = { bold: true };
  labelCell(ws, 15, 6, 'Debt');                setFormula(ws, 'G15', '(C16+C18+C30+G30+G34)/(1-(1-G17)*G19)-G14', ed.debt, '$#,##0');
  ws.getCell('G15').font = { bold: true };
  labelCell(ws, 16, 6, 'Total Project Cost');  setFormula(ws, 'G16', 'G14+G15', ed.equity + ed.debt, '$#,##0');
  ws.getCell('G16').font = { bold: true };
  labelCell(ws, 17, 6, 'Target Equity %');     inputCell(ws, 'G17', 0.26, '0.0%');
  labelCell(ws, 18, 6, 'Interest Rate');       inputCell(ws, 'G18', 0.09, '0.0%');
  labelCell(ws, 19, 6, 'Orig Fee %');          inputCell(ws, 'G19', 0.02, '0.0%');
  labelCell(ws, 20, 6, 'Orig Fee $');          setFormula(ws, 'G20', 'G15*G19', ed.debt * 0.02, '$#,##0');

  ws.getCell('F25').value = 'CARRY COSTS';
  ws.getCell('F25').font = _hdrFont; ws.getCell('F25').fill = _hdrFill;
  ws.getCell('G25').fill = _hdrFill;

  labelCell(ws, 26, 6, 'Prop Tax Rate');    inputCell(ws, 'G26', 0.011, '0.000%');
  labelCell(ws, 27, 6, 'Monthly Tax');      setFormula(ws, 'G27', 'C16*G26/12', (l.price || 0) * 0.011 / 12, '$#,##0');
  labelCell(ws, 28, 6, 'Insurance Annual'); inputCell(ws, 'G28', 20000, '$#,##0');
  labelCell(ws, 29, 6, 'Monthly Insurance'); setFormula(ws, 'G29', 'G28/12', 20000 / 12, '$#,##0');
  labelCell(ws, 30, 6, 'Total Carry');       setFormula(ws, 'G30', '(G27+G29+G35)*(G5+G7)+(G27+G29+G35+G36)*G6', 0, '$#,##0');
  ws.getCell('G30').font = { bold: true };

  ws.getCell('F32').value = 'FEES';
  ws.getCell('F32').font = _hdrFont; ws.getCell('F32').fill = _hdrFill;
  ws.getCell('G32').fill = _hdrFill;

  labelCell(ws, 33, 6, 'Acq Fee %');       inputCell(ws, 'G33', 0.02, '0.0%');
  labelCell(ws, 34, 6, 'Acq Fee $');       setFormula(ws, 'G34', 'C16*G33', (l.price || 0) * 0.02, '$#,##0');
  labelCell(ws, 35, 6, 'AM Monthly');       inputCell(ws, 'G35', 3000, '$#,##0');
  labelCell(ws, 36, 6, 'DM Monthly');       inputCell(ws, 'G36', 5000, '$#,##0');
  labelCell(ws, 37, 6, 'Disp Fee %');      inputCell(ws, 'G37', 0.015, '0.0%');
  labelCell(ws, 38, 6, 'Disp Fee $');      setFormula(ws, 'G38', 'C36*G37', grossRevenue * 0.015, '$#,##0');

  // Print setup
  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'portrait', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildSourcesUsesTab(wb, l, ed, pf) {
  var ws = wb.addWorksheet('Sources & Uses');
  ws.getColumn(1).width = 2;
  ws.getColumn(2).width = 26;
  ws.getColumn(3).width = 18;
  ws.getColumn(4).width = 12;
  ws.getColumn(5).width = 3;
  ws.getColumn(6).width = 26;
  ws.getColumn(7).width = 18;
  ws.getColumn(8).width = 12;

  var units = pf.maxUnits;
  var avgUnitSF = proforma.avgUnitSf;
  var buildCostPSF = pf.adjBuildCostPerSf;
  var buildableSF = units * avgUnitSF;
  var hardCosts = buildableSF * buildCostPSF;
  var softCosts = hardCosts * 0.25;
  var price = l.price || 0;
  var monthlyTax = price * 0.011 / 12;

  // Title
  ws.mergeCells('B2:H2');
  ws.getCell('B2').value = 'Sources & Uses of Funds';
  ws.getCell('B2').font = { bold: true, size: 14 };

  // ── SOURCES ──
  ws.getCell('B4').value = 'SOURCES';
  ws.getCell('B4').font = _hdrFont; ws.getCell('B4').fill = _hdrFill;
  ws.getCell('C4').value = 'Amount'; ws.getCell('C4').font = _hdrFont; ws.getCell('C4').fill = _hdrFill;
  ws.getCell('D4').value = '% of Total'; ws.getCell('D4').font = _hdrFont; ws.getCell('D4').fill = _hdrFill;

  sectionHeader(ws, 5, 2, 'Senior Debt');
  labelCell(ws, 6, 2, '  Construction Loan');
  setFormula(ws, 'C6', 'Assumptions!G15', ed.debt, '$#,##0');
  labelCell(ws, 7, 2, '  Origination Fee');
  setFormula(ws, 'C7', 'Assumptions!G20', ed.debt * 0.02, '$#,##0');
  ws.getCell('C7').font = { color: { argb: 'FF999999' }, italic: true };
  labelCell(ws, 8, 2, '  Interest Payments');
  setFormula(ws, 'C8', "'Cash Flow'!AA39", 0, '$#,##0');

  sectionHeader(ws, 10, 2, 'Equity');
  labelCell(ws, 11, 2, '  LP Equity');
  setFormula(ws, 'C11', 'Assumptions!G14*(1-Assumptions!C44)', ed.equity * 0.95, '$#,##0');
  labelCell(ws, 12, 2, '  GP Co-Invest');
  setFormula(ws, 'C12', 'Assumptions!G14*Assumptions!C44', ed.equity * 0.05, '$#,##0');

  labelCell(ws, 14, 2, 'TOTAL SOURCES');
  ws.getCell('B14').font = { bold: true };
  setFormula(ws, 'C14', 'C6+C8+C11+C12', ed.debt + ed.equity, '$#,##0');
  ws.getCell('C14').font = { bold: true };
  ws.getCell('C14').border = { top: { style: 'double', color: { argb: 'FF000000' } } };
  setFormula(ws, 'D14', 'C14/C14', 1, '0.0%');

  // Source % of total
  setFormula(ws, 'D6', 'C6/C$14', ed.debt / (ed.debt + ed.equity), '0.0%');
  setFormula(ws, 'D8', 'C8/C$14', 0, '0.0%');
  setFormula(ws, 'D11', 'C11/C$14', ed.equity * 0.95 / (ed.debt + ed.equity), '0.0%');
  setFormula(ws, 'D12', 'C12/C$14', ed.equity * 0.05 / (ed.debt + ed.equity), '0.0%');

  // ── USES ──
  ws.getCell('F4').value = 'USES';
  ws.getCell('F4').font = _hdrFont; ws.getCell('F4').fill = _hdrFill;
  ws.getCell('G4').value = 'Amount'; ws.getCell('G4').font = _hdrFont; ws.getCell('G4').fill = _hdrFill;
  ws.getCell('H4').value = '% of Total'; ws.getCell('H4').font = _hdrFont; ws.getCell('H4').fill = _hdrFill;

  sectionHeader(ws, 5, 6, 'Land Acquisition');
  labelCell(ws, 6, 6, '  Purchase Price');
  setFormula(ws, 'G6', 'Assumptions!C16', price, '$#,##0');
  labelCell(ws, 7, 6, '  Acq Fee');
  setFormula(ws, 'G7', 'Assumptions!G34', price * 0.02, '$#,##0');
  labelCell(ws, 8, 6, '  Txn Costs');
  setFormula(ws, 'G8', 'Assumptions!C18', price * 0.01, '$#,##0');

  sectionHeader(ws, 9, 6, 'Development');
  labelCell(ws, 10, 6, '  Hard Costs');
  setFormula(ws, 'G10', 'Assumptions!C24', hardCosts, '$#,##0');
  labelCell(ws, 11, 6, '  Soft Costs');
  setFormula(ws, 'G11', 'Assumptions!C26', softCosts, '$#,##0');
  labelCell(ws, 12, 6, '  Demo');
  setFormula(ws, 'G12', 'Assumptions!C27', 55000, '$#,##0');
  labelCell(ws, 13, 6, '  Subdivision');
  setFormula(ws, 'G13', 'Assumptions!C28', 100000, '$#,##0');
  labelCell(ws, 14, 6, '  A&E');
  setFormula(ws, 'G14', 'Assumptions!C29', 150000, '$#,##0');

  sectionHeader(ws, 16, 6, 'Carry');
  labelCell(ws, 17, 6, '  Interest Payments');
  setFormula(ws, 'G17', "'Cash Flow'!AA39", 0, '$#,##0'); // Total interest paid from CF
  labelCell(ws, 18, 6, '  Property Tax');
  setFormula(ws, 'G18', 'Assumptions!G27*Assumptions!G8', monthlyTax * 24, '$#,##0');
  labelCell(ws, 19, 6, '  Insurance');
  setFormula(ws, 'G19', 'Assumptions!G28*(Assumptions!G8/12)', 20000 * 2, '$#,##0');
  labelCell(ws, 20, 6, '  Asset Mgmt');
  setFormula(ws, 'G20', 'Assumptions!G35*Assumptions!G8', 3000 * 24, '$#,##0');
  labelCell(ws, 21, 6, '  Dev Mgmt');
  setFormula(ws, 'G21', 'Assumptions!G36*Assumptions!G6', 5000 * 12, '$#,##0');

  sectionHeader(ws, 23, 6, 'Financing');
  labelCell(ws, 24, 6, '  Origination Fee');
  setFormula(ws, 'G24', 'Assumptions!G20', ed.debt * 0.02, '$#,##0');

  labelCell(ws, 26, 6, 'TOTAL USES');
  ws.getCell('F26').font = { bold: true };
  setFormula(ws, 'G26', 'G6+G7+G8+G10+G11+G12+G13+G14+G17+G18+G19+G20+G21+G24', 0, '$#,##0');
  ws.getCell('G26').font = { bold: true };
  ws.getCell('G26').border = { top: { style: 'double', color: { argb: 'FF000000' } } };
  setFormula(ws, 'H26', 'G26/G26', 1, '0.0%');

  // Uses % of total
  setFormula(ws, 'H6', 'G6/G$26', 0, '0.0%');
  setFormula(ws, 'H7', 'G7/G$26', 0, '0.0%');
  setFormula(ws, 'H8', 'G8/G$26', 0, '0.0%');
  setFormula(ws, 'H10', 'G10/G$26', 0, '0.0%');
  setFormula(ws, 'H11', 'G11/G$26', 0, '0.0%');
  setFormula(ws, 'H12', 'G12/G$26', 0, '0.0%');
  setFormula(ws, 'H13', 'G13/G$26', 0, '0.0%');
  setFormula(ws, 'H14', 'G14/G$26', 0, '0.0%');
  setFormula(ws, 'H17', 'G17/G$26', 0, '0.0%');
  setFormula(ws, 'H18', 'G18/G$26', 0, '0.0%');
  setFormula(ws, 'H19', 'G19/G$26', 0, '0.0%');
  setFormula(ws, 'H20', 'G20/G$26', 0, '0.0%');
  setFormula(ws, 'H21', 'G21/G$26', 0, '0.0%');
  setFormula(ws, 'H24', 'G24/G$26', 0, '0.0%');

  // Check row
  labelCell(ws, 28, 2, 'CHECK (Sources - Uses)');
  setFormula(ws, 'C28', 'C14-G26', 0, '$#,##0');
  ws.getCell('C28').font = { bold: true, color: { argb: 'FFFF0000' } };

  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'landscape', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildCashFlowTab(wb, l, ed, pf) {
  var ws = wb.addWorksheet('Cash Flow');
  var MONTHS = 24;
  var totalCol = MONTHS + 3; // col index for TOTAL (months in cols 3..26, total in 27 = AA)
  var totalLtr = colLetter(totalCol); // AA

  ws.getColumn(1).width = 2;
  ws.getColumn(2).width = 28;
  for (var mi = 3; mi <= totalCol; mi++) ws.getColumn(mi).width = 12;

  var price = l.price || 0;
  var units = pf.maxUnits;
  var avgUnitSF = proforma.avgUnitSf;
  var buildCostPSF = pf.adjBuildCostPerSf;
  var buildableSF = units * avgUnitSF;
  var hardCosts = buildableSF * buildCostPSF;
  var softCosts = hardCosts * 0.25;
  var exitPSF = l.clusterT1psf || l.subdivExitPsf || l.newconPpsf || l.exitPsf || 0;
  var grossRevenue = units * avgUnitSF * exitPSF;
  var txCostPct = proforma.txnCostPct / 100;

  // Row 1: Title
  ws.mergeCells('B1:' + totalLtr + '1');
  ws.getCell('B1').value = 'Monthly Cash Flow';
  ws.getCell('B1').font = { bold: true, size: 14 };

  // Row 2: Month headers
  var hdrRow = ws.getRow(2);
  hdrRow.getCell(2).value = '';
  for (var m = 0; m < MONTHS; m++) {
    var c = hdrRow.getCell(m + 3);
    c.value = 'Month ' + m;
    c.font = _hdrFont; c.fill = _hdrFill;
    c.alignment = { horizontal: 'center' };
  }
  var tc = hdrRow.getCell(totalCol);
  tc.value = 'TOTAL'; tc.font = _hdrFont; tc.fill = _hdrFill;
  tc.alignment = { horizontal: 'center' };

  // Row 3: Phase labels
  var phaseRow = ws.getRow(3);
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    // Phase: IF(month < G5, "Pre-Dev", IF(month < G5+G6, "Construction", "Sale"))
    setFormula(ws, cl + '3',
      'IF(' + m + '<Assumptions!$G$5,"Pre-Dev",IF(' + m + '<Assumptions!$G$5+Assumptions!$G$6,"Construction","Sale"))',
      m < 6 ? 'Pre-Dev' : (m < 18 ? 'Construction' : 'Sale'));
    ws.getCell(cl + '3').font = { italic: true, color: { argb: 'FF888888' } };
    ws.getCell(cl + '3').alignment = { horizontal: 'center' };
  }

  // Helper: formula for each month column
  function monthFormula(row, formulaFn, resultFn) {
    for (var m = 0; m < MONTHS; m++) {
      var cl = colLetter(m + 3);
      setFormula(ws, cl + row, formulaFn(m, cl), resultFn(m), '$#,##0');
    }
    // Total column = SUM
    setFormula(ws, totalLtr + row, 'SUM(C' + row + ':' + colLetter(MONTHS + 2) + row + ')', 0, '$#,##0');
    ws.getCell(totalLtr + row).font = { bold: true };
  }

  // ── Row 5: SOURCES header ──
  sectionHeader(ws, 5, 2, 'SOURCES');
  ws.getCell('B5').fill = _hdrFill; ws.getCell('B5').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '5').fill = _hdrFill; }
  ws.getCell(totalLtr + '5').fill = _hdrFill;

  // Row 6: LP Equity Call — Month 0 only
  labelCell(ws, 6, 2, '  LP Equity Call');
  var lpEquityVal = ed.equity * 0.95;
  monthFormula(6,
    function(m) { return m === 0 ? 'Assumptions!G14*(1-Assumptions!C44)' : '0'; },
    function(m) { return m === 0 ? lpEquityVal : 0; }
  );

  // Row 7: GP Co-Invest Call — Month 0 only
  labelCell(ws, 7, 2, '  GP Co-Invest Call');
  var gpCoInvestVal = ed.equity * 0.05;
  monthFormula(7,
    function(m) { return m === 0 ? 'Assumptions!G14*Assumptions!C44' : '0'; },
    function(m) { return m === 0 ? gpCoInvestVal : 0; }
  );

  // Row 8: Construction Draws — balancing entry (total uses - equity for that month)
  labelCell(ws, 8, 2, '  Construction Draws');
  monthFormula(8,
    function(m, cl) { return 'MAX(0,' + cl + '32-' + cl + '6-' + cl + '7)'; },
    function() { return 0; }
  );

  // Row 9: Total Sources
  labelCell(ws, 9, 2, 'Total Sources');
  ws.getCell('B9').font = { bold: true };
  monthFormula(9,
    function(m, cl) { return cl + '6+' + cl + '7+' + cl + '8'; },
    function() { return 0; }
  );

  // ── Row 11: USES - DEVELOPMENT ──
  sectionHeader(ws, 11, 2, 'USES - DEVELOPMENT');
  ws.getCell('B11').fill = _hdrFill; ws.getCell('B11').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '11').fill = _hdrFill; }
  ws.getCell(totalLtr + '11').fill = _hdrFill;

  // Row 12: Land Acquisition + Txn Costs — Month 0
  labelCell(ws, 12, 2, '  Land Acquisition + Txn');
  monthFormula(12,
    function(m) { return m === 0 ? 'Assumptions!C16+Assumptions!C18' : '0'; },
    function(m) { return m === 0 ? price + price * 0.01 : 0; }
  );

  // Row 13: Hard Costs — construction months, spread evenly
  labelCell(ws, 13, 2, '  Hard Costs');
  monthFormula(13,
    function(m) { return 'IF(AND(' + m + '>=Assumptions!$G$5,' + m + '<Assumptions!$G$5+Assumptions!$G$6),Assumptions!C24/Assumptions!$G$6,0)'; },
    function(m) { return (m >= 6 && m < 18) ? hardCosts / 12 : 0; }
  );

  // Row 14: Soft Costs — construction months, spread evenly
  labelCell(ws, 14, 2, '  Soft Costs');
  monthFormula(14,
    function(m) { return 'IF(AND(' + m + '>=Assumptions!$G$5,' + m + '<Assumptions!$G$5+Assumptions!$G$6),Assumptions!C26/Assumptions!$G$6,0)'; },
    function(m) { return (m >= 6 && m < 18) ? softCosts / 12 : 0; }
  );

  // Row 15: Demo — Month 0
  labelCell(ws, 15, 2, '  Demo');
  monthFormula(15,
    function(m) { return m === 0 ? 'Assumptions!C27' : '0'; },
    function(m) { return m === 0 ? 55000 : 0; }
  );

  // Row 16: Subdivision — Month 1
  labelCell(ws, 16, 2, '  Subdivision');
  monthFormula(16,
    function(m) { return m === 1 ? 'Assumptions!C28' : '0'; },
    function(m) { return m === 1 ? 100000 : 0; }
  );

  // Row 17: A&E — Pre-dev months 1+ spread evenly
  labelCell(ws, 17, 2, '  A&E');
  monthFormula(17,
    function(m) { return 'IF(AND(' + m + '>=1,' + m + '<Assumptions!$G$5),Assumptions!C29/(Assumptions!$G$5-1),0)'; },
    function(m) { return (m >= 1 && m < 6) ? 150000 / 5 : 0; }
  );

  // Row 18: Subtotal Development
  labelCell(ws, 18, 2, 'Subtotal Development');
  ws.getCell('B18').font = { bold: true };
  monthFormula(18,
    function(m, cl) { return 'SUM(' + cl + '12:' + cl + '17)'; },
    function() { return 0; }
  );

  // ── Row 20: USES - CARRY ──
  sectionHeader(ws, 20, 2, 'USES - CARRY');
  ws.getCell('B20').fill = _hdrFill; ws.getCell('B20').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '20').fill = _hdrFill; }
  ws.getCell(totalLtr + '20').fill = _hdrFill;

  // Row 21: Property Tax — every month
  labelCell(ws, 21, 2, '  Property Tax');
  monthFormula(21,
    function() { return 'Assumptions!$G$27'; },
    function() { return price * 0.011 / 12; }
  );

  // Row 22: Insurance — every month
  labelCell(ws, 22, 2, '  Insurance');
  monthFormula(22,
    function() { return 'Assumptions!$G$29'; },
    function() { return 20000 / 12; }
  );

  // Row 23: Asset Mgmt — every month
  labelCell(ws, 23, 2, '  Asset Mgmt');
  monthFormula(23,
    function() { return 'Assumptions!$G$35'; },
    function() { return 3000; }
  );

  // Row 24: Dev Mgmt — construction months only
  labelCell(ws, 24, 2, '  Dev Mgmt');
  monthFormula(24,
    function(m) { return 'IF(AND(' + m + '>=Assumptions!$G$5,' + m + '<Assumptions!$G$5+Assumptions!$G$6),Assumptions!$G$36,0)'; },
    function(m) { return (m >= 6 && m < 18) ? 5000 : 0; }
  );

  // Row 25: Subtotal Carry
  labelCell(ws, 25, 2, 'Subtotal Carry');
  ws.getCell('B25').font = { bold: true };
  monthFormula(25,
    function(m, cl) { return 'SUM(' + cl + '21:' + cl + '24)'; },
    function() { return 0; }
  );

  // ── Row 27: USES - FEES ──
  sectionHeader(ws, 27, 2, 'USES - FEES');
  ws.getCell('B27').fill = _hdrFill; ws.getCell('B27').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '27').fill = _hdrFill; }
  ws.getCell(totalLtr + '27').fill = _hdrFill;

  // Row 28: Acquisition Fee — Month 0
  labelCell(ws, 28, 2, '  Acquisition Fee');
  monthFormula(28,
    function(m) { return m === 0 ? 'Assumptions!G34' : '0'; },
    function(m) { return m === 0 ? price * 0.02 : 0; }
  );

  // Row 29: Origination Fee — Month 0
  labelCell(ws, 29, 2, '  Origination Fee');
  monthFormula(29,
    function(m) { return m === 0 ? 'Assumptions!G20' : '0'; },
    function(m) { return m === 0 ? ed.debt * 0.02 : 0; }
  );

  // Row 30: Subtotal Fees
  labelCell(ws, 30, 2, 'Subtotal Fees');
  ws.getCell('B30').font = { bold: true };
  monthFormula(30,
    function(m, cl) { return cl + '28+' + cl + '29'; },
    function() { return 0; }
  );

  // ── Row 32: TOTAL USES ──
  labelCell(ws, 32, 2, 'TOTAL USES');
  ws.getCell('B32').font = { bold: true, size: 11 };
  monthFormula(32,
    function(m, cl) { return cl + '18+' + cl + '25+' + cl + '30+' + cl + '38'; },
    function() { return 0; }
  );
  // Double top border on total
  for (var m = 0; m < MONTHS; m++) {
    ws.getCell(colLetter(m+3) + '32').border = { top: { style: 'double', color: { argb: 'FF000000' } } };
  }
  ws.getCell(totalLtr + '32').border = { top: { style: 'double', color: { argb: 'FF000000' } } };

  // ── Row 34: LOAN SCHEDULE ──
  sectionHeader(ws, 34, 2, 'LOAN SCHEDULE');
  ws.getCell('B34').fill = _hdrFill; ws.getCell('B34').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '34').fill = _hdrFill; }
  ws.getCell(totalLtr + '34').fill = _hdrFill;

  // Row 35: Opening Balance
  labelCell(ws, 35, 2, '  Opening Balance');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    if (m === 0) {
      setFormula(ws, cl + '35', '0', 0, '$#,##0');
    } else {
      var prevCl = colLetter(m + 2);
      setFormula(ws, cl + '35', prevCl + '37', 0, '$#,##0');
    }
  }

  // Row 36: + Draws (= construction draws from row 8)
  labelCell(ws, 36, 2, '  + Draws');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '36', cl + '8', 0, '$#,##0');
  }
  setFormula(ws, totalLtr + '36', 'SUM(C36:' + colLetter(MONTHS + 2) + '36)', 0, '$#,##0');
  ws.getCell(totalLtr + '36').font = { bold: true };

  // Row 37: Closing Balance
  labelCell(ws, 37, 2, '  Closing Balance');
  ws.getCell('B37').font = { bold: true };
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '37', cl + '35+' + cl + '36', 0, '$#,##0');
  }

  // Row 38: Interest Payment (cash pay on opening balance)
  labelCell(ws, 38, 2, '  Interest Payment');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '38', cl + '35*Assumptions!$G$18/12', 0, '$#,##0');
  }
  setFormula(ws, totalLtr + '38', 'SUM(C38:' + colLetter(MONTHS + 2) + '38)', 0, '$#,##0');
  ws.getCell(totalLtr + '38').font = { bold: true };

  // Row 39: Cumulative Interest
  labelCell(ws, 39, 2, '  Cumulative Interest');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    if (m === 0) {
      setFormula(ws, cl + '39', cl + '38', 0, '$#,##0');
    } else {
      var prevCl = colLetter(m + 2);
      setFormula(ws, cl + '39', prevCl + '39+' + cl + '38', 0, '$#,##0');
    }
  }
  ws.getCell(totalLtr + '39').font = { bold: true };

  // ── Row 41: NET OPERATING CF ──
  labelCell(ws, 41, 2, 'NET OPERATING CF');
  ws.getCell('B41').font = { bold: true };
  monthFormula(41,
    function(m, cl) { return cl + '9-' + cl + '32'; },
    function() { return 0; }
  );

  // ── Row 43: EXIT ──
  sectionHeader(ws, 43, 2, 'EXIT');
  ws.getCell('B43').fill = _hdrFill; ws.getCell('B43').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '43').fill = _hdrFill; }
  ws.getCell(totalLtr + '43').fill = _hdrFill;

  // Row 44: Gross Sale Proceeds — last month only (month = G8-1)
  labelCell(ws, 44, 2, '  Gross Sale Proceeds');
  monthFormula(44,
    function(m) { return 'IF(' + m + '=Assumptions!$G$8-1,Assumptions!C36,0)'; },
    function(m) { return m === 23 ? grossRevenue : 0; }
  );

  // Row 45: Transaction Costs
  labelCell(ws, 45, 2, '  Transaction Costs');
  monthFormula(45,
    function(m) { return 'IF(' + m + '=Assumptions!$G$8-1,Assumptions!C36*Assumptions!C37,0)'; },
    function(m) { return m === 23 ? grossRevenue * txCostPct : 0; }
  );

  // Row 46: Disposition Fee
  labelCell(ws, 46, 2, '  Disposition Fee');
  monthFormula(46,
    function(m) { return 'IF(' + m + '=Assumptions!$G$8-1,Assumptions!G38,0)'; },
    function(m) { return m === 23 ? grossRevenue * 0.015 : 0; }
  );

  // Row 47: Loan Repayment (closing balance only — interest already paid monthly)
  labelCell(ws, 47, 2, '  Loan Repayment');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '47', 'IF(' + m + '=Assumptions!$G$8-1,' + cl + '37,0)', 0, '$#,##0');
  }
  setFormula(ws, totalLtr + '47', 'SUM(C47:' + colLetter(MONTHS + 2) + '47)', 0, '$#,##0');
  ws.getCell(totalLtr + '47').font = { bold: true };

  // Row 48: Net Exit CF
  labelCell(ws, 48, 2, 'Net Exit CF');
  ws.getCell('B48').font = { bold: true };
  monthFormula(48,
    function(m, cl) { return cl + '44-' + cl + '45-' + cl + '46-' + cl + '47'; },
    function() { return 0; }
  );

  // ── Row 50: NET CASH TO EQUITY ──
  labelCell(ws, 50, 2, 'NET CASH TO EQUITY');
  ws.getCell('B50').font = { bold: true, size: 11 };
  monthFormula(50,
    function(m, cl) { return cl + '41+' + cl + '48'; },
    function() { return 0; }
  );
  for (var m = 0; m < MONTHS; m++) {
    ws.getCell(colLetter(m+3) + '50').border = { top: { style: 'double', color: { argb: 'FF000000' } } };
  }
  ws.getCell(totalLtr + '50').border = { top: { style: 'double', color: { argb: 'FF000000' } } };

  // ── Row 52: DISTRIBUTIONS (last month) ──
  sectionHeader(ws, 52, 2, 'DISTRIBUTIONS');
  ws.getCell('B52').fill = _hdrFill; ws.getCell('B52').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '52').fill = _hdrFill; }
  ws.getCell(totalLtr + '52').fill = _hdrFill;

  var lastMo = 23;
  var lastCl = colLetter(lastMo + 3); // Z

  // Row 53: LP Return of Capital
  labelCell(ws, 53, 2, '  LP Return of Capital');
  monthFormula(53,
    function(m) { return m === lastMo ? 'Assumptions!G14*(1-Assumptions!C44)' : '0'; },
    function(m) { return m === lastMo ? lpEquityVal : 0; }
  );

  // Row 54: GP Return of Capital
  labelCell(ws, 54, 2, '  GP Return of Capital');
  monthFormula(54,
    function(m) { return m === lastMo ? 'Assumptions!G14*Assumptions!C44' : '0'; },
    function(m) { return m === lastMo ? gpCoInvestVal : 0; }
  );

  // Row 55: LP Preferred Return
  labelCell(ws, 55, 2, '  LP Preferred Return');
  monthFormula(55,
    function(m) {
      if (m !== lastMo) return '0';
      return 'Assumptions!G14*(1-Assumptions!C44)*Assumptions!C42*Assumptions!G8/12';
    },
    function(m) { return m === lastMo ? lpEquityVal * 0.08 * 24 / 12 : 0; }
  );

  // Row 56: GP Promote — MAX(0, NetCashToEquity - LP ROC - GP ROC - LP Pref) * promote %
  labelCell(ws, 56, 2, '  GP Promote');
  monthFormula(56,
    function(m, cl) {
      if (m !== lastMo) return '0';
      return 'MAX(0,' + totalLtr + '50-' + cl + '53-' + cl + '54-' + cl + '55)*Assumptions!C43';
    },
    function() { return 0; }
  );

  // Row 57: LP Residual Share
  labelCell(ws, 57, 2, '  LP Residual Share');
  monthFormula(57,
    function(m, cl) {
      if (m !== lastMo) return '0';
      return 'MAX(0,' + totalLtr + '50-' + cl + '53-' + cl + '54-' + cl + '55)*(1-Assumptions!C43)';
    },
    function() { return 0; }
  );

  // ── Row 59: LP TOTAL DISTRIBUTION ──
  labelCell(ws, 59, 2, 'LP TOTAL DISTRIBUTION');
  ws.getCell('B59').font = { bold: true };
  monthFormula(59,
    function(m, cl) { return cl + '53+' + cl + '55+' + cl + '57'; },
    function() { return 0; }
  );

  // Row 60: LP Net Profit
  labelCell(ws, 60, 2, 'LP Net Profit');
  monthFormula(60,
    function(m, cl) { return cl + '59-' + cl + '53'; },
    function() { return 0; }
  );

  // ── Row 62: LLC CASH BALANCE ──
  labelCell(ws, 62, 2, 'LLC CASH BALANCE');
  ws.getCell('B62').font = { bold: true };
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    if (m === 0) {
      setFormula(ws, cl + '62', cl + '9-' + cl + '32+' + cl + '48', 0, '$#,##0');
    } else {
      var prevCl = colLetter(m + 2);
      setFormula(ws, cl + '62', prevCl + '62+' + cl + '9-' + cl + '32+' + cl + '48', 0, '$#,##0');
    }
  }

  // Freeze panes: B column labels + header rows
  ws.views = [{ state: 'frozen', xSplit: 2, ySplit: 3, showGridLines: false }];
  ws.pageSetup = { orientation: 'landscape', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildOutputsTab(wb, ed) {
  var ws = wb.addWorksheet('Outputs');
  ws.getColumn(1).width = 2;
  ws.getColumn(2).width = 26;
  ws.getColumn(3).width = 20;

  // Title
  ws.mergeCells('B2:C2');
  ws.getCell('B2').value = 'Investment Returns';
  ws.getCell('B2').font = { bold: true, size: 14 };

  // ── LP Returns ──
  ws.getCell('B4').value = 'LP RETURNS';
  ws.getCell('B4').font = _hdrFont; ws.getCell('B4').fill = _hdrFill;
  ws.getCell('C4').fill = _hdrFill;

  labelCell(ws, 5, 2, 'LP MOIC');
  setFormula(ws, 'C5', "IF('Cash Flow'!AA6=0,0,'Cash Flow'!AA59/'Cash Flow'!AA6)", 0, '0.00x');
  ws.getCell('C5').font = { bold: true, size: 12 };

  labelCell(ws, 6, 2, 'LP IRR (ann.)');
  setFormula(ws, 'C6', 'IF(C5<=0,0,(C5^(12/Assumptions!G8))-1)', 0, '0.0%');
  ws.getCell('C6').font = { bold: true, size: 12 };

  labelCell(ws, 7, 2, 'LP Total Dist');
  setFormula(ws, 'C7', "'Cash Flow'!AA59", 0, '$#,##0');

  labelCell(ws, 8, 2, 'LP Equity In');
  setFormula(ws, 'C8', "'Cash Flow'!AA6", 0, '$#,##0');

  labelCell(ws, 9, 2, 'LP Net Profit');
  setFormula(ws, 'C9', "'Cash Flow'!AA60", 0, '$#,##0');

  // ── Project Metrics ──
  ws.getCell('B11').value = 'PROJECT METRICS';
  ws.getCell('B11').font = _hdrFont; ws.getCell('B11').fill = _hdrFill;
  ws.getCell('C11').fill = _hdrFill;

  labelCell(ws, 12, 2, 'Project Margin');
  setFormula(ws, 'C12', 'IF(Assumptions!C38=0,0,(Assumptions!C38-Assumptions!G16)/Assumptions!C38)', 0, '0.0%');

  labelCell(ws, 13, 2, 'Project MOIC');
  setFormula(ws, 'C13', 'IF(Assumptions!G16=0,0,Assumptions!C38/Assumptions!G16)', 0, '0.00x');

  labelCell(ws, 14, 2, 'Development Spread');
  setFormula(ws, 'C14', 'Assumptions!C35-Assumptions!G16/Assumptions!C22', 0, '$#,##0');

  labelCell(ws, 17, 2, 'All-In $/SF');
  setFormula(ws, 'C17', 'IF(Assumptions!C22=0,0,Assumptions!G16/Assumptions!C22)', 0, '$#,##0');

  labelCell(ws, 18, 2, 'Break-Even $/SF');
  setFormula(ws, 'C18', 'IF(Assumptions!C22=0,0,Assumptions!G16/(Assumptions!C22*(1-Assumptions!C37)))', 0, '$#,##0');

  // ── GP Economics ──
  ws.getCell('B20').value = 'GP ECONOMICS';
  ws.getCell('B20').font = _hdrFont; ws.getCell('B20').fill = _hdrFill;
  ws.getCell('C20').fill = _hdrFill;

  labelCell(ws, 21, 2, 'GP Promote $');
  setFormula(ws, 'C21', "'Cash Flow'!AA56", 0, '$#,##0');

  labelCell(ws, 22, 2, 'Acq Fee');
  setFormula(ws, 'C22', 'Assumptions!G34', 0, '$#,##0');

  labelCell(ws, 23, 2, 'Asset Mgmt Total');
  setFormula(ws, 'C23', 'Assumptions!G35*Assumptions!G8', 0, '$#,##0');

  labelCell(ws, 24, 2, 'Dev Mgmt Total');
  setFormula(ws, 'C24', 'Assumptions!G36*Assumptions!G6', 0, '$#,##0');

  labelCell(ws, 25, 2, 'Disp Fee');
  setFormula(ws, 'C25', 'Assumptions!G38', 0, '$#,##0');

  labelCell(ws, 26, 2, 'GP Total Income');
  ws.getCell('B26').font = { bold: true };
  setFormula(ws, 'C26', 'C21+C22+C23+C24+C25', 0, '$#,##0');
  ws.getCell('C26').font = { bold: true };
  ws.getCell('C26').border = { top: { style: 'double', color: { argb: 'FF000000' } } };

  // ── Sensitivity Analysis ──
  ws.getColumn(4).width = 14;
  ws.getColumn(5).width = 14;
  ws.getColumn(6).width = 14;
  ws.getColumn(7).width = 14;

  ws.getCell('B29').value = 'SENSITIVITY ANALYSIS';
  ws.getCell('B29').font = _hdrFont; ws.getCell('B29').fill = _hdrFill;
  ['C29','D29','E29','F29','G29'].forEach(function(a){ ws.getCell(a).fill = _hdrFill; });

  var baseFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFDCE6F1' } };
  var crossFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  var buildDeltas = [-0.15, -0.075, 0, 0.075, 0.15];
  var exitDeltas = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];

  // Inline LP return formulas (no LET — compatible with all Excel versions)
  // Simplified waterfall: LP gets equity back + (1-promote%) × profit
  function irrFormula(R, K, M) {
    return 'IF((' + K + ')*Assumptions!G17=0,0,IFERROR((1+(1-Assumptions!C43)*(' + R + '-(' + K + '))/((' + K + ')*Assumptions!G17))^(12/' + M + ')-1,-1))';
  }
  function moicFormula(R, K, M) {
    return 'IF((' + K + ')*Assumptions!G17=0,0,1+(1-Assumptions!C43)*(' + R + '-(' + K + '))/((' + K + ')*Assumptions!G17))';
  }

  // ── Table 1: Investor IRR vs Exit $/SF × Build Cost $/SF ──
  ws.mergeCells('B31:G31');
  ws.getCell('B31').value = 'Investor IRR: Exit $/SF vs Build Cost $/SF';
  ws.getCell('B31').font = { italic: true, size: 11 };

  ws.getCell('B32').value = 'Exit \u2193 / Build \u2192';
  ws.getCell('B32').font = { bold: true, size: 9 };
  for (var bi = 0; bi < buildDeltas.length; bi++) {
    var cl = colLetter(bi + 3);
    var f = buildDeltas[bi] === 0 ? 'Assumptions!C23' : 'Assumptions!C23*' + (1 + buildDeltas[bi]);
    setFormula(ws, cl + '32', f, 0, '$#,##0');
    ws.getCell(cl + '32').font = { bold: true };
    ws.getCell(cl + '32').alignment = { horizontal: 'center' };
    if (buildDeltas[bi] === 0) ws.getCell(cl + '32').fill = baseFill;
  }

  for (var ei = 0; ei < exitDeltas.length; ei++) {
    var row = 33 + ei;
    var ef = exitDeltas[ei] === 0 ? 'Assumptions!C35' : 'Assumptions!C35*' + (1 + exitDeltas[ei]);
    setFormula(ws, 'B' + row, ef, 0, '$#,##0');
    ws.getCell('B' + row).font = { bold: true };
    if (exitDeltas[ei] === 0) ws.getCell('B' + row).fill = baseFill;

    for (var bi2 = 0; bi2 < buildDeltas.length; bi2++) {
      var cl2 = colLetter(bi2 + 3);
      var revE = 'Assumptions!C20*Assumptions!C21*$B' + row + '*(1-Assumptions!C37)';
      var costE = 'Assumptions!G16+(' + cl2 + '$32-Assumptions!C23)*Assumptions!C22*(1+Assumptions!C25)';
      setFormula(ws, cl2 + row, irrFormula(revE, costE, 'Assumptions!G8'), 0, '0.0%');
      if (exitDeltas[ei] === 0 && buildDeltas[bi2] === 0) {
        ws.getCell(cl2 + row).fill = baseFill;
        ws.getCell(cl2 + row).font = { bold: true };
      } else if (exitDeltas[ei] === 0 || buildDeltas[bi2] === 0) {
        ws.getCell(cl2 + row).fill = crossFill;
      }
    }
  }

  // ── Table 2: Investor MOIC vs Exit $/SF × Purchase Price ──
  var t2 = 33 + exitDeltas.length + 2; // row 42
  ws.mergeCells('B' + t2 + ':G' + t2);
  ws.getCell('B' + t2).value = 'Investor MOIC: Exit $/SF vs Purchase Price';
  ws.getCell('B' + t2).font = { italic: true, size: 11 };

  var h2 = t2 + 1; // row 43
  var priceDeltas = [-0.15, -0.075, 0, 0.075, 0.15];
  ws.getCell('B' + h2).value = 'Exit \u2193 / Price \u2192';
  ws.getCell('B' + h2).font = { bold: true, size: 9 };
  for (var pi = 0; pi < priceDeltas.length; pi++) {
    var cl3 = colLetter(pi + 3);
    var pf2 = priceDeltas[pi] === 0 ? 'Assumptions!C16' : 'Assumptions!C16*' + (1 + priceDeltas[pi]);
    setFormula(ws, cl3 + h2, pf2, 0, '$#,##0');
    ws.getCell(cl3 + h2).font = { bold: true };
    ws.getCell(cl3 + h2).alignment = { horizontal: 'center' };
    if (priceDeltas[pi] === 0) ws.getCell(cl3 + h2).fill = baseFill;
  }

  for (var ei2 = 0; ei2 < exitDeltas.length; ei2++) {
    var row2 = h2 + 1 + ei2;
    var ef2 = exitDeltas[ei2] === 0 ? 'Assumptions!C35' : 'Assumptions!C35*' + (1 + exitDeltas[ei2]);
    setFormula(ws, 'B' + row2, ef2, 0, '$#,##0');
    ws.getCell('B' + row2).font = { bold: true };
    if (exitDeltas[ei2] === 0) ws.getCell('B' + row2).fill = baseFill;

    for (var pi2 = 0; pi2 < priceDeltas.length; pi2++) {
      var cl4 = colLetter(pi2 + 3);
      var revE2 = 'Assumptions!C20*Assumptions!C21*$B' + row2 + '*(1-Assumptions!C37)';
      var costE2 = 'Assumptions!G16+(' + cl4 + '$' + h2 + '-Assumptions!C16)*(1+Assumptions!G33)';
      setFormula(ws, cl4 + row2, moicFormula(revE2, costE2, 'Assumptions!G8'), 0, '0.00x');
      if (exitDeltas[ei2] === 0 && priceDeltas[pi2] === 0) {
        ws.getCell(cl4 + row2).fill = baseFill;
        ws.getCell(cl4 + row2).font = { bold: true };
      } else if (exitDeltas[ei2] === 0 || priceDeltas[pi2] === 0) {
        ws.getCell(cl4 + row2).fill = crossFill;
      }
    }
  }

  // ── Table 3: Investor IRR vs Hold Period × Exit $/SF ──
  var t3 = h2 + 1 + exitDeltas.length + 2;
  ws.mergeCells('B' + t3 + ':G' + t3);
  ws.getCell('B' + t3).value = 'Investor IRR: Hold Period vs Exit $/SF';
  ws.getCell('B' + t3).font = { italic: true, size: 11 };

  var h3 = t3 + 1;
  var exitDeltas3 = [-0.15, -0.075, 0, 0.075, 0.15];
  var holdMonths = [18, 20, 22, 24, 26, 28, 30];
  ws.getCell('B' + h3).value = 'Months \u2193 / Exit \u2192';
  ws.getCell('B' + h3).font = { bold: true, size: 9 };
  for (var xi = 0; xi < exitDeltas3.length; xi++) {
    var cl5 = colLetter(xi + 3);
    var xf = exitDeltas3[xi] === 0 ? 'Assumptions!C35' : 'Assumptions!C35*' + (1 + exitDeltas3[xi]);
    setFormula(ws, cl5 + h3, xf, 0, '$#,##0');
    ws.getCell(cl5 + h3).font = { bold: true };
    ws.getCell(cl5 + h3).alignment = { horizontal: 'center' };
    if (exitDeltas3[xi] === 0) ws.getCell(cl5 + h3).fill = baseFill;
  }

  for (var hi = 0; hi < holdMonths.length; hi++) {
    var row3 = h3 + 1 + hi;
    var months = holdMonths[hi];
    setVal(ws, 'B' + row3, months, '#,##0');
    ws.getCell('B' + row3).font = { bold: true };
    if (months === 24) ws.getCell('B' + row3).fill = baseFill;

    for (var xi2 = 0; xi2 < exitDeltas3.length; xi2++) {
      var cl6 = colLetter(xi2 + 3);
      var revE3 = 'Assumptions!C20*Assumptions!C21*' + cl6 + '$' + h3 + '*(1-Assumptions!C37)';
      setFormula(ws, cl6 + row3, irrFormula(revE3, 'Assumptions!G16', '$B' + row3), 0, '0.0%');
      if (months === 24 && exitDeltas3[xi2] === 0) {
        ws.getCell(cl6 + row3).fill = baseFill;
        ws.getCell(cl6 + row3).font = { bold: true };
      } else if (months === 24 || exitDeltas3[xi2] === 0) {
        ws.getCell(cl6 + row3).fill = crossFill;
      }
    }
  }

  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'portrait', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildBTRTab(wb) {
  var ws = wb.addWorksheet('BTR Hold');
  ws.getColumn(1).width = 2;
  ws.getColumn(2).width = 28;
  ws.getColumn(3).width = 20;

  ws.mergeCells('B2:C2');
  ws.getCell('B2').value = 'Build-to-Rent Analysis';
  ws.getCell('B2').font = { bold: true, size: 14 };

  // ── Income ──
  ws.getCell('B4').value = 'INCOME';
  ws.getCell('B4').font = _hdrFont; ws.getCell('B4').fill = _hdrFill;
  ws.getCell('C4').fill = _hdrFill;

  labelCell(ws, 5, 2, 'Units');
  setFormula(ws, 'C5', 'Assumptions!C20', 0, '#,##0');

  labelCell(ws, 6, 2, 'Rent / Unit / Mo');
  setFormula(ws, 'C6', 'Assumptions!C48', 0, '$#,##0');

  labelCell(ws, 7, 2, 'Gross Annual Rent');
  setFormula(ws, 'C7', 'C5*C6*12', 0, '$#,##0');

  labelCell(ws, 8, 2, 'OpEx Ratio');
  setFormula(ws, 'C8', 'Assumptions!C50', 0, '0.0%');

  labelCell(ws, 9, 2, 'Annual NOI');
  setFormula(ws, 'C9', 'C7*(1-C8)', 0, '$#,##0');
  ws.getCell('C9').font = { bold: true };

  // ── Valuation ──
  ws.getCell('B11').value = 'VALUATION';
  ws.getCell('B11').font = _hdrFont; ws.getCell('B11').fill = _hdrFill;
  ws.getCell('C11').fill = _hdrFill;

  labelCell(ws, 12, 2, 'Cap Rate');
  setFormula(ws, 'C12', 'Assumptions!C51', 0, '0.0%');

  labelCell(ws, 13, 2, 'Market Value');
  setFormula(ws, 'C13', 'Assumptions!C36', 0, '$#,##0');
  ws.getCell('C13').font = { bold: true };

  labelCell(ws, 14, 2, 'Yield on Cost');
  setFormula(ws, 'C14', 'IF(Assumptions!G16=0,0,C9/Assumptions!G16)', 0, '0.0%');

  // ── Refinance ──
  ws.getCell('B16').value = 'REFINANCE';
  ws.getCell('B16').font = _hdrFont; ws.getCell('B16').fill = _hdrFill;
  ws.getCell('C16').fill = _hdrFill;

  labelCell(ws, 17, 2, 'Refi LTV');
  setFormula(ws, 'C17', 'Assumptions!C52', 0, '0.0%');

  labelCell(ws, 18, 2, 'Refi Loan');
  setFormula(ws, 'C18', 'C13*C17', 0, '$#,##0');

  labelCell(ws, 19, 2, 'Perm Rate');
  setFormula(ws, 'C19', 'Assumptions!C53', 0, '0.00%');

  labelCell(ws, 20, 2, 'Annual Debt Service');
  setFormula(ws, 'C20', 'C18*C19', 0, '$#,##0');

  labelCell(ws, 21, 2, 'DSCR');
  setFormula(ws, 'C21', 'IF(C20=0,0,C9/C20)', 0, '0.00x');
  ws.getCell('C21').font = { bold: true };

  // ── Cash Flow ──
  ws.getCell('B23').value = 'LEVERED CASH FLOW';
  ws.getCell('B23').font = _hdrFont; ws.getCell('B23').fill = _hdrFill;
  ws.getCell('C23').fill = _hdrFill;

  labelCell(ws, 24, 2, 'Annual Cash Flow');
  setFormula(ws, 'C24', 'C9-C20', 0, '$#,##0');
  ws.getCell('C24').font = { bold: true };

  labelCell(ws, 25, 2, 'Equity After Refi');
  setFormula(ws, 'C25', 'Assumptions!G16-C18', 0, '$#,##0');

  labelCell(ws, 26, 2, 'Cash-on-Cash');
  setFormula(ws, 'C26', 'IF(C25=0,0,C24/C25)', 0, '0.0%');
  ws.getCell('C26').font = { bold: true };

  labelCell(ws, 27, 2, 'Cash-Out at Refi');
  setFormula(ws, 'C27', 'C18-Assumptions!G16', 0, '$#,##0');

  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'portrait', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildExitCompsTab(wb, l) {
  var compResult = _deps.findCompsForListing(l);
  if (!compResult.used.length && !compResult.ref.length) return null;

  var cs = wb.addWorksheet('Exit Comps');
  var el = _deps.exitLabel(l);

  cs.getCell('A1').value = 'Exit Comps for ' + (l.address || '');
  cs.getCell('A1').font = { bold: true, size: 14 };
  cs.mergeCells('A1:L1');
  cs.getCell('A2').value = el.label + '  \u2014  $' + el.psf + '/SF';
  cs.getCell('A2').font = { bold: true, size: 11 };
  cs.mergeCells('A2:L2');

  var compHeaders = ['Status','Address','Sale Price','$/SF','SqFt','Beds','Baths','Zone','Year Built','Tier','Sale Date','Distance (mi)'];
  var headerRow = cs.getRow(4);
  compHeaders.forEach(function(h, i) {
    var cell = headerRow.getCell(i + 1);
    cell.value = h;
    cell.font = { bold: true };
    cell.fill = { type:'pattern', pattern:'solid', fgColor:{ argb:'FFE0E0E0' } };
  });

  cs.getColumn(1).width = 8;
  cs.getColumn(2).width = 35;
  cs.getColumn(3).width = 14;
  cs.getColumn(4).width = 10;
  cs.getColumn(5).width = 10;
  cs.getColumn(6).width = 6;
  cs.getColumn(7).width = 6;
  cs.getColumn(8).width = 8;
  cs.getColumn(9).width = 11;
  cs.getColumn(10).width = 6;
  cs.getColumn(11).width = 12;
  cs.getColumn(12).width = 12;

  var greenFill = { type:'pattern', pattern:'solid', fgColor:{ argb:'FFE8F5E9' } };
  var allComps = compResult.used.concat(compResult.ref);
  for (var ci = 0; ci < allComps.length; ci++) {
    var comp = allComps[ci];
    var row = cs.getRow(5 + ci);
    var isUsed = ci < compResult.used.length;

    row.getCell(1).value = isUsed ? 'Used' : 'Ref';
    row.getCell(2).value = comp.address || '';
    row.getCell(3).value = comp.price || 0;
    row.getCell(3).numFmt = '$#,##0';
    row.getCell(4).value = comp.ppsf || 0;
    row.getCell(4).numFmt = '$#,##0';
    row.getCell(5).value = comp.sqft || 0;
    row.getCell(5).numFmt = '#,##0';
    row.getCell(6).value = comp.bd || '';
    row.getCell(7).value = comp.ba || '';
    row.getCell(8).value = comp.zone || '';
    row.getCell(9).value = comp.yb || '';
    row.getCell(10).value = comp.t ? 'T' + comp.t : '';
    row.getCell(11).value = comp.date || '';
    row.getCell(12).value = comp.dist ? +comp.dist.toFixed(2) : '';
    row.getCell(12).numFmt = '0.00';

    if (isUsed) {
      for (var k = 1; k <= 12; k++) row.getCell(k).fill = greenFill;
    }
  }
  cs.views = [{ showGridLines: false }];
  return cs;
}

async function exportModel(lat, lng) {
  var l = _deps.getLISTINGS().find(function(x){ return x.lat===lat && x.lng===lng; });
  if (!l) { alert('Listing not found'); return; }

  var pf = calculateProForma(l);
  var exitPSF = l.clusterT1psf || l.subdivExitPsf || l.newconPpsf || l.exitPsf || 0;
  var monthlyRent = l.estRentMonth || l.fmr3br || 4000;
  var units = pf.maxUnits;
  var avgUnitSF = proforma.avgUnitSf;
  var buildableSF = units * avgUnitSF;
  var buildCostPSF = buildableSF > 0 ? Math.round(pf.hardCosts / buildableSF) : 0;

  var ed = sizeEquityAndDebt(l.price, units, avgUnitSF, buildCostPSF, exitPSF, monthlyRent);
  var btr = calculateBTRProForma(l);

  // Build workbook programmatically — no template needed
  var wb = new ExcelJS.Workbook();
  wb.creator = 'SB 1123 Deal Finder';

  buildAssumptionsTab(wb, l, pf, ed, exitPSF, monthlyRent);
  buildSourcesUsesTab(wb, l, ed, pf);
  buildCashFlowTab(wb, l, ed, pf);
  buildOutputsTab(wb, ed);
  buildBTRTab(wb);
  buildExitCompsTab(wb, l);

  // Generate and download
  var filename = (l.address||'deal').replace(/[^a-zA-Z0-9]/g,'_').replace(/_+/g,'_') + '_model.xlsx';
  var outBuf = await wb.xlsx.writeBuffer();
  var blob = new Blob([outBuf], {type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function exportOM(lat, lng) {
  var OM_API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? '' : 'https://sb1123-om-api.fly.dev';

  var l = _deps.getLISTINGS().find(function(x){ return x.lat===lat && x.lng===lng; });
  if (!l) { alert('Listing not found'); return; }

  var pf = calculateProForma(l);
  var btr = calculateBTRProForma(l);
  var exitPSF = l.clusterT1psf || l.subdivExitPsf || l.newconPpsf || l.exitPsf || 0;
  var monthlyRent = l.estRentMonth || l.fmr3br || 4000;
  var avgUnitSF = proforma.avgUnitSf;
  var buildCostPSF = pf.adjBuildCostPerSf;
  var units = pf.maxUnits;

  var ed = sizeEquityAndDebt(l.price, units, avgUnitSF, buildCostPSF, exitPSF, monthlyRent);

  // ── Constants (must match sizeEquityAndDebt) ──
  var SOFT_PCT = 0.25;
  var DEMO = 55000;
  var SUBDIV = 100000;
  var AE = 150000;
  var TAX_RATE = 0.011;
  var INS_ANNUAL = 20000;
  var AM_MONTHLY = 3000;
  var DM_MONTHLY = 5000;
  var ACQ_FEE_PCT = 0.02;
  var DISP_FEE_PCT = 0.015;
  var ORIG_FEE_PCT = 0.02;
  var INTEREST_RATE = 0.09;
  var LP_PREF = 0.08;
  var GP_PROMOTE = 0.20;
  var GP_COINVEST = 0.05;
  var PRE_DEV_MO = 6;
  var CONSTR_MO = 12;
  var SALE_MO = 6;
  var HOLD_MO = PRE_DEV_MO + CONSTR_MO + SALE_MO;
  var TX_COST_PCT = proforma.txnCostPct / 100;
  var BTR_OPEX = btr.opexRatio;
  var BTR_CAP = btr.capRate;
  var BTR_LTV = btr.refiLTV;
  var BTR_PERM_RATE = 0.0625;
  var BTR_RENT_GROWTH = 0.03;

  // ── Development costs ──
  var buildableSF = units * avgUnitSF;
  var hardCosts = buildableSF * buildCostPSF;
  var softCosts = hardCosts * SOFT_PCT;
  var totalDev = hardCosts + softCosts + DEMO + SUBDIV + AE;

  // ── Capital structure ──
  var totalProjectCost = ed.totalCost;
  var equity = ed.equity;
  var debt = totalProjectCost - equity;
  var gpCoinvestEquity = Math.round(equity * GP_COINVEST);
  var lpEquity = equity - gpCoinvestEquity;
  var origFee = debt * ORIG_FEE_PCT;

  // ── Carry costs (monthly accumulation) ──
  var monthlyTax = l.price * TAX_RATE / 12;
  var monthlyIns = INS_ANNUAL / 12;

  var totalPropTax = monthlyTax * HOLD_MO;
  var totalInsurance = monthlyIns * HOLD_MO;
  var totalAssetMgmt = AM_MONTHLY * HOLD_MO;
  var totalDevMgmt = DM_MONTHLY * CONSTR_MO;

  // ── Interest (PIK — accrues on drawn debt) ──
  // Pre-dev: land acquisition debt drawn; Construction: progressive draws; Sale: fully drawn
  var landDebt = Math.max(0, l.price - equity);  // debt portion of land
  var constrDebt = debt - landDebt;  // remaining debt for construction
  // Simplified PIK: average outstanding x rate x time
  var preDevInterest = landDebt * INTEREST_RATE * (PRE_DEV_MO / 12);
  var constrInterest = (landDebt + constrDebt * 0.5) * INTEREST_RATE * (CONSTR_MO / 12);
  var saleInterest = debt * INTEREST_RATE * (SALE_MO / 12);
  var totalInterest = preDevInterest + constrInterest + saleInterest;

  // ── Fees ──
  var acqFee = l.price * ACQ_FEE_PCT;
  var dispFee = 0;  // computed on exit below
  var totalSponsorFees = acqFee + totalAssetMgmt + totalDevMgmt;  // disposition added at exit

  // ── Exit ──
  var grossRevenue = units * avgUnitSF * exitPSF;
  var txCosts = grossRevenue * TX_COST_PCT;
  dispFee = grossRevenue * DISP_FEE_PCT;
  totalSponsorFees += dispFee;
  var netSaleProceeds = grossRevenue - txCosts;

  // ── Waterfall ──
  var loanRepayment = debt + totalInterest + origFee;
  var netDistributable = netSaleProceeds - loanRepayment;
  var lpROC = lpEquity;
  var gpROC = gpCoinvestEquity;
  var profitAfterROC = netDistributable - lpROC - gpROC;

  // LP preferred return (simple, on hold period)
  var lpPrefDollars = lpEquity * LP_PREF * (HOLD_MO / 12);
  var remainingAfterPref = Math.max(0, profitAfterROC - lpPrefDollars);

  // GP promote on remaining
  var gpPromoteDollars = remainingAfterPref * GP_PROMOTE;
  var lpShareRemaining = remainingAfterPref * (1 - GP_PROMOTE);

  // LP totals
  var lpTotalDist = lpROC + lpPrefDollars + lpShareRemaining;
  var lpNetProfit = lpTotalDist - lpEquity;
  var lpMOIC = lpEquity > 0 ? lpTotalDist / lpEquity : 0;

  // LP IRR (annualized approximation from MOIC and hold)
  var holdYears = HOLD_MO / 12;
  var lpIRR = holdYears > 0 ? Math.pow(lpMOIC, 1 / holdYears) - 1 : 0;

  // Project-level metrics
  var projectMargin = netSaleProceeds > 0 ? (netSaleProceeds - totalProjectCost) / netSaleProceeds : 0;
  var projectMOIC = totalProjectCost > 0 ? netSaleProceeds / totalProjectCost : 0;
  var allInPsf = buildableSF > 0 ? totalProjectCost / buildableSF : 0;

  // GP economics
  var gpTotalIncome = gpPromoteDollars + totalSponsorFees;
  var gpFeeLoad = grossRevenue > 0 ? gpTotalIncome / grossRevenue : 0;

  // Lot dimensions
  var lotWidth = l.lw || Math.round(Math.sqrt((l.lotSf||10000) * 0.33));
  var lotDepth = l.ld || Math.round((l.lotSf||10000) / lotWidth);

  // ── BTR ──
  var btrGPI = btr.grossAnnualRent;
  var btrEGI = btr.grossAnnualRent;
  var btrNOI = btr.annualNOI;
  var btrStabilizedValue = btr.stabilizedValue;
  var btrRefiLoan = btr.refiLoanAmount;
  var btrEffectiveLTV = btrStabilizedValue > 0 ? btrRefiLoan / btrStabilizedValue : 0;
  var btrAnnualDS = btr.annualDebtService;
  var btrDSCR = btr.dscr;
  var btrAnnualCF = btr.cashFlow;
  var btrCoC = btr.cashOnCash;
  var btrYOC = btr.yieldOnCost;

  // ── Build deal dict matching read_xls() schema ──
  var addrParts = (l.address || '').split(',');
  var street = addrParts[0] ? addrParts[0].trim() : (l.address || '');

  var d = {
    // Property
    address: street,
    city: l.city || '',
    zip: l.zip || '',
    state: 'CA',
    zoning: (l.zone || 'R1').toUpperCase(),
    lot_sf: l.lotSf || 0,
    lot_width: lotWidth,
    lot_depth: lotDepth,
    slope_pct: (l.slope || 0) / 100,
    beds_baths: (l.beds || '') + ' / ' + (l.baths || ''),
    dom: l.dom || 0,

    // Acquisition
    asking_price: l.price || 0,

    // Development
    units: units,
    unit_sf: avgUnitSF,
    buildable_sf: buildableSF,
    build_cost_psf: buildCostPSF,
    hard_costs: hardCosts,
    soft_cost_pct: SOFT_PCT,
    soft_costs: softCosts,
    demo_cost: DEMO,
    subdivision_cost: SUBDIV,
    ae_cost: AE,
    total_dev_costs: totalDev,

    // Exit
    exit_psf: exitPSF,
    gross_revenue: grossRevenue,
    tx_cost_pct: TX_COST_PCT,
    net_sale_proceeds: netSaleProceeds,

    // Timeline
    predev_months: PRE_DEV_MO,
    construction_months: CONSTR_MO,
    sale_months: SALE_MO,
    hold_months: HOLD_MO,

    // Capital structure
    equity_total: equity,
    debt_total: debt,
    total_project_cost: totalProjectCost,
    equity_pct: totalProjectCost > 0 ? equity / totalProjectCost : 0,
    interest_rate: INTEREST_RATE,
    orig_fee_pct: ORIG_FEE_PCT,
    orig_fee_dollars: origFee,
    interest_treatment: 'PIK',

    // Carry
    prop_tax_rate: TAX_RATE,
    monthly_tax: monthlyTax,
    insurance_annual: INS_ANNUAL,
    monthly_insurance: monthlyIns,

    // Fees
    acq_fee_pct: ACQ_FEE_PCT,
    acq_fee_dollars: acqFee,
    asset_mgmt_monthly: AM_MONTHLY,
    dev_mgmt_monthly: DM_MONTHLY,
    disposition_fee_pct: DISP_FEE_PCT,
    disposition_fee_dollars: dispFee,
    total_sponsor_fees: totalSponsorFees,

    // Waterfall
    lp_pref_rate: LP_PREF,
    gp_promote_pct: GP_PROMOTE,
    gp_coinvest_pct: GP_COINVEST,
    lp_promote_pct: 1 - GP_PROMOTE,

    // Waterfall results
    lp_moic: lpMOIC,
    lp_irr: lpIRR,
    lp_total_dist: lpTotalDist,
    lp_equity_in: lpEquity,
    lp_net_profit: lpNetProfit,
    project_margin: projectMargin,
    project_moic: projectMOIC,
    all_in_psf: allInPsf,
    gp_promote_dollars: gpPromoteDollars,
    gp_total_income: gpTotalIncome,
    gp_fee_load: gpFeeLoad,

    // Monthly CF waterfall detail
    loan_repayment: loanRepayment,
    net_distributable: netDistributable,
    lp_roc: lpROC,
    gp_roc: gpROC,
    profit_after_roc: profitAfterROC,
    lp_pref_dollars: lpPrefDollars,
    remaining_after_pref: remainingAfterPref,
    lp_share_remaining: lpShareRemaining,
    gp_coinvest_equity: gpCoinvestEquity,
    loan_draws: debt,
    total_interest: totalInterest,
    total_prop_tax: totalPropTax,
    total_insurance: totalInsurance,
    total_asset_mgmt: totalAssetMgmt,
    total_dev_mgmt: totalDevMgmt,

    // BTR
    btr_rent_monthly: btr.rentPerUnit,
    btr_opex_ratio: BTR_OPEX,
    btr_cap_rate: BTR_CAP,
    btr_refi_ltv: BTR_LTV,
    btr_perm_rate: BTR_PERM_RATE,
    btr_rent_growth: BTR_RENT_GROWTH,
    btr_gpi: btrGPI,
    btr_egi: btrEGI,
    btr_noi: btrNOI,
    btr_stabilized_value: btrStabilizedValue,
    btr_effective_ltv: btrEffectiveLTV,
    btr_refi_loan: btrRefiLoan,
    btr_annual_ds: btrAnnualDS,
    btr_dscr: btrDSCR,
    btr_annual_cf: btrAnnualCF,
    btr_coc: btrCoC,
    btr_yoc: btrYOC,

    // Derived
    break_even_psf: buildableSF > 0 ? totalProjectCost / (buildableSF * (1 - TX_COST_PCT)) : 0,
    lot_per_unit: units > 0 ? (l.lotSf || 0) / units : 0,
    fee_pct_of_cap: totalProjectCost > 0 ? totalSponsorFees / totalProjectCost : 0,
  };

  // ── Attach comp sales data ──
  var compResult = _deps.findCompsForListing(l);
  var el = _deps.exitLabel(l);
  d.comp_source = el.short || '';
  d.comp_label = el.label || '';
  d.comps = compResult.used.slice(0, 12).map(function(c) {
    return {
      address: c.address || '',
      price: c.price || 0,
      ppsf: Math.round(c.ppsf || 0),
      sqft: c.sqft || 0,
      beds: c.bd || '',
      baths: c.ba || '',
      zone: c.zone || '',
      year_built: c.yb || '',
      date: c.date || '',
      dist: c.dist ? +c.dist.toFixed(2) : 0,
    };
  });

  // ── POST to OM API ──
  try {
    var resp = await fetch(OM_API + '/api/generate-om', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(d),
    });
    if (!resp.ok) {
      var errText = await resp.text();
      alert('OM generation failed: ' + errText);
      return;
    }
    var blob = await resp.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = street.replace(/[^a-zA-Z0-9]/g, '_').replace(/_+/g, '_') + '_OM.pptx';
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('OM export failed: ' + err.message);
  }
}

export { exportCSV, exportModel, exportOM, sizeEquityAndDebt };

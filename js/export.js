// Export module — Excel model, OM export, CSV export
import { proforma, calculateProForma, calculateBTRProForma } from './proforma.js';

var _deps = {};
export function initExport(deps) {
  _deps = deps;
}

function sizeEquityAndDebt(askingPrice, units, avgUnitSF, allInBuildPSF, exitPSF, monthlyRent) {
  const TAX_RATE = 0.011;
  const INS_ANNUAL = 20000;
  const AM_MONTHLY = 3000;
  const DM_MONTHLY = 5000;
  const ACQ_FEE_PCT = 0.02;
  const ORIG_FEE_PCT = 0.02;
  const EQUITY_PCT = 0.30;
  const PRE_DEV_MO = 6;
  const CONSTR_MO = 12;
  const SALE_MO = 6;

  const buildableSF = units * avgUnitSF;
  const totalDev = buildableSF * allInBuildPSF;

  const monthlyTax = askingPrice * TAX_RATE / 12;
  const monthlyIns = INS_ANNUAL / 12;
  const preDev = (monthlyTax + monthlyIns + AM_MONTHLY) * PRE_DEV_MO;
  const constr = (monthlyTax + monthlyIns + AM_MONTHLY + DM_MONTHLY) * CONSTR_MO;
  const sale = (monthlyTax + monthlyIns + AM_MONTHLY) * SALE_MO;
  const totalCarry = preDev + constr + sale;

  const acqFee = askingPrice * ACQ_FEE_PCT;

  const txnCosts = askingPrice * 0.01;
  const baseCosts = askingPrice + txnCosts + totalDev + totalCarry + acqFee;
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
    l.lotSf||'', l.lw||'', l.maxUnits, l.subdivExitPsf||l.newconPpsf||l.clusterT1psf||l.exitPsf||0,
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
function autoFitColumns(ws, opts) {
  opts = opts || {};
  var padding = opts.padding != null ? opts.padding : 3;
  var maxWidth = opts.maxWidth || 50;
  var fixed = opts.fixed || {};
  var uniformFrom = opts.uniformFrom || 0;
  var uniformTo = opts.uniformTo || 0;
  var maxLens = {};
  ws.eachRow({ includeEmpty: false }, function(row) {
    row.eachCell({ includeEmpty: false }, function(cell, colNumber) {
      if (fixed[colNumber]) return;
      var v = cell.value;
      if (v && typeof v === 'object' && v.formula != null) v = v.result;
      if (v == null) return;
      var len;
      if (typeof v === 'string') {
        len = v.length;
      } else if (v instanceof Date) {
        len = 12;
      } else if (typeof v === 'number') {
        var fmt = cell.numFmt || '';
        if (fmt.indexOf('$') >= 0) {
          var s = Math.abs(Math.round(v)).toString();
          len = s.length + Math.floor((s.length - 1) / 3) + 2;
        } else if (fmt.indexOf('%') >= 0) {
          len = 7;
        } else if (fmt.indexOf('x') >= 0) {
          len = 6;
        } else {
          var s = Math.abs(Math.round(v)).toString();
          len = s.length + Math.floor((s.length - 1) / 3);
        }
      } else {
        len = String(v).length;
      }
      if (!maxLens[colNumber] || len > maxLens[colNumber]) maxLens[colNumber] = len;
    });
  });
  if (uniformFrom && uniformTo) {
    var uMax = 0;
    for (var c = uniformFrom; c <= uniformTo; c++) {
      if (maxLens[c] && maxLens[c] > uMax) uMax = maxLens[c];
    }
    for (var c = uniformFrom; c <= uniformTo; c++) maxLens[c] = uMax;
  }
  for (var col in maxLens) {
    var c = parseInt(col);
    if (fixed[c]) continue;
    ws.getColumn(c).width = Math.min(Math.max(maxLens[c] + padding, 4), maxWidth);
  }
  for (var col in fixed) ws.getColumn(parseInt(col)).width = fixed[col];
}
function buildAssumptionsTab(wb, l, pf, ed, exitPSF, monthlyRent) {
  var ws = wb.addWorksheet('Assumptions');

  var units = pf.maxUnits;
  var avgUnitSF = proforma.avgUnitSf;
  var lotWidth = l.lw || Math.round(Math.sqrt((l.lotSf || 10000) * 0.33));
  var lotDepth = l.ld || Math.round((l.lotSf || 10000) / lotWidth);
  var slopeDecimal = (l.slope || 0) / 100;
  var bedsBaths = (l.beds || '') + ' / ' + (l.baths || '');
  var buildableSF = units * avgUnitSF;
  var allInBuildPSF = pf.adjBuildCostPerSf;
  var totalBuildCost = buildableSF * allInBuildPSF;
  var hardCosts = Math.round(totalBuildCost / 1.25);
  var softCosts = Math.round(hardCosts * 0.25);
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
  var now = new Date();
  ws.getCell('F2').value = now.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  ws.getCell('F2').font = { size: 10, color: { argb: 'FF888888' } };
  ws.getCell('F2').alignment = { horizontal: 'right' };

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
  labelCell(ws, 23, 2, 'All-In Build $/SF');   inputCell(ws, 'C23', allInBuildPSF, '$#,##0');
  labelCell(ws, 24, 2, 'Hard Costs');          setFormula(ws, 'C24', 'C22*C23/(1+C25)', hardCosts, '$#,##0');
  labelCell(ws, 25, 2, 'Soft Cost %');         inputCell(ws, 'C25', 0.25, '0.0%');
  labelCell(ws, 26, 2, 'Soft Costs');          setFormula(ws, 'C26', 'C24*C25', softCosts, '$#,##0');
  labelCell(ws, 27, 2, 'Total Build Cost');    setFormula(ws, 'C27', 'C22*C23', totalBuildCost, '$#,##0');
  ws.getCell('C27').font = { bold: true };

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
  labelCell(ws, 44, 2, 'GP Co-Invest % Price'); inputCell(ws, 'C44', 0.02, '0.0%');

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

  labelCell(ws, 14, 6, 'Equity');              setFormula(ws, 'G14', 'CEILING((C16+C18+C27+G30+G34)/(1-(1-G17)*G19)*G17,10000)', ed.equity, '$#,##0');
  ws.getCell('G14').font = { bold: true };
  labelCell(ws, 15, 6, 'Debt');                setFormula(ws, 'G15', '(C16+C18+C27+G30+G34)/(1-(1-G17)*G19)-G14', ed.debt, '$#,##0');
  ws.getCell('G15').font = { bold: true };
  labelCell(ws, 16, 6, 'Total Project Cost');  setFormula(ws, 'G16', 'G14+G15', ed.equity + ed.debt, '$#,##0');
  ws.getCell('G16').font = { bold: true };
  labelCell(ws, 17, 6, 'Target Equity %');     inputCell(ws, 'G17', 0.30, '0.0%');
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
  autoFitColumns(ws, { fixed: { 1: 2, 4: 3, 5: 2 } });
  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'portrait', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildSourcesUsesTab(wb, l, ed, pf) {
  var ws = wb.addWorksheet('Sources & Uses');

  var units = pf.maxUnits;
  var avgUnitSF = proforma.avgUnitSf;
  var buildableSF = units * avgUnitSF;
  var totalBuildCost = buildableSF * pf.adjBuildCostPerSf;
  var hardCosts = Math.round(totalBuildCost / 1.25);
  var softCosts = Math.round(hardCosts * 0.25);
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
  labelCell(ws, 6, 2, '  Loan Facility');
  setFormula(ws, 'C6', 'Assumptions!G15', ed.debt, '$#,##0');
  labelCell(ws, 7, 2, '  Origination Fee');
  setFormula(ws, 'C7', 'Assumptions!G20', ed.debt * 0.02, '$#,##0');
  ws.getCell('C7').font = { color: { argb: 'FF999999' }, italic: true };
  labelCell(ws, 8, 2, '  Capitalized Interest');
  setFormula(ws, 'C8', "'Cash Flow'!AA39", 0, '$#,##0');

  sectionHeader(ws, 10, 2, 'Equity');
  labelCell(ws, 11, 2, '  LP Equity');
  setFormula(ws, 'C11', 'Assumptions!G14-Assumptions!C16*Assumptions!C44', ed.equity - (l.price || 0) * 0.02, '$#,##0');
  labelCell(ws, 12, 2, '  GP Co-Invest');
  setFormula(ws, 'C12', 'Assumptions!C16*Assumptions!C44', (l.price || 0) * 0.02, '$#,##0');

  labelCell(ws, 14, 2, 'TOTAL SOURCES');
  ws.getCell('B14').font = { bold: true };
  setFormula(ws, 'C14', 'C6+C8+C11+C12', ed.debt + ed.equity, '$#,##0');
  ws.getCell('C14').font = { bold: true };
  ws.getCell('C14').border = { top: { style: 'double', color: { argb: 'FF000000' } } };
  setFormula(ws, 'D14', 'C14/C14', 1, '0.0%');

  // Source % of total
  setFormula(ws, 'D6', 'C6/C$14', ed.debt / (ed.debt + ed.equity), '0.0%');
  setFormula(ws, 'D8', 'C8/C$14', 0, '0.0%');
  setFormula(ws, 'D11', 'C11/C$14', (ed.equity - (l.price || 0) * 0.02) / (ed.debt + ed.equity), '0.0%');
  setFormula(ws, 'D12', 'C12/C$14', (l.price || 0) * 0.02 / (ed.debt + ed.equity), '0.0%');

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

  sectionHeader(ws, 13, 6, 'Carry');
  labelCell(ws, 14, 6, '  Capitalized Interest');
  setFormula(ws, 'G14', "'Cash Flow'!AA39", 0, '$#,##0'); // Total interest paid from CF
  labelCell(ws, 15, 6, '  Property Tax');
  setFormula(ws, 'G15', 'Assumptions!G27*Assumptions!G8', monthlyTax * 24, '$#,##0');
  labelCell(ws, 16, 6, '  Insurance');
  setFormula(ws, 'G16', 'Assumptions!G28*(Assumptions!G8/12)', 20000 * 2, '$#,##0');
  labelCell(ws, 17, 6, '  Asset Mgmt');
  setFormula(ws, 'G17', 'Assumptions!G35*Assumptions!G8', 3000 * 24, '$#,##0');
  labelCell(ws, 18, 6, '  Dev Mgmt');
  setFormula(ws, 'G18', 'Assumptions!G36*Assumptions!G6', 5000 * 12, '$#,##0');

  sectionHeader(ws, 20, 6, 'Financing');
  labelCell(ws, 21, 6, '  Origination Fee');
  setFormula(ws, 'G21', 'Assumptions!G20', ed.debt * 0.02, '$#,##0');

  labelCell(ws, 23, 6, 'TOTAL USES');
  ws.getCell('F23').font = { bold: true };
  setFormula(ws, 'G23', 'G6+G7+G8+G10+G11+G14+G15+G16+G17+G18+G21', 0, '$#,##0');
  ws.getCell('G23').font = { bold: true };
  ws.getCell('G23').border = { top: { style: 'double', color: { argb: 'FF000000' } } };
  setFormula(ws, 'H23', 'G23/G23', 1, '0.0%');

  // Uses % of total
  setFormula(ws, 'H6', 'G6/G$23', 0, '0.0%');
  setFormula(ws, 'H7', 'G7/G$23', 0, '0.0%');
  setFormula(ws, 'H8', 'G8/G$23', 0, '0.0%');
  setFormula(ws, 'H10', 'G10/G$23', 0, '0.0%');
  setFormula(ws, 'H11', 'G11/G$23', 0, '0.0%');
  setFormula(ws, 'H14', 'G14/G$23', 0, '0.0%');
  setFormula(ws, 'H15', 'G15/G$23', 0, '0.0%');
  setFormula(ws, 'H16', 'G16/G$23', 0, '0.0%');
  setFormula(ws, 'H17', 'G17/G$23', 0, '0.0%');
  setFormula(ws, 'H18', 'G18/G$23', 0, '0.0%');
  setFormula(ws, 'H21', 'G21/G$23', 0, '0.0%');

  // Check row
  labelCell(ws, 25, 2, 'CHECK (Sources - Uses)');
  setFormula(ws, 'C25', 'C14-G23', 0, '$#,##0');
  ws.getCell('C25').font = { bold: true, color: { argb: 'FFFF0000' } };

  autoFitColumns(ws, { fixed: { 1: 2, 3: 12, 4: 10, 5: 3, 7: 12, 8: 10 } });
  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'landscape', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildCashFlowTab(wb, l, ed, pf) {
  var ws = wb.addWorksheet('Cash Flow');
  var MONTHS = 24;
  var CF_FMT = '$#,##0;-$#,##0;" "'; // hide $0 cells — show blank
  var totalCol = MONTHS + 3; // col index for TOTAL (months in cols 3..26, total in 27 = AA)
  var totalLtr = colLetter(totalCol); // AA

  var price = l.price || 0;
  var units = pf.maxUnits;
  var avgUnitSF = proforma.avgUnitSf;
  var buildableSF = units * avgUnitSF;
  var totalBuildCost = buildableSF * pf.adjBuildCostPerSf;
  var hardCosts = Math.round(totalBuildCost / 1.25);
  var softCosts = Math.round(hardCosts * 0.25);
  var exitPSF = l.subdivExitPsf || l.newconPpsf || l.clusterT1psf || l.exitPsf || 0;
  var grossRevenue = units * avgUnitSF * exitPSF;
  var txCostPct = proforma.txnCostPct / 100;
  var SCURVE = [0.04, 0.07, 0.10, 0.12, 0.13, 0.14, 0.13, 0.11, 0.08, 0.05, 0.02, 0.01];

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
      setFormula(ws, cl + row, formulaFn(m, cl), resultFn(m), CF_FMT);
    }
    // Total column = SUM
    setFormula(ws, totalLtr + row, 'SUM(C' + row + ':' + colLetter(MONTHS + 2) + row + ')', 0, CF_FMT);
    ws.getCell(totalLtr + row).font = { bold: true };
  }

  // ── Row 5: SOURCES header ──
  sectionHeader(ws, 5, 2, 'SOURCES');
  ws.getCell('B5').fill = _hdrFill; ws.getCell('B5').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '5').fill = _hdrFill; }
  ws.getCell(totalLtr + '5').fill = _hdrFill;

  // Row 6: LP Equity Call — Month 0 only
  labelCell(ws, 6, 2, '  LP Equity Call');
  var gpCoInvestVal = (l.price || 0) * 0.02;
  var lpEquityVal = ed.equity - gpCoInvestVal;
  monthFormula(6,
    function(m) { return m === 0 ? 'Assumptions!G14-Assumptions!C16*Assumptions!C44' : '0'; },
    function(m) { return m === 0 ? lpEquityVal : 0; }
  );

  // Row 7: GP Co-Invest Call — Month 0 only
  labelCell(ws, 7, 2, '  GP Co-Invest Call');
  monthFormula(7,
    function(m) { return m === 0 ? 'Assumptions!C16*Assumptions!C44' : '0'; },
    function(m) { return m === 0 ? gpCoInvestVal : 0; }
  );

  // Row 8: Debt Draws — 70% of all uses each month (equity covers 30%)
  labelCell(ws, 8, 2, '  Debt Draws');
  monthFormula(8,
    function(m, cl) { return '(1-Assumptions!$G$17)*(' + cl + '15+' + cl + '25+' + cl + '30)'; },
    function(m) {
      // Result approximation: 70% of each month's total uses
      var devM = 0, carryM = 0, feesM = 0;
      // Dev: land+txn at M0, hard/soft S-curve M6-17
      if (m === 0) devM += price + price * 0.01;
      if (m >= 6 && m < 18) devM += SCURVE[m - 6] * (hardCosts + softCosts);
      // Carry: tax+ins+AM every month, DM during construction
      carryM = price * 0.011 / 12 + 20000 / 12 + 3000;
      if (m >= 6 && m < 18) carryM += 5000;
      // Fees: acq fee + orig fee at M0
      if (m === 0) feesM += price * 0.02 + ed.debt * 0.02;
      return 0.70 * (devM + carryM + feesM);
    }
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

  // Row 13: Hard Costs — S-curve during construction
  labelCell(ws, 13, 2, '  Hard Costs');
  monthFormula(13,
    function(m) { return 'IF(AND(' + m + '>=Assumptions!$G$5,' + m + '<Assumptions!$G$5+Assumptions!$G$6),CHOOSE(' + m + '-Assumptions!$G$5+1,0.04,0.07,0.10,0.12,0.13,0.14,0.13,0.11,0.08,0.05,0.02,0.01)*Assumptions!C24,0)'; },
    function(m) { return (m >= 6 && m < 18) ? SCURVE[m - 6] * hardCosts : 0; }
  );

  // Row 14: Soft Costs — S-curve during construction
  labelCell(ws, 14, 2, '  Soft Costs');
  monthFormula(14,
    function(m) { return 'IF(AND(' + m + '>=Assumptions!$G$5,' + m + '<Assumptions!$G$5+Assumptions!$G$6),CHOOSE(' + m + '-Assumptions!$G$5+1,0.04,0.07,0.10,0.12,0.13,0.14,0.13,0.11,0.08,0.05,0.02,0.01)*Assumptions!C26,0)'; },
    function(m) { return (m >= 6 && m < 18) ? SCURVE[m - 6] * softCosts : 0; }
  );

  // Row 15: Subtotal Development
  labelCell(ws, 15, 2, 'Subtotal Development');
  ws.getCell('B15').font = { bold: true };
  monthFormula(15,
    function(m, cl) { return 'SUM(' + cl + '12:' + cl + '14)'; },
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

  // ── Row 32: TOTAL USES (excl. interest — capitalized on loan) ──
  labelCell(ws, 32, 2, 'TOTAL USES');
  ws.getCell('B32').font = { bold: true, size: 11 };
  monthFormula(32,
    function(m, cl) { return cl + '15+' + cl + '25+' + cl + '30'; },
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
      setFormula(ws, cl + '35', '0', 0, CF_FMT);
    } else {
      var prevCl = colLetter(m + 2);
      setFormula(ws, cl + '35', prevCl + '38', 0, CF_FMT);
    }
  }

  // Row 36: + Draws (= construction draws from row 8)
  labelCell(ws, 36, 2, '  + Draws');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '36', cl + '8', 0, CF_FMT);
  }
  setFormula(ws, totalLtr + '36', 'SUM(C36:' + colLetter(MONTHS + 2) + '36)', 0, CF_FMT);
  ws.getCell(totalLtr + '36').font = { bold: true };

  // Row 37: + Capitalized Interest (accrued on opening balance, added to loan)
  labelCell(ws, 37, 2, '  + Capitalized Interest');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '37', cl + '35*Assumptions!$G$18/12', 0, CF_FMT);
  }
  setFormula(ws, totalLtr + '37', 'SUM(C37:' + colLetter(MONTHS + 2) + '37)', 0, CF_FMT);
  ws.getCell(totalLtr + '37').font = { bold: true };

  // Row 38: Closing Balance (= Opening + Draws + Capitalized Interest)
  labelCell(ws, 38, 2, '  Closing Balance');
  ws.getCell('B38').font = { bold: true };
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '38', cl + '35+' + cl + '36+' + cl + '37', 0, CF_FMT);
  }

  // Row 39: Cumulative Interest
  labelCell(ws, 39, 2, '  Cumulative Interest');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    if (m === 0) {
      setFormula(ws, cl + '39', cl + '37', 0, CF_FMT);
    } else {
      var prevCl = colLetter(m + 2);
      setFormula(ws, cl + '39', prevCl + '39+' + cl + '37', 0, CF_FMT);
    }
  }
  setFormula(ws, totalLtr + '39', colLetter(MONTHS + 2) + '39', 0, CF_FMT);
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

  // Row 47: Loan Repayment (closing balance incl. capitalized interest)
  labelCell(ws, 47, 2, '  Loan Repayment');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '47', 'IF(' + m + '=Assumptions!$G$8-1,' + cl + '38,0)', 0, CF_FMT);
  }
  setFormula(ws, totalLtr + '47', 'SUM(C47:' + colLetter(MONTHS + 2) + '47)', 0, CF_FMT);
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
    function(m) { return m === lastMo ? 'Assumptions!G14-Assumptions!C16*Assumptions!C44' : '0'; },
    function(m) { return m === lastMo ? lpEquityVal : 0; }
  );

  // Row 54: GP Return of Capital
  labelCell(ws, 54, 2, '  GP Return of Capital');
  monthFormula(54,
    function(m) { return m === lastMo ? 'Assumptions!C16*Assumptions!C44' : '0'; },
    function(m) { return m === lastMo ? gpCoInvestVal : 0; }
  );

  // Row 55: LP Preferred Return
  labelCell(ws, 55, 2, '  LP Preferred Return');
  monthFormula(55,
    function(m) {
      if (m !== lastMo) return '0';
      return '(Assumptions!G14-Assumptions!C16*Assumptions!C44)*Assumptions!C42*Assumptions!G8/12';
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

  // ── Row 61-63: LLC BANK BALANCE ──
  sectionHeader(ws, 61, 2, 'LLC BANK BALANCE');
  ws.getCell('B61').fill = _hdrFill; ws.getCell('B61').font = _hdrFont;
  for (var m = 0; m < MONTHS; m++) { ws.getCell(colLetter(m+3) + '61').fill = _hdrFill; }
  ws.getCell(totalLtr + '61').fill = _hdrFill;

  // Row 62: Beginning Balance
  labelCell(ws, 62, 2, '  Beginning Balance');
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    if (m === 0) {
      setFormula(ws, cl + '62', '0', 0, CF_FMT);
    } else {
      var prevCl = colLetter(m + 2);
      setFormula(ws, cl + '62', prevCl + '63', 0, CF_FMT);
    }
  }

  // Row 63: Ending Balance (= Beginning + Sources - Uses + Exit)
  labelCell(ws, 63, 2, '  Ending Balance');
  ws.getCell('B63').font = { bold: true };
  for (var m = 0; m < MONTHS; m++) {
    var cl = colLetter(m + 3);
    setFormula(ws, cl + '63', cl + '62+' + cl + '9-' + cl + '32+' + cl + '48', 0, CF_FMT);
  }

  // Freeze panes: B column labels + header rows
  var cfFixed = { 1: 2 };
  for (var fc = 3; fc <= totalCol; fc++) cfFixed[fc] = 11;
  autoFitColumns(ws, { fixed: cfFixed });
  ws.views = [{ state: 'frozen', xSplit: 2, ySplit: 3, showGridLines: false }];
  ws.pageSetup = { orientation: 'landscape', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildOutputsTab(wb, ed) {
  var ws = wb.addWorksheet('Outputs');

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
  ws.getCell('B29').value = 'SENSITIVITY ANALYSIS';
  ws.getCell('B29').font = _hdrFont; ws.getCell('B29').fill = _hdrFill;
  ['C29','D29','E29','F29','G29'].forEach(function(a){ ws.getCell(a).fill = _hdrFill; });

  var baseFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFDCE6F1' } };
  var crossFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  var buildDeltas = [-0.15, -0.075, 0, 0.075, 0.15];
  var exitDeltas = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];

  // Full LP waterfall formulas matching Cash Flow distributions:
  // LP equity = K × equity% − price × GP co-invest%
  // LP pref = LP equity × pref rate × months / 12
  // Distributable = MAX(0, Revenue − Cost − Cap Interest − Pref)
  // LP total = LP equity + Pref + (1−promote) × Distributable
  // MOIC = LP total / LP equity;  IRR = MOIC^(12/M) − 1
  function moicFormula(R, K, M) {
    var le = '(' + K + ')*Assumptions!G17-Assumptions!C16*Assumptions!C44';
    var pr = '(' + le + ')*Assumptions!C42*' + M + '/12';
    var ci = "'Cash Flow'!AA39";
    var db = 'MAX(0,' + R + '-(' + K + ')-' + ci + '-' + pr + ')';
    return 'IF(' + le + '=0,0,(' + le + '+' + pr + '+(1-Assumptions!C43)*' + db + ')/(' + le + '))';
  }
  function irrFormula(R, K, M) {
    return 'IFERROR((' + moicFormula(R, K, M) + ')^(12/' + M + ')-1,-1)';
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
      var revE = 'Assumptions!C20*Assumptions!C21*$B' + row + '*(1-Assumptions!C37-Assumptions!G37)';
      var costE = 'Assumptions!G16+(' + cl2 + '$32-Assumptions!C23)*Assumptions!C22';
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
      var revE2 = 'Assumptions!C20*Assumptions!C21*$B' + row2 + '*(1-Assumptions!C37-Assumptions!G37)';
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
      var revE3 = 'Assumptions!C20*Assumptions!C21*' + cl6 + '$' + h3 + '*(1-Assumptions!C37-Assumptions!G37)';
      setFormula(ws, cl6 + row3, irrFormula(revE3, 'Assumptions!G16', '$B' + row3), 0, '0.0%');
      if (months === 24 && exitDeltas3[xi2] === 0) {
        ws.getCell(cl6 + row3).fill = baseFill;
        ws.getCell(cl6 + row3).font = { bold: true };
      } else if (months === 24 || exitDeltas3[xi2] === 0) {
        ws.getCell(cl6 + row3).fill = crossFill;
      }
    }
  }

  autoFitColumns(ws, { fixed: { 1: 2, 3: 12, 4: 12, 5: 12, 6: 12, 7: 12 } });
  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'portrait', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildBTRTab(wb) {
  var ws = wb.addWorksheet('BTR Hold');

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

  labelCell(ws, 17, 2, 'Implied LTV');
  setFormula(ws, 'C17', 'IF(C13=0,0,C18/C13)', 0, '0.0%');

  labelCell(ws, 18, 2, 'Refi Loan');
  setFormula(ws, 'C18', 'Assumptions!G15', 0, '$#,##0');

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

  autoFitColumns(ws, { fixed: { 1: 2 } });
  ws.views = [{ showGridLines: false }];
  ws.pageSetup = { orientation: 'portrait', fitToPage: true, fitToWidth: 1 };
  return ws;
}

function buildExitCompsTab(wb, l) {
  var compResult = _deps.findCompsForListing(l);
  if (!compResult.used.length && !compResult.ref.length) return null;

  // ── XLS-specific filtering for exit comps ──
  // Combine used + ref, then apply stricter XLS filters
  var allRaw = compResult.used.concat(compResult.ref);

  // 24-month cutoff date
  var cutoffDate = new Date();
  cutoffDate.setMonth(cutoffDate.getMonth() - 24);
  var cutoffStr = cutoffDate.toISOString().slice(0, 10); // YYYY-MM-DD

  var filtered = allRaw.filter(function(c) {
    // SQFT: 1,300 - 2,000
    if (!c.sqft || c.sqft < 1300 || c.sqft > 2000) return false;
    // Sale date: last 24 months
    if (!c.date || c.date < cutoffStr) return false;
    // Year built: 2000+ OR T1 tier (new construction / remodel)
    if (c.yb && c.yb < 2000 && c.t !== 1) return false;
    return true;
  });

  // Sort by distance (closest first), cap at 100
  filtered.sort(function(a, b) { return a.dist - b.dist; });
  if (filtered.length > 100) filtered = filtered.slice(0, 100);

  if (!filtered.length) return null;

  var cs = wb.addWorksheet('Exit Comps');
  var el = _deps.exitLabel(l);

  cs.getCell('A1').value = 'Exit Comps for ' + (l.address || '');
  cs.getCell('A1').font = { bold: true, size: 14 };
  cs.mergeCells('A1:J1');
  cs.getCell('A2').value = el.label + '  \u2014  $' + el.psf + '/SF  (' + filtered.length + ' comps)';
  cs.getCell('A2').font = { bold: true, size: 11 };
  cs.mergeCells('A2:J2');

  var compHeaders = ['Address','Sale Price','$/SF','SqFt','Beds','Baths','Year Built','Tier','Sale Date','Distance (mi)'];
  var headerRow = cs.getRow(4);
  compHeaders.forEach(function(h, i) {
    var cell = headerRow.getCell(i + 1);
    cell.value = h;
    cell.font = { bold: true };
    cell.fill = { type:'pattern', pattern:'solid', fgColor:{ argb:'FFE0E0E0' } };
  });

  var greenFill = { type:'pattern', pattern:'solid', fgColor:{ argb:'FFE8F5E9' } };
  for (var ci = 0; ci < filtered.length; ci++) {
    var comp = filtered[ci];
    var row = cs.getRow(5 + ci);

    row.getCell(1).value = comp.address || '';
    row.getCell(2).value = comp.price || 0;
    row.getCell(2).numFmt = '$#,##0';
    row.getCell(3).value = comp.ppsf || 0;
    row.getCell(3).numFmt = '$#,##0';
    row.getCell(4).value = comp.sqft || 0;
    row.getCell(4).numFmt = '#,##0';
    row.getCell(5).value = comp.bd || '';
    row.getCell(6).value = comp.ba || '';
    row.getCell(7).value = comp.yb || '';
    row.getCell(8).value = comp.t ? 'T' + comp.t : '';
    row.getCell(9).value = comp.date || '';
    row.getCell(10).value = comp.dist ? +comp.dist.toFixed(2) : '';
    row.getCell(10).numFmt = '0.00';

    // Highlight first 20 closest comps in green
    if (ci < 20) {
      for (var k = 1; k <= 10; k++) row.getCell(k).fill = greenFill;
    }
  }
  autoFitColumns(cs, { fixed: { 2: 12, 3: 8, 4: 7, 5: 5, 6: 6, 7: 11, 8: 5, 9: 11, 10: 13 } });
  cs.views = [{ showGridLines: false }];
  return cs;
}

// ── Pre-Export Modal ──
function showExportModal(lat, lng, type) {
  var l = _deps.getLISTINGS().find(function(x){ return x.lat===lat && x.lng===lng; });
  if (!l) { alert('Listing not found'); return; }
  var pf = calculateProForma(l);

  var defExitPSF = l.subdivExitPsf || l.newconPpsf || l.clusterT1psf || l.exitPsf || 0;
  var defBuildPSF = pf.adjBuildCostPerSf;
  var defUnits = pf.maxUnits;
  var defAvgUnitSF = proforma.avgUnitSf;
  var defRent = l.estRentMonth || l.fmr3br || 4000;
  var defPrice = l.price || 0;

  var exitSrc = l.subdivExitPsf ? 'subdiv' : l.newconPpsf ? 'new-con' : l.clusterT1psf ? 'T1 norm' : l.exitPsf ? 'zone P75' : 'none';
  var slopePct = l.slope || 0;
  var buildSrc = slopePct > 0 ? 'slope-adj ' + slopePct + '%' : 'base';
  var rentSrc = l.estRentMonth ? 'est rent' : l.fmr3br ? 'HUD SAFMR' : 'default';

  var typeLabel = type === 'xls' ? 'Export XLS Model' : 'Export Offering Memo';
  var addr = l.address || '';
  var zone = (l.zone || 'R1').toUpperCase();

  var existing = document.getElementById('exportModal');
  if (existing) existing.remove();

  var overlay = document.createElement('div');
  overlay.id = 'exportModal';
  overlay.className = 'modal-overlay active';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.onclick = function(e) { if (e.target === overlay) closeExportModal(); };

  overlay.innerHTML =
    '<div class="modal-panel" style="max-width:440px">' +
      '<div class="modal-header">' +
        '<div><h3>' + typeLabel + '</h3>' +
        '<div style="font-size:12px;color:var(--text-dim);margin-top:2px">' + addr + ' \u00b7 ' + zone + '</div></div>' +
        '<button class="modal-close" onclick="closeExportModal()">\u00d7</button>' +
      '</div>' +
      '<div class="modal-body" style="padding:16px 20px">' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px 16px">' +
          _expField('Asking Price', 'expAskingPrice', defPrice, '$', '') +
          _expField('Exit $/SF', 'expExitPSF', defExitPSF, '$', exitSrc) +
          _expField('Build Cost $/SF', 'expBuildPSF', Math.round(defBuildPSF), '$', buildSrc) +
          _expField('Units', 'expUnits', defUnits, '', '') +
          _expField('Avg Unit SF', 'expAvgUnitSF', defAvgUnitSF, '', 'sf') +
          _expField('Monthly Rent', 'expMonthlyRent', defRent, '$', rentSrc) +
        '</div>' +
        '<button id="expDoExport" style="margin-top:16px;width:100%;padding:10px;border:none;border-radius:8px;' +
          'background:var(--accent);color:#fff;font-weight:600;font-size:14px;cursor:pointer">' +
          (type === 'xls' ? 'Download XLS' : 'Generate OM') +
        '</button>' +
      '</div>' +
    '</div>';

  document.body.appendChild(overlay);

  var defaults = { askingPrice: defPrice, exitPSF: defExitPSF, allInBuildPSF: defBuildPSF, units: defUnits, avgUnitSF: defAvgUnitSF, monthlyRent: defRent };
  document.getElementById('expDoExport').onclick = async function() {
    var btn = this;
    var vals = _readExpValues(defaults);
    btn.textContent = 'Exporting\u2026';
    btn.disabled = true;
    btn.style.opacity = '0.7';
    try {
      if (type === 'xls') await exportModel(lat, lng, vals);
      else await exportOM(lat, lng, vals);
      closeExportModal();
    } catch (err) {
      console.error(err);
      btn.textContent = type === 'xls' ? 'Download XLS' : 'Generate OM';
      btn.disabled = false;
      btn.style.opacity = '1';
    }
  };

  var first = document.getElementById('expAskingPrice');
  if (first) first.focus();
}

function _expField(label, id, value, prefix, srcLabel) {
  var srcHtml = srcLabel ? '<span style="font-size:10px;color:var(--text-dim);margin-left:4px">(' + srcLabel + ')</span>' : '';
  var fmtVal = (value == null || value === 0) ? '0' : Math.round(value).toLocaleString('en-US');
  return '<div>' +
    '<label style="font-size:11px;color:var(--text-dim);display:block;margin-bottom:3px">' + label + srcHtml + '</label>' +
    '<div style="display:flex;align-items:center;background:var(--surface2);border:1px solid var(--border);border-radius:6px;overflow:hidden">' +
      (prefix ? '<span style="padding:0 0 0 8px;color:var(--text-dim);font-size:13px">' + prefix + '</span>' : '') +
      '<input id="' + id + '" type="text" value="' + fmtVal + '" ' +
        'style="flex:1;background:none;border:none;color:var(--text);padding:8px 8px 8px ' + (prefix ? '2px' : '8px') + ';font-size:14px;width:100%;outline:none">' +
    '</div>' +
  '</div>';
}

function _readExpValues(defaults) {
  function parseNum(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    var raw = el.value.replace(/[,$\s]/g, '');
    var n = Number(raw);
    return isNaN(n) || raw === '' ? fallback : n;
  }
  var units = parseNum('expUnits', defaults.units);
  if (units < 1) units = 1;
  if (units > 10) units = 10;
  units = Math.round(units);
  return {
    askingPrice: parseNum('expAskingPrice', defaults.askingPrice),
    exitPSF: parseNum('expExitPSF', defaults.exitPSF),
    allInBuildPSF: parseNum('expBuildPSF', defaults.allInBuildPSF),
    units: units,
    avgUnitSF: parseNum('expAvgUnitSF', defaults.avgUnitSF),
    monthlyRent: parseNum('expMonthlyRent', defaults.monthlyRent),
  };
}

function closeExportModal() {
  var el = document.getElementById('exportModal');
  if (el) el.remove();
}

async function exportModel(lat, lng, overrides) {
  var ov = overrides || {};
  var l = _deps.getLISTINGS().find(function(x){ return x.lat===lat && x.lng===lng; });
  if (!l) { alert('Listing not found'); return; }

  var pf = calculateProForma(l);

  // Shallow-copy listing and pf so overrides don't mutate originals
  var ll = Object.assign({}, l);
  var pfOv = Object.assign({}, pf);

  if (ov.askingPrice != null) ll.price = ov.askingPrice;
  if (ov.exitPSF != null) { ll.subdivExitPsf = ov.exitPSF; ll.newconPpsf = 0; ll.clusterT1psf = 0; ll.exitPsf = 0; }
  if (ov.monthlyRent != null) ll.estRentMonth = ov.monthlyRent;
  if (ov.units != null) pfOv.maxUnits = ov.units;
  if (ov.allInBuildPSF != null) pfOv.adjBuildCostPerSf = ov.allInBuildPSF;

  var exitPSF = ll.subdivExitPsf || ll.newconPpsf || ll.clusterT1psf || ll.exitPsf || 0;
  var monthlyRent = ll.estRentMonth || ll.fmr3br || 4000;
  var units = pfOv.maxUnits;
  var savedAvgUnitSf = proforma.avgUnitSf;
  if (ov.avgUnitSF != null) proforma.avgUnitSf = ov.avgUnitSF;
  var avgUnitSF = proforma.avgUnitSf;
  var buildableSF = units * avgUnitSF;

  var ed = sizeEquityAndDebt(ll.price, units, avgUnitSF, pfOv.adjBuildCostPerSf, exitPSF, monthlyRent);
  var btr = calculateBTRProForma(l);

  // Build workbook
  var wb = new ExcelJS.Workbook();
  wb.creator = 'SB 1123 Deal Finder';

  buildAssumptionsTab(wb, ll, pfOv, ed, exitPSF, monthlyRent);
  buildSourcesUsesTab(wb, ll, ed, pfOv);
  buildCashFlowTab(wb, ll, ed, pfOv);
  buildOutputsTab(wb, ed);
  buildBTRTab(wb);
  buildExitCompsTab(wb, l);

  proforma.avgUnitSf = savedAvgUnitSf;

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

async function exportOM(lat, lng, overrides) {
  var ov = overrides || {};
  var OM_API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? '' : 'https://sb1123-om-api.fly.dev';

  var l = _deps.getLISTINGS().find(function(x){ return x.lat===lat && x.lng===lng; });
  if (!l) { alert('Listing not found'); return; }

  var pf = calculateProForma(l);
  var btr = calculateBTRProForma(l);
  var exitPSF = ov.exitPSF != null ? ov.exitPSF : (l.subdivExitPsf || l.newconPpsf || l.clusterT1psf || l.exitPsf || 0);
  var monthlyRent = ov.monthlyRent != null ? ov.monthlyRent : (l.estRentMonth || l.fmr3br || 4000);
  var avgUnitSF = ov.avgUnitSF != null ? ov.avgUnitSF : proforma.avgUnitSf;
  var units = ov.units != null ? ov.units : pf.maxUnits;
  var buildableSF_om = units * avgUnitSF;
  var allInBuildPSF = ov.allInBuildPSF != null ? ov.allInBuildPSF : pf.adjBuildCostPerSf;
  var askingPrice = ov.askingPrice != null ? ov.askingPrice : (l.price || 0);

  var ed = sizeEquityAndDebt(askingPrice, units, avgUnitSF, allInBuildPSF, exitPSF, monthlyRent);

  // ── Constants (must match sizeEquityAndDebt) ──
  var SOFT_PCT = 0.25;
  var SUBDIV = buildableSF_om * 10;
  var AE = buildableSF_om * 5;
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
  var GP_COINVEST = 0.02;
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
  var totalDev = buildableSF * allInBuildPSF;
  var hardCosts = Math.round((totalDev - SUBDIV - AE) / (1 + SOFT_PCT));
  var softCosts = Math.round(hardCosts * SOFT_PCT);

  // ── Capital structure ──
  var totalProjectCost = ed.totalCost;
  var equity = ed.equity;
  var debt = totalProjectCost - equity;
  var gpCoinvestEquity = Math.round(askingPrice * GP_COINVEST);
  var lpEquity = equity - gpCoinvestEquity;
  var origFee = debt * ORIG_FEE_PCT;

  // ── Carry costs (monthly accumulation) ──
  var monthlyTax = askingPrice * TAX_RATE / 12;
  var monthlyIns = INS_ANNUAL / 12;

  var totalPropTax = monthlyTax * HOLD_MO;
  var totalInsurance = monthlyIns * HOLD_MO;
  var totalAssetMgmt = AM_MONTHLY * HOLD_MO;
  var totalDevMgmt = DM_MONTHLY * CONSTR_MO;

  // ── Fees ──
  var acqFee = askingPrice * ACQ_FEE_PCT;

  // ── Interest (month-by-month PIK matching XLS Cash Flow) ──
  var SCURVE = [0.04, 0.07, 0.10, 0.12, 0.13, 0.14, 0.13, 0.11, 0.08, 0.05, 0.02, 0.01];
  var monthlyTaxAmt = askingPrice * TAX_RATE / 12;
  var monthlyInsAmt = INS_ANNUAL / 12;
  var loanBalance = 0;
  var totalInterest = 0;
  for (var m = 0; m < HOLD_MO; m++) {
    var devUses = 0;
    if (m === 0) devUses = askingPrice + askingPrice * 0.01; // land + txn costs
    if (m >= PRE_DEV_MO && m < PRE_DEV_MO + CONSTR_MO) {
      var si = m - PRE_DEV_MO;
      devUses += totalDev * SCURVE[si];
    }
    var carryUses = monthlyTaxAmt + monthlyInsAmt + AM_MONTHLY;
    if (m >= PRE_DEV_MO && m < PRE_DEV_MO + CONSTR_MO) carryUses += DM_MONTHLY;
    var feeUses = 0;
    if (m === 0) feeUses = acqFee + origFee;
    var totalUses = devUses + carryUses + feeUses;

    // Debt draw = 70% of uses (matching XLS Row 8)
    var draw = totalUses * (1 - 0.30);

    // Capitalized interest on opening balance (matching XLS Row 37)
    var monthInterest = loanBalance * INTEREST_RATE / 12;
    totalInterest += monthInterest;

    // Closing balance (matching XLS Row 38)
    loanBalance += draw + monthInterest;
  }
  var dispFee = 0;  // computed on exit below
  var totalSponsorFees = acqFee + totalAssetMgmt + totalDevMgmt;  // disposition added at exit

  // ── Exit ──
  var grossRevenue = units * avgUnitSF * exitPSF;
  var txCosts = grossRevenue * TX_COST_PCT;
  dispFee = grossRevenue * DISP_FEE_PCT;
  totalSponsorFees += dispFee;
  var netSaleProceeds = grossRevenue - txCosts - dispFee;

  // ── Waterfall ──
  var loanRepayment = loanBalance;
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
    asking_price: askingPrice,

    // Development
    units: units,
    unit_sf: avgUnitSF,
    buildable_sf: buildableSF,
    build_cost_psf: allInBuildPSF,
    hard_costs: hardCosts,
    soft_cost_pct: SOFT_PCT,
    soft_costs: softCosts,
    subdivision_cost: SUBDIV,
    ae_cost: AE,
    demo_cost: 0,
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
    interest_treatment: 'Cash Pay',

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
  var pptComps = compResult.used.concat(compResult.ref);
  pptComps.sort(function(a, b) { return (a.dist || 99) - (b.dist || 99); });
  d.comps = pptComps.slice(0, 8).map(function(c) {
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
      var msg = errText.match(/Message: (.+?)\./);
      alert('OM generation failed (' + resp.status + '): ' + (msg ? msg[1] : errText.substring(0, 200)));
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

export { exportCSV, exportModel, exportOM, showExportModal, closeExportModal, sizeEquityAndDebt };

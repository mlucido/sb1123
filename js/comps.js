// ── js/comps.js — Comp search, display, and sorting ──
// Extracted from index.html P4-1

// ── Dependencies (injected via initComps) ──
var _deps = {};
export function initComps(deps){ _deps = deps; }

// ── Constants ──
var COMP_SQFT_MIN = 1300, COMP_SQFT_MAX = 3500;
var ZONE_TYPE_MAP = {R1:'SFR',R2:'TH/Condo',R3:'MF 2-4',R4:'MF 5+',LAND:'Land'};
var PT_LABEL = {1:'SFR',2:'Condo',3:'Townhome',4:'MF 2-4',5:'MF 5+'};
var ADJ_ZONES = {R1:['R2'],R2:['R1','R3'],R3:['R2','R4'],R4:['R3'],LAND:['R1']};
var RENTAL_PT_LABEL = {1:'SFR',2:'Condo',3:'Townhome',4:'MF 2-4',5:'MF 5+'};
var SFR_TH_TYPES = [1,2,3,4];

// ── Sale comp state ──
var compsTableActive = false;
var compsMapLayer = null;
var compsRadiusCircle = null;
var rentalCompsTableActive = false;
var rentalCompsMapLayer = null;
var rentalCompsRadiusCircle = null;
var savedPipelineHeader = '';

// ── Helpers ──

export function distMi(lat1,lng1,lat2,lng2){
  var dlat=(lat2-lat1)*69, dlng=(lng2-lng1)*69*Math.cos(lat1*Math.PI/180);
  return Math.sqrt(dlat*dlat+dlng*dlng);
}

function searchCompsInRadius(lat,lng,radiusMi){
  var grid = _deps.getCompSpatialGrid();
  var COMPS = _deps.getCOMPS();
  if(!grid || !COMPS.length) return [];
  var radiusDeg=radiusMi/69, S=0.005;
  var rMin=Math.floor((lat-radiusDeg)/S), rMax=Math.floor((lat+radiusDeg)/S);
  var cMin=Math.floor((lng-radiusDeg)/S), cMax=Math.floor((lng+radiusDeg)/S);
  var out=[];
  for(var r=rMin;r<=rMax;r++){
    for(var c=cMin;c<=cMax;c++){
      var cell=grid[r+','+c];
      if(cell) cell.forEach(function(comp){
        if(Math.abs(comp.lat-lat)<=radiusDeg && Math.abs(comp.lng-lng)<=radiusDeg){
          out.push(Object.assign({},comp,{dist:distMi(lat,lng,comp.lat,comp.lng)}));
        }
      });
    }
  }
  return out;
}

export function findCompsForListing(l){
  var COMPS = _deps.getCOMPS();
  if(!COMPS.length) return {used:[],ref:[],source:'none',radius:0};

  var source,searchRadius,targetCount;

  if(l.subdivExitPsf){
    source='subdiv'; searchRadius=l.subdivCompRadius||2; targetCount=l.subdivCompCount||0;
  } else if(l.newconPpsf){
    source='newcon'; searchRadius=2; targetCount=l.newconCount||0;
  } else if(l.exitPsf){
    source='zone'; searchRadius=l.compRadius||1; targetCount=l.compCount||0;
  } else {
    return {used:[],ref:[],source:'none',radius:0};
  }

  var wideRadius = Math.min(searchRadius*2, 5);
  var all = searchCompsInRadius(l.lat,l.lng,wideRadius);

  var used=[], ref=[];
  for(var i=0;i<all.length;i++){
    var c=all[i];
    var inRadius = c.dist <= searchRadius + 0.05;
    var isUsed = false;

    if(source==='newcon'){
      var isNewcon = c.yb && c.yb >= 2021;
      var zmOrAdj = l.newconZoneMatch
        ? c.zone===l.zone
        : (c.zone===l.zone || (ADJ_ZONES[l.zone]||[]).includes(c.zone));
      var inBand = c.sqft>=COMP_SQFT_MIN && c.sqft<=COMP_SQFT_MAX;
      isUsed = inRadius && isNewcon && zmOrAdj && inBand;
    } else if(source==='subdiv'){
      isUsed = inRadius && c.zone===l.zone && c.yb && c.yb>=2021;
    } else {
      var method = l.compMethod||'';
      var zoneMatch = method.startsWith('zone') ? c.zone===l.zone : true;
      var inBand2 = c.sqft>=COMP_SQFT_MIN && c.sqft<=COMP_SQFT_MAX;
      isUsed = inRadius && zoneMatch && inBand2;
    }

    c.isUsed = isUsed;
    c.isOutlier = c.sqft<400 || c.ppsf>2000;
    if(isUsed && !c.isOutlier) used.push(c);
    else ref.push(c);
  }

  if(source==='zone' && used.length < targetCount){
    var method2 = l.compMethod||'';
    var zoneMatch2 = method2.startsWith('zone');
    for(var j=ref.length-1;j>=0;j--){
      var c2=ref[j];
      if(c2.dist<=searchRadius+0.05 && !c2.isOutlier && (zoneMatch2?c2.zone===l.zone:true)){
        c2.isUsed=true;
        used.push(ref.splice(j,1)[0]);
      }
    }
  }

  used.sort(function(a,b){return a.dist-b.dist;});
  ref.sort(function(a,b){return a.dist-b.dist;});
  return {used:used,ref:ref,source:source,radius:searchRadius};
}

// ── Comp table display ──

function formatCompDate(d){
  if(!d) return '\u2014';
  var parts = d.split('-');
  if(parts.length>=3) return parts[0].substring(0,3)+' '+parts[2];
  return d;
}

function compRow(c){
  var outlier = c.isOutlier;
  var style = outlier ? 'opacity:0.4' : c.isUsed ? 'border-left:3px solid var(--green)' : '';
  var tag = outlier ? ' <span style="color:var(--orange);font-size:9px">&#9888; outlier</span>' : '';
  return '<tr style="cursor:pointer;'+style+'" onclick="map.flyTo(['+c.lat+','+c.lng+'],17)">'
    +'<td style="text-align:center">'+(c.isUsed&&!outlier?'<span style="color:var(--green)">&#10003;</span>':'')+'</td>'
    +'<td style="white-space:nowrap;max-width:200px;overflow:hidden;text-overflow:ellipsis">'+(c.address||'\u2014')+tag+'</td>'
    +'<td>$'+c.price.toLocaleString()+'</td>'
    +'<td style="color:'+(c.ppsf>=800?'var(--green)':c.ppsf>=600?'var(--yellow)':'var(--red)')+'">$'+c.ppsf+'</td>'
    +'<td>'+c.sqft.toLocaleString()+'</td>'
    +'<td>'+(c.bd||'\u2014')+'/'+(c.ba||'\u2014')+'</td>'
    +'<td'+(c.pt===3?' style="color:var(--green);font-weight:600"':'')+'>'+(PT_LABEL[c.pt]||ZONE_TYPE_MAP[c.zone]||c.zone||'\u2014')+'</td>'
    +'<td>'+(c.zone||'\u2014')+'</td>'
    +'<td>'+(c.yb||'\u2014')+'</td>'
    +'<td style="color:'+(c.t===1?'var(--green)':'var(--text-dim)')+'">T'+(c.t||'?')+'</td>'
    +'<td>'+formatCompDate(c.date)+'</td>'
    +'<td>'+c.dist.toFixed(2)+'mi</td>'
    +'</tr>';
}

export function showCompsTable(lat,lng){
  var LISTINGS = _deps.getLISTINGS();
  var COMPS = _deps.getCOMPS();
  var map = _deps.getMap();
  var l = LISTINGS.find(function(ll){return ll.lat===lat&&ll.lng===lng;});
  if(!l || !COMPS.length) return;
  if(!_deps.isListingsPanelOpen()) _deps.toggleListingsPanel();

  if(rentalCompsTableActive) hideRentalCompsTable();

  var result = findCompsForListing(l);
  var used=result.used, ref=result.ref, source=result.source, radius=result.radius;
  var sourceLabel = {subdiv:'Subdivision',newcon:'New Construction',zone:'Zone-Matched'}[source]||source;

  document.getElementById('tableWrap').style.display='none';
  document.getElementById('mobileCards').style.display='none';
  var header = document.querySelector('.listings-panel-header');
  savedPipelineHeader = header.innerHTML;
  header.innerHTML = '<button onclick="hideCompsTable()" style="background:none;border:1px solid var(--border);color:var(--text);padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px;white-space:nowrap">&larr; Back to Pipeline</button>'
    +'<div style="flex:1;min-width:0">'
    +'<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">BTS COMPS &mdash; '+l.address+'</div>'
    +'<div style="font-size:11px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+sourceLabel+' &bull; '+used.length+' used / '+(used.length+ref.length)+' nearby within '+radius.toFixed(1)+'mi</div>'
    +'</div>'
    +'<button class="listings-panel-close" onclick="hideCompsTable()">x</button>';

  var wrap = document.getElementById('compsTableWrap');
  if(!wrap){
    wrap = document.createElement('div');
    wrap.id = 'compsTableWrap';
    wrap.className = 'listings-table-wrap';
    var panel = document.getElementById('listingsPanel');
    panel.insertBefore(wrap, document.getElementById('tableWrap'));
  }
  wrap.style.display = '';

  var thead = '<table class="listings-table"><thead><tr>'
    +'<th style="width:30px">Used</th>'
    +'<th onclick="sortCompsTable(\'address\')">Address</th>'
    +'<th onclick="sortCompsTable(\'price\')">Sale Price</th>'
    +'<th onclick="sortCompsTable(\'ppsf\')">$/SF</th>'
    +'<th onclick="sortCompsTable(\'sqft\')">SqFt</th>'
    +'<th>Bd/Ba</th>'
    +'<th>Type</th>'
    +'<th onclick="sortCompsTable(\'zone\')">Zone</th>'
    +'<th onclick="sortCompsTable(\'yb\')">Yr Built</th>'
    +'<th onclick="sortCompsTable(\'t\')">Tier</th>'
    +'<th onclick="sortCompsTable(\'date\')">Sale Date</th>'
    +'<th onclick="sortCompsTable(\'dist\')">Dist</th>'
    +'</tr></thead>';

  var dividerRow = ref.length ? '<tr><td colspan="12" style="text-align:center;padding:6px;color:var(--text-dim);font-size:11px;border-top:2px solid var(--border);border-bottom:1px solid var(--border)">&mdash; Additional comps for reference ('+ref.length+') &mdash;</td></tr>' : '';
  var tbody = '<tbody>'+used.map(function(c){return compRow(c);}).join('')+dividerRow+ref.filter(function(c){return !c.isOutlier;}).map(function(c){return compRow(c);}).join('')+'</tbody></table>';
  wrap.innerHTML = thead + tbody;

  wrap._used = used;
  wrap._ref = ref;
  wrap._listing = l;

  if(compsMapLayer){ map.removeLayer(compsMapLayer); }
  if(compsRadiusCircle){ map.removeLayer(compsRadiusCircle); }
  compsMapLayer = L.layerGroup();
  used.forEach(function(c){
    L.circleMarker([c.lat,c.lng],{
      radius:6, color:'#22c55e', fillColor:'#22c55e', fillOpacity:0.8, weight:1
    }).bindPopup('<b>'+(c.address||'\u2014')+'</b><br>$'+c.price.toLocaleString()+' &bull; $'+c.ppsf+'/sf &bull; '+c.sqft+'sf<br>'+(c.date||'\u2014')+' &bull; T'+(c.t||'?')+' &bull; '+c.zone).addTo(compsMapLayer);
  });
  ref.filter(function(c){return !c.isOutlier;}).forEach(function(c){
    L.circleMarker([c.lat,c.lng],{
      radius:4, color:'#64748b', fillColor:'#64748b', fillOpacity:0.4, weight:1
    }).addTo(compsMapLayer);
  });
  compsRadiusCircle = L.circle([l.lat,l.lng],{
    radius: radius*1609.34, color:'#22c55e', fillColor:'#22c55e',
    fillOpacity:0.04, weight:1, dashArray:'6,4'
  });
  compsMapLayer.addTo(map);
  compsRadiusCircle.addTo(map);
  compsTableActive = true;
}

export function sortCompsTable(key){
  var wrap = document.getElementById('compsTableWrap');
  if(!wrap || !wrap._used) return;
  var prev = wrap.getAttribute('data-sort-key');
  var dir = prev===key && wrap.getAttribute('data-sort-dir')!=='asc' ? 'asc' : 'desc';
  wrap.setAttribute('data-sort-key', key);
  wrap.setAttribute('data-sort-dir', dir==='asc' ? 'desc' : 'asc');
  var sorter = function(a,b){
    var va=a[key],vb=b[key];
    if(typeof va==='string') return dir==='asc'?va.localeCompare(vb):vb.localeCompare(va);
    va=va||0;vb=vb||0;
    return dir==='asc'?va-vb:vb-va;
  };
  wrap._used.sort(sorter);
  wrap._ref.sort(sorter);
  var dividerRow = wrap._ref.length ? '<tr><td colspan="12" style="text-align:center;padding:6px;color:var(--text-dim);font-size:11px;border-top:2px solid var(--border);border-bottom:1px solid var(--border)">&mdash; Additional comps for reference ('+wrap._ref.length+') &mdash;</td></tr>' : '';
  wrap.querySelector('tbody').innerHTML = wrap._used.map(function(c){return compRow(c);}).join('') + dividerRow + wrap._ref.filter(function(c){return !c.isOutlier;}).map(function(c){return compRow(c);}).join('');
}

export function hideCompsTable(){
  var map = _deps.getMap();
  document.getElementById('tableWrap').style.display='';
  document.getElementById('mobileCards').style.display='';
  var header = document.querySelector('.listings-panel-header');
  if(savedPipelineHeader) header.innerHTML = savedPipelineHeader;
  var wrap = document.getElementById('compsTableWrap');
  if(wrap) wrap.remove();
  if(compsMapLayer){ map.removeLayer(compsMapLayer); compsMapLayer=null; }
  if(compsRadiusCircle){ map.removeLayer(compsRadiusCircle); compsRadiusCircle=null; }
  compsTableActive = false;
}

// ── Rental Comps ──

export function buildRentalCompGrid(comps){
  var grid = {};
  var S = 0.005;
  comps.forEach(function(c){
    var key = Math.floor(c.lat/S)+','+Math.floor(c.lng/S);
    if(!grid[key]) grid[key]=[];
    grid[key].push(c);
  });
  return grid;
}

function searchRentalCompsInRadius(lat,lng,radiusMi){
  var grid = _deps.getRentalCompGrid();
  var RENTAL_COMPS = _deps.getRENTAL_COMPS();
  if(!grid || !RENTAL_COMPS.length) return [];
  var radiusDeg=radiusMi/69, S=0.005;
  var rMin=Math.floor((lat-radiusDeg)/S), rMax=Math.floor((lat+radiusDeg)/S);
  var cMin=Math.floor((lng-radiusDeg)/S), cMax=Math.floor((lng+radiusDeg)/S);
  var out=[];
  for(var r=rMin;r<=rMax;r++){
    for(var c=cMin;c<=cMax;c++){
      var cell=grid[r+','+c];
      if(cell) cell.forEach(function(comp){
        if(Math.abs(comp.lat-lat)<=radiusDeg && Math.abs(comp.lng-lng)<=radiusDeg){
          out.push(Object.assign({},comp,{dist:distMi(lat,lng,comp.lat,comp.lng)}));
        }
      });
    }
  }
  return out;
}

export function findRentalCompsForListing(l){
  var RENTAL_COMPS = _deps.getRENTAL_COMPS();
  if(!RENTAL_COMPS.length) return {used:[],ref:[],radius:0,method:'none'};
  var method = l.rentMethod||'';

  var usedRadius = l.rentCompRadius || 1;
  var wideRadius = Math.min(usedRadius * 2, 5);
  var all = searchRentalCompsInRadius(l.lat, l.lng, wideRadius);

  var used=[], ref=[];
  for(var i=0;i<all.length;i++){
    var c=all[i];
    var inRadius = c.dist <= usedRadius + 0.05;
    var isUsed = false;

    if(method === 'rental-comp' || method === 'rental-comp-wide'){
      var bdOk = (c.bd||0) === 3;
      var sfOk = (c.sqft||0) >= 800 && (c.sqft||0) <= 2500;
      var ptOk = SFR_TH_TYPES.includes(c.pt||0);
      isUsed = inRadius && bdOk && sfOk && ptOk;
    } else if(method === 'rental-adj'){
      var bdOk2 = (c.bd||0) >= 2;
      var sfOk2 = (c.sqft||0) >= 800;
      isUsed = inRadius && bdOk2 && sfOk2;
    } else {
      isUsed = false;
    }

    c.isUsed = isUsed;
    if(isUsed) used.push(c);
    else ref.push(c);
  }

  used.sort(function(a,b){return a.dist-b.dist;});
  ref.sort(function(a,b){return a.dist-b.dist;});
  return {used:used, ref:ref, radius:usedRadius, method:method};
}

function rentalCompRow(c){
  var rentPsf = (c.sqft && c.sqft > 0) ? (c.rent / c.sqft).toFixed(2) : '\u2014';
  var style = c.isUsed ? 'border-left:3px solid var(--green)' : '';
  return '<tr style="cursor:pointer;'+style+'" onclick="map.flyTo(['+c.lat+','+c.lng+'],17)">'
    +'<td style="text-align:center">'+(c.isUsed?'<span style="color:var(--green)">&#10003;</span>':'')+'</td>'
    +'<td style="white-space:nowrap;max-width:200px;overflow:hidden;text-overflow:ellipsis">'+(c.addr||'\u2014')+'</td>'
    +'<td>$'+c.rent.toLocaleString()+'</td>'
    +'<td>'+(rentPsf==='\u2014'?'\u2014':'$'+rentPsf)+'</td>'
    +'<td>'+(c.bd||'\u2014')+'</td>'
    +'<td>'+(c.ba||'\u2014')+'</td>'
    +'<td>'+(c.sqft?c.sqft.toLocaleString():'\u2014')+'</td>'
    +'<td>'+(RENTAL_PT_LABEL[c.pt]||'\u2014')+'</td>'
    +'<td>'+c.dist.toFixed(2)+'mi</td>'
    +'</tr>';
}

export function showRentalCompsTable(lat,lng){
  var LISTINGS = _deps.getLISTINGS();
  var RENTAL_COMPS = _deps.getRENTAL_COMPS();
  var map = _deps.getMap();
  var l = LISTINGS.find(function(ll){return ll.lat===lat&&ll.lng===lng;});
  if(!l || !RENTAL_COMPS.length) return;
  if(!_deps.isListingsPanelOpen()) _deps.toggleListingsPanel();

  if(compsTableActive) hideCompsTable();

  var result = findRentalCompsForListing(l);
  var used=result.used, ref=result.ref, radius=result.radius;

  document.getElementById('tableWrap').style.display='none';
  document.getElementById('mobileCards').style.display='none';
  var header = document.querySelector('.listings-panel-header');
  if(!rentalCompsTableActive && !compsTableActive) savedPipelineHeader = header.innerHTML;
  header.innerHTML = '<button onclick="hideRentalCompsTable()" style="background:none;border:1px solid var(--border);color:var(--text);padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px;white-space:nowrap">&larr; Back to Pipeline</button>'
    +'<div style="flex:1;min-width:0">'
    +'<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">RENTAL COMPS &mdash; '+l.address+'</div>'
    +'<div style="font-size:11px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+used.length+' used / '+(used.length+ref.length)+' nearby within '+radius.toFixed(1)+'mi</div>'
    +'</div>'
    +'<button class="listings-panel-close" onclick="hideRentalCompsTable()">x</button>';

  var wrap = document.getElementById('rentalCompsTableWrap');
  if(!wrap){
    wrap = document.createElement('div');
    wrap.id = 'rentalCompsTableWrap';
    wrap.className = 'listings-table-wrap';
    var panel = document.getElementById('listingsPanel');
    panel.insertBefore(wrap, document.getElementById('tableWrap'));
  }
  wrap.style.display = '';

  var thead = '<table class="listings-table"><thead><tr>'
    +'<th style="width:30px">Used</th>'
    +'<th onclick="sortRentalCompsTable(\'addr\')">Address</th>'
    +'<th onclick="sortRentalCompsTable(\'rent\')">Rent $/mo</th>'
    +'<th onclick="sortRentalCompsTable(\'rentPsf\')">$/SF/mo</th>'
    +'<th onclick="sortRentalCompsTable(\'bd\')">Beds</th>'
    +'<th onclick="sortRentalCompsTable(\'ba\')">Baths</th>'
    +'<th onclick="sortRentalCompsTable(\'sqft\')">SqFt</th>'
    +'<th>Type</th>'
    +'<th onclick="sortRentalCompsTable(\'dist\')">Dist</th>'
    +'</tr></thead>';

  var dividerRow = ref.length ? '<tr><td colspan="9" style="text-align:center;padding:6px;color:var(--text-dim);font-size:11px;border-top:2px solid var(--border);border-bottom:1px solid var(--border)">&mdash; Additional comps for reference ('+ref.length+') &mdash;</td></tr>' : '';
  var tbody = '<tbody>'+used.map(function(c){return rentalCompRow(c);}).join('')+dividerRow+ref.map(function(c){return rentalCompRow(c);}).join('')+'</tbody></table>';
  wrap.innerHTML = thead + tbody;

  wrap._used = used;
  wrap._ref = ref;
  wrap._listing = l;

  if(rentalCompsMapLayer){ map.removeLayer(rentalCompsMapLayer); }
  if(rentalCompsRadiusCircle){ map.removeLayer(rentalCompsRadiusCircle); }
  rentalCompsMapLayer = L.layerGroup();
  used.forEach(function(c){
    L.circleMarker([c.lat,c.lng],{
      radius:6, color:'#3b82f6', fillColor:'#3b82f6', fillOpacity:0.8, weight:1
    }).bindPopup('<b>'+(c.addr||'\u2014')+'</b><br>$'+c.rent.toLocaleString()+'/mo &bull; '+(c.bd||'?')+'bd/'+(c.ba||'?')+'ba &bull; '+(c.sqft?c.sqft.toLocaleString()+'sf':'\u2014')).addTo(rentalCompsMapLayer);
  });
  ref.forEach(function(c){
    L.circleMarker([c.lat,c.lng],{
      radius:4, color:'#64748b', fillColor:'#64748b', fillOpacity:0.4, weight:1
    }).addTo(rentalCompsMapLayer);
  });
  rentalCompsRadiusCircle = L.circle([l.lat,l.lng],{
    radius: radius*1609.34, color:'#3b82f6', fillColor:'#3b82f6',
    fillOpacity:0.04, weight:1, dashArray:'6,4'
  });
  rentalCompsMapLayer.addTo(map);
  rentalCompsRadiusCircle.addTo(map);
  rentalCompsTableActive = true;
}

export function sortRentalCompsTable(key){
  var wrap = document.getElementById('rentalCompsTableWrap');
  if(!wrap || !wrap._used) return;
  var prev = wrap.getAttribute('data-sort-key');
  var dir = prev===key && wrap.getAttribute('data-sort-dir')!=='asc' ? 'asc' : 'desc';
  wrap.setAttribute('data-sort-key', key);
  wrap.setAttribute('data-sort-dir', dir==='asc' ? 'desc' : 'asc');
  var sorter = function(a,b){
    var va,vb;
    if(key==='rentPsf'){
      va=(a.sqft&&a.sqft>0)?a.rent/a.sqft:0;
      vb=(b.sqft&&b.sqft>0)?b.rent/b.sqft:0;
    } else {
      va=a[key]; vb=b[key];
    }
    if(typeof va==='string') return dir==='asc'?va.localeCompare(vb):vb.localeCompare(va);
    va=va||0;vb=vb||0;
    return dir==='asc'?va-vb:vb-va;
  };
  wrap._used.sort(sorter);
  wrap._ref.sort(sorter);
  var dividerRow = wrap._ref.length ? '<tr><td colspan="9" style="text-align:center;padding:6px;color:var(--text-dim);font-size:11px;border-top:2px solid var(--border);border-bottom:1px solid var(--border)">&mdash; Additional comps for reference ('+wrap._ref.length+') &mdash;</td></tr>' : '';
  wrap.querySelector('tbody').innerHTML = wrap._used.map(function(c){return rentalCompRow(c);}).join('') + dividerRow + wrap._ref.map(function(c){return rentalCompRow(c);}).join('');
}

export function hideRentalCompsTable(){
  var map = _deps.getMap();
  document.getElementById('tableWrap').style.display='';
  document.getElementById('mobileCards').style.display='';
  var header = document.querySelector('.listings-panel-header');
  if(savedPipelineHeader) header.innerHTML = savedPipelineHeader;
  var wrap = document.getElementById('rentalCompsTableWrap');
  if(wrap) wrap.remove();
  if(rentalCompsMapLayer){ map.removeLayer(rentalCompsMapLayer); rentalCompsMapLayer=null; }
  if(rentalCompsRadiusCircle){ map.removeLayer(rentalCompsRadiusCircle); rentalCompsRadiusCircle=null; }
  rentalCompsTableActive = false;
}

// ── State queries (for other modules) ──
export function isCompsTableActive(){ return compsTableActive; }
export function isRentalCompsTableActive(){ return rentalCompsTableActive; }

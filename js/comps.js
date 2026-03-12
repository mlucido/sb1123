// ── js/comps.js — Comp search, display, and sorting ──
// Extracted from index.html P4-1

import { proforma } from './proforma.js';

// ── Dependencies (injected via initComps) ──
var _deps = {};
export function initComps(deps){ _deps = deps; }

// ── Constants ──
var METERS_PER_MILE = 1609.34;
var SCORE_GOOD = 80;
var SCORE_OK = 50;
var COMP_SQFT_MIN = 1300, COMP_SQFT_MAX = 3500;
var PT_LABEL = {1:'SFR',2:'Condo',3:'Townhome',4:'MF 2-4',5:'MF 5+'};
var BTS_ALLOWED_PT = [1, 2, 3];  // SFR, Condo, Townhome — exclude MF for BTS exit comps
var MONTH_MAP = {january:1,february:2,march:3,april:4,may:5,june:6,july:7,august:8,september:9,october:10,november:11,december:12};
function parseSaleDate(d){
  if(!d) return 0;
  var parts=d.split('-');
  if(parts.length>=3){var m=MONTH_MAP[parts[0].toLowerCase()]||0; return parseInt(parts[2])*10000+m*100+parseInt(parts[1]);}
  return 0;
}
var PT_COLORS = {1:'#3b82f6', 2:'#a855f7', 3:'#22c55e'};
var PT_DEFAULT_COLOR = '#94a3b8';

// ── Sale comp grouping ──
var SALE_GROUP_ORDER = ['sfr','condo','townhome'];
var SALE_GROUP_LABELS = {sfr:'Single Family', condo:'Condos', townhome:'Townhomes'};
var SALE_PT_TO_GROUP = {1:'sfr', 2:'condo', 3:'townhome'};
var SALE_GROUP_CAP = 10;

// ── Sale comp state ──
var compsTableActive = false;
var compsMapLayer = null;
var compsRadiusCircle = null;
var rentalCompsTableActive = false;
var rentalCompsMapLayer = null;
var rentalCompsRadiusCircle = null;

// ── Helpers ──

function redfinLink(address){
  // Google search is the most reliable way to reach a Redfin property page
  // (redfin.com/search?query= just loads the homepage)
  return 'https://www.google.com/search?q=redfin+'+encodeURIComponent(address||'');
}

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

  if(l.exitPsf){
    source='spatial'; searchRadius=l.compRadius||1; targetCount=l.compCount||0;
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

    var inBand2 = c.sqft>=COMP_SQFT_MIN && c.sqft<=COMP_SQFT_MAX;
    isUsed = inRadius && inBand2;

    c.isUsed = isUsed;
    c.isOutlier = c.sqft<400 || c.ppsf>2000;
    var ptAllowed = BTS_ALLOWED_PT.indexOf(c.pt) !== -1;
    if(isUsed && !c.isOutlier && ptAllowed) used.push(c);
    else ref.push(c);
  }

  if(used.length < targetCount){
    for(var j=ref.length-1;j>=0;j--){
      var c2=ref[j];
      if(c2.dist<=searchRadius+0.05 && !c2.isOutlier){
        c2.isUsed=true;
        used.push(ref.splice(j,1)[0]);
      }
    }
  }

  used.sort(function(a,b){return a.dist-b.dist;});
  ref.sort(function(a,b){return a.dist-b.dist;});

  // Group by property type for table display
  var pool = used.concat(ref.filter(function(c){return !c.isOutlier;}));
  var groups = {};
  SALE_GROUP_ORDER.forEach(function(g){ groups[g] = []; });
  pool.forEach(function(c){
    var g = SALE_PT_TO_GROUP[c.pt];
    if(g) groups[g].push(c);
  });
  // Sort each group by distance, cap at SALE_GROUP_CAP
  var totalCount = pool.length;
  SALE_GROUP_ORDER.forEach(function(g){
    groups[g].sort(function(a,b){return a.dist-b.dist;});
    groups[g] = groups[g].slice(0, SALE_GROUP_CAP);
  });
  var allComps = [];
  SALE_GROUP_ORDER.forEach(function(g){ allComps = allComps.concat(groups[g]); });

  return {used:used,ref:ref,groups:groups,allComps:allComps,source:source,radius:searchRadius,usedCount:used.length,totalCount:totalCount};
}

// ── Sale comp helpers ──

function saleGroupAvgs(comps){
  if(!comps.length) return {avgPrice:0, avgPpsf:0, avgSqft:0};
  var prices=[], psfs=[], sqfts=[];
  comps.forEach(function(c){
    prices.push(c.price);
    if(c.ppsf) psfs.push(c.ppsf);
    if(c.sqft) sqfts.push(c.sqft);
  });
  return {
    avgPrice: prices.length ? Math.round(prices.reduce(function(a,b){return a+b;},0)/prices.length) : 0,
    avgPpsf: psfs.length ? Math.round(psfs.reduce(function(a,b){return a+b;},0)/psfs.length) : 0,
    avgSqft: sqfts.length ? Math.round(sqfts.reduce(function(a,b){return a+b;},0)/sqfts.length) : 0
  };
}

// ── Comp table display ──

function formatCompDate(d){
  if(!d) return '\u2014';
  var parts = d.split('-');
  if(parts.length>=3) return parts[0].substring(0,3)+' '+parts[2];
  return d;
}

function compRow(c){
  var style = c.isUsed ? 'border-left:3px solid var(--green)' : '';
  return '<tr style="cursor:pointer;'+style+'" onclick="map.flyTo(['+c.lat+','+c.lng+'],17)" onmouseenter="highlightCompPin('+c.lat+','+c.lng+')" onmouseleave="unhighlightCompPin()">'
    +'<td style="white-space:nowrap;max-width:200px;overflow:hidden;text-overflow:ellipsis"><a class="redfin-link" href="'+redfinLink(c.address)+'" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="View on Redfin">'+(c.address||'\u2014')+' &#8599;</a></td>'
    +'<td>$'+c.price.toLocaleString()+'</td>'
    +'<td style="color:'+(c.ppsf>=800?'var(--green)':c.ppsf>=600?'var(--yellow)':'var(--red)')+'">$'+c.ppsf+'</td>'
    +'<td>'+c.sqft.toLocaleString()+'</td>'
    +'<td>'+(c.bd||'\u2014')+'/'+(c.ba||'\u2014')+'</td>'
    +'<td>'+(c.zone||'\u2014')+'</td>'
    +'<td>'+(c.yb||'\u2014')+'</td>'
    +'<td style="color:'+(c.t1s==='T1-Reno'?'#d97706':c.t===1?'var(--green)':'var(--text-dim)')+'">'+( c.t1s || ('T'+(c.t||'?')) )+'</td>'
    +'<td>'+formatCompDate(c.date)+'</td>'
    +'<td>'+c.dist.toFixed(2)+'mi</td>'
    +'</tr>';
}

function saleGroupTheadRow(group){
  return '<tr>'
    +'<th data-sort="address" onclick="sortCompsTable(\'address\',\''+group+'\')" style="cursor:pointer">Address<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="price" onclick="sortCompsTable(\'price\',\''+group+'\')" style="cursor:pointer">Sale Price<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="ppsf" onclick="sortCompsTable(\'ppsf\',\''+group+'\')" style="cursor:pointer">$/SF<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="sqft" onclick="sortCompsTable(\'sqft\',\''+group+'\')" style="cursor:pointer">SqFt<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="bd" onclick="sortCompsTable(\'bd\',\''+group+'\')" style="cursor:pointer">Bd/Ba<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="zone" onclick="sortCompsTable(\'zone\',\''+group+'\')" style="cursor:pointer">Zone<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="yb" onclick="sortCompsTable(\'yb\',\''+group+'\')" style="cursor:pointer">Yr Built<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="t" onclick="sortCompsTable(\'t\',\''+group+'\')" style="cursor:pointer">Tier<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="date" onclick="sortCompsTable(\'date\',\''+group+'\')" style="cursor:pointer">Sale Date<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="dist" onclick="sortCompsTable(\'dist\',\''+group+'\')" style="cursor:pointer">Dist<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
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
  var groups = result.groups;
  var source = result.source;
  var radius = result.radius;
  var sourceLabel = {subdiv:'Subdivision',spatial:'Spatial P75'}[source]||source;
  var totalShown = result.allComps.length;

  document.getElementById('tableWrap').style.display='none';
  document.getElementById('mobileCards').style.display='none';
  document.getElementById('pipelineHeader').style.display='none';
  var compsHdr = document.getElementById('compsHeader');
  compsHdr.innerHTML = '<button onclick="hideCompsTable()" style="background:none;border:1px solid var(--border);color:var(--text);padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px;white-space:nowrap">&larr; Back to Pipeline</button>'
    +'<div style="flex:1;min-width:0">'
    +'<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">BTS COMPS &mdash; '+l.address+'</div>'
    +'<div style="font-size:11px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+sourceLabel+' &bull; '+totalShown+' comps within '+radius.toFixed(1)+'mi <span style="margin-left:8px;font-size:10px"><span style="color:#3b82f6">&#9679;</span> SFR <span style="color:#a855f7">&#9679;</span> Condo <span style="color:#22c55e">&#9679;</span> TH</span></div>'
    +'</div>'
    +'<button onclick="exportSaleCompsCsv()" style="background:none;border:1px solid var(--border);color:var(--text-dim);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;white-space:nowrap" title="Export all sale comps to CSV">&#x2913; CSV</button>'
    +'<button class="listings-panel-close" onclick="hideCompsTable()">x</button>';
  compsHdr.style.display='';

  var wrap = document.getElementById('compsTableWrap');
  if(!wrap){
    wrap = document.createElement('div');
    wrap.id = 'compsTableWrap';
    wrap.className = 'listings-table-wrap';
    var panel = document.getElementById('listingsPanel');
    panel.insertBefore(wrap, document.getElementById('tableWrap'));
  }
  wrap.style.display = '';

  // Build grouped sections
  var html = '';
  SALE_GROUP_ORDER.forEach(function(g){
    var comps = groups[g] || [];
    if(!comps.length) return;
    var label = SALE_GROUP_LABELS[g] || g;
    var avgs = saleGroupAvgs(comps);
    var avgLine = avgs.avgPrice ? 'Avg: $'+(avgs.avgPrice>=1000000?(avgs.avgPrice/1000000).toFixed(1)+'M':(avgs.avgPrice/1000).toFixed(0)+'K')+' | $'+avgs.avgPpsf+'/SF | '+avgs.avgSqft.toLocaleString()+' SF' : '';
    html += '<div class="sale-group-section" data-group="'+g+'" style="margin-bottom:8px">'
      +'<div class="sale-group-header" style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;background:var(--card-bg);border:1px solid var(--border);border-radius:6px 6px 0 0;cursor:pointer" onclick="toggleSaleGroup(\''+g+'\')">'
      +'<span style="font-size:12px;font-weight:700;color:var(--text)">'+label.toUpperCase()+' <span style="font-weight:400;color:var(--text-dim)">('+comps.length+')</span>'+(avgLine ? ' <span style="font-weight:400;font-size:11px;color:var(--text-dim);margin-left:8px">'+avgLine+'</span>' : '')+'</span>'
      +'<span class="sale-group-chevron" style="font-size:10px;color:var(--text-dim)">\u25BC</span>'
      +'</div>'
      +'<div class="sale-group-body">'
      +'<table class="listings-table" style="margin:0"><thead>'+saleGroupTheadRow(g)+'</thead>'
      +'<tbody data-group="'+g+'">'+comps.map(function(c){return compRow(c);}).join('')+'</tbody></table>'
      +'</div></div>';
  });

  if(!html){
    html = '<div style="padding:20px;text-align:center;color:var(--text-dim)">No sale comps found within '+radius.toFixed(1)+'mi</div>';
  }

  wrap.innerHTML = html;
  wrap._groups = groups;
  wrap._listing = l;
  wrap._result = result;

  // Map markers
  if(compsMapLayer){ map.removeLayer(compsMapLayer); }
  if(compsRadiusCircle){ map.removeLayer(compsRadiusCircle); }
  compsMapLayer = L.layerGroup();
  result.allComps.forEach(function(c){
    var ptColor = PT_COLORS[c.pt] || PT_DEFAULT_COLOR;
    var isUsed = c.isUsed;
    L.circleMarker([c.lat,c.lng],{
      radius: isUsed ? 7 : 4,
      color: isUsed ? '#ffffff' : ptColor,
      fillColor: ptColor,
      fillOpacity: isUsed ? 0.9 : 0.25,
      weight: isUsed ? 2 : 1,
      bubblingMouseEvents: false
    }).bindPopup(
      '<b>'+(c.address||'\u2014')+'</b>'
      +'<br>$'+c.price.toLocaleString()+' &bull; <b>$'+c.ppsf+'/SF</b> &bull; '+c.sqft.toLocaleString()+' SF'
      +'<br>'+(c.bd||'\u2014')+'bd/'+(c.ba||'\u2014')+'ba &bull; Built '+(c.yb||'\u2014')
      +'<br>'+(PT_LABEL[c.pt]||'\u2014')+' &bull; '+(c.zone||'\u2014')+' &bull; '+formatCompDate(c.date)
      +'<br>'+c.dist.toFixed(2)+'mi'
      +'<br><a href="'+redfinLink(c.address)+'" target="_blank" rel="noopener" style="color:#3b82f6;font-size:11px">View on Redfin &#8599;</a>'
    ).addTo(compsMapLayer);
  });
  compsRadiusCircle = L.circle([l.lat,l.lng],{
    radius: radius*METERS_PER_MILE, color:'#22c55e', fillColor:'#22c55e',
    fillOpacity:0.04, weight:1, dashArray:'6,4'
  });
  compsMapLayer.addTo(map);
  compsRadiusCircle.addTo(map);
  compsTableActive = true;
  // Zoom to show comp radius — deferred to avoid Leaflet animation/autoPan conflicts
  var compsBounds = compsRadiusCircle.getBounds().pad(0.1);
  setTimeout(function(){ map.stop(); map.flyToBounds(compsBounds, {duration:0.6, maxZoom:17}); }, 50);
}

export function sortCompsTable(key, group){
  var wrap = document.getElementById('compsTableWrap');
  if(!wrap || !wrap._groups) return;
  var comps = wrap._groups[group];
  if(!comps || !comps.length) return;

  var stateKey = 'data-sort-'+group;
  var prev = wrap.getAttribute(stateKey+'-key');
  var prevDir = wrap.getAttribute(stateKey+'-dir');
  var dir = prev===key ? (prevDir==='asc' ? 'desc' : 'asc') : 'desc';
  wrap.setAttribute(stateKey+'-key', key);
  wrap.setAttribute(stateKey+'-dir', dir);

  var sorter = function(a,b){
    var va,vb;
    if(key==='date'){va=parseSaleDate(a.date);vb=parseSaleDate(b.date);}
    else if(key==='bd'){va=a.bd||0;vb=b.bd||0;}
    else{va=a[key];vb=b[key];}
    if(typeof va==='string') return dir==='asc'?(va||'').localeCompare(vb||''):(vb||'').localeCompare(va||'');
    va=va||0;vb=vb||0;
    return dir==='asc'?va-vb:vb-va;
  };
  comps.sort(sorter);

  var tbody = wrap.querySelector('tbody[data-group="'+group+'"]');
  if(tbody) tbody.innerHTML = comps.map(function(c){return compRow(c);}).join('');

  // Update arrows within this group's section
  var section = wrap.querySelector('.sale-group-section[data-group="'+group+'"]');
  if(section){
    section.querySelectorAll('th[data-sort]').forEach(function(th){
      var arrow = th.querySelector('.sort-arrow');
      var active = th.getAttribute('data-sort')===key;
      arrow.textContent = active ? (dir==='asc'?' \u25B2':' \u25BC') : ' \u25BD';
      arrow.style.opacity = active ? '1' : '0.4';
    });
  }
}

export function toggleSaleGroup(group){
  var wrap = document.getElementById('compsTableWrap');
  if(!wrap) return;
  var section = wrap.querySelector('.sale-group-section[data-group="'+group+'"]');
  if(!section) return;
  var body = section.querySelector('.sale-group-body');
  var chevron = section.querySelector('.sale-group-chevron');
  if(body.style.display === 'none'){
    body.style.display = '';
    if(chevron) chevron.textContent = '\u25BC';
  } else {
    body.style.display = 'none';
    if(chevron) chevron.textContent = '\u25B6';
  }
}

export function hideCompsTable(){
  var map = _deps.getMap();
  document.getElementById('tableWrap').style.display='';
  document.getElementById('mobileCards').style.display='';
  document.getElementById('compsHeader').style.display='none';
  document.getElementById('pipelineHeader').style.display='';
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

// ── Rental comp match scoring ──
var RENTAL_GROUP_ORDER = ['townhome','condo','sfr','mf'];
var RENTAL_GROUP_LABELS = {townhome:'Townhomes',condo:'Condos',sfr:'Single Family',mf:'Multi-Family'};
var RENTAL_PT_TO_GROUP = {3:'townhome',2:'condo',1:'sfr',4:'mf',5:'mf'};
var RENTAL_PT_LABEL = {1:'SFR',2:'Condo',3:'Townhome',4:'Apartment',5:'Multi-Family'};
var RENTAL_GROUP_CAP = 10;

function rentalMatchScore(c, maxRadius){
  var score = 0;
  // Property type (40 pts): TH=40, Condo=30, SFR=20, MF=15
  var ptScores = {3:40, 2:30, 1:20, 4:15, 5:15};
  score += ptScores[c.pt] || 0;
  // Bed match (15 pts): 3BR exact = 15, 2BR or 4BR = 8, else 0
  var bd = c.bd || 0;
  if(bd === 3) score += 15;
  else if(bd === 2 || bd === 4) score += 8;
  // Size proximity (15 pts): closer to target unit SF = higher
  var sqft = c.sqft || 0;
  var targetSf = proforma.avgUnitSf || 1750;
  if(sqft > 0) score += Math.max(0, 15 * (1 - Math.abs(sqft - targetSf) / targetSf));
  // Recency (20 pts): newer = higher, requires dt field
  if(c.dt){
    var dtParts = c.dt.split('-');
    if(dtParts.length === 3){
      var compDate = new Date(parseInt(dtParts[0]), parseInt(dtParts[1])-1, parseInt(dtParts[2]));
      var ageDays = Math.max(0, (Date.now() - compDate.getTime()) / 86400000);
      score += Math.max(0, 20 * (1 - ageDays / 365));
    }
  }
  // Distance (10 pts): closer = higher
  if(maxRadius > 0) score += Math.max(0, 10 * (1 - (c.dist || 0) / maxRadius));
  return Math.round(score);
}

export function findRentalCompsForListing(l){
  var RENTAL_COMPS = _deps.getRENTAL_COMPS();
  if(!RENTAL_COMPS.length) return {groups:{},allComps:[],radius:0,totalCount:0,method:l.rentMethod||'none',summary:{medianRentPsf:0,p75RentPsf:0,primaryCount:0,supportingCount:0}};

  // Gate: 2+ BR, 700-4000 SF, types 1-5 (SFR/Condo/TH/Apt/MF)
  // Scoring handles relevance — 3BR near 1750 SF score highest
  function passFilter(c){ return [1,2,3,4,5].indexOf(c.pt||0)!==-1 && (c.bd||0)>=2 && (c.sqft||0)>=700 && (c.sqft||0)<=4000; }

  // Expanding radius: 0.5mi → 1mi → 2mi → 3mi, stop when ≥10 per active group
  var radii = [0.5, 1.0, 2.0, 3.0];
  var searchRadius = 0.5;
  var filtered = [];
  for(var ri=0; ri<radii.length; ri++){
    searchRadius = radii[ri];
    var all = searchRentalCompsInRadius(l.lat, l.lng, searchRadius);
    filtered = all.filter(function(c){ return c.dist <= searchRadius + 0.05 && passFilter(c); });
    // Check per-group coverage: stop when every active group has ≥10
    var groupCounts = {};
    filtered.forEach(function(c){ var g=RENTAL_PT_TO_GROUP[c.pt]; if(g) groupCounts[g]=(groupCounts[g]||0)+1; });
    var activeGroups = Object.keys(groupCounts);
    var allFull = activeGroups.length > 0 && activeGroups.every(function(g){ return groupCounts[g] >= RENTAL_GROUP_CAP; });
    if(allFull) break;
  }

  // Score each comp
  var maxR = searchRadius;
  filtered.forEach(function(c){
    c.matchScore = rentalMatchScore(c, maxR);
    c.isUsed = true; // all filtered comps are "used" in the new model
  });

  // Group by property type
  var groups = {};
  RENTAL_GROUP_ORDER.forEach(function(g){ groups[g] = []; });
  filtered.forEach(function(c){
    var g = RENTAL_PT_TO_GROUP[c.pt];
    if(g) groups[g].push(c);
  });

  // Sort each group by matchScore desc, cap at 10
  var totalCount = filtered.length;
  RENTAL_GROUP_ORDER.forEach(function(g){
    groups[g].sort(function(a,b){ return b.matchScore - a.matchScore; });
    groups[g] = groups[g].slice(0, RENTAL_GROUP_CAP);
  });

  // Flat allComps for map markers (capped set)
  var allComps = [];
  RENTAL_GROUP_ORDER.forEach(function(g){ allComps = allComps.concat(groups[g]); });

  // Summary stats
  var rentPsfs = allComps.filter(function(c){return c.sqft>0;}).map(function(c){return c.rent/c.sqft;});
  rentPsfs.sort(function(a,b){return a-b;});
  var medianRentPsf = rentPsfs.length ? rentPsfs[Math.floor(rentPsfs.length/2)] : 0;
  var p75RentPsf = rentPsfs.length ? rentPsfs[Math.floor(rentPsfs.length*0.75)] : 0;
  var primaryCount = (groups.townhome||[]).length + (groups.condo||[]).length;
  var supportingCount = (groups.sfr||[]).length + (groups.mf||[]).length;

  return {
    groups: groups,
    allComps: allComps,
    fullPool: filtered,
    radius: searchRadius,
    totalCount: totalCount,
    method: l.rentMethod || '',
    summary: {
      medianRentPsf: Math.round(medianRentPsf * 100) / 100,
      p75RentPsf: Math.round(p75RentPsf * 100) / 100,
      primaryCount: primaryCount,
      supportingCount: supportingCount
    }
  };
}

function formatRentalDate(dt){
  if(!dt) return '\u2014';
  var parts = dt.split('-');
  if(parts.length < 3) return dt;
  var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var m = parseInt(parts[1], 10) - 1;
  return (months[m]||parts[1]) + ' ' + parseInt(parts[2], 10);
}

function scoreColor(s){
  if(s >= SCORE_GOOD) return 'var(--green)';
  if(s >= SCORE_OK) return 'var(--yellow)';
  return 'var(--text-dim)';
}

function rentalCompRow(c, group){
  var rentPsf = (c.sqft && c.sqft > 0) ? (c.rent / c.sqft).toFixed(2) : '\u2014';
  var sc = c.matchScore || 0;
  return '<tr style="cursor:pointer" onclick="map.flyTo(['+c.lat+','+c.lng+'],17)" onmouseenter="highlightCompPin('+c.lat+','+c.lng+')" onmouseleave="unhighlightCompPin()">'
    +'<td style="white-space:nowrap;max-width:180px;overflow:hidden;text-overflow:ellipsis"><a class="redfin-link" href="'+redfinLink(c.addr)+'" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="View on Redfin">'+(c.addr||'\u2014')+' &#8599;</a></td>'
    +'<td>$'+c.rent.toLocaleString()+'</td>'
    +'<td>'+(rentPsf==='\u2014'?'\u2014':'$'+rentPsf)+'</td>'
    +'<td>'+(c.bd||'\u2014')+'</td>'
    +'<td>'+(c.ba||'\u2014')+'</td>'
    +'<td>'+(c.sqft?c.sqft.toLocaleString():'\u2014')+'</td>'
    +'<td>'+formatRentalDate(c.dt)+'</td>'
    +'<td>'+c.dist.toFixed(2)+'mi</td>'
    +'<td><span style="display:inline-block;min-width:28px;text-align:center;padding:1px 4px;border-radius:4px;font-size:10px;font-weight:700;background:'+scoreColor(sc)+';color:#fff">'+sc+'</span></td>'
    +'</tr>';
}

function rentalGroupAvgs(comps){
  if(!comps.length) return {avgRent:0, avgPsf:0, avgSqft:0};
  var rents=[], psfs=[], sqfts=[];
  comps.forEach(function(c){
    rents.push(c.rent);
    if(c.sqft > 0){ psfs.push(c.rent / c.sqft); sqfts.push(c.sqft); }
  });
  return {
    avgRent: rents.length ? Math.round(rents.reduce(function(a,b){return a+b;},0)/rents.length) : 0,
    avgPsf: psfs.length ? Math.round(psfs.reduce(function(a,b){return a+b;},0)/psfs.length*100)/100 : 0,
    avgSqft: sqfts.length ? Math.round(sqfts.reduce(function(a,b){return a+b;},0)/sqfts.length) : 0
  };
}

function rentalGroupTheadRow(group){
  return '<tr>'
    +'<th data-sort="addr" onclick="sortRentalCompsTable(\'addr\',\''+group+'\')" style="cursor:pointer">Address<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="rent" onclick="sortRentalCompsTable(\'rent\',\''+group+'\')" style="cursor:pointer">Rent<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="rentPsf" onclick="sortRentalCompsTable(\'rentPsf\',\''+group+'\')" style="cursor:pointer">$/SF<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="bd" onclick="sortRentalCompsTable(\'bd\',\''+group+'\')" style="cursor:pointer">Beds<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="ba" onclick="sortRentalCompsTable(\'ba\',\''+group+'\')" style="cursor:pointer">Baths<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="sqft" onclick="sortRentalCompsTable(\'sqft\',\''+group+'\')" style="cursor:pointer">SqFt<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="dt" onclick="sortRentalCompsTable(\'dt\',\''+group+'\')" style="cursor:pointer">Date<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="dist" onclick="sortRentalCompsTable(\'dist\',\''+group+'\')" style="cursor:pointer">Dist<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="matchScore" onclick="sortRentalCompsTable(\'matchScore\',\''+group+'\')" style="cursor:pointer">Score<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
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
  var groups = result.groups;
  var radius = result.radius;
  var summary = result.summary;
  var totalShown = result.allComps.length;

  // Est rent from listing
  var estRent = l.estRentMonth || 0;
  var estPsf = l.rentPsf || 0;

  document.getElementById('tableWrap').style.display='none';
  document.getElementById('mobileCards').style.display='none';
  document.getElementById('pipelineHeader').style.display='none';

  var estLine = estRent > 0
    ? 'Est. Rent: $'+estRent.toLocaleString()+'/mo ($'+estPsf.toFixed(2)+'/SF) &mdash; based on '+totalShown+' comps within '+radius.toFixed(1)+'mi'
    : totalShown+' comps within '+radius.toFixed(1)+'mi';

  var rentalHdr = document.getElementById('rentalCompsHeader');
  rentalHdr.innerHTML = '<button onclick="hideRentalCompsTable()" style="background:none;border:1px solid var(--border);color:var(--text);padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px;white-space:nowrap">&larr; Back to Pipeline</button>'
    +'<div style="flex:1;min-width:0">'
    +'<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">RENTAL COMPS &mdash; '+l.address+'</div>'
    +'<div style="font-size:11px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+estLine+'</div>'
    +'</div>'
    +'<button onclick="exportRentalCompsCsv()" style="background:none;border:1px solid var(--border);color:var(--text-dim);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;white-space:nowrap" title="Export all rental comps to CSV">&#x2913; CSV</button>'
    +'<button class="listings-panel-close" onclick="hideRentalCompsTable()">x</button>';
  rentalHdr.style.display='';

  var wrap = document.getElementById('rentalCompsTableWrap');
  if(!wrap){
    wrap = document.createElement('div');
    wrap.id = 'rentalCompsTableWrap';
    wrap.className = 'listings-table-wrap';
    var panel = document.getElementById('listingsPanel');
    panel.insertBefore(wrap, document.getElementById('tableWrap'));
  }
  wrap.style.display = '';

  // Build grouped sections
  var html = '';
  RENTAL_GROUP_ORDER.forEach(function(g){
    var comps = groups[g] || [];
    if(!comps.length) return;
    var label = RENTAL_GROUP_LABELS[g] || g;
    var avgs = rentalGroupAvgs(comps);
    var avgLine = avgs.avgRent ? 'Avg: $'+avgs.avgRent.toLocaleString()+'/mo &bull; $'+avgs.avgPsf.toFixed(2)+'/SF &bull; '+avgs.avgSqft.toLocaleString()+' SF' : '';
    html += '<div class="rental-group-section" data-group="'+g+'" style="margin-bottom:8px">'
      +'<div class="rental-group-header" style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;background:var(--card-bg);border:1px solid var(--border);border-radius:6px 6px 0 0;cursor:pointer" onclick="toggleRentalGroup(\''+g+'\')">'
      +'<span style="font-size:12px;font-weight:700;color:var(--text)">'+label.toUpperCase()+' <span style="font-weight:400;color:var(--text-dim)">('+comps.length+')</span>'+(avgLine ? ' <span style="font-weight:400;font-size:11px;color:var(--text-dim);margin-left:8px">'+avgLine+'</span>' : '')+'</span>'
      +'<span class="rental-group-chevron" style="font-size:10px;color:var(--text-dim)">\u25BC</span>'
      +'</div>'
      +'<div class="rental-group-body">'
      +'<table class="listings-table" style="margin:0"><thead>'+rentalGroupTheadRow(g)+'</thead>'
      +'<tbody data-group="'+g+'">'+comps.map(function(c){return rentalCompRow(c,g);}).join('')+'</tbody></table>'
      +'</div></div>';
  });

  if(!html){
    html = '<div style="padding:20px;text-align:center;color:var(--text-dim)">No rental comps found within '+radius.toFixed(1)+'mi matching 2+ BR / 700\u20134,000 SF filters</div>';
  }

  wrap.innerHTML = html;
  wrap._groups = groups;
  wrap._listing = l;
  wrap._result = result;

  // Map markers — score-based sizing
  if(rentalCompsMapLayer){ map.removeLayer(rentalCompsMapLayer); }
  if(rentalCompsRadiusCircle){ map.removeLayer(rentalCompsRadiusCircle); }
  rentalCompsMapLayer = L.layerGroup();
  result.allComps.forEach(function(c){
    var sc = c.matchScore || 0;
    var r, fillOp, col;
    if(sc >= SCORE_GOOD){ r=7; fillOp=0.9; col='#3b82f6'; }
    else if(sc >= SCORE_OK){ r=5; fillOp=0.6; col='#3b82f6'; }
    else { r=4; fillOp=0.35; col='#94a3b8'; }
    L.circleMarker([c.lat,c.lng],{
      radius:r, color:'#ffffff', fillColor:col, fillOpacity:fillOp, weight:1,
      bubblingMouseEvents: false
    }).bindPopup(
      '<b>'+(c.addr||'\u2014')+'</b>'
      +'<br>$'+c.rent.toLocaleString()+'/mo &bull; <b>$'+((c.sqft&&c.sqft>0)?(c.rent/c.sqft).toFixed(2):'\u2014')+'/SF</b>'
      +'<br>'+(c.bd||'\u2014')+'bd/'+(c.ba||'\u2014')+'ba &bull; '+(c.sqft?c.sqft.toLocaleString()+' SF':'\u2014')
      +'<br>'+(RENTAL_PT_LABEL[c.pt]||'\u2014')+' &bull; '+formatRentalDate(c.dt)
      +'<br>'+c.dist.toFixed(2)+'mi &bull; Score: '+sc
      +'<br><a href="'+redfinLink(c.addr)+'" target="_blank" rel="noopener" style="color:#3b82f6;font-size:11px">View on Redfin &#8599;</a>'
    ).addTo(rentalCompsMapLayer);
  });
  rentalCompsRadiusCircle = L.circle([l.lat,l.lng],{
    radius: radius*METERS_PER_MILE, color:'#3b82f6', fillColor:'#3b82f6',
    fillOpacity:0.04, weight:1, dashArray:'6,4'
  });
  rentalCompsMapLayer.addTo(map);
  rentalCompsRadiusCircle.addTo(map);
  rentalCompsTableActive = true;
  // Zoom to show comp radius — deferred to avoid Leaflet animation/autoPan conflicts
  var rentalBounds = rentalCompsRadiusCircle.getBounds().pad(0.1);
  setTimeout(function(){ map.stop(); map.flyToBounds(rentalBounds, {duration:0.6, maxZoom:17}); }, 50);
}

export function sortRentalCompsTable(key, group){
  var wrap = document.getElementById('rentalCompsTableWrap');
  if(!wrap || !wrap._groups) return;
  var comps = wrap._groups[group];
  if(!comps || !comps.length) return;

  // Track sort state per group
  var stateKey = 'data-sort-'+group;
  var prev = wrap.getAttribute(stateKey+'-key');
  var prevDir = wrap.getAttribute(stateKey+'-dir');
  var dir = prev===key ? (prevDir==='asc' ? 'desc' : 'asc') : 'desc';
  wrap.setAttribute(stateKey+'-key', key);
  wrap.setAttribute(stateKey+'-dir', dir);

  var sorter = function(a,b){
    var va,vb;
    if(key==='rentPsf'){
      va=(a.sqft&&a.sqft>0)?a.rent/a.sqft:0;
      vb=(b.sqft&&b.sqft>0)?b.rent/b.sqft:0;
    } else {
      va=a[key]; vb=b[key];
    }
    if(typeof va==='string') return dir==='asc'?(va||'').localeCompare(vb||''):(vb||'').localeCompare(va||'');
    va=va||0;vb=vb||0;
    return dir==='asc'?va-vb:vb-va;
  };
  comps.sort(sorter);

  var tbody = wrap.querySelector('tbody[data-group="'+group+'"]');
  if(tbody) tbody.innerHTML = comps.map(function(c){return rentalCompRow(c,group);}).join('');

  // Update arrows within this group's section
  var section = wrap.querySelector('.rental-group-section[data-group="'+group+'"]');
  if(section){
    section.querySelectorAll('th[data-sort]').forEach(function(th){
      var arrow = th.querySelector('.sort-arrow');
      var active = th.getAttribute('data-sort')===key;
      arrow.textContent = active ? (dir==='asc'?' \u25B2':' \u25BC') : ' \u25BD';
      arrow.style.opacity = active ? '1' : '0.4';
    });
  }
}

export function toggleRentalGroup(group){
  var wrap = document.getElementById('rentalCompsTableWrap');
  if(!wrap) return;
  var section = wrap.querySelector('.rental-group-section[data-group="'+group+'"]');
  if(!section) return;
  var body = section.querySelector('.rental-group-body');
  var chevron = section.querySelector('.rental-group-chevron');
  if(body.style.display === 'none'){
    body.style.display = '';
    if(chevron) chevron.textContent = '\u25BC';
  } else {
    body.style.display = 'none';
    if(chevron) chevron.textContent = '\u25B6';
  }
}

export function hideRentalCompsTable(){
  var map = _deps.getMap();
  document.getElementById('tableWrap').style.display='';
  document.getElementById('mobileCards').style.display='';
  document.getElementById('rentalCompsHeader').style.display='none';
  document.getElementById('pipelineHeader').style.display='';
  var wrap = document.getElementById('rentalCompsTableWrap');
  if(wrap) wrap.remove();
  if(rentalCompsMapLayer){ map.removeLayer(rentalCompsMapLayer); rentalCompsMapLayer=null; }
  if(rentalCompsRadiusCircle){ map.removeLayer(rentalCompsRadiusCircle); rentalCompsRadiusCircle=null; }
  rentalCompsTableActive = false;
}

// ── Hover highlight (pulse pin on table row hover) ──
var _pulseTimer = null;
var _pulseMarker = null;
var _pulseOrig = null;

export function highlightCompPin(lat, lng){
  unhighlightCompPin();
  var layer = compsMapLayer || rentalCompsMapLayer;
  if(!layer) return;
  layer.eachLayer(function(m){
    if(!m.getLatLng) return;
    var ll = m.getLatLng();
    if(Math.abs(ll.lat-lat)<0.00001 && Math.abs(ll.lng-lng)<0.00001){
      _pulseMarker = m;
      _pulseOrig = {radius:m.getRadius(), color:m.options.color, weight:m.options.weight, fillOpacity:m.options.fillOpacity};
      var big = true;
      m.setRadius(_pulseOrig.radius+6);
      m.setStyle({color:'#fbbf24', weight:3});
      _pulseTimer = setInterval(function(){
        m.setRadius(big ? _pulseOrig.radius+3 : _pulseOrig.radius+6);
        m.setStyle({fillOpacity: big ? 0.4 : _pulseOrig.fillOpacity});
        big = !big;
      }, 400);
    }
  });
}

export function unhighlightCompPin(){
  if(_pulseTimer){ clearInterval(_pulseTimer); _pulseTimer=null; }
  if(_pulseMarker && _pulseOrig){
    _pulseMarker.setRadius(_pulseOrig.radius);
    _pulseMarker.setStyle({color:_pulseOrig.color, weight:_pulseOrig.weight, fillOpacity:_pulseOrig.fillOpacity});
    _pulseMarker=null; _pulseOrig=null;
  }
}

// ── CSV Export ──

function csvEscape(v){
  if(v==null) return '';
  var s = String(v);
  if(s.indexOf(',')!==-1 || s.indexOf('"')!==-1 || s.indexOf('\n')!==-1) return '"'+s.replace(/"/g,'""')+'"';
  return s;
}

var PT_LABEL = {1:'SFR',2:'Condo',3:'Townhome',4:'Multi-Family (2-4)',5:'Multi-Family (5+)'};

function downloadCsv(filename, csvContent){
  var blob = new Blob([csvContent], {type:'text/csv;charset=utf-8;'});
  var link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function exportSaleCompsCsv(){
  var wrap = document.getElementById('compsTableWrap');
  if(!wrap || !wrap._result || !wrap._listing) return;
  var result = wrap._result;
  var l = wrap._listing;
  // Full uncapped pool: used + non-outlier ref
  var pool = result.used.concat(result.ref.filter(function(c){return !c.isOutlier;}));
  pool.sort(function(a,b){return a.dist-b.dist;});

  var rows = [['Type','Address','Sale Price','$/SF','SqFt','Beds','Baths','Zone','Yr Built','Tier','Sale Date','Distance (mi)','Used in Model'].join(',')];
  pool.forEach(function(c){
    rows.push([
      csvEscape(PT_LABEL[c.pt]||''),
      csvEscape(c.address),
      c.price,
      c.ppsf,
      c.sqft,
      c.bd,
      c.ba,
      csvEscape(c.zone),
      c.yb,
      c.t1s || (c.t===1?'T1':'T2'),
      csvEscape(c.date),
      c.dist?c.dist.toFixed(2):'',
      c.isUsed?'Yes':'No'
    ].join(','));
  });

  var addr = (l.address||'export').replace(/[^a-zA-Z0-9]/g,'_').substring(0,40);
  downloadCsv('sale_comps_'+addr+'.csv', rows.join('\n'));
}

export function exportRentalCompsCsv(){
  var wrap = document.getElementById('rentalCompsTableWrap');
  if(!wrap || !wrap._result || !wrap._listing) return;
  var result = wrap._result;
  var l = wrap._listing;
  var pool = result.fullPool || result.allComps;
  pool.sort(function(a,b){return a.dist-b.dist;});

  var rows = [['Type','Address','Rent ($/mo)','$/SF','Beds','Baths','SqFt','Date','Distance (mi)','Match Score'].join(',')];
  pool.forEach(function(c){
    var psf = c.sqft>0 ? (c.rent/c.sqft).toFixed(2) : '';
    rows.push([
      csvEscape(PT_LABEL[c.pt]||''),
      csvEscape(c.addr),
      c.rent,
      psf,
      c.bd,
      c.ba,
      c.sqft,
      csvEscape(c.dt),
      c.dist?c.dist.toFixed(2):'',
      c.matchScore||''
    ].join(','));
  });

  var addr = (l.address||'export').replace(/[^a-zA-Z0-9]/g,'_').substring(0,40);
  downloadCsv('rental_comps_'+addr+'.csv', rows.join('\n'));
}

// ── State queries (for other modules) ──
export function isCompsTableActive(){ return compsTableActive; }
export function isRentalCompsTableActive(){ return rentalCompsTableActive; }

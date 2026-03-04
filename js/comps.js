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
var BTS_ALLOWED_PT = [1, 2, 3];  // SFR, Condo, Townhome — exclude MF for BTS exit comps
var PT_COLORS = {1:'#3b82f6', 2:'#a855f7', 3:'#22c55e'};
var PT_DEFAULT_COLOR = '#94a3b8';

// ── Sale comp state ──
var compsTableActive = false;
var compsMapLayer = null;
var compsRadiusCircle = null;
var rentalCompsTableActive = false;
var rentalCompsMapLayer = null;
var rentalCompsRadiusCircle = null;

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
  } else if(l.clusterT1psf){
    source='newcon'; searchRadius=2; targetCount=0;
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
    var ptAllowed = BTS_ALLOWED_PT.indexOf(c.pt) !== -1;
    if(isUsed && !c.isOutlier && ptAllowed) used.push(c);
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
    +'<td style="color:'+(PT_COLORS[c.pt]||PT_DEFAULT_COLOR)+';font-weight:600">'+(PT_LABEL[c.pt]||ZONE_TYPE_MAP[c.zone]||c.zone||'\u2014')+'</td>'
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
  document.getElementById('pipelineHeader').style.display='none';
  var compsHdr = document.getElementById('compsHeader');
  compsHdr.innerHTML = '<button onclick="hideCompsTable()" style="background:none;border:1px solid var(--border);color:var(--text);padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px;white-space:nowrap">&larr; Back to Pipeline</button>'
    +'<div style="flex:1;min-width:0">'
    +'<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">BTS COMPS &mdash; '+l.address+'</div>'
    +'<div style="font-size:11px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+sourceLabel+' &bull; '+used.length+' used / '+(used.length+ref.length)+' nearby within '+radius.toFixed(1)+'mi <span style="margin-left:8px;font-size:10px"><span style="color:#3b82f6">&#9679;</span> SFR <span style="color:#a855f7">&#9679;</span> Condo <span style="color:#22c55e">&#9679;</span> TH</span></div>'
    +'</div>'
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

  var thead = '<table class="listings-table"><thead><tr>'
    +'<th style="width:30px">Used</th>'
    +'<th data-sort="address" onclick="sortCompsTable(\'address\')" style="cursor:pointer">Address<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="price" onclick="sortCompsTable(\'price\')" style="cursor:pointer">Sale Price<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="ppsf" onclick="sortCompsTable(\'ppsf\')" style="cursor:pointer">$/SF<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="sqft" onclick="sortCompsTable(\'sqft\')" style="cursor:pointer">SqFt<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th>Bd/Ba</th>'
    +'<th>Type</th>'
    +'<th data-sort="zone" onclick="sortCompsTable(\'zone\')" style="cursor:pointer">Zone<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="yb" onclick="sortCompsTable(\'yb\')" style="cursor:pointer">Yr Built<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="t" onclick="sortCompsTable(\'t\')" style="cursor:pointer">Tier<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="date" onclick="sortCompsTable(\'date\')" style="cursor:pointer">Sale Date<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
    +'<th data-sort="dist" onclick="sortCompsTable(\'dist\')" style="cursor:pointer">Dist<span class="sort-arrow" style="opacity:0.4"> \u25BD</span></th>'
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
    var ptColor = PT_COLORS[c.pt] || PT_DEFAULT_COLOR;
    L.circleMarker([c.lat,c.lng],{
      radius:7, color:'#ffffff', fillColor:ptColor, fillOpacity:0.9, weight:2
    }).bindPopup('<b>'+(c.address||'\u2014')+'</b><br>$'+c.price.toLocaleString()+' &bull; $'+c.ppsf+'/sf &bull; '+c.sqft+'sf<br>'+(c.date||'\u2014')+' &bull; T'+(c.t||'?')+' &bull; '+c.zone+' &bull; '+(PT_LABEL[c.pt]||'?')).addTo(compsMapLayer);
  });
  ref.filter(function(c){return !c.isOutlier;}).forEach(function(c){
    var ptColor = PT_COLORS[c.pt] || PT_DEFAULT_COLOR;
    L.circleMarker([c.lat,c.lng],{
      radius:4, color:ptColor, fillColor:ptColor, fillOpacity:0.25, weight:1
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
  var prevDir = wrap.getAttribute('data-sort-dir');
  var dir = prev===key ? (prevDir==='asc' ? 'desc' : 'asc') : 'desc';
  wrap.setAttribute('data-sort-key', key);
  wrap.setAttribute('data-sort-dir', dir);
  var sorter = function(a,b){
    var va=a[key],vb=b[key];
    if(typeof va==='string') return dir==='asc'?(va||'').localeCompare(vb||''):(vb||'').localeCompare(va||'');
    va=va||0;vb=vb||0;
    return dir==='asc'?va-vb:vb-va;
  };
  wrap._used.sort(sorter);
  wrap._ref.sort(sorter);
  var dividerRow = wrap._ref.length ? '<tr><td colspan="12" style="text-align:center;padding:6px;color:var(--text-dim);font-size:11px;border-top:2px solid var(--border);border-bottom:1px solid var(--border)">&mdash; Additional comps for reference ('+wrap._ref.length+') &mdash;</td></tr>' : '';
  wrap.querySelector('tbody').innerHTML = wrap._used.map(function(c){return compRow(c);}).join('') + dividerRow + wrap._ref.filter(function(c){return !c.isOutlier;}).map(function(c){return compRow(c);}).join('');
  // Update header arrows
  wrap.querySelectorAll('th[data-sort]').forEach(function(th){
    var arrow = th.querySelector('.sort-arrow');
    var active = th.getAttribute('data-sort')===key;
    arrow.textContent = active ? (dir==='asc'?' \u25B2':' \u25BC') : ' \u25BD';
    arrow.style.opacity = active ? '1' : '0.4';
  });
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
  // Size proximity (15 pts): closer to 1750 SF = higher
  var sqft = c.sqft || 0;
  if(sqft > 0) score += Math.max(0, 15 * (1 - Math.abs(sqft - 1750) / 1750));
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
  if(s >= 80) return 'var(--green)';
  if(s >= 50) return 'var(--yellow)';
  return 'var(--text-dim)';
}

function rentalCompRow(c, group){
  var rentPsf = (c.sqft && c.sqft > 0) ? (c.rent / c.sqft).toFixed(2) : '\u2014';
  var sc = c.matchScore || 0;
  return '<tr style="cursor:pointer" onclick="map.flyTo(['+c.lat+','+c.lng+'],17)">'
    +'<td style="white-space:nowrap;max-width:180px;overflow:hidden;text-overflow:ellipsis">'+(c.addr||'\u2014')+'</td>'
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
    if(sc >= 80){ r=7; fillOp=0.9; col='#3b82f6'; }
    else if(sc >= 50){ r=5; fillOp=0.6; col='#3b82f6'; }
    else { r=4; fillOp=0.35; col='#94a3b8'; }
    L.circleMarker([c.lat,c.lng],{
      radius:r, color:'#ffffff', fillColor:col, fillOpacity:fillOp, weight:1
    }).bindPopup('<b>'+(c.addr||'\u2014')+'</b><br>$'+c.rent.toLocaleString()+'/mo &bull; '+(c.bd||'?')+'bd/'+(c.ba||'?')+'ba &bull; '+(c.sqft?c.sqft.toLocaleString()+'sf':'\u2014')+'<br>Score: '+sc+' &bull; '+c.dist.toFixed(2)+'mi').addTo(rentalCompsMapLayer);
  });
  rentalCompsRadiusCircle = L.circle([l.lat,l.lng],{
    radius: radius*1609.34, color:'#3b82f6', fillColor:'#3b82f6',
    fillOpacity:0.04, weight:1, dashArray:'6,4'
  });
  rentalCompsMapLayer.addTo(map);
  rentalCompsRadiusCircle.addTo(map);
  rentalCompsTableActive = true;
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

// ── State queries (for other modules) ──
export function isCompsTableActive(){ return compsTableActive; }
export function isRentalCompsTableActive(){ return rentalCompsTableActive; }

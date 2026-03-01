// Polygon draw-to-filter module
// Dependencies injected via initDraw()

var _deps = {};
var drawPolygonLayer = null;
var drawPolygonGeoJSON = null;
var drawMode = false;
var drawVertices = [];
var drawPreviewLine = null;
var _polyEditHandler = null;

export function initDraw(deps) {
  _deps = deps;
}

export function isInsideDrawPolygon(lat, lng){
  if(!drawPolygonGeoJSON) return true;
  return turf.booleanPointInPolygon(turf.point([lng, lat]), drawPolygonGeoJSON);
}

export function getDrawPolygonGeoJSON(){ return drawPolygonGeoJSON; }

export function initDrawControl(){
  const container = L.DomUtil.create('div','draw-control');
  container.innerHTML = `
    <button class="draw-btn" id="drawBtn" title="Draw area to filter">&#9998;</button>
    <button class="draw-btn" id="drawDoneBtn" title="Close polygon" style="display:none;font-size:11px;font-weight:700">Done</button>
    <button class="draw-clear-btn" id="drawClearBtn" title="Clear drawn area">&#10005;</button>
    <button class="draw-btn" id="dataKeyBtn" title="Data Key — how metrics are calculated" style="font-size:14px;font-weight:700;margin-top:8px">?</button>
  `;
  document.getElementById('map').appendChild(container);
  L.DomEvent.disableClickPropagation(container);
  L.DomEvent.disableScrollPropagation(container);

  document.getElementById('drawBtn').addEventListener('click', toggleDrawMode);
  document.getElementById('drawDoneBtn').addEventListener('click', function(){ finishPolygon(); });
  document.getElementById('drawClearBtn').addEventListener('click', clearDrawPolygon);
  document.getElementById('dataKeyBtn').addEventListener('click', function(){
    document.getElementById('dataKeyModal').classList.add('active');
  });
}

export function toggleDrawMode(){
  if(drawMode) stopDrawMode();
  else startDrawMode();
}

function startDrawMode(){
  var map = _deps.getMap();
  drawMode = true;
  drawVertices = [];
  document.getElementById('drawBtn').classList.add('active');
  document.getElementById('drawDoneBtn').style.display = 'none';
  map.getContainer().classList.add('draw-mode');
  map._drawClickHandler = onDrawClick;
  map._drawMoveHandler = onDrawMouseMove;
  map._drawDblClickHandler = onDrawDoubleClick;
  map._drawKeyHandler = onDrawKeyDown;
  map.on('click', map._drawClickHandler);
  map.on('mousemove', map._drawMoveHandler);
  map.on('dblclick', map._drawDblClickHandler);
  document.addEventListener('keydown', map._drawKeyHandler);
  map.doubleClickZoom.disable();
}

function stopDrawMode(){
  var map = _deps.getMap();
  drawMode = false;
  document.getElementById('drawBtn').classList.remove('active');
  document.getElementById('drawDoneBtn').style.display = 'none';
  map.getContainer().classList.remove('draw-mode');
  if(drawPreviewLine){ map.removeLayer(drawPreviewLine); drawPreviewLine = null; }
  if(map._drawClickHandler) map.off('click', map._drawClickHandler);
  if(map._drawMoveHandler) map.off('mousemove', map._drawMoveHandler);
  if(map._drawDblClickHandler) map.off('dblclick', map._drawDblClickHandler);
  if(map._drawKeyHandler) document.removeEventListener('keydown', map._drawKeyHandler);
  map.doubleClickZoom.enable();
}

function onDrawClick(e){
  var map = _deps.getMap();
  if(!drawMode) return;
  if(drawVertices.length >= 3){
    const first = map.latLngToContainerPoint(L.latLng(drawVertices[0]));
    const click = map.latLngToContainerPoint(e.latlng);
    if(first.distanceTo(click) < 20){
      finishPolygon();
      return;
    }
  }
  drawVertices.push([e.latlng.lat, e.latlng.lng]);
  updateDrawPreview();
  if(drawVertices.length >= 3){
    document.getElementById('drawDoneBtn').style.display = 'flex';
  }
}

function onDrawMouseMove(e){
  if(!drawMode || drawVertices.length === 0) return;
  updateDrawPreview(e.latlng);
}

function onDrawDoubleClick(e){
  if(!drawMode) return;
  L.DomEvent.stop(e);
  if(drawVertices.length > 2) drawVertices.pop();
  if(drawVertices.length > 2) drawVertices.pop();
  if(drawVertices.length >= 3) finishPolygon();
}

function onDrawKeyDown(e){
  if(e.key === 'Escape') stopDrawMode();
  if(e.key === 'Enter' && drawVertices.length >= 3) finishPolygon();
}

function updateDrawPreview(mouseLatLng){
  var map = _deps.getMap();
  if(drawPreviewLine){ map.removeLayer(drawPreviewLine); drawPreviewLine = null; }
  if(drawVertices.length === 0) return;
  const pts = drawVertices.map(v => L.latLng(v[0], v[1]));
  if(mouseLatLng) pts.push(mouseLatLng);
  if(pts.length >= 2) pts.push(pts[0]);
  drawPreviewLine = L.polyline(pts, {color:'#2563eb',weight:2,dashArray:'6,6',fillOpacity:0}).addTo(map);
}

function finishPolygon(){
  var map = _deps.getMap();
  const verts = drawVertices.slice();
  stopDrawMode();
  if(verts.length < 3) return;
  disablePolygonEdit();
  if(drawPolygonLayer){ map.removeLayer(drawPolygonLayer); }
  drawPolygonLayer = L.polygon(verts, {
    color:'#2563eb', weight:2, fillColor:'#2563eb', fillOpacity:0.1
  }).addTo(map);
  syncPolygonGeoJSON();
  drawVertices = [];
  enablePolygonEdit();
  document.getElementById('drawClearBtn').classList.add('visible');
  _deps.applyFilters();
}

function syncPolygonGeoJSON(){
  if(!drawPolygonLayer) return;
  const latlngs = drawPolygonLayer.getLatLngs()[0];
  const coords = latlngs.map(ll => [ll.lng, ll.lat]);
  coords.push(coords[0]);
  drawPolygonGeoJSON = turf.polygon([coords]);
}

function enablePolygonEdit(){
  var map = _deps.getMap();
  if(!drawPolygonLayer) return;
  if(drawPolygonLayer.editing){
    drawPolygonLayer.editing.enable();
    _polyEditHandler = function(){ syncPolygonGeoJSON(); _deps.applyFilters(); };
    drawPolygonLayer.on('edit', _polyEditHandler);
    map.on('draw:editvertex', _polyEditHandler);
  }
}

function disablePolygonEdit(){
  var map = _deps.getMap();
  if(drawPolygonLayer && drawPolygonLayer.editing){
    drawPolygonLayer.editing.disable();
    if(_polyEditHandler){
      drawPolygonLayer.off('edit', _polyEditHandler);
      map.off('draw:editvertex', _polyEditHandler);
    }
  }
  _polyEditHandler = null;
}

export function clearDrawPolygon(){
  var map = _deps.getMap();
  disablePolygonEdit();
  if(drawPolygonLayer){ map.removeLayer(drawPolygonLayer); drawPolygonLayer = null; }
  drawPolygonGeoJSON = null;
  drawVertices = [];
  document.getElementById('drawClearBtn').classList.remove('visible');
  document.getElementById('drawBtn').classList.remove('active');
  document.getElementById('drawDoneBtn').style.display = 'none';
  _deps.applyFilters();
}

export function applyPolygonOpacity(){
  if(!drawPolygonGeoJSON) return;
  _deps.getOffMarketLayer().eachLayer(function(marker){
    if(marker.getLatLng){
      const ll = marker.getLatLng();
      const inside = isInsideDrawPolygon(ll.lat, ll.lng);
      marker.setStyle({opacity: inside ? 1 : 0.2, fillOpacity: inside ? 0.85 : 0.1});
    }
  });
  _deps.getBtrLayer().eachLayer(function(marker){
    if(marker.getLatLng){
      const ll = marker.getLatLng();
      const inside = isInsideDrawPolygon(ll.lat, ll.lng);
      marker.setStyle({opacity: inside ? 1 : 0.2, fillOpacity: inside ? 0.85 : 0.1});
    }
  });
  Object.values(_deps.getMarkerLayers()).forEach(function(layer){
    layer.eachLayer(function(marker){
      if(marker.getLatLng){
        const ll = marker.getLatLng();
        const inside = isInsideDrawPolygon(ll.lat, ll.lng);
        marker.setStyle({opacity: inside ? 1 : 0.15, fillOpacity: inside ? 0.5 : 0.05});
      }
    });
  });
}

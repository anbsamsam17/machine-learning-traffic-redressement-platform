"""Build carte v2 :
  - 2025_light reduit a 9 cols (drop FUNC_CLASS, length_m, PLr, n_merged, RAMP, ROUNDABOUT)
  - cast int sur TVr/min/max + DPL/min/max
  - + capteurs TV (bleus) + PL (rouges) toggleables
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import mapping

ROOT = Path(__file__).resolve().parent
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
LIGHT_SRC = DATA_ROOT / "Travaux_donnees_Lyon" / "Livrables" / "2025_light.geojson"
TV_SRC = DATA_ROOT / "Travaux_donnees_Lyon" / "DataApprentissage" / "BCFCDREF_AllYears_TV.parquet"
PL_SRC = DATA_ROOT / "Travaux_donnees_Lyon" / "DataApprentissage" / "BCFCDREF_AllYears_PL_enriched.geojson"

OUT_LIGHT = ROOT / "2025_light.min.geojson"
OUT_TV    = ROOT / "sensors_tv.min.geojson"
OUT_PL    = ROOT / "sensors_pl.min.geojson"
OUT_HTML  = ROOT / "index.html"

KEEP_COLS = ["agregId", "TVr", "TVrmin", "TVrmax", "DPL", "DPLmin", "DPLmax", "PL", "FC"]
INT_COLS  = ["TVr", "TVrmin", "TVrmax", "DPL", "DPLmin", "DPLmax", "PL", "FC"]

PRECISION = 5  # decimals on lon/lat


def round_coords(coords, n=PRECISION):
    return [[round(x, n), round(y, n)] for x, y in coords]


def gdf_to_minified_geojson(gdf, prop_keeper):
    """Return a python dict (FeatureCollection) with rounded coords + filtered props."""
    feats = []
    for geom, props in zip(gdf.geometry, gdf.drop(columns="geometry").to_dict("records")):
        if geom is None or geom.is_empty:
            continue
        gj = mapping(geom)
        if gj["type"] == "LineString":
            gj["coordinates"] = round_coords(gj["coordinates"])
        elif gj["type"] == "Point":
            x, y = gj["coordinates"][:2]
            gj["coordinates"] = [round(x, PRECISION), round(y, PRECISION)]
        clean_props = prop_keeper(props)
        feats.append({"type": "Feature", "geometry": gj, "properties": clean_props})
    return {"type": "FeatureCollection", "features": feats}


# ---------------------------------------------------------------------------
def build_light():
    t0 = time.time()
    print("[1/4] Loading 2025_light.geojson ...")
    gdf = gpd.read_file(LIGHT_SRC, engine="pyogrio")
    print(f"  {len(gdf):,} features, cols={list(gdf.columns)[:6]}...")

    # Keep only what we need
    keep = [c for c in KEEP_COLS if c in gdf.columns] + ["geometry"]
    gdf = gdf[keep].copy()

    # Rounding rules (same as apps/api/app/routers/carte.py final stage)
    #   TVr / TVrmin / TVrmax  -> conditional 10/100 (10 if < 10 000, else 100)
    #   DPL / DPLmin / DPLmax  -> always 10
    #   PL                     -> always 10
    #   TVrmax == 0            -> 10  (max dégénéré = 0 interdit)
    #   DPLmax == 0            -> 10  (idem)
    for col in ("TVr", "TVrmin", "TVrmax"):
        if col in gdf.columns:
            s = pd.to_numeric(gdf[col], errors="coerce").replace([np.inf, -np.inf], 0).fillna(0)
            gdf[col] = np.where(
                s < 10_000,
                np.round(s / 10) * 10,
                np.round(s / 100) * 100,
            ).astype("int32")
    for col in ("DPL", "DPLmin", "DPLmax", "PL"):
        if col in gdf.columns:
            s = pd.to_numeric(gdf[col], errors="coerce").replace([np.inf, -np.inf], 0).fillna(0)
            gdf[col] = (np.round(s / 10) * 10).astype("int32")
    # FC : just int
    if "FC" in gdf.columns:
        gdf["FC"] = pd.to_numeric(gdf["FC"], errors="coerce").fillna(0).astype("int32")
    # max-floor
    for col in ("TVrmax", "DPLmax"):
        if col in gdf.columns:
            gdf.loc[gdf[col] == 0, col] = 10

    def keep_props(p):
        out = {}
        for k in KEEP_COLS:
            if k not in p:
                continue
            v = p[k]
            if v is None or (isinstance(v, float) and (v != v)):
                continue
            out[k] = v
        return out

    fc = gdf_to_minified_geojson(gdf, keep_props)
    OUT_LIGHT.write_text(json.dumps(fc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    sz = OUT_LIGHT.stat().st_size / 1024 / 1024
    print(f"  -> {OUT_LIGHT.name} {sz:.2f} MB ({time.time()-t0:.1f}s)")
    return fc


# ---------------------------------------------------------------------------
def build_sensors_tv():
    t0 = time.time()
    print("[2/4] Loading TV sensors parquet ...")
    df = pd.read_parquet(TV_SRC)
    # geometry stored as WKB bytes -> use geopandas
    gdf = gpd.GeoDataFrame(df, geometry=gpd.GeoSeries.from_wkb(df["geometry"]), crs="EPSG:4326")
    print(f"  {len(gdf):,} sensors")

    # Aggregate per NO_DU_POSTE (one point per sensor) — keep most recent year
    gdf["annee"] = pd.to_numeric(gdf["annee"], errors="coerce")
    gdf = gdf.sort_values("annee").drop_duplicates(subset="NO_DU_POSTE", keep="last")
    print(f"  {len(gdf):,} unique sensors (latest year)")

    def keep_props(p):
        out = {
            "id": str(p.get("NO_DU_POSTE", "")),
            "addr": str(p.get("adresse compteur", "") or "")[:60],
            "year": int(p["annee"]) if pd.notna(p.get("annee")) else None,
            "tmjobc_tv": int(p["TMJOBCTV"]) if pd.notna(p.get("TMJOBCTV")) else None,
            "tmjofcd_tv": round(float(p["TMJOFCDTV"]), 1) if pd.notna(p.get("TMJOFCDTV")) else None,
            "txpen": round(float(p["TxPen"]), 3) if pd.notna(p.get("TxPen")) else None,
            "type": str(p.get("Type Compteur", "") or ""),
            "fc": int(p["functional_class"]) if pd.notna(p.get("functional_class")) else None,
        }
        return {k: v for k, v in out.items() if v is not None and v != ""}

    fc = gdf_to_minified_geojson(gdf[["NO_DU_POSTE","adresse compteur","annee","TMJOBCTV","TMJOFCDTV","TxPen","Type Compteur","functional_class","geometry"]], keep_props)
    OUT_TV.write_text(json.dumps(fc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    sz = OUT_TV.stat().st_size / 1024 / 1024
    print(f"  -> {OUT_TV.name} {sz:.3f} MB ({time.time()-t0:.1f}s)")
    return fc


# ---------------------------------------------------------------------------
def build_sensors_pl():
    t0 = time.time()
    print("[3/4] Loading PL sensors geojson ...")
    gdf = gpd.read_file(PL_SRC)
    print(f"  {len(gdf):,} sensors")

    gdf["annee"] = pd.to_numeric(gdf["annee"], errors="coerce")
    gdf = gdf.sort_values("annee").drop_duplicates(subset="NO_DU_POSTE", keep="last")
    print(f"  {len(gdf):,} unique sensors (latest year)")

    def keep_props(p):
        out = {
            "id": str(p.get("NO_DU_POSTE", "")),
            "addr": str(p.get("adresse compteur", "") or "")[:60],
            "year": int(p["annee"]) if pd.notna(p.get("annee")) else None,
            "tmjobc_pl": int(p["TMJOBCPL"]) if pd.notna(p.get("TMJOBCPL")) else None,
            "tmjofcd_pl": round(float(p["TMJOFCDPL"]), 1) if pd.notna(p.get("TMJOFCDPL")) else None,
            "txpen_pl": round(float(p["TxPenPL"]), 3) if pd.notna(p.get("TxPenPL")) else None,
            "type": str(p.get("Type Compteur", "") or ""),
            "fc": int(p["functional_class"]) if pd.notna(p.get("functional_class")) else None,
        }
        return {k: v for k, v in out.items() if v is not None and v != ""}

    fc = gdf_to_minified_geojson(gdf[["NO_DU_POSTE","adresse compteur","annee","TMJOBCPL","TMJOFCDPL","TxPenPL","Type Compteur","functional_class","geometry"]], keep_props)
    OUT_PL.write_text(json.dumps(fc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    sz = OUT_PL.stat().st_size / 1024 / 1024
    print(f"  -> {OUT_PL.name} {sz:.3f} MB ({time.time()-t0:.1f}s)")
    return fc


# ---------------------------------------------------------------------------
HTML_TMPL = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<title>Carte des volumes de trafic 2025 - Grand Lyon</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet"/>
<style>
  html, body {{ margin:0; height:100%; background:#0d1117; color:#e6edf3;
    font-family:'Inter','Segoe UI',Roboto,Arial,sans-serif; -webkit-font-smoothing:antialiased; }}
  #map {{ position:absolute; inset:0; }}
  #title {{ position:absolute; top:16px; left:50%; transform:translateX(-50%); z-index:3;
    padding:8px 18px; background:rgba(255,255,255,.92); color:#0f1424;
    font-size:15px; font-weight:600; border-radius:999px; box-shadow:0 4px 18px rgba(0,0,0,.25);
    pointer-events:none; user-select:none; }}
  #legend {{ position:absolute; top:16px; left:16px; z-index:2; width:300px;
    background:rgba(15,20,36,.94); border:1px solid #1f2740; border-radius:14px;
    padding:14px 16px; box-shadow:0 6px 28px rgba(0,0,0,.45); max-height:calc(100vh - 32px); overflow-y:auto; }}
  #legend h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.5px; color:#a0b0d8;
    margin:14px 0 8px; padding-bottom:4px; border-bottom:1px solid #2a3252; }}
  #legend h2:first-child {{ margin-top:0; }}
  #legend .sub {{ font-size:11px; color:#a0b0d8; font-style:italic; margin:-4px 0 10px; }}
  .mode-toggle {{ display:flex; gap:0; background:#0a0e1c; border:1px solid #2a3252; border-radius:8px; overflow:hidden; }}
  .mode-toggle button {{ flex:1; padding:8px 12px; background:transparent; border:0; color:#a0b0d8;
    font-size:12px; font-weight:600; cursor:pointer; transition:.2s; }}
  .mode-toggle button.active {{ background:#22d3ee; color:#0a0e1c; }}
  .mode-toggle button:hover:not(.active) {{ background:#1a2140; color:#fff; }}
  .legend-row {{ display:flex; align-items:center; padding:5px 0; cursor:pointer; user-select:none; transition:.15s; border-radius:4px; }}
  .legend-row:hover {{ background:rgba(255,255,255,.04); }}
  .legend-row.off {{ opacity:.35; }}
  .legend-row .sw {{ width:28px; height:12px; border-radius:2px; flex-shrink:0; margin-right:10px; }}
  .legend-row .lbl {{ font-size:12px; color:#e6edf3; }}
  .layer-toggle {{ display:flex; align-items:center; padding:8px 10px; background:#0a0e1c;
    border:1px solid #2a3252; border-radius:8px; margin-bottom:6px; cursor:pointer; transition:.15s; }}
  .layer-toggle:hover {{ background:#161c34; }}
  .layer-toggle input {{ margin-right:10px; accent-color:#22d3ee; }}
  .layer-toggle .dot {{ width:12px; height:12px; border-radius:50%; margin-right:8px; flex-shrink:0; }}
  .layer-toggle .lbl {{ font-size:12px; flex:1; }}
  .layer-toggle .count {{ font-size:10px; color:#a0b0d8; font-family:monospace; }}
  #reset {{ display:block; width:100%; margin-top:10px; padding:7px; background:#1a2140;
    color:#a0b0d8; border:1px solid #2a3252; border-radius:6px; cursor:pointer; font-size:11px; transition:.15s; }}
  #reset:hover {{ background:#22d3ee; color:#0a0e1c; }}
  #fit {{ position:absolute; bottom:24px; right:24px; z-index:2; padding:10px 16px;
    background:rgba(15,20,36,.92); color:#fff; border:1px solid #2a3252; border-radius:8px;
    cursor:pointer; font-size:12px; box-shadow:0 4px 18px rgba(0,0,0,.35); }}
  #fit:hover {{ background:#22d3ee; color:#0a0e1c; }}
  .maplibregl-popup-content {{ background:#0f1424!important; color:#e6edf3!important;
    border:1px solid #2a3252; border-radius:10px; padding:14px 16px; min-width:260px; font-size:12px; }}
  .maplibregl-popup-close-button {{ color:#a0b0d8!important; font-size:20px!important; padding:4px 8px!important; }}
  .maplibregl-popup-tip {{ display:none; }}
  .pop-h {{ font-weight:700; font-size:13px; color:#22d3ee; margin-bottom:8px; word-break:break-all; }}
  .pop-r {{ display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid #1f2740; }}
  .pop-r:last-of-type {{ border-bottom:0; }}
  .pop-r .v {{ font-family:monospace; color:#fff; font-weight:600; }}
  .pop-btn {{ margin-top:10px; padding:5px 10px; background:#22d3ee; color:#0a0e1c;
    border:0; border-radius:5px; cursor:pointer; font-size:11px; font-weight:600; }}
  #toast {{ position:fixed; bottom:24px; left:50%; transform:translateX(-50%); z-index:10;
    background:#22d3ee; color:#0a0e1c; padding:10px 20px; border-radius:6px; font-size:12px;
    font-weight:600; opacity:0; transition:opacity .2s; pointer-events:none; }}
  #toast.show {{ opacity:1; }}
</style>
</head>
<body>
<div id="map"></div>
<div id="title">Carte des volumes de trafic 2025 - Grand Lyon</div>
<div id="legend">
  <h2>Donnees a afficher</h2>
  <div class="mode-toggle">
    <button id="btn-tvr" class="active">TVr (TV)</button>
    <button id="btn-dpl">DPL (PL)</button>
  </div>
  <p class="sub" id="mode-label">veh/jour, par sens</p>

  <h2>Legende</h2>
  <div id="classes"></div>
  <button id="reset">Reinitialiser les filtres</button>

  <h2>Capteurs (mesures terrain)</h2>
  <div class="layer-toggle" onclick="toggleLayer('sensors-tv', this)">
    <input type="checkbox" id="cb-tv">
    <span class="dot" style="background:#1976d2"></span>
    <span class="lbl">Capteurs TV</span>
    <span class="count" id="ct-tv"></span>
  </div>
  <div class="layer-toggle" onclick="toggleLayer('sensors-pl', this)">
    <input type="checkbox" id="cb-pl">
    <span class="dot" style="background:#e53935"></span>
    <span class="lbl">Capteurs PL</span>
    <span class="count" id="ct-pl"></span>
  </div>
</div>
<button id="fit">Centrer sur les donnees</button>
<div id="toast">Copie</div>

<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script>
const FLOWS  = __FLOWS__;
const TV_S   = __TV__;
const PL_S   = __PL__;

const COLORS = ['#fff4a3','#fdd97c','#fbb444','#f08a3a','#dd5a35','#a32c1e','#7a1f0f'];
const WIDTHS = [0.6, 0.9, 1.3, 1.8, 2.4, 3.2, 4.0];
const TVR_BREAKS = [500, 1000, 2000, 4000, 6000, 10000];
const DPL_BREAKS = [50, 100, 200, 400, 600, 1000];

const LBL_TVR = ['Inferieur a 500','Entre 500 et 1 000','Entre 1 000 et 2 000','Entre 2 000 et 4 000','Entre 4 000 et 6 000','Entre 6 000 et 10 000','Superieur a 10 000'];
const LBL_DPL = ['Inferieur a 50','Entre 50 et 100','Entre 100 et 200','Entre 200 et 400','Entre 400 et 600','Entre 600 et 1 000','Superieur a 1 000'];

let currentMode = 'TVr';
let breaks = TVR_BREAKS;
let labels = LBL_TVR;
let hiddenClasses = new Set();

// Read URL hash
const hashMatch = location.hash.match(/mode=(TVr|DPL)/);
if (hashMatch) currentMode = hashMatch[1];

function colorExpr(prop) {{
  const e = ['step', ['get', prop], COLORS[0]];
  const br = prop === 'TVr' ? TVR_BREAKS : DPL_BREAKS;
  for (let i = 0; i < br.length; i++) {{ e.push(br[i], COLORS[i+1]); }}
  return e;
}}
function widthExpr(prop) {{
  const e = ['step', ['get', prop], WIDTHS[0]];
  const br = prop === 'TVr' ? TVR_BREAKS : DPL_BREAKS;
  for (let i = 0; i < br.length; i++) {{ e.push(br[i], WIDTHS[i+1]); }}
  return ['interpolate', ['exponential', 1.2], ['zoom'], 9, ['*', e, 0.55], 13, e, 17, ['*', e, 1.8]];
}}
function filterExpr() {{
  if (hiddenClasses.size === 0) return null;
  const br = currentMode === 'TVr' ? TVR_BREAKS : DPL_BREAKS;
  const f = ['all'];
  for (const cls of hiddenClasses) {{
    const lo = cls === 0 ? -Infinity : br[cls-1];
    const hi = cls === 7 ? Infinity : br[cls];
    if (cls === 0) f.push(['>=', ['get', currentMode], hi]);
    else if (cls === 6) f.push(['<', ['get', currentMode], lo]);
    else f.push(['any', ['<', ['get', currentMode], lo], ['>=', ['get', currentMode], hi]]);
  }}
  return f;
}}

const map = new maplibregl.Map({{
  container: 'map',
  style: {{
    version: 8,
    sources: {{
      basemap: {{ type:'raster', tiles:['https://a.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png','https://b.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png','https://c.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png','https://d.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png'], tileSize:256, attribution:'(c) CartoDB (c) OpenStreetMap' }}
    }},
    layers: [{{ id:'basemap', type:'raster', source:'basemap' }}],
  }},
  center: [4.85, 45.75], zoom: 11,
}});
map.addControl(new maplibregl.NavigationControl({{ showCompass:false }}), 'top-right');

map.on('load', () => {{
  map.addSource('flows', {{ type:'geojson', data: FLOWS }});
  map.addLayer({{
    id: 'flow-lines', source: 'flows', type: 'line',
    layout: {{ 'line-cap':'round', 'line-join':'round' }},
    paint: {{
      'line-color': colorExpr(currentMode),
      'line-width': widthExpr(currentMode),
      'line-opacity': 0.78,
      'line-color-transition': {{ duration: 250 }},
      'line-width-transition': {{ duration: 250 }},
    }}
  }});

  map.addSource('sensors-tv', {{ type:'geojson', data: TV_S }});
  map.addLayer({{
    id: 'sensors-tv', source: 'sensors-tv', type: 'circle', layout: {{ visibility:'none' }},
    paint: {{ 'circle-radius':5, 'circle-color':'#1976d2', 'circle-stroke-color':'#fff', 'circle-stroke-width':1.2, 'circle-opacity':0.9 }}
  }});
  map.addSource('sensors-pl', {{ type:'geojson', data: PL_S }});
  map.addLayer({{
    id: 'sensors-pl', source: 'sensors-pl', type: 'circle', layout: {{ visibility:'none' }},
    paint: {{ 'circle-radius':5, 'circle-color':'#e53935', 'circle-stroke-color':'#fff', 'circle-stroke-width':1.2, 'circle-opacity':0.9 }}
  }});

  document.getElementById('ct-tv').textContent = TV_S.features.length;
  document.getElementById('ct-pl').textContent = PL_S.features.length;
  renderLegend();
  bindEvents();
}});

function renderLegend() {{
  const cont = document.getElementById('classes');
  cont.innerHTML = '';
  for (let i = 6; i >= 0; i--) {{
    const off = hiddenClasses.has(i);
    const row = document.createElement('div');
    row.className = 'legend-row' + (off ? ' off' : '');
    row.innerHTML = '<span class="sw" style="background:'+COLORS[i]+'"></span><span class="lbl">'+labels[i]+'</span>';
    row.onclick = () => {{ if (off) hiddenClasses.delete(i); else hiddenClasses.add(i); applyFilter(); renderLegend(); }};
    cont.appendChild(row);
  }}
  document.getElementById('mode-label').textContent = currentMode + ' veh/jour, par sens';
}}

function applyFilter() {{ map.setFilter('flow-lines', filterExpr()); }}

function setMode(m) {{
  currentMode = m; breaks = (m==='TVr'?TVR_BREAKS:DPL_BREAKS); labels = (m==='TVr'?LBL_TVR:LBL_DPL);
  document.getElementById('btn-tvr').classList.toggle('active', m==='TVr');
  document.getElementById('btn-dpl').classList.toggle('active', m==='DPL');
  map.setPaintProperty('flow-lines','line-color', colorExpr(m));
  map.setPaintProperty('flow-lines','line-width', widthExpr(m));
  applyFilter(); renderLegend();
  history.replaceState(null,'','#mode='+m);
}}

function toggleLayer(id, el) {{
  const cb = el.querySelector('input');
  cb.checked = !cb.checked;
  map.setLayoutProperty(id, 'visibility', cb.checked ? 'visible' : 'none');
}}

function nf(v) {{ return Number(v).toLocaleString('fr-FR'); }}
function showToast(msg) {{ const t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),1400); }}

function bindEvents() {{
  document.getElementById('btn-tvr').onclick = () => setMode('TVr');
  document.getElementById('btn-dpl').onclick = () => setMode('DPL');
  document.getElementById('reset').onclick = () => {{ hiddenClasses.clear(); applyFilter(); renderLegend(); }};
  document.getElementById('fit').onclick = () => {{
    const b = new maplibregl.LngLatBounds();
    for (const f of FLOWS.features) for (const c of f.geometry.coordinates) b.extend(c);
    map.fitBounds(b, {{ padding: 80, duration: 800 }});
  }};
  // Popup flows
  map.on('click', 'flow-lines', e => {{
    const p = e.features[0].properties;
    const html = '<div class="pop-h">' + (p.agregId||'?') + '</div>'
      + '<div class="pop-r"><span>TVr (TV)</span><span class="v">' + nf(p.TVr||0) + ' veh/j</span></div>'
      + '<div class="pop-r"><span>&nbsp; min - max</span><span class="v">' + nf(p.TVrmin||0) + ' - ' + nf(p.TVrmax||0) + '</span></div>'
      + '<div class="pop-r"><span>DPL (PL)</span><span class="v">' + nf(p.DPL||0) + ' veh/j</span></div>'
      + '<div class="pop-r"><span>&nbsp; min - max</span><span class="v">' + nf(p.DPLmin||0) + ' - ' + nf(p.DPLmax||0) + '</span></div>'
      + '<div class="pop-r"><span>PL absolu</span><span class="v">' + nf(p.PL||0) + '</span></div>'
      + '<div class="pop-r"><span>FC</span><span class="v">' + (p.FC||'?') + '</span></div>'
      + '<button class="pop-btn" onclick="navigator.clipboard.writeText(\'' + (p.agregId||'') + '\').then(()=>showToast(\'ID copie\'))">Copier l\'ID</button>';
    new maplibregl.Popup({{ maxWidth:'320px' }}).setLngLat(e.lngLat).setHTML(html).addTo(map);
  }});
  // Popup TV sensors
  map.on('click', 'sensors-tv', e => {{
    const p = e.features[0].properties;
    const html = '<div class="pop-h" style="color:#42a5f5">Capteur TV ' + (p.id||'') + '</div>'
      + '<div class="pop-r"><span>Adresse</span><span class="v">' + (p.addr||'?') + '</span></div>'
      + '<div class="pop-r"><span>Annee</span><span class="v">' + (p.year||'?') + '</span></div>'
      + '<div class="pop-r"><span>Type</span><span class="v">' + (p.type||'?') + '</span></div>'
      + '<div class="pop-r"><span>TMJOBC TV</span><span class="v">' + (p.tmjobc_tv!=null?nf(p.tmjobc_tv)+' veh/j':'?') + '</span></div>'
      + '<div class="pop-r"><span>TMJOFCD TV</span><span class="v">' + (p.tmjofcd_tv!=null?nf(p.tmjofcd_tv):'?') + '</span></div>'
      + '<div class="pop-r"><span>TxPen</span><span class="v">' + (p.txpen!=null?p.txpen:'?') + '</span></div>'
      + '<div class="pop-r"><span>FC</span><span class="v">' + (p.fc||'?') + '</span></div>';
    new maplibregl.Popup({{ maxWidth:'300px' }}).setLngLat(e.lngLat).setHTML(html).addTo(map);
  }});
  // Popup PL sensors
  map.on('click', 'sensors-pl', e => {{
    const p = e.features[0].properties;
    const html = '<div class="pop-h" style="color:#ef5350">Capteur PL ' + (p.id||'') + '</div>'
      + '<div class="pop-r"><span>Adresse</span><span class="v">' + (p.addr||'?') + '</span></div>'
      + '<div class="pop-r"><span>Annee</span><span class="v">' + (p.year||'?') + '</span></div>'
      + '<div class="pop-r"><span>Type</span><span class="v">' + (p.type||'?') + '</span></div>'
      + '<div class="pop-r"><span>TMJOBC PL</span><span class="v">' + (p.tmjobc_pl!=null?nf(p.tmjobc_pl)+' veh/j':'?') + '</span></div>'
      + '<div class="pop-r"><span>TMJOFCD PL</span><span class="v">' + (p.tmjofcd_pl!=null?nf(p.tmjofcd_pl):'?') + '</span></div>'
      + '<div class="pop-r"><span>TxPenPL</span><span class="v">' + (p.txpen_pl!=null?p.txpen_pl:'?') + '</span></div>'
      + '<div class="pop-r"><span>FC</span><span class="v">' + (p.fc||'?') + '</span></div>';
    new maplibregl.Popup({{ maxWidth:'300px' }}).setLngLat(e.lngLat).setHTML(html).addTo(map);
  }});
  // Cursor pointer on all interactive layers
  for (const lid of ['flow-lines','sensors-tv','sensors-pl']) {{
    map.on('mouseenter', lid, () => map.getCanvas().style.cursor = 'pointer');
    map.on('mouseleave', lid, () => map.getCanvas().style.cursor = '');
  }}
  // Boot mode from hash
  if (currentMode === 'DPL') setMode('DPL');
}}
</script>
</body>
</html>
"""


def build_html(flows_fc, tv_fc, pl_fc):
    print("[4/4] Building index.html ...")
    flows = json.dumps(flows_fc, separators=(",", ":"), ensure_ascii=False)
    tv = json.dumps(tv_fc, separators=(",", ":"), ensure_ascii=False)
    pl = json.dumps(pl_fc, separators=(",", ":"), ensure_ascii=False)
    # HTML_TMPL was authored with doubled braces ({{ / }}) for str.format()
    # style — but we use .replace() which does NOT unescape. Collapse them
    # back to single braces BEFORE injecting JSON (which has its own braces).
    html = HTML_TMPL.replace("{{", "{").replace("}}", "}")
    html = html.replace("__FLOWS__", flows).replace("__TV__", tv).replace("__PL__", pl)
    OUT_HTML.write_text(html, encoding="utf-8")
    sz = OUT_HTML.stat().st_size / 1024 / 1024
    print(f"  -> {OUT_HTML.name} {sz:.2f} MB")


def main():
    t0 = time.time()
    flows = build_light()
    tv = build_sensors_tv()
    pl = build_sensors_pl()
    build_html(flows, tv, pl)
    print(f"\nTotal: {time.time()-t0:.1f}s")
    print("\nResultats :")
    print(f"  {OUT_LIGHT.name}: {OUT_LIGHT.stat().st_size/1024/1024:.2f} MB")
    print(f"  {OUT_TV.name}:    {OUT_TV.stat().st_size/1024/1024:.3f} MB ({len(tv['features'])} capteurs)")
    print(f"  {OUT_PL.name}:    {OUT_PL.stat().st_size/1024/1024:.3f} MB ({len(pl['features'])} capteurs)")
    print(f"  {OUT_HTML.name}:  {OUT_HTML.stat().st_size/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

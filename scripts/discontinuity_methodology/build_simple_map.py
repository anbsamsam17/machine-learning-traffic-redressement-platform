"""Carte HTML simplifiee : noeuds de discontinuite uniquement.

Regle utilisateur :
  - discontinuite si max_flow <= 20 000 ET |delta| > 2 000 veh/j
  - discontinuite si max_flow >  20 000 ET |delta| > 4 000 veh/j
  - boundary nodes (in==0 ou out==0) exclus (bords reseau)

Sortie : un seul HTML standalone Leaflet, marqueurs colores + popup KPIs.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent
NODES_CSV = ROOT / "outputs" / "discontinuity_nodes_full.csv"
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
GEO_2025  = DATA_ROOT / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables" / "2025.geojson"
OUT_HTML  = ROOT / "outputs" / "discontinuity_map_simple.html"
OUT_CSV   = ROOT / "outputs" / "discontinuity_nodes_simple.csv"


def main() -> int:
    t0 = time.time()

    # 1) Load nodes
    nodes = pd.read_csv(NODES_CSV)
    n_total = len(nodes)

    # 2) Exclude boundary
    inner = nodes[~nodes["is_boundary"]].copy()
    n_inner = len(inner)

    # 3) Apply user rule
    inner["delta_abs"] = (inner["in_flow"] - inner["out_flow"]).abs()
    inner["threshold"] = inner["max_flow"].apply(lambda f: 4000.0 if f > 20000 else 2000.0)
    inner["is_discontinuous"] = inner["delta_abs"] > inner["threshold"]

    discont = inner[inner["is_discontinuous"]].copy()
    n_discont = len(discont)
    pct_discont = 100.0 * n_discont / n_inner if n_inner else 0.0

    # 4) Tier : orange ([1x, 2x[ threshold), rouge (>= 2x)
    discont["tier"] = (discont["delta_abs"] >= 2 * discont["threshold"]).map(
        {True: "red", False: "orange"}
    )

    # 5) Look up lat/lon for each node_id from 2025.geojson
    #    Use first/last geometry point of each edge's REF/NREF
    print(f"[1/3] Loading 2025.geojson to extract node coords...")
    edges = gpd.read_file(GEO_2025, columns=["REF_IN_ID", "NREF_IN_ID"])
    # Build node -> (lat, lon) map from geometry endpoints
    node_coords: dict[int, tuple[float, float]] = {}
    for ref, nref, geom in zip(edges["REF_IN_ID"], edges["NREF_IN_ID"], edges.geometry):
        coords = list(geom.coords)
        if coords:
            if ref not in node_coords:
                node_coords[ref] = (coords[0][1], coords[0][0])    # (lat, lon)
            if nref not in node_coords:
                node_coords[nref] = (coords[-1][1], coords[-1][0])

    discont["lat"] = discont["node_id"].map(lambda nid: node_coords.get(int(nid), (None, None))[0])
    discont["lon"] = discont["node_id"].map(lambda nid: node_coords.get(int(nid), (None, None))[1])
    missing_coord = discont[discont["lat"].isna()]
    if not missing_coord.empty:
        print(f"  Warning: {len(missing_coord)} nodes without coords (dropped)")
        discont = discont.dropna(subset=["lat", "lon"])

    # 6) CSV slim
    print(f"[2/3] Writing {OUT_CSV.name}...")
    discont_out = discont[[
        "node_id", "lat", "lon", "n_in", "n_out",
        "in_flow", "out_flow", "delta_abs", "threshold", "tier",
    ]].copy()
    discont_out.columns = [
        "node_id", "lat", "lon", "n_in", "n_out",
        "in_flow", "out_flow", "ecart", "seuil", "tier",
    ]
    discont_out.to_csv(OUT_CSV, index=False)

    # 7) Build HTML
    print(f"[3/3] Building HTML map...")
    # Convert to feature list (compact JSON)
    features = []
    for _, r in discont.iterrows():
        features.append({
            "id": int(r["node_id"]),
            "lat": round(float(r["lat"]), 6),
            "lon": round(float(r["lon"]), 6),
            "in":  int(r["in_flow"]),
            "out": int(r["out_flow"]),
            "d":   int(r["delta_abs"]),
            "t":   int(r["threshold"]),
            "ni":  int(r["n_in"]),
            "no":  int(r["n_out"]),
            "tier": r["tier"],
        })

    payload = json.dumps(features, ensure_ascii=False, separators=(",", ":"))

    n_red    = sum(1 for f in features if f["tier"] == "red")
    n_orange = sum(1 for f in features if f["tier"] == "orange")

    html = HTML_TMPL.format(
        n_total=n_total,
        n_inner=n_inner,
        n_discont=n_discont,
        pct=f"{pct_discont:.2f}",
        n_red=n_red,
        n_orange=n_orange,
        boundary=n_total - n_inner,
        nodes_json=payload,
    )

    OUT_HTML.write_text(html, encoding="utf-8")
    sz_mb = OUT_HTML.stat().st_size / 1024 / 1024
    print(f"\n  -> {OUT_HTML} ({sz_mb:.2f} MB)")
    print(f"\nStats:")
    print(f"  Total nodes        : {n_total:,}")
    print(f"  Boundary excluded  : {n_total - n_inner:,}")
    print(f"  Inner analyzed     : {n_inner:,}")
    print(f"  Discontinuous      : {n_discont:,} ({pct_discont:.2f}%)")
    print(f"  -> Orange (1x-2x)  : {n_orange:,}")
    print(f"  -> Red (>= 2x)     : {n_red:,}")
    print(f"\nDone in {time.time()-t0:.1f}s.")
    return 0


HTML_TMPL = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Discontinuites TVr - Lyon Metropole</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<style>
  html, body {{ height: 100%; margin: 0; font-family: -apple-system, "Segoe UI", Roboto, sans-serif; }}
  #wrap {{ display: flex; height: 100vh; }}
  #map {{ flex: 1; }}
  #side {{
    width: 320px; padding: 18px 20px; background: #0f1424; color: #e5ebff;
    overflow-y: auto; box-shadow: 2px 0 6px rgba(0,0,0,.25);
  }}
  #side h1 {{ font-size: 18px; margin: 0 0 12px; color: #fff; }}
  #side h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .5px;
              color: #a0b0d8; margin: 18px 0 8px; border-bottom: 1px solid #2a3252; padding-bottom: 4px; }}
  .stat {{ background: #1a2140; padding: 12px; border-radius: 8px; margin-bottom: 10px; }}
  .stat .lbl {{ font-size: 11px; color: #a0b0d8; text-transform: uppercase; letter-spacing: .5px; }}
  .stat .val {{ font-size: 22px; font-weight: 700; color: #fff; margin-top: 4px; }}
  .stat.big .val {{ font-size: 28px; }}
  .stat.red {{ border-left: 4px solid #d32f2f; }}
  .stat.orange {{ border-left: 4px solid #f57c00; }}
  .stat.blue {{ border-left: 4px solid #1976d2; }}
  .rule {{ font-size: 11px; color: #c0c8e0; background: #1a2140; padding: 10px;
           border-radius: 8px; line-height: 1.5; }}
  .rule code {{ background: #0a0e1c; padding: 2px 5px; border-radius: 3px; color: #ffe88a; font-size: 10.5px; }}
  .legend {{ display: flex; gap: 8px; margin-top: 6px; }}
  .dot {{ width: 14px; height: 14px; border-radius: 50%; display: inline-block; vertical-align: middle; margin-right: 6px; }}
  .dot.r {{ background: #d32f2f; }}
  .dot.o {{ background: #f57c00; }}
  .leaflet-popup-content {{ font-size: 12px; min-width: 250px; }}
  .kpi {{ display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #eee; }}
  .kpi:last-child {{ border-bottom: 0; font-weight: 700; }}
  .kpi .v {{ font-family: ui-monospace, monospace; color: #1a2140; }}
  .kpi .v.warn {{ color: #d32f2f; }}
</style>
</head>
<body>
<div id="wrap">
  <div id="side">
    <h1>Discontinuites TVr</h1>
    <p style="font-size:11.5px; color:#a0b0d8; margin-top:0;">
      Carte des noeuds ou les flux entrants / sortants predits sont incoherents.
    </p>

    <h2>Statistiques</h2>
    <div class="stat blue big">
      <div class="lbl">Noeuds discontinus</div>
      <div class="val">{n_discont:,} <span style="font-size:14px; color:#a0b0d8;">/ {n_inner:,}</span></div>
      <div style="font-size:12px; color:#a0b0d8; margin-top:2px;">soit {pct} % des noeuds analyses</div>
    </div>
    <div class="stat red">
      <div class="lbl">Rouge (ecart &gt;= 2x seuil)</div>
      <div class="val">{n_red:,}</div>
    </div>
    <div class="stat orange">
      <div class="lbl">Orange (ecart 1x-2x seuil)</div>
      <div class="val">{n_orange:,}</div>
    </div>

    <h2>Couverture</h2>
    <div class="stat">
      <div class="lbl">Noeuds totaux</div>
      <div class="val" style="font-size:18px;">{n_total:,}</div>
      <div style="font-size:11px; color:#a0b0d8; margin-top:2px;">
        dont {boundary:,} en bordure (exclus)
      </div>
    </div>

    <h2>Regle de discontinuite</h2>
    <div class="rule">
      Ecart = <code>|in_flow - out_flow|</code><br>
      Seuils :
      <ul style="margin:6px 0 0 16px; padding:0;">
        <li>flux &le; 20 000 veh/j : <code>ecart &gt; 2 000</code></li>
        <li>flux &gt; 20 000 veh/j : <code>ecart &gt; 4 000</code></li>
      </ul>
      <div style="margin-top:8px;">
        <span class="dot o"></span>Orange : 1x-2x seuil<br>
        <span class="dot r"></span>Rouge : ecart &ge; 2x seuil
      </div>
    </div>

    <p style="font-size:10px; color:#6a7a98; margin-top:18px;">
      Clic sur un point pour voir les KPIs detaillees.
    </p>
  </div>
  <div id="map"></div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const NODES = {nodes_json};

const map = L.map('map').setView([45.75, 4.85], 11);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '&copy; OpenStreetMap, &copy; CartoDB',
  subdomains: 'abcd', maxZoom: 19,
}}).addTo(map);

function nf(v) {{ return Number(v).toLocaleString('fr-FR'); }}

for (const n of NODES) {{
  const color = n.tier === 'red' ? '#d32f2f' : '#f57c00';
  const radius = n.tier === 'red' ? 7 : 5;
  const m = L.circleMarker([n.lat, n.lon], {{
    radius: radius,
    color: color, weight: 1.5, fillColor: color, fillOpacity: 0.75,
  }});
  const ratio = n.t > 0 ? (n.d / n.t).toFixed(2) : '?';
  m.bindPopup(
    '<div class="kpi"><span>Node ID</span><span class="v">' + n.id + '</span></div>' +
    '<div class="kpi"><span>Liens entrants</span><span class="v">' + n.ni + '</span></div>' +
    '<div class="kpi"><span>Liens sortants</span><span class="v">' + n.no + '</span></div>' +
    '<div class="kpi"><span>Flux entrant (in)</span><span class="v">' + nf(n.in) + ' veh/j</span></div>' +
    '<div class="kpi"><span>Flux sortant (out)</span><span class="v">' + nf(n.out) + ' veh/j</span></div>' +
    '<div class="kpi"><span>Seuil applique</span><span class="v">' + nf(n.t) + '</span></div>' +
    '<div class="kpi"><span>Ecart |in-out|</span><span class="v warn">' + nf(n.d) + ' (' + ratio + 'x)</span></div>'
  );
  m.addTo(map);
}}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    raise SystemExit(main())

"""Build standalone map_node_cause.html (v4) — inline GeoJSON + MapLibre + custom UI.

v4 changes (vs v3):
- Consumes `nodes_with_cause_v3.json` (principal_cause + topology per feature).
- Multi_factor REMOVED entirely from the taxonomy (8 causes instead of 9).
- Dual-encoding markers : fill = principal_cause (8 colors), stroke = topology (3 colors).
- Sidebar : two stat panels (Causes principales + Topologie), then filters.
- Popup : prominent cause badge, topology chip, expandable "Voir toutes les causes" panel
  containing the v3 ranked-drivers UI + per-segment table.
- French accents restored in labels (Bretelle asymétrique, Inexpliqué, …).

Run once. Output: outputs/map_node_cause.html
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
SRC = OUT / "nodes_with_cause_v3.json"
HTML_OUT = OUT / "map_node_cause.html"

src_text = SRC.read_text(encoding="utf-8")
src_data = json.loads(src_text)

META = src_data.get("metadata", {}) or {}
FEATURES = src_data.get("features", []) or []
GEOJSON_OBJ = {"type": "FeatureCollection", "features": FEATURES}

geojson_str = json.dumps(GEOJSON_OBJ, ensure_ascii=False, separators=(",", ":"))
meta_str = json.dumps(META, ensure_ascii=False, separators=(",", ":"))

PALETTE_AND_LABELS_JS = r"""
// 8 causes — Multi_factor a ete supprime de la taxonomie en v4.
// Seuls les deux FCD_*_cliff sont en rouge (signal "qualite de donnees").
const PALETTE = {
  'FCD_TV_cliff':        '#E41A1C',
  'FCD_PL_cliff':        '#B30000',
  'Coverage_gap':        '#7B1FA2',
  'Distance_anomaly':    '#FF7F00',
  'RAMP_asymmetry':      '#FFB000',
  'ROUNDABOUT_asymmetry':'#A65628',
  'FC_transition':       '#377EB8',
  'Unexplained':         '#999999'
};

// Topology : stroke color = encodage visuel de la topologie.
// Continuite en saumon clair pour ressortir (nœud mid-segment, plus suspect).
const TOPO_PALETTE = {
  'Bretelle':   '#87CEEB',
  'Carrefour':  '#4682B4',
  'Continuite': '#FFA07A'
};

// Labels FR avec accents (fallback si META ne couvre pas).
const LABELS_FR_FALLBACK = {
  'FCD_TV_cliff':        'Falaise FCD VL',
  'FCD_PL_cliff':        'Falaise FCD PL',
  'Coverage_gap':        'Trou de couverture FCD',
  'Distance_anomaly':    'Anomalie de distance',
  'RAMP_asymmetry':      'Bretelle asymétrique',
  'ROUNDABOUT_asymmetry':'Rond-point asymétrique',
  'FC_transition':       'Transition de classe fonctionnelle (légitime)',
  'Unexplained':         'Inexpliqué (à investiguer)'
};
const TOPO_LABELS_FR_FALLBACK = {
  'Bretelle':   'Bretelle',
  'Carrefour':  'Carrefour',
  'Continuite': 'Continuité segment'
};
const NARRATIVES_FALLBACK = {
  'FCD_TV_cliff':        'Discontinuité VL reposant sur une falaise des données FCD (ratio TMJO VL min/max élevé).',
  'FCD_PL_cliff':        'Discontinuité PL reposant sur une falaise des données FCD PL (ratio TMJO PL min/max élevé).',
  'Coverage_gap':        'Capteurs absents ou trop espacés : la couverture FCD est lacunaire autour du nœud.',
  'Distance_anomaly':    'Distance inter-nœuds anormale par rapport aux voisins, suggérant un découpage du graphe déficient.',
  'RAMP_asymmetry':      "Bretelle présente uniquement d'un côté du nœud (entrant XOR sortant).",
  'ROUNDABOUT_asymmetry':"Rond-point détecté d'un seul côté : la modélisation du carrefour est asymétrique.",
  'FC_transition':       'Changement attendu de classe fonctionnelle (FC) entre amont et aval : la rupture est légitime.',
  'Unexplained':         "Aucun signal explicatif n'a été déclenché : nœud à investiguer manuellement."
};
const TOPO_HINT = {
  'Bretelle':   "Au moins une bretelle (RAMP=Y) est incidente à ce nœud.",
  'Carrefour':  "Au moins 3 arcs incidents (carrefour) ou rond-point détecté.",
  'Continuite': "1 entrant + 1 sortant, pas de bretelle ni de rond-point — discontinuité en plein segment, suspect."
};
const CAUSE_ORDER = [
  'FCD_TV_cliff','FCD_PL_cliff','Coverage_gap','Distance_anomaly',
  'RAMP_asymmetry','ROUNDABOUT_asymmetry','FC_transition','Unexplained'
];
const TOPO_ORDER = ['Bretelle','Carrefour','Continuite'];

// Z-order : Unexplained en bas, FCD_*_cliff en haut.
const CAUSE_SORT_KEY = {
  'Unexplained':          0,
  'FC_transition':        1,
  'Distance_anomaly':     2,
  'Coverage_gap':         3,
  'RAMP_asymmetry':       4,
  'ROUNDABOUT_asymmetry': 4,
  'FCD_TV_cliff':         5,
  'FCD_PL_cliff':         5
};

// Ordre canonique des inputs (lignes du tableau du popup).
const INPUT_ORDER = [
  'TMJOFCDTV',
  'TMJOFCDPL',
  'functional_class',
  'avg_distance_before_m',
  'avg_min_distance_m',
  'truck_avg_distance_before_m'
];
const INPUT_LABELS_FALLBACK = {
  'TMJOFCDTV': 'Trafic VL (TMJO FCD VL)',
  'TMJOFCDPL': 'Trafic PL (TMJO FCD PL)',
  'functional_class': 'Classe fonctionnelle (FC)',
  'avg_distance_before_m': 'Distance moyenne avant (m)',
  'avg_min_distance_m': 'Distance minimale (m)',
  'truck_avg_distance_before_m': 'Distance moyenne PL avant (m)'
};
"""

HEAD_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Discontinuités de débit TVr - Nœuds Grand Lyon 2025</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<style>
  :root {
    --bg-dark: #14171A;
    --panel-dark: #1B1F23;
    --text-light: #E6E6E6;
    --text-mute: #9AA0A6;
    --accent: #FFB000;
    --border: #2A2F36;
    --red: #E41A1C;
  }
  * { box-sizing: border-box; }
  html, body { margin:0; height:100%; font-family: 'Inter', system-ui, -apple-system, sans-serif; background: var(--bg-dark); color: var(--text-light); }
  #app { display: grid; grid-template-columns: 340px 1fr; height: 100vh; }
  #sidebar { background: var(--bg-dark); border-right: 1px solid var(--border); overflow-y: auto; padding: 16px 18px; }
  #map { width: 100%; height: 100%; }
  #title-bar {
    position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
    background: rgba(27,31,35,0.92); color: var(--text-light);
    padding: 8px 18px; border-radius: 6px; font-size: 14px; font-weight: 600;
    border: 1px solid var(--border); z-index: 5; letter-spacing: 0.2px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25);
  }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-mute); margin: 18px 0 8px; font-weight: 600; }
  h2:first-child { margin-top: 4px; }
  .big-number { font-size: 32px; font-weight: 700; color: var(--text-light); line-height: 1; }
  .big-number small { font-size: 12px; color: var(--text-mute); font-weight: 400; margin-left: 8px; }
  .stack-bar { display:flex; height: 10px; border-radius: 4px; overflow:hidden; margin: 10px 0 12px; background: #2A2F36; }
  .stack-bar > div { height:100%; }
  .legend-row {
    display: flex; align-items: center; gap: 8px; padding: 5px 6px; margin: 1px -6px;
    border-radius: 4px; cursor: pointer; font-size: 12px;
    user-select: none;
  }
  .legend-row:hover { background: #20252B; }
  .legend-row.off { opacity: 0.35; }
  .legend-row .swatch {
    width: 12px; height: 12px; border-radius: 50%; flex: 0 0 12px;
    border: 1px solid rgba(255,255,255,0.15);
  }
  .legend-row .swatch.ring {
    border-radius: 50%; border-width: 3px; background: transparent !important;
  }
  .legend-row .lab { flex: 1; }
  .legend-row .ct { color: var(--text-mute); font-variant-numeric: tabular-nums; }
  .panel-hint {
    font-size: 10.5px; color: var(--text-mute); line-height: 1.5;
    margin-top: 8px; padding: 8px 10px; background: var(--panel-dark);
    border-radius: 4px; border-left: 2px solid var(--accent);
  }
  .filter-block { margin-bottom: 14px; }
  .tier-radios { display: flex; gap: 4px; margin-top: 4px; }
  .tier-radios label {
    flex: 1; text-align: center; padding: 6px 4px; border-radius: 4px;
    background: var(--panel-dark); border: 1px solid var(--border);
    font-size: 11px; cursor: pointer; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .tier-radios input { display: none; }
  .tier-radios input:checked + span { color: var(--accent); }
  .tier-radios label:has(input:checked) { border-color: var(--accent); }
  input[type=search], input[type=text] {
    width: 100%; padding: 7px 9px; border: 1px solid var(--border);
    background: var(--panel-dark); color: var(--text-light); border-radius: 4px;
    font-family: inherit; font-size: 12px; outline: none;
  }
  input[type=search]:focus, input[type=text]:focus { border-color: var(--accent); }
  button.btn {
    width: 100%; padding: 8px 10px; border: 1px solid var(--border);
    background: var(--panel-dark); color: var(--text-light);
    border-radius: 4px; cursor: pointer; font-size: 12px; font-family: inherit;
    margin-top: 6px;
  }
  button.btn:hover { background: #20252B; border-color: var(--accent); }
  button.btn.primary { background: var(--accent); color: #1A1300; border-color: var(--accent); font-weight: 600; }
  button.btn.primary:hover { background: #FFC233; }
  .footer-note {
    margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--border);
    font-size: 10px; color: var(--text-mute); line-height: 1.5;
  }
  /* ----- Popup v4 ----- */
  .maplibregl-popup-content {
    background: #1B1F23 !important; color: #E6E6E6; padding: 0 !important;
    border-radius: 6px; width: 460px; box-shadow: 0 10px 30px rgba(0,0,0,0.45);
    font-family: 'Inter', system-ui, sans-serif;
    border: 1px solid #2A2F36;
    max-height: 85vh; overflow-y: auto;
  }
  .maplibregl-popup-close-button { color: #E6E6E6 !important; font-size: 22px !important; padding: 4px 9px !important; }
  .maplibregl-popup-tip { display: none; }
  .popup { font-size: 12.5px; line-height: 1.45; }
  .popup section { padding: 12px 14px; border-bottom: 1px solid #2A2F36; }
  .popup section:last-of-type { border-bottom: none; }
  .popup .head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 14px 10px; border-bottom: 1px solid #2A2F36;
  }
  .popup .head .nid { font-weight: 700; font-size: 13px; }
  .popup .head .nid small { color: #9AA0A6; font-weight: 400; font-size: 10px; display: block; margin-top: 2px; letter-spacing: 0.5px; text-transform: uppercase; }
  .badge { display: inline-block; padding: 3px 9px; border-radius: 99px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; }
  .badge.red { background: #5A1518; color: #FF8E92; border: 1px solid #E41A1C; }
  .badge.orange { background: #4A2E0E; color: #FFC58A; border: 1px solid #FF7F00; }
  .popup h4 { margin: 0 0 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; color: #9AA0A6; font-weight: 600; }

  /* Cause principale BIG */
  .cause-big {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 14px; border-radius: 6px; font-weight: 700; font-size: 16px;
    color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.45);
    border: 1px solid rgba(255,255,255,0.08);
  }
  .cause-big .dot { width: 14px; height: 14px; border-radius: 50%; background: rgba(255,255,255,0.85); flex: 0 0 14px; box-shadow: 0 0 0 2px rgba(0,0,0,0.25); }

  .narrative { color: #BFC4CA; font-size: 12.5px; margin-top: 10px; line-height: 1.55; }

  /* Topologie chip */
  .topo-line { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .topo-line .lbl { font-size: 10.5px; color: #9AA0A6; text-transform: uppercase; letter-spacing: 0.6px; }
  .topo-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 99px; font-size: 11.5px; font-weight: 600;
    color: #fff;
  }
  .topo-chip .dot { width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,0.85); }
  .topo-hint { color: #9AA0A6; font-size: 10.5px; margin-top: 4px; line-height: 1.5; flex-basis: 100%; }

  .kpi-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .kpi-row .cell { background: #14171A; padding: 7px 9px; border-radius: 4px; }
  .kpi-row .cell .lab { font-size: 10px; color: #9AA0A6; text-transform: uppercase; letter-spacing: 0.4px; }
  .kpi-row .cell .val { font-size: 14px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
  .kpi-row .cell.ecart .val { color: #FF8E92; }

  /* <details> expandable */
  .popup details { margin: 0; padding: 0; }
  .popup details > summary {
    list-style: none; cursor: pointer; padding: 10px 14px;
    background: #14171A; border-top: 1px solid #2A2F36; border-bottom: 1px solid #2A2F36;
    font-size: 11.5px; font-weight: 600; color: #E6E6E6;
    display: flex; align-items: center; justify-content: space-between;
    user-select: none;
  }
  .popup details > summary::-webkit-details-marker { display: none; }
  .popup details > summary::after {
    content: '+'; font-size: 16px; color: var(--accent); font-weight: 400;
    margin-left: 6px; transition: transform 0.15s;
  }
  .popup details[open] > summary::after { content: '−'; }
  .popup details > summary:hover { background: #20252B; }
  .popup details .body { padding: 0; }

  /* Rank badges */
  .driver-badges { display: flex; flex-direction: column; gap: 5px; }
  .driver-badge {
    display: flex; align-items: center; gap: 8px;
    padding: 5px 8px; border-radius: 4px;
    background: #14171A; border: 1px solid #2A2F36;
    font-size: 11.5px;
  }
  .driver-badge .rank {
    width: 20px; height: 20px; border-radius: 50%;
    background: #2A2F36; color: #fff;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 700; flex: 0 0 20px;
  }
  .driver-badge.r1 { border-color: #E41A1C; background: #2A1414; }
  .driver-badge.r1 .rank { background: #E41A1C; color: #fff; }
  .driver-badge.r2 { border-color: #FF7F00; background: #2A1F0E; }
  .driver-badge.r2 .rank { background: #FF7F00; color: #1A0F00; }
  .driver-badge.r3 { border-color: #FFB000; background: #2A230E; }
  .driver-badge.r3 .rank { background: #FFB000; color: #1A1300; }
  .driver-badge .lbl { flex: 1; color: #E6E6E6; font-weight: 500; }
  .driver-badge .val { color: #FFB7B7; font-weight: 700; font-variant-numeric: tabular-nums; }
  .driver-extra { color: #9AA0A6; font-size: 10.5px; margin-top: 5px; font-style: italic; }

  /* Table inputs x edges */
  .table-wrap { overflow-x: auto; margin-top: 4px; }
  .pop-table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 4px; }
  .pop-table th {
    position: sticky; top: 0; z-index: 1;
    background: #14171A; color: #fff;
    padding: 4px 6px; text-align: right; font-weight: 600;
    border-bottom: 1px solid #2a2f36;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .pop-table th.var { text-align: left; min-width: 130px; }
  .pop-table th.edge-e { background: #1e3a5f; color: #cfe0ff; }
  .pop-table th.edge-s { background: #5f1e3a; color: #ffcfe0; }
  .pop-table th.edge-tvr { font-weight: 400; font-size: 10px; color: #cfd6df; background: #14171A; }
  .pop-table th.edge-tvr.edge-e { background: #14202d; color: #9fb5d4; }
  .pop-table th.edge-tvr.edge-s { background: #2d1420; color: #d49fb5; }
  .pop-table td {
    padding: 3px 6px; text-align: right;
    border-bottom: 1px solid #1f2329;
    color: #9ca3af;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .pop-table td.var { text-align: left; font-weight: 500; color: #d4d4d8; }
  .pop-table tr.driver td { background: #2a1414; color: #FFB7B7; font-weight: 600; }
  .pop-table tr.driver td.var { color: #FFB7B7; }

  .popup-actions { display: flex; gap: 6px; padding: 10px 14px 12px; }
  .popup-actions button, .popup-actions a {
    flex: 1; padding: 7px 8px; border-radius: 4px; font-size: 11.5px;
    text-align: center; text-decoration: none; font-family: inherit; cursor: pointer;
    background: #14171A; color: #E6E6E6; border: 1px solid #2A2F36; font-weight: 500;
  }
  .popup-actions button:hover, .popup-actions a:hover { border-color: var(--accent); color: var(--accent); }
  #toast {
    position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
    background: var(--panel-dark); color: var(--accent); padding: 10px 18px;
    border-radius: 4px; border: 1px solid var(--accent); font-size: 12px;
    z-index: 1000; pointer-events: none; opacity: 0; transition: opacity 0.2s;
    font-weight: 600;
  }
  #toast.show { opacity: 1; }
  #loader {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    background: rgba(20,23,26,0.6); z-index: 10; color: var(--text-light); font-size: 13px;
  }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #2A2F36; border-radius: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
</style>
</head>
<body>
<div id="app">
  <aside id="sidebar">
    <h2>Vue d'ensemble</h2>
    <div class="big-number"><span id="stat-total">0</span><small>nœuds visibles / <span id="stat-grand-total">0</span></small></div>

    <h2>Causes principales</h2>
    <div id="stack-bar-causes" class="stack-bar"></div>
    <div id="legend-causes"></div>

    <h2>Topologie</h2>
    <div id="stack-bar-topo" class="stack-bar"></div>
    <div id="legend-topo"></div>
    <div class="panel-hint">
      ℹ️ Une discontinuité sur un nœud <strong>« Continuité segment »</strong>
      est plus suspecte qu'un saut à un carrefour ou en sortie de bretelle :
      il n'y a aucune intersection physique pour la justifier.
    </div>

    <h2>Sévérité</h2>
    <div class="tier-radios" id="tier-radios">
      <label><input type="radio" name="tier" value="all" checked><span>Tous</span></label>
      <label><input type="radio" name="tier" value="orange"><span>Orange</span></label>
      <label><input type="radio" name="tier" value="red"><span>Rouge</span></label>
    </div>

    <h2>Recherche</h2>
    <input type="search" id="search-node" placeholder="node_id (ex: 611034076)" autocomplete="off">

    <h2>Actions</h2>
    <button class="btn primary" id="btn-fit" title="Recadrer la vue sur les nœuds actuellement visibles">Recadrer sur les nœuds</button>
    <button class="btn" id="btn-reset">Réinitialiser les filtres</button>

    <div class="footer-note">
      Source : MDL Redressement Tool · Grand Lyon · méthodologie discontinuités v4.0<br>
      Seuil rouge : écart &ge; 7 200 v/j (p75). Fond CartoDB Positron, MapLibre GL 4.7.1.<br>
      Encodage : <strong>remplissage = cause principale</strong>, <strong>contour = topologie</strong>.
    </div>
  </aside>
  <div style="position:relative;">
    <div id="title-bar">Discontinuités de débit TVr - Nœuds Grand Lyon 2025</div>
    <div id="map"></div>
    <div id="loader">Chargement de la carte...</div>
  </div>
</div>
<div id="toast"></div>

<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script>
"""

MAIN_JS = r"""
// ---------------- UTIL ----------------
const fmtFR = (n) => {
  if (n === null || n === undefined || (typeof n === 'number' && isNaN(n))) return '—';
  return Number(n).toLocaleString('fr-FR', { maximumFractionDigits: 0 });
};
const fmtFRdec = (n, d=2) => {
  if (n === null || n === undefined || (typeof n === 'number' && isNaN(n))) return '—';
  return Number(n).toLocaleString('fr-FR', { maximumFractionDigits: d, minimumFractionDigits: 0 });
};
const escapeHtml = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 1600);
}

// Resolveurs labels (META > fallback local).
function causeLabel(c) {
  const m = (META && META.cause_labels_fr) || {};
  return m[c] || LABELS_FR_FALLBACK[c] || c;
}
function topoLabel(t) {
  const m = (META && META.topology_labels_fr) || {};
  return m[t] || TOPO_LABELS_FR_FALLBACK[t] || t;
}
function inputLabel(k) {
  const m = (META && META.input_labels) || {};
  return m[k] || INPUT_LABELS_FALLBACK[k] || k;
}

// ---------------- COMPTAGES ----------------
const causeCounts = {};
CAUSE_ORDER.forEach(c => causeCounts[c] = 0);
const topoCounts = {};
TOPO_ORDER.forEach(t => topoCounts[t] = 0);

NODES_GEOJSON.features.forEach(f => {
  const p = f.properties;
  const c = p.principal_cause;
  const t = p.topology;
  if (causeCounts[c] === undefined) causeCounts[c] = 0;
  causeCounts[c] += 1;
  if (topoCounts[t] === undefined) topoCounts[t] = 0;
  topoCounts[t] += 1;
});
const TOTAL = NODES_GEOJSON.features.length;

// ---------------- LEGEND : Causes principales ----------------
const causesLegendEl = document.getElementById('legend-causes');
const activeCauses = new Set(CAUSE_ORDER);  // toutes ON par defaut (Multi gone)
CAUSE_ORDER.forEach(cause => {
  const ct = causeCounts[cause] || 0;
  const row = document.createElement('div');
  row.className = 'legend-row';
  row.dataset.cause = cause;
  if (ct === 0) row.style.display = 'none';
  const pct = TOTAL ? ((ct / TOTAL) * 100).toFixed(1) : '0';
  row.innerHTML = `
    <span class="swatch" style="background:${PALETTE[cause]}"></span>
    <span class="lab">${escapeHtml(causeLabel(cause))}</span>
    <span class="ct">${fmtFR(ct)} (${pct}%)</span>
  `;
  row.addEventListener('click', () => {
    if (activeCauses.has(cause)) {
      activeCauses.delete(cause);
      row.classList.add('off');
    } else {
      activeCauses.add(cause);
      row.classList.remove('off');
    }
    applyFilters();
  });
  causesLegendEl.appendChild(row);
});

// Stack bar — causes
const stackCauses = document.getElementById('stack-bar-causes');
CAUSE_ORDER.forEach(cause => {
  const ct = causeCounts[cause] || 0;
  if (ct === 0) return;
  const seg = document.createElement('div');
  seg.style.background = PALETTE[cause];
  seg.style.width = ((ct / TOTAL) * 100).toFixed(2) + '%';
  seg.title = `${causeLabel(cause)} : ${fmtFR(ct)}`;
  stackCauses.appendChild(seg);
});

// ---------------- LEGEND : Topologie ----------------
const topoLegendEl = document.getElementById('legend-topo');
const activeTopos = new Set(TOPO_ORDER);
TOPO_ORDER.forEach(topo => {
  const ct = topoCounts[topo] || 0;
  const row = document.createElement('div');
  row.className = 'legend-row';
  row.dataset.topo = topo;
  if (ct === 0) row.style.display = 'none';
  const pct = TOTAL ? ((ct / TOTAL) * 100).toFixed(1) : '0';
  // Anneau (ring) pour bien rappeler que la topologie = contour du marqueur
  row.innerHTML = `
    <span class="swatch ring" style="border-color:${TOPO_PALETTE[topo]}"></span>
    <span class="lab">${escapeHtml(topoLabel(topo))}</span>
    <span class="ct">${fmtFR(ct)} (${pct}%)</span>
  `;
  row.addEventListener('click', () => {
    if (activeTopos.has(topo)) {
      activeTopos.delete(topo);
      row.classList.add('off');
    } else {
      activeTopos.add(topo);
      row.classList.remove('off');
    }
    applyFilters();
  });
  topoLegendEl.appendChild(row);
});

// Stack bar — topo
const stackTopo = document.getElementById('stack-bar-topo');
TOPO_ORDER.forEach(topo => {
  const ct = topoCounts[topo] || 0;
  if (ct === 0) return;
  const seg = document.createElement('div');
  seg.style.background = TOPO_PALETTE[topo];
  seg.style.width = ((ct / TOTAL) * 100).toFixed(2) + '%';
  seg.title = `${topoLabel(topo)} : ${fmtFR(ct)}`;
  stackTopo.appendChild(seg);
});

document.getElementById('stat-grand-total').textContent = fmtFR(TOTAL);

// ---------------- MAP ----------------
const POSITRON = {
  version: 8,
  sources: {
    carto: {
      type: 'raster',
      tiles: [
        'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
        'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
        'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
        'https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png'
      ],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
    }
  },
  layers: [{ id: 'carto', type: 'raster', source: 'carto' }],
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf'
};

const map = new maplibregl.Map({
  container: 'map',
  style: POSITRON,
  center: [4.85, 45.75],
  zoom: 11,
  attributionControl: true
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
map.addControl(new maplibregl.FullscreenControl(), 'top-right');

// Fill color = principal_cause
const COLOR_MATCH = ['match', ['get', 'principal_cause']];
CAUSE_ORDER.forEach(c => { COLOR_MATCH.push(c, PALETTE[c]); });
COLOR_MATCH.push('#999999');

// Stroke color = topology
const STROKE_COLOR_MATCH = ['match', ['get', 'topology']];
TOPO_ORDER.forEach(t => { STROKE_COLOR_MATCH.push(t, TOPO_PALETTE[t]); });
STROKE_COLOR_MATCH.push('#FFFFFF');

const SORT_KEY_MATCH = ['match', ['get', 'principal_cause']];
CAUSE_ORDER.forEach(c => { SORT_KEY_MATCH.push(c, CAUSE_SORT_KEY[c] != null ? CAUSE_SORT_KEY[c] : 0); });
SORT_KEY_MATCH.push(0);

const RADIUS_EXPR = [
  'interpolate', ['linear'], ['zoom'],
  10, ['max', 4, ['min', 12, ['/', ['sqrt', ['max', 1, ['get', 'ecart']]], 8]]],
  13, ['max', 4, ['min', 14, ['/', ['sqrt', ['max', 1, ['get', 'ecart']]], 6]]],
  16, ['max', 5, ['min', 18, ['/', ['sqrt', ['max', 1, ['get', 'ecart']]], 5]]]
];

const RADIUS_HALO_EXPR = [
  'interpolate', ['linear'], ['zoom'],
  10, ['+', 4, ['max', 4, ['min', 12, ['/', ['sqrt', ['max', 1, ['get', 'ecart']]], 8]]]],
  13, ['+', 4, ['max', 4, ['min', 14, ['/', ['sqrt', ['max', 1, ['get', 'ecart']]], 6]]]],
  16, ['+', 4, ['max', 5, ['min', 18, ['/', ['sqrt', ['max', 1, ['get', 'ecart']]], 5]]]]
];

const OPACITY_EXPR = ['case', ['==', ['get', 'tier'], 'red'], 0.9, 0.55];

map.on('load', () => {
  document.getElementById('loader').style.display = 'none';

  map.addSource('nodes', { type: 'geojson', data: NODES_GEOJSON });

  map.addLayer({
    id: 'nodes-halo',
    type: 'circle',
    source: 'nodes',
    filter: ['==', ['get', 'tier'], 'red'],
    paint: {
      'circle-radius': RADIUS_HALO_EXPR,
      'circle-color': COLOR_MATCH,
      'circle-opacity': 0.22,
      'circle-stroke-width': 0
    }
  });

  map.addLayer({
    id: 'nodes-circle',
    type: 'circle',
    source: 'nodes',
    layout: {
      'circle-sort-key': SORT_KEY_MATCH
    },
    paint: {
      'circle-radius': RADIUS_EXPR,
      'circle-color': COLOR_MATCH,
      'circle-opacity': OPACITY_EXPR,
      'circle-stroke-color': STROKE_COLOR_MATCH,
      'circle-stroke-width': 2,
      'circle-stroke-opacity': 0.95
    }
  });

  const canvas = map.getCanvas();
  map.on('mousemove', 'nodes-circle', () => { canvas.style.cursor = 'pointer'; });
  map.on('mouseleave', 'nodes-circle', () => { canvas.style.cursor = ''; });

  map.on('click', 'nodes-circle', (e) => {
    const feat = e.features[0];
    const coords = feat.geometry.coordinates.slice();
    showPopup(feat, coords);
  });

  applyFilters();
});

// ---------------- POPUP v4 ----------------
let currentPopup = null;

function tierLabel(t) { return t === 'red' ? 'Rouge' : 'Orange'; }

function fmtCellValue(k, v) {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
  if (k === 'functional_class') return String(Math.round(Number(v)));
  if (k && k.endsWith('_m')) return fmtFRdec(v, 1);
  return fmtFR(v);
}
function fmtDriverExtreme(k, score) {
  if (!score) return '';
  if (k === 'functional_class') {
    const lo = (score.min != null) ? Math.round(Number(score.min)) : '?';
    const hi = (score.max != null) ? Math.round(Number(score.max)) : '?';
    return `${lo} → ${hi}`;
  }
  if (typeof score.ratio === 'number' && isFinite(score.ratio)) return '×' + fmtFRdec(score.ratio, 1);
  if (typeof score.delta === 'number') return 'Δ' + fmtFR(score.delta);
  return '';
}

function buildPopupHTML(feature) {
  const p = feature.properties;
  const cause = p.principal_cause || 'Unexplained';
  const tier = p.tier;
  const topo = p.topology || 'Carrefour';
  const color = PALETTE[cause] || '#999';
  const topoColor = TOPO_PALETTE[topo] || '#4682B4';
  const lat = (typeof p.lat === 'number') ? p.lat : (feature.geometry && feature.geometry.coordinates ? feature.geometry.coordinates[1] : null);
  const lon = (typeof p.lon === 'number') ? p.lon : (feature.geometry && feature.geometry.coordinates ? feature.geometry.coordinates[0] : null);

  let drivers = p.drivers;
  if (typeof drivers === 'string') { try { drivers = JSON.parse(drivers); } catch(_) { drivers = []; } }
  if (!Array.isArray(drivers)) drivers = [];

  let scores = p.driver_scores;
  if (typeof scores === 'string') { try { scores = JSON.parse(scores); } catch(_) { scores = {}; } }
  if (!scores || typeof scores !== 'object') scores = {};

  let edgesIn = p.edges_in;
  if (typeof edgesIn === 'string') { try { edgesIn = JSON.parse(edgesIn); } catch(_) { edgesIn = []; } }
  if (!Array.isArray(edgesIn)) edgesIn = [];

  let edgesOut = p.edges_out;
  if (typeof edgesOut === 'string') { try { edgesOut = JSON.parse(edgesOut); } catch(_) { edgesOut = []; } }
  if (!Array.isArray(edgesOut)) edgesOut = [];

  const narrativeText = (typeof p.narrative === 'string' && p.narrative.length > 0)
    ? p.narrative
    : (NARRATIVES_FALLBACK[cause] || '');

  // ---- HEADER
  const headHTML = `
    <div class="head">
      <div class="nid">Nœud ${escapeHtml(p.node_id)}<small>${fmtFRdec(lat,5)}, ${fmtFRdec(lon,5)}</small></div>
      <span class="badge ${tier}">${tierLabel(tier)}</span>
    </div>
  `;

  // ---- CAUSE PRINCIPALE (BIG)
  const causeHTML = `
    <section>
      <h4>Cause principale</h4>
      <div class="cause-big" style="background:${color};">
        <span class="dot"></span>${escapeHtml(causeLabel(cause))}
      </div>
      <div class="narrative">${escapeHtml(narrativeText)}</div>
      <div class="topo-line">
        <span class="lbl">Topologie :</span>
        <span class="topo-chip" style="background:${topoColor};">
          <span class="dot"></span>${escapeHtml(topoLabel(topo))}
        </span>
        <span class="topo-hint">${escapeHtml(TOPO_HINT[topo] || '')}</span>
      </div>
    </section>
  `;

  // ---- FLUX (KPIs)
  const fluxHTML = `
    <section>
      <h4>Flux</h4>
      <div class="kpi-row">
        <div class="cell"><div class="lab">Entrant</div><div class="val">${fmtFR(p.flow_in)} v/j</div></div>
        <div class="cell"><div class="lab">Sortant</div><div class="val">${fmtFR(p.flow_out)} v/j</div></div>
        <div class="cell ecart"><div class="lab">Écart</div><div class="val">${fmtFR(p.ecart)} v/j</div></div>
      </div>
      <div style="font-size:10.5px;color:#9AA0A6;margin-top:6px;">n_in = ${p.n_in} &middot; n_out = ${p.n_out}</div>
    </section>
  `;

  // ---- EXPANDABLE : Voir toutes les causes
  // Build content
  let driversInner = '';
  if (drivers.length >= 1) {
    const sorted = drivers.slice().sort((a, b) => {
      const ra = (scores[a] && scores[a].rank != null) ? scores[a].rank : 999;
      const rb = (scores[b] && scores[b].rank != null) ? scores[b].rank : 999;
      return ra - rb;
    });
    const top = sorted.slice(0, 3);
    const extra = sorted.length - top.length;
    let rows = '';
    top.forEach((k, i) => {
      const score = scores[k] || {};
      const extreme = fmtDriverExtreme(k, score);
      const rankClass = `r${i + 1}`;
      rows += `
        <div class="driver-badge ${rankClass}">
          <span class="rank">#${i + 1}</span>
          <span class="lbl">${escapeHtml(inputLabel(k))}</span>
          <span class="val">${escapeHtml(extreme)}</span>
        </div>
      `;
    });
    const extraLine = extra > 0
      ? `<div class="driver-extra">+ ${extra} autre${extra > 1 ? 's' : ''} facteur${extra > 1 ? 's' : ''} détecté${extra > 1 ? 's' : ''}</div>`
      : '';
    driversInner = `
      <section>
        <h4>Drivers classés</h4>
        <div class="driver-badges">${rows}</div>
        ${extraLine}
      </section>
    `;
  } else {
    driversInner = `
      <section>
        <h4>Drivers classés</h4>
        <div style="color:#9AA0A6;font-size:11.5px;">Aucun driver statistique déclenché — cause attribuée par topologie.</div>
      </section>
    `;
  }

  const allEdges = edgesIn.concat(edgesOut);
  let tableInner = '';
  if (allEdges.length > 0) {
    let hdr1 = '<th class="var">Variable</th>';
    let hdr2 = '<th class="var edge-tvr">TVr (v/j)</th>';
    allEdges.forEach(e => {
      const lbl = e.label || '';
      const isE = lbl.startsWith('E');
      const cls = isE ? 'edge-e' : 'edge-s';
      hdr1 += `<th class="${cls}">${escapeHtml(lbl)}</th>`;
      hdr2 += `<th class="${cls} edge-tvr">${fmtFR(e.TVr)}</th>`;
    });
    const driverSet = new Set(drivers);
    let rows = '';
    INPUT_ORDER.forEach(k => {
      const isDriver = driverSet.has(k);
      const label = inputLabel(k);
      const cells = allEdges.map(e => {
        const v = (e.inputs && e.inputs[k] !== undefined) ? e.inputs[k] : null;
        return `<td>${escapeHtml(fmtCellValue(k, v))}</td>`;
      }).join('');
      rows += `
        <tr class="${isDriver ? 'driver' : ''}">
          <td class="var">${escapeHtml(label)}</td>
          ${cells}
        </tr>
      `;
    });
    tableInner = `
      <section>
        <h4>Valeurs par segment</h4>
        <div class="table-wrap">
          <table class="pop-table">
            <thead>
              <tr>${hdr1}</tr>
              <tr>${hdr2}</tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  const nDrivers = drivers.length;
  const detailsHTML = `
    <details>
      <summary>Voir toutes les causes${nDrivers > 0 ? ` (${nDrivers})` : ''} et valeurs par segment</summary>
      <div class="body">
        ${driversInner}
        ${tableInner}
      </div>
    </details>
  `;

  // ---- ACTIONS
  const osmHref = (lat != null && lon != null)
    ? `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=18/${lat}/${lon}`
    : 'https://www.openstreetmap.org/';
  const actionsHTML = `
    <div class="popup-actions">
      <button data-copy="${escapeHtml(p.node_id)}">Copier ID</button>
      <a href="${osmHref}" target="_blank" rel="noopener">Voir sur OSM</a>
    </div>
  `;

  return `
    <div class="popup">
      ${headHTML}
      ${causeHTML}
      ${fluxHTML}
      ${detailsHTML}
      ${actionsHTML}
    </div>
  `;
}

function showPopup(feat, coords) {
  const html = buildPopupHTML(feat);
  if (currentPopup) currentPopup.remove();
  currentPopup = new maplibregl.Popup({ closeButton: true, maxWidth: '480px', offset: 12 })
    .setLngLat(coords)
    .setHTML(html)
    .addTo(map);
  setTimeout(() => {
    const btn = document.querySelector('.popup-actions button[data-copy]');
    if (btn) {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-copy');
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(id).then(
            () => showToast('Node ID copié : ' + id),
            () => showToast('Échec de la copie')
          );
        } else {
          const ta = document.createElement('textarea');
          ta.value = id; document.body.appendChild(ta); ta.select();
          try { document.execCommand('copy'); showToast('Node ID copié : ' + id); }
          catch(_) { showToast('Échec de la copie'); }
          document.body.removeChild(ta);
        }
      });
    }
  }, 30);
}

// ---------------- FILTERS ----------------
let currentTier = 'all';
let searchTerm = '';
let searchTimer = null;

function applyFilters() {
  updateVisibleCount();
  if (!map.getLayer('nodes-circle')) return;
  const filters = ['all'];
  const causesIn = Array.from(activeCauses);
  const toposIn = Array.from(activeTopos);
  filters.push(['in', ['get', 'principal_cause'], ['literal', causesIn]]);
  filters.push(['in', ['get', 'topology'], ['literal', toposIn]]);
  if (currentTier !== 'all') filters.push(['==', ['get', 'tier'], currentTier]);
  if (searchTerm) filters.push(['in', searchTerm, ['to-string', ['get', 'node_id']]]);
  map.setFilter('nodes-circle', filters);

  if (currentTier === 'all' || currentTier === 'red') {
    map.setLayoutProperty('nodes-halo', 'visibility', 'visible');
    const haloFilter = ['all',
      ['==', ['get', 'tier'], 'red'],
      ['in', ['get', 'principal_cause'], ['literal', causesIn]],
      ['in', ['get', 'topology'], ['literal', toposIn]]
    ];
    if (searchTerm) haloFilter.push(['in', searchTerm, ['to-string', ['get', 'node_id']]]);
    map.setFilter('nodes-halo', haloFilter);
  } else {
    map.setLayoutProperty('nodes-halo', 'visibility', 'none');
  }
}

function updateVisibleCount() {
  let n = 0;
  NODES_GEOJSON.features.forEach(f => {
    const p = f.properties;
    if (!activeCauses.has(p.principal_cause)) return;
    if (!activeTopos.has(p.topology)) return;
    if (currentTier !== 'all' && p.tier !== currentTier) return;
    if (searchTerm && !String(p.node_id).includes(searchTerm)) return;
    n++;
  });
  document.getElementById('stat-total').textContent = fmtFR(n);
}

document.querySelectorAll('#tier-radios input').forEach(inp => {
  inp.addEventListener('change', () => {
    currentTier = inp.value;
    applyFilters();
  });
});

const searchInput = document.getElementById('search-node');
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    searchTerm = searchInput.value.trim();
    applyFilters();
    if (searchTerm) {
      const m = NODES_GEOJSON.features.find(f => String(f.properties.node_id).includes(searchTerm));
      if (m) map.flyTo({ center: m.geometry.coordinates, zoom: 16, duration: 800 });
    }
  }, 220);
});

document.getElementById('btn-reset').addEventListener('click', () => {
  activeCauses.clear();
  CAUSE_ORDER.forEach(c => activeCauses.add(c));
  activeTopos.clear();
  TOPO_ORDER.forEach(t => activeTopos.add(t));
  document.querySelectorAll('#legend-causes .legend-row').forEach(r => r.classList.remove('off'));
  document.querySelectorAll('#legend-topo .legend-row').forEach(r => r.classList.remove('off'));
  document.querySelector('#tier-radios input[value=all]').checked = true;
  currentTier = 'all';
  searchInput.value = '';
  searchTerm = '';
  applyFilters();
});

document.getElementById('btn-fit').addEventListener('click', () => {
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity, any = false;
  NODES_GEOJSON.features.forEach(f => {
    const p = f.properties;
    if (!activeCauses.has(p.principal_cause)) return;
    if (!activeTopos.has(p.topology)) return;
    if (currentTier !== 'all' && p.tier !== currentTier) return;
    if (searchTerm && !String(p.node_id).includes(searchTerm)) return;
    any = true;
    const [lng, lat] = f.geometry.coordinates;
    if (lng < minLng) minLng = lng;
    if (lat < minLat) minLat = lat;
    if (lng > maxLng) maxLng = lng;
    if (lat > maxLat) maxLat = lat;
  });
  if (any) map.fitBounds([[minLng, minLat], [maxLng, maxLat]], { padding: 60, duration: 800, maxZoom: 15 });
  else showToast('Aucun nœud visible');
});

updateVisibleCount();
"""

TAIL_HTML = """
</script>
</body>
</html>
"""

# Assemble
parts = [
    HEAD_HTML,
    PALETTE_AND_LABELS_JS,
    "\nconst META = ",
    meta_str,
    ";\n",
    "const NODES_GEOJSON = ",
    geojson_str,
    ";\n",
    MAIN_JS,
    TAIL_HTML,
]
html = "".join(parts)

HTML_OUT.write_text(html, encoding="utf-8")

size = HTML_OUT.stat().st_size
print(f"WROTE: {HTML_OUT}")
print(f"SIZE: {size/(1024*1024):.2f} MB ({size} bytes)")

# Validation
assert "const NODES_GEOJSON = " in html, "GeoJSON inlining missing"
assert '"FeatureCollection"' in html, "FeatureCollection token missing"
assert "principal_cause" in html, "principal_cause not used"
assert "topology" in html, "topology not used"
# v3 had Multi_factor — v4 must NOT mention it as a cause palette key.
assert "'Multi_factor'" not in html, "Multi_factor should be gone from palette"
# Accents present
for needle in ['Bretelle asymétrique', 'Rond-point asymétrique', 'Inexpliqué', 'Transition de classe fonctionnelle (légitime)']:
    assert needle in html, f"Missing accented label: {needle}"
print("All accented labels present.")

# Palette colors present
for hx in ['#E41A1C','#B30000','#7B1FA2','#FF7F00','#FFB000','#A65628','#377EB8','#999999']:
    assert hx in html, f"Missing palette color {hx}"
# Topology palette
for hx in ['#87CEEB','#4682B4','#FFA07A']:
    assert hx in html, f"Missing topo palette color {hx}"
print("All 8 cause colors + 3 topology colors present.")

# Sidebar markers
for marker in ['legend-causes', 'legend-topo', 'stack-bar-causes', 'stack-bar-topo', 'Continuité segment']:
    assert marker in html, f"Missing sidebar marker {marker}"
# Popup markers
for marker in ['Cause principale', 'Voir toutes les causes', 'cause-big', 'topo-chip', 'driver-badges']:
    assert marker in html, f"Missing popup marker {marker}"
print("All sidebar + popup markers present.")

from collections import Counter
cc = Counter(f["properties"]["principal_cause"] for f in FEATURES)
tt = Counter(f["properties"]["topology"] for f in FEATURES)
print("\nPrincipal cause distribution:")
for c in ['FCD_TV_cliff','FCD_PL_cliff','Coverage_gap','Distance_anomaly','RAMP_asymmetry','ROUNDABOUT_asymmetry','FC_transition','Unexplained']:
    print(f"  {c}: {cc.get(c, 0)}")
print("Topology distribution:")
for t in ['Bretelle','Carrefour','Continuite']:
    print(f"  {t}: {tt.get(t, 0)}")

print("OK.")

# Review 05 — Output visualisation (HTML map)

Reviewer scope: map design, color semantics, interactivity, UX, output usability. Source documents: `00_METHODOLOGY.md` §4-5 and the two detail docs. User requirement: standalone HTML map with green = OK / orange = moderate / red = severe.

## Verdict: APPROVE WITH CHANGES

The output schema in §4 is map-ready (LineStrings already aligned to flow direction + `composite_severity` already ranked), but the methodology stops at GeoJSON export. To honour the user request we must add a small `S8 — render_html_map.py` stage. The user said "points" but the truthful unit of analysis is the **edge** (where `composite_severity` lives) with **nodes overlaid** when `is_bad` (the imbalance lives there, not on a segment). Forcing nodes-only would discard 60 % of the signal (Check A jumps). Below: concrete library, thresholds, layer plan, anti-patterns.

---

## 1. What to plot — nodes vs edges vs both

Plot **both, as toggleable layers**, with edges as the default visible layer.

- **Edges layer (default ON).** All edges with `composite_severity > 0`, colored by 3-tier severity, drawn over a muted basemap. This is where `top_issue` (`jump_up`/`jump_down`/`node_*_imbalance`) is visualised — a segment-level decision is what the QGIS reviewer actually opens to inspect.
- **Nodes layer (default ON, smaller markers).** All nodes with `is_bad=True` from `discontinuity_nodes.csv`, plotted as circle markers at the junction's representative point (use `edges.in_node` group centroid of incident segment endpoints — node coords are not in the schema, derive at export time). This honors the user's "points" wording AND surfaces the conservation-side signal.
- **OK layer (default OFF).** Green edges with `composite_severity == 0` should NOT be exported by default — 241 k LineStrings will kill the browser (see §4). Provide a `--include-ok` CLI flag that emits a separate `ok_edges.geojson` for users who want it as a background overlay; render via vector tiles only.

Toggle via a Leaflet `L.control.layers` widget (top-right). Edges layer always wins on z-order over nodes when both visible, because clicking a node usually means the analyst wants to inspect the segments around it — keep node markers small (radius 4 px) and semi-transparent (0.7) so they don't occlude edges.

---

## 2. Color scale semantics

**Three discrete tiers, not a continuous gradient.** A gradient on `composite_severity` is technically richer but defeats the user's spec and is harder to scan during a QGIS-style review pass.

Bind tiers to **percentiles of `composite_severity` over flagged edges** (already exported in `discontinuity_qc.json` per §S7), not to absolute cuts — Lyon's distribution will drift each release and absolute cuts will go stale.

| Tier   | Condition                                          | Color (default) | Colorblind-safe alternative |
|--------|----------------------------------------------------|-----------------|------------------------------|
| OK     | `composite_severity == 0` (not exported by default) | `#2ECC71` green | `#0571B0` blue              |
| Moderate | `0 < composite_severity ≤ p75`                   | `#F39C12` orange | `#F4A582` light orange     |
| Severe | `composite_severity > p75`                         | `#E74C3C` red   | `#CA0020` dark red           |

**Accessibility.** Default red/orange/green is the user's explicit request — keep it but ship a `--palette {classic,cvd}` flag where `cvd` = ColorBrewer `RdBu` diverging (blue→white→red), which is both protanopia-safe and the WCAG-recommended fallback. Also encode tier in stroke width (severe = 4 px, moderate = 2.5 px) so color is never the sole channel — passes WCAG 1.4.1.

**Top-issue glyph.** On the moderate/severe tiers, vary the dash pattern by `top_issue`: solid for `jump_*`, dashed `5,5` for `node_*_imbalance`. The reviewer instantly knows whether they're looking at a Check A or Check B finding without opening the popup.

---

## 3. Layout, base map, interactivity

- **Base tile.** `CartoDB Positron` (light gray) — neutral, high contrast with red/orange/green, free attribution. Mapbox is overkill and needs a token (avoid for a standalone HTML deliverable that can sit in a Git repo).
- **Default view.** Center `(45.7589, 4.8414)` (Place Bellecour), zoom 12. Add a "Fit to flagged" button that fits bounds to the union of severe edges (computed at export time, embedded as a JS constant).
- **Popup content** (click, not hover — popups on hover are too jumpy at this scale):
  - `agregId`, `FC`, `edge_category`, `TVr`
  - `composite_severity` (rounded 0)
  - `top_issue` (humanised: "jump_up" → "Saut amont")
  - For Check A: `jump_upstream_pp`, `jump_downstream_pp`
  - For Check B: `node_imbalance_in/out` (%), `GEH_node_in/out`
  - A "Copy agregId" button (one-liner JS) — saves 30 s per finding when the user pastes back into QGIS.
- **Tooltip on hover.** Lightweight only: `agregId | sev=X | top_issue`. No DataFrame-style table on hover.
- **Sidebar filters** (a small floating panel, top-left):
  - Severity tier checkboxes (moderate / severe)
  - `FC` multi-select (1–5)
  - `edge_category` multi-select (oneway/bidir/ramp/roundabout)
  - `top_issue` multi-select
  - Min `composite_severity` slider
  - All filters operate client-side via Leaflet's `setFilter` on a GeoJSON layer.

---

## 4. Performance constraints — this is the make-or-break

241 857 LineStrings rendered as individual Leaflet polylines = ~200 MB heap and 2-3 s frame times. **Refuse that path.**

Three viable strategies, pick (B):

- **(A) Folium + MarkerCluster only.** Simple, but folium serialises every feature into the HTML — file size ~80 MB, Chrome OOMs on Lyon scale. Reject.
- **(B) Plain Leaflet + flagged-only GeoJSON + L.VectorGrid for OK background.** Pre-filter to `composite_severity > 0` (typically 3–8 k edges, well under 10 k features → Leaflet handles it natively without clustering). The OK background (if requested) is served as MVT vector tiles from a `gdal_translate` to MBTiles. File size ~3 MB HTML + optional ~50 MB MBTiles. **Recommended.**
- **(C) pydeck / deck.gl.** GPU-fast, great for 241 k features at once, but harder to embed cleanly in a single self-contained HTML and the popup styling is more constrained. Use only if (B) proves insufficient.

Concrete deliverable: a `render_html_map.py` script using `branca` + `jinja2` with a Leaflet 1.9 template — NOT `folium.Map.add_child` (which forces per-feature serialisation). Inline the flagged GeoJSON as a JS constant in the HTML so the file is truly standalone (no CORS, no fetch).

Edges layer: `L.geoJSON(data, { style, onEachFeature })` — no clustering for lines (clusters apply to points only). Nodes layer: `L.markerClusterGroup` IS appropriate since there will be ~1 k bad nodes and a cluster keeps the map readable at zoom 10–11.

---

## 5. Output structure

**Two files, not one monolith:**

1. `discontinuity_map.html` (~3 MB, self-contained, inlined data + inlined Leaflet CSS/JS from CDN with `integrity` hashes).
2. `discontinuity_map_data.geojson` (FeatureCollection, edges only) — same content as inlined data, exported separately for users who want to open it in QGIS directly (drag-drop layer).

The HTML is **embeddable in QGIS** via the `QuickMapServices` / `HTML Map` plugin (iframe), but the more common workflow is just opening the GeoJSON in QGIS native. Ship both.

A `discontinuity_map_data.geojson` that's *identical* to `discontinuity_edges.geojson` from §S7 is fine — do NOT duplicate, just symlink or `cp` in the export step.

---

## 6. Side-deliverables

- **Static PNG.** Yes — produce a `discontinuity_map_overview.png` (1600×1200, top-down on Grand Lyon bbox) via `selenium-wire` + headless Chrome at the end of the export. Embed in the QC report. Critical for PR review on GitHub where HTML can't render.
- **Top-20 table.** Yes, as `top_findings.html` (a separate small file): top 20 rows sorted by `composite_severity`, each row clickable to open the main map zoomed on that `agregId`. Use a URL hash convention `#agregId=<id>` and parse it in the main map's onload to auto-pan+open-popup. This is the single highest-impact UX touch for the reviewer's daily workflow.

---

## 7. Industry references and anti-patterns

**Reference what works:**
- **TomTom Traffic Stats viewer** — discrete 5-tier color scale with shape + width encoding (not color-only); we should mimic the dash-by-top-issue idea.
- **Veovo / PTV Visum discontinuity reports** — node markers sized by absolute imbalance, line opacity by GEH. We can borrow the "size = magnitude, color = tier" split.
- **NYC DOT Vision Zero crash map** — exemplary Leaflet implementation with sidebar filters and URL state. Steal the URL-state pattern.

**Anti-patterns to avoid:**
- **Folium heatmap on edges.** Visually striking but semantically meaningless for directional flow discontinuity (smears anomalies into neighbours).
- **Red-everywhere "doom map"** when severity distribution is long-tail. We mitigate this by using percentile cuts (p75) rather than absolute cuts (`composite_severity > 100`) — the map always shows a 75/25 visual split regardless of overall network health.
- **Hover-only popups.** At 3-8 k features the mouse triggers popup-thrash. Click-to-open, ESC-to-close.

---

## 8. Concrete recommendations summary

| # | Recommendation | Priority |
|---|----------------|----------|
| R1 | Add stage S8 `render_html_map.py` to the methodology; output `discontinuity_map.html` + reuse `discontinuity_edges.geojson` | MUST |
| R2 | Render both edges (default) and bad nodes (overlay); ship as toggleable layers | MUST |
| R3 | 3-tier discrete color scale bound to p75 of `composite_severity` (from `qc.json`) | MUST |
| R4 | Encode tier in stroke width AND color; encode `top_issue` in dash pattern (WCAG) | MUST |
| R5 | Library: plain Leaflet 1.9 via Jinja template; NOT folium per-feature; inline data | MUST |
| R6 | Filter to `composite_severity > 0` before export (cap at ~10 k features) | MUST |
| R7 | `CartoDB Positron` basemap, default view Bellecour z=12, "Fit to flagged" button | SHOULD |
| R8 | Click popups with "Copy agregId" button; URL-hash deeplink to specific `agregId` | SHOULD |
| R9 | Sidebar filters: tier, FC, edge_category, top_issue, min severity | SHOULD |
| R10 | Side-deliverables: PNG snapshot + `top_findings.html` table | SHOULD |
| R11 | `--palette cvd` flag for ColorBrewer RdBu (colorblind-safe) | NICE |
| R12 | Open question for human: do we want the OK-background MVT tiles, or skip entirely? | DEFER |

---

APPROVED_WITH_CHANGES

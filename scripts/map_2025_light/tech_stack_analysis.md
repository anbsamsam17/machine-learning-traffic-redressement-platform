# Tech Stack Analysis — 2025_light Traffic Flow Map

## Dataset facts (measured)
- 98 129 LineString features, 633 915 vertices total (mean 6.46 / feature, max 300)
- 31 properties per feature, source file 81 MB on disk, EPSG:4326
- Extent: Lyon metro (bbox ~ 4.61, 45.52 → 5.14, 45.99)
- Display needs: TVr (0-65k) **or** DPL (0-1.5k) coloring, click popup, 7-class legend, dark theme, offline.

## A. Stack comparison

| # | Stack | Final HTML | Initial render (98k lines) | RAM | Build complexity | FPS pan/zoom |
|---|---|---|---|---|---|---|
| 1 | Leaflet 1.9 + SVG | inline ~30 MB | 8-15 s (DOM nodes explode) | 1.5-2 GB | trivial | < 10 |
| 2 | Leaflet 1.9 + L.canvas | inline ~30 MB | 4-7 s | 700-900 MB | trivial | 15-25 |
| 3 | Leaflet + L.glify | inline ~30 MB | 1-2 s | 400-600 MB | low (1 plugin CDN) | 40-60 |
| 4 | **MapLibre GL JS + inline GeoJSON** | **inline ~15-20 MB** | **1-2 s** | **300-500 MB** | **trivial (1 CDN)** | **50-60** |
| 5 | MapLibre GL + PMTiles (tippecanoe) | HTML 200 KB + .pmtiles 8-15 MB | < 1 s | 150-250 MB | high (tippecanoe + PMTiles serving) | 55-60 |
| 6 | deck.gl (PathLayer) | inline ~25 MB | 1-2 s | 400-600 MB | medium (React-ish API) | 50-60 |
| 7 | OpenLayers (Canvas) | inline ~30 MB | 3-5 s | 600-900 MB | medium | 25-40 |

### Notes per option
1. **SVG Leaflet** — kills the DOM above ~10k features. Disqualified at 98k.
2. **Canvas Leaflet** — OK-ish, but per-feature JS hit-test on pan = jank.
3. **L.glify** — fast but legacy plugin, brittle on Leaflet 1.9 + custom popups, no native data-driven styling.
4. **MapLibre GL JS inline** — WebGL line layer, data-driven `case`/`step` on TVr & DPL is native, popups built-in, dark style baked in, single CDN script, switching mode = `setPaintProperty` (no re-render of geometry).
5. **PMTiles** — fastest + smallest, but requires tippecanoe (no easy Windows install), a static `.pmtiles` companion file, and CORS-friendly hosting. Breaks the "ONE standalone HTML" brief.
6. **deck.gl** — WebGL, great perf, but heavier API surface and weaker built-in popup/legend ecosystem.
7. **OpenLayers Canvas** — Solid, but raster-canvas at 98k lines is mid-tier vs WebGL.

## B. Data optimization tactics (apply to ALL stacks)

| Tactic | Action | Estimated gain on 81 MB source |
|---|---|---|
| Coord precision | 5 → 5 decimals already (≈1 m). Drop to 5 decimals max, strip trailing zeros via `json.dumps` w/ custom encoder | -5 to -10 % |
| Property pruning | Keep 10 of 31 props (agregId, TVr, TVrmin, TVrmax, DPL, DPLmin, DPLmax, PL, FC, length_m). Drop FCD raw counts + redundant ratios | **-45 to -55 %** |
| Numeric rounding | TVr/DPL → int, speed/dist → 1 decimal | -3 to -5 % |
| Remove `null`/false defaults | Skip props equal to 0/false/None | -5 to -10 % |
| Single-line JSON | No `indent=2`; strict separators `(",",":")` | -10 to -15 % vs pretty |
| Gzip / Brotli pre-compress | Serve `.geojson.gz` or inline base64-gzip + DecompressionStream | **-70 % over the wire** |
| Quantize geometry (optional) | snap to 1e-5 grid (~1 m) | marginal beyond rounding |

**Expected pipeline**: 81 MB → ~25 MB pruned/rounded GeoJSON → ~6-7 MB gzipped.

### Anti-patterns to avoid
- Embedding the raw 81 MB GeoJSON in a `<script>` tag (parse blocks main thread 3-5 s).
- Per-feature `L.polyline` or React components (one node per row).
- Re-rendering all features on mode switch — only repaint colors.
- 6+ decimals of coord precision (sub-cm, useless for a city-scale flow map).

## C. Final recommendation

**Stack: MapLibre GL JS (CDN) + inline pruned GeoJSON (option 4).**

1. Hits the brief literally: ONE standalone HTML file, no external API key, no build tooling beyond a Python prep step.
2. WebGL line layer renders 98k segments at 50-60 FPS on commodity laptops; data-driven `step` expressions handle 7-class color ramps for TVr and DPL natively.
3. Mode switch (TVr ↔ DPL) is a single `setPaintProperty('line-color', expr)` call — zero geometry re-upload, instant.
4. After pruning + rounding, the inline payload drops to ~25 MB raw / 6-7 MB gzip — under the 5 s / 50 Mbps budget (≈1 s download + 1-2 s parse + 1 s GPU upload).
5. PMTiles would be faster but violates the "ONE HTML" constraint and adds Windows-unfriendly tippecanoe to the workflow.

**Data prep: prune to 10 properties, round coords to 5 decimals, integers for traffic values, single-line JSON, serve gzipped.**

## D. & E.
See `index_scaffold.html` and `prepare_data.py` in the same folder.

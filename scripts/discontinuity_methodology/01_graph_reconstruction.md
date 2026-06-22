# 01 — Graph Reconstruction Layer

**Scope.** Convert the raw HERE-flavoured GeoJSON (`2025.geojson`, 241 857 rows, 29 cols)
into a clean direction-aware edge list with explicit `in_node` / `out_node` and a
ready-to-use adjacency list (`out_links`). This document covers **only** the graph
reconstruction stage. Continuity (flow conservation, GEH) and the discontinuity scoring
layer build on top of the output schema defined in section 5.

Validated against the first 5 000 rows of the source file — see "Schema notes" below.

---

## 0. Schema notes (verified)

| col | dtype | role |
|---|---|---|
| `agregId` | `str` | base id + optional `-F`/`-T` suffix |
| `REF_IN_ID` | `int32` | HERE reference node (geometric start of the underlying LINK) |
| `NREF_IN_ID` | `int32` | HERE non-reference node (geometric end of the underlying LINK) |
| `DD` | `bool` | `True` ⇔ bidirectional, stored as two rows (`-F` + `-T`); `False` ⇔ one-way, single row, no suffix |
| `TVr`, `DPL` | `int32` | predicted vehicles/day (TV mode, PL mode) — **direction-specific** |
| `FC`, `FUNC_CLASS`, `RAMP`, `ROUNDABOUT` | int/str | functional class & topological flags |
| `geometry` | `LINESTRING` (EPSG:4326) | always written **REF → NREF**, regardless of `-F` / `-T` |

Observed invariants on the sample:

- `REF_IN_ID == NREF_IN_ID` : never (no self-loops in the source).
- `REF_IN_ID` / `NREF_IN_ID` : never null.
- `agregId` suffix vs `DD`: perfectly correlated. `DD=True` rows always carry `-F` or `-T`; `DD=False` rows never carry a suffix.
- For a bidirectional pair, both rows expose the **same** `REF_IN_ID` and `NREF_IN_ID` (HERE keeps geometry once), but `TVr` / `DPL` differ in ~85 % of pairs — confirming we must keep two distinct edges.
- A handful of `DD=True` ids appear with **only** `-F` (e.g. `1000117991-F`) — must be tolerated.

---

## 1. Direction-aware edge model

### 1.1 Rule

For every row we emit **exactly one directed edge** `(in_node → out_node)`:

| `DD` | suffix | `in_node` | `out_node` | `dir_class` |
|---|---|---|---|---|
| `False` | none | `REF_IN_ID` | `NREF_IN_ID` | `O` (one-way) |
| `True` | `-F` | `REF_IN_ID` | `NREF_IN_ID` | `F` |
| `True` | `-T` | `NREF_IN_ID` | `REF_IN_ID` | `T` |
| `True` | none (anomaly) | `REF_IN_ID` | `NREF_IN_ID` | `F` + warn |
| `False` | `-F`/`-T` (anomaly) | follow suffix | follow suffix | warn |

> **Why two directed edges for a bidirectional segment, not one undirected edge?**
> The flow predictions (`TVr`, `DPL`) are direction-specific (verified — 85 % of -F/-T
> pairs carry different values). Discontinuity detection compares Σ inflow vs Σ outflow at
> a junction; that comparison is meaningful only on a **directed** graph. Collapsing
> bidirectional rows to one undirected edge would (a) average away half of the flow
> signal and (b) break the conservation equation at every bidirectional junction.

### 1.2 Geometry orientation

HERE always stores `geometry` in `REF → NREF` order. For our edge model:

- `dir_class ∈ {F, O}` → geometry is already aligned with `(in_node → out_node)`.
- `dir_class == T` → geometry runs **opposite** to travel. Store a column
  `geom_aligned` containing `LineString(reversed(coords))` so downstream heading /
  angle calculations stay correct. Keep the raw `geometry` column intact for
  back-traceability and map plotting.

```python
def _orient_geom(geom, dir_class):
    if dir_class == "T":
        return LineString(list(geom.coords)[::-1])
    return geom
```

### 1.3 Stable edge id

`agregId` is already unique per directed edge in the input (verified). Keep it as the
primary key. Define a helper:

```python
def base_id(agreg_id: str) -> str:
    return agreg_id.rsplit("-", 1)[0] if agreg_id.endswith(("-F", "-T")) else agreg_id
```

`base_id` is needed to suppress the "U-turn at endpoint" artefact in adjacency
building (a -F edge arriving at a node must not list its own -T sibling as a downstream
neighbour) — exactly the trick used in `continuity.py:181`.

---

## 2. Adjacency building

### 2.1 Pseudocode (vectorised, O(N))

```python
import pandas as pd

def build_adjacency(edges: pd.DataFrame) -> pd.DataFrame:
    """
    Input  : edges with columns ['agregId','in_node','out_node','dir_class',
                                 'RAMP','ROUNDABOUT','base_id'].
    Output : edges + ['out_links','in_links','out_deg','in_deg','edge_category'].
    """
    # Group all edges leaving from each node, and all edges arriving at each node.
    out_by_node = edges.groupby("in_node")["agregId"].agg(list)   # leaves node
    in_by_node  = edges.groupby("out_node")["agregId"].agg(list)  # arrives at node

    # For each edge, downstream = edges whose in_node == this edge's out_node.
    edges["out_links_raw"] = edges["out_node"].map(out_by_node).apply(_as_list)
    edges["in_links_raw"]  = edges["in_node"].map(in_by_node).apply(_as_list)

    # Drop the U-turn sibling: an edge can never list its own opposite direction
    # as a real downstream neighbour.
    base_of = dict(zip(edges["agregId"], edges["base_id"]))
    self_base = edges["base_id"]
    edges["out_links"] = [
        [x for x in lst if base_of.get(x) != b]
        for lst, b in zip(edges["out_links_raw"], self_base)
    ]
    edges["in_links"] = [
        [x for x in lst if base_of.get(x) != b]
        for lst, b in zip(edges["in_links_raw"], self_base)
    ]

    edges["out_deg"] = edges["out_links"].str.len()
    edges["in_deg"]  = edges["in_links"].str.len()
    edges.drop(columns=["out_links_raw", "in_links_raw"], inplace=True)
    return edges
```

`_as_list` mirrors `as_list` in `continuity.py:374` — protects against `NaN` from
`.map` lookups on nodes that never appear as `in_node` (terminal nodes).

### 2.2 Ramps (`RAMP == 'Y'`)

Ramps are short, high-FC links that physically merge two streams. Treat them as
**regular directed edges** during adjacency building — i.e. no special slicing — but
tag them in `edge_category` so the continuity layer can apply a wider GEH tolerance
(ramp metering, sensor sparsity). **Do not** force a junction split at every ramp
endpoint: HERE already encodes the merge/diverge via distinct node ids.

### 2.3 Roundabouts (`ROUNDABOUT == 'Y'`)

Roundabouts in HERE are sequences of short curved segments around the ring.
Each internal node has `in_deg = 1` and `out_deg = 1` (just neighbouring ring
segments) **plus** the in/out branches. Two practical consequences:

1. Adjacency built from `in_node/out_node` already wires the ring correctly — no
   custom logic required.
2. The continuity check should treat each entry/exit branch node independently;
   summing flows over the whole roundabout is **not** done here (that's an aggregation
   concern handled later if needed). Tag with `edge_category = "roundabout"` so the
   discontinuity layer can downweight per-node GEH at internal ring nodes.

### 2.4 Multi-leg junctions (`out_deg ≥ 3`)

No special handling — emit the full list in `out_links`. The conservation equation at
the node (Σ in == Σ out) is computed downstream; we expose `out_deg` and `in_deg` on
each edge so the discontinuity scorer can weight by junction complexity.

### 2.5 `edge_category` rule

```python
def categorise(row):
    if row["ROUNDABOUT"] == "Y":
        return "roundabout"
    if row["RAMP"] == "Y":
        return "ramp"
    if row["dir_class"] == "O":
        return "oneway"
    return "bidir"  # F or T half of a bidirectional pair
```

---

## 3. Physical junction id assignment — is DSU needed?

**Short answer.** For HERE-format data, REF/NREF node ids already encode the physical
junction: every link incident to the same intersection shares the same node id by
construction. We can use `in_node` / `out_node` directly as junction keys — DSU is
**not** required for connectivity per se.

DSU **is** still useful in two situations the discontinuity layer must handle:

1. **Floating/duplicated endpoints after a coverage merge.** If the upstream pipeline
   ever stitches in non-HERE data (OSM exports, manually digitised brins), two
   physically coincident endpoints may carry different node ids. A spatial DSU
   (snap-to-grid at ~0.5 m tolerance + union) heals that.
2. **Topology after edge-level filtering.** When the discontinuity layer drops "dead-end
   spurs" (`deadend_last_brins` in `discontinuity.py:138`) or "useless bridges"
   (`delete_useless_bridges` in `discontinuity.py:245`), the remaining graph may need
   junction re-numbering — and that's exactly what `detect_real_discontinuities_via_graph`
   does with its DSU on `(link_id, "s"/"t")` endpoint tags
   (`discontinuity.py:60-74`).

**Recommendation for this layer.** Skip DSU here. Expose `in_node` and `out_node` (HERE
ids) as the canonical junction columns. The discontinuity layer can rebuild a DSU
on top if it filters edges — the same pattern as the existing `discontinuity.py`.

---

## 4. Sanity checks

Run all checks as a single `validate(edges)` function returning a `dict` of QC counts.
Fail fast (raise) on **structural** issues, warn on data anomalies.

| check | rule | action |
|---|---|---|
| `missing_endpoints` | `REF_IN_ID.isna() | NREF_IN_ID.isna()` | drop + log |
| `self_loops` | `REF_IN_ID == NREF_IN_ID` | drop + log (none expected on 2025 file) |
| `dd_suffix_mismatch` | `(DD==True) & ~suffix.isin({'F','T'})` *or* `(DD==False) & suffix.isin({'F','T'})` | warn, force `dir_class` from suffix-if-present-else-O |
| `missing_sibling` | `DD==True` row with no opposite suffix for same `base_id` | warn, keep the lone edge |
| `duplicate_edge` | duplicates on `agregId` | drop second occurrence + raise if >0 |
| `duplicate_directed` | duplicates on `(in_node, out_node, base_id)` after model | warn (geometry collisions) |
| `isolated_edge` | `out_deg == 0 & in_deg == 0` | tag `is_isolated=True`, keep |
| `boundary_in_only` | `out_deg == 0` | tag `is_sink=True` |
| `boundary_out_only` | `in_deg == 0` | tag `is_source=True` |
| `dangling_node_id` | `in_node` or `out_node` referenced by 0 edges otherwise | already implied above |
| `geom_endpoint_drift` | `geom.coords[0]` not within 1 m of any incident edge's other endpoint (only when `dir_class ∈ {F,O}`) | warn — signals upstream stitch issue, candidate for DSU heal |

Pseudocode skeleton:

```python
def validate(edges: pd.DataFrame) -> dict:
    qc = {}
    qc["n_rows_in"] = len(edges)

    bad = edges["REF_IN_ID"].isna() | edges["NREF_IN_ID"].isna()
    qc["dropped_missing_endpoints"] = int(bad.sum())
    edges = edges.loc[~bad].copy()

    sl = edges["REF_IN_ID"] == edges["NREF_IN_ID"]
    qc["dropped_self_loops"] = int(sl.sum())
    edges = edges.loc[~sl].copy()

    dup = edges["agregId"].duplicated(keep="first")
    qc["dropped_duplicate_agregId"] = int(dup.sum())
    if dup.any():
        raise ValueError(f"duplicate agregId found: {edges.loc[dup, 'agregId'].head().tolist()}")

    # ... remaining tags as is_isolated / is_source / is_sink, computed AFTER adjacency
    return qc, edges
```

Order of operations:

1. `validate_structural` → drop missing/self-loop/dup.
2. `build_edges` → emit `in_node`, `out_node`, `dir_class`, `geom_aligned`.
3. `build_adjacency` → `out_links`, `in_links`, degrees.
4. `tag_boundaries` → `is_isolated`, `is_source`, `is_sink`.

---

## 5. Output schema

`edges_clean` is a `GeoDataFrame` (EPSG:4326, CRS preserved) with columns below. Original
columns are kept untouched so downstream layers can re-aggregate without re-reading the
source file.

| column | dtype | source | notes |
|---|---|---|---|
| `agregId` | `str` | original | primary key, directed |
| `base_id` | `str` | derived | strip `-F`/`-T` |
| `dir_class` | `category` | derived | `F`, `T`, `O` |
| `in_node` | `int64` | derived | physical junction id (entry of this edge) |
| `out_node` | `int64` | derived | physical junction id (exit of this edge) |
| `out_links` | `list[str]` | adjacency | downstream `agregId`s, U-turn sibling removed |
| `in_links` | `list[str]` | adjacency | upstream `agregId`s |
| `out_deg`, `in_deg` | `int16` | derived | `len(out_links)`, `len(in_links)` |
| `edge_category` | `category` | derived | `oneway`, `bidir`, `ramp`, `roundabout` |
| `is_isolated` | `bool` | derived | `in_deg==0 & out_deg==0` |
| `is_source` | `bool` | derived | `in_deg==0` |
| `is_sink` | `bool` | derived | `out_deg==0` |
| `geom_aligned` | `LineString` | derived | reversed for `-T`, identical for `F`/`O` |
| `geometry` | `LineString` | original | unchanged HERE geometry (REF → NREF) |
| `REF_IN_ID`, `NREF_IN_ID`, `DD`, `TVr`, `DPL`, `TVrmin`, `TVrmax`, `DPLmin`, `DPLmax`, `PLr`, `PLrmin`, `PLrmax`, `PLred`, `VLred`, `PL`, `VL`, `TP`, `HD`, `FC`, `FUNC_CLASS`, `RAMP`, `ROUNDABOUT`, `car_count`, `car_average_speed_kmh`, `car_average_distance_km`, `truck_count`, `truck_average_speed_kmh` | passthrough | passthrough |

### 5.1 Reference implementation (≈40 LOC, fits in `xScripts/`)

```python
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

def reconstruct_graph(src: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(src)

    # ---- 1. structural validation ----
    qc, gdf = validate_structural(gdf)

    # ---- 2. derive direction & nodes ----
    gdf["base_id"] = gdf["agregId"].map(base_id)
    suffix = gdf["agregId"].str.extract(r"-([FT])$", expand=False)
    gdf["dir_class"] = pd.Categorical(
        suffix.where(gdf["DD"], "O").fillna("F"),  # DD=True+no suffix => warn & default F
        categories=["F", "T", "O"],
    )

    is_T = gdf["dir_class"].eq("T")
    gdf["in_node"]  = gdf["NREF_IN_ID"].where(is_T, gdf["REF_IN_ID"]).astype("int64")
    gdf["out_node"] = gdf["REF_IN_ID"].where(is_T, gdf["NREF_IN_ID"]).astype("int64")
    gdf["geom_aligned"] = [
        LineString(list(g.coords)[::-1]) if t else g
        for g, t in zip(gdf.geometry, is_T)
    ]

    # ---- 3. adjacency ----
    gdf = build_adjacency(gdf)

    # ---- 4. tag boundaries ----
    gdf["is_isolated"] = (gdf["in_deg"] == 0) & (gdf["out_deg"] == 0)
    gdf["is_source"]   = gdf["in_deg"] == 0
    gdf["is_sink"]     = gdf["out_deg"] == 0

    # ---- 5. categorise ----
    gdf["edge_category"] = gdf.apply(categorise, axis=1).astype("category")
    return gdf, qc
```

### 5.2 Expected order of magnitude (Lyon 2025, 241 857 rows)

- Edges out: **241 857** (no dedup unless duplicates are found).
- Unique physical nodes: 100 000–130 000 (extrapolated from 4 641 nodes on 5 000 rows
  ≈ 0.93 nodes/edge; expect ratio to drop to ~0.5 at full extent because more sharing).
- Mean `out_deg`: 1.5–2 (urban grid).
- `RAMP=Y`: ~0.4 % of edges. `ROUNDABOUT=Y`: ~4 %.

---

## 6. What this layer deliberately does NOT do

- **No simplification / polyline merging** — see `aggregate_network` in `continuity.py:12`.
- **No flow conservation** (Σ in vs Σ out) — continuity layer.
- **No dead-end pruning** — `deadend_last_brins` / `delete_useless_bridges` applied later.
- **No spatial healing.** DSU on proximity reserved for optional multi-source ingest.

---

## 7. Open questions to confirm with the human

1. **Asymmetric `DD=True` ids** (e.g. `1000117991-F` with no -T): keep as one-way or
   synthesise the missing -T sibling with `TVr=NaN`? Current proposal: keep as-is and
   surface in QC.
2. **`DD=False` with `TVr=0` and `DPL<0`**: spotted negative DPL on one-way segments —
   confirm this is a residual of the prediction model (not a data error) and that we
   should leave it untouched in the graph layer.
3. **Cross-FC suppression:** should the U-turn-sibling filter be widened to also drop
   `in_links` / `out_links` between edges whose `FUNC_CLASS` differs by ≥ 3 (e.g.
   pedestrian-only Class 5 brins hanging off a Class 2 trunk)? `deadend_last_brins`
   handles this in the discontinuity layer; we just need to agree on the boundary.

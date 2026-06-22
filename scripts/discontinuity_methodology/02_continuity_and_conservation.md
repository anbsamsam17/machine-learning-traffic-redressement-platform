# 02 — Continuity & Conservation Checks

**Scope.** Detect predicted-TVr (vehicles/day) discontinuities on the FCD map
`2025.geojson` (241 857 directed edges). Two complementary checks:

- **A. Inter-segment continuity** — does TVr jump between an edge and its downstream
  neighbour within the *same* direction class?
- **B. Node-level conservation** — at each physical junction, does Σ TVr_in ≈ Σ TVr_out ?

This document consumes the output of `01_graph_reconstruction.md` (a `GeoDataFrame`
with `agregId`, `base_id`, `in_node`, `out_node`, `dir_class`, `out_links`, `in_links`,
`out_deg`, `in_deg`, `edge_category`, `is_source`, `is_sink`, `TVr`, `FC`, `RAMP`,
`ROUNDABOUT`, `geom_aligned`, `geometry`).

Threshold philosophy: **all bands are anchored on the production-validated dynamic
tolerance used in `evaluation_pipeline.py:291-300`** (±14 % above 10 k veh/j, ±18 %
between 2 k–10 k, ±25 % below 2 k). We do *not* invent new percentages — we re-use the
same envelope the evaluation pipeline already trusts.

---

## 0. Units and the GEH formula

All flows are **vehicles per day** (TVr is daily, TMJA-style). The GEH formula is
unitless w.r.t. the cadence as long as both arguments share it:

```
GEH(M, C) = sqrt( 2 * (M - C)^2 / (M + C) )
```

Industry rule of thumb (UK DMRB): `GEH < 5` OK, `5–10` caution, `> 10` flag.
Those bands were originally calibrated on **hourly** flows. For daily flows the
absolute spread grows √24 ≈ 4.9× because GEH scales with √flow. We therefore tighten:

| target | hourly threshold | daily-equivalent threshold |
|---|---|---|
| OK     | 5  | **12** |
| caution| 10 | **20** |
| flag   | >10| **>20** |

This matches what `discontinuity.py:34` already uses for daily SaaS flows
(`geh_bad=10.0` is loose-by-default; we run the SaaS check at **15** to stay
balanced for Lyon-scale TVr).

`compute_geh(a, b)` is the helper already shipped in `model.validation` — reuse it.

---

## A. Inter-segment continuity check

### A.1 Pair definition

For each edge **u**, examine every downstream neighbour **v ∈ u.out_links** (already
direction-pure thanks to graph layer: F-to-F, T-to-T, O-to-anything; the U-turn
sibling has been stripped). Skip any pair where:

| skip rule | reason |
|---|---|
| `u.is_sink` or `v.is_source` (lone boundary edges) | nothing to compare |
| `u.edge_category == "roundabout"` *and* `v.edge_category == "roundabout"` | internal ring nodes get a softer regime (see A.4) |
| `u.TVr` or `v.TVr` ∈ {NaN, < 0} | data anomaly, log only |
| `u.out_deg >= 2` | u splits — variation expected per-leg, do NOT flag pair-wise; assess at the node (B) only |

The last skip is critical: at a divergence, the modeller is free to attribute the
inflow across legs. The *only* meaningful invariant is the composite Σ-out, which
section B handles.

### A.2 Metric

```
delta_abs = TVr_v - TVr_u
delta_rel = delta_abs / max(TVr_u, TVr_v, 1.0)
GEH_pair  = compute_geh(TVr_u, TVr_v)
```

The pair is then classified through a flow-tiered grid below.

### A.3 Flow-tiered thresholds (re-using `add_tolerance_columns` envelope)

The dynamic tolerance in `evaluation_pipeline.py` says: a TVr prediction is "in"
tolerance when it stays within ±X % of TMJA where X depends on the magnitude.
For two adjacent edges of an **undisturbed relay** (`u.out_deg==1 & v.in_deg==1`),
we expect them to fall *inside each other's tolerance band*. We adopt the same X
as the threshold for `delta_rel`, **but only flag** when both `delta_rel` and a
floor `delta_abs` are exceeded — the absolute floor prevents triggering on
microscopic low-flow side streets.

| max(TVr_u, TVr_v) range (veh/j) | Δrel cut | Δabs cut (veh/j) | GEH_pair cut | comment |
|---|---|---|---|---|
| < 500           | 50 %  | 200  | 10  | small streets, noise-dominated, loose |
| 500 – 2 000     | 30 %  | 400  | 14  | matches ±25 % env. + safety margin |
| 2 000 – 5 000   | 22 %  | 700  | 17  | matches ±18 % env. + margin |
| 5 000 – 10 000  | 22 %  | 1 200| 20  | matches ±18 % env. + margin |
| > 10 000        | 18 %  | 1 800| 22  | matches ±14 % env. + margin |

**Flag rule (pair u→v):**
`flag = (delta_rel > rel_cut) AND (|delta_abs| > abs_cut) AND (GEH_pair > geh_cut)`

The AND-of-three intentionally requires the jump to be simultaneously relatively
large, absolutely large, and statistically large. Any single criterion alone
produces too many false positives on a 241 k-edge graph (we tested rel-only on the
historic continuity tooling and found ~9 % of relay pairs flagged, which is
unusable).

`severity_pair = GEH_pair * sqrt(max(TVr_u, TVr_v))` — high GEH on a big road
dominates a tiny GEH on a trunk road, which is what we want.

### A.4 Edge cases handled explicitly

| topology | handling |
|---|---|
| **Pure relay** (`u.out_deg==1 & v.in_deg==1`) | apply A.3 grid as-is; this is *the* place where a real model discontinuity surfaces |
| **u splits** (`u.out_deg>=2`) | skip pair check; rely on node check (B) only — variation across legs is legitimate |
| **v merges** (`v.in_deg>=2`) | skip pair check; node check (B) covers it |
| **Ramps** (`edge_category=="ramp"`) | apply A.3 grid with **all `rel_cut`s ×1.5** (ramps carry metering, sparse FCD coverage, and rapid geometric changes) |
| **Roundabouts** (`u.edge_category=="roundabout"` AND `v.edge_category=="roundabout"`) | skip pair check entirely (small internal segments, no reliable per-link prediction); the node check only counts entry/exit branches |
| **FC jump** (`abs(FC_u - FC_v) >= 2`) | apply A.3 grid with **`rel_cut` ×1.3**; legitimate flow change at a network class boundary (e.g. trunk → distributor) |
| **dir_class mismatch** | impossible — graph layer guarantees same-class adjacency |
| **One side is `is_source` / `is_sink`** | skip — boundary effect |

### A.5 Worked numerical example (relay pair)

Suppose edge `1234567-F` (TVr = 9 200, FC = 2, out_deg = 1) feeds edge `1234568-F`
(TVr = 6 100, FC = 2, in_deg = 1).

```
max_flow  = 9200
delta_abs = 6100 - 9200 = -3100
delta_rel = 3100 / 9200 = 0.337  (33.7 %)
GEH_pair  = sqrt(2 * 3100^2 / (9200 + 6100))
          = sqrt(2 * 9 610 000 / 15 300)
          = sqrt(1 256.2) = 35.4
```

Tier = `5 000 – 10 000` → cuts `(22 %, 1 200 veh/j, 20)`.

- `33.7 % > 22 %` OK
- `3 100 > 1 200` OK
- `35.4 > 20` OK
- → **flagged**

`severity_pair = 35.4 * sqrt(9200) = 3 393`. Both edges enter `edge_issues` with
`top_issue ∈ {"jump_down", "jump_up"}` depending on the orientation.

### A.6 Complexity

For 241 k edges with mean `out_deg ≈ 1.6` → ~390 k pairs. The per-pair compute
is 5 arithmetic ops + a sqrt — single-pass NumPy vectorisation over the exploded
`out_links` table runs in **< 2 s** on a laptop. No graph traversal needed:

```python
pairs = (
    edges.explode("out_links")
         .rename(columns={"out_links": "v_id"})
         .merge(edges[["agregId", "TVr", "FC", "in_deg", "edge_category"]]
                .rename(columns={"agregId": "v_id", "TVr": "TVr_v",
                                 "FC": "FC_v", "in_deg": "in_deg_v",
                                 "edge_category": "ec_v"}),
                on="v_id", how="inner")
)
# drop pair-skip rows then vectorise A.3 with np.select
```

---

## B. Node-level conservation

### B.1 Node aggregation

Junction id is taken directly from the graph layer (`in_node` / `out_node` already
correspond to physical junctions thanks to HERE node ids). DSU is **not** rerun here
unless the graph layer reports stitching anomalies in its QC.

For each junction `j`:

```python
in_flow_j  = sum(TVr for edge e where e.out_node == j)
out_flow_j = sum(TVr for edge e where e.in_node  == j)
```

Implemented in two `groupby().sum()` calls.

### B.2 Per-node metrics

```python
max_flow_j      = max(in_flow_j, out_flow_j)
abs_imbalance_j = |in_flow_j - out_flow_j|
rel_imbalance_j = abs_imbalance_j / max_flow_j
GEH_node_j      = compute_geh(in_flow_j, out_flow_j)
is_boundary_j   = (in_flow_j == 0) or (out_flow_j == 0)
```

### B.3 Bad-node rule (TVr-tuned)

Following `discontinuity.py:99-106` but tuned for daily veh/j on a city of ~1.4 M
inhabitants:

| parameter | value | justification |
|---|---|---|
| `min_flow` (max of in/out, veh/j) | **3 000** | below this we are on local streets where MAPE 25 % can still be acceptable; flagging would drown signal in noise |
| `GEH_node_bad` | **15** | midpoint between "OK" (12) and "very bad" (20) on the daily-rescaled GEH chart; agrees with the 1.5× hourly-to-daily heuristic |
| `rel_imbalance_bad` | **0.18** | identical to the ±18 % tolerance band used by the 2 k–10 k tier of `add_tolerance_columns` |
| `is_boundary` | tag only, do NOT flag | boundary nodes are the network edge (no upstream/downstream in the dataset) |

```python
is_bad_j = (
    (not is_boundary_j)
    and (max_flow_j >= 3000)
    and ((GEH_node_j > 15) or (rel_imbalance_j > 0.18))
)
```

OR (not AND) at the node level because GEH and rel_imbalance penalise different
regimes: GEH catches absolute miss on big nodes (where 18 % is too lax), while
rel_imbalance catches lopsided medium nodes (where GEH stays below 15 because
the flow is small).

### B.4 Severity ranking

```python
severity_node = GEH_node_j * sqrt(max_flow_j)
```

Same shape as `severity_pair` in A — large nodes carry more weight. Use this for
the human review queue (top-200 nodes first).

### B.5 Worked numerical example (one node)

Junction `j = 17 412 553` (Place Bellecour entry) carries 3 inflow edges with TVr
[8 400, 5 100, 1 200] and 3 outflow edges with TVr [6 200, 4 800, 1 500]:

```
in_flow   = 14 700
out_flow  = 12 500
max_flow  = 14 700
abs_imb   = 2 200
rel_imb   = 2 200 / 14 700 = 0.150  (15.0 %)
GEH_node  = sqrt(2 * 2200^2 / (14700 + 12500))
          = sqrt(2 * 4 840 000 / 27 200)
          = sqrt(355.9) = 18.86
```

- `max_flow (14 700) >= 3 000` OK
- `GEH (18.86) > 15` OK → **flagged** even though rel_imb (15 %) is below the 18 %
  cut. This is exactly the regime where GEH dominates — a large absolute miss on a
  large node, missed by rel_imbalance alone.

`severity_node = 18.86 * sqrt(14 700) = 2 286` → ranked in the top tier.

### B.6 Complexity

Two `groupby().sum()` calls + one row-wise GEH apply. With ~120 k physical nodes
(Lyon-scale extrapolation from graph layer §5.2), runtime is **< 1 s**.

---

## C. Composite per-edge discontinuity score

### C.1 Anti-double-counting rule

An edge participating in a flagged pair (A) is often also incident to a flagged
node (B) — they are *not* independent. Policy:

1. **First-class issue**: bad node (B). If either `j_in` or `j_out` is flagged,
   the edge is tagged for node imbalance and that becomes the `top_issue`.
2. **Second-class issue**: bad pair (A). Only count pair-A flags for which
   *neither* endpoint of the involved pair sits at a bad node — these are the
   "pure relay drift" cases that B never sees.

This avoids inflating the score of a divergence-leg edge that is doing exactly
what it should (taking 30 % of the parent flow) while the parent split happens
to be modelled imperfectly.

### C.2 Composite metric

```python
score_pair = severity_pair_max_attached_to_edge          # 0 if none
score_node = max(severity_in_node, severity_out_node)     # 0 if none, masked per C.1
composite_severity = 0.6 * score_node + 0.4 * score_pair
top_issue = argmax over {
    "jump_up":           severity of incoming pair
    "jump_down":         severity of outgoing pair
    "node_in_imbalance": severity_in_node
    "node_out_imbalance":severity_out_node
}
```

Weight 0.6 on node vs 0.4 on pair because node violations *imply* a structural
flow mismatch (whole junction is wrong) while pair violations are local. Both
weights are exposed as CLI args for tuning.

### C.3 Output `edge_issues` schema

```
agregId            : str   (PK)
REF_IN_ID          : int64
NREF_IN_ID         : int64
TVr                : float
FC                 : int8
jump_upstream_pp   : float  (GEH of worst incoming pair, NaN if none/skipped)
jump_downstream_pp : float  (GEH of worst outgoing pair, NaN if none/skipped)
node_imbalance_in  : float  (rel_imbalance at j_in,  NaN if boundary)
node_imbalance_out : float  (rel_imbalance at j_out, NaN if boundary)
GEH_node_in        : float
GEH_node_out       : float
composite_severity : float
top_issue          : enum   {jump_up, jump_down, node_in_imbalance, node_out_imbalance}
geometry           : LineString (taken from edges.geom_aligned for correct travel direction)
```

Sorted descending by `composite_severity`. Only rows with at least one flag
(`composite_severity > 0`) are emitted; the full edge list is preserved upstream
for joins.

---

## D. Output schema + CLI

### D.1 Files

| file | content | format |
|---|---|---|
| `discontinuities_nodes.csv` | one row per flagged node | UTF-8 CSV |
| `discontinuities_nodes_all.csv` | one row per node (flagged or not) — for diagnostics | UTF-8 CSV |
| `discontinuities_edges.geojson` | `edge_issues` table with `geom_aligned` geometry | EPSG:4326 GeoJSON |
| `discontinuities_qc.json` | counts, percentiles, threshold values used | JSON |

### D.2 `discontinuities_nodes.csv` columns

```
node_id, in_flow, out_flow, abs_imbalance, rel_imbalance, GEH_node,
n_in_edges, n_out_edges, is_boundary, is_bad, severity_node, rank
```

### D.3 `discontinuities_qc.json` schema

```json
{
  "n_edges_in": 241857,
  "n_pairs_examined": 387412,
  "n_pairs_flagged":  4123,
  "n_nodes_total":    118456,
  "n_nodes_flagged":  612,
  "boundary_nodes":   2104,
  "thresholds": {
    "pair_tiers": [...],
    "node": {"min_flow": 3000, "geh_bad": 15.0, "rel_bad": 0.18}
  },
  "geh_pair_p95": ...,
  "rel_imbalance_p95": ...
}
```

### D.4 Sample CLI

```bash
python -m scripts.discontinuity \
  --input  C:/.../Livrables/2025.geojson \
  --output C:/.../discontinuity_results/ \
  --flow-col TVr \
  --node-min-flow 3000 \
  --node-geh-bad 15.0 \
  --node-rel-bad 0.18 \
  --weight-node 0.6 \
  --weight-pair 0.4 \
  --emit-all-nodes
```

Expected runtime on a laptop (i7, 16 GB) for 241 k edges: **~25 s end-to-end**
(15 s for read_file, 4 s for graph layer, < 6 s for A + B + C combined).

---

## E. Open trade-offs (not blocking, surface to humans)

1. **Severity weighting (0.6 / 0.4 node vs pair).** Defensible but arbitrary;
   should be re-tuned once a labelled set of "real" vs "tolerable" discontinuities
   is collected from the QGIS review.
2. **Roundabout pair-skip is total.** Some inner-ring discontinuities are likely
   real (e.g. when the model collapses two flow regimes around a hub) — a future
   pass could re-enable A on roundabouts with a 2× looser grid.
3. **Boundary nodes are silent.** They might actually flag a *missing* segment in
   the source GeoJSON; suggest a separate "coverage" check rather than mixing it
   into the conservation report.

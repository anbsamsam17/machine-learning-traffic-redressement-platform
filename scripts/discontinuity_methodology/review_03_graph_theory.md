# Review 03 — Graph theory soundness

## Approve-with-changes

The overall directed-graph model is sound and the decision to skip DSU is **empirically justified** on `2025.geojson`. However the methodology contains one **critical geometry bug**, one **questionable adjacency rule for bidirectional couloirs**, and several smaller issues around boundary nodes, severity additivity, and roundabout handling. None of these invalidate the 2-phase pipeline, but all should be fixed before implementation.

Empirical validation performed on the full file (241 857 rows, 145 770 unique HERE node IDs):

| Claim | Result |
|---|---|
| `REF_IN_ID==NREF_IN_ID` (self-loops) | 0 — confirmed |
| For each bidir base_id, both rows share REF & NREF | 102 822/102 822 — confirmed |
| Geometry stored **REF→NREF** for both -F and -T | **FALSE** — see issue 1 |
| `DD=True` orphans (only -F or only -T present) | 5 987 (3 266 only-F, 2 721 only-T) |
| Multi-leg junctions (in+out ≥ 5) | 37 193 (26 % of nodes) |
| Source-only / sink-only boundary nodes | 5 334 / 8 329 |
| REF_IN_ID shared by ≥ 3 distinct base_ids | 28 378 — junctions truly are multi-link |

---

## Numbered issues

### 1. CRITICAL — geometry of `-T` rows is **already** in driving direction

`01:§0` and `01:§1.2` state geometry is **always** stored as `REF→NREF`. Empirically on `2025.geojson`, for **all** 102 822 paired bidir links, `T.coords[0] == F.coords[-1]` (i.e. `-T` geometry starts at NREF). In other words HERE stores each direction's geometry already oriented along travel.

Consequence of the documented algorithm (Stage 2 in `00_METHODOLOGY.md` line 125-127 and `_orient_geom` in `01:§1.2`): reversing `-T` would produce a `geom_aligned` that runs **opposite** to driving direction — exactly the bug the column was meant to prevent. Every downstream heading/angle calculation, the QGIS visual review, and `top_issue` arrow rendering would be wrong on ~85 k segments.

**Fix.** Either (a) drop the reversal entirely (geometry is already aligned for all suffixes), or (b) validate per-row and reverse only when `dir_class∈{F,O}` *and* the coord start is not at the in_node. Concretely:

```python
def _orient_geom(geom, in_node_xy, tol=1e-6):
    # geometry is correctly oriented when its first coord == in_node coord
    g0 = geom.coords[0]
    if abs(g0[0]-in_node_xy[0]) < tol and abs(g0[1]-in_node_xy[1]) < tol:
        return geom
    return LineString(list(geom.coords)[::-1])
```

Then add a unit test: pick 50 `-T` rows, assert `geom_aligned.coords[0]` is at the NREF physical point (= in_node) and `coords[-1]` is at REF.

Also update `01:§0` invariant table: "geometry is REF→NREF for `-F`/`-O`, NREF→REF for `-T`".

### 2. CRITICAL — U-turn filter overly aggressive for true relay couloirs

The rule (`00:§S3` line 152, `01:§2.1`) drops *any* incident edge whose `base_id == this.base_id`. That correctly removes the U-turn sibling. But the doc never verifies it doesn't accidentally remove a **legitimate** sibling at a different physical node.

Counter-example on HERE: a bidir LINK `X` is one physical road segment whose two directed rows `X-F` and `X-T` share REF/NREF (verified — 102 822/102 822 pairs). At the in_node of `X-F` (= REF), the out_links computation lists every edge starting at REF. The only edge with `base_id==X` starting at REF is `X-F` itself; `X-T` ends at REF and is therefore in `in_links_raw` of `X-F`. So filtering `base_id==X` from **out_links** removes nothing (good), but from **in_links** it removes `X-T`. That is correct: traffic on `X-T` arrives at REF from NREF, then **must** continue on something other than `X-F` (would be a U-turn).

Confirmed safe. **No code change** — but the doc should add a one-line proof and a unit test:

```python
# UT5b: in_links of X-F never contains X-T
edge_F = edges.loc[edges.agregId=='1215690320-F'].iloc[0]
assert '1215690320-T' not in edge_F.in_links
```

### 3. MAJOR — DSU skip is justified for HERE-native data, but the doc undersells the caveat

Validation: of the 145 770 HERE node IDs, **none** is split across spatially distinct points (modulo the `-T` geometry artefact in issue 1). REF_IN_ID values are shared by up to 8 edges (max observed) and the geometry of all incident links converges on a single XY (verified by clustering start_xy of `-F`/`-O` edges grouped by REF_IN_ID — 100 % agreement). So **for HERE-only ingest, DSU is genuinely unnecessary**.

But `01:§3` already flags the two cases that need DSU (multi-source merges, post-filter renumber). The discontinuity layer in `discontinuity.py:60-74` uses DSU on `(LINK_ID, "s"/"t")` because it operates on a **filtered** subgraph (after `deadend_last_brins`) where the original HERE ids may now point to nodes that have collapsed. The new methodology must preserve this option for Phase 3 (post-filter rescoring). Recommend exposing the DSU helper from a shared `graph_utils.py` rather than re-inventing it in `discontinuity.py`.

### 4. MAJOR — Conservation rule at split roundabout junctions

HERE sometimes splits a roundabout across multiple node ids (each ring segment endpoint is its own node). Stage 5 of the methodology computes Σin vs Σout per `node_id`. For a roundabout node with 1 ring-in + 1 ring-out + 1 leg-in + 1 leg-out (in_deg=2, out_deg=2), Σin and Σout each mix circulating + radial flow. A legitimate "circulation imbalance" can fire — false positive.

The doc (`01:§2.3`) says "tag with `edge_category='roundabout'` so the discontinuity layer can downweight per-node GEH at internal ring nodes" but **never implements that downweighting in Stage 5**.

**Fix.** Add a node-level `is_roundabout_internal` flag:

```python
ring_nodes = set(edges.loc[edges.edge_category=='roundabout', 'in_node']) | \
             set(edges.loc[edges.edge_category=='roundabout', 'out_node'])
nodes['is_ring'] = nodes['node_id'].isin(ring_nodes)
nodes['is_bad'] = ( ... usual rule ... ) & (~nodes['is_ring'] | (nodes['GEH_node'] > 25))
```

Or, alternatively, **aggregate the roundabout into a single super-node** before running conservation. This is the cleaner graph-theoretic approach: build a DSU over edges where `edge_category=='roundabout'` is on BOTH endpoints, then collapse. ~4 % of edges → minor cost.

### 5. MAJOR — Direction-aware adjacency: `-F` and `-T` of *neighbouring* links

`00:§S3` claim: "downstream neighbours of `F` edge with `out_node=NREF` are edges with `in_node==NREF`". This is correct **if** we accept that the in_node of a `-T` row of a different base_id is whatever physical node that `-T` row leaves from. Verified: a `-T` row of base_id `Y` has `in_node = Y.NREF` (the suffix-based formula), so it correctly appears in `out_links` of any edge ending at `Y.NREF`. F-going-out and T-going-out are both included — correct.

But the doc never makes this explicit and the diagram in `00:§Stage 4` Example 1 omits the T-of-neighbour case. **Suggestion**: extend Example 1 with a 4-edge bidirectional junction (2 base_ids × 2 dir each = 4 directed edges meeting at one node, 2 in / 2 out) to demonstrate the adjacency table contains the cross-base T edges.

### 6. MINOR — Bidirectional (no-suffix) edges: 1 directed edge is correct

`DD=False` rows = 30 226 — these are genuine one-ways (with `-O` class). The doc emits one directed edge per such row, REF→NREF. Verified correct by data: `DD=False ⇔ no suffix` (100 % correlation on the 5 000-row sample, confirmed on full file). No issue.

### 7. MINOR — Boundary node definition (`in==0 OR out==0`) is correct but incomplete

Definition holds. Empirically: 5 334 source-only + 8 329 sink-only = 13 663 boundary nodes (9.4 % of all nodes). Orphan nodes (`in==0 AND out==0`) are **structurally impossible** because every node appears as endpoint of ≥ 1 edge (we derive nodes from the edge list, not vice-versa). The doc should add a one-liner asserting this invariant:

```python
assert not nodes[(nodes.n_in_edges==0) & (nodes.n_out_edges==0)].any().any()
```

Also clarify in `00:§S5` line 240: "boundary = (in==0) XOR (out==0)" — the OR notation in the doc is technically right but the XOR phrasing makes the impossibility clear.

### 8. MAJOR — Composite severity: additivity & monotonicity

`composite = 0.6·max(sev_in,sev_out) + 0.4·pair_mask·max(sev_pair_up, sev_pair_down)`.

Two graph-theoretic concerns:

(a) **Double-attribution of jumps.** A pair `u→v` flagged in S4 attributes severity to both `u` (via `sev_pair_down`) and `v` (via `sev_pair_up`). Since the composite takes a `max` (not sum) over up/down, the same jump can flag both ends of the pair at near-identical severity — desirable for ranking (both segments need review) but bookkeeping must avoid counting it twice in QC totals. Add to `discontinuity_qc.json`: `n_pair_flags` (number of distinct pairs) ≠ `n_edges_pair_flagged` (sum of endpoints).

(b) **Monotonicity.** If we increase one pair's `severity_pair`, does composite stay non-decreasing? Yes — `max` is monotone, the 0.4 coefficient is positive, and `pair_mask` only suppresses (it doesn't depend on severity magnitude). Confirmed monotone.

(c) **Anti-double-count masks** — when `pair_mask=False`, the pair contribution is zeroed and only the node contributes. But if there's a single bad endpoint and the *other* endpoint is fine, suppressing both pair directions is over-aggressive. Suggested refinement:

```python
# attribute pair severity only on the half whose endpoint is NOT bad
score_pair = ((~edges['in_bad'].fillna(False))  * edges['sev_pair_up'].fillna(0)
            + (~edges['out_bad'].fillna(False)) * edges['sev_pair_down'].fillna(0)) / 2
```

(d) **Self-loops and cycles in the discontinuity graph.** Empirically zero self-loops in the source. Cycles in the *flagged* edge subgraph cannot compound scores because each edge's `composite_severity` depends only on its own incident nodes and its 1-hop pairs — no propagation. Confirmed safe.

### 9. MINOR — Cross-check vs `discontinuity.py` reference impl

The reference computes `severity_score = pred * (|resid_start| + |resid_end|)` per link — i.e. a sum over endpoints. The new methodology uses a `max` over the two endpoint severities and adds a pair term. They are **not equivalent**:

| dimension | reference | new |
|---|---|---|
| node aggregation | sum of `\|residual\|` × pred | max of `GEH·√max_flow` |
| pair contribution | none | weighted 0.4 |
| boundary handling | exclude via `is_boundary` | exclude via `is_boundary` |
| junction reconstruction | DSU on (link, s/t) | HERE node ids |

The new method is **strictly more informative** (adds pair check, uses GEH-scaled severity), but it diverges enough that a small regression test is needed: take 100 edges where the reference impl ranks them top-100 problematic, recompute with the new method, and verify Spearman ρ ≥ 0.6. If lower, investigate.

### 10. MINOR — Roundabout self-loops

`01:§0` says "no self-loops in source" — verified true on 2025.geojson. But HERE roundabouts use a sequence of short curved links, never a single self-looped edge, so this is by construction. The `discontinuity.py:97` filter `REF==NREF → drop` remains a useful safety net. No change needed.

---

## Suggested test additions (graph-theoretic)

```python
# T1: -T geometry already in travel direction
def test_geom_T_already_oriented(sample_T_row, sample_F_row_same_base):
    assert sample_T_row.geometry.coords[0] == sample_F_row_same_base.geometry.coords[-1]

# T2: REF_IN_ID at multi-leg junction wires all incident edges
def test_multileg_adjacency():
    # at REF=82516565 there are 8 incident edges (4 base_ids × 2 dir)
    incidents = edges[(edges.in_node==82516565) | (edges.out_node==82516565)]
    assert len(incidents) == 8
    assert len(set(incidents.base_id)) == 4

# T3: no orphan nodes
def test_no_orphan_nodes(nodes):
    assert ((nodes.n_in_edges==0) & (nodes.n_out_edges==0)).sum() == 0

# T4: monotonicity of composite
def test_composite_monotonic():
    base = compute_composite(edges)
    edges2 = edges.copy(); edges2.loc[0,'sev_pair_down'] *= 2
    new = compute_composite(edges2)
    assert (new >= base).all()

# T5: DSU vs HERE-node-id equivalence on unfiltered graph
def test_dsu_redundant_on_here_native():
    nodes_dsu = run_with_dsu(edges)
    nodes_native = run_without_dsu(edges)
    assert (nodes_dsu.sort_index() == nodes_native.sort_index()).all().all()
```

---

## End state

APPROVED_WITH_CHANGES

Required before implementation: fix issue 1 (geometry orientation — currently inverted), implement issue 4 (roundabout node aggregation or ring downweight in Stage 5), and document issues 5 and 8c in the methodology body. Issues 2, 3, 6, 7, 9, 10 are documentation / test-coverage improvements.

APPROVED_WITH_CHANGES

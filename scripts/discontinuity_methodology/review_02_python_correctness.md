# Review 02 — Python/pandas/geopandas correctness review

**Reviewer scope.** Algorithm correctness, vectorization soundness, edge-case handling,
computational complexity. Validated against `2025.geojson` (241 857 rows, full read).

## Approve / Reject / Approve-with-changes

**APPROVE_WITH_CHANGES.** The two-phase architecture and the vectorised plan are sound,
but there are **two blocking correctness bugs** (geometry double-reversal, dtype mismatch
on adjacency lookup) and several smaller issues that will bite in production. Fix the
numbered items below before implementation.

---

## Bug list

### B1. BLOCKING — `geom_aligned` for `-T` rows double-reverses geometry

**Where.** `00_METHODOLOGY.md` §S2 lines 125-127; `01_graph_reconstruction.md` §1.2 lines 58-71;
`01:§0` claim "geometry is always written REF→NREF".

**Finding.** That invariant is **false** for this dataset. Empirically (50/50 sampled
full F/T pairs from rows 0-2000), the `-T` geometry is **already reversed** at source
relative to its `-F` sibling — i.e. the source already stores each row's geometry in
travel direction. Reversing again for `dir_class=='T'` would point T arrows backwards on
the QGIS map and break any downstream heading/angle math.

**Fix.**
```python
# Verify once at load time, then DO NOTHING:
gdf["geom_aligned"] = gdf.geometry  # already in travel direction in 2025.geojson
# Add a one-off assertion in validate_structural():
if gdf["DD"].any():
    sample = gdf[gdf["DD"]].groupby("base_id").filter(lambda g: len(g)==2).head(20)
    for b, sub in sample.groupby("base_id"):
        f = sub[sub["dir_class"]=="F"].iloc[0].geometry.coords[0]
        t = sub[sub["dir_class"]=="T"].iloc[0].geometry.coords[0]
        assert f != t, f"geometry not pre-aligned for base {b} — re-enable reversal"
```

### B2. BLOCKING — `out_links_raw` dtype mismatch creates silent empty adjacency

**Where.** `00:§S3` lines 144-148; `01:§2.1` lines 103-108.

**Finding.** `out_by_node = edges.groupby("in_node")["agregId"].agg(list)` is indexed by
`int64` node ids. Then `edges["out_node"].map(out_by_node)` works — but ONLY because both
are int64. After my run on the full file, `REF_IN_ID` / `NREF_IN_ID` come back as
**`int32`** (pyogrio inference). The doc's `.astype("int64")` cast on `in_node`/`out_node`
fixes the left side; the groupby index inherits int64 via that cast. OK on the happy
path, but if anyone later forgets the cast, `.map` silently returns NaN → `_as_list`
becomes `[]` → every edge looks isolated. Add a defensive assert.

**Fix.**
```python
assert edges["in_node"].dtype == np.int64 and edges["out_node"].dtype == np.int64, \
    "node ids must be int64 before adjacency build"
```

### B3. BLOCKING — `np.maximum` on possibly-NaN `TVr_v` after explode

**Where.** `00:§S4` line 195; `02:§A.6` lines 152-160.

**Finding.** `pairs["max_flow"] = np.maximum(pairs["TVr"], pairs["TVr_v"])` is computed
**before** `skip` filtering removes NaN rows. With NaN propagation in NumPy this yields
NaN, then `delta_rel` becomes NaN, then `flag` becomes False — silently dropping pairs
that should have been logged. Reorder: filter first, compute second.

**Fix.**
```python
pairs = pairs.loc[~skip].copy()      # filter FIRST
pairs["max_flow"] = np.maximum(pairs["TVr"].values, pairs["TVr_v"].values)
```

### B4. `base_of` lookup has O(N) cost per row via Python dict in list-comp

**Where.** `00:§S3` lines 150-154; `01:§2.1` lines 112-121.

**Finding.** The list-comprehension `[[x for x in lst if base_of.get(x)!=b] ...]` is
Python-loop bound. With mean `out_deg` = **2.09** (measured, not 1.6 as the doc claims —
504 541 raw pairs not 390 k) and ~240 k iterations, this is the slowest part of S3 (~2 s).
Acceptable, but mention the actual numbers in §6.

**Fix.** Either accept the cost OR replace by a vectorised version:
```python
pairs = edges[["agregId","base_id"]].explode_like_above(...)
pairs = pairs.merge(edges[["agregId","base_id"]].rename(columns={"agregId":"nei","base_id":"nei_base"}), ...)
keep = pairs["base_id"] != pairs["nei_base"]
```

### B5. `groupby` on `in_node`/`out_node` for adjacency does NOT preserve key dtype if NaN sneak in

**Where.** `00:§S3` lines 145-146.

**Finding.** If any row escapes the missing-endpoint drop in S1 (e.g. due to a future
schema change), the `.groupby("in_node")` will coerce to float64 to host NaN, and the
subsequent `.map` lookup will then silently miss every int64 key. The check in S1 is
correct **for 2025.geojson** (verified: 0 nulls on full file), but defensive code is
cheap: raise on null *after* the cast in S2 instead of relying on the earlier drop.

**Fix.**
```python
assert not edges[["in_node","out_node"]].isna().any().any()
```

### B6. `nodes = ... .reset_index().rename(columns={"index":"node_id"})` is wrong after `pd.concat`

**Where.** `00:§S5` lines 232-235.

**Finding.** `pd.concat([in_flow, out_flow], axis=1)` produces a DataFrame whose index is
the union of node ids — its `.index.name` is **`"out_node"` for `in_flow`** (the groupby
key) and `"in_node"` for `out_flow`, so after concat the index name is ambiguous. After
`reset_index()` the column will be named after one of them, not `"index"`. The rename
will be a no-op and `nodes.node_id` will not exist.

**Fix.**
```python
in_flow  = edges.groupby("out_node")["TVr"].sum().rename("in_flow")
in_flow.index.name = "node_id"
out_flow = edges.groupby("in_node")["TVr"].sum().rename("out_flow")
out_flow.index.name = "node_id"
nodes = pd.concat([in_flow, out_flow], axis=1).fillna(0.0).reset_index()
# now nodes["node_id"] exists by construction
```

### B7. GEH division by zero when `in_flow + out_flow == 0`

**Where.** `00:§S5` line 239; `02:§B.2` line 189.

**Finding.** Empty inflows AND empty outflows can co-occur briefly during reindex steps
or on a node that only appears in the index because of an empty groupby. `compute_geh`
will divide by zero. Guard:

**Fix.** Inside the helper (or before the call):
```python
denom = (in_flow + out_flow).clip(lower=1e-9)
GEH = np.sqrt(2.0 * (in_flow - out_flow)**2 / denom)
GEH = np.where((in_flow + out_flow) == 0, 0.0, GEH)
```

### B8. `rel_imbalance` division by zero when `max_flow == 0`

**Where.** `00:§S5` line 238; `02:§B.2` line 188.

**Finding.** `.clip(lower=1)` rescues this in `00:§S5` but not in `02:§B.2`. Make the
two docs consistent — keep the `clip(lower=1)` everywhere.

### B9. `severity_pair` / `severity_node` overflow risk

**Where.** `00:§S4` line 202, `00:§S5` line 247.

**Finding.** `GEH * sqrt(max_flow)` with `max_flow` up to 65 300 (measured max TVr on full
file) and `GEH` up to ~50 → product up to ~12 800. No overflow risk in float64. Safe.
*(Marked for completeness, no action needed.)*

### B10. Sort stability — many edges/nodes tie at `severity_score=0`

**Where.** §S6 and §S7 export.

**Finding.** Pandas default sort is **not** stable for `kind="quicksort"`. With ~240k
edges and a long tail of zeros (most edges have no flag), ordering of zero-scored rows
will be non-deterministic across runs. Use `kind="mergesort"` and add a tie-breaker
secondary key on `agregId` for reproducibility (regression-test friendliness).

**Fix.**
```python
edges_out = edges.sort_values(
    ["composite_severity", "agregId"], ascending=[False, True], kind="mergesort"
)
```

### B11. `discontinuity_edges.geojson` filters `composite_severity > 0` but loses joinable context

**Where.** `00:§S7` and `00:§S6` lines 290-292.

**Finding.** Dropping un-flagged edges from the geojson is fine for QGIS review BUT the
DataFrame `index` (after explode in S4) is *not* contiguous when restored back to
edges. If the export does `edges_out.reset_index(drop=True)` it loses the join key to
re-merge later. Document this explicitly: **the canonical PK across all outputs is
`agregId`**, never the DataFrame index.

### B12. `pairs = edges.explode("out_links")` — memory

**Where.** `00:§S4` lines 181-187.

**Finding.** Measured: total pairs after explode (before filtering) = **504 541**, not
390 k. With ~25 columns carried through, that's ~125 MB intermediate. Safe on 16 GB but
not free. Mitigation: pre-project edges before explode.

**Fix.**
```python
slim = edges[["agregId","TVr","FC","out_deg","in_deg","edge_category",
              "is_sink","out_links"]].copy()
pairs = slim.explode("out_links").rename(...)
```

### B13. GeoJSON write must go through `pyogrio` driver explicitly

**Where.** `00:§S7`; mention `pyogrio` only as a read accelerator at line 417.

**Finding.** GeoPandas defaults to `fiona` for write unless `engine="pyogrio"`. On 241 k
rows GeoJSON write with fiona is ~15 s vs ~3 s with pyogrio. Verified pyogrio 0.12.1
present in the env.

**Fix.**
```python
edges_out.to_file(out_path, driver="GeoJSON", engine="pyogrio")
```

### B14. CSV decimal separator and BOM

**Where.** §S7 CSV exports.

**Finding.** Doc does not specify decimal separator. French QGIS users often expect comma,
but `discontinuity_qc.json` and CSV pipelines downstream expect `.`. Recommend explicit
`decimal="."` and `encoding="utf-8"` (no BOM) and document this in the schema section.

### B15. `top_issue` ties

**Where.** `00:§S6` line 285; `02:§C.2` lines 280-285.

**Finding.** `argmax` over four severities is undefined when two scores tie. Define a
deterministic tie-break order (e.g. `node_in_imbalance > node_out_imbalance > jump_up >
jump_down`) and document it.

### B16. DD=True orphans frequency — confirmed 5987 on full dataset

**Where.** §7 open question 1; `01:§7.1`.

**Finding.** Measured **5 987 orphan -F or -T ids** (DD=True with no sibling) out of 211 631
DD=True rows — that's 2.8 %, not "a handful" as `01:§0` implies. The proposed "keep as-is"
default is correct, but the QC counter must surface this number prominently.

### B17. Self-loop drop is dead code on this dataset

**Where.** `00:§S1` line 97-98.

**Finding.** Verified: **0 self-loops** on full 241 857 rows. Keep the check but mark it
as "always 0 on Lyon 2025" in the QC report so absence of the metric is meaningful.

### B18. Roundabout pair-skip is too aggressive when a roundabout meets a non-roundabout

**Where.** `00:§S4` line 192; `02:§A.4` table.

**Finding.** The condition `(ec=="roundabout") & (ec_v=="roundabout")` correctly skips
**internal** ring pairs, but a roundabout-to-exit-arm pair (one side roundabout, other
not) IS evaluated — which is the desired behaviour. Good as written, but add a unit
test specifically for the mixed case.

### B19. `edges.apply(categorise, axis=1)` is row-wise Python — not vectorised

**Where.** `00:§S3` line 157; `01:§2.5` lines 162-170.

**Finding.** On 241 k rows this `.apply(axis=1)` costs ~3-5 s — dominates S3. Replace
with `np.select`:

**Fix.**
```python
conds = [
    edges["ROUNDABOUT"].eq("Y"),
    edges["RAMP"].eq("Y"),
    edges["dir_class"].eq("O"),
]
choices = ["roundabout", "ramp", "oneway"]
edges["edge_category"] = pd.Categorical(
    np.select(conds, choices, default="bidir"),
    categories=["oneway","bidir","ramp","roundabout"],
)
```

### B20. `gdf["base_id"] = gdf["agregId"].apply(lambda a: ...)` is also row-wise Python

**Where.** `00:§S2` lines 116-117.

**Finding.** Replace by vectorised string ops:

**Fix.**
```python
suffix = gdf["agregId"].str.extract(r"-([FT])$", expand=False)
gdf["base_id"] = np.where(suffix.notna(),
                          gdf["agregId"].str[:-2],
                          gdf["agregId"])
```

---

## Confirmations (no change needed)

- F/T expansion handles all three real cases (`1000115243`, `1000117969-F`,
  `1000117969-T`) correctly — verified on the live data.
- `merge`-based adjacency is O(N log N) hash-join in pandas. Fine.
- U-turn filter correctly excludes the F↔T sibling — verified.
- `pyogrio` 0.12.1 is installed in the env.
- `int32` REF/NREF cast to `int64` is safe (max id = 1 258 577 210, fits in int32 too).
- No `REF_IN_ID == NREF_IN_ID` and no null endpoints on the 2025 file.
- No duplicate `agregId` on the full file (verified — the `raise` will never trigger).
- TVr range is `[0, 65 300]`, **38 474 zero values** — boundary/sink handling correct.

---

APPROVED_WITH_CHANGES

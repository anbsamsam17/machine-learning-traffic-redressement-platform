# Review 04 — HERE data conventions vs methodology

## REJECT — methodology violates two empirically-verified invariants of `2025.geojson`

Reviewer focus: HERE F/T direction handling, REF/NREF_IN_ID semantics, RAMP / ROUNDABOUT
/ MULTIDIGIT / DIR_TRAVEL behaviour. All findings below are reproduced from
`2025.geojson` (241 857 rows) cross-checked against
`ref_here_brut/Streets.shp` (2 494 043 LINK rows).

Net result: **two showstopper bugs in Stage 2 (build directed edges)** that will mis-orient
roughly 121 309 / 241 857 edges (≈ 50 %) — every `-T` half of a bidirectional brin and
every `DD=False` row whose underlying HERE link had `DIR_TRAVEL='T'`. Until those are
fixed, the rest of the pipeline (adjacency, conservation, severity) is computed on a
graph whose directions are partly reversed, which silently corrupts node-level Σin/Σout.

---

## 1. SHOWSTOPPER — Geometry is *already* direction-aligned in `2025.geojson`

**Methodology claim** (`01:§0`, `00:§S3 Stage 2`):
> "`geometry` is always written REF → NREF, regardless of -F / -T."
> → reverse coordinates whenever `dir_class == 'T'` to build `geom_aligned`.

**Empirical reality** (sampled 500 of each):

| suffix | REF at start | REF at end | ambiguous (curved/aggregated brin) |
|---|---|---|---|
| `-F` | **423** | 2 | 75 |
| `-T` | 4 | **402** | 94 |
| DD=False (no suffix) | 217 | 228 | 55 |

For paired bidirectional rows (`base_id` with both -F and -T, n=2 000 pairs):
**`identical=0, reversed=2000`** — the two siblings carry **opposite** coordinate orders.

Cross-tab `DIR_TRAVEL` (HERE Streets.shp) × `(DD, suffix)` over the full 241 857 rows
matched 1-to-1:

| HERE DIR_TRAVEL | DD=False / no sfx | DD=True / -F | DD=True / -T |
|---|---|---|---|
| `B` | 0 | **106 088** | **105 543** |
| `F` | 14 460 | 0 | 0 |
| `T` | **15 766** | 0 | 0 |

The 2025 producer **already pre-rotated** geometries so that they read in the travel
direction. The doc has misidentified the convention.

**Concrete impact of the bug.**
- `-T` rows: `geom_aligned = LineString(reversed(coords))` **double-reverses** them — exported
  `discontinuity_edges.geojson` will show arrows against traffic on 105 543 brins.
- DD=False rows mapped to HERE `DIR_TRAVEL='T'` (15 766 rows = 52 % of all one-ways):
  the doc sets `dir_class='O'`, `in_node=REF`, `out_node=NREF`. Wrong: travel is
  NREF→REF. These edges contribute their TVr to the **wrong side** of every
  Σin/Σout balance — biasing 7–8 % of all node-conservation totals.

**Fix.** Stage 2 must **not** rely on suffix alone. Read `DIR_TRAVEL` from the HERE
source (or expose it in `2025.geojson` as an extra column) and use:

```python
gdf["dir_class"] = np.where(gdf["DD"], np.where(sfx=="F", "F", "T"),
                            np.where(here_dir=="F", "F",
                                     np.where(here_dir=="T", "T", "F")))
is_T = gdf["dir_class"].eq("T")
gdf["in_node"]  = np.where(is_T, gdf["NREF_IN_ID"], gdf["REF_IN_ID"]).astype("int64")
gdf["out_node"] = np.where(is_T, gdf["REF_IN_ID"], gdf["NREF_IN_ID"]).astype("int64")
gdf["geom_aligned"] = gdf.geometry   # already aligned, NO reversal
```

If `DIR_TRAVEL` is not re-exposed, the unambiguous fallback is: for each row, snap
`geometry.coords[0]` to either the REF point or the NREF point of the source HERE LINK
(retrievable by joining `agregId.base_id == LINK_ID` against `Streets.shp`) and set
direction from the snap result.

---

## 2. SHOWSTOPPER — DSU **is** required (doc says it isn't)

**Methodology claim** (`01:§3`, `02:§B.1`): "REF/NREF node ids already encode the
physical junction… DSU is not required for connectivity."

**Empirical reality.** In `2025.geojson` (which is the input the pipeline actually
consumes), at endpoint coordinates bucketed at 6 decimals (≈ 0.1 m):

| metric | value |
|---|---|
| distinct endpoint coordinates | 113 935 |
| distinct REF/NREF node IDs used | 145 770 |
| **physical points carrying ≥ 2 distinct node IDs** | **107 211 / 113 935 = 94.1 %** |
| node IDs that appear at > 1 physical point | 130 228 / 145 770 = 89.3 % |

Same test on the original `Streets.shp` (50 000-row sample): **0.1 %** multi-id buckets.
HERE's source is clean — but the `2025.geojson` *brin* aggregation has fractured node
identity, and that is the file the pipeline reads.

Direct consequence of skipping DSU: running Stage 5 on the raw node IDs yields **33 956
boundary nodes (23.3 %)** in Lyon, which is implausible — Lyon's true network boundary
fits in a few hundred edges. Most of those "boundary" nodes are split-junction artefacts
that hide real Σin/Σout violations.

**Fix.** Insert a spatial DSU between Stage 2 and Stage 3:

1. snap every `(REF_IN_ID, coord)` and `(NREF_IN_ID, coord)` to a 6-decimal bucket;
2. union all node IDs sharing a bucket;
3. expose `node_phys_id` as the canonical key, *but* keep the raw IDs for back-trace.

Caveat for **MULTIDIGIT='Y'**: two parallel one-way edges of a divided road may legitimately
have distinct node IDs at the same coordinate (central reservation). DSU should
therefore union by `(coord_bucket, RAMP/ROUNDABOUT/MULTIDIGIT signature)` — never blindly
collapse two opposing one-way nodes that face each other on a dual carriageway. A
naive 0.1 m spatial collapse alone bumps boundary count to **34.7 %** (verified), worse
than no DSU — so the union rule must be selective.

---

## 3. Orphan siblings are ~12× more common than the methodology assumes

| `DD=True` base_id sibling layout | count | % |
|---|---|---|
| both F+T present | 102 822 | 94.5 % |
| F-only orphan | 3 266 | 3.0 % |
| T-only orphan | 2 721 | 2.5 % |

**Total 5 987 orphan brins** (2.5 % of all rows). The methodology calls them
"a handful" (`01:§0`) and lists them as a deferrable open question. They are not
a handful, and on a bidirectional segment with a missing sibling the node-conservation
math fails systematically (one direction's TVr is absent from the sum). Recommend:

- Surface a hard QC counter `orphan_dd_true` in `discontinuity_qc.json`.
- For each orphan, synthesize a `dir_class='T'`-or-`F` ghost edge with `TVr=NaN` so
  that the node-balance computation can flag the resulting boundary as "missing data"
  rather than "real boundary".

---

## 4. TVr=0 plague on FC=5 — affects the pair-tier grid floor

`TVr=0` rows: **38 474 / 241 857 = 15.9 %**, almost all on FC=5 (residential).
`TVr` percentiles: p25=10, p50=90, p75=740, p95≈4 800.

The pair-tier grid's "< 500" bucket therefore covers **~75 % of all edges** and uses
the loosest cuts (Δrel 50 %, Δabs 200, GEH 10). This is fine — but combined with
`TVr=0` on one side of a pair, `delta_rel` saturates to 1.0 and the only meaningful
gate is `delta_abs > 200`, which fires on every transition into a non-residential
street. Recommend: **explicitly skip pairs where `min(TVr_u, TVr_v) == 0`** and
emit a separate "FC=5 silence pocket" diagnostic instead of stuffing those into
the discontinuity ranking.

The methodology already skips `TVr<0`/NaN but **not** `TVr==0` — patch
Stage 4 skip filter to add `(pairs["TVr"]==0) | (pairs["TVr_v"]==0)`.

---

## 5. RAMP / ROUNDABOUT / FUNC_CLASS confirmations

These are mostly fine; small clarifications:

| flag | rows | comment |
|---|---|---|
| `RAMP='Y'` | 1 412 (0.58 %) | FC distribution: 1=110, 2=293, 3=689, 4=198, 5=122 — methodology's ×1.5 rel_cut for ramps is appropriate; median TVr=5 810 so they fall in the 5–10 k tier |
| `ROUNDABOUT='Y'` | 5 549 (2.29 %) | **100 % DD=False, no suffix** (i.e. one-way ring) — methodology's "skip pair-wise inside ring" is correct |
| `RAMP='Y'` AND `ROUNDABOUT='Y'` | 0 | no combined case in Lyon — methodology can simplify the `categorise()` priority |
| `FC=5` | 198 900 (82.2 %) | dominant by sheer volume; median TVr=50 → the pair grid's `< 500` tier is right but see §4 above |

**Missing flags to use** (present in HERE Streets.shp, currently dropped during
brin aggregation):

- `MULTIDIGIT` — needed for DSU selectivity (§2). On the Streets sample,
  1 137 / 50 000 = 2.3 % of links. Without this flag, DSU will mistakenly merge
  the two halves of every divided carriageway.
- `ENH_GEOM` — informational only, methodology can ignore (confirmed).
- `BRIDGE` / `TUNNEL` / `TOLLWAY` — not exported in `2025.geojson` (verified via
  `list(gdf.columns)`). Not blocking for the discontinuity check, but worth a
  one-line note in `01:§0` so a future contributor doesn't assume they're available.

---

## 6. Minor — `FC == FUNC_CLASS` redundancy

In `2025.geojson` both columns exist and are bitwise identical (verified: same
counts per class 1/2/3/4/5). The doc references both interchangeably. Drop one,
or document explicitly that they are mirrors.

---

## Concrete patch list (in priority order)

1. **(BLOCKING)** Rewrite `Stage 2` orientation logic to honour HERE `DIR_TRAVEL`,
   not the brin suffix alone. Remove the `geom_aligned` reversal — the geometry
   is already aligned. See fix in §1.
2. **(BLOCKING)** Add a selective spatial DSU between Stage 2 and Stage 3,
   keyed on `(coord_bucket, MULTIDIGIT)`. Expose `node_phys_id` as the
   conservation key. See §2.
3. **(HIGH)** Add `(TVr==0)` to the Stage 4 pair-skip filter (§4).
4. **(HIGH)** Promote orphan-sibling diagnostics from "open question" to a
   first-class QC metric and consider ghost-edge synthesis (§3).
5. **(MEDIUM)** Re-expose `MULTIDIGIT`, `DIR_TRAVEL`, `BRIDGE`, `TUNNEL`,
   `TOLLWAY` in the next iteration of `2025.geojson` (upstream change).
6. **(LOW)** Resolve `FC` vs `FUNC_CLASS` duplication (§6).

After patches 1–2 the rest of the methodology (severity grid, GEH thresholds,
0.6 / 0.4 weights, top-issue argmax) becomes defensible — the underlying graph
will finally represent the right edges, so the analytic layer can be re-evaluated
on its own merits.

REJECTED.

# Review 01 — Traffic engineering perspective

Reviewer scope: physics of flow conservation, threshold realism, urban context (Grand Lyon, ~1.4 M inh., FC1-FC5 mix, dense radial+ring topology). Source documents: `00_METHODOLOGY.md`, `01_graph_reconstruction.md`, `02_continuity_and_conservation.md`.

## Verdict: APPROVE WITH CHANGES

The two-phase design (pair continuity + node conservation) is methodologically sound and matches industry practice (Highways England DMRB-style GEH + relative envelope). The skip rules for divergence/convergence and the daily-rescaling of GEH are correct. However several thresholds are tuned for inter-urban / mid-density networks and will under-trigger or over-trigger in Grand-Lyon-specific regimes. Eight changes recommended below before production.

---

## 1. Flow-tier band realism (Phase 2A grid)

**Issue 1.1 — Lyon flow distribution argues for an extra mid-band.**
For an urban network like Grand Lyon, the bulk of `boulevards de ceinture`, `boulevard périphérique nord`, M6/M7 traverses, and `quais` sit in the 10 000-30 000 veh/day band, with M6/A6 and BPNL feeding > 50 000 veh/day on shared sections. The current >10 000 band lumps a Cours Lafayette segment (~12 k) with a BPNL ramp (~40 k) under the same 1 800 veh/day floor. At 40 k veh/day, a 1 800 abs floor is only 4.5 %, which under the 18 % rel cut is dominated by rel — fine. But at 12 k, 1 800 is 15 %, well below the 18 % rel cut — so abs becomes a non-binding floor and the rule reduces to rel-only.

**Fix 1.1** — split the top band into two:
| max(TVr) | Δrel | Δabs | GEH |
|---|---|---|---|
| 10 000-25 000 | 18 % | 1 800 | 22 |
| > 25 000 | 14 % | 3 000 | 26 |

**Issue 1.2 — < 500 band is too lax for an urban core.**
50 % rel + 200 abs + GEH 10 will pass through real discontinuities on `rues de desserte` where the model jumps from 60 to 350 veh/day (legitimate hospital access vs. cul-de-sac). On Lyon's `Pentes de la Croix-Rousse`, that band is heavily populated and the loose cut effectively disables Check A there.

**Fix 1.2** — tighten to `Δrel 40 %, Δabs 150, GEH 9`. Keeps noise-tolerance but recovers obvious factor-of-5 jumps.

## 2. GEH unit and threshold

**Issue 2.1 — GEH at daily cadence is fine, but the √24 rescaling is approximate.**
The √N scaling assumes Poisson intra-day arrivals with no peaking; for urban arterials with a clear 2-peak distribution, the effective scaling is closer to √(N/(peak-factor)) ≈ √(24/1.8) ≈ ×3.6, not ×4.9. The doc says "tighten daily threshold to 20" — that is in the right direction but slightly loose for arterials with sharp peaks.

**Fix 2.1** — keep daily GEH at the cuts proposed (10/14/17/20/22) and add a note that for *peak-hour* validation against count loops, the threshold reverts to 5/10 hourly. Also expose `--geh-mode {daily, peak_hour}` so a future hourly run reuses the same code.

**Issue 2.2 — Do not convert to hourly inside the pipeline.** TVr is daily (TMJA). Converting via `÷24` is wrong (DMRB GEH is for the modelled period's volume, not annualized). Stay daily. The doc already does this correctly; just make it explicit in the CLI help.

## 3. AND-of-three vs. dominant metric

**Issue 3.1 — AND-of-three is safe but masks high-flow trunk anomalies.**
On a > 10 000 trunk, a GEH of 30 with delta_rel 16 % (Δabs ≈ 4 000) is a real model failure on a flagship axis, but if `Δrel = 16 % < 18 %` the AND rule will not flag it. GEH alone is the trusted metric above ~5 000 veh/day in DMRB and TfL practice.

**Fix 3.1** — switch from pure AND to a **2-of-3 majority above 5 000 veh/day, AND-of-3 below**:
```
if max_flow >= 5000:
    flag = sum([delta_rel>rel_cut, |delta_abs|>abs_cut, GEH_pair>geh_cut]) >= 2
else:
    flag = (delta_rel>rel_cut) AND (|delta_abs|>abs_cut) AND (GEH_pair>geh_cut)
```
This preserves the low-flow noise filter and lets GEH/abs dominate on big roads.

## 4. Node conservation rule (Phase 2B)

**Issue 4.1 — min_flow = 3 000 is correct as a noise floor but should depend on degree.**
A 4-leg signalized intersection with 2 500 veh/day total is rare in Lyon but exists in residential pockets (Caluire). A 6-leg star at Place Bellecour with 2 500 veh/day is impossible — it would mean the model is dead. Decoupling cuts by degree helps:

**Fix 4.1** — `min_flow = max(3000, 600 * (n_in_edges + n_out_edges))`. For a 3-leg junction → 3000. For a 6-leg star → 3600. Keeps the bar realistic.

**Issue 4.2 — OR between GEH and rel_imbalance is correct.** Agreed: GEH catches absolute miss on big nodes; rel catches lopsided medium nodes. Keep OR.

**Issue 4.3 — Turning-movement effects make Σin = Σout intrinsically biased.**
At signalized intersections with left-turn bans, bus-only contraflow lanes, or one-way detours (common on Lyon `presqu'île` and `Vieux-Lyon`), the daily Σin can legitimately differ from Σout by 3-8 % due to TVr aggregation across direction-restricted movements that the model resolves at sub-link cadence. The 18 % cut absorbs that comfortably, but the bottom of the distribution will be noisy.

**Fix 4.3** — Add a soft tolerance for nodes with `n_in_edges != n_out_edges` (asymmetric junction, often signal+ban): bump `rel_imbalance_bad` from 0.18 to 0.22 when `|n_in_edges - n_out_edges| >= 2`. Surface the asymmetry as a column for QGIS review.

## 5. Skip rules and edge cases

**Issue 5.1 — Skipping pair check on roundabouts is too aggressive for large Lyon ronds-points.**
`Place Jean-Macé`, `Place Bellecour`, `Pont Lafayette / Place Lyautey` — these are large multi-lane gyratories where internal links carry 8 000-15 000 veh/day each and the model can absolutely fail on one quadrant. The doc already notes this in §E.2 as deferrable; given the scale of Lyon ronds-points, recommend not deferring.

**Fix 5.1** — Enable A on internal roundabout pairs with a `×2.0` looser grid (rel_cut, abs_cut both doubled; GEH cut +4). Tag results with `edge_category=roundabout` for QGIS color-coding so reviewer can dismiss false positives quickly.

**Issue 5.2 — Boundary nodes tagged-not-flagged: agreed for QC, but add a coverage check.**
A boundary that sits geographically inside the Lyon Métropole bounding box (not on its convex hull) is almost certainly a *missing brin*, which is a different defect class than a TVr error. Recommend §E.3's separate coverage check as non-optional.

**Fix 5.2** — Build `is_interior_boundary = is_boundary AND (point inside convex hull of all non-boundary nodes shrunk by 500 m)`. Emit those to `coverage_gaps.csv` separately from `discontinuity_*`.

**Issue 5.3 — FC boundary handled as ×1.3 modulator: agreed.**
A trunk-to-distributor jump of 30 % is legitimate; loosening rel is the right physical move. Do not promote it to a separate hard threshold.

## 6. Composite severity weighting

**Issue 6.1 — 0.6 / 0.4 is reasonable but evidence-free.**
Standard practice (e.g. TomTom Move QA, Inrix custom-validation playbooks) weights node 0.55-0.65 against pair 0.35-0.45 because node-level errors propagate through more downstream forecasts. The 0.6/0.4 split is defensible.

**Fix 6.1** — Keep 0.6/0.4 as default but expose as CLI arg (already done in `--weight-node`/`--weight-pair`). After QGIS labelling round 1, refit weights against the labelled set (logistic regression on `is_real_discontinuity`).

## 7. Known counterexamples

### False positives expected

**FP-1 — Carrefour à phases avec tourne-à-gauche interdit (e.g., `Cours Gambetta × rue Servient`).**
The left-turn ban moves real flow around the block via 3 right turns. Each leg's TVr is correct, but Σin at the cross node can be 8-12 % off Σout because the ban-induced detour is partly counted on adjacent links. The 18 % rel cut absorbs most, but ~5 % of such nodes will trip GEH at high flow.
*Mitigation:* Fix 4.3 (asymmetry-aware threshold) + add a `has_turn_restriction` feature pulled from HERE `LANE_CAT`/`TURN_RESTR` if available.

**FP-2 — Pont sur le Rhône (e.g., Pont Lafayette) avec voies bus reversées.**
Bus-only contraflow lanes carry zero TVr but contribute geometry that the model includes as a separate brin. The brin reads ~80 veh/day (delivery + emergency) next to a sibling at 18 000 veh/day → tier `>10k` fires on the pair check because Δrel ≈ 99 %.
*Mitigation:* Add a category filter: skip pair when `min(TVr_u, TVr_v) < 200 AND (FC_u != FC_v OR bus_lane==Y)`. Surface to a `low_flow_siblings.csv` for separate review.

### False negatives expected

**FN-1 — Slowly drifting TVr along a 4 km radial axis.**
Consider `Avenue Berthelot` between Jean-Macé and Garibaldi: 6 successive brins at 8 200 / 8 500 / 7 900 / 7 100 / 6 600 / 6 200. No single pair exceeds Δrel 22 % (the largest gap is 7 100→6 600 = 7 %), so Check A finds nothing. Yet the axis lost 2 000 veh/day with no upstream junction explaining the leak — a real model defect.
*Mitigation:* Add a **Phase 2C — corridor drift**: for chains of edges with out_deg=in_deg=1 and same FC of length ≥ 3, compute the end-to-end Δrel against tier `(>=10k → 18%, 5-10k → 20%, etc.)`. Implement as a single DFS in < 1 s.

**FN-2 — Compensating errors at a junction.**
Σin = 12 000, Σout = 12 000, but one inflow over-predicts by 1 500 and another under-predicts by 1 500. Check B sees a balanced node. Check A only sees it if the over/under sits in a 1-in-1-out relay; at the junction itself the divergence skip kills it.
*Mitigation:* Add a **per-leg dispersion** metric at flagged-or-near-flag nodes: standard deviation of normalized leg flows vs. mean turning fraction. Flag the node when `cv > 0.25` even if Σ-balanced. Cheap (~50 ms).

---

## Summary of concrete changes

| # | Change | Param / Code |
|---|---|---|
| 1.1 | Split >10k band into 10-25k and >25k | tier grid |
| 1.2 | Tighten <500 band to 40 % / 150 / 9 | tier grid |
| 3.1 | 2-of-3 above 5k, AND-of-3 below | pair flag rule |
| 4.1 | `min_flow = max(3000, 600*(n_in+n_out))` | node rule |
| 4.3 | `rel_bad=0.22` when junction asymmetry ≥ 2 | node rule |
| 5.1 | Enable A on roundabouts with ×2.0 grid | skip rule |
| 5.2 | Separate `coverage_gaps.csv` for interior boundaries | export |
| FN-1| Add Phase 2C corridor drift check | new step |
| FN-2| Add per-leg dispersion at junctions | enrich B |

All changes additive; no breaking change to the output schema. Total runtime impact estimated < 5 s.

APPROVED_WITH_CHANGES

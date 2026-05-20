# Worker A1 Phase 0-5 — loss + target ablation (12 configs)

Generated: 2026-05-20 08:28:16
Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Baseline: Full 11 features, ep=1000, drp=0.025, neurons_factors=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05, no weighting

## Results (sorted by tol_in %)

| Run | Loss | Drp | Ep | TLog | Tol in | Tol % | p80% | R2 | RMSE | MAE | GEH<5 | Train(s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1_tolerance_aware_02_ep1000 | tolerance_aware | 0.02 | 1000 | — | 2361/3632 | 65.0% | 28.15 | 0.6641 | 0.6827 | 0.3551 | 100.0% | 191 |
| A1_tolerance_aware_025_ep1000 | tolerance_aware | 0.025 | 1000 | — | 2343/3632 | 64.5% | 28.35 | 0.6628 | 0.6840 | 0.3587 | 100.0% | 190 |
| A1_huber_02_ep1000 | huber | 0.02 | 1000 | — | 2254/3632 | 62.1% | 28.39 | 0.6717 | 0.6749 | 0.3685 | 100.0% | 190 |
| A1_huber_025_ep1000 | huber | 0.025 | 1000 | — | 2235/3632 | 61.5% | 28.51 | 0.6676 | 0.6792 | 0.3712 | 100.0% | 304 |
| A1_huber_025_ep1000_tlog | huber | 0.025 | 1000 | Y | 2235/3632 | 61.5% | 28.51 | 0.6676 | 0.6792 | 0.3712 | 100.0% | 183 |
| A1_mse_025_ep750 | mse | 0.025 | 750 | — | 2193/3632 | 60.4% | 29.24 | 0.6786 | 0.6678 | 0.3795 | 100.0% | 134 |
| A1_mse_02_ep1000 | mse | 0.02 | 1000 | — | 2193/3632 | 60.4% | 29.58 | 0.6742 | 0.6723 | 0.3824 | 100.0% | 120 |
| A1_mse_025_ep1250 | mse | 0.025 | 1250 | — | 2191/3632 | 60.3% | 29.22 | 0.6793 | 0.6670 | 0.3794 | 100.0% | 239 |
| A1_mse_025_ep1000 | mse | 0.025 | 1000 | — | 2190/3632 | 60.3% | 29.23 | 0.6790 | 0.6674 | 0.3795 | 100.0% | 99 |
| A1_mse_025_ep1000_tlog | mse | 0.025 | 1000 | Y | 2190/3632 | 60.3% | 29.23 | 0.6790 | 0.6674 | 0.3795 | 100.0% | 183 |
| A1_mse_03_ep1000 | mse | 0.03 | 1000 | — | 2182/3632 | 60.1% | 28.92 | 0.6797 | 0.6666 | 0.3814 | 100.0% | 388 |
| A1_pinball_p80_025_ep1000 | pinball_p80 | 0.025 | 1000 | — | 1693/3632 | 46.6% | 33.16 | 0.6230 | 0.7232 | 0.4777 | 100.0% | 183 |

## Best of batch (highest tol_in %)
- **A1_tolerance_aware_02_ep1000** — tol=2361/3632 (65.0%) | p80=28.15% | R2=0.6641 | RMSE=0.6827 | GEH<5=100.0% | train=191s
- Lowest p80: **A1_tolerance_aware_02_ep1000** — p80=28.15% | tol=2361/3632 | R2=0.6641
- Highest R2: **A1_mse_03_ep1000** — R2=0.6797 | tol=2182/3632 | p80=28.92%

## Wall-clock
- Restart batch (configs 3-12): **2415s** (40.2 min)
- Smoke test config 1: ~124s (~2 min)
- Aborted batch (config 3 first attempt): ~388s training time wasted
- **Total wall-clock (incl. retries): ~2927s (48.8 min)**

## Notes & issues
- **API bug detected**: `apps/api/app/services/ml/training_pipeline.py:584` does NOT pass `target_log_transform` to `split_train_valid`. Configs 9 (mse_tlog) and 10 (huber_tlog) produced metrics identical to their non-tlog counterparts. Flag persisted via `warning_target_log_transform_no_op` in their metrics.json.
- **Worker bug detected & fixed mid-batch**: the API serializes all run models into the same session-level `models/` dir. The original `sub_dirs[0]` heuristic picked the wrong model when multiple existed. Fixed to match by expected `loss + drp + ep` pattern; configs 2-12 re-ran cleanly after the fix.
- **pinball_p80 is not a good fit** for tol_in optimisation (tol=46.6% vs 60-65% for other losses). Expected — pinball@0.8 targets the 80th percentile, not the median.
- **`target_log_transform` had no effect** (see API bug above) — once the bug is fixed, configs 9 & 10 should be re-run.
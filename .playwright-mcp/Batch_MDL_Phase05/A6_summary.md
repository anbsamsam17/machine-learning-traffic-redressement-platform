# A6 — winning combinations + TTA (14 configs)

Worker A6 of the 6-agent Phase 0-5 grid search. Port 7006.
Baseline: Full 11 features, drp=0.025, ep=1000, neurons_factors=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05.
Dataset: BCFCDREF_AllYears_TV.geojson (Grand Lyon, 3632 capteurs, 2019-2025).

## Training configs (1-10) — ranked by tolerance %

| # | run_name | loss | optimizer | skip | weighting | tol_in/total (%) | p80 (%) | R2 | RMSE | MAE | train (s) | broken |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | `A6_tolerance_permX2` | tolerance_aware | - | - | permX2.0 | 2379/3632 (65.5%) | 27.69 | 0.668 | 0.678 | 0.351 | 246.9 | - |
| 10 | `A6_AdamW_skip_permX2_nseeds3` | mse | adamw | yes | permX2.0 | 2258/3632 (62.2%) | 29.45 | 0.672 | 0.675 | 0.423 | 246.6 | - |
| 2 | `A6_huber_permX3_recX3` | huber | - | - | permX3.0+recX3.0 | 2251/3632 (62.0%) | 28.81 | 0.674 | 0.672 | 0.372 | 182.9 | - |
| 1 | `A6_huber_permX2_recX2` | huber | - | - | permX2.0+recX2.0 | 2236/3632 (61.6%) | 28.92 | 0.669 | 0.678 | 0.374 | 197.5 | - |
| 6 | `A6_ratioPLTV_logTMJOFCDTV_permX2` | mse | - | - | permX2.0 | 2229/3632 (61.4%) | 27.83 | 0.685 | 0.661 | 0.368 | 113.1 | - |
| 7 | `A6_robustScaler_permX2` | mse | - | - | permX2.0 | 2207/3632 (60.8%) | 29.11 | 0.681 | 0.666 | 0.378 | 105.6 | - |
| 8 | `A6_yearEmb_permX2` | mse | - | - | permX2.0 | 2207/3632 (60.8%) | 29.11 | 0.681 | 0.666 | 0.378 | 91.6 | - |
| 3 | `A6_AdamW_skip_LN_permX2` | mse | adamw | yes | permX2.0 | 2107/3632 (58.0%) | 31.19 | 0.662 | 0.685 | 0.399 | 182.9 | - |
| 4 | `A6_AdamW_skip_LN_permX2_recX2` | mse | adamw | yes | permX2.0+recX2.0 | 2080/3632 (57.3%) | 31.11 | 0.668 | 0.679 | 0.402 | 190.1 | - |
| 9 | `A6_AdamW_skip_huber_permX3` | huber | adamw | yes | permX3.0 | 2045/3632 (56.3%) | 30.52 | 0.662 | 0.685 | 0.400 | 91.5 | - |

## TTA re-evaluations (11-14) — parent vs TTA

| # | run_name | parent | tta_iter | tta_noise_std | tol_in/total (%) | p80 (%) | R2 | RMSE | broken |
|---|---|---|---|---|---|---|---|---|---|
| 11 | `A6_C1_TTA` | A6_huber_permX2_recX2 | 5 | 0.01 | 2238/3632 (61.6%) | 28.76 | 0.669 | 0.678 | - |
| 12 | `A6_C3_TTA` | A6_AdamW_skip_LN_permX2 | 5 | 0.01 | 2112/3632 (58.1%) | 31.18 | 0.662 | 0.685 | - |
| 13 | `A6_C4_TTA` | A6_AdamW_skip_LN_permX2_recX2 | 5 | 0.01 | 2087/3632 (57.5%) | 31.29 | 0.668 | 0.678 | - |
| 14 | `A6_C9_TTA` | A6_AdamW_skip_huber_permX3 | 5 | 0.01 | 2047/3632 (56.4%) | 30.57 | 0.662 | 0.684 | - |

## Winner (training)
- **A6_tolerance_permX2** — tol=65.5% p80=27.69% R2=0.668
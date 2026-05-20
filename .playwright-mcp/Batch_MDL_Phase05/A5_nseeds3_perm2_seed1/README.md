# A5_nseeds3_perm2

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "n_seeds": 3,
  "use_flag_permanent_weighting": true,
  "flag_priority_weight": 2.0
}
```

## Baseline
- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)
- loss=`mse`, dropout=0.025, neurons_factors=[3.0, 2.0, 1.0], lr=0.01, batch=256, activation=elu
- epochs_requested=1250, epochs_trained=1075, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `False`
- use_curriculum: `False`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `True`
- use_flag_recent_year_weighting: `False`
- n_seeds: `3`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **2226/3632** (61.29%)
- Erreur relative p80: **28.6941%**
- R²: **0.697275**
- GEH < 5: **100.0%**
- RMSE: 0.6481  MAE: 0.3682  MAPE: 21.42%
- Median rel. error: 13.97%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.648037,
    0.743341
  ],
  "p80": [
    27.7143,
    29.6739
  ],
  "tol_in_pct": [
    59.64,
    63.0
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 93 | 46.5% | 61.939 | 0.087001 |
| 1k-5k | 1361 | 795 | 58.41% | 35.281 | 0.468319 |
| 5k-20k | 1618 | 995 | 61.5% | 24.2634 | 0.575864 |
| 20k+ | 453 | 343 | 75.72% | 15.2656 | 0.742849 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.624641 | 0.2854 | 58.11% | 25.0004% |
| 2020 | 266 | 0.810573 | 0.2883 | 59.77% | 26.1175% |
| 2021 | 347 | 0.874101 | 0.2567 | 63.69% | 21.08% |
| 2022 | 390 | 0.871908 | 0.2413 | 65.64% | 20.2965% |
| 2023 | 440 | 0.723244 | 0.2946 | 60.91% | 22.4076% |
| 2024 | 453 | 0.596455 | 0.355 | 57.17% | 26.0038% |
| 2025 | 1514 | 0.668779 | 0.478 | 40.82% | 43.2247% |

_Wall-clock: 539.4s  bootstrap_iter=1000_
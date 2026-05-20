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
- epochs_requested=1250, epochs_trained=1067, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `False`
- use_curriculum: `False`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `True`
- use_flag_recent_year_weighting: `False`
- n_seeds: `3`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **2166/3632** (59.64%)
- Erreur relative p80: **29.9697%**
- R²: **0.669319**
- GEH < 5: **100.0%**
- RMSE: 0.6774  MAE: 0.3862  MAPE: 22.19%
- Median rel. error: 14.46%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.620274,
    0.717531
  ],
  "p80": [
    28.9307,
    31.0087
  ],
  "tol_in_pct": [
    57.96,
    61.34
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 96 | 48.0% | 63.1545 | 0.070849 |
| 1k-5k | 1361 | 755 | 55.47% | 36.3238 | 0.413703 |
| 5k-20k | 1618 | 974 | 60.2% | 25.4533 | 0.533139 |
| 20k+ | 453 | 341 | 75.28% | 16.6781 | 0.688965 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.549239 | 0.3118 | 52.25% | 27.6627% |
| 2020 | 266 | 0.761554 | 0.3241 | 53.76% | 29.5322% |
| 2021 | 347 | 0.853902 | 0.2728 | 61.38% | 23.0448% |
| 2022 | 390 | 0.856262 | 0.2601 | 65.13% | 22.5027% |
| 2023 | 440 | 0.716669 | 0.3003 | 60.68% | 25.2655% |
| 2024 | 453 | 0.583362 | 0.3634 | 58.28% | 27.6406% |
| 2025 | 1514 | 0.634893 | 0.4982 | 39.89% | 44.6228% |

_Wall-clock: 544.5s  bootstrap_iter=1000_
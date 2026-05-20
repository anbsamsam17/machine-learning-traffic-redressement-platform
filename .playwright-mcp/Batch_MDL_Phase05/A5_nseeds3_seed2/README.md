# A5_nseeds3

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "n_seeds": 3
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
- use_flag_permanent_weighting: `False`
- use_flag_recent_year_weighting: `False`
- n_seeds: `3`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **2155/3632** (59.33%)
- Erreur relative p80: **30.1018%**
- R²: **0.666072**
- GEH < 5: **100.0%**
- RMSE: 0.6807  MAE: 0.3877  MAPE: 22.12%
- Median rel. error: 14.6%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.617318,
    0.714603
  ],
  "p80": [
    29.1108,
    31.0928
  ],
  "tol_in_pct": [
    57.71,
    61.1
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 94 | 47.0% | 64.3841 | 0.076042 |
| 1k-5k | 1361 | 755 | 55.47% | 36.3831 | 0.411295 |
| 5k-20k | 1618 | 969 | 59.89% | 25.3484 | 0.524877 |
| 20k+ | 453 | 337 | 74.39% | 16.859 | 0.679871 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.553975 | 0.3083 | 52.7% | 27.6536% |
| 2020 | 266 | 0.757474 | 0.3279 | 53.38% | 30.1184% |
| 2021 | 347 | 0.852806 | 0.2743 | 61.1% | 23.8871% |
| 2022 | 390 | 0.854145 | 0.2628 | 62.82% | 23.3489% |
| 2023 | 440 | 0.715107 | 0.306 | 58.86% | 26.4005% |
| 2024 | 453 | 0.586789 | 0.3634 | 57.4% | 28.4766% |
| 2025 | 1514 | 0.629466 | 0.4989 | 40.55% | 44.2624% |

_Wall-clock: 556.9s  bootstrap_iter=1000_
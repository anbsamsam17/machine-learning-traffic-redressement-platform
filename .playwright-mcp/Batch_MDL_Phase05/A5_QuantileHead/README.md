# A5_QuantileHead

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "use_quantile_head": true
}
```

## Baseline
- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)
- loss=`mse`, dropout=0.025, neurons_factors=[3.0, 2.0, 1.0], lr=0.01, batch=256, activation=elu
- epochs_requested=1250, epochs_trained=1035, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `False`
- use_curriculum: `False`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `False`
- use_flag_recent_year_weighting: `False`
- n_seeds: `1`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **2190/3632** (60.3%)
- Erreur relative p80: **29.0602%**
- R²: **0.679003**
- GEH < 5: **100.0%**
- RMSE: 0.6674  MAE: 0.3795  MAPE: 21.88%
- Median rel. error: 14.39%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.630336,
    0.726799
  ],
  "p80": [
    27.9614,
    30.1591
  ],
  "tol_in_pct": [
    58.59,
    61.95
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 96 | 48.0% | 63.6743 | 0.07229 |
| 1k-5k | 1361 | 780 | 57.31% | 34.7246 | 0.45585 |
| 5k-20k | 1618 | 976 | 60.32% | 25.0987 | 0.537795 |
| 20k+ | 453 | 338 | 74.61% | 16.3491 | 0.701813 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.587853 | 0.293 | 54.5% | 27.7248% |
| 2020 | 266 | 0.790287 | 0.3039 | 55.64% | 25.6158% |
| 2021 | 347 | 0.855166 | 0.2731 | 60.81% | 22.5084% |
| 2022 | 390 | 0.855813 | 0.2623 | 64.36% | 22.5403% |
| 2023 | 440 | 0.724788 | 0.2997 | 59.77% | 24.1314% |
| 2024 | 453 | 0.599113 | 0.3525 | 58.72% | 27.5738% |
| 2025 | 1514 | 0.643563 | 0.4914 | 40.89% | 43.3101% |

_Wall-clock: 183.4s  bootstrap_iter=1000_
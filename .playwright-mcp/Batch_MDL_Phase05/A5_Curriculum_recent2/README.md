# A5_Curriculum_recent2

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "use_curriculum": true,
  "use_flag_recent_year_weighting": true,
  "recent_year_priority_weight": 2.0
}
```

## Baseline
- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)
- loss=`mse`, dropout=0.025, neurons_factors=[3.0, 2.0, 1.0], lr=0.01, batch=256, activation=elu
- epochs_requested=1250, epochs_trained=1250, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `False`
- use_curriculum: `True`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `False`
- use_flag_recent_year_weighting: `True`
- n_seeds: `1`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **1897/3632** (52.23%)
- Erreur relative p80: **33.3102%**
- R²: **0.616302**
- GEH < 5: **100.0%**
- RMSE: 0.7296  MAE: 0.448  MAPE: 25.94%
- Median rel. error: 17.57%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.568515,
    0.661907
  ],
  "p80": [
    32.4627,
    34.1576
  ],
  "tol_in_pct": [
    50.5,
    53.83
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 89 | 44.5% | 59.2113 | 0.083455 |
| 1k-5k | 1361 | 707 | 51.95% | 38.7222 | 0.379237 |
| 5k-20k | 1618 | 846 | 52.29% | 30.1218 | 0.424909 |
| 20k+ | 453 | 255 | 56.29% | 22.647 | 0.527465 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.419973 | 0.352 | 48.65% | 35.4086% |
| 2020 | 266 | 0.669656 | 0.3789 | 46.99% | 33.9192% |
| 2021 | 347 | 0.77101 | 0.3458 | 54.47% | 32.0506% |
| 2022 | 390 | 0.750137 | 0.3496 | 50.77% | 30.2684% |
| 2023 | 440 | 0.620695 | 0.3936 | 47.27% | 31.0245% |
| 2024 | 453 | 0.533534 | 0.4363 | 47.02% | 32.6572% |
| 2025 | 1514 | 0.600303 | 0.5423 | 35.6% | 49.0218% |

_Wall-clock: 124.1s  bootstrap_iter=1000_
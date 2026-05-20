# A5_Curriculum_perm2

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "use_curriculum": true,
  "use_flag_permanent_weighting": true,
  "flag_priority_weight": 2.0
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
- use_flag_permanent_weighting: `True`
- use_flag_recent_year_weighting: `False`
- n_seeds: `1`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **1908/3632** (52.53%)
- Erreur relative p80: **33.433%**
- R²: **0.622775**
- GEH < 5: **100.0%**
- RMSE: 0.7235  MAE: 0.4404  MAPE: 26.05%
- Median rel. error: 16.86%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.573886,
    0.669319
  ],
  "p80": [
    32.4794,
    34.3866
  ],
  "tol_in_pct": [
    50.88,
    54.21
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 86 | 43.0% | 60.334 | 0.080439 |
| 1k-5k | 1361 | 683 | 50.18% | 39.2117 | 0.362813 |
| 5k-20k | 1618 | 874 | 54.02% | 29.5177 | 0.442903 |
| 20k+ | 453 | 265 | 58.5% | 21.4248 | 0.564214 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.439712 | 0.3466 | 48.65% | 35.9959% |
| 2020 | 266 | 0.694709 | 0.3685 | 47.74% | 33.6284% |
| 2021 | 347 | 0.802452 | 0.3213 | 55.04% | 28.5636% |
| 2022 | 390 | 0.786584 | 0.3273 | 54.62% | 28.9918% |
| 2023 | 440 | 0.653644 | 0.3746 | 51.36% | 30.9216% |
| 2024 | 453 | 0.554802 | 0.4157 | 49.67% | 32.2534% |
| 2025 | 1514 | 0.592516 | 0.5496 | 35.34% | 51.9203% |

_Wall-clock: 124.1s  bootstrap_iter=1000_
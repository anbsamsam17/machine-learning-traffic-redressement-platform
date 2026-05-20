# A5_HardMining_Curriculum

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "use_hard_example_mining": true,
  "use_curriculum": true
}
```

## Baseline
- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)
- loss=`mse`, dropout=0.025, neurons_factors=[3.0, 2.0, 1.0], lr=0.01, batch=256, activation=elu
- epochs_requested=1250, epochs_trained=1250, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `True`
- use_curriculum: `True`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `False`
- use_flag_recent_year_weighting: `False`
- n_seeds: `1`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **1953/3632** (53.77%)
- Erreur relative p80: **33.4416%**
- R²: **0.622515**
- GEH < 5: **100.0%**
- RMSE: 0.7237  MAE: 0.4356  MAPE: 25.22%
- Median rel. error: 16.62%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.574018,
    0.668884
  ],
  "p80": [
    32.342,
    34.5413
  ],
  "tol_in_pct": [
    52.06,
    55.45
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 87 | 43.5% | 57.8167 | 0.080124 |
| 1k-5k | 1361 | 697 | 51.21% | 39.4389 | 0.358412 |
| 5k-20k | 1618 | 890 | 55.01% | 29.202 | 0.439994 |
| 20k+ | 453 | 279 | 61.59% | 20.6582 | 0.573721 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.441888 | 0.3398 | 48.65% | 34.0345% |
| 2020 | 266 | 0.691897 | 0.3666 | 49.62% | 33.7296% |
| 2021 | 347 | 0.797167 | 0.3249 | 55.62% | 28.3766% |
| 2022 | 390 | 0.785092 | 0.3253 | 54.1% | 29.6005% |
| 2023 | 440 | 0.651563 | 0.375 | 52.5% | 30.1605% |
| 2024 | 453 | 0.554121 | 0.4145 | 50.11% | 31.7308% |
| 2025 | 1514 | 0.593363 | 0.5394 | 37.19% | 48.8937% |

_Wall-clock: 247.4s  bootstrap_iter=1000_
# A5_Curriculum

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "use_curriculum": true
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
- use_flag_recent_year_weighting: `False`
- n_seeds: `1`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **1940/3632** (53.41%)
- Erreur relative p80: **33.5633%**
- R²: **0.622347**
- GEH < 5: **100.0%**
- RMSE: 0.7239  MAE: 0.4398  MAPE: 25.75%
- Median rel. error: 16.97%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.574116,
    0.668552
  ],
  "p80": [
    32.6765,
    34.4502
  ],
  "tol_in_pct": [
    51.71,
    55.18
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 87 | 43.5% | 58.1558 | 0.087165 |
| 1k-5k | 1361 | 698 | 51.29% | 39.2802 | 0.365119 |
| 5k-20k | 1618 | 874 | 54.02% | 29.6249 | 0.435467 |
| 20k+ | 453 | 281 | 62.03% | 20.6358 | 0.568607 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.438659 | 0.3439 | 47.75% | 34.032% |
| 2020 | 266 | 0.691669 | 0.3682 | 48.5% | 33.6604% |
| 2021 | 347 | 0.795097 | 0.3283 | 55.62% | 28.9564% |
| 2022 | 390 | 0.781069 | 0.3304 | 53.08% | 30.165% |
| 2023 | 440 | 0.648014 | 0.3793 | 51.14% | 30.7084% |
| 2024 | 453 | 0.553827 | 0.4181 | 49.01% | 32.1493% |
| 2025 | 1514 | 0.594406 | 0.5442 | 36.13% | 50.1044% |

_Wall-clock: 231.6s  bootstrap_iter=1000_
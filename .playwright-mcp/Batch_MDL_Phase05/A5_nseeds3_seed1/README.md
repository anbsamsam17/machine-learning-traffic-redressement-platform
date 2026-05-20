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
- epochs_requested=1250, epochs_trained=1075, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `False`
- use_curriculum: `False`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `False`
- use_flag_recent_year_weighting: `False`
- n_seeds: `3`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **2207/3632** (60.77%)
- Erreur relative p80: **29.0936%**
- R²: **0.695402**
- GEH < 5: **100.0%**
- RMSE: 0.6501  MAE: 0.3712  MAPE: 21.44%
- Median rel. error: 14.28%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.646856,
    0.741551
  ],
  "p80": [
    28.0345,
    30.1527
  ],
  "tol_in_pct": [
    59.09,
    62.42
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 94 | 47.0% | 61.8409 | 0.090677 |
| 1k-5k | 1361 | 789 | 57.97% | 34.6955 | 0.469894 |
| 5k-20k | 1618 | 990 | 61.19% | 24.7122 | 0.572402 |
| 20k+ | 453 | 334 | 73.73% | 15.4401 | 0.730849 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.611614 | 0.2879 | 54.05% | 25.6668% |
| 2020 | 266 | 0.800808 | 0.2932 | 59.4% | 26.4341% |
| 2021 | 347 | 0.867586 | 0.2621 | 64.27% | 23.1149% |
| 2022 | 390 | 0.865877 | 0.2511 | 65.9% | 21.8959% |
| 2023 | 440 | 0.722986 | 0.3 | 58.64% | 22.9836% |
| 2024 | 453 | 0.598115 | 0.3578 | 56.73% | 27.063% |
| 2025 | 1514 | 0.667671 | 0.4779 | 40.62% | 42.4884% |

_Wall-clock: 551.0s  bootstrap_iter=1000_